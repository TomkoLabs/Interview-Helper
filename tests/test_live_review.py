"""Coverage/scheduling assertions against real packets, with controlled provider I/O."""

import asyncio
import json
import time
import pytest
from interview_helper.config import Config
from interview_helper.controller import Controller
from interview_helper.gateway import Outcome
from interview_helper.protocol import Parser, ProtocolError


class Provider:
    def __init__(self):
        self.calls = []
        self.next = Outcome("fixture", {"action": "IGNORE"})
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.release.set()

    async def race(self, messages, rid, line, strategy, current=None):
        self.calls.append(json.loads(messages[-1]["content"]))
        response = self.next
        self.entered.set()
        await self.release.wait()
        for i, a in enumerate(
            response.answers or [{"header": response.header, "lines": response.lines}]
        ):
            if a["lines"]:
                await line("fixture", {**a["header"], "_index": i}, a["lines"])
        return response

    async def close(self):
        pass


def answer(action="NEW", start=1, text="Detach the current bucket before advancing words."):
    h = {"action": action, "question": "Count matching subsequences", "developing": False}
    if action == "NEW":
        h["start_revision"] = start
    return Outcome("fixture", h, [text])


async def setup(tmp_path):
    g = Provider()
    pub, saved, reviews, statuses = [], [], [], []

    async def publish(kind, data):
        pub.append((kind, data))

    c = Controller(
        Config.load(tmp_path / "config.local.toml"),
        g,
        publish,
        saved.append,
        statuses.append,
        reviews.append,
    )
    c.stopping = True
    await c.tick_task
    # Disable automatic final drain until explicitly requested, without a timer.
    c.stopping = False
    return c, g, pub, saved, reviews, statuses


def ingest(c, revision, text, segment=None):
    c.ingest(
        {
            "revision": revision,
            "source_name": "Playback",
            "text": text,
            "segment_id": segment or str(revision),
        }
    )


async def review(c):
    c.submit()
    await c.runner


@pytest.mark.asyncio
async def test_verbatim_coverage_survives_ignore_wait_and_repeated_headings(tmp_path):
    c, g, _, _, logs, _ = await setup(tmp_path)
    words = [
        "Given a string s and words, count words that are subsequences of s.",
        "A subsequence deletes characters without reordering the rest.",
        "For example ace is a subsequence of abcde.",
        "I would use buckets, but the input also includes empty words and duplicates.",
        "Oh, okay.",
        "Please implement that solution in Java.",
    ]
    try:
        g.next = answer()
        ingest(c, 1, words[0])
        await review(c)
        identity = c.cards[0]["id"]
        for rev, text in enumerate(words[1:], 2):
            g.next = Outcome("fixture", {"action": "WAIT" if rev == 2 else "IGNORE"})
            ingest(c, rev, text)
            await review(c)
            packet = g.calls[-1]
            assert [e["text"] for e in packet["CONVERSATION"]] == words[:rev]
            assert packet["NEW_REVISIONS"] == [rev, rev]
            assert packet["REVIEWED_THROUGH"] == rev - 1
            assert packet["ACTIVE_QUESTION"]["answer"] == c.cards[0]["answer"]
            assert len(c.cards) == 1 and c.cards[0]["id"] == identity
        assert len(g.calls) == 6 and c.reviewed == 6
        assert logs[-1]["outcome"] == "unchanged" and logs[-1]["included_revisions"] == list(
            range(1, 7)
        )
        for _ in range(5):
            c.submit()
        assert len(g.calls) == 6
    finally:
        await c.finish()


@pytest.mark.asyncio
async def test_inflight_coverage_followup_and_final_flush(tmp_path):
    c, g, pub, saved, logs, _ = await setup(tmp_path)
    try:
        g.next = answer()
        g.release.clear()
        ingest(c, 1, "Count subsequences in s.")
        c.submit(trigger="initial")
        await g.entered.wait()
        for i, t in [(2, "Count duplicates separately."), (3, "Empty words count too.")]:
            ingest(c, i, t)
            c.submit(trigger="maximum_delay")
        assert len(g.calls) == 1 and c.pending.revision == 3
        g.next = answer("UPDATE", text="Include duplicate counts and empty words.")
        g.release.set()
        await c.runner
        assert len(g.calls) == 2 and len(c.cards) == 1
        assert [e["text"] for e in g.calls[1]["CONVERSATION"]] == [
            "Count subsequences in s.",
            "Count duplicates separately.",
            "Empty words count too.",
        ]
        assert g.calls[1]["NEW_REVISIONS"] == [2, 3] and "empty words" in c.cards[0]["answer"]
        assert logs[0]["followup_revision"] == 3
        ingest(c, 4, "Finally support Java 8.")
        g.next = answer(
            "UPDATE", text="Use Java 8 collections and retain duplicate/empty handling."
        )
        await c.finish()
        assert g.calls[-1]["NEW_REVISIONS"] == [4, 4] and logs[-2]["trigger"] == "final_flush"
        assert c.reviewed == 4 and saved[-1]["revision"] == 4
    finally:
        if not c.closed:
            await c.finish()


