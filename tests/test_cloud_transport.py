"""Transport failures use simulated servers; they are not live renewal evidence."""

import json
import time
from dataclasses import replace
import httpx
import pytest
from interview_helper.budget import Budget
from interview_helper.config import Endpoint
from interview_helper.gateway import Gateway
from interview_helper.protocol import Parser, ProtocolError
from interview_helper.responses_socket import Lane, SocketResponse


def endpoint(**kw):
    return Endpoint(
        "cloud",
        "https://api.openai.com/v1",
        "gpt-6-luna",
        backend="openai_api",
        api_key="fixture",
        **kw,
    )


class Socket:
    close_code = None

    def __init__(self, replies):
        self.replies = list(replies)
        self.sent = []
        self.closed = False

    async def send(self, body):
        self.sent.append(json.loads(body))
        self.current = iter(self.replies.pop(0))

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return json.dumps(next(self.current))
        except StopIteration:
            raise StopAsyncIteration

    async def close(self):
        self.closed = True


def complete(id="r1"):
    return {"type": "response.completed", "response": {"id": id, "status": "completed"}}


async def consume(lane, payload):
    diagnostics = {}
    response = SocketResponse(lane, payload, diagnostics, lambda *_: None)
    output = [event async for event in response.aiter_lines()]
    return diagnostics, output


async def test_continuation_and_reset_never_accumulate_unbounded_context():
    lane = Lane()
    lane.socket = Socket([[complete(str(i))] for i in range(7)])
    payload = {"input": [{"role": "user", "content": "one"}], "stream": True, "store": False}
    await consume(lane, payload)
    for i in range(1, 6):
        payload = {**payload, "input": payload["input"] + [{"role": "user", "content": str(i)}]}
        await consume(lane, payload)
    assert "stream" not in lane.socket.sent[0]
    assert lane.socket.sent[1]["previous_response_id"] == "0"
    assert len(lane.socket.sent[1]["input"]) == 1
    assert "previous_response_id" not in lane.socket.sent[4]
    await consume(lane, {**payload, "input": [{"role": "user", "content": "replacement"}]})
    assert "previous_response_id" not in lane.socket.sent[-1]


async def test_missing_previous_rebuilds_only_after_definitive_rejection():
    lane = Lane()
    lane.previous_id = "gone"
    lane.previous_input = [{"role": "user", "content": "one"}]
    lane.socket = Socket(
        [[{"type": "error", "error": {"code": "previous_response_not_found"}}], [complete()]]
    )
    full = lane.previous_input + [{"role": "user", "content": "two"}]
    diagnostic, _ = await consume(lane, {"input": full, "store": False})
    assert diagnostic["recovery"] == "previous_response_not_found"
    assert lane.socket.sent[1]["input"] == full
    assert "previous_response_id" not in lane.socket.sent[1]


async def test_disconnect_does_not_replay_uncertain_inference():
    lane = Lane()
    lane.socket = Socket([[{"type": "response.created"}]])
    with pytest.raises(ConnectionError):
        await consume(lane, {"input": []})
    assert len(lane.socket.sent) == 1


@pytest.mark.parametrize("reason", ["age", "renewal", "closed"])
async def test_connection_rotation_before_dispatch(reason):
    lane = Lane()
    old = Socket([])
    lane.socket = old
    lane.key = "old"
    lane.created = time.monotonic()
    key = "old"
    if reason == "age":
        lane.created -= 3600
    if reason == "renewal":
        key = "renewed"
    if reason == "closed":
        old.close_code = 1000

    async def opened(key, mark):
        lane.socket = Socket([[complete()]])
        lane.key = key

    lane.open = opened
    async with lane.response(
        None, endpoint(), key, {"input": []}, "id", lambda *_: None, {}, None
    ) as response:
        assert [line async for line in response.aiter_lines()]
    assert old.closed and lane.key == key


async def test_handshake_failure_falls_back_before_dispatch():
    lane = Lane()

    async def failed(*a):
        raise OSError("simulated handshake failure")

    lane.open = failed
    calls = []

    def handler(req):
        calls.append(req)
        return httpx.Response(200, text="data: {}\n\n")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        diag = {}
        async with lane.response(
            client, endpoint(), "fixture", {"input": []}, "id", lambda *_: None, diag, None
        ) as response:
            assert response.status_code == 200
        assert len(calls) == 1 and diag["websocket_fallback"] == "OSError"


async def test_malformed_answer_drains_terminal_usage_and_keeps_failure():
    ep = endpoint()
    g = Gateway([ep])
    events = [
        {
            "type": "response.output_text.delta",
            "delta": '{"action":"WAIT"}\n{"done":true}\n{"text":"wrong"}\n',
        },
        {
            "type": "response.completed",
            "response": {
                "status": "completed",
                "service_tier": "fast",
                "usage": {"input_tokens": 12, "output_tokens": 8},
            },
        },
    ]
    await g.client.aclose()
    g.client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200, text="".join("data: " + json.dumps(e) + "\n\n" for e in events)
            )
        )
    )

    async def emit(*a):
        pass

    result = await g.stream(ep, [], "id", emit)
    assert result.error == "Content after done" and result.usage["output_tokens"] == 8
    assert result.diagnostics["response_service_tier"] == "fast"
    await g.close()


