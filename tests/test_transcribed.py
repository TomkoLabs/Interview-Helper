import fcntl
from pathlib import Path
import tomllib
import pytest
from fastapi.testclient import TestClient
from interview_helper.app import create_app
from interview_helper.config import Config
from interview_helper.migration import migrate, files
from interview_helper.storage import SessionStore, readable, read_journal, rebuild_readable


def event(n, text, **changes):
    return dict(
        type="transcript",
        segment_id=str(n),
        revision=n,
        source="monitor-a",
        source_name="Long hardware device name",
        start=n,
        end=n + 0.5,
        text=text,
        **changes,
    )


def test_readable_fragments_revisions_gaps_and_sources(tmp_path):
    s = SessionStore(tmp_path)
    records = [
        event(1, "Sure, let me go one by"),
        event(2, "one, first would be the"),
        event(3, "JDK, which is the"),
        event(4, "development kit."),
    ]
    for e in records:
        s.append(e)
        assert read_journal(s.path / "transcript.jsonl")[0][-1] == e
    live = (s.path / "transcript.txt").read_text()
    assert "one by one, first would be the JDK, which is the development kit." in live
    assert live.count("[") == 1 and "hardware" not in live
    gap = {"type": "gap", "at": 4.8, "source": "monitor-a", "reason": "Audio disconnected"}
    s.append(gap)
    s.append(event(5, "Playback resumed."))
    revised = {**records[-1], "text": "development toolkit.", "revision": 6}
    s.append(revised)
    s.append({**event(7, "Second captured source."), "source": "monitor-b"})
    s.close()
    data = SessionStore.inspect(tmp_path, s.id)
    text = (s.path / "transcript.txt").read_text()
    assert text == data["readable"]
    assert "toolkit." in text and "development kit." not in text
    assert text.index("[CAPTURE GAP]") < text.index("Playback resumed")
    assert "Second captured source" in text and "monitor-a" not in text
    assert data["events"][0]["source_name"] == "Long hardware device name"
    assert (s.path / "transcript.txt").stat().st_mode & 0o777 == 0o600


def test_partial_recovery_preserves_journal(tmp_path):
    s = SessionStore(tmp_path)
    s.append(event(1, "Preserve these exact words"))
    s.close()
    journal = s.path / "transcript.jsonl"
    journal.write_bytes(journal.read_bytes() + b'{"partial"')
    before = journal.read_bytes()
    text = rebuild_readable(s.path)
    assert "RECOVERY" in text and journal.read_bytes() == before


@pytest.mark.asyncio
async def test_readable_failure_does_not_duplicate_journal_or_stop_saving(tmp_path, monkeypatch):
    from interview_helper.session import Session
    from test_session import NoQuestion

    c = Config.load(tmp_path / "config.local.toml")
    session = Session(c)
    session.start(replay=True)
    await session.controller.gateway.close()
    session.controller.gateway = NoQuestion()
    original = session.store._sync

    def fail_view(f):
        if f is session.store.text:
            raise OSError("view failure")
        original(f)

    monkeypatch.setattr(session.store, "_sync", fail_view)
    session.ingest("a", "Playback", "one", 0, 1)
    session.ingest("a", "Playback", "two", 1, 2, final=True)
    assert session.state == "recording" and not session.unsaved
    assert session.view()["readable_error"]
    await session.shutdown()
    assert session.state == "ended" and not session.view()["readable_error"]
    data = SessionStore.inspect(c.data_dir, session.store.id)
    assert len(data["events"]) == 2 and "one two" in data["readable"]


def test_final_view_failure_visible_and_recoverable(tmp_path, monkeypatch):
    import interview_helper.storage as storage

    s = SessionStore(tmp_path)
    s.append(event(1, "durable"))
    monkeypatch.setattr(
        storage, "rebuild_readable", lambda _: (_ for _ in ()).throw(OSError("full"))
    )
    s.close()
    assert s.closed and s.view_error
    data = SessionStore.inspect(tmp_path, s.id)
    assert data["metadata"]["readable_error"] and "durable" in data["readable"]