@pytest.mark.asyncio
async def test_two_questions_same_batch_validated_and_rollback(tmp_path):
    c, g, pub, saved, logs, _ = await setup(tmp_path)
    try:
        ingest(c, 1, "Explain mutexes. Separately explain composite indexes.")
        a = answer()
        b = answer(text="The leftmost prefix often determines useful seeks.")
        b.header["question"] = "Composite index filtering"
        g.next = Outcome(
            "fixture",
            a.header,
            a.lines,
            answers=[
                {"header": a.header, "lines": a.lines},
                {"header": b.header, "lines": b.lines},
            ],
        )
        await review(c)
        assert len(c.cards) == 2 and len({x["id"] for x in c.cards}) == 2
        assert len(logs[-1]["decisions"]) == 2
        before = list(c.cards)
        ingest(c, 2, "Why?")
        g.next = Outcome("fixture", error="Truncated response without done record")
        await review(c)
        assert c.cards == before and c.reviewed == 1
        assert logs[-1]["outcome"] == "failed" and pub[-1][0] == "discard"
        assert c.due(time.monotonic() + 100) is None
        c.submit()
        await c.runner
        assert len(g.calls) == 2  # same failed snapshot, no blind retry
        ingest(c, 3, "Explain why that index needs the leading key.")
        g.next = answer(start=3)
        await review(c)
        assert g.calls[-1]["NEW_REVISIONS"] == [2, 3]
    finally:
        await c.finish()


@pytest.mark.asyncio
async def test_pause_delayed_commit_continuous_and_initial_triggers(tmp_path):
    c, g, _, _, _, _ = await setup(tmp_path)
    try:
        ingest(c, 1, "Given a string s")
        c.dirty_since = c.changed_at = 100
        c.last_submit = 100
        c.activity_at = 100
        assert c.due(100.6) is None
        assert c.due(100.71) == "initial"
        g.next = answer()
        await review(c)
        ingest(c, 2, "and an array of words")
        c.dirty_since = c.changed_at = 200
        c.last_submit = 199
        c.activity_at = 200
        assert c.due(200.5) is None
        c.activity_at = 201.7
        c.changed_at = 201.7
        assert c.due(201.81) == "maximum_delay"
        c.changed_at = c.dirty_since = 300
        c.last_submit = 300
        c.activity_at = 299.1
        assert c.due(300.16) == "speech_pause"
        c.activity_at = 300
        c.pause()
        assert c.due(300.16) == "committed_pause"
        c.activity_at = None
        c.pause_revision = 0
        assert c.due(301.01) == "commit_pause"
    finally:
        await c.finish()


@pytest.mark.asyncio
async def test_long_context_nonoverlap_topic_boundary_and_revised_segment(tmp_path):
    c, g, _, _, _, _ = await setup(tmp_path)
    try:
        opening = "Design a service without locks or third-party identity."
        for i in range(1, 13):
            ingest(
                c,
                i,
                opening if i == 1 else f"Constraint {i}: " + "retain durable deletion intent " * 20,
            )
            g.next = answer() if i == 1 else Outcome("fixture", {"action": "IGNORE"})
            await review(c)
        packet = g.calls[-1]
        assert packet["CONVERSATION"][0]["text"] == opening
        assert opening not in " ".join(r[2] for r in c.recent)
        assert len(packet["CONVERSATION"]) == 12
        assert len({e["revision"] for e in packet["CONVERSATION"]}) == 12
        ingest(c, 13, "Instead retain deletion for 30 days.", segment="2")
        g.next = answer("UPDATE")
        await review(c)
        texts = [e["text"] for e in g.calls[-1]["CONVERSATION"]]
        assert texts[1] == "Instead retain deletion for 30 days." and "Constraint 2:" not in str(
            texts
        )
        ingest(c, 14, "Now explain Python tuples.")
        g.next = answer(start=14)
        await review(c)
        assert c.scenario == "Now explain Python tuples."
        assert c.messages(c.snapshot())[2]["content"].count(opening) == 0
    finally:
        await c.finish()


