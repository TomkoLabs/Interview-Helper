"""De-identified offline recovery/consent contracts; no real interview or paid calls."""

import asyncio
from copy import deepcopy
import json
import importlib.util
from pathlib import Path
import threading
import time
from types import SimpleNamespace

import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient

from interview_helper.app import create_app
from interview_helper.asr import Recognizer, RecognitionPending
from interview_helper.audio import Capture, Monitor
from interview_helper.coding import apply_reference
from interview_helper.config import Config, Endpoint
from interview_helper.gateway import Gateway, Outcome
from interview_helper.microphone import (
    EchoCancel,
    MicrophoneUnavailable,
    MicrophoneWorker,
    Selection,
)
from interview_helper.protocol import Parser, ProtocolError
from interview_helper.session import Session
from interview_helper.storage import SessionStore, readable
from test_live_review import setup, ingest, review, answer
from test_microphone import graph_fixture


def reader_graph(aec):
    graph = graph_fixture(aec)
    graph.extend(
        [
            {
                "id": 20,
                "type": "PipeWire:Interface:Node",
                "info": {"props": {"node.name": aec.name + "-reader"}},
            },
            {
                "id": 21,
                "type": "PipeWire:Interface:Link",
                "info": {
                    "output-node-id": 3,
                    "input-node-id": 20,
                    "output-port-id": 22,
                    "state": "active",
                },
            },
        ]
    )
    return graph


async def test_delayed_reader_links_settle_without_accepting_unsafe_audio(tmp_path, monkeypatch):
    import interview_helper.microphone as mic

    worker = MicrophoneWorker(Session(Config.load(tmp_path / "none")))
    aec = EchoCancel(Selection(Monitor("mic", "Mic", ""), "speaker"))
    ready = reader_graph(aec)
    delayed = deepcopy(ready[:-1])
    calls = []

    async def graph():
        calls.append(1)
        return delayed if len(calls) < 3 else ready

    monkeypatch.setattr(mic, "graph", graph)
    worker.aec = aec
    worker.capture = SimpleNamespace(stopping=False)
    with pytest.raises(MicrophoneUnavailable, match="no links"):
        aec.verify(delayed, require_reader=True)
    await worker.settle_reader()
    assert len(calls) == 3
    wrong = deepcopy(ready)
    wrong[-1]["info"]["output-node-id"] = 1
    with pytest.raises(MicrophoneUnavailable, match="unsafe source"):
        aec.verify(wrong, require_reader=True)
    with pytest.raises(MicrophoneUnavailable, match="node not ready"):
        aec.verify(ready[:-2], require_reader=True)


def test_multiple_clean_channels_and_unrelated_churn_preserve_identity():
    aec = EchoCancel(Selection(Monitor("mic", "Mic", ""), "speaker"))
    graph = reader_graph(aec)
    graph.append(
        {
            "id": 23,
            "type": "PipeWire:Interface:Link",
            "info": {
                "output-node-id": 3,
                "input-node-id": 20,
                "output-port-id": 24,
                "state": "paused",
            },
        }
    )
    aec.verify(graph, True)
    graph.insert(
        0,
        {
            "id": 99,
            "type": "PipeWire:Interface:Node",
            "info": {"props": {"node.name": "unrelated", "object.serial": 100}},
        },
    )
    aec.verify(graph, True)
    assert aec.selection.same_devices(
        Selection(Monitor("mic", "Changed human label", ""), "speaker")
    )
    assert not aec.selection.same_devices(Selection(Monitor("mic2", "Mic", ""), "speaker"))
    graph[2]["info"]["props"]["object.serial"] = 999
    with pytest.raises(MicrophoneUnavailable, match="changed"):
        aec.verify(graph, True)


