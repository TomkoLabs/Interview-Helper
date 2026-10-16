import asyncio
import json
import httpx
import pytest
from interview_helper.config import Endpoint
from interview_helper.gateway import Gateway


class Stream(httpx.AsyncByteStream):
    def __init__(self, text, delay=0, finish="stop"):
        self.text = text
        self.delay = delay
        self.finish = finish
        self.closed = False

    async def __aiter__(self):
        await asyncio.sleep(self.delay)
        for part in [self.text[i : i + 7] for i in range(0, len(self.text), 7)]:
            yield (
                "data: " + json.dumps({"choices": [{"delta": {"content": part}}]}) + "\n\n"
            ).encode()
        yield (
            "data: "
            + json.dumps({"choices": [{"delta": {}, "finish_reason": self.finish}]})
            + "\n\n"
        ).encode()
        yield b"data: [DONE]\n\n"

    async def aclose(self):
        self.closed = True


WAIT = '{"action":"WAIT"}\n{"done":true}\n'
ANSWER = '{"action":"NEW","question":"Explain mutexes","developing":false}\n{"text":"Mutexes protect shared state."}\n{"done":true}\n'


def gateway(handler):
    e = [
        Endpoint("a", "https://example.invalid/v1", "a", api_key="test"),
        Endpoint("b", "https://example.invalid/v1", "b", api_key="test"),
    ]
    g = Gateway(e)
    g.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return g


@pytest.mark.asyncio
async def test_fast_wait_does_not_suppress_answer():
    def handler(r):
        model = json.loads(r.content)["model"]
        return httpx.Response(
            200, stream=Stream(WAIT if model == "a" else ANSWER, 0 if model == "a" else 0.03)
        )

    g = gateway(handler)
    lines = []

    async def emit(*args):
        lines.append(args)

    r = await g.race([], "1", emit, "race")
    assert r.host == "b" and r.header["action"] == "NEW" and lines
    await g.close()


@pytest.mark.asyncio
async def test_drain_holds_host_slot_and_no_splice():
    streams = []

    def handler(r):
        s = Stream(ANSWER, 0.01 if json.loads(r.content)["model"] == "a" else 0.15)
        streams.append(s)
        return httpx.Response(200, stream=s)

    g = gateway(handler)
    lines = []

    async def emit(host, *args):
        lines.append(host)

    r = await g.race([], "1", emit, "race")
    assert r.host == "a" and g.locks["b"].locked()
    await g.close()
    assert set(lines) == {"a"} and all(s.closed for s in streams)


@pytest.mark.asyncio
async def test_malformed_winner_rejected():
    def handler(r):
        return httpx.Response(200, stream=Stream(ANSWER.replace('{"done":true}', "{bad}")))

    g = gateway(handler)

    async def emit(*_):
        pass

    r = await g.race([], "1", emit)
    assert r.error and not r.lines
    await g.close()


@pytest.mark.asyncio
async def test_truncated_finish_rejected():
    g = gateway(lambda r: httpx.Response(200, stream=Stream(ANSWER, finish="length")))

    async def emit(*_):
        pass

    r = await g.race([], "1", emit)
    assert r.error
    await g.close()


@pytest.mark.asyncio
async def test_unavailable_peer():
    g = gateway(
        lambda r: httpx.Response(503)
        if json.loads(r.content)["model"] == "a"
        else httpx.Response(200, stream=Stream(ANSWER))
    )

    async def emit(*_):
        pass

    r = await g.race([], "1", emit, "race")
    assert r.host == "b" and not r.error
    await g.close()


@pytest.mark.asyncio
async def test_supported_cancel_closes_loser_stream_and_releases_slot():
    streams = {}

    def handler(r):
        name = json.loads(r.content)["model"]
        streams[name] = Stream(ANSWER, 0.01 if name == "a" else 5)
        return httpx.Response(200, stream=streams[name])

    g = gateway(handler)
    g.endpoints[1].cancel_supported = True

    async def emit(*_):
        pass

    result = await g.race([], "cancel", emit, "race")
    await g.close()
    assert result.host == "a" and streams["b"].closed
    assert not g.locks["b"].locked()


@pytest.mark.asyncio
async def test_repeated_races_do_not_queue_obsolete_work_on_draining_peer():
    release = asyncio.Event()
    calls = []

    class HeldStream(Stream):
        async def __aiter__(self):
            await release.wait()
            async for chunk in super().__aiter__():
                yield chunk

    def handler(request):
        model = json.loads(request.content)["model"]
        calls.append(model)
        return httpx.Response(
            200, stream=HeldStream(ANSWER) if model == "b" else Stream(ANSWER, 0.001)
        )

    g = gateway(handler)

    async def emit(*_):
        pass

    for i in range(8):
        result = await g.race([], str(i), emit, "race")
        assert result.host == "a"
    queued = len(g.draining)
    release.set()
    await g.close()
    assert queued == 1 and calls.count("b") == 1


@pytest.mark.asyncio
async def test_superseded_waiter_never_dispatches_and_queue_is_separate():
    calls = []

    def handler(request):
        calls.append(request.headers["x-request-id"])
        return httpx.Response(200, stream=Stream(ANSWER, 0.001))

    g = gateway(handler)
    await g.locks["a"].acquire()
    current = True

    async def emit(*_):
        pass

    old = asyncio.create_task(g.race([], "old", emit, current=lambda: current))
    await asyncio.sleep(0.06)
    current = False
    outcome = await asyncio.wait_for(old, 0.2)
    assert outcome.error == "Superseded before dispatch" and not calls
    assert outcome.queue_seconds >= 0.05 and outcome.first_useful is None
    latest = asyncio.create_task(g.race([], "latest", emit))
    await asyncio.sleep(0.06)
    g.locks["a"].release()
    outcome = await latest
    assert calls == ["latest"] and outcome.queue_seconds >= 0.05
    assert outcome.first_useful < outcome.queue_seconds
    await g.close()


@pytest.mark.asyncio
async def test_timeout_still_quarantines_non_cancellable_host():
    g = gateway(lambda r: httpx.Response(200, stream=Stream(ANSWER, 1)))
    g.endpoints[0].timeout = 0.02

    async def emit(*_):
        pass

    first = await g.race([], "timeout", emit)
    second = await g.race([], "paused", emit)
    assert first.error == "TimeoutError" and "a" in g.quarantined
    assert "Host paused after timeout" in second.error
    await g.close()
