"""Fsync'd journals are authoritative; readable views can be rebuilt."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import uuid

SESSION_ID = re.compile(r"^\d{8}T\d{6}Z-[a-f0-9]{8}$")


def now():
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path, value):
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as f:
        os.chmod(temporary, 0o600)
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    temporary.replace(path)
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def read_journal(path):
    """Tolerate only a partial last record, never corruption in the middle."""
    if not path.exists():
        return [], False
    records = []
    with path.open("rb") as f:
        for line in f:
            if not line.endswith(b"\n"):
                return records, True
            records.append(json.loads(line))
    return records, False


def transcript_view(records):
    latest = {}
    for e in records:
        if e["type"] == "transcript":
            latest[e["segment_id"]] = e
    return sorted(latest.values(), key=lambda e: (e["start"], e["revision"]))


SCOPE = "Captured playback / remote conversation (microphone excluded)\n\n"


class ReadableText:
    """Bounded paragraph state; no wording changes or inferred speaker labels."""

    def __init__(self):
        self.previous = None
        self.characters = 0
        self.paragraph_start = 0

    def append(self, event):
        if event["type"] == "gap":
            self.previous = None
            return "\n\n[CAPTURE GAP] " + event["reason"] + "\n\n"
        if event["type"] != "transcript":
            return ""
        text = event["text"].strip()
        if not text:
            return ""
        previous = self.previous
        boundary = (
            previous is None
            or event["source"] != previous["source"]
            or event["start"] - previous["end"] > 3
            or (
                (self.characters >= 500 or event["start"] - self.paragraph_start >= 30)
                and previous["text"].rstrip().endswith((".", "?", "!"))
            )
        )
        if boundary:
            mins, secs = divmod(event["start"], 60)
            prefix = ("\n\n" if previous else "") + f"[{int(mins):02d}:{secs:05.2f}] "
            self.characters = 0
            self.paragraph_start = event["start"]
        else:
            prefix = "" if text[0] in ",.;:?!)]}" else " "
        self.characters += len(text)
        self.previous = event
        return prefix + text


def readable(records):
    # Latest revisions are authoritative. Gaps stay in chronological context.
    events = transcript_view(records) + [e for e in records if e["type"] == "gap"]
    events.sort(key=lambda e: e.get("start", e.get("at", float("inf"))))
    view = ReadableText()
    return SCOPE + "".join(view.append(e) for e in events).rstrip() + "\n"


def rebuild_readable(path):
    records, partial = read_journal(path / "transcript.jsonl")
    text = readable(records)
    if partial:
        text += "\n[RECOVERY] Incomplete final journal record excluded.\n"
    temporary = path / "transcript.txt.tmp"
    with temporary.open("w", encoding="utf-8") as f:
        os.chmod(temporary, 0o600)
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    temporary.replace(path / "transcript.txt")
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    return text


class SessionStore:
    def __init__(self, root: Path, metadata=None):
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(root, 0o700)
        self.id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:8]
        self.path = root / self.id
        self.path.mkdir(mode=0o700)
        self.metadata = {
            "id": self.id,
            "started": now(),
            "status": "recording",
            "scope": "playback only; microphone excluded",
            **(metadata or {}),
        }
        atomic_json(self.path / "metadata.json", self.metadata)
        self.events = self._open("transcript.jsonl")
        self.hints = self._open("hints.jsonl")
        self.text = self._open("transcript.txt")
        self.text.write(SCOPE.encode())
        self.readable_state = ReadableText()
        self.view_error = None
        self._sync(self.text)
        self.closed = False

    def _open(self, name):
        f = (self.path / name).open("xb", buffering=0)
        os.chmod(self.path / name, 0o600)
        return f

    @staticmethod
    def _sync(f):
        f.flush()
        os.fsync(f.fileno())

    def append(self, event, hint=False):
        f = self.hints if hint else self.events
        data = (json.dumps(event, ensure_ascii=False) + "\n").encode()
        start = f.tell()
        try:
            if f.write(data) != len(data):
                raise OSError("Short journal write")
            self._sync(f)
        except OSError:
            # Keep the journal recoverable if a disk fills during a record.
            f.truncate(start)
            raise
        if not hint:
            try:
                line = self.readable_state.append(event).encode()
                if self.text.write(line) != len(line):
                    raise OSError("Short transcript view write")
                self._sync(self.text)
            except OSError:
                # The journal is already durable. Do not enqueue the same event
                # twice or interrupt capture because a derived view failed.
                self.view_error = "Readable transcript write failed; journal saved. End session to rebuild, or download/recover from Saved sessions."

    def close(self, status="ended"):
        if self.closed:
            return
        try:
            self.text.close()
            try:
                rebuild_readable(self.path)
                self.view_error = None
            except (OSError, ValueError, KeyError):
                self.view_error = "Readable transcript finalization failed; journal retained. Use Saved sessions download or recover --write-view."
            self.metadata.update(status=status, ended=now(), readable_error=self.view_error)
            atomic_json(self.path / "metadata.json", self.metadata)
        finally:
            for f in (self.events, self.hints, self.text):
                f.close()
            self.closed = True

    @staticmethod
    def inspect(root, session_id):
        if not SESSION_ID.fullmatch(session_id):
            raise ValueError("Invalid session ID")
        path = root / session_id
        if path.is_symlink() or not path.is_dir():
            raise ValueError("Session does not exist")
        metadata = json.loads((path / "metadata.json").read_text())
        events, partial = read_journal(path / "transcript.jsonl")
        hints, partial_hint = read_journal(path / "hints.jsonl")
        return {
            "metadata": metadata,
            "transcript_path": str(path / "transcript.txt"),
            "readable": readable(events),
            "events": events,
            "hints": hints,
            "partial_tail": partial or partial_hint,
            "interrupted": metadata["status"] == "recording",
        }
