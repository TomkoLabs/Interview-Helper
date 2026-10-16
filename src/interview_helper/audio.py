"""Read-only PulseAudio/PipeWire monitor discovery and bounded PCM capture."""

import asyncio
from dataclasses import dataclass
from fnmatch import fnmatchcase
import json
import re
import shlex
import time
import numpy as np


@dataclass(frozen=True)
class Monitor:
    name: str
    label: str
    sink: str


class AudioDiscoveryError(RuntimeError):
    """A discovery-stage failure safe to show without raw server output."""


async def pactl(kind):
    try:
        return await _pactl(kind)
    except json.JSONDecodeError as exc:
        raise AudioDiscoveryError(f"pactl {kind}: invalid JSON") from exc
    except (ValueError, RuntimeError) as exc:
        raise AudioDiscoveryError(f"pactl {kind}: {exc}") from exc
    except (OSError, TimeoutError) as exc:
        raise AudioDiscoveryError(f"pactl {kind}: {type(exc).__name__}") from exc


async def _pactl(kind):
    process = await asyncio.create_subprocess_exec(
        "pactl",
        "--format=json",
        "list",
        kind,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), 5)
    except BaseException:
        process.kill()
        await process.wait()
        raise
    if process.returncode:
        raise RuntimeError("Audio server unavailable; check pactl info / pipewire-pulse")
    data = json.loads(stdout)
    if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
        raise ValueError("Expected a JSON list of records")
    if kind == "modules" and any("index" not in module for module in data):
        # PulseAudio 17 JSON omits module indices; its short format retains them.
        process = await asyncio.create_subprocess_exec(
            "pactl",
            "list",
            "short",
            "modules",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            short, _ = await asyncio.wait_for(process.communicate(), 5)
        except BaseException:
            process.kill()
            await process.wait()
            raise
        if process.returncode:
            raise RuntimeError("Cannot read indexed audio module topology")
        data = parse_short_modules(short.decode(), data)
    if kind == "modules":
        validate_module_identities(data)
    return data


def validate_module_identities(modules):
    indices = set()
    for module in modules:
        index, name = module.get("index"), module.get("name")
        if (
            type(index) is not int
            or not 0 <= index < 4294967295
            or index in indices
            or not isinstance(name, str)
            or not name
            or any(c.isspace() for c in name)
            or not isinstance(module.get("argument", ""), str)
        ):
            raise ValueError("Invalid or duplicate module identity")
        indices.add(index)


def parse_short_modules(text, expected=None):
    # JSON supplies exact record boundaries, even for native PipeWire arguments
    # containing newlines/tabs/comments. Only short output supplies Pulse indices.
    # A topology change between reads fails visibly and is retried by discovery.
    if expected is not None:
        modules, offset = [], 0
        for record in expected:
            name, argument = record.get("name"), record.get("argument", "")
            if not isinstance(name, str) or not isinstance(argument, str):
                raise ValueError("Invalid module JSON identity/argument")
            pattern = (
                r"([0-9]+)\t"
                + re.escape(name)
                + r"\t"
                + re.escape(argument)
                + r"(?:\t[^\t\r\n]*)?(?:\n|$)"
            )
            match = re.compile(pattern).match(text, offset)
            if not match:
                raise ValueError("Indexed module topology does not match JSON records")
            index = int(match[1])
            if "index" in record and (type(record["index"]) is not int or record["index"] != index):
                raise ValueError("Conflicting module indices")
            modules.append({"index": index, "name": name, "argument": argument})
            offset = match.end()
        if offset != len(text):
            raise ValueError("Unexpected trailing indexed module data")
        validate_module_identities(modules)
        return modules
    modules = []
    for line in text.splitlines():
        columns = line.split("\t")
        if len(columns) < 2 or not columns[0].isdigit():
            raise ValueError("Unrecognized pactl module topology")
        modules.append(
            {
                "index": int(columns[0]),
                "name": columns[1],
                "argument": columns[2] if len(columns) > 2 else "",
            }
        )
    validate_module_identities(modules)
    return modules


def select_monitors(sinks, sources, modules, inputs, outputs, include=(), exclude=()):
    """Prefer upstream monitors for known forwarding chains; never mix identities.

    module-loopback source→sink and combine/remap master/slaves are supported.
    Skip downstream only when it has no independent application input. If it
    does, keep downstream and suppress upstream when all its targets are kept.
    Unknown graphs remain visible and can be overridden explicitly.
    """
    by_index = {str(s["index"]): s["name"] for s in sinks}
    by_source = {str(s["index"]): s["name"] for s in sources}
    source_to_sink = {
        str(s[key]): s["name"]
        for s in sinks
        for key in ("monitor_source", "monitor_source_name")
        if s.get(key) not in (None, "")
    }
    for s in sources:
        sink = (
            source_to_sink.get(s["name"])
            or source_to_sink.get(str(s["index"]))
            or by_index.get(str(s.get("monitor_of_sink")))
        )
        if sink:
            source_to_sink[s["name"]] = sink
            source_to_sink[str(s["index"])] = sink
    edges = set()
    forwarding_owners = set()

    def args(module):
        return dict(p.split("=", 1) for p in shlex.split(module.get("argument", "")) if "=" in p)

    for m in modules:
        name = m["name"]
        if name not in {"module-loopback", "module-combine-sink", "module-remap-sink"}:
            continue  # Native PipeWire arguments are SPA syntax, not shell arguments.
        a = args(m)
        owner = str(m["index"])
        forwarding_owners.add(owner)
        if name == "module-loopback":
            src = a.get("source")
            dst = a.get("sink")
            # Actual stream relationships also work when module args use defaults.
            src = src or next(
                (
                    by_source.get(str(o["source"]))
                    for o in outputs
                    if str(o.get("owner_module")) == owner
                ),
                None,
            )
            dst = dst or next(
                (
                    by_index.get(str(i["sink"]))
                    for i in inputs
                    if str(i.get("owner_module")) == owner
                ),
                None,
            )
            if src in source_to_sink and dst:
                edges.add((source_to_sink[src], by_index.get(str(dst), dst)))
        elif name in {"module-combine-sink", "module-remap-sink"}:
            upstream = a.get("sink_name") or next(
                (s["name"] for s in sinks if str(s.get("owner_module")) == owner), None
            )
            downstream = a.get("slaves", a.get("master", "")).split(",")
            downstream += [
                by_index.get(str(i["sink"]), "")
                for i in inputs
                if str(i.get("owner_module")) == owner
            ]
            edges.update((upstream, by_index.get(str(d), d)) for d in downstream if upstream and d)
    independent = {
        by_index.get(str(i["sink"]))
        for i in inputs
        if str(i.get("owner_module")) not in forwarding_owners
    }
    # A feedback cycle has no reliable upstream capture point. Preserve monitors
    # and surface uncertainty rather than accidentally suppressing the whole cycle.
    cyclic = False
    for origin in {u for u, _ in edges}:
        pending = [d for u, d in edges if u == origin]
        seen = set()
        while pending:
            node = pending.pop()
            if node == origin:
                cyclic = True
                break
            if node not in seen:
                seen.add(node)
                pending.extend(d for u, d in edges if u == node)
        if cyclic:
            break
    omitted = set()
    for upstream, downstream in sorted(edges):
        if downstream not in independent:
            omitted.add(downstream)
    for upstream in {u for u, _ in edges}:
        targets = {d for u, d in edges if u == upstream}
        if targets and not (targets & omitted):
            omitted.add(upstream)
    if cyclic:
        omitted.clear()
    monitors, warnings = [], []
    for s in sources:
        sink = source_to_sink.get(s["name"])
        if not sink:
            continue  # Physical microphones never admitted by include patterns.
        explicit = bool(include) and any(fnmatchcase(s["name"], p) for p in include)
        if include and not explicit:
            continue
        if any(fnmatchcase(s["name"], p) for p in exclude):
            continue
        if sink in omitted and not explicit:
            continue
        monitors.append(Monitor(s["name"], s.get("description", s["name"]), sink))
    if cyclic:
        warnings.append(
            "Forwarding cycle: monitors retained; use include/exclude to avoid duplicates"
        )
    elif edges:
        warnings.append(
            "Known forwarding topology deduplicated; independent downstream mixes may overlap"
        )
    return monitors, warnings


async def discover(include=(), exclude=()):
    data = await asyncio.gather(
        *(pactl(k) for k in ("sinks", "sources", "modules", "sink-inputs", "source-outputs"))
    )
    try:
        return select_monitors(*data, include, exclude)
    except (ValueError, KeyError, TypeError) as exc:
        raise AudioDiscoveryError(
            "monitor topology: invalid records or forwarding arguments"
        ) from exc


class Capture:
    """One process/source. A full 30-second queue stops capture with a visible gap."""

    def __init__(self, monitor, on_status, start_time):
        self.monitor = monitor
        self.on_status = on_status
        self.start_time = start_time
        self.queue = asyncio.Queue(maxsize=300)
        self.process = None
        self.task = None
        self.stopping = False

    async def start(self):
        self.process = await asyncio.create_subprocess_exec(
            "parec",
            "--device=" + self.monitor.name,
            "--raw",
            "--format=float32le",
            "--rate=16000",
            "--channels=1",
            "--latency-msec=100",
            "--client-name=IH",
            "--stream-name=Playback transcription",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        self.task = asyncio.create_task(self._read())

    async def _read(self):
        try:
            while not self.stopping:
                data = await self.process.stdout.readexactly(6400)  # 100 ms mono float32
                timestamp = time.monotonic() - self.start_time - 0.1
                block = np.frombuffer(data, dtype="<f4").copy()
                try:
                    self.queue.put_nowait((max(0, timestamp), block))
                except asyncio.QueueFull:
                    self.on_status(
                        self.monitor.name, "failed", "ASR backlog exceeded 30s; capture stopped"
                    )
                    break
        except asyncio.IncompleteReadError as exc:
            if exc.partial and len(exc.partial) % 4 == 0 and not self.queue.full():
                self.queue.put_nowait(
                    (
                        time.monotonic() - self.start_time,
                        np.frombuffer(exc.partial, dtype="<f4").copy(),
                    )
                )
            if not self.stopping:
                self.on_status(self.monitor.name, "disconnected", "Audio source disconnected")
        finally:
            if self.process.returncode is None:
                self.process.terminate()
                await self.process.wait()
            self.stopping = True

    async def stop(self):
        self.stopping = True
        if self.process and self.process.returncode is None:
            self.process.terminate()
        if self.task:
            await self.task
