"""Offline request-routing and refinement contracts; no model-quality claim."""

import json
from pathlib import Path
import pytest
from interview_helper.config import Endpoint
from interview_helper.gateway import Gateway
from test_live_review import setup, ingest, review, answer

CASES = json.loads(
    Path(__file__).with_name("fixtures").joinpath("solution_selection_0.1.11.json").read_text()
)


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
@pytest.mark.parametrize("backend", ["chat_completions", "openai_api"])
async def test_selection_cases_reach_effective_local_and_compact_cloud_prompts(
    tmp_path, case, backend
):
    c, _, _, _, _, _ = await setup(tmp_path)
    endpoint = Endpoint(
        "fixture",
        "https://api.openai.com/v1" if backend == "openai_api" else "https://example.invalid/v1",
        "gpt-6.1-sol",
        backend=backend,
        compact=backend == "openai_api",
        parameters={
            "reasoning_effort": "low",
            "service_tier": "ultrafast",
            "max_output_tokens": 1024,
        }
        if backend == "openai_api"
        else {},
    )
    gateway = Gateway([endpoint])
    try:
        ingest(c, 1, case["speech"], "case-1")
        payload = gateway.payload(endpoint, c.messages(c.snapshot()))
        if backend == "openai_api":
            instructions = payload["instructions"]
            packet = json.loads(payload["input"][-1]["content"])
            assert payload["reasoning"] == {"effort": "low"}
            assert payload["service_tier"] == "ultrafast" and payload["max_output_tokens"] == 1024
        else:
            instructions = payload["messages"][0]["content"]
            packet = json.loads(payload["messages"][-1]["content"])
            assert payload["max_tokens"] == 1024
        # Verify the effective prompt, including compact-cloud substitution, rather
        # than testing a detached policy file that may never reach the provider.
        assert "simplest correct approach" in instructions
        assert "Explicit performance requirements and supplied bounds take priority" in instructions
        assert "two pointers" in instructions and "explicit no-rescan requirement" in instructions
        assert "without a second implementation" in instructions
        assert packet["CONVERSATION"] == [
            {"revision": 1, "segment_id": "case-1", "source": "playback-1", "text": case["speech"]}
        ]
        assert packet["NEW_REVISIONS"] == [1, 1]
        assert payload["stream"] is True
    finally:
        c.closed = True  # no inferred final call; this test only builds requests
        await c.finish()
        await gateway.close()


async def test_optimization_keeps_baseline_requirements_and_card_identity(tmp_path):
    c, provider, _, _, reviews, _ = await setup(tmp_path)
    try:
        ingest(c, 1, CASES[0]["speech"], "baseline")
        provider.next = answer(text="TL;DR: Check each word with two pointers.")
        await review(c)
        card_id = c.cards[0]["id"]
        ingest(c, 2, CASES[1]["speech"], "optimization")
        provider.next = answer(
            "UPDATE",
            text=(
                "TL;DR: Preprocess character positions once because repeated scans now violate the requirement."
            ),
        )
        await review(c)
        packet = provider.calls[-1]
        assert [e["text"] for e in packet["CONVERSATION"]] == [
            CASES[0]["speech"],
            CASES[1]["speech"],
        ]
        assert packet["ACTIVE_QUESTION"]["id"] == card_id
        assert packet["NEW_REVISIONS"] == [2, 2]
        assert c.reviewed == 2 and len(c.cards) == 1 and c.cards[0]["id"] == card_id
        assert reviews[-1]["action"] == "UPDATE"
    finally:
        await c.finish()
