"""Conservative, durable USD ledger for explicitly authorized API benchmarks only."""

import json
import os
from pathlib import Path
from filelock import FileLock

# Official short-context global prices, USD/million, verified 2026-10-14.
# input, cached input, cache write, output (reasoning included).
RATES = {
    ("gpt-6-luna", "default"): (0.10, 0.01, 0.125, 0.50),
    ("gpt-6-luna", "fast"): (0.20, 0.02, 0.25, 1.0),
    ("gpt-6.1-sol", "default"): (2.0, 0.10, 2.50, 10.0),
    ("gpt-6.1-sol", "fast"): (4.0, 0.20, 5.0, 20.0),
    ("gpt-6.1-sol", "ultrafast"): (12.0, 0.60, 15.0, 60.0),
}


def rate(model, tier):
    return RATES[(model, "fast" if tier == "priority" else tier)]


class Budget:
    def __init__(self, path, cap=5.0):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.cap = cap
        self.lock = FileLock(str(self.path) + ".lock")

    def read(self):
        return (
            json.loads(self.path.read_text())
            if self.path.exists()
            else {"cap_usd": self.cap, "requests": {}}
        )

    def write(self, data):
        tmp = self.path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)

    def reserve(self, request_id, payload):
        model, tier = payload["model"], payload.get("service_tier", "default")
        prices = rate(model, tier)
        # UTF-8 byte count + envelope overhead upper-bounds ordinary text tokens.
        # Max output includes reasoning; cache writes priced at their higher rate.
        tokens = len(json.dumps(payload, ensure_ascii=False).encode()) + 2048
        if tokens > 272000:
            raise ValueError("Benchmark input exceeds short-context price bound")
        amount = (tokens * max(prices[:3]) + payload["max_output_tokens"] * prices[3]) / 1e6
        with self.lock:
            data = self.read()
            if request_id in data["requests"]:
                raise ValueError("Duplicate benchmark request ID")
            used = sum(r.get("cost_usd", r["reserved_usd"]) for r in data["requests"].values())
            if used + amount > min(self.cap, data["cap_usd"]):
                raise RuntimeError("Benchmark USD cap reached; no request dispatched")
            data["requests"][request_id] = {
                "model": model,
                "requested_tier": tier,
                "reserved_usd": amount,
            }
            self.write(data)
        return amount

    def settle(self, request_id, usage, effective_tier):
        if not usage or not effective_tier:
            return  # Unknown usage/tier keeps the full reservation, including failures.
        with self.lock:
            data = self.read()
            row = data["requests"][request_id]
            prices = rate(row["model"], effective_tier)
            details = usage.get("input_tokens_details") or {}
            cached = details.get("cached_tokens", 0)
            written = details.get("cache_creation_tokens", details.get("cache_write_tokens", 0))
            total = usage["input_tokens"]
            cost = (
                max(0, total - cached - written) * prices[0]
                + cached * prices[1]
                + written * prices[2]
                + usage["output_tokens"] * prices[3]
            ) / 1e6
            row.update(usage=usage, effective_tier=effective_tier, cost_usd=cost)
            self.write(data)


def reject_unbudgeted_api(endpoints):
    """Legacy evaluation scripts must not inherit a paid app startup selection."""
    if any(endpoint.backend == "openai_api" for endpoint in endpoints):
        raise ValueError(
            "Paid evaluation requires cost-capped scripts/cloud_evaluation.py and the existing "
            "authorized ledger; normal app sessions are unaffected"
        )
