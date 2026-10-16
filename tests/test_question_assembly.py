"""Scripted model decisions exercise assembly/publication, not live model quality."""

import asyncio
import json
import pytest
from interview_helper.config import Config
from interview_helper.controller import Controller
from interview_helper.gateway import Outcome
from interview_helper.protocol import Parser, ProtocolError


class Decisions:
    def __init__(self):
        self.next = None
        self.calls = []

    async def race(self, messages, request_id, on_line, strategy, current=None):
        self.calls.append(json.loads(messages[-1]["content"]))
        action, heading, answer = self.next
        action = action or "IGNORE"
        header = {"action": action}
        if heading:
            header.update(question=heading, developing=action == "NEW")
            if action == "NEW":
                header["start_revision"] = self.calls[-1]["NEW_REVISIONS"][0]
        # Run actual incremental validation before simulated publication.
        parser = Parser()
        parser.feed(json.dumps(header) + "\n")
        lines = [answer] if answer else []
        if lines:
            parser.feed(json.dumps({"text": answer}) + "\n")
            await on_line("fixture", header, lines)
        parser.feed('{"done":true}\n')
        parser.finish()
        return Outcome("fixture", header, lines, 0.01, 0.02)

    async def close(self):
        pass


@pytest.mark.asyncio
async def test_fragmented_mock_design_and_topics(tmp_path):
    gateway = Decisions()
    published, saved, reviews = [], [], []

    async def publish(kind, data):
        published.append((kind, data))

    c = Controller(
        Config.load(tmp_path / "config.local.toml"),
        gateway,
        publish,
        saved.append,
        lambda _: None,
        reviews.append,
    )
    revision = 0

    async def step(text, action=None, heading=None, answer=None):
        nonlocal revision
        revision += 1
        gateway.next = (action, heading, answer)
        c.ingest({"revision": revision, "source_name": "Mock playback", "text": text})
        c.submit()
        if c.runner:
            await c.runner

    try:
        await step("Oh, okay.")
        assert len(gateway.calls) == 1
        await step("Okay, so basically the first", "WAIT")
        await step("of a memory allocation", "WAIT")
        await step("itself", "IGNORE")
        await step("that top line.", "IGNORE")
        assert not c.cards and not [p for p in published if p[0] == "draft"]
        await step(
            "Design a cloud short-story reader",
            "NEW",
            "Design a cloud short-story reader",
            "Store stories and serve readers through a bounded API.",
        )
        identity = c.cards[-1]["id"]
        await step(
            "with offline reading and no third-party identity service",
            "UPDATE",
            "Story reader with offline access and local identity",
            "Cache authorized stories offline; own identity and revocation rules.",
        )
        assert len(c.cards) == 1 and c.cards[-1]["id"] == identity
        assert "offline" in c.cards[-1]["answer"]
        await step(
            "Actually, support ten million readers and retain deletion requests",
            "UPDATE",
            "Story reader: scale, offline access and deletion",
            "Partition reads and preserve durable deletion intent with offline expiry rules.",
        )
        assert c.cards[-1]["id"] == identity and len(c.cards) == 1
        for constraint in (
            "cloud short-story reader",
            "offline reading",
            "no third-party",
            "ten million",
            "deletion",
        ):
            assert constraint in " ".join(e["text"] for e in gateway.calls[-1]["CONVERSATION"])
        retained = c.scenario
        await step("I would put the stories in object storage and cache popular pages.", "IGNORE")
        assert c.scenario.startswith(retained) and "object storage" in c.scenario
        await step(
            "Why?",
            "NEW",
            "Why cache popular stories?",
            "Caching reduces repeated storage reads when freshness requirements permit it.",
        )
        assert len(c.cards) == 2 and c.cards[-1]["id"] != identity
        await step("Compare a Python list and", None)
        calls = len(gateway.calls)
        await step(
            "a tuple",
            "NEW",
            "Python list versus tuple",
            "Lists are mutable; tuples fix the sequence of object references.",
        )
        assert len(gateway.calls) == calls + 1 and len(c.cards) == 3
        assert "Compare a Python list and" in str(gateway.calls[-1]["CONVERSATION"])
        assert "short-story" not in c.scenario
        await step(".")
        await step("Oh, okay.")
        assert len(c.cards) == 3
        assert all(
            r["heading_origin"] == "model" for r in reviews if r["action"] in {"NEW", "UPDATE"}
        )
    finally:
        await c.finish()


def test_raw_fragment_fallback_is_removed_and_heading_validation_stays_strict():
    for header in [
        {"action": "NEW", "developing": False},
        {"action": "NEW", "question": ".", "developing": False},
        {"action": "UPDATE", "question": " " * 5, "developing": False},
        {"action": "NEW", "question": "Why?", "developing": "false"},
    ]:
        with pytest.raises(ProtocolError):
            Parser().feed(json.dumps(header) + "\n")
    p = Parser()
    p.feed(
        '{"action":"NEW","question":"Why?","developing":false}\n{"text":"Explain the contextual tradeoff."}\n{"done":true}\n'
    )
    p.finish()


@pytest.mark.asyncio
async def test_update_wait_prefix_cleared_and_stale_correction_cannot_publish(tmp_path):
    from test_controller import setup, event

    c, g, published, saved, _ = await setup(tmp_path)
    c.ingest(event(1, "Design a cloud reader without locks"))
    c.submit()
    await asyncio.sleep(0.01)
    c.ingest(event(2, "Actually, the storage is across multiple processes"))
    c.submit()
    g.release.set()
    await c.runner
    assert all(card["revision"] == 2 for card in saved)
    assert not any(kind == "draft" and data["revision"] == 1 for kind, data in published)
    assert any(kind == "discard" for kind, data in published)
    await c.finish()


@pytest.mark.asyncio
async def test_long_developing_question_keeps_beginning_after_recent_window_rolls(tmp_path):
    g = Decisions()

    async def publish(*_):
        pass

    c = Controller(
        Config.load(tmp_path / "config.local.toml"), g, publish, lambda _: None, lambda _: None
    )
    try:
        chunks = ["Design a reader without third-party identity and retain deletion requests."] + [
            f"Requirement {i}: " + "bounded offline story access " * 24 for i in range(12)
        ]
        identity = None
        for i, chunk in enumerate(chunks, 1):
            g.next = (
                "NEW" if i == 1 else "UPDATE",
                "Reader design with accumulated constraints",
                "Retain all explicit requirements.",
            )
            c.ingest({"revision": i, "source_name": "Playback", "text": chunk})
            c.submit()
            await c.runner
            identity = identity or c.cards[-1]["id"]
            assert c.cards[-1]["id"] == identity and len(c.cards) == 1
            assert chunks[0] in c.scenario
        assert chunks[0] not in " ".join(r[2] for r in c.recent)
        assert chunks[0] in str(g.calls[-1]["CONVERSATION"])
        assert len(c.scenario) < c.config.scenario_chars
    finally:
        await c.finish()


@pytest.mark.asyncio
async def test_complete_operator_request_is_not_mistaken_for_dangling_conjunction(tmp_path):
    from test_controller import setup, event

    c, g, _, saved, _ = await setup(tmp_path)
    g.release.set()
    c.ingest(event(1, "Explain logical AND"))
    c.submit()
    await c.runner
    assert len(g.calls) == 1 and len(saved) == 1
    await c.finish()
