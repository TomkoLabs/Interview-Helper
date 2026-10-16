#!/usr/bin/env python3
"""Small synthetic gateway comparison. Results are private, never commit them."""

import argparse
import asyncio
import json
from pathlib import Path
import statistics
import time
import uuid
from interview_helper.budget import reject_unbudgeted_api
from interview_helper.config import Config
from interview_helper.controller import PROMPT
from interview_helper.gateway import Gateway

CASES = [
    ("wait", "Let me think about how to phrase the", {"WAIT", "IGNORE"}),
    ("topic", "Java, Python and C++ are all on the agenda today.", {"IGNORE", "WAIT"}),
    ("compare", "Compare a Python list and a tuple. When would you choose each?", {"NEW"}),
    (
        "constraint",
        "Design a Java 8 counter used by multiple processes, without locks. What would you check first?",
        {"NEW"},
    ),
    (
        "indirect",
        "We have at-least-once delivery and orders get charged twice. Walk me through an approach to prevent that.",
        {"NEW"},
    ),
    (
        "compound",
        "Explain C++ RAII, how it differs from garbage collection, and one exception-safety benefit.",
        {"NEW"},
    ),
]


def messages(text, active=None, scenario=""):
    return [
        {"role": "system", "content": PROMPT},
        {
            "role": "user",
            "content": json.dumps(
                {
                    "NEW_STABLE_TEXT": text,
                    "RECENT_CONVERSATION": text,
                    "ACTIVE_QUESTION": active,
                    "SCENARIO_REQUIREMENTS": scenario,
                    "EXPAND": False,
                }
            ),
        },
    ]


async def run(config, output, repeats=1):
    reject_unbudgeted_api(config.endpoints)
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    gateway = Gateway(config.endpoints)
    rows = []

    async def ignore(*_):
        pass

    strategies = [e.name for e in config.endpoints] + (
        ["race"] if len(config.endpoints) == 2 else []
    )
    try:
        for strategy in strategies:
            for repeat in range(repeats):
                for name, text, expected in CASES:
                    t = time.monotonic()
                    request_id = "bench-" + uuid.uuid4().hex
                    if strategy == "race":
                        result = await gateway.race(messages(text), request_id, ignore, "race")
                    else:
                        endpoint = next(e for e in config.endpoints if e.name == strategy)
                        result = await gateway.stream(endpoint, messages(text), request_id, ignore)
                    row = {
                        "strategy": strategy,
                        "case": name,
                        "repeat": repeat,
                        "wall_seconds": time.monotonic() - t,
                        **result.__dict__,
                        "decision_pass": not result.error
                        and result.header.get("action") in expected,
                    }
                    rows.append(row)
                    output.write_text(json.dumps(rows, indent=2))
                    print(
                        json.dumps(
                            {
                                k: row[k]
                                for k in [
                                    "strategy",
                                    "case",
                                    "first_useful",
                                    "complete",
                                    "error",
                                    "decision_pass",
                                ]
                            }
                        ),
                        flush=True,
                    )
            if gateway.draining:
                await asyncio.gather(*list(gateway.draining), return_exceptions=True)
        for strategy in strategies:
            good = [
                r
                for r in rows
                if r["strategy"] == strategy and r["first_useful"] is not None and not r["error"]
            ]
            if good:
                print(
                    strategy,
                    "median first useful",
                    round(statistics.median(r["first_useful"] for r in good), 3),
                )
    finally:
        await gateway.close()
    return rows


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--config", type=Path, default=Path("config.local.toml"))
    p.add_argument("--output", type=Path, default=Path(".local/benchmark.json"))
    p.add_argument("--repeats", type=int, default=1)
    a = p.parse_args()
    asyncio.run(run(Config.load(a.config), a.output, a.repeats))
