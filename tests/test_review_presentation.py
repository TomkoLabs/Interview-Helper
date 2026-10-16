"""Deterministic protocol/lifecycle tests, not evidence of model quality."""

import asyncio
import json
import time
import httpx
import pytest
from interview_helper.protocol import Parser, ProtocolError
from interview_helper.gateway import Gateway
from interview_helper.config import Config, Endpoint
from interview_helper.session import Session
from interview_helper.storage import SessionStore
from test_live_review import setup, ingest, review, answer


HEAD = {"action": "NEW", "question": "Count subsequences", "developing": False, "segments": ["s1"]}
CODE = {
    "code": "int count = 0;\n// <script> remains literal code text",
    "language": "java",
    "scope": "snippet",
}


def wire(*records):
    return "".join(json.dumps(r) + "\n" for r in records)


@pytest.mark.parametrize(
    "bad",
    [
        {**HEAD, "segments": ["x"] * 9},
        {**HEAD, "segments": ["x", "x"]},
        {**HEAD, "segments": [1]},
        {**HEAD, "segments": "x"},
    ],
)
def test_reference_schema(bad):
    with pytest.raises(ProtocolError):
        Parser().feed(wire(bad))


def test_code_requires_approach_and_complete_record():
    with pytest.raises(ProtocolError):
        Parser().feed(wire(HEAD, CODE))
    p = Parser()
    p.feed(wire(HEAD, {"text": "TL;DR: Use waiting buckets."}))
    partial = json.dumps(CODE)
    assert p.feed(partial[:25]) == []
    assert len(p.lines) == 1
    with pytest.raises(ProtocolError):
        p.finish()
    p = Parser()
    p.feed(wire(HEAD, {"text": "TL;DR: Use waiting buckets."}, CODE, {"done": True}))
    p.finish()
    assert p.lines[-1].startswith("```java snippet\n")
    for bad in [
        {**CODE, "code": "```"},
        {**CODE, "language": "<img src=x>"},
        {**CODE, "scope": "unfinished"},
    ]:
        with pytest.raises(ProtocolError):
            Parser().feed(wire(HEAD, {"text": "Approach."}, bad))


async def test_input_ids_ai_label_and_out_of_snapshot_refs_rejected(tmp_path):
    c, g, pub, _, logs, _ = await setup(tmp_path)
    try:
        ingest(c, 1, "Count subsequences.", "stable-id")
        g.next = answer()
        g.next.header["segments"] = ["stable-id"]
        await review(c)
        assert g.calls[0]["CONVERSATION"][0]["segment_id"] == "stable-id"
        before = list(c.cards)
        ingest(c, 2, "Why does detaching matter?")
        g.next = answer("UPDATE")
        g.next.header["segments"] = ["made-up-id"]
        await review(c)
        assert c.cards == before and c.reviewed == 1
        assert "AI-generated" in g.calls[-1]["ACTIVE_QUESTION"]["answer_origin"]
        assert "references" in logs[-1]["error"]
        assert not any(k == "draft" and d["revision"] == 2 for k, d in pub)
        assert logs[-1]["included_segments"] == ["stable-id", "2"]
    finally:
        await c.finish()


async def test_review_now_idle_inflight_click_storm_and_unchanged_snapshot(tmp_path):
    c, g, _, _, logs, _ = await setup(tmp_path)
    try:
        assert not c.review_now()
        ingest(c, 1, "Explain volatile visibility.")
        g.next = answer()
        g.release.clear()
        assert c.review_now()
        await g.entered.wait()
        for _ in range(20):
            c.review_now()
        assert c.pending is None and len(g.calls) == 1
        ingest(c, 2, "It does not make increment atomic, correct?")
        for _ in range(20):
            c.review_now()
        assert c.pending.revision == 2
        g.next = answer("UPDATE")
        g.release.set()
        await c.runner
        assert len(g.calls) == 2 and len(c.cards) == 1 and c.reviewed == 2
        assert c.review_now()  # explicit rereview of identical transcript
        await c.runner
        assert len(g.calls) == 3 and len(c.cards) == 1
        assert g.calls[-1]["NEW_REVISIONS"] is None
        assert logs[-1]["trigger"] == "review_now"
        c.submit()
        await c.runner
        assert len(g.calls) == 3
    finally:
        await c.finish()


class BlockingStream(httpx.AsyncByteStream):
    def __init__(self):
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def __aiter__(self):
        for record in [
            HEAD,
            {"text": "TL;DR: Detach each bucket before advancing."},
            CODE,
            {"text": "- Count duplicates independently."},
        ]:
            yield (
                "data: " + json.dumps({"choices": [{"delta": {"content": wire(record)}}]}) + "\n\n"
            ).encode()
        self.started.set()
        await self.release.wait()
        yield (
            "data: "
            + json.dumps({"choices": [{"delta": {"content": wire({"done": True})}}]})
            + "\n\n"
        ).encode()
        yield b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'


async def test_real_gateway_streams_tldr_but_holds_code_until_validated():
    ep = Endpoint("fixture", "https://example.invalid/v1", "fixture", api_key="fixture")
    g = Gateway([ep])
    await g.client.aclose()
    stream = BlockingStream()
    g.client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=stream))
    )
    drafts = []

    async def publish(host, header, lines):
        drafts.append(list(lines))

    task = asyncio.create_task(g.race([], "test", publish))
    await stream.started.wait()
    assert drafts and drafts[0] == ["TL;DR: Detach each bucket before advancing."]
    assert all("```" not in "\n".join(lines) for lines in drafts)
    assert not task.done()
    stream.release.set()
    result = await task
    assert not result.error and "```java snippet" in "\n".join(result.lines)
    await g.close()


async def test_end_saves_tail_without_provider_completion_and_preserves_quarantine(
    tmp_path, monkeypatch
):
    monkeypatch.setattr("interview_helper.controller.SHUTDOWN_REVIEW_GRACE", 0.03)
    cfg = Config.load(tmp_path / "config.local.toml")
    ep = Endpoint("fixture", "https://example.invalid/v1", "fixture", api_key="fixture", timeout=60)
    cfg.endpoints = [ep]
    s = Session(cfg)
    s.start(replay=True)
    g = s.controller.gateway
    await g.client.aclose()
    stream = BlockingStream()
    g.client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=stream))
    )
    s.ingest("fixture", "Playback", "Count subsequences.", 0, 1)
    s.controller.submit()
    await stream.started.wait()
    s.ingest("fixture", "Playback", "Count empty words too.", 1, 2)
    stamp = time.monotonic()
    s.end()
    await s.end_task
    assert time.monotonic() - stamp < 0.5
    assert s.state == "ended" and s.store.closed and not s.drafts
    assert g.failure_key(ep) in s.gateway_quarantine
    data = SessionStore.inspect(cfg.data_dir, s.store.id)
    assert len([e for e in data["events"] if e.get("type") == "transcript"]) == 2
    shutdown = next(h for h in data["hints"] if h["type"] == "review_shutdown")
    assert shutdown["cancelled_request_id"] and shutdown["cancelled_input_revision"] == 1
    assert shutdown["unreviewed_range"] == [1, 2]
    assert any("Unreviewed transcript tail saved" in n["message"] for n in s.notices)
    s.start(replay=True)
    assert g.failure_key(ep) in s.controller.gateway.quarantined
    await s.shutdown()
