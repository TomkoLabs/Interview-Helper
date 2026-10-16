#!/usr/bin/env python3
"""Observe real loser draining/host-slot ownership; not upstream cancellation proof."""

import argparse
import asyncio
import json
from pathlib import Path
import time
import uuid
from interview_helper.budget import reject_unbudgeted_api
from interview_helper.config import Config
from interview_helper.gateway import Gateway
from benchmark import messages


async def run(config, output):
    reject_unbudgeted_api(config.endpoints)
    if len(config.endpoints) != 2 or any(e.cancel_supported for e in config.endpoints):
        raise ValueError("This check requires two explicit hosts with cancellation disabled")
    statuses = []
    visible_hosts = set()
    gateway = Gateway(config.endpoints, lambda host, status: statuses.append([host, status]))

    async def emit(host, *_):
        visible_hosts.add(host)

    started = time.monotonic()
    try:
        result = await gateway.race(
            messages("Compare a Python list and a tuple."),
            "drain-" + uuid.uuid4().hex,
            emit,
            "race",
        )
        at_winner = {name: lock.locked() for name, lock in gateway.locks.items()}
        pending = len(gateway.draining)
        await gateway.close()
        receipt = {
            "winner": result.host,
            "first_useful_seconds": result.first_useful,
            "winner_complete_seconds": result.complete,
            "all_streams_complete_seconds": time.monotonic() - started,
            "visible_hosts": sorted(visible_hosts),
            "draining_at_winner": pending,
            "host_locks_at_winner": at_winner,
            "host_locks_after_drain": {name: lock.locked() for name, lock in gateway.locks.items()},
            "statuses": statuses,
            "scope": "Client drains loser under host lock. Upstream disconnect termination is NOT asserted.",
            "error": result.error,
        }
        output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        output.write_text(json.dumps(receipt, indent=2))
        assert not result.error and len(visible_hosts) == 1, receipt
        assert not any(lock.locked() for lock in gateway.locks.values()), receipt
        if pending:
            assert any(at_winner.values()), receipt
        print(json.dumps(receipt, indent=2))
    finally:
        await gateway.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--config", type=Path, default=Path("config.local.toml"))
    p.add_argument("--output", type=Path, default=Path(".local/race-drain.json"))
    a = p.parse_args()
    asyncio.run(run(Config.load(a.config), a.output))