def test_multiple_protocol_coalesced_publication_state_and_bounds():
    def h(q):
        return (
            json.dumps({"action": "NEW", "question": q, "developing": False, "start_revision": 1})
            + "\n"
        )

    wire = (
        h("Mutex ownership")
        + '{"text":"One thread owns a mutex."}\n'
        + h("Semaphore permits")
        + '{"text":"A semaphore counts permits."}\n{"done":true}\n'
    )
    p = Parser()
    records = p.feed(wire)
    p.finish()
    texts = [r for r in records if "text" in r]
    assert [r.header["question"] for r in texts] == ["Mutex ownership", "Semaphore permits"]
    assert [r.index for r in texts] == [0, 1]
    assert texts[0].lines == ["One thread owns a mutex."]
    assert texts[1].lines == ["A semaphore counts permits."]
    for bad in [
        wire + "{}\n",
        h("Empty first") + h("Second"),
        (h("Question") + '{"text":"Answer."}\n') * 4 + '{"done":true}\n',
        '{"overflow":true}\n',
    ]:
        with pytest.raises(ProtocolError):
            p = Parser()
            p.feed(bad)
            p.finish()


@pytest.mark.asyncio
async def test_invalid_boundary_cannot_replace_previous_answer(tmp_path):
    c, g, pub, _, logs, _ = await setup(tmp_path)
    try:
        ingest(c, 1, "Explain mutexes.")
        g.next = answer()
        await review(c)
        old = list(c.cards)
        ingest(c, 2, "Explain semaphores.")
        g.next = answer(start=99)
        await review(c)
        assert c.cards == old and c.reviewed == 1
        assert "boundary" in logs[-1]["error"] and pub[-1][0] == "discard"
    finally:
        await c.finish()


@pytest.mark.asyncio
async def test_many_tiny_segments_bound_metadata_and_overflow_is_visible(tmp_path):
    c, g, _, _, _, status = await setup(tmp_path)
    try:
        for i in range(1, 514):
            ingest(c, i, "x")
        assert c.context_overflow and len(c.events) == 512
        assert len(c.recent) <= 512 and "context limit" in status[-1]
        c.submit()
        assert not g.calls
        c.reset()
        assert not c.context_overflow and not c.events
        ingest(c, 514, "New context")
        await review(c)
        assert [e["text"] for e in g.calls[-1]["CONVERSATION"]] == ["New context"]
    finally:
        await c.finish()


@pytest.mark.asyncio
async def test_session_multiple_drafts_and_failed_update_preserve_answer(tmp_path):
    from interview_helper.session import Session
    from interview_helper.storage import SessionStore

    s = Session(Config.load(tmp_path / "config.local.toml"))
    s.start(replay=True)
    await s.controller.gateway.close()
    g = Provider()
    s.controller.gateway = g
    try:
        g.next = answer()
        s.ingest("fixture", "Playback", "Explain buckets.", 0, 1)
        await review(s.controller)
        before = list(s.controller.cards)
        g.next = answer("UPDATE", text="This draft must not replace the previous answer.")
        g.next.error = "Truncated response without done record"
        s.ingest("fixture", "Playback", "Add empty words.", 1, 2)
        await review(s.controller)
        assert s.controller.cards == before and not s.drafts
        assert any("previous answer retained" in n["message"] for n in s.notices)
        for i in range(2):
            await s.publish("draft", {"id": f"draft-{i}", "request_id": "batch", "answer": "text"})
        assert len(s.drafts) == 2
        await s.publish("discard", {"request_id": "batch"})
        assert not s.drafts
        s.end()
        await s.end_task
        recovered = SessionStore.inspect(s.config.data_dir, s.store.id)
        assert [e["text"] for e in recovered["events"] if e.get("type") == "transcript"] == [
            "Explain buckets.",
            "Add empty words.",
        ]
    finally:
        if s.state != "ended":
            await s.shutdown()


@pytest.mark.asyncio
async def test_session_end_waits_for_final_capture_commit_and_review(tmp_path):
    from interview_helper.session import Session
    from interview_helper.storage import SessionStore

    s = Session(Config.load(tmp_path / "config.local.toml"))
    s.start(replay=True)
    await s.controller.gateway.close()
    g = Provider()
    s.controller.gateway = g
    g.next = answer()
    s.ingest("fixture", "Playback", "Count subsequences.", 0, 1)
    await review(s.controller)

    async def flush():
        await asyncio.sleep(0.01)
        s.ingest("fixture", "Playback", "Finally count empty words too.", 1, 2, final=True)
        g.next = answer("UPDATE", text="Include empty words and duplicates.")

    s._stop_capture = flush
    s.end()
    await s.end_task
    assert s.state == "ended" and s.controller.reviewed == 2
    assert g.calls[-1]["CONVERSATION"][-1]["text"] == "Finally count empty words too."
    data = SessionStore.inspect(s.config.data_dir, s.store.id)
    assert data["events"][-1]["commit"] == "final_flush"
    assert s.controller.cards[-1]["answer"] == "Include empty words and duplicates."