def test_cloud_failure_scope_does_not_quarantine_other_reasoning_or_local_host():
    low = endpoint(parameters={"reasoning_effort": "low"})
    none = replace(low, parameters={"reasoning_effort": "none"})
    assert Gateway.failure_key(low) != Gateway.failure_key(none)
    local = Endpoint("local", "http://localhost:1234", "model", host_id="physical")
    assert Gateway.failure_key(local) == "physical"


def test_compact_header_still_validates_action_and_qualifiers():
    parser = Parser()
    records = parser.feed(
        '{"action":"UPDATE","question":"Shared counter: Java 8 without locks across processes","developing":false}\n{"text":"Clarify lock-free scope before choosing shared storage."}\n{"done":true}\n'
    )
    assert "Shared counter" in records[0]["question"]
    assert "Java 8 without locks" in records[0]["question"]
    parser.finish()
    with pytest.raises(ProtocolError):
        Parser().feed('{"action":"NEW","developing":"false"}\n')


def test_budget_preserves_unknown_cost_and_blocks_over_cap(tmp_path):
    budget = Budget(tmp_path / "cost.json", cap=0.1)
    payload = {
        "model": "gpt-6.1-sol",
        "service_tier": "ultrafast",
        "max_output_tokens": 512,
        "input": [],
    }
    reserved = budget.reserve("one", payload)
    budget.settle("one", {}, "ultrafast")
    assert budget.read()["requests"]["one"]["reserved_usd"] == reserved
    with pytest.raises(RuntimeError):
        budget.reserve("two", payload)
    budget.settle(
        "one",
        {"input_tokens": 100, "output_tokens": 20, "input_tokens_details": {"cached_tokens": 50}},
        "ultrafast",
    )
    assert budget.read()["requests"]["one"]["cost_usd"] == pytest.approx(0.00183)
    budget.reserve("two", payload)
    with pytest.raises(ValueError):
        budget.reserve("two", payload)


async def test_transcript_delta_retains_scenario_and_resets_on_truncation():
    lane = Lane()
    lane.socket = Socket([[complete(str(i))] for i in range(3)])
    original = {
        "SCENARIO_REQUIREMENTS": "Java 8 without locks.",
        "RECENT_CONVERSATION": "Question.",
        "NEW_STABLE_TEXT": "Question.",
    }

    def payload(state):
        return {
            "instructions": "Honor CONTEXT_APPEND.",
            "input": [{"role": "user", "content": json.dumps(state)}],
        }

    await consume(lane, payload(original))
    newer = {
        **original,
        "SCENARIO_REQUIREMENTS": original["SCENARIO_REQUIREMENTS"] + " Multiple processes.",
        "RECENT_CONVERSATION": "Question. Correction.",
        "NEW_STABLE_TEXT": "Correction.",
    }
    await consume(lane, payload(newer))
    delta = json.loads(lane.socket.sent[-1]["input"][0]["content"])
    assert (
        delta["CONTEXT_APPEND"] is True and delta["SCENARIO_REQUIREMENTS"] == " Multiple processes."
    )
    await consume(lane, payload({**newer, "RECENT_CONVERSATION": "Window truncated"}))
    assert "previous_response_id" not in lane.socket.sent[-1]


async def test_timeout_quarantines_only_experimental_cloud_profile():
    low = endpoint(parameters={"reasoning_effort": "low"}, timeout=1)
    none = replace(low, parameters={"reasoning_effort": "none"})
    gateway = Gateway([low])
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        if body["reasoning"]["effort"] == "none":
            raise httpx.ReadTimeout("fixture timeout")
        text = '{"action":"WAIT"}\n{"done":true}\n'
        events = [
            {"type": "response.output_text.delta", "delta": text},
            {"type": "response.completed", "response": {"status": "completed"}},
        ]
        return httpx.Response(200, text="".join("data: " + json.dumps(e) + "\n\n" for e in events))

    await gateway.client.aclose()
    gateway.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    async def emit(*a):
        pass

    failed = await gateway.stream(none, [], "none", emit)
    healthy = await gateway.stream(low, [], "low", emit)
    blocked = await gateway.stream(none, [], "none-again", emit)
    assert failed.error == "ReadTimeout" and not healthy.error and "paused" in blocked.error
    assert len(calls) == 2
    await gateway.close()


