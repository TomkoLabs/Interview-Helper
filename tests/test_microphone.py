"""Offline topology, isolation and lifecycle tests; no microphone/model/network use."""

import asyncio
import json
from pathlib import Path
import threading
import time
from types import SimpleNamespace

import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient

from interview_helper import microphone as mic
from interview_helper.app import create_app
from interview_helper.asr import Recognizer
from interview_helper.audio import Capture, Monitor, parse_short_modules, select_monitors
from interview_helper.config import Config, Endpoint
from interview_helper.gateway import Gateway
from interview_helper.session import Session
from interview_helper.storage import SessionStore, transcript_view


def topology():
    data = json.loads((Path(__file__).parent / "fixtures/pipewire_pactl17.json").read_text())
    modules = parse_short_modules(data["modules_short"], data["modules"])
    return [data["sinks"], data["sources"], modules, [], []]


def test_automatic_input_uses_actual_monitor_relationships_and_stable_default():
    data = topology()
    for sink in data[0]:
        sink["state"] = "IDLE"
    selected = mic.select_input(*data, "webcam-input", "analog")
    assert selected.microphone.name == "webcam-input" and selected.reference == "analog"
    assert mic.select_input(*data, "analog-input", "analog", current="webcam-input") == selected
    data[1] = [s for s in data[1] if s["name"] != "webcam-input"]
    assert mic.select_input(*data, "webcam-input", "analog").microphone.name == "analog-input"
    # A stale default may be a monitor; sole physical input still wins.
    assert mic.select_input(*data, "analog.monitor", "analog").microphone.name == "analog-input"
    pb, _ = select_monitors(*data)
    assert {m.name for m in pb} == {"analog.monitor", "hdmi.monitor"}


def test_virtual_duplicate_inputs_and_ambiguous_outputs_fail_closed():
    data = topology()
    for sink in data[0]:
        sink["state"] = "IDLE"
    real = data[1][0]
    for name, props in [
        ("ih-aec-123", {}),
        ("remapped", {"node.virtual": True}),
        ("filtered", {"device.class": "filter"}),
    ]:
        data[1].append(
            dict(
                real,
                name=name,
                index=900 + len(data[1]),
                properties={**real["properties"], **props},
            )
        )
    data[2].append({"index": 99, "name": "module-remap-source", "argument": ""})
    data[1].append(dict(real, name="duplicate", owner_module=99, index=999))
    data[2].append({"index": 100, "name": "libpipewire-module-loopback", "argument": "{}"})
    data[1].append(dict(real, name="native-duplicate", owner_module=100, index=1000))
    data[1] = [s for s in data[1] if s["name"] not in {"webcam-input", "analog-input"}]
    with pytest.raises(mic.MicrophoneUnavailable, match="physical microphone"):
        mic.select_input(*data, "duplicate", "analog")
    data = topology()
    for sink in data[0]:
        sink["state"] = "RUNNING"
    # Monitor readers alone do not make both outputs active references.
    assert mic.select_input(*data, "webcam-input", "analog").reference == "analog"
    data[3] = [{"sink": sink["index"], "corked": False} for sink in data[0]]
    with pytest.raises(mic.MicrophoneUnavailable, match="multiple active"):
        mic.select_input(*data, "webcam-input", "analog")
    data[3][0]["corked"] = True
    assert mic.select_input(*data, "webcam-input", "analog").reference == "hdmi"
    data[3].append({"sink": 999})
    with pytest.raises(mic.MicrophoneUnavailable, match="virtual output"):
        mic.select_input(*data, "webcam-input", "analog")


def graph_fixture(aec):
    def node(id, name, kind):
        return {
            "id": id,
            "type": "PipeWire:Interface:Node",
            "info": {"props": {"node.name": name, "media.class": kind, "object.serial": id + 100}},
        }

    def link(id, source, target, port):
        return {
            "id": id,
            "type": "PipeWire:Interface:Link",
            "info": {
                "output-node-id": source,
                "input-node-id": target,
                "output-port-id": port,
                "state": "active",
            },
        }

    return [
        node(1, "mic", "Audio/Source"),
        node(2, "speaker", "Audio/Sink"),
        node(3, aec.name, "Audio/Source"),
        node(4, aec.name + "-capture", "Stream/Input/Audio"),
        node(5, aec.name + "-reference", "Stream/Input/Audio"),
        {"id": 6, "type": "PipeWire:Interface:Port", "info": {"props": {"port.monitor": True}}},
        link(7, 1, 4, 8),
        link(9, 2, 5, 6),
    ]


