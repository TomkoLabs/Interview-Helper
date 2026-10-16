"""One serial Responses lane. No replay after an uncertain dispatched request."""

import json
import time
from contextlib import asynccontextmanager
from websockets.asyncio.client import connect

TERMINAL = {"response.completed", "response.failed", "response.incomplete", "error"}


class SocketResponse:
    status_code = 200
    headers = {}
    http_version = "WebSocket"

    def __init__(self, lane, payload, diagnostics, mark):
        self.lane, self.payload, self.diagnostics, self.mark = lane, payload, diagnostics, mark
        self.extensions = {}

    async def aiter_lines(self):
        lane = self.lane
        body = {k: v for k, v in self.payload.items() if k not in {"stream", "background"}}
        original_input = body["input"]
        # Only exact append-only input prefixes can be replaced by a delta. Snapshot
        # replacements reset the context, so no hidden hour-long answer chain grows.
        previous = lane.previous_input
        continued = bool(
            lane.previous_id
            and lane.turns < 4
            and previous
            and original_input[: len(previous)] == previous
            and len(original_input) > len(previous)
            and len(json.dumps(original_input)) < 24000
        )
        delta = original_input[len(previous) :] if continued else None
        if (
            "CONTEXT_APPEND" in body.get("instructions", "")
            and not continued
            and lane.previous_id
            and lane.turns < 4
            and previous
            and original_input[:-1] == previous[:-1]
            and len(json.dumps(original_input)) < 24000
        ):
            try:
                old = json.loads(previous[-1]["content"])
                new = json.loads(original_input[-1]["content"])
                fields = ("SCENARIO_REQUIREMENTS", "RECENT_CONVERSATION")
                if all(
                    isinstance(old.get(k), str)
                    and isinstance(new.get(k), str)
                    and new[k].startswith(old[k])
                    for k in fields
                ):
                    update = dict(new)
                    for k in fields:
                        update[k] = new[k][len(old[k]) :]
                    update["CONTEXT_APPEND"] = True
                    delta = [{"role": "user", "content": json.dumps(update, ensure_ascii=False)}]
                    continued = True
            except (ValueError, KeyError, TypeError, IndexError):
                pass  # Unrecognized/replaced state always receives the full snapshot.
        if continued:
            body["previous_response_id"] = lane.previous_id
            body["input"] = delta
        self.diagnostics["continuation"] = continued
        for attempt in range(2):
            self.mark("wire_dispatch")
            await lane.socket.send(json.dumps({"type": "response.create", **body}))
            started = False
            retry = False
            async for wire in lane.socket:
                event = json.loads(wire)
                kind = event.get("type")
                code = (event.get("error") or {}).get("code")
                if (
                    kind == "error"
                    and not started
                    and attempt == 0
                    and code
                    in {"previous_response_not_found", "websocket_connection_limit_reached"}
                ):
                    # Explicit pre-generation rejection, not a blind retry.
                    self.diagnostics["recovery"] = code
                    body.pop("previous_response_id", None)
                    body["input"] = original_input
                    if code == "websocket_connection_limit_reached":
                        await lane.close()
                        await lane.open(lane.key, self.mark)
                    retry = True
                    break
                started = started or kind == "response.created"
                if kind == "response.completed":
                    lane.previous_id = event.get("response", {}).get("id")
                    lane.previous_input = original_input
                    lane.turns = lane.turns + 1 if continued else 1
                yield "data: " + json.dumps(event)
                if kind in TERMINAL:
                    if kind != "response.completed":
                        lane.previous_id = None
                    return
            if not retry:
                raise ConnectionError("Responses WebSocket disconnected before completion")
        raise ConnectionError("Responses WebSocket recovery failed")


class Lane:
    def __init__(self):
        self.socket = None
        self.key = None
        self.created = 0
        self.previous_id = None
        self.previous_input = []
        self.turns = 0
        self.generation = 0

    async def open(self, key, mark):
        self.key = key
        mark("websocket_connect_started")
        self.socket = await connect(
            "wss://api.openai.com/v1/responses",
            additional_headers={"Authorization": "Bearer " + key},
            proxy=None,
            open_timeout=10,
            close_timeout=2,
            max_size=2**20,
            ping_interval=20,
        )
        self.created = time.monotonic()
        self.generation += 1
        mark("websocket_connect_complete")

    async def close(self):
        if self.socket is not None:
            await self.socket.close()
        self.socket = None
        self.previous_id = None
        self.previous_input = []
        self.turns = 0

    @asynccontextmanager
    async def response(self, client, endpoint, key, payload, request_id, mark, diagnostics, trace):
        # Rotate before the documented 60-minute limit and when app-owned renewal
        # produces a new token. No inference is used to keep a connection warm.
        if self.socket is not None and (
            self.key != key
            or time.monotonic() - self.created >= 3300
            or self.socket.close_code is not None
        ):
            await self.close()
        reused = self.socket is not None
        if not reused:
            try:
                await self.open(key, mark)
            except Exception as exc:
                # Handshake failed: no response.create was sent. HTTP is safe here.
                diagnostics["websocket_fallback"] = type(exc).__name__
                async with client.stream(
                    "POST",
                    endpoint.base_url.rstrip("/") + "/responses",
                    headers={"Authorization": "Bearer " + key, "X-Request-ID": request_id},
                    json=payload,
                    extensions={"trace": trace},
                    timeout=endpoint.timeout,
                ) as response:
                    yield response
                return
        diagnostics.update(connection_id="ws-" + str(self.generation), connection_reused=reused)
        try:
            yield SocketResponse(self, payload, diagnostics, mark)
        except BaseException:
            # After dispatch an interrupted response may still be running remotely.
            # Close it, discard continuation, and let the gateway quarantine it.
            await self.close()
            raise
