import asyncio
import pytest
from interview_helper.config import Config
from interview_helper.session import Session
from interview_helper.gateway import Outcome
from interview_helper.storage import SessionStore


class NoQuestion:
    async def race(self, *args, **kwargs):
        return Outcome("fixture", {"action": "IGNORE"}, [], None, 0.01)

    async def close(self):
        pass


@pytest.mark.asyncio
async def test_backend_survives_views_and_final_flush(tmp_path):
    c = Config.load(tmp_path / "config.local.toml")
    s = Session(c)
    s.start(replay=True)
    await s.controller.gateway.close()
    s.controller.gateway = NoQuestion()
    for i in range(10):
        s.ingest("source", "Playback", f"conversation {i}", i, i + 1)
        assert s.view()["state"] == "recording"
    await s.shutdown()
    data = SessionStore.inspect(c.data_dir, s.store.id)
    assert len(data["events"]) == 10 and data["metadata"]["status"] == "ended"
    elapsed = s.view()["elapsed"]
    await asyncio.sleep(0.02)
    assert s.view()["elapsed"] == elapsed


@pytest.mark.asyncio
async def test_save_failure_pauses_and_retry_retains_event(tmp_path, monkeypatch):
    c = Config.load(tmp_path / "config.local.toml")
    s = Session(c)
    s.start(replay=True)
    await s.controller.gateway.close()
    s.controller.gateway = NoQuestion()
    original = s.store.append

    def fail(*_):
        raise OSError("disk full")

    monkeypatch.setattr(s.store, "append", fail)
    with pytest.raises(OSError):
        s.ingest("s", "Playback", "Must not be lost", 0, 1)
    assert s.state == "save_failed" and len(s.unsaved) == 1
    assert s.controller.revision == 0
    monkeypatch.setattr(s.store, "append", original)
    s.retry_save()
    await s.shutdown()
    data = SessionStore.inspect(c.data_dir, s.store.id)
    assert data["events"][0]["text"] == "Must not be lost"


@pytest.mark.asyncio
async def test_shutdown_while_loading(tmp_path, monkeypatch):
    import interview_helper.session as module

    class Slow:
        def __init__(self, c):
            pass

        async def load(self):
            await asyncio.sleep(0.05)

    monkeypatch.setattr(module, "Recognizer", Slow)
    c = Config.load(tmp_path / "config.local.toml")
    s = Session(c)
    s.start()
    await s.shutdown()
    assert s.state == "ended" and not s.captures


@pytest.mark.asyncio
async def test_startup_failure_does_not_fallback(tmp_path, monkeypatch):
    import interview_helper.session as module

    class Broken:
        def __init__(self, c):
            pass

        async def load(self):
            raise RuntimeError("CUDA unavailable; no fallback")

    monkeypatch.setattr(module, "Recognizer", Broken)
    c = Config.load(tmp_path / "config.local.toml")
    s = Session(c)
    s.start()
    await s.start_task
    assert s.state == "failed" and s.store.closed
    assert s.store.metadata["status"] == "startup_failed"