def legacy(tmp_path):
    config = tmp_path / "config.local.toml"
    config.write_text(
        '# Keep settings\ndata_dir = ".local/sessions"\nport = 8787\n[asr]\ndevice = "cpu"\n'
    )
    s = SessionStore(tmp_path / ".local/sessions")
    s.append(event(1, "Exact recorded words."))
    s.append(
        {"type": "hint", "id": "one", "question": "Why?", "answer": "Separate hint"}, hint=True
    )
    s.close()
    (s.path / "transcript.txt").write_text("old device-labelled view")
    return config, s


def test_migration_verified_idempotent_private_and_saved_sessions(tmp_path):
    config, s = legacy(tmp_path)
    original, before = config.read_bytes(), files(s.path)
    result = migrate(config)
    assert result["sessions"] == 1 and files(s.path) == before
    assert Path(result["config_backup"]).read_bytes() == original
    raw = tomllib.loads(config.read_text())
    assert raw["data_dir"] == "Transcribed" and raw["asr"]["device"] == "cpu"
    target = tmp_path / "Transcribed" / s.id
    assert (target / "transcript.pre-0.1.8.txt").read_text() == "old device-labelled view"
    assert "Exact recorded words." in (target / "transcript.txt").read_text()
    assert "device-labelled" not in (target / "transcript.txt").read_text()
    assert all(
        p.stat().st_mode & 0o777 == (0o700 if p.is_dir() else 0o600)
        for p in [target, *target.rglob("*")]
    )
    first = files(target)
    (target / "transcript.txt").chmod(0o644)
    assert migrate(config)["config_backup"] is None and files(target) == first
    assert (target / "transcript.txt").stat().st_mode & 0o777 == 0o600
    c = Config.load(config)
    with TestClient(create_app(c), base_url="http://127.0.0.1:8787") as client:
        client.get("/")
        assert client.get("/api/sessions").json()[0]["id"] == s.id
        detail = client.get("/api/sessions/" + s.id).json()
        assert detail["hints"][0]["answer"] == "Separate hint"
        download = client.get("/api/sessions/" + s.id + "/transcript")
        assert download.status_code == 200 and "Exact recorded words." in download.text
        assert "Separate hint" not in download.text


def test_migration_conflict_preserves_all_originals_and_config(tmp_path):
    config, s = legacy(tmp_path)
    original = config.read_bytes()
    target = tmp_path / "Transcribed" / s.id
    target.mkdir(parents=True)
    (target / "metadata.json").write_text("conflict")
    with pytest.raises(ValueError, match="conflict"):
        migrate(config)
    assert config.read_bytes() == original and (target / "metadata.json").read_text() == "conflict"
    assert s.path.exists()


def test_migration_lock_custom_directory_and_symlink_refusal(tmp_path):
    config, s = legacy(tmp_path)
    with (tmp_path / ".local/runtime.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_SH)
        with pytest.raises(ValueError, match="Stop IH"):
            migrate(config)
    (s.path / "escape").symlink_to(config)
    with pytest.raises(ValueError, match="symlink"):
        migrate(config)
    config.write_text('data_dir = "custom"\n')
    before = config.read_bytes()
    assert migrate(config)["status"] == "custom data_dir preserved"
    assert config.read_bytes() == before
    assert Config.load(tmp_path / "absent.toml").data_dir == tmp_path / "Transcribed"


def test_readable_does_not_rewrite_or_mix_hint_text():
    text = readable(
        [
            event(1, "This has odd grammar"),
            event(2, ", captured exactly."),
            {"type": "hint", "text": "INVENTED"},
        ]
    )
    assert "This has odd grammar, captured exactly." in text and "INVENTED" not in text


def test_copy_failure_never_switches_config_or_changes_original(tmp_path, monkeypatch):
    import interview_helper.migration as migration

    config, s = legacy(tmp_path)
    original, hashes = config.read_bytes(), files(s.path)
    monkeypatch.setattr(
        migration.shutil, "copytree", lambda *a, **kw: (_ for _ in ()).throw(OSError("disk full"))
    )
    with pytest.raises(OSError):
        migrate(config)
    assert config.read_bytes() == original and files(s.path) == hashes
    assert not list((tmp_path / "Transcribed").iterdir())
