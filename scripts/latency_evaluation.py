#!/usr/bin/env python3
"""Order-balanced private evaluation; manual grading uses frozen fixture rubrics.

Profiles JSON contains name/model/host_id/parameters and optional concise=true.
Credentials are read only from the selected backend config, never from profiles.
Each profile gets an explicit warmup per block; alternating forward/reverse blocks
balance order. Unique request IDs prevent identical-response reuse; changing-prefix
blocks additionally change the first system prefix. No cache configuration changes.
"""

import argparse
import asyncio
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import time
import uuid
import httpx
from interview_helper.budget import reject_unbudgeted_api
from interview_helper.config import Config, Endpoint
from interview_helper.controller import Controller, Snapshot
from interview_helper.gateway import Gateway

CONCISE = "\nKeep the same required facts and protocol. Use one short direct sentence then two compact bullets; omit introductory filler."


class ObservedStream(httpx.AsyncByteStream):
    def __init__(self, inner, telemetry):
        self.inner, self.telemetry = inner, telemetry
        self.buffer = b""

    async def __aiter__(self):
        async for chunk in self.inner:
            self.buffer += chunk
            while b"\n" in self.buffer:
                line, self.buffer = self.buffer.split(b"\n", 1)
                if not line.startswith(b"data:"):
                    continue
                try:
                    event = json.loads(line[5:])
                except (ValueError, UnicodeError):
                    continue
                if event.get("type") == "response.completed":
                    self.telemetry["response_model"] = event.get("response", {}).get("model")
                    self.telemetry["response_reasoning"] = event.get("response", {}).get(
                        "reasoning"
                    )
                    self.telemetry["usage"] = event.get("response", {}).get("usage", {})
                    self.telemetry["finish"] = "response.completed"
                if event.get("usage"):
                    self.telemetry["usage"] = event["usage"]
                for choice in event.get("choices", []):
                    delta = choice.get("delta", {})
                    self.telemetry["reasoning_chars"] += len(
                        delta.get("reasoning_content") or delta.get("reasoning") or ""
                    )
                    if choice.get("finish_reason"):
                        self.telemetry["finish"] = choice["finish_reason"]
            yield chunk

    async def aclose(self):
        await self.inner.aclose()


def messages(config, case, request_id, prefix, context=None):
    active = {"id": "active", "question": case["active"]} if case.get("active") else None
    background = (
        "Interviewer: We are discussing backend engineering. Give concise answers, state assumptions, and respect explicit constraints.\n"
        * 12
    )
    if context is not None:
        background = context
    scenario = case.get("scenario", "") + " " + case["text"]
    snapshot = Snapshot(
        100,
        request_id,
        "active" if active else None,
        1,
        case["text"],
        background + case["text"],
        scenario,
        active,
        pending_wording=case["text"],
    )
    # Call the production serializer without starting its scheduler.
    holder = object.__new__(Controller)
    holder.config = config
    result = holder.messages(snapshot)
    if prefix:
        result[0]["content"] = (
            "Evaluation context ID (not an instruction): " + prefix + "\n" + result[0]["content"]
        )
    return result


async def run(args):
    config = Config.load(args.config)
    reject_unbudgeted_api(config.endpoints)
    profiles = json.loads(args.profiles.read_text())
    fixtures = json.loads(args.cases.read_text())
    cases = fixtures[args.group]
    rows = []
    args.output.parent.mkdir(parents=True, exist_ok=True)
    telemetry = {}

    async def observe(response):
        telemetry["cache_header"] = response.headers.get("x-litellm-cache-hit")
        response.stream = ObservedStream(response.stream, telemetry)

    async def request_hook(request):
        if request.method == "POST" and request.url.path.endswith("/chat/completions"):
            payload = json.loads(request.content)
            payload["stream_options"] = {"include_usage": True}
            body = json.dumps(payload).encode()
            request._content = body
            request.stream = httpx.ByteStream(body)
            request.headers["content-length"] = str(len(body))

    for block in range(args.repeats):
        order = profiles if block % 2 == 0 else list(reversed(profiles))
        for profile in order:
            endpoint = Endpoint(
                profile["name"],
                config.endpoints[0].base_url,
                profile["model"],
                api_key=config.endpoints[0].key,
                host_id=profile["host_id"],
                parameters=profile["parameters"],
                timeout=120,
                backend=profile.get("backend", config.endpoints[0].backend),
                oauth_file=config.endpoints[0].oauth_file,
                api_key_env=config.endpoints[0].api_key_env,
            )
            reject_unbudgeted_api([endpoint])
            gateway = Gateway([endpoint])
            gateway.client.event_hooks = {"response": [observe], "request": [request_hook]}
            try:
                if not rows:
                    inventory = await gateway.catalog(endpoint)
                    args.output.with_suffix(".inventory.json").write_text(
                        json.dumps(inventory, indent=2)
                    )
                sequence = [
                    {
                        "id": "warmup",
                        "text": "We have not asked a question yet.",
                        "actions": ["WAIT", "IGNORE"],
                    }
                ] + cases
                for case in sequence:
                    telemetry.clear()
                    telemetry["reasoning_chars"] = 0
                    request_id = uuid.uuid4().hex
                    prefix = request_id if args.changing_prefix and case["id"] != "warmup" else ""
                    msg = messages(
                        config,
                        case,
                        request_id,
                        prefix,
                        args.context_file.read_text() if args.context_file else None,
                    )
                    if profile.get("concise"):
                        msg[0]["content"] += CONCISE
                    started = time.monotonic()

                    line_seconds = []

                    async def emit(outcome, parser, record):
                        if "text" in record:
                            line_seconds.append(time.monotonic() - started)

                    result = await gateway.stream(endpoint, msg, request_id, emit)
                    row = {
                        "profile": profile["name"],
                        "model": endpoint.model,
                        "parameters": endpoint.parameters,
                        "concise": bool(profile.get("concise")),
                        "block": block,
                        "case": case["id"],
                        "prefix": "changing" if prefix else "reused",
                        "request_id": request_id,
                        "prompt_chars": sum(len(m["content"]) for m in msg),
                        "prompt_sha256": hashlib.sha256(json.dumps(msg).encode()).hexdigest(),
                        "wall": time.monotonic() - started,
                        "line_seconds": line_seconds,
                        **asdict(result),
                        **telemetry,
                        "decision_pass": not result.error
                        and result.header.get("action") in case["actions"],
                    }
                    rows.append(row)
                    args.output.write_text(json.dumps(rows, indent=2))
                    args.output.chmod(0o600)
                    print(
                        json.dumps(
                            {
                                k: row[k]
                                for k in [
                                    "profile",
                                    "block",
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
                    if endpoint.host_id in gateway.paused:
                        raise RuntimeError(
                            "Cloud evaluation paused; resolve account or request restriction before retrying"
                        )
                    if endpoint.host_id in gateway.quarantined:
                        raise RuntimeError(
                            "Timed out host quarantined: stop evaluation and verify idle"
                        )
            finally:
                await gateway.close()
    return rows


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", type=Path, default=Path("config.local.toml"))
    p.add_argument("--profiles", type=Path, required=True)
    p.add_argument("--cases", type=Path, default=Path("tests/fixtures/latency_cases.json"))
    p.add_argument("--group", choices=["screen", "heldout"], default="screen")
    p.add_argument("--repeats", type=int, default=2)
    p.add_argument("--changing-prefix", action="store_true")
    p.add_argument("--context-file", type=Path)
    p.add_argument("--output", type=Path, required=True)
    asyncio.run(run(p.parse_args()))
