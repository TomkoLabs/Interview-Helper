"""Authenticated streaming with bounded per-host slots and honest cancellation."""

import asyncio
import json
import re
import time
from dataclasses import dataclass, field
import httpx
from .protocol import Parser, ProtocolError
from .cloud_auth import access_token
from .responses_socket import Lane
from websockets.exceptions import ConnectionClosed
from pathlib import Path


@dataclass
class Outcome:
    host: str
    header: dict = field(default_factory=dict)
    lines: list = field(default_factory=list)
    first_useful: float | None = None
    complete: float | None = None
    error: str = ""
    queue_seconds: float = 0.0
    usage: dict = field(default_factory=dict)
    diagnostics: dict = field(default_factory=dict)
    timings: dict = field(default_factory=dict)
    started_at: float = 0.0
    answers: list = field(default_factory=list)


class Gateway:
    def __init__(self, endpoints, status=None, observe=None, keepalive_expiry=120):
        self.endpoints = endpoints
        self.compact_prompt = Path(__file__).with_name("prompts").joinpath("cloud.txt").read_text()
        self.locks = {e.host_id: asyncio.Lock() for e in endpoints}
        self.client = httpx.AsyncClient(
            trust_env=False, limits=httpx.Limits(keepalive_expiry=keepalive_expiry)
        )
        self.observe = observe or (lambda event, data: None)
        self.connections = {}
        self.connection_count = 0
        self.sockets = {}
        self.started = {}
        self.status = status or (lambda *_: None)
        self.draining = set()
        self.quarantined = set()
        self.paused = {}
        self.account_paused = {}

    async def credential(self, endpoint):
        if endpoint.backend == "chatgpt":
            return await access_token(endpoint.oauth_file, self.client)
        if not endpoint.key:
            raise RuntimeError("Missing backend API credential")
        return endpoint.key

    async def model_choices(self, endpoint):
        response = await self.client.get(
            endpoint.base_url.rstrip("/") + "/models",
            headers={"Authorization": "Bearer " + await self.credential(endpoint)},
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()
        if endpoint.backend == "chatgpt":
            return [
                {"id": m["slug"], "name": m["display_name"]}
                for m in data["models"]
                if m.get("visibility") == "list"
            ]
        return [{"id": m["id"], "name": m["id"]} for m in data["data"]]

    async def catalog(self, endpoint):
        return [m["id"] for m in await self.model_choices(endpoint)]

    def payload(self, endpoint, messages):
        if endpoint.backend == "chat_completions":
            return {
                "model": endpoint.model,
                "messages": messages,
                "stream": True,
                "max_tokens": 1024,
                **endpoint.parameters,
            }
        if endpoint.compact:
            messages = [dict(m) for m in messages]
            messages[0]["content"] = self.compact_prompt
            state = json.loads(messages[-1]["content"])
            for field in (
                "request_id",
                "transcript_revision",
                "CANDIDATE_SPOKEN_ANSWER",
                "CANDIDATE_AUDIO_AVAILABLE",
            ):
                state.pop(field, None)
            messages[-1]["content"] = json.dumps(state, ensure_ascii=False)
        instructions = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        payload = {
            "model": endpoint.model,
            "input": [m for m in messages if m["role"] != "system"],
            "store": False,
            "stream": True,
            "reasoning": {"effort": endpoint.parameters.get("reasoning_effort", "low")},
        }
        if instructions:
            payload["instructions"] = instructions
        if "max_output_tokens" in endpoint.parameters:
            payload["max_output_tokens"] = endpoint.parameters["max_output_tokens"]
        if "service_tier" in endpoint.parameters:
            payload["service_tier"] = endpoint.parameters["service_tier"]
        return payload

    async def stream(self, endpoint, messages, request_id, emit, current=None):
        outcome = Outcome(endpoint.name)
        parser = Parser()
        queued = time.monotonic()
        async with self.locks[endpoint.host_id]:
            outcome.queue_seconds = time.monotonic() - queued
            if current is not None and not current():
                outcome.error = "Superseded before dispatch"
                return outcome
            start = time.monotonic()
            outcome.started_at = start
            self.started[request_id] = start
            if len(self.started) > 256:
                self.started.pop(next(iter(self.started)))

            def mark(name):
                outcome.timings.setdefault(name, time.monotonic() - start)

            async def trace(event, info):
                # Trace names only: info can include sockets, URLs and credentials.
                if event.startswith(("connection.", "http11.", "http2.")):
                    mark(event)

            mark("dispatch")
            self.status(endpoint.name, "generating")
            payload = self.payload(endpoint, messages)
            try:
                failure_key = self.failure_key(endpoint)
                if failure_key in self.quarantined:
                    raise RuntimeError(
                        "Host paused after timeout or uncertain cancellation; verify server idle, then restart app"
                    )
                if failure_key in self.paused:
                    raise RuntimeError(self.paused[failure_key])
                account_key = (
                    endpoint.backend,
                    endpoint.oauth_file,
                    endpoint.api_key_file,
                    endpoint.api_key_env,
                )
                if endpoint.backend != "chat_completions" and account_key in self.account_paused:
                    raise RuntimeError(self.account_paused[account_key])
                key = await self.credential(endpoint)
                mark("credential_ready")
                async with asyncio.timeout(endpoint.timeout):
                    transport = self.client.stream(
                        "POST",
                        endpoint.base_url.rstrip("/")
                        + (
                            "/chat/completions"
                            if endpoint.backend == "chat_completions"
                            else "/responses"
                        ),
                        headers={
                            "Authorization": "Bearer " + key,
                            "X-Request-ID": request_id,
                        },
                        json=payload,
                        extensions={"trace": trace},
                        timeout=httpx.Timeout(endpoint.timeout, connect=10),
                    )
                    if endpoint.transport == "websocket":
                        lane = self.sockets.setdefault(endpoint.name, Lane())
                        transport = lane.response(
                            self.client,
                            endpoint,
                            key,
                            payload,
                            request_id,
                            mark,
                            outcome.diagnostics,
                            trace,
                        )
                    async with transport as response:
                        mark("response_headers")
                        network = response.extensions.get("network_stream")
                        if network is not None:
                            network_id = id(network)
                            reused = network_id in self.connections
                            if not reused:
                                self.connection_count += 1
                                self.connections[network_id] = (self.connection_count, network)
                                if len(self.connections) > 64:
                                    self.connections.pop(next(iter(self.connections)))
                            outcome.diagnostics.update(
                                connection_id=self.connections[network_id][0],
                                connection_reused=reused,
                            )
                        outcome.diagnostics.update(
                            {
                                "http_status": response.status_code,
                                "request_id": response.headers.get("x-request-id", "")[:128],
                                "http_version": response.http_version,
                            }
                        )
                        if response.status_code != 200:
                            if endpoint.backend != "chat_completions":
                                body = b""
                                async for chunk in response.aiter_bytes():
                                    body += chunk
                                    if len(body) > 8192:
                                        break
                                try:
                                    detail = json.loads(body[:8192])
                                    outcome.diagnostics["body_shape"] = (
                                        "error"
                                        if isinstance(detail.get("error"), dict)
                                        else "detail"
                                        if "detail" in detail
                                        else "other"
                                    )
                                    for field in ("code", "param"):
                                        value = (
                                            (detail.get("error") or {}).get(field)
                                            if isinstance(detail.get("error"), dict)
                                            else None
                                        )
                                        if isinstance(value, str) and re.fullmatch(
                                            r"[a-zA-Z0-9_.-]{1,120}", value
                                        ):
                                            outcome.diagnostics[field] = value
                                except (ValueError, AttributeError):
                                    outcome.diagnostics["body_shape"] = "unparsed"
                                if response.status_code in {400, 401, 403, 429}:
                                    self.paused[failure_key] = (
                                        "Cloud paused after HTTP "
                                        + str(response.status_code)
                                        + "; check account/settings, then end and restart session"
                                    )
                                if response.status_code in {401, 403, 429}:
                                    self.account_paused[account_key] = self.paused[failure_key]
                            raise RuntimeError(f"Gateway HTTP {response.status_code}")
                        finish_reason = None
                        saw_done = False
                        protocol_error = None
                        async for line in response.aiter_lines():
                            if not line.startswith("data:"):
                                continue
                            data = line[5:].strip()
                            if data == "[DONE]":
                                if endpoint.backend == "chat_completions":
                                    saw_done = True
                                continue
                            event = json.loads(data)
                            mark("first_response_event")
                            kind = event.get("type", "")
                            if (
                                "reasoning" in kind
                                or event.get("item", {}).get("type") == "reasoning"
                            ):
                                mark("first_reasoning_event")
                            if kind == "response.output_text.delta" and event.get("delta"):
                                mark("first_output_text_delta")
                                self.observe(
                                    "answer_delta",
                                    {
                                        "request_id": request_id,
                                        "text": event["delta"],
                                        "seconds": time.monotonic() - start,
                                    },
                                )
                            if kind in {
                                "response.created",
                                "response.completed",
                                "response.failed",
                                "response.incomplete",
                            }:
                                body = event.get("response", {})
                                if body.get("usage"):
                                    outcome.usage = body["usage"]
                                for name in ("model", "service_tier", "reasoning", "id"):
                                    if name in body:
                                        prefix = (
                                            "created_"
                                            if kind == "response.created"
                                            else "response_"
                                        )
                                        outcome.diagnostics[prefix + name] = body[name]
                                if kind == "response.completed":
                                    mark("response_completed")
                            if event.get("error"):
                                detail = event["error"]
                                self.observe(
                                    "provider_error", {"request_id": request_id, "event": event}
                                )
                                for field in ("code", "type", "param"):
                                    value = detail.get(field) if isinstance(detail, dict) else None
                                    if isinstance(value, str) and re.fullmatch(
                                        r"[a-zA-Z0-9_.-]{1,120}", value
                                    ):
                                        outcome.diagnostics[field] = value
                                if outcome.diagnostics.get("code") in {
                                    "credit_balance_exhausted",
                                    "insufficient_quota",
                                    "invalid_api_key",
                                    "token_expired",
                                    "invalid_token",
                                    "authentication_error",
                                }:
                                    self.paused[failure_key] = (
                                        "Cloud paused: "
                                        + outcome.diagnostics["code"]
                                        + "; check account, then restart session"
                                    )
                                if failure_key in self.paused:
                                    self.account_paused[account_key] = self.paused[failure_key]
                                protocol_error = ProtocolError(
                                    "Gateway stream error"
                                    + (
                                        ": " + outcome.diagnostics["code"]
                                        if "code" in outcome.diagnostics
                                        else ""
                                    )
                                )
                                continue
                            if endpoint.backend != "chat_completions":
                                kind = event.get("type")
                                if kind in {"response.failed", "response.incomplete", "error"}:
                                    # Fixed categories avoid leaking remote bodies or transcript.
                                    code = event.get("response", {}).get("error", {}) or {}
                                    code = code.get("code", "")
                                    known = {
                                        "subscription_sharing_usage_limit_exceeded",
                                        "subscription_sharing_usage_unavailable",
                                        "subscription_sharing_user_not_eligible",
                                        "subscription_sharing_unsupported_capability",
                                    }
                                    outcome.diagnostics["terminal"] = kind
                                    if code in known:
                                        outcome.diagnostics["code"] = code
                                        self.paused[failure_key] = (
                                            "Cloud paused: "
                                            + code
                                            + "; check ChatGPT Usage/settings, then end and restart session"
                                        )
                                    if code in known:
                                        self.account_paused[account_key] = self.paused[failure_key]
                                    protocol_error = protocol_error or ProtocolError(
                                        "Responses " + kind + (": " + code if code in known else "")
                                    )
                                    continue
                                if kind == "response.completed":
                                    if event.get("response", {}).get("status") not in {
                                        None,
                                        "completed",
                                    }:
                                        raise ProtocolError("Responses terminal status mismatch")
                                    outcome.usage = event.get("response", {}).get("usage") or {}
                                    saw_done = True
                                    continue  # Drain HTTP to EOF so the pool can reuse its connection.
                                content = (
                                    event.get("delta", "")
                                    if kind == "response.output_text.delta"
                                    else ""
                                )
                                if protocol_error is not None:
                                    continue
                                has_answer_content = re.search(
                                    r'"text"\s*:\s*"[^"\s]', parser.buffer + content
                                )
                                try:
                                    records = parser.feed(content)
                                except ProtocolError as exc:
                                    protocol_error = exc
                                    continue  # Collect terminal usage and safely drain before rollback.
                                # A single provider delta may contain both the header
                                # and answer. Check after header validation, before
                                # recording complete lines, without losing the buffer.
                                if parser.header and has_answer_content:
                                    mark("first_answer_content_delta")
                                for record in records:
                                    if "text" in record and outcome.first_useful is None:
                                        mark("first_complete_record")
                                        outcome.first_useful = time.monotonic() - start
                                    await emit(outcome, parser, record)
                                continue
                            if event.get("usage"):
                                outcome.usage = event["usage"]
                            choices = event.get("choices", [])
                            if not choices:
                                continue
                            choice = choices[0]
                            finish_reason = choice.get("finish_reason") or finish_reason
                            # reasoning_content / reasoning are deliberately not displayed or stored.
                            content = choice.get("delta", {}).get("content") or ""
                            for record in parser.feed(content):
                                if "text" in record and outcome.first_useful is None:
                                    outcome.first_useful = time.monotonic() - start
                                await emit(outcome, parser, record)
                        if protocol_error is not None:
                            raise protocol_error
                        for record in parser.finish():
                            if "text" in record and outcome.first_useful is None:
                                outcome.first_useful = time.monotonic() - start
                            await emit(outcome, parser, record)
                        if finish_reason not in {None, "stop"} or not saw_done:
                            raise ProtocolError("Incomplete or truncated gateway stream")
                outcome.answers = parser.answers + [
                    {"header": parser.header, "lines": parser.lines}
                ]
                outcome.header, outcome.lines = (
                    outcome.answers[0]["header"],
                    outcome.answers[0]["lines"],
                )
                outcome.complete = time.monotonic() - start
                self.status(endpoint.name, "ready")
            except asyncio.CancelledError:
                if not endpoint.cancel_supported:
                    self.quarantined.add(failure_key)
                self.status(endpoint.name, "cancelled; backend termination depends on server")
                raise
            except Exception as exc:
                if (
                    isinstance(
                        exc,
                        (TimeoutError, httpx.TimeoutException, ConnectionError, ConnectionClosed),
                    )
                    and not endpoint.cancel_supported
                ):
                    self.quarantined.add(failure_key)
                # Never include response bodies, URLs with headers or transcript in diagnostics.
                mark("failure")
                outcome.diagnostics["failure_type"] = type(exc).__name__
                outcome.diagnostics["parser_done"] = parser.done
                outcome.diagnostics["accepted_records"] = len(parser.lines)
                self.observe(
                    "failure",
                    {
                        "request_id": request_id,
                        "buffer": parser.buffer,
                        "lines": parser.lines,
                        "error_type": type(exc).__name__,
                    },
                )
                outcome.error = (
                    str(exc)
                    if isinstance(exc, (ProtocolError, RuntimeError))
                    else type(exc).__name__
                )
                self.status(endpoint.name, "failed: " + outcome.error)
        return outcome

    @staticmethod
    def failure_key(endpoint):
        if endpoint.backend == "chat_completions":
            return endpoint.host_id
        return (
            endpoint.host_id,
            endpoint.backend,
            endpoint.model,
            endpoint.parameters.get("reasoning_effort", "low"),
            endpoint.parameters.get("service_tier", "default"),
        )

    async def race(self, messages, request_id, on_line, strategy="single", current=None):
        endpoints = self.endpoints[:1] if strategy == "single" else self.endpoints
        if not endpoints:
            return Outcome("none", error="No endpoint configured; transcription continues")
        queued = time.monotonic()
        # Never build a FIFO behind a noncancellable loser. Only idle hosts join
        # this race. If every host is busy, retain only the controller's latest
        # snapshot and recheck it before dispatching when a slot opens.
        while True:
            if current is not None and not current():
                return Outcome(
                    "application",
                    error="Superseded before dispatch",
                    queue_seconds=time.monotonic() - queued,
                )
            available = [e for e in endpoints if not self.locks[e.host_id].locked()]
            if available:
                break
            await asyncio.sleep(0.05)
        endpoints = available
        queue_seconds = time.monotonic() - queued
        winner = None
        tasks = {}

        async def emit(outcome, parser, record):
            nonlocal winner
            if "text" not in record:
                return
            if winner is None:
                winner = outcome.host
            if winner == outcome.host:
                await on_line(
                    outcome.host,
                    {**record.header, "_index": record.index},
                    [line for line in record.lines if not line.startswith("```")],
                )
                outcome.timings.setdefault("backend_publish", time.monotonic() - outcome.started_at)

        for endpoint in endpoints:
            task = asyncio.create_task(self.stream(endpoint, messages, request_id, emit, current))
            tasks[task] = endpoint
        results = []
        pending = set(tasks)
        try:
            while pending:
                completed, pending = await asyncio.wait(
                    pending, return_when=asyncio.FIRST_COMPLETED
                )
                for task in completed:
                    result = task.result()
                    result.queue_seconds += queue_seconds
                    results.append(result)
                    if result.host == winner:
                        # A malformed winner must not leave a partial answer published.
                        # Controller rolls back. Do not splice in a competitor's answer.
                        for other in pending:
                            endpoint = tasks[other]
                            if endpoint.cancel_supported:
                                other.cancel()
                            else:
                                self.status(endpoint.name, "draining unused request")
                            self.draining.add(other)
                            other.add_done_callback(self.draining.discard)
                        return result
            actionable = next(
                (r for r in results if not r.error and r.header.get("action") in {"NEW", "UPDATE"}),
                None,
            )
            if actionable:
                return actionable
            return next((r for r in results if not r.error), results[0])
        except BaseException:
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            raise

    async def close(self):
        if self.draining:
            draining = list(self.draining)
            for task in draining:
                task.cancel()
            await asyncio.gather(*draining, return_exceptions=True)
        for lane in self.sockets.values():
            await lane.close()
        await self.client.aclose()
