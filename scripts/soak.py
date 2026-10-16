#!/usr/bin/env python3
"""Wall-clock session/persistence/HTTP-parser soak with an in-process provider.

No audio, GPU, OAuth or real provider calls. No benchmark ledger is opened.
"""

import argparse
import asyncio
import json
from pathlib import Path
import resource
import time

import httpx
from interview_helper.config import Config, Endpoint
from interview_helper.session import Session
from interview_helper.storage import SessionStore, atomic_json, now


async def soak(minutes, root):
    if minutes <= 0:
        raise ValueError("Duration must be positive")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    config = Config.load(root / "absent.local.toml")
    config.data_dir = root / "sessions"
    config.review_seconds = 0.5
    config.endpoints = [
        Endpoint(
            "SIMULATED OpenAI",
            "https://api.openai.com/v1",
            "gpt-6.1-sol",
            backend="openai_api",
            api_key="synthetic-not-a-credential",
            compact=True,
            parameters={
                "reasoning_effort": "low",
                "service_tier": "ultrafast",
                "max_output_tokens": 1024,
            },
        )
    ]
    session = Session(config)
    session.start(replay=True)
    gateway = session.controller.gateway
    await gateway.client.aclose()
    calls = failures = 0

    def provider(request):
        nonlocal calls, failures
        calls += 1
        body = json.loads(request.content)
        assert body["max_output_tokens"] == 1024
        if calls % 17 == 0:
            failures += 1
            return httpx.Response(500, json={"error": {"code": "synthetic_server_error"}})
        text = (
            '{"action":"NEW","developing":false}\n'
            '{"text":"Store the idempotency key and effect atomically to prevent duplicate side effects."}\n'
            '{"done":true}\n'
        )
        events = [
            {"type": "response.output_text.delta", "delta": text},
            {
                "type": "response.completed",
                "response": {
                    "id": f"synthetic-{calls}",
                    "status": "completed",
                    "model": "gpt-6.1-sol",
                    "service_tier": "ultrafast",
                },
            },
        ]
        return httpx.Response(200, text="".join("data: " + json.dumps(e) + "\n\n" for e in events))

    gateway.client = httpx.AsyncClient(transport=httpx.MockTransport(provider))
    start = time.monotonic()
    started_at = now()
    count = checks = 0
    max_pending = 0
    receipt = root / "soak-progress.json"
    while time.monotonic() - start < minutes * 60:
        elapsed = time.monotonic() - start
        session.ingest(
            "synthetic-playback",
            "Synthetic playback",
            f"Explain idempotent processing in scenario number {count}.",
            elapsed,
            elapsed + 1,
            final=True,
        )
        count += 1
        await asyncio.sleep(5)
        controller = session.controller
        max_pending = max(max_pending, int(controller.pending is not None))
        assert session.state == "recording" and not session.store.closed
        assert not session.unsaved and not controller.context_overflow
        assert len(session.transcript) <= 200 and len(controller.cards) <= 200
        assert len(controller.scenario) <= config.scenario_chars
        assert sum(len(item[2]) for item in controller.recent) <= config.context_chars
        assert len(gateway.started) <= 256 and len(session.published) <= 256
        assert not gateway.quarantined
        if count % 12 == 0 or count == 1:
            data = SessionStore.inspect(config.data_dir, session.store.id)
            assert len(data["events"]) == count and not data["partial_tail"]
            assert data["metadata"]["status"] == "recording"
            checks += 1
        if calls % 17 == 0:
            assert "failed" in session.status["model"]
            assert any("Hint failed" in n["message"] for n in session.notices)
        result = {
            "session_id": session.store.id,
            "started_at": started_at,
            "elapsed_seconds": time.monotonic() - start,
            "transcript_events": count,
            "simulated_provider_calls": calls,
            "simulated_provider_failures": failures,
            "live_journal_checks": checks,
            "cards": len(controller.cards),
            "live_transcript": len(session.transcript),
            "scenario_chars": len(controller.scenario),
            "pending_bound": max_pending,
            "memory_peak_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "state": session.state,
            "real_provider_calls": 0,
            "cost_usd": 0,
            "scope": "wall-clock synthetic session with MockTransport; no audio/GPU/provider endurance claim",
        }
        atomic_json(receipt, result)
    await session.shutdown()
    data = SessionStore.inspect(config.data_dir, session.store.id)
    assert len(data["events"]) == count
    assert not data["partial_tail"] and session.state == "ended"
    assert calls >= count - 1
    result.update(
        elapsed_seconds=time.monotonic() - start,
        ended_at=now(),
        state=session.state,
        recovered_events=len(data["events"]),
        passed=True,
    )
    atomic_json(receipt, result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--minutes", type=float, default=180)
    p.add_argument("--output", type=Path, default=Path(".local/soak"))
    a = p.parse_args()
    asyncio.run(soak(a.minutes, a.output))