async def test_repeated_outage_records_one_start_real_recovery_and_unresolved_end(tmp_path):
    s = Session(Config.load(tmp_path / "none"))
    s.store = SessionStore(s.config.data_dir, {"microphone": True})
    s.started = time.monotonic() - 10
    s.state = "recording"
    w = MicrophoneWorker(s)
    w.valid = True
    for _ in range(48):
        w.gap("Reader links not ready")
    assert len(w.diagnostics) == 1 and not s.notices
    w.status("listening", {"lag_seconds": 0.1})
    assert not w.outage and s.microphone_state["state"] == "listening"
    w.gap("Recognition continuity lost", "recognition")
    w.status("listening", {"lag_seconds": 0.1})
    assert w.outage  # capture availability alone does not repair recognition
    w.status("ready", {"inference_seconds": 0.2})
    assert not w.outage
    w.gap("Reference disconnected")
    s.state = "stopping"
    await w.run()
    s.store.close()
    events = SessionStore.inspect(s.config.data_dir, s.store.id)["events"]
    phases = [e["phase"] for e in events if e["type"] == "outage"]
    assert phases == ["start", "recovered", "start", "recovered", "start", "unresolved"]
    text = (s.store.path / "transcript.txt").read_text()
    assert text.count("Reader links not ready") == 1 and "00:10." in text and "UNRESOLVED" in text
    assert len([e for e in events if e["type"] == "microphone_diagnostic"]) <= 1


def test_legacy_warning_export_deduplicates_without_rewriting_or_inventing_time():
    gap = {"type": "gap", "source_kind": "microphone", "reason": "Old reader failure"}
    old = [dict(gap) for _ in range(48)]
    before = deepcopy(old)
    text = readable(old)
    assert text.count("Old reader failure") == 1 and "[00:" not in text and old == before


def test_unverified_worker_cannot_report_recovery(tmp_path):
    s = Session(Config.load(tmp_path / "none"))
    w = MicrophoneWorker(s)
    w.gap("Physical reference changed")
    w.status("ready", {})
    w.status("listening", {})
    assert w.outage and s.microphone_state["state"] == "unavailable"


