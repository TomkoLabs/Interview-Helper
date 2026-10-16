"""Incremental strict NDJSON: only complete validated records are publishable."""

import json
import re


class ProtocolError(ValueError):
    pass


class Record(dict):
    """A wire record with immutable publication state for coalesced deltas."""

    def __init__(self, item, header, lines, index):
        super().__init__(item)
        self.header = dict(header or {})
        self.lines = list(lines)
        self.index = index


class Parser:
    def __init__(self):
        self.buffer = ""
        self.header = None
        self.lines = []
        self.done = False
        self.size = 0
        self.answers = []

    def feed(self, text):
        self.size += len(text)
        if self.size > 12000:
            raise ProtocolError("Response exceeds protocol size bound")
        self.buffer += text
        output = []
        while "\n" in self.buffer:
            line, self.buffer = self.buffer.split("\n", 1)
            if line.strip():
                output.append(self._record(line))
        return output

    def _record(self, line):
        if self.done:
            raise ProtocolError("Content after done")
        try:
            item = json.loads(line)
        except (ValueError, TypeError) as exc:
            raise ProtocolError("Malformed JSON record") from exc
        if not isinstance(item, dict):
            raise ProtocolError("Record must be an object")
        if item == {"overflow": True} and type(item["overflow"]) is bool:
            raise ProtocolError("More than three unanswered requests; split the review context")
        if "action" in item and self.header is not None:
            if self.header["action"] not in {"NEW", "UPDATE"} or not self.lines:
                raise ProtocolError("Missing answer before next question")
            if len(self.answers) >= 2 or item.get("action") != "NEW":
                raise ProtocolError("At most three answers; only the first may UPDATE")
            self.answers.append({"header": self.header, "lines": self.lines})
            self.header, self.lines = None, []
        if self.header is None:
            action = item.get("action")
            if not isinstance(action, str) or action not in {"WAIT", "IGNORE", "NEW", "UPDATE"}:
                raise ProtocolError("Missing decision")
            if action in {"NEW", "UPDATE"}:
                required = {"action", "question", "developing"}
                if not required <= set(item) or set(item) - required - {
                    "start_revision",
                    "segments",
                }:
                    raise ProtocolError("Invalid actionable header")
                refs = item.get("segments", [])
                if (
                    not isinstance(refs, list)
                    or len(refs) > 8
                    or any(not isinstance(ref, str) or not 1 <= len(ref) <= 80 for ref in refs)
                    or len(set(refs)) != len(refs)
                ):
                    raise ProtocolError("Invalid supporting segment references")
                if "start_revision" in item and (
                    action != "NEW"
                    or type(item["start_revision"]) is not int
                    or item["start_revision"] < 1
                ):
                    raise ProtocolError("Invalid question boundary")
                q = item["question"]
                if not isinstance(q, str) or not 3 <= len(q.strip()) <= 1200:
                    raise ProtocolError(
                        "Invalid question heading: expected 3–1200 nonblank characters"
                    )
                if type(item["developing"]) is not bool:
                    raise ProtocolError("Invalid developing flag")
            elif set(item) != {"action"}:
                raise ProtocolError("Unexpected decision fields")
            self.header = item
        elif item == {"done": True} and type(item["done"]) is bool:
            if self.header["action"] in {"NEW", "UPDATE"} and not self.lines:
                raise ProtocolError("Empty actionable answer")
            self.done = True
        elif set(item) == {"code", "language", "scope"} and self.header["action"] in {
            "NEW",
            "UPDATE",
        }:
            code, language, scope = item["code"], item["language"], item["scope"]
            if (
                not self.lines
                or any(line.startswith("```") for line in self.lines)
                or not isinstance(code, str)
                or not 1 <= len(code.strip()) <= 5000
                or "```" in code
                or not isinstance(language, str)
                or not re.fullmatch(r"[a-z][a-z0-9+#-]{0,19}", language)
                or scope not in ("snippet", "complete")
                or len(self.lines) >= 8
            ):
                raise ProtocolError("Invalid coherent code record")
            # Canonical safe storage format. Code is held back from drafts until
            # the complete response validates; the first text record streams now.
            self.lines.append(f"```{language} {scope}\n{code}\n```")
        elif set(item) == {"text"} and self.header["action"] in {"NEW", "UPDATE"}:
            value = item["text"]
            if (
                not isinstance(value, str)
                or not value.strip()
                or len(value) > 1800
                or "```" in value
            ):
                raise ProtocolError("Invalid answer text")
            if any(t in value.lower() for t in ("<think", "</think", "<script")):
                raise ProtocolError("Reasoning/unsafe protocol output")
            if len(self.lines) >= 8:
                raise ProtocolError("Too many answer lines")
            self.lines.append(value)
        else:
            raise ProtocolError("Unexpected answer record")
        return Record(item, self.header, self.lines, len(self.answers))

    def finish(self):
        records = []
        if self.buffer.strip():
            records.append(self._record(self.buffer))
            self.buffer = ""
        if not self.done:
            raise ProtocolError("Truncated response without done record")
        return records