@pytest.mark.parametrize(
    "damage", ["reference", "mic", "link", "monitor", "identity", "extra", "reader"]
)
def test_aec_rejects_missing_or_wrong_graph(damage):
    aec = mic.EchoCancel(mic.Selection(Monitor("mic", "Mic", ""), "speaker"))
    data = graph_fixture(aec)
    aec.verify(data)
    args = json.loads(aec.arguments())
    assert args["monitor.mode"] is True
    assert "playback.props" not in args and args["library.name"] == "aec/libspa-aec-webrtc"
    if damage == "reference":
        data.pop(1)
    if damage == "mic":
        data.pop(0)
    if damage == "link":
        data[-1]["info"]["output-node-id"] = 1
    if damage == "monitor":
        data[5]["info"]["props"]["port.monitor"] = False
    if damage == "identity":
        data[1]["info"]["props"]["object.serial"] = 900
    if damage == "extra":
        data.append(
            {
                "id": 10,
                "type": "PipeWire:Interface:Node",
                "info": {"props": {"node.name": aec.name + "-playback"}},
            }
        )
    if damage == "reader":
        data.append(
            {
                "id": 10,
                "type": "PipeWire:Interface:Node",
                "info": {"props": {"node.name": aec.name + "-reader"}},
            }
        )
    with pytest.raises(mic.MicrophoneUnavailable):
        aec.verify(data)


def test_idle_choice_persists_privately_and_existing_install_stays_off(tmp_path):
    c = Config.load(tmp_path / "config.local.toml")
    assert not c.microphone
    with TestClient(create_app(c), base_url="http://127.0.0.1:8787") as client:
        assert '<details id="transcriptPanel" open>' in client.get("/").text
        state = client.get("/api/state").json()
        headers = {"Origin": "http://127.0.0.1:8787", "X-Interview-CSRF": state["csrf"]}
        assert (
            client.post("/api/microphone", json={"enabled": "yes"}, headers=headers).status_code
            == 400
        )
        assert (
            client.post("/api/microphone", json={"enabled": True}, headers=headers).status_code
            == 200
        )
        assert Config.load(tmp_path / "config.local.toml").microphone
        assert c.capture_file.stat().st_mode & 0o777 == 0o600
        assert c.capture_file.parent.stat().st_mode & 0o777 == 0o700
        client.app.state.session.state = "recording"
        assert (
            client.post("/api/microphone", json={"enabled": False}, headers=headers).status_code
            == 409
        )
        client.app.state.session.state = "idle"
    assert c.microphone


@pytest.mark.parametrize("backend", ["chat_completions", "openai_api"])
async def test_microphone_sentinel_stays_saved_but_never_reaches_real_outbound_payloads(
    tmp_path, monkeypatch, backend
):
    c = Config.load(tmp_path / "config.local.toml")
    c.endpoints = [
        Endpoint(
            "fixture",
            "http://fixture.invalid/v1"
            if backend == "chat_completions"
            else "https://api.openai.com/v1",
            "fixture",
            api_key="fixture",
            backend=backend,
        )
    ]
    c.microphone = True
    s = Session(c)
    s.start(replay=True)
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        text = '{"action":"IGNORE"}\n{"done":true}\n'
        events = (
            [{"choices": [{"delta": {"content": text}, "finish_reason": "stop"}]}]
            if backend == "chat_completions"
            else [
                {"type": "response.output_text.delta", "delta": text},
                {"type": "response.completed", "response": {"status": "completed"}},
            ]
        )
        return httpx.Response(
            200,
            text="".join("data: " + json.dumps(e) + "\n\n" for e in events) + "data: [DONE]\n\n",
        )

    await s.controller.gateway.client.aclose()
    s.controller.gateway.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    s.ingest("mic", "Microphone", "MICROPHONE_SECRET_SENTINEL", 2, 3, source_kind="microphone")
    assert s.revision == s.controller.revision == 0 and not s.controller.events
    s.controller.ingest(dict(s.transcript[-1], revision=999))
    assert s.controller.revision == 0
    s.ingest("speaker", "Playback", "Explain a thread safe Java counter.", 0, 1)
    assert s.revision == 1 and s.sequence == 2 and s.controller.revision == 1
    s.controller.submit()
    await asyncio.sleep(0.05)
    s.ingest("mic", "Microphone", "MICROPHONE_SECOND_SENTINEL", 3, 4, source_kind="microphone")
    s.ingest("speaker", "Playback", "Now explain multiple JVMs.", 4, 5)
    await s.shutdown()
    assert requests and all(
        sentinel not in json.dumps(requests)
        for sentinel in ("MICROPHONE_SECRET_SENTINEL", "MICROPHONE_SECOND_SENTINEL")
    )
    data = SessionStore.inspect(c.data_dir, s.store.id)
    assert "MICROPHONE_SECRET_SENTINEL" in data["readable"]
    assert [e["source_kind"] for e in transcript_view(data["events"])] == [
        "playback",
        "microphone",
        "microphone",
        "playback",
    ]
    assert len({e["segment_id"] for e in data["events"]}) == 4

    # Summary uses actual Gateway HTTP serialization too.
    class SummaryGateway(Gateway):
        async def race(self, *args, **kwargs):
            await self.client.aclose()

            def summary_handler(request):
                requests.append(json.loads(request.content))
                text = '{"action":"NEW","question":"Summary","developing":false}\n{"text":"Playback summary."}\n{"done":true}\n'
                events = (
                    [{"choices": [{"delta": {"content": text}, "finish_reason": "stop"}]}]
                    if backend == "chat_completions"
                    else [
                        {"type": "response.output_text.delta", "delta": text},
                        {"type": "response.completed", "response": {"status": "completed"}},
                    ]
                )
                return httpx.Response(
                    200,
                    text="".join("data: " + json.dumps(e) + "\n\n" for e in events)
                    + "data: [DONE]\n\n",
                )

            self.client = httpx.AsyncClient(transport=httpx.MockTransport(summary_handler))
            return await super().race(*args, **kwargs)

    monkeypatch.setattr("interview_helper.summary.Gateway", SummaryGateway)
    from interview_helper.summary import summarize

    c.microphone = c.microphone_context = True  # explicit live consent never extends summaries
    await summarize(c, s.store.id)
    assert all(
        sentinel not in json.dumps(requests)
        for sentinel in ("MICROPHONE_SECRET_SENTINEL", "MICROPHONE_SECOND_SENTINEL")
    )


