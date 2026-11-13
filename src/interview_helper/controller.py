"""Bounded latest-work controller; transcript storage lives outside this class."""

import asyncio
from collections import deque
from dataclasses import dataclass, field
from copy import deepcopy
from .coding import ACK, apply_reference, coding_capacity, reference_pending, refresh_answer
from .protocol import ProtocolError
import json
import hashlib
from pathlib import Path
import re
import time
import uuid

# A correction invalidates an in-flight draft, but never filters its speech.
CORRECTION = re.compile(r"\b(actually|correction|instead|without|i meant|not .{0,20}but)\b", re.I)
SHUTDOWN_REVIEW_GRACE = 1.0
PROMPT = (Path(__file__).parent / "prompts/interview.txt").read_text()


@dataclass
class Snapshot:
    revision: int
    request_id: str
    active_id: str | None
    epoch: int
    events: list
    new_from: int
    reviewed: int
    active: dict | None
    headings: list
    trigger: str
    digest: str
    retained_revisions: tuple
    microphone_events: list = field(default_factory=list)
    microphone_revision: int = 0
    microphone_reviewed: int = 0
    microphone_omitted_through: int = 0


class Controller:
    def __init__(
        self, config, gateway, publish, save, status, observe=None, microphone_context=None
    ):
        self.config, self.gateway = config, gateway
        self.publish, self.save, self.status = publish, save, status
        self.observe = observe or (lambda event: None)
        self.microphone_context = (
            bool(config.microphone and config.microphone_context)
            if microphone_context is None
            else microphone_context
        )
        self.microphone_events = deque()
        self.microphone_revision = self.microphone_reviewed = self.microphone_attempted = 0
        self.microphone_changed = 0.0
        self.microphone_omitted_through = 0
        self.recent = deque()
        self.events = []
        self.cards = []
        self.revision = self.reviewed = self.attempted = self.epoch = 0
        self.pending = self.runner = None
        self.last_submit = self.changed_at = self.dirty_since = 0.0
        self.activity_at = None
        self.pause_revision = 0
        self.stopping = self.closed = self.context_overflow = False
        self.last_snapshot = None
        self.inflight = None
        self.tick_task = asyncio.create_task(self._tick())

    @property
    def scenario(self):
        return " ".join(e["text"] for e in self.events)

    @property
    def unreviewed(self):
        return " ".join(e["text"] for e in self.events if e["revision"] > self.reviewed)

    def reset(self):
        self.events.clear()
        self.recent.clear()
        self.microphone_events.clear()
        self.microphone_reviewed = self.microphone_attempted = self.microphone_revision
        self.reviewed = self.attempted = self.revision
        self.pending = None
        self.context_overflow = False
        self.epoch += 1

    def pause(self):
        self.pause_revision = self.revision

    def activity(self, speaking):
        if speaking:
            self.activity_at = time.monotonic()

    def ingest_microphone(self, event):
        # Consent is captured at the session boundary. Replay/summary stay playback-only.
        if not self.microphone_context or not self.cards or self.closed:
            return
        text = event["text"].strip()
        if not text or ACK.fullmatch(text):
            return
        self.microphone_revision += 1
        self.microphone_changed = time.monotonic()
        self.microphone_events.append(
            {
                "segment_id": event["segment_id"],
                "text": text,
                "revision": self.microphone_revision,
                "start": event.get("start"),
                "end": event.get("end"),
                "playback_revision": self.revision,
                "received": self.microphone_changed,
            }
        )
        self.trim_microphone()

    def trim_microphone(self):
        limit = min(1500, self.config.context_chars // 4)
        while self.microphone_events and (
            len(self.microphone_events) > 12
            or sum(len(e["text"]) for e in self.microphone_events) > limit
            or time.monotonic() - self.microphone_events[0]["received"]
            > self.config.context_seconds
        ):
            removed = self.microphone_events.popleft()
            if removed["revision"] > self.microphone_reviewed:
                self.microphone_omitted_through = removed["revision"]

    def microphone_due(self):
        return (
            self.microphone_context
            and self.cards
            and self.microphone_revision > self.microphone_attempted
            and sum(
                len(e["text"])
                for e in self.microphone_events
                if e["revision"] > self.microphone_attempted
            )
            >= 24
        )

    def ingest(self, event):
        # Defense in depth: microphone/unknown source kinds never enter context.
        if event.get("source_kind", "playback") != "playback":
            return
        self.revision = event["revision"]
        t = time.monotonic()
        text = event["text"].strip()
        if not text or self.context_overflow:
            return
        if not self.dirty_since:
            self.dirty_since = t
        self.changed_at = t
        entry = {
            "revision": self.revision,
            "source": event["source_name"],
            "text": text,
            "start": event.get("start"),
            "end": event.get("end"),
        }
        # Committed segments are immutable in production. Revisions supplied by
        # recovery/replay replace the same segment in chronological position.
        entry["segment_id"] = event.get("segment_id", str(self.revision))
        source_revised = any(e["segment_id"] == entry["segment_id"] for e in self.events)
        if (
            self.cards
            and (self.cards[-1].get("reference") or self.cards[-1].get("requirements"))
            and (source_revised or not ACK.fullmatch(text))
        ):
            pending_card = reference_pending(
                self.cards[-1], self.revision, corrected_segment=entry["segment_id"]
            )
            self.save({"type": "hint", **pending_card})
            self.cards[-1] = pending_card
        before = list(self.events)
        corrected = False
        for i, old in enumerate(self.events):
            if old["segment_id"] == entry["segment_id"]:
                self.events[i] = entry
                corrected = True
                break
        if not corrected:
            self.events.append(entry)
        self.recent = deque(r for r in self.recent if r[4] != entry["segment_id"])
        self.recent.append((t, entry["source"], text, self.revision, entry["segment_id"]))
        while self.recent and (
            t - self.recent[0][0] > self.config.context_seconds
            or sum(len(x[2]) for x in self.recent) > self.config.context_chars
            or len(self.recent) > 512
        ):
            self.recent.popleft()
        if corrected or CORRECTION.search(text):
            self.epoch += 1
        if len(self.scenario) > self.config.scenario_chars or len(self.events) > 512:
            # Never send a truncated requirement. The full event is already on disk.
            self.events = before
            self.context_overflow = True
            self.pending = None
            self.epoch += 1
            self.status(
                "context limit: active scenario retained on disk; start a new question context"
            )
            return

    def snapshot(self, trigger="manual"):
        active = deepcopy(self.cards[-1]) if self.cards else None
        # Retained active wording plus recent conversation, once each. Earlier
        # unrelated context is retained only within the rolling window.
        recent = {
            r[4]: {"revision": r[3], "source": r[1], "text": r[2], "segment_id": r[4]}
            for r in self.recent
        }
        recent.update({e["segment_id"]: dict(e) for e in self.events})
        # Source revisions preserve normal chronological order; corrected segments
        # retain their original position within the active problem.
        order = [r[4] for r in self.recent if r[4] not in {e["segment_id"] for e in self.events}]
        events = [recent[k] for k in order] + [dict(e) for e in self.events]
        first = min(
            (e["revision"] for e in events if e["revision"] > self.reviewed), default=self.revision
        )
        headings = [
            {"id": c["id"], "question": c["question"], "revision": c["revision"]}
            for c in self.cards[-8:]
        ]
        self.trim_microphone()
        microphone_events = (
            [{k: v for k, v in e.items() if k != "received"} for e in self.microphone_events]
            if self.microphone_context
            else []
        )
        identity = [
            events,
            self.reviewed,
            active,
            self.epoch,
            microphone_events,
            self.microphone_reviewed,
        ]
        digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        return Snapshot(
            self.revision,
            uuid.uuid4().hex,
            active["id"] if active else None,
            self.epoch,
            events,
            first,
            self.reviewed,
            active,
            headings,
            trigger,
            digest,
            tuple(e["revision"] for e in self.events),
            microphone_events,
            self.microphone_revision,
            self.microphone_reviewed,
            self.microphone_omitted_through,
        )

    def review_now(self):
        if self.closed or self.stopping or self.context_overflow or not self.events:
            return False
        # A running request already reconsiders this snapshot. New speech replaces
        # the one pending snapshot; repeated clicks never create a second lane.
        if self.runner and not self.runner.done():
            if self.revision > self.attempted or self.microphone_due():
                self.submit(trigger="review_now")
            return True
        self.submit(trigger="review_now", force=True)
        return True

    def submit(self, trigger="manual", force=False):
        if (
            self.closed
            or self.context_overflow
            or (not self.unreviewed and not self.microphone_due() and not force)
        ):
            return
        s = self.snapshot(trigger)
        if s.digest == self.last_snapshot and not force:
            return
        self.last_snapshot = s.digest
        self.pending = s
        self.last_submit = time.monotonic()
        self.attempted = self.revision
        self.microphone_attempted = self.microphone_revision
        self.dirty_since = 0.0
        if not self.runner or self.runner.done():
            self.runner = asyncio.create_task(self._run())

    def due(self, now):
        # Coalesce candidate speech on the same lane, at most once per 8 seconds.
        # The existing model decides usefulness; no second classifier call.
        self.trim_microphone()
        if (
            self.microphone_due()
            and now - self.last_submit >= 8
            and now - self.microphone_changed >= 1
        ):
            return "microphone_support"
        if self.revision <= self.attempted or not self.dirty_since:
            return None
        # A final ASR commit after an observed audio pause should not wait another
        # whole silence interval. Without audio activity, use commit inactivity.
        quiet = now - (self.activity_at if self.activity_at is not None else self.changed_at)
        if self.pause_revision > self.attempted and now - self.changed_at >= 0.15:
            return "committed_pause"
        if quiet >= 1.0 and now - self.changed_at >= 0.15:
            return "speech_pause" if self.activity_at is not None else "commit_pause"
        if not self.cards and now - self.dirty_since >= 0.7:
            return "initial"
        if now - max(self.last_submit, self.dirty_since) >= self.config.review_seconds:
            return "maximum_delay"
        return None

    async def _tick(self):
        while not self.stopping:
            await asyncio.sleep(0.1)
            trigger = self.due(time.monotonic())
            if trigger:
                self.submit(trigger=trigger)

    def messages(self, s):
        active = (
            {k: s.active[k] for k in ("id", "question", "answer", "revision")} if s.active else None
        )
        if active:
            for key in (
                "task_kind",
                "reference",
                "requirements",
                "focus",
                "review_status",
                "latest_followup",
            ):
                if key in s.active:
                    active[key] = s.active[key]
            if s.active.get("reference"):
                active["answer"] = s.active.get("guidance", active["answer"])
            active["answer_origin"] = "AI-generated guidance; not transcript evidence"
        sources = {
            name: f"playback-{i + 1}"
            for i, name in enumerate(dict.fromkeys(e["source"] for e in s.events))
        }
        return [
            {"role": "system", "content": PROMPT},
            {
                "role": "user",
                "content": "EXPLICIT_CANDIDATE_JOB_CONTEXT (data):\n"
                + self.config.candidate_context,
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "CONVERSATION": [
                            {
                                "revision": e["revision"],
                                "segment_id": e["segment_id"],
                                "source": sources[e["source"]],
                                "source_kind": "playback",
                                "start": e.get("start"),
                                "end": e.get("end"),
                                "text": e["text"],
                            }
                            for e in s.events
                        ],
                        "MICROPHONE_OMITTED_THROUGH": s.microphone_omitted_through or None,
                        "MICROPHONE_SUPPORT": [
                            dict(e, source="microphone", source_kind="microphone")
                            for e in s.microphone_events
                        ],
                        "MICROPHONE_NEW_RANGE": [
                            min(
                                e["revision"]
                                for e in s.microphone_events
                                if e["revision"] > s.microphone_reviewed
                            ),
                            s.microphone_events[-1]["revision"],
                        ]
                        if any(e["revision"] > s.microphone_reviewed for e in s.microphone_events)
                        else None,
                        "MICROPHONE_ONLY_REVIEW": s.revision <= s.reviewed
                        and bool(s.microphone_events),
                        "NEW_REVISIONS": [s.new_from, s.revision]
                        if s.new_from > s.reviewed
                        else None,
                        "REVIEWED_THROUGH": s.reviewed,
                        "ACTIVE_FROM": s.retained_revisions[0] if s.retained_revisions else None,
                        "ACTIVE_QUESTION": active,
                        "RECENT_CARDS": s.headings,
                        "RESPONSE_CAPACITY": {
                            "style": "coding" if coding_capacity(s.events, s.active) else "brief",
                            "coding_tokens": self.config.coding_output_tokens,
                        },
                        "PLAYBACK_SPEAKER_ROLES": "audio paths, not identified people; playback requests govern the task; microphone is optional supporting context",
                    },
                    ensure_ascii=False,
                ),
            },
        ]

    def valid(self, s):
        active_id = self.cards[-1]["id"] if self.cards else None
        return not self.closed and s.epoch == self.epoch and s.active_id == active_id

    @staticmethod
    def followup_only(header, snapshot):
        if header.get("action") != "UPDATE":
            return False
        if header.get("update") == "followup":
            return True
        fresh_playback = any(
            e["revision"] > snapshot.reviewed and not ACK.fullmatch(e["text"])
            for e in snapshot.events
        )
        return bool(
            snapshot.microphone_events
            and not fresh_playback
            and header.get("update") != "correction"
        )

    async def _run(self):
        while self.pending:
            s, self.pending = self.pending, None
            self.inflight = s
            self.status("reviewing")

            async def line(host, header, lines):
                if not self.valid(s):
                    return
                if self.followup_only(header, s):
                    # The small structured follow-up publishes after full validation;
                    # never preview redirected prose over the retained main answer.
                    return
                if not self.references_valid(header, s) or (
                    header.get("action") == "NEW" and s.revision <= s.reviewed
                ):
                    return
                index = header.get("_index", 0)
                update = header["action"] == "UPDATE"
                if update and (not s.active or index):
                    return
                await self.publish(
                    "draft",
                    {
                        "id": s.active_id
                        if update
                        else s.request_id + (f"-{index}" if index else ""),
                        "question": header["question"],
                        "answer": "\n".join(lines),
                        "developing": header["developing"],
                        "state": "updating" if update else "generating",
                        "host": host,
                        "revision": s.revision,
                        "request_id": s.request_id,
                    },
                )

            result = await self.gateway.race(
                self.messages(s),
                s.request_id,
                line,
                self.config.strategy,
                current=lambda: self.valid(s)
                and (self.pending is None or self.pending.revision <= s.revision),
            )
            answers = result.answers or [{"header": result.header, "lines": result.lines}]
            error = result.error
            last_boundary = -1
            for i, answer in enumerate(answers):
                h = answer["header"]
                if not self.references_valid(h, s):
                    error = "Supporting segment references are outside the input snapshot"
                if h.get("action") == "UPDATE" and (not s.active or i):
                    error = "UPDATE requires the active question and must be first"
                if h.get("action") == "NEW" and s.revision <= s.reviewed:
                    error = "New tasks require unreviewed playback evidence"
                followup = h.get("_followup")
                if followup and self.followup_only(h, s):
                    playback_pending = {
                        e["segment_id"]
                        for e in s.events
                        if e["revision"] > s.reviewed and not ACK.fullmatch(e["text"])
                    }
                    if playback_pending and not playback_pending.intersection(followup["segments"]):
                        error = (
                            "Pending playback follow-up takes priority over microphone commentary"
                        )
                start = h.get("start_revision")
                if start is not None:
                    if start not in s.retained_revisions:
                        error = "Question boundary is outside the retained problem"
                    elif s.retained_revisions.index(start) < last_boundary:
                        error = "Question boundaries must be chronological"
                    else:
                        last_boundary = s.retained_revisions.index(start)
            prepared = []
            if not error:
                try:
                    for a in answers:
                        h = a["header"]
                        prepared.append(
                            apply_reference(
                                {"question": h.get("question", ""), "revision": s.revision},
                                s.active if h.get("action") == "UPDATE" else None,
                                h,
                                a["lines"],
                                s.events,
                                support=s.microphone_events,
                                followup_only=self.followup_only(h, s),
                            )
                            if h.get("action") in {"NEW", "UPDATE"}
                            else {}
                        )
                except ProtocolError as exc:
                    error = str(exc)
            stale = not self.valid(s)
            outcome = (
                "superseded"
                if stale
                else "rejected"
                if error
                and (not result.error or result.diagnostics.get("failure_type") == "ProtocolError")
                else "failed"
                if error
                else "unchanged"
                if result.header.get("action") in {"IGNORE", "WAIT"}
                else "validated"
            )
            try:
                self.observe(
                    {
                        "type": "review",
                        "request_id": s.request_id,
                        "snapshot_hash": s.digest,
                        "revision": s.revision,
                        "new_range": [s.new_from, s.revision],
                        "included_revisions": [e["revision"] for e in s.events],
                        "included_segments": [e["segment_id"] for e in s.events],
                        "target_card_id": s.active_id,
                        "reviewed_before": s.reviewed,
                        "microphone_included_segments": [
                            e["segment_id"] for e in s.microphone_events
                        ],
                        "microphone_omitted_through": s.microphone_omitted_through or None,
                        "microphone_reviewed_before": s.microphone_reviewed,
                        "microphone_input_revision": s.microphone_revision,
                        "trigger": s.trigger,
                        "followup_revision": self.revision if self.revision > s.revision else None,
                        "host": result.host,
                        "action": result.header.get("action"),
                        "decisions": [
                            {
                                "action": a["header"].get("action"),
                                "segments": a["header"].get("segments", []),
                                "card_id": s.active_id
                                if a["header"].get("action") == "UPDATE"
                                else s.request_id + (f"-{i}" if i else ""),
                            }
                            for i, a in enumerate(answers)
                        ],
                        "decision_origin": "model",
                        "heading_origin": "model" if result.header.get("question") else None,
                        "outcome": outcome,
                        "error": error,
                        "stale": stale,
                        "first_useful_seconds": result.first_useful,
                        "complete_seconds": result.complete,
                        "queue_seconds": result.queue_seconds,
                        "usage": result.usage,
                        "diagnostics": result.diagnostics,
                        "timings": result.timings,
                    }
                )
            except OSError:
                await self.publish(
                    "discard", {"request_id": s.request_id, "error": "Review metadata save failed"}
                )
                self.pending = None
                return
            if stale or error:
                if error and not stale and self.cards and self.cards[-1].get("reference"):
                    failed_card = reference_pending(self.cards[-1], self.revision, failed=True)
                    try:
                        self.save({"type": "hint", **failed_card})
                        self.cards[-1] = failed_card
                    except OSError:
                        self.pending = None
                        return
                await self.publish(
                    "discard", {"request_id": s.request_id, "error": error, "stale": stale}
                )
                self.status("stale response ignored" if stale else "failed: " + error)
            else:
                for i, answer in enumerate(answers):
                    h, lines = answer["header"], answer["lines"]
                    action = h.get("action")
                    if action not in {"NEW", "UPDATE"}:
                        self.status(action.lower() if action else "failed: missing decision")
                        continue
                    update = action == "UPDATE"
                    card = {
                        "id": s.active_id if update else s.request_id + (f"-{i}" if i else ""),
                        "question": h["question"],
                        "answer": "\n".join(lines),
                        "developing": h["developing"],
                        "state": "complete",
                        "supporting_segments": h.get("segments", []),
                        "host": result.host,
                        "revision": s.revision,
                        "request_id": s.request_id,
                        "first_useful_seconds": result.first_useful,
                        "complete_seconds": result.complete,
                        "queue_seconds": result.queue_seconds,
                        "usage": result.usage,
                        "diagnostics": result.diagnostics,
                        "timings": result.timings,
                    }
                    card.update(prepared[i])
                    pending_material = [
                        e["revision"]
                        for e in self.events
                        if e["revision"] > s.revision and not ACK.fullmatch(e["text"])
                    ]
                    if pending_material and card.get("reference"):
                        # Anchor uncertainty at the first uncovered requirement,
                        # not a later acknowledgment or independent task boundary.
                        card = reference_pending(card, min(pending_material))
                        card["pending_revision"] = self.revision
                    unchanged = update and all(
                        card[k] == s.active[k] for k in ("question", "answer", "developing")
                    )
                    card["publication"] = (
                        "unchanged" if unchanged else "updated" if update else "new"
                    )
                    try:
                        self.save({"type": "hint", **card})
                    except OSError:
                        await self.publish(
                            "discard",
                            {
                                "request_id": s.request_id,
                                "error": "Hint save failed; retained for retry",
                            },
                        )
                        self.status("failed: hint save failed")
                        self.pending = None
                        return
                    if update:
                        self.cards[-1] = card
                    else:
                        if self.cards and "start_revision" in h:
                            prior = deepcopy(self.cards[-1])
                            ref = prior.get("reference")
                            if (
                                ref
                                and ref.get("status") == "unreviewed"
                                and ref.get("pending_from", 0) >= h["start_revision"]
                            ):
                                ref["status"] = "current"
                                ref.pop("pending_from", None)
                                prior["review_status"] = "reviewed"
                                refresh_answer(prior)
                                try:
                                    self.save({"type": "hint", **prior})
                                except OSError:
                                    self.pending = None
                                    return
                                self.cards[-1] = prior
                        self.microphone_events.clear()
                        self.microphone_reviewed = self.microphone_attempted = (
                            self.microphone_revision
                        )
                        self.cards.append(card)
                        self.cards = self.cards[-200:]
                        # Only a validated model boundary resets active wording.
                        # Legacy headers without a boundary retain full context.
                        if "start_revision" in h:
                            pos = next(
                                j
                                for j, e in enumerate(self.events)
                                if e["revision"] == h["start_revision"]
                            )
                            self.events = self.events[pos:]
                    await self.publish("card", card)
                    self.status("ready")
                self.reviewed = max(self.reviewed, s.revision)
                self.microphone_reviewed = max(self.microphone_reviewed, s.microphone_revision)
                # Only discard exact acknowledgment-only segments after successful
                # review; never summarize or silently trim substantive requirements.
                if self.cards and self.cards[-1].get("task_kind") == "coding":
                    pinned = {
                        ref for f in self.cards[-1].get("requirements", []) for ref in f["segments"]
                    }
                    self.events = [
                        e
                        for i, e in enumerate(self.events)
                        if i == 0
                        or e["revision"] > self.reviewed
                        or e["segment_id"] in pinned
                        or not ACK.fullmatch(e["text"])
                    ]
            self.inflight = None
            # Never replay the same failed snapshot on a timer. New speech still
            # receives one follow-up; failures keep its uncovered context intact.
            if self.pending:
                self.pending = self.snapshot(self.pending.trigger)
                self.last_snapshot = self.pending.digest
            elif self.stopping and self.revision > s.revision:
                self.submit(trigger="final_flush")

    @staticmethod
    def references_valid(header, snapshot):
        return set(header.get("segments", [])) <= {
            e["segment_id"] for e in snapshot.events + snapshot.microphone_events
        }

    async def finish(self):
        cancelled = None
        self.stopping = True
        await self.tick_task
        if self.revision > self.attempted or self.microphone_due():
            self.submit(trigger="final_flush")
        if self.runner:
            _, pending = await asyncio.wait({self.runner}, timeout=SHUTDOWN_REVIEW_GRACE)
            if pending:
                cancelled = self.inflight
                self.closed = True
                self.pending = None
                self.runner.cancel()
                await asyncio.gather(self.runner, return_exceptions=True)
        self.closed = True
        self.observe(
            {
                "type": "review_shutdown",
                "cancelled_request_id": cancelled.request_id if cancelled else None,
                "cancelled_input_revision": cancelled.revision if cancelled else None,
                "revision": self.revision,
                "reviewed_through": self.reviewed,
                "microphone_reviewed_through": self.microphone_reviewed,
                "microphone_revision": self.microphone_revision,
                "unreviewed_range": [self.reviewed + 1, self.revision]
                if self.reviewed < self.revision
                else None,
            }
        )
        if self.reviewed < self.revision:
            self.status("stopped; unreviewed transcript tail saved")
        await self.gateway.close()