def test_diagnostic_filters_graph_without_collecting_unrelated_properties():
    spec = importlib.util.spec_from_file_location(
        "mic_diag", Path(__file__).parents[1] / "scripts/microphone_diagnostics.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    aec = EchoCancel(Selection(Monitor("mic", "Mic", ""), "speaker"))
    graph = reader_graph(aec)
    graph[0]["info"]["props"]["private.extra"] = "DO_NOT_EXPORT"
    graph.append(
        {
            "id": 999,
            "type": "PipeWire:Interface:Node",
            "info": {"props": {"node.name": "UNRELATED_APPLICATION_NAME"}},
        }
    )
    encoded = json.dumps(module.filtered_graph(graph))
    assert aec.name in encoded and "mic" in encoded and "active" in encoded
    assert "DO_NOT_EXPORT" not in encoded and "UNRELATED_APPLICATION_NAME" not in encoded


async def test_microphone_queue_pressure_keeps_reader_and_marks_actual_loss():
    events = []
    c = Capture(
        Monitor("clean", "Mic", ""),
        lambda *args: events.append(args),
        time.monotonic(),
        microphone=True,
    )
    stream = asyncio.StreamReader()
    c.process = SimpleNamespace(stdout=stream, returncode=0)
    stream.feed_data(np.zeros(1600 * 25, dtype="<f4").tobytes())
    stream.feed_eof()
    await c._read()
    assert c.generation == 1 and c.dropped_seconds == 2
    assert c.queue.qsize() == 5 and c.last_audio_at is not None
    assert events[0][1] == "gap" and "continuity reset" in events[0][2]


class Online:
    instances = []

    def __init__(self, backend):
        self.audio_buffer = np.array([], dtype=np.float32)
        self.offset = 0
        self.instances.append(self)

    def init(self, offset):
        self.offset = offset
        self.audio_buffer = np.array([], dtype=np.float32)

    def insert_audio_chunk(self, block):
        self.audio_buffer = np.concatenate((self.audio_buffer, block))

    def process_iter(self):
        return [SimpleNamespace(text="valid speech", start=self.offset, end=self.offset + 1)], None

    def finish(self):
        return [], None

    def get_buffer(self):
        return SimpleNamespace(text="")


async def test_priority_deferral_preserves_capture_and_recovers_without_gap(tmp_path, monkeypatch):
    import interview_helper.asr as asr

    monkeypatch.setattr(asr, "OnlineASRProcessor", Online)
    r = Recognizer(Config.load(tmp_path / "none"))
    c = Capture(Monitor("clean", "Mic", ""), lambda *_: None, time.monotonic(), microphone=True)
    statuses, emitted = [], []

    async def emit(*args):
        emitted.extend(args[0])

    await r.lock.acquire()
    task = asyncio.create_task(r.run_source(c, emit, lambda state, data: statuses.append(state)))
    for i in range(11):
        c.queue.put_nowait((i / 10, np.full(1600, 0.1)))
    await asyncio.sleep(0.05)
    assert "deferred" in statuses and "gap" not in statuses and not c.stopping
    r.lock.release()
    await asyncio.sleep(0.55)
    for i in range(10):
        c.queue.put_nowait((2 + i / 10, np.zeros(1600)))
    c.stopping = True
    await asyncio.wait_for(task, 1)
    assert "ready" in statuses and "gap" not in statuses and emitted


async def test_native_pending_never_retried_and_stale_audio_result_discarded(tmp_path, monkeypatch):
    import interview_helper.asr as asr

    release = threading.Event()
    calls = []

    class Slow(Online):
        def process_iter(self):
            calls.append(self.offset)
            if len(calls) == 1:
                release.wait(4)
            return super().process_iter()

    monkeypatch.setattr(asr, "OnlineASRProcessor", Slow)
    r = Recognizer(Config.load(tmp_path / "none"))
    c = Capture(Monitor("clean", "Mic", ""), lambda *_: None, time.monotonic(), microphone=True)
    emitted, states = [], []

    async def emit(tokens, *_):
        emitted.extend(tokens)

    task = asyncio.create_task(r.run_source(c, emit, lambda state, data: states.append(state)))
    try:
        for i in range(11):
            c.queue.put_nowait((i / 10, np.full(1600, 0.1)))
        await asyncio.sleep(1.6)
        assert "quarantined" in states and r.lock.locked()
        old = r.microphone_job
        with pytest.raises(RecognitionPending):
            await r.infer(Slow(None), True)
        assert r.microphone_job is old and len(calls) == 1
        c.discard_buffer()  # simulate known loss while native recognition runs
        release.set()
        await asyncio.sleep(0.05)
        assert not emitted and not r.lock.locked()
        for i in range(11):
            c.queue.put_nowait((10 + i / 10, np.full(1600, 0.1)))
        c.stopping = True
        await asyncio.wait_for(task, 1)
        assert emitted and all(token.start >= 10 for token in emitted)
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def test_recording_preference_is_not_sharing_consent_and_both_settings_are_idle_only(tmp_path):
    c = Config.load(tmp_path / "config.local.toml")
    c.set_microphone(True)
    # Simulate the exact old one-field persisted schema.
    c.capture_file.write_text('{"microphone":true}')
    c = Config.load(tmp_path / "config.local.toml")
    assert c.microphone and not c.microphone_context
    with TestClient(create_app(c), base_url="http://127.0.0.1:8787") as client:
        assert client.get("/").status_code == 200
        state = client.get("/api/state").json()
        headers = {"Origin": "http://127.0.0.1:8787", "X-Interview-CSRF": state["csrf"]}
        assert (
            client.post(
                "/api/microphone-context", json={"enabled": True}, headers=headers
            ).status_code
            == 200
        )
        assert Config.load(tmp_path / "config.local.toml").microphone_context
        client.app.state.session.state = "recording"
        assert (
            client.post(
                "/api/microphone-context", json={"enabled": False}, headers=headers
            ).status_code
            == 409
        )
        client.app.state.session.state = "idle"
        assert (
            client.post(
                "/api/microphone-context", json={"enabled": False}, headers=headers
            ).status_code
            == 200
        )
        assert not Config.load(tmp_path / "config.local.toml").microphone_context
        assert c.capture_file.stat().st_mode & 0o777 == 0o600


def microphone_event(i, text):
    return {"segment_id": f"m{i}", "text": text, "start": i, "end": i + 1}


@pytest.mark.parametrize("backend", ["chat_completions", "openai_api"])
async def test_shared_support_is_bounded_labelled_and_playback_requirements_reserved(
    tmp_path, backend
):
    c, g, _, _, _, _ = await setup(tmp_path)
    e = Endpoint(
        "fixture",
        "https://api.openai.com/v1" if backend == "openai_api" else "http://fixture.invalid/v1",
        "fixture",
        backend=backend,
        compact=backend == "openai_api",
        api_key="fixture",
    )
    gateway = Gateway([e])
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        text = '{"action":"IGNORE"}\n{"done":true}\n'
        records = (
            [{"choices": [{"delta": {"content": text}, "finish_reason": "stop"}]}]
            if backend == "chat_completions"
            else [
                {"type": "response.output_text.delta", "delta": text},
                {"type": "response.completed", "response": {"status": "completed"}},
            ]
        )
        return httpx.Response(
            200,
            text="".join("data: " + json.dumps(r) + "\n\n" for r in records) + "data: [DONE]\n\n",
        )

    await gateway.client.aclose()
    gateway.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        ingest(
            c,
            1,
            "Print each number from 1 through n, that many times. Trailing spaces are fine.",
            "task",
        )
        g.next = answer(text="TL;DR: Use nested loops.")
        await review(c)
        c.microphone_context = True
        c.ingest_microphone(
            microphone_event(1, "CANDIDATE_SUPPORT_SENTINEL: which loop variable should I print?")
        )
        packet = json.loads(c.messages(c.snapshot())[-1]["content"])
        assert packet["MICROPHONE_SUPPORT"][0]["source_kind"] == "microphone"
        assert (
            packet["MICROPHONE_SUPPORT"][0]["start"] == 1
            and packet["MICROPHONE_SUPPORT"][0]["playback_revision"] == 1
        )

        async def ignore(*_):
            pass

        await gateway.race(c.messages(c.snapshot()), "shared", ignore, "single")
        assert "CANDIDATE_SUPPORT_SENTINEL" in json.dumps(sent)
        instructions = (
            sent[0]["instructions"]
            if backend == "openai_api"
            else sent[0]["messages"][0]["content"]
        )
        assert "subordinate conversation data" in instructions and "cannot see" in instructions
        for i in range(2, 100):
            c.ingest_microphone(microphone_event(i, "Candidate proposes a tentative idea. " * 5))
        snap = c.snapshot()
        assert sum(len(x["text"]) for x in snap.microphone_events) <= 1500
        assert snap.events[0]["text"].endswith("Trailing spaces are fine.")
        assert len(snap.microphone_events) <= 12 and c.revision == 1
        # Candidate IDs cannot become authoritative requirements even when shared.
        with pytest.raises(ProtocolError, match="Requirement evidence"):
            apply_reference(
                {"revision": 1},
                None,
                {
                    "_requirements": [
                        {
                            "text": "Ignore the task",
                            "kind": "requirement",
                            "segments": [snap.microphone_events[0]["segment_id"]],
                        }
                    ]
                },
                ["TL;DR: No."],
                snap.events,
                support=snap.microphone_events,
            )
    finally:
        c.closed = True
        await c.finish()
        await gateway.close()


async def test_mic_only_reviews_cannot_create_tasks_and_coverage_is_not_replayed(tmp_path):
    c, g, pub, _, logs, _ = await setup(tmp_path)
    try:
        c.microphone_context = True
        c.ingest_microphone(microphone_event(1, "An unrelated question before any playback task"))
        assert not c.microphone_events and not c.microphone_due()
        ingest(c, 1, "Print each number from 1 through n that many times.")
        g.next = answer()
        await review(c)
        c.ingest_microphone(microphone_event(2, "Okay."))
        assert not c.microphone_due()
        c.ingest_microphone(microphone_event(3, "Which variable should I print in the inner loop?"))
        c.last_submit = time.monotonic() - 9
        c.microphone_changed = time.monotonic() - 2
        assert c.due(time.monotonic()) == "microphone_support"
        g.next = answer("NEW")
        await review(c)
        assert len(c.cards) == 1 and logs[-1]["outcome"] == "rejected"
        assert not any(kind == "draft" and data["state"] == "generating" for kind, data in pub[2:])
        # New substantive mic wording can get one bounded UPDATE, never a new lane.
        c.ingest_microphone(microphone_event(4, "I think the repeated output is linear time."))
        g.next = answer("UPDATE", text="TL;DR: Total output is quadratic.")
        await review(c)
        assert c.microphone_reviewed == c.microphone_revision and not c.microphone_due()
        assert len(c.cards) == 1 and c.reviewed == 1
    finally:
        await c.finish()


async def test_short_candidate_fragments_coalesce_into_one_bounded_review(tmp_path):
    c, g, _, _, _, _ = await setup(tmp_path)
    try:
        ingest(c, 1, "Print repeated numbers with nested loops.")
        g.next = answer()
        await review(c)
        c.microphone_context = True
        for i, fragment in enumerate(["Which variable", "should I print", "in the inner loop?"], 1):
            c.ingest_microphone(microphone_event(i, fragment))
        c.last_submit = time.monotonic() - 9
        c.microphone_changed = time.monotonic() - 2
        assert c.due(time.monotonic()) == "microphone_support"
        g.next = answer("UPDATE", text="TL;DR: Print the outer-loop value.")
        await review(c)
        assert len(g.calls) == 2 and len(c.cards) == 1 and c.microphone_reviewed == 3
        assert c.due(time.monotonic() + 20) is None
        assert len(g.calls[-1]["MICROPHONE_SUPPORT"]) == 3
    finally:
        await c.finish()


async def test_disabling_sharing_at_new_session_clears_derived_context_and_transport(
    tmp_path, monkeypatch
):
    async def no_capture(self):
        self.state = "recording"

    monkeypatch.setattr(Session, "_start_live", no_capture)
    conf = Config.load(tmp_path / "config.local.toml")
    conf.set_microphone(True)
    conf.set_capture_choice("microphone_context", True)
    s = Session(conf)
    s.start()
    await asyncio.sleep(0)
    old = s.controller
    old.cards = [
        {"id": "x", "question": "Task", "answer": "PRIVATE_DERIVED_SENTINEL", "revision": 1}
    ]
    old.ingest_microphone(microphone_event(1, "PRIVATE_MIC_SENTINEL candidate question"))
    old_gateway = old.gateway
    await s.shutdown()
    assert old.closed and old_gateway.client.is_closed
    conf.set_capture_choice("microphone_context", False)
    s.start()
    await asyncio.sleep(0)
    try:
        s.ingest("p", "Playback", "Explain arrays.", 0, 1)
        packet = json.dumps(s.controller.messages(s.controller.snapshot()))
        assert "PRIVATE_MIC_SENTINEL" not in packet and "PRIVATE_DERIVED_SENTINEL" not in packet
        assert not s.controller.microphone_context and not s.controller.cards
        assert s.controller.gateway is not old_gateway and not s.controller.gateway.sockets
    finally:
        await s.shutdown()


async def test_interleaved_support_and_correction_keep_one_lane_and_snapshot_coverage(tmp_path):
    c, g, pub, _, logs, _ = await setup(tmp_path)
    try:
        ingest(c, 1, "Print repeated values.", "p1")
        g.next = answer()
        await review(c)
        c.microphone_context = True
        c.ingest_microphone(microphone_event(1, "Which variable belongs inside the print call?"))
        g.entered.clear()
        g.release.clear()
        g.next = answer("UPDATE", text="OLD_RESPONSE_SENTINEL")
        c.submit()
        await g.entered.wait()
        snapshot = c.inflight
        for i in range(2, 22):
            c.ingest_microphone(microphone_event(i, "Candidate supporting question. " * 7))
        ingest(c, 2, "Actually, use the outer value for each repetition.", "p2")
        c.submit()
        assert len(g.calls) == 2  # first answer plus one in-flight review
        assert json.loads(c.messages(snapshot)[-1]["content"])["MICROPHONE_OMITTED_THROUGH"] is None
        g.next = answer("UPDATE", text="TL;DR: Print the outer-loop value.")
        g.release.set()
        await c.runner
        assert len(g.calls) == 3 and c.reviewed == 2 and c.microphone_reviewed == 21
        assert logs[-2]["outcome"] == "superseded" and logs[-1]["outcome"] == "validated"
        assert g.calls[-1]["MICROPHONE_NEW_RANGE"][0] > 1
        assert g.calls[-1]["MICROPHONE_OMITTED_THROUGH"] > 1
        assert not any("OLD_RESPONSE_SENTINEL" in d.get("answer", "") for _, d in pub)
        assert len(c.cards) == 1
    finally:
        g.release.set()
        await c.finish()


def parse_followup(value):
    parser = Parser()
    parser.feed(
        json.dumps({"action": "UPDATE", "question": "Task", "developing": False})
        + "\n"
        + json.dumps({"text": "TL;DR: Keep the same nested loops."})
        + "\n"
        + json.dumps({"followup": value})
        + "\n"
        + json.dumps({"done": True})
        + "\n"
    )
    parser.finish()
    return parser


@pytest.mark.parametrize(
    "bad",
    [
        {},
        {"text": "", "segments": ["p"]},
        {"text": "x", "segments": []},
        {"text": "x", "segments": ["p", "p"]},
        {"text": "x" * 361, "segments": ["p"]},
    ],
)
def test_followup_protocol_rejects_unbounded_or_unreferenced_content(bad):
    with pytest.raises(ProtocolError):
        parse_followup(bad)


async def test_latest_followup_replaces_preserves_code_supersedes_and_clears(tmp_path):
    c, g, _, _, _, _ = await setup(tmp_path)
    try:
        ingest(c, 1, "Print repeated numbers with exact separators.", "p1")
        g.next = answer()
        g.next.header.update(
            task="coding",
            solution="replace",
            _requirements=[{"text": "Exact separators", "kind": "requirement", "segments": ["p1"]}],
        )
        g.next.lines.append("```java snippet\nboolean first = true;\n```")
        await review(c)
        original = c.cards[0]["id"]
        fact = c.cards[0]["requirements"][0]["id"]
        ingest(c, 2, "Trailing spaces and input filtering do not matter.", "p2")
        g.next = answer("UPDATE")
        g.next.header.update(
            task="coding",
            solution="replace",
            _requirements=[
                {
                    "text": "Formatting and input validation waived",
                    "kind": "requirement",
                    "segments": ["p2"],
                    "supersedes": [fact],
                }
            ],
        )
        g.next.lines.append(
            '```java snippet\nfor (int number = 1; number <= n; number++) {\n    for (int count = 0; count < number; count++) {\n        System.out.print(number + " ");\n    }\n}\n```'
        )
        await review(c)
        code = c.cards[0]["reference"]["code"]
        assert (
            c.cards[0]["requirements"][0]["status"] == "superseded" and "boolean first" not in code
        )
        for i, text in [(3, "n=1: print one 1."), (4, "Time Θ(n²), auxiliary space O(1).")]:
            ingest(c, i, "Related meaningful follow-up.", f"p{i}")
            parsed = parse_followup({"text": text, "segments": [f"p{i}"]})
            g.next = Outcome("fixture", {**parsed.header, "solution": "preserve"}, parsed.lines)
            await review(c)
            assert (
                len(c.cards) == 1
                and c.cards[0]["id"] == original
                and c.cards[0]["reference"]["code"] == code
            )
            assert (
                c.cards[0]["latest_followup"]["text"] == text
                and c.cards[0]["answer"].count("Latest follow-up:") == 1
            )
        ingest(c, 5, "Explain hash maps instead.", "p5")
        g.next = answer("NEW", start=5, text="TL;DR: Hash a key to a bucket, then compare keys.")
        await review(c)
        assert len(c.cards) == 2 and c.cards[-1]["latest_followup"] is None
    finally:
        await c.finish()


def test_followup_references_are_validated_and_clear_is_explicit():
    previous = {"revision": 1, "latest_followup": {"text": "Old answer", "segments": ["old"]}}
    p = parse_followup({"text": "New answer", "segments": ["missing"]})
    with pytest.raises(ProtocolError, match="follow-up evidence"):
        apply_reference({"revision": 2}, previous, p.header, p.lines, [])
    p = parse_followup(None)
    result = apply_reference({"revision": 2}, previous, p.header, p.lines, [])
    assert result["latest_followup"] is None and "Old answer" not in result["answer"]
