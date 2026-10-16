#!/usr/bin/env python3
"""Paid API comparison with durable reservations; never creates or changes billing.

Run from the repository using its venv. Raw synthetic evidence stays in .local.
The ledger is shared across probes/runs; unknown usage retains its reservation.
"""

import argparse
import asyncio
from dataclasses import asdict
import json
from pathlib import Path
import time
from interview_helper.budget import Budget, rate
from interview_helper.config import Config, Endpoint
from interview_helper.gateway import Gateway
from latency_evaluation import messages

PROFILES = [
    ("luna-default", "gpt-6-luna", "default"),
    ("luna-fast", "gpt-6-luna", "fast"),
    ("sol-fast", "gpt-6.1-sol", "fast"),
    ("sol-ultrafast", "gpt-6.1-sol", "ultrafast"),
]


async def run(args):
    if args.output.exists():
        raise ValueError("Output already exists; preserve previous evidence")
    cfg = Config.load(args.config)
    budget = Budget(args.ledger, cap=5.0)
    old = json.loads(Path("tests/fixtures/quality_cases_0.1.2.json").read_text())["heldout"]
    fresh = json.loads(Path("tests/fixtures/cloud_cases_0.1.3.json").read_text())["fresh"]
    cases = old + fresh
    context = Path("tests/fixtures/latency_context.txt").read_text()
    workload = [(c, "short") for c in cases] + [(c, "long") for c in cases]
    if args.probe:
        workload = [
            (
                {
                    "id": "funding-probe",
                    "text": "In one sentence, explain why a database unique constraint prevents concurrent duplicate inserts.",
                },
                "short",
            )
        ]
    profiles = []
    for name, model, tier in PROFILES[:1] if args.probe else PROFILES:
        ep = Endpoint(
            name,
            "https://api.openai.com/v1",
            model,
            backend="openai_api",
            api_key_env="OPENAI_API_KEY",
            api_key_file=str(cfg.root / ".local/openai-api-key"),
            parameters={
                "reasoning_effort": "low",
                "service_tier": tier,
                "max_output_tokens": 256 if args.probe else 1024,
            },
            compact=True,
            transport=args.transport,
            timeout=60,
        )
        profiles.append((ep, Gateway([ep])))
    rows = []
    try:
        catalog = await profiles[0][1].catalog(profiles[0][0])
        if any(ep.model not in catalog for ep, _ in profiles):
            raise ValueError("Requested model unavailable; no paid comparison dispatched")
        used = sum(r.get("cost_usd", r["reserved_usd"]) for r in budget.read()["requests"].values())
        # Plan equal workloads for every profile at pessimistic byte-token/output
        # ceilings, reducing the initial comparison instead of exceeding the cap.
        planned = []
        worst = used
        estimate = 0.0
        for index, (case, kind) in enumerate(workload[args.start : args.start + args.cases]):
            group = []
            upper = 0.0
            approx = 0.0
            for ep, g in profiles:
                rid = args.output.stem + "-" + ep.name + "-" + str(index)
                ms = messages(cfg, case, rid, "", context if kind == "long" else None)
                payload = g.payload(ep, ms)
                prices = rate(ep.model, ep.parameters["service_tier"])
                byte_tokens = len(json.dumps(payload, ensure_ascii=False).encode()) + 2048
                upper += (
                    byte_tokens * max(prices[:3]) + payload["max_output_tokens"] * prices[3]
                ) / 1e6
                approx += (byte_tokens / 4 * prices[0] + 220 * prices[3]) / 1e6
                group.append((ep, g, case, kind, rid, ms, payload))
            if worst + upper > min(5.0, budget.read()["cap_usd"]):
                break
            worst += upper
            estimate += approx
            planned.extend(group if index % 2 == 0 else group[::-1])
        print(
            json.dumps(
                {
                    "planned_requests": len(planned),
                    "preliminary_usd": estimate,
                    "pessimistic_total_including_prior": worst,
                    "hard_cap_usd": 5,
                }
            ),
            flush=True,
        )
        if not args.execute:
            return
        for ep, g, case, kind, rid, ms, payload in planned:
            if g.quarantined or g.paused:
                continue
            raw = []
            events = []
            lines = []

            def observe(event, data):
                if event == "answer_delta":
                    raw.append(data["text"])
                elif event in {"failure", "provider_error"}:
                    events.append(data)

            g.observe = observe
            budget.reserve(rid, payload)

            async def emit(outcome, parser, record):
                if "text" in record:
                    lines.append(time.monotonic() - outcome.started_at)

            result = await g.stream(ep, ms, rid, emit)
            budget.settle(rid, result.usage, result.diagnostics.get("response_service_tier"))
            rows.append(
                {
                    "profile": ep.name,
                    "case": case["id"],
                    "context": kind,
                    "raw_text": "".join(raw),
                    "events": events,
                    "line_seconds": lines,
                    **asdict(result),
                }
            )
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(rows, indent=2))
            args.output.chmod(0o600)
            print(
                json.dumps(
                    {
                        "profile": ep.name,
                        "case": case["id"],
                        "error": result.error,
                        "first_record": result.first_useful,
                        "effective_tier": result.diagnostics.get("response_service_tier"),
                    }
                ),
                flush=True,
            )
            if result.diagnostics.get("code") in {
                "credit_balance_exhausted",
                "insufficient_quota",
                "invalid_api_key",
            }:
                break  # Account-wide cause; do not probe other profiles blindly.
    finally:
        for ep, g in profiles:
            await g.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config.local.toml"))
    parser.add_argument("--ledger", type=Path, default=Path(".local/0.1.3/cost-ledger.json"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--transport", choices=["http", "websocket"], default="http")
    parser.add_argument(
        "--probe",
        action="store_true",
        help="One small standard-tier Luna request only; use after user verifies matching credit",
    )
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--cases", type=int, default=48)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Without this flag only model catalog and cost plan are checked",
    )
    asyncio.run(run(parser.parse_args()))
