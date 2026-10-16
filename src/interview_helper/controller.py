"""Bounded latest-work controller; transcript storage lives outside this class."""

import asyncio
from collections import deque
from dataclasses import dataclass
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


class Controller:
    def __init__(self, config, gateway, publish, save, status, observe=None):
        self.config, self.gateway = config, gateway
        self.publish, self.save, self.status = publish, save, status
        self.observe = observe or (lambda event: None)
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
        self.reviewed = self.attempted = self.revision
        self.pending = None
        self.context_overflow = False
        self.epoch += 1

    def pause(self):
        self.pause_revision = self.revision

    def activity(self, speaking):
        if speaking:
            self.activity_at = time.monotonic()

    def ingest(self, event):
        self.revision = event["revision"]
        t = time.monotonic()
        text = event["text"].strip()
        if not text or self.context_overflow:
            return
        if not self.dirty_since:
            self.dirty_since = t
        self.changed_at = t
        entry = {"revision": self.revision, "source": event["source_name"], "text": text}
        # Committed segments are immutable in production. Revisions supplied by
        # recovery/replay replace the same segment in chronological position.
        entry["segment_id"] = event.get("segment_id", str(self.revision))
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
        active = self.cards[-1].copy() if self.cards else None
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
        identity = [events, self.reviewed, active, self.epoch]
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
        )

    def review_now(self):
        if self.closed or self.stopping or self.context_overflow or not self.events:
            return False
        # A running request already reconsiders this snapshot. New speech replaces
        # the one pending snapshot; repeated clicks never create a second lane.
        if self.runner and not self.runner.done():
            if self.revision > self.attempted:
                self.submit(trigger="review_now")
            return True
        self.submit(trigger="review_now", force=True)
        return True

    def submit(self, trigger="manual", force=False):
        if self.closed or self.context_overflow or (not self.unreviewed and not force):
            return
        s = self.snapshot(trigger)
        if s.digest == self.last_snapshot and not force:
            return
        self.last_snapshot = s.digest
        self.pending = s
        self.last_submit = time.monotonic()
        self.attempted = self.revision
        self.dirty_since = 0.0
        if not self.runner or self.runner.done():
            self.runner = asyncio.create_task(self._run())

    def due(self, now):
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
                                "text": e["text"],
                            }
                            for e in s.events
                        ],
                        "NEW_REVISIONS": [s.new_from, s.revision]
                        if s.new_from > s.reviewed
                        else None,
                        "REVIEWED_THROUGH": s.reviewed,
                        "ACTIVE_FROM": s.retained_revisions[0] if s.retained_revisions else None,
                        "ACTIVE_QUESTION": active,
                        "RECENT_CARDS": s.headings,
                        "PLAYBACK_SPEAKER_ROLES": "unknown; may contain both sides; microphone unavailable",
                    },
                    ensure_ascii=False,
                ),
            },
        ]

    def valid(self, s):
        active_id = self.cards[-1]["id"] if self.cards else None
        return not self.closed and s.epoch == self.epoch and s.active_id == active_id

    async def _run(self):
        while self.pending:
            s, self.pending = self.pending, None
            self.inflight = s
            self.status("reviewing")

            async def line(host, header, lines):
                if not self.valid(s):
                    return
                if not self.references_valid(header, s):
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
                start = h.get("start_revision")
                if start is not None:
                    if start not in s.retained_revisions:
                        error = "Question boundary is outside the retained problem"
                    elif s.retained_revisions.index(start) < last_boundary:
                        error = "Question boundaries must be chronological"
                    else:
                        last_boundary = s.retained_revisions.index(start)
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
                await self.publish("discard", {"request_id": s.request_id, "error": error})
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
        return set(header.get("segments", [])) <= {e["segment_id"] for e in snapshot.events}

    async def finish(self):
        cancelled = None
        self.stopping = True
        await self.tick_task
        if self.revision > self.attempted:
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
                "unreviewed_range": [self.reviewed + 1, self.revision]
                if self.reviewed < self.revision
                else None,
            }
        )
        if self.reviewed < self.revision:
            self.status("stopped; unreviewed transcript tail saved")
        await self.gateway.close()
