"""Synthetic source-policy and buffer regressions; no interview text or model calls."""

from copy import deepcopy
import json
from types import SimpleNamespace

import numpy as np
import pytest

from interview_helper.asr import Backend, trim_microphone_committed
from interview_helper.coding import ACK, apply_reference
from interview_helper.gateway import Outcome
from interview_helper.protocol import Parser, ProtocolError
from interview_helper.vendor.local_agreement import OnlineASRProcessor
from interview_helper.vendor.timed import ASRToken
from test_live_review import setup, ingest, review, answer
from test_reliability import microphone_event


@pytest.mark.parametrize(
    "problem,main,comment,help_text",
    [
        (
            "Count matching words",
            "Scan the text for each word with two pointers.",
            "Would recursion help with matching?",
            "Iteration suffices; recursion adds stack space.",
        ),
        (
            "Minimum clock gap",
            "Sort minutes since midnight; check neighbors and wraparound.",
            "Should I convert everything to Unix timestamps?",
            "Dates are unnecessary; use minutes since midnight.",
        ),
        (
            "Repeated number output",
            "Use nested loops to repeat each outer value.",
            "Which loop variable should I print inside?",
            "Print the outer value; the inner counter controls repetitions.",
        ),
    ],
)
async def test_mic_help_preserves_main_and_never_streams_redirected_prose(
    tmp_path, problem, main, comment, help_text
):
    c, g, published, _, _, _ = await setup(tmp_path)
    try:
        ingest(c, 1, problem)
        g.next = answer(text="TL;DR: " + main)
        g.next.header.update(question=problem, task="coding", solution="replace")
        g.next.lines += ["```java snippet\nint result = 0;\n```", "- Assumes valid input."]
        await review(c)
        old = deepcopy(c.cards[0])
        assert not old.get("focus")
        c.microphone_context = True
        c.ingest_microphone(microphone_event(1, comment))
        g.next = answer("UPDATE", text="TL;DR: Redirected candidate speculation.")
        g.next.header.update(
            question="Different focus",
            focus="Recursion redirects the main topic",
            solution="preserve",
            segments=["m1"],
            _followup={"text": help_text, "segments": ["m1"]},
        )
        published.clear()
        await review(c)
        card = c.cards[0]
        for key in ("question", "guidance", "reference", "requirements", "focus"):
            assert card.get(key) == old.get(key)
        assert card["latest_followup"]["text"] == help_text
        assert not any(kind == "draft" for kind, _ in published)
        assert c.microphone_reviewed == c.microphone_revision == 1
        assert "Redirected" not in card["answer"]
    finally:
        await c.finish()


async def test_playback_constraint_and_independent_correction_can_change_reference(tmp_path):
    c, g, _, _, _, _ = await setup(tmp_path)
    try:
        ingest(c, 1, "Count matching words, including empty words.")
        g.next = answer(text="Scan each word.")
        g.next.header.update(task="coding", solution="replace")
        g.next.lines.append("```java snippet\nint count = 0; // incomplete fixture\n```")
        await review(c)
        c.microphone_context = True
        c.ingest_microphone(microphone_event(1, "Does that code count empty words correctly?"))
        g.next = answer("UPDATE", text="Count a word when its matched length equals its length.")
        g.next.header.update(
            update="correction",
            solution="replace",
            segments=["1", "m1"],
            reason="The reference omitted the required empty-word case.",
        )
        g.next.lines.append("```java snippet\nif (matched == word.length()) count++;\n```")
        await review(c)
        assert "matched ==" in c.cards[0]["reference"]["code"]
        ingest(c, 2, "Now prohibit rescanning the large fixed text for each batch.")
        g.next = answer("UPDATE", text="Index text positions once; reuse them across batches.")
        g.next.header.update(
            solution="invalidate", reason="Per-word full scans violate the new requirement."
        )
        await review(c)
        assert c.cards[0]["reference"]["status"] == "needs_revision"
        assert "Index text" in c.cards[0]["guidance"]
    finally:
        await c.finish()


@pytest.mark.parametrize("change", ["code", "requirements"])
def test_followup_scope_cannot_change_code_or_launder_candidate_requirement(change):
    previous = {"question": "Stable problem", "revision": 1, "guidance": "Stable approach"}
    h = {"action": "UPDATE", "question": "Speculation", "solution": "preserve"}
    lines = ["Candidate idea"]
    if change == "code":
        h["solution"] = "replace"
        lines.append("```java snippet\nint different = 1;\n```")
    else:
        h["_requirements"] = [
            {"text": "Recursion is mandatory", "kind": "requirement", "segments": ["p1"]}
        ]
    with pytest.raises(ProtocolError, match="Follow-up-only"):
        apply_reference({"revision": 1}, previous, h, lines, [], followup_only=True)


async def test_playback_question_has_priority_and_navigation_has_no_mic_review(tmp_path):
    c, g, _, _, logs, _ = await setup(tmp_path)
    try:
        ingest(c, 1, "Count matching words.")
        g.next = answer()
        await review(c)
        c.microphone_context = True
        for i, text in enumerate(["Okay.", "One second.", "Question two"]):
            c.ingest_microphone(microphone_event(i, text))
        assert not c.microphone_events and not c.microphone_due()
        assert ACK.fullmatch("Question two") and not ACK.fullmatch("Question two requires sorting.")
        c.ingest_microphone(microphone_event(5, "Should I use recursion for this?"))
        ingest(c, 2, "Explain why your algorithm is correct.")
        old = deepcopy(c.cards[0])
        g.next = answer("UPDATE")
        g.next.header.update(
            update="followup", _followup={"text": "Iteration is enough.", "segments": ["m5"]}
        )
        await review(c)
        assert c.cards[0] == old and c.reviewed == 1
        assert "takes priority" in logs[-1]["error"]
        # WAIT does not remove the previous explanation/reference.
        g.next = Outcome("fixture", {"action": "WAIT"})
        c.review_now()
        await c.runner
        assert c.cards[0] == old
    finally:
        await c.finish()