def test_combined_continuous_view_is_chronological_and_legacy_readable(tmp_path):
    store = SessionStore(tmp_path, {"microphone": True})

    def e(i, start, kind):
        return dict(
            type="transcript",
            segment_id=str(i),
            revision=i,
            sequence=i,
            source_kind=kind,
            source=kind,
            source_name="Long hardware name",
            start=start,
            end=start + 1,
            text=f"{kind} sentence {i}.",
        )

    store.append(e(1, 4, "playback"))
    store.append(e(2, 1, "microphone"))
    text = (store.path / "transcript.txt").read_text()
    assert text.index("[00:01.00]") < text.index("[00:04.00]") and "Microphone: microphone" in text
    store.append(e(3, 5, "playback"))
    store.close()
    text = SessionStore.inspect(tmp_path, store.id)["readable"]
    assert "Long hardware" not in text and "Playback: playback" in text
    assert text == (store.path / "transcript.txt").read_text()


async def test_priority_and_native_mic_timeout_do_not_release_busy_model(tmp_path):
    r = Recognizer(Config.load(tmp_path / "config.local.toml"))
    await r.lock.acquire()
    with pytest.raises(RuntimeError, match="priority"):
        await r.infer(SimpleNamespace(process_iter=lambda: None), True)
    r.lock.release()
    release = threading.Event()
    task = asyncio.create_task(r.infer(SimpleNamespace(process_iter=lambda: release.wait(4)), True))
    try:
        with pytest.raises(RuntimeError, match="1.5s"):
            await task
        assert r.microphone_overloaded and r.lock.locked()
    finally:
        release.set()
        await asyncio.sleep(0.03)
    assert not r.lock.locked()
    assert await r.infer(SimpleNamespace(process_iter=lambda: "playback")) == "playback"
    assert not r.microphone_overloaded
    assert (
        await r.infer(SimpleNamespace(process_iter=lambda: "recovered microphone"), True)
        == "recovered microphone"
    )


async def test_separate_asr_histories_and_bounded_queues(tmp_path, monkeypatch):
    import interview_helper.asr as asr

    histories = []

    class Online:
        def __init__(self, backend):
            self.audio_buffer = []
            histories.append(self)

        def init(self, offset):
            self.offset = offset
            self.audio_buffer = []

        def insert_audio_chunk(self, block):
            self.audio_buffer.extend(block)

        def process_iter(self):
            return [], None

        def finish(self):
            return [], None

        def get_buffer(self):
            return SimpleNamespace(text="")

    monkeypatch.setattr(asr, "OnlineASRProcessor", Online)
    r = Recognizer(Config.load(tmp_path / "missing"))

    async def emit(*_):
        pass

    for microphone in [False, True]:
        capture = Capture(
            Monitor("s", "S", ""), lambda *_: None, time.monotonic(), microphone=microphone
        )
        assert capture.queue.maxsize == (20 if microphone else 300)
        capture.stopping = True
        for i in range(11):
            capture.queue.put_nowait((i / 10, np.full(1600, 0.1, dtype=np.float32)))
        await r.run_source(capture, emit, lambda *_: None)
    assert len(histories) == 2 and histories[0] is not histories[1]


