import json
import pytest
from interview_helper.storage import SessionStore, read_journal, transcript_view
from interview_helper.protocol import Parser, ProtocolError
from interview_helper.audio import select_monitors
from interview_helper.vendor.local_agreement import HypothesisBuffer
from interview_helper.vendor.timed import ASRToken


def test_stable_prefix_and_revision():
    b = HypothesisBuffer()
    b.insert([ASRToken(0, 0.4, " Java"), ASRToken(0.4, 0.8, " locks")], 0)
    assert b.flush() == []
    b.insert([ASRToken(0, 0.4, " Java"), ASRToken(0.4, 0.8, " memory")], 0)
    assert [t.text for t in b.flush()] == [" Java"]
    assert [t.text for t in b.buffer] == [" memory"]


def test_storage_recovery_partial_tail_and_revision(tmp_path):
    s = SessionStore(tmp_path)
    e = dict(
        type="transcript",
        segment_id="one",
        source="a",
        source_name="Speakers",
        revision=1,
        start=0,
        end=1,
        text="hello",
    )
    s.append(e)
    s.append(dict(e, revision=2, text="hello world"))
    s.close()
    with (s.path / "transcript.jsonl").open("ab") as f:
        f.write(b'{"partial"')
    data = SessionStore.inspect(tmp_path, s.id)
    assert data["partial_tail"]
    assert transcript_view(data["events"])[0]["text"] == "hello world"
    assert (s.path.stat().st_mode & 0o777) == 0o700
    assert ((s.path / "transcript.jsonl").stat().st_mode & 0o777) == 0o600


def test_corrupt_middle_rejected(tmp_path):
    p = tmp_path / "events"
    p.write_bytes(b"{bad}\n{}\n")
    with pytest.raises(json.JSONDecodeError):
        read_journal(p)


def test_storage_disk_error(tmp_path, monkeypatch):
    s = SessionStore(tmp_path)
    monkeypatch.setattr(s, "_sync", lambda _: (_ for _ in ()).throw(OSError("full")))
    with pytest.raises(OSError):
        s.append({"type": "gap"})
    assert (s.path / "transcript.jsonl").read_bytes() == b""
    s.close()


@pytest.mark.parametrize("action", ["WAIT", "IGNORE", "NEW", "UPDATE"])
def test_protocol_stream_boundaries(action):
    header = {"action": action}
    if action in {"NEW", "UPDATE"}:
        header.update(question="Explain mutexes", developing=False)
    records = [header]
    if action in {"NEW", "UPDATE"}:
        records.append({"text": "A mutex protects shared state."})
    records.append({"done": True})
    p = Parser()
    for c in "\n".join(map(json.dumps, records)):
        p.feed(c)
    p.finish()
    assert p.done and p.header["action"] == action


@pytest.mark.parametrize(
    "body",
    [
        '{"action":"NEW","question":"why","developing":false}\n',
        "not JSON\n",
        '{"action":"WAIT"}\n{"text":"no"}\n',
        '{"action":"NEW","question":"why","developing":false}\n{"text":"<think>secret"}\n',
        '{"action":"WAIT"}\n{"done":true}\n{"text":"later"}\n',
        '{"action":"WAIT"}\n{"done":1}\n',
        '{"action":[]}\n{"done":true}\n',
    ],
)
def test_bad_protocol(body):
    with pytest.raises(ProtocolError):
        p = Parser()
        p.feed(body)
        p.finish()


def topology():
    sinks = [
        {"index": 1, "name": "virtual", "monitor_source": "virtual.monitor"},
        {"index": 2, "name": "speakers", "monitor_source": "speakers.monitor"},
    ]
    sources = [
        {"index": 11, "name": "virtual.monitor", "monitor_of_sink": 1},
        {"index": 12, "name": "speakers.monitor", "monitor_of_sink": 2},
        {"index": 13, "name": "microphone", "monitor_of_sink": 4294967295},
    ]
    modules = [
        {"index": 5, "name": "module-loopback", "argument": "source=virtual.monitor sink=speakers"}
    ]
    return sinks, sources, modules


def test_loopback_dedup_and_independent_output():
    sinks, sources, modules = topology()
    monitors, _ = select_monitors(sinks, sources, modules, [{"sink": 2, "owner_module": 5}], [])
    assert [m.name for m in monitors] == ["virtual.monitor"]
    monitors, _ = select_monitors(sinks, sources, modules, [{"sink": 2, "owner_module": 7}], [])
    assert [m.name for m in monitors] == ["speakers.monitor"]


def test_include_exclude_never_microphone():
    s, src, m = topology()
    monitors, _ = select_monitors(s, src, m, [], [], ["*"], ["virtual*"])
    assert [x.name for x in monitors] == ["speakers.monitor"]


def test_combine_dedup():
    s, src, _ = topology()
    m = [
        {"index": 5, "name": "module-combine-sink", "argument": "sink_name=virtual slaves=speakers"}
    ]
    monitors, _ = select_monitors(s, src, m, [], [])
    assert [x.name for x in monitors] == ["virtual.monitor"]


def test_pulseaudio17_short_modules():
    from interview_helper.audio import parse_short_modules

    assert parse_short_modules("5\tmodule-loopback\tsource=a sink=b\t\n") == [
        {"index": 5, "name": "module-loopback", "argument": "source=a sink=b"}
    ]
    with pytest.raises(ValueError):
        parse_short_modules("unexpected format")


def test_forwarding_cycle_keeps_audio_visible():
    sinks, sources, modules = topology()
    modules.append(
        {"index": 6, "name": "module-loopback", "argument": "source=speakers.monitor sink=virtual"}
    )
    monitors, warnings = select_monitors(sinks, sources, modules, [], [])
    assert {m.name for m in monitors} == {"virtual.monitor", "speakers.monitor"}
    assert "cycle" in warnings[0]


@pytest.mark.asyncio
async def test_audio_backlog_stops_visibly_without_dropping_queued_blocks():
    import asyncio
    import time
    from interview_helper.audio import Capture, Monitor

    class Process:
        returncode = None
        stdout = asyncio.StreamReader()

        def terminate(self):
            self.returncode = -15

        async def wait(self):
            return self.returncode

    statuses = []
    capture = Capture(
        Monitor("speaker.monitor", "Speakers", "speaker"),
        lambda *v: statuses.append(v),
        time.monotonic(),
    )
    capture.process = Process()
    for i in range(300):
        capture.queue.put_nowait((i, b"preserved"))
    capture.process.stdout.feed_data(bytes(6400))
    await capture._read()
    assert capture.stopping and capture.queue.qsize() == 300
    assert capture.queue.get_nowait() == (0, b"preserved")
    assert statuses[0][1] == "failed" and "30s" in statuses[0][2]