@pytest.mark.parametrize("split", [None, 12, 95])
async def test_answer_delta_timing_when_header_and_text_share_provider_delta(split):
    wire = (
        '{"action":"NEW","question":"Unique inserts?","developing":false}\n'
        '{"text":"Enforce uniqueness atomically in the database."}\n{"done":true}\n'
    )
    chunks = [wire] if split is None else [wire[:split], wire[split:]]
    events = [{"type": "response.output_text.delta", "delta": chunk} for chunk in chunks]
    events.append(complete())

    def handler(request):
        return httpx.Response(200, text="".join("data: " + json.dumps(e) + "\n\n" for e in events))

    ep = endpoint()
    gateway = Gateway([ep])
    await gateway.client.aclose()
    gateway.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    async def emit(*args):
        pass

    try:
        result = await gateway.stream(ep, [], "coalesced", emit)
        assert not result.error
        assert result.lines == ["Enforce uniqueness atomically in the database."]
        assert (
            result.timings["first_output_text_delta"]
            <= result.timings["first_answer_content_delta"]
            <= result.timings["first_complete_record"]
        )
    finally:
        await gateway.close()


@pytest.mark.parametrize("recovery", ["age", "renewal", "closed", "missing", "limit"])
async def test_socket_recovery_keeps_session_question_constraints_and_saving(tmp_path, recovery):
    from interview_helper.config import Config
    from interview_helper.session import Session
    from interview_helper.storage import SessionStore

    config = Config.load(tmp_path / "config.local.toml")
    ep = endpoint(transport="websocket", compact=True, parameters={"reasoning_effort": "low"})
    config.endpoints = [ep]
    session = Session(config)
    sid = session.start(replay=True)
    gateway = session.controller.gateway
    lane = Lane()
    gateway.sockets[ep.name] = lane
    sockets = []

    def answer(action, response_id):
        return [
            {"type": "response.created"},
            {
                "type": "response.output_text.delta",
                "delta": (
                    json.dumps(
                        {
                            "action": action,
                            "question": "Shared counter in Java 8 without locks across JVMs",
                            "developing": False,
                        }
                    )
                    + "\n"
                    + '{"text":"Within one JVM, use AtomicInteger; this does not coordinate multiple JVMs."}\n{"done":true}\n'
                ),
            },
            complete(response_id),
        ]

    async def opened(key, mark):
        lane.socket = Socket([answer("NEW" if not sockets else "UPDATE", str(len(sockets)))])
        sockets.append(lane.socket)
        lane.key, lane.created = key, time.monotonic()
        lane.generation += 1

    lane.open = opened

    async def submit(text, index):
        session.ingest("fixture", "Playback", text, index, index + 1, final=True)
        session.controller.submit()
        await session.controller.runner

    try:
        await submit("Explain a shared counter using Java 8 without locks.", 0)
        active = session.controller.cards[-1]["id"]
        first = lane.socket
        if recovery == "age":
            lane.created -= 3301
        elif recovery == "renewal":
            ep.api_key = "fixture-renewed"
        elif recovery == "closed":
            first.close_code = 1000
        else:
            code = (
                "previous_response_not_found"
                if recovery == "missing"
                else "websocket_connection_limit_reached"
            )
            first.replies = [
                [{"type": "error", "error": {"code": code}}],
                answer("UPDATE", "recovered"),
            ]
        await submit("Actually it must work across multiple JVMs without an external service.", 1)
        assert session.store.id == sid and session.state == "recording"
        assert session.controller.cards[-1]["id"] == active
        assert "Java 8" in session.controller.scenario
        assert "multiple JVMs" in session.controller.scenario
        sent = lane.socket.sent[-1]
        assert "previous_response_id" not in sent
        state = json.loads(sent["input"][-1]["content"])
        assert "Java 8" in str(state["CONVERSATION"])
        assert state["ACTIVE_QUESTION"] and "without locks" in state["ACTIVE_QUESTION"]["question"]
        if recovery != "missing":
            assert first.closed and len(sockets) == 2
        else:
            assert len(first.sent) == 3 and len(sockets) == 1
        # A definitive provider failure is visible but does not end the session.
        lane.socket.replies = [[{"type": "error", "error": {"code": "server_error"}}]]
        await submit("What happens when the process crashes while writing?", 2)
        assert session.state == "recording" and session.controller.cards[-1]["id"] == active
        assert any("Hint failed" in n["message"] for n in session.notices)
        assert session.status["save"] == "saved"
    finally:
        await session.shutdown()
    data = SessionStore.inspect(config.data_dir, sid)
    assert len(data["events"]) == 3 and not data["partial_tail"]
    assert data["metadata"]["status"] == "ended"


async def test_created_tier_without_terminal_tier_is_not_effective():
    ep = endpoint()
    g = Gateway([ep])
    await g.client.aclose()
    events = [
        {"type": "response.created", "response": {"service_tier": "ultrafast"}},
        {"type": "response.output_text.delta", "delta": '{"action":"WAIT"}\n{"done":true}\n'},
        complete(),
    ]
    g.client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200, text="".join("data: " + json.dumps(e) + "\n\n" for e in events)
            )
        )
    )

    async def emit(*_):
        pass

    try:
        result = await g.stream(ep, [], "id", emit)
        assert not result.error
        assert "response_service_tier" not in result.diagnostics
        assert result.diagnostics["created_service_tier"] == "ultrafast"
    finally:
        await g.close()