async def test_missing_aec_is_optional_and_shutdown_bounded(tmp_path, monkeypatch):
    from test_session import NoQuestion

    c = Config.load(tmp_path / "missing")
    c.microphone = True
    s = Session(c)
    s.start(replay=True)
    await s.controller.gateway.close()
    s.controller.gateway = NoQuestion()
    s.recognizer = SimpleNamespace(microphone_overloaded=False)

    async def unavailable(*_):
        raise mic.MicrophoneUnavailable("WebRTC unavailable")

    monkeypatch.setattr(mic, "discover_input", unavailable)
    worker = mic.MicrophoneWorker(s)
    worker.task = asyncio.create_task(worker.run())
    s.microphone_worker = worker
    await asyncio.sleep(0.02)
    assert s.state == "recording" and s.microphone_state["state"] == "unavailable"
    s.ingest("p", "Playback", "Playback still works.", 0, 1)
    await asyncio.wait_for(s.shutdown(), 1)
    data = SessionStore.inspect(c.data_dir, s.store.id)
    assert any(e["type"] == "outage" and e["source_kind"] == "microphone" for e in data["events"])
    assert "Playback still works." in data["readable"] and s.state == "ended"


async def test_replay_explicitly_skips_microphone(tmp_path, monkeypatch):
    from interview_helper.cli import replay

    sessions = []

    class ObservedSession(Session):
        def start(self, **kwargs):
            sessions.append(self)
            return super().start(**kwargs)

    monkeypatch.setattr("interview_helper.session.Session", ObservedSession)
    c = Config.load(tmp_path / "missing")
    c.microphone = c.microphone_context = True  # replay remains playback-only
    records = tmp_path / "replay.json"
    records.write_text(
        json.dumps(
            [
                {"at": 0, "text": "MIC_REPLAY_SENTINEL", "source_kind": "microphone"},
                {"at": 0, "text": "Explain Java concurrency."},
            ]
        )
    )
    await replay(c, records, speed=1000)
    data = SessionStore.inspect(c.data_dir, sessions[0].store.id)
    assert "MIC_REPLAY_SENTINEL" not in json.dumps(data)
    assert sessions[0].revision == 1


async def test_pending_native_mic_cannot_load_another_model(tmp_path):
    c = Config.load(tmp_path / "missing")
    s = Session(c)
    pending = asyncio.create_task(asyncio.sleep(0.01))
    s.recognizer = SimpleNamespace(microphone_job=pending)
    with pytest.raises(ValueError, match="draining"):
        s.start(replay=True)
    await pending


async def test_reference_switch_recreates_only_optional_resources(tmp_path, monkeypatch):
    from test_session import NoQuestion

    c = Config.load(tmp_path / "missing")
    s = Session(c)
    s.start(replay=True)
    await s.controller.gateway.close()
    s.controller.gateway = NoQuestion()
    first = mic.Selection(Monitor("mic", "Mic", ""), "speaker-a")
    second = mic.Selection(Monitor("mic", "Mic", ""), "speaker-b")
    wanted = [first]
    ownership = []

    class AEC:
        def __init__(self, selection):
            self.selection = selection
            ownership.append(("create", selection.reference))

        async def start(self):
            return Monitor("clean", "Microphone", "")

        async def check(self, require_reader=False):
            pass

        async def stop(self):
            ownership.append(("stop", self.selection.reference))

    class Reader:
        def __init__(self, *args, **kwargs):
            self.stopping = False

        async def start(self):
            pass

        def discard_buffer(self):
            pass

        async def stop(self):
            self.stopping = True

    class ASR:
        microphone_overloaded = False

        async def run_source(self, capture, *args):
            while not capture.stopping:
                await asyncio.sleep(0.01)

    async def discover(current):
        return wanted[0]

    monkeypatch.setattr(mic, "discover_input", discover)
    monkeypatch.setattr(mic, "EchoCancel", AEC)
    monkeypatch.setattr("interview_helper.audio.Capture", Reader)
    s.recognizer = ASR()
    worker = mic.MicrophoneWorker(s)
    s.microphone_worker = worker
    worker.task = asyncio.create_task(worker.run())
    await asyncio.sleep(0.03)
    wanted[0] = second
    await asyncio.sleep(1.1)
    assert ownership[:3] == [
        ("create", "speaker-a"),
        ("stop", "speaker-a"),
        ("create", "speaker-b"),
    ]
    assert s.state == "recording" and s.revision == 0
    s.ingest("playback", "Playback", "Original path unaffected.", 0, 1)
    await asyncio.wait_for(s.shutdown(), 1)
    assert ownership[-1] == ("stop", "speaker-b")
    assert any(
        e["type"] == "outage" for e in SessionStore.inspect(c.data_dir, s.store.id)["events"]
    )


