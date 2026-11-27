"""Focused content/protocol contracts; browser selection checks have a separate harness."""

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from interview_helper.protocol import Parser, ProtocolError
from interview_helper.gateway import Outcome
from test_live_review import setup, ingest, review, answer


async def test_substantive_followup_keeps_code_and_filler_keeps_cue(tmp_path):
    c, provider, published, saved, _, _ = await setup(tmp_path)
    try:
        ingest(c, 1, "Implement a queue with a caller-supplied capacity.")
        provider.next = answer(text="Solution in brief: Check capacity before accepting an item.")
        provider.next.header.update(task="coding", solution="replace")
        provider.next.lines += [
            "```java snippet\nboolean fits(int size) { return size < limit; }\n```"
        ]
        await review(c)
        first = c.cards[0]
        assert not first["latest_followup"]
        ingest(c, 2, "What if its size equals the limit?")
        provider.next = answer("UPDATE", text=first["guidance"])
        provider.next.header.update(
            update="followup",
            solution="preserve",
            _followup={
                "text": "At the limit, `size < limit` is false; the item waits.",
                "segments": ["2"],
            },
        )
        published.clear()
        await review(c)
        second = c.cards[0]
        assert second["reference"]["code"] == first["reference"]["code"]
        assert saved[-1]["latest_followup"] == second["latest_followup"]
        assert not any(kind == "draft" for kind, _ in published)
        for number, decision, speech in [(3, "IGNORE", "Okay."), (4, "WAIT", "And if we...")]:
            ingest(c, number, speech)
            provider.next = Outcome("fixture", {"action": decision})
            await review(c)
            assert c.cards[0]["latest_followup"] == second["latest_followup"]
        ingest(c, 5, "Allow an item when size equals the limit too.")
        provider.next = answer("UPDATE", text="Accept sizes up to and including the limit.")
        provider.next.header.update(
            solution="replace",
            _followup={"text": "The inclusive limit changes `<` to `<=`.", "segments": ["5"]},
        )
        provider.next.lines += [
            "```java snippet\nboolean fits(int size) { return size <= limit; }\n```"
        ]
        await review(c)
        assert c.cards[0]["id"] == first["id"]
        assert "size <= limit" in saved[-1]["reference"]["code"]
        assert "inclusive limit" in saved[-1]["latest_followup"]["text"]
    finally:
        await c.finish()


def test_initial_answer_cannot_claim_latest_followup():
    records = [
        {"action": "NEW", "question": "Initial task", "developing": False},
        {"text": "Solution in brief: Use a queue."},
        {"followup": {"text": "A follow-up before one was asked.", "segments": ["1"]}},
    ]
    with pytest.raises(ProtocolError, match="Initial answers"):
        Parser().feed("".join(json.dumps(r) + "\n" for r in records))


def test_highlighter_and_matches_preserve_literal_code(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is needed for the optional pure-JavaScript checks")
    source = Path("src/interview_helper/static/app.js").read_text()
    functions = source[source.index("const codeKeywords") : source.index("function updatePart")]
    script = tmp_path / "checks.cjs"
    script.write_text(
        functions
        + r"""
const assert = require("node:assert/strict");
for (const language of ["java", "python", "cpp", "javascript", "sql", "perl", "unknown"]) {
 const code = 'class Example {\n  String s = "<script>"; // quoted\n  return pending.peek();\n}\n';
 assert.equal(codeTokens(code, language).map(t => t.text).join(""), code);
}
const tokens = codeTokens('public int size = 12; String name = "item"; // hi', 'java');
for (const kind of ['keyword','number','type','string','comment']) assert(tokens.some(t => t.kind === kind));
assert.deepEqual(codeMatches('pending.peek();\nused += cost;', 'Read `pending.peek()`.'), [0]);
assert.deepEqual(codeMatches('q.peek(); q.peek();', 'Read `q.peek()`.'), []);
assert.deepEqual(codeMatches('outside;', 'Read `side` or `missing()`.'), []);
assert.deepEqual(codeMatches('x();\ny();', 'Read `y()` then `x()`.'), [0,1]);
"""
    )
    subprocess.run([node, str(script)], check=True, capture_output=True, text=True)
