"""Bounded, transcript-linked reference state; never candidate-code state."""

from copy import deepcopy
import re
from .protocol import ProtocolError

ACK = re.compile(
    r"(?:ok(?:ay)?|yes|yeah|right|sure|thanks|thank you|mm[- ]?hmm|"
    r"(?:one|a) (?:second|moment)|question (?:one|two|three|four|five|\d+))[.! ,]*",
    re.I,
)
CODE = re.compile(r"```[a-z][a-z0-9+#-]{0,19} (?:snippet|complete)\n[\s\S]*?\n```")
MAX_FACTS = 24


def coding_capacity(events, active):
    if active and active.get("task_kind") == "coding":
        return True
    # This is a capacity allowance, not a task classifier. Give substantial
    # accumulated wording room even when ASR paraphrases operation/intent words.
    # The model still decides the task and should use only the space it needs.
    pending = [e for e in events if not active or e["revision"] > active["revision"]]
    speech = " ".join(e["text"] for e in pending)
    return len(speech.split()) >= 40 or bool(
        re.search(r"\b(implement|write|build|design|code|create)\b", speech, re.I)
    )


def refresh_answer(card):
    """Keep the backward-compatible text view honest as status changes."""
    if "guidance" not in card:
        return card
    card["answer"] = card["guidance"]
    ref = card.get("reference")
    if ref:
        label = (
            "Current IH reference"
            if ref["status"] == "current"
            else "Previous IH reference — " + ref["status"].replace("_", " ")
        )
        card["answer"] += "\n" + label + "\n" + ref["code"]
        if ref.get("notes"):
            card["answer"] += "\n" + ref["notes"]
    if card.get("latest_followup"):
        card["answer"] += "\n- Latest follow-up: " + card["latest_followup"]["text"]
    return card


def reference_pending(card, revision, failed=False, corrected_segment=None):
    """Retain the previous solution, visibly unchecked against newly captured speech."""
    card = deepcopy(card)
    reference = card.get("reference")
    if reference:
        if reference["status"] == "current":
            reference["status"] = "unreviewed"
            reference["pending_from"] = revision
        card["review_status"] = "failed" if failed else "pending"
        card["pending_revision"] = revision
    if corrected_segment:
        for fact in card.get("requirements", []):
            if corrected_segment in fact["segments"]:
                fact["evidence_status"] = "source_changed"
                if fact["status"] == "active":
                    fact["status"] = "source_changed"
    return refresh_answer(card)


def apply_reference(card, previous, header, lines, events, support=(), followup_only=False):
    """Called only after full provider/protocol/reference validation."""
    previous = previous or {}
    code = next((line for line in lines if CODE.fullmatch(line)), None)
    old_code = previous.get("reference")
    # Legacy saved/in-memory cards may contain only canonical fenced answer text.
    if not old_code:
        match = CODE.search(previous.get("answer", ""))
        if match:
            old_code = {
                "code": match.group(),
                "revision": previous["revision"],
                "status": "unreviewed",
            }
    coding = header.get("task") == "coding" or previous.get("task_kind") == "coding"
    effect = header.get("solution", "replace" if code else "preserve")
    if followup_only and (
        not previous or code or effect != "preserve" or header.get("_requirements")
    ):
        raise ProtocolError(
            "Follow-up-only updates cannot change the main solution or requirements"
        )
    if effect == "replace" and not code:
        raise ProtocolError("Replacing a reference requires validated code")
    if code and effect != "replace":
        raise ProtocolError("Code conflicts with reference update semantics")
    if effect in {"invalidate", "clear"} and not header.get("reason"):
        raise ProtocolError("Invalidating or clearing a reference requires a reason")
    reference = deepcopy(old_code)
    if code:
        reference = {
            "code": code,
            "notes": "\n".join(lines[lines.index(code) + 1 :]),
            "revision": card["revision"],
            "status": "current",
        }
    elif effect == "clear":
        reference = None
    elif reference:
        if effect == "invalidate":
            reference.update(status="needs_revision", reason=header["reason"])
        elif header.get("solution") == "preserve" and reference["status"] != "needs_revision":
            reference.update(status="current", checked_through=card["revision"])
            reference.pop("pending_from", None)
            reference.pop("reason", None)
        elif header.get("solution") is None and reference["status"] == "current":
            reference["status"] = "unreviewed"
        # Supporting points belong to the current explanation, not permanently
        # to the retained code. Replace them together when full guidance changes.
        if len(lines) > 1 and not followup_only:
            reference["notes"] = "\n".join(lines[1:])
    if coding or reference:
        card["task_kind"] = "coding" if coding else previous.get("task_kind", "brief")
        card["guidance"] = "\n".join(
            lines[: lines.index(code)] if code else lines[:1] if reference else lines
        )
        card["reference"] = reference
        card["reference_action"] = effect
        card["reference_reason"] = header.get("reason", "")
        card["review_status"] = "reviewed"
        if coding and previous:
            card["question"] = previous["question"]
        card["focus"] = header.get("focus") or (
            header["question"] if header["question"] != card["question"] else ""
        )
        refresh_answer(card)
    facts = deepcopy(previous.get("requirements", []))
    for change in header.get("_requirements", []):
        supersedes = change.get("supersedes", [])
        if not set(supersedes) <= {f["id"] for f in facts}:
            raise ProtocolError("Superseded requirement does not belong to the active task")
        for fact in facts:
            if fact["id"] in supersedes:
                fact["status"] = "superseded"
        if any(
            all(f.get(k) == change.get(k) for k in ("text", "kind", "segments"))
            and f["status"] == "active"
            for f in facts
        ):
            continue
        source = {e["segment_id"]: e for e in events}
        if not set(change["segments"]) <= source.keys():
            raise ProtocolError("Requirement evidence is outside the input snapshot")
        facts.append(
            {
                **change,
                "id": f"r{card['revision']}-{len(facts)}",
                "status": "active",
                "evidence_revisions": {s: source[s]["revision"] for s in change["segments"]},
            }
        )
    if len(facts) > MAX_FACTS:
        raise ProtocolError("Task requirement limit reached; full speech remains saved")
    if facts:
        card["requirements"] = facts
    if followup_only:
        # Keep the semantic main answer byte-for-byte, including conceptual cards.
        # Provider wording cannot redirect it merely by citing microphone support.
        for key in (
            "question",
            "guidance",
            "reference",
            "requirements",
            "task_kind",
            "focus",
            "review_status",
            "reference_action",
            "reference_reason",
            "developing",
        ):
            if key in previous:
                card[key] = deepcopy(previous[key])
            else:
                card.pop(key, None)
        card.setdefault("guidance", previous.get("answer", ""))
    followup = deepcopy(header.get("_followup", previous.get("latest_followup")))
    if followup:
        available = {e["segment_id"] for e in list(events) + list(support)}
        # Preserved follow-ups may cite older bounded context; NEW replacements must
        # be grounded in this exact snapshot, including optional supporting speech.
        if "_followup" in header and not set(followup["segments"]) <= available:
            raise ProtocolError("Latest follow-up evidence is outside the input snapshot")
        followup["revision"] = card["revision"]
    card["latest_followup"] = followup
    card.setdefault("guidance", "\n".join(lines))
    return refresh_answer(card)