async def test_stop_racing_natural_exit_finishes_one_shielded_flush(tmp_path):
    s = Session(Config.load(tmp_path / "missing"))
    s.state = "stopping"
    worker = mic.MicrophoneWorker(s)
    entered = asyncio.Event()
    release = asyncio.Event()
    calls = []

    async def cleanup(flush=False):
        calls.append(flush)
        entered.set()
        await release.wait()

    worker.cleanup = cleanup
    worker.task = asyncio.create_task(worker.run())
    await entered.wait()
    stopped = asyncio.create_task(worker.stop())
    await asyncio.sleep(0.01)
    assert not stopped.done() and calls == [True]
    release.set()
    await asyncio.wait_for(stopped, 0.1)
    assert s.microphone_state["state"] == "stopped"


async def test_microphone_history_cannot_hide_playback_review_state(tmp_path):
    from test_session import NoQuestion

    c = Config.load(tmp_path / "missing")
    s = Session(c)
    s.start(replay=True)
    await s.controller.gateway.close()
    s.controller.gateway = NoQuestion()
    s.ingest("p", "Playback", "Explain a Java counter.", 0, 1)
    for i in range(201):
        s.ingest("m", "Microphone", "Local-only remark.", i + 2, i + 3, source_kind="microphone")
    assert len(s.view()["transcript"]) == 200
    assert not any(e["source_kind"] == "playback" for e in s.view()["transcript"])
    assert s.view()["playback_revision"] == 1 and s.controller.review_now()
    js = (Path(__file__).parents[1] / "src/interview_helper/static/app.js").read_text()
    assert 'data.state !== "recording" || !data.playback_revision' in js
    await s.shutdown()


async def test_provisional_state_has_no_reserved_playback_device_name(tmp_path, monkeypatch):
    c = Config.load(tmp_path / "missing")
    s = Session(c)
    s.provisional["microphone"] = "Playback from a monitor literally named microphone"
    worker = mic.MicrophoneWorker(s)
    worker.current = "physical-mic"
    worker.selection = mic.Selection(Monitor("physical-mic", "Mic", ""), "speaker")
    worker.valid = True

    async def discovered(*_):
        return worker.selection

    class AEC:
        async def check(self, require_reader=False):
            pass

        async def stop(self):
            pass

    worker.aec = AEC()
    monkeypatch.setattr(mic, "discover_input", discovered)
    await worker.emit([], "LOCAL_ONLY_PROVISIONAL", False)
    assert s.provisional["microphone"].startswith("Playback")
    assert s.microphone_state["provisional"] == "LOCAL_ONLY_PROVISIONAL"
    await worker.cleanup()
    assert s.provisional["microphone"].startswith("Playback")
    assert "provisional" not in s.microphone_state


@pytest.mark.parametrize("stop", ["eof", "terminate"])
def test_owner_pipe_and_termination_release_owned_child(tmp_path, stop):
    import os
    import subprocess
    import sys

    child = tmp_path / "pw-cli"
    child.write_text("""#!/usr/bin/env python3
import os, signal, time
from pathlib import Path
signal.signal(signal.SIGTERM, signal.SIG_IGN)
Path(os.environ['IH_TEST_CHILD_PID']).write_text(str(os.getpid()))
time.sleep(4)
""")
    child.chmod(0o755)
    pid_file = tmp_path / "child.pid"
    env = dict(
        os.environ,
        PATH=str(tmp_path) + os.pathsep + os.environ["PATH"],
        IH_TEST_CHILD_PID=str(pid_file),
        PYTHONPATH=str(Path(__file__).parents[1] / "src"),
    )
    process = subprocess.Popen(
        [sys.executable, "-m", "interview_helper.aec_owner", "{}"],
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    try:
        for _ in range(100):
            if pid_file.exists():
                break
            time.sleep(0.01)
        assert pid_file.exists()
        pid = int(pid_file.read_text())
        if stop == "eof":
            process.stdin.close()
        else:
            process.terminate()
        assert process.wait(timeout=2) == 0
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        process.stderr.close()
        if not process.stdin.closed:
            process.stdin.close()