def test_supporting_points_have_one_current_owner_when_code_is_retained():
    old = apply_reference(
        {"question": "Lookup", "revision": 1},
        None,
        {"question": "Lookup", "task": "coding", "solution": "replace"},
        [
            "TL;DR: Use an ID map.",
            "```java snippet\nStudent s = byId.get(id);\n```",
            "- Time O(n) per lookup.",
        ],
        [],
    )
    new = apply_reference(
        {"question": "Lookup", "revision": 2},
        old,
        {"question": "Lookup", "solution": "preserve"},
        [
            "TL;DR: Use an ID map.",
            "- O(1) average per lookup; O(n) storage.",
            "- n is the number of stored students; IDs are non-null.",
        ],
        [],
    )
    assert new["reference"]["code"] == old["reference"]["code"]
    assert "Time O(n) per lookup" not in new["answer"]
    assert new["answer"].count("O(1) average") == 1
    assert new["answer"].index("```java") < new["answer"].index("O(1) average")


def test_update_scope_protocol_is_explicit_and_correction_needs_reason():
    for update in ["followup", "correction"]:
        h = {
            "action": "UPDATE",
            "question": "Existing problem",
            "developing": False,
            "update": update,
        }
        if update == "correction":
            with pytest.raises(ProtocolError, match="explanation"):
                Parser().feed(json.dumps(h) + "\n")
            h["reason"] = "The old reference omitted a required edge case."
        p = Parser()
        p.feed(
            json.dumps(h)
            + "\n"
            + json.dumps({"text": "Complete sentence."})
            + "\n"
            + json.dumps({"done": True})
            + "\n"
        )
        p.finish()
        assert p.header["update"] == update


class StableBackend:
    sep = ""
    tokenizer = None
    confidence_validation = False
    buffer_trimming = "segment"
    buffer_trimming_sec = 25

    def transcribe(self, audio, init_prompt=""):
        return [ASRToken(i, i + 0.8, f" word{i}") for i in range(int(len(audio) / 16000))]

    def ts_words(self, tokens):
        return tokens

    def segments_end_ts(self, tokens):
        return [t.end for t in tokens]


def test_guard_reproduction_uses_real_localagreement_retained_committed_audio():
    online = OnlineASRProcessor(StableBackend())
    for _ in range(5):
        online.insert_audio_chunk(np.ones(16000, dtype=np.float32))
        online.process_iter()
    online.insert_audio_chunk(np.ones(17600, dtype=np.float32))
    assert Backend.buffer_trimming_sec == 25
    assert len(online.audio_buffer) > 6 * 16000  # Old guard reset despite stable progress.
    assert online.committed and online.committed[-1].end > 3
    pending = list(online.transcript_buffer.buffer)
    end = online.get_audio_buffer_end_time()
    trim_microphone_committed(online)
    assert len(online.audio_buffer) < 3 * 16000
    assert online.transcript_buffer.buffer == pending
    assert online.get_audio_buffer_end_time() == pytest.approx(end)
    assert online.committed[-1].end == pytest.approx(online.buffer_time_offset)


def test_guard_keeps_uncommitted_loss_bound_and_never_trims_future_or_unstable_audio():
    online = OnlineASRProcessor(StableBackend())
    online.insert_audio_chunk(np.ones(100000, dtype=np.float32))
    before = online.audio_buffer.copy()
    trim_microphone_committed(online)
    assert np.array_equal(online.audio_buffer, before) and len(online.audio_buffer) > 6 * 16000
    online.committed = [SimpleNamespace(end=999)]
    trim_microphone_committed(online)
    assert np.array_equal(online.audio_buffer, before)


@pytest.mark.parametrize("starved", [False, True])
async def test_microphone_guard_through_real_worker_progress_and_starvation(tmp_path, starved):
    import asyncio
    import time
    from interview_helper.asr import Recognizer
    from interview_helper.audio import Capture, Monitor
    from interview_helper.config import Config

    r = Recognizer(Config.load(tmp_path / "none"))
    r.backend = StableBackend()
    capture = Capture(
        Monitor("synthetic-clean", "Microphone", ""),
        lambda *_: None,
        time.monotonic(),
        microphone=True,
    )
    states, tokens = [], []

    async def emit(batch, *_):
        tokens.extend(batch)

    if starved:
        await r.lock.acquire()
    task = asyncio.create_task(
        r.run_source(capture, emit, lambda state, data: states.append((state, data)))
    )
    try:
        # Synthetic PCM and a deterministic backend; no audio device/model is used.
        for i in range(120):
            await capture.queue.put((i / 10, np.full(1600, 0.1, dtype=np.float32)))
        for i in range(11):
            await capture.queue.put((12 + i / 10, np.zeros(1600, dtype=np.float32)))
        capture.stopping = True
        await asyncio.wait_for(task, 3)
        if starved:
            assert any(state == "deferred" for state, _ in states)
            assert any(state == "gap" and "6s" in data["error"] for state, data in states)
            assert not tokens and r.lock.locked()
        else:
            assert tokens and any(state == "ready" for state, _ in states)
            assert not any(state == "gap" for state, _ in states)
    finally:
        if starved:
            r.lock.release()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
