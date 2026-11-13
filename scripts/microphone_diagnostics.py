#!/usr/bin/env python3
"""Read-only, narrowly filtered PipeWire evidence. No IH imports or audio capture."""

from datetime import datetime, timezone
import json
import subprocess


def filtered_graph(records):
    nodes = {r["id"]: r for r in records if r.get("type") == "PipeWire:Interface:Node"}
    owned = {
        i
        for i, r in nodes.items()
        if r.get("info", {}).get("props", {}).get("node.name", "").startswith("ih-aec-")
    }
    links = [
        r
        for r in records
        if r.get("type") == "PipeWire:Interface:Link"
        and (
            r.get("info", {}).get("input-node-id") in owned
            or r.get("info", {}).get("output-node-id") in owned
        )
    ]
    connected = set(owned)
    ports = set()
    for r in links:
        info = r["info"]
        connected.update((info.get("input-node-id"), info.get("output-node-id")))
        ports.update((info.get("input-port-id"), info.get("output-port-id")))
    targets = {nodes[i].get("info", {}).get("props", {}).get("target.object") for i in owned}
    connected.update(
        i
        for i, r in nodes.items()
        if r.get("info", {}).get("props", {}).get("node.name") in targets
    )
    node_keys = {
        "node.name",
        "object.serial",
        "media.class",
        "device.class",
        "target.object",
        "node.autoconnect",
        "node.dont-fallback",
        "node.dont-reconnect",
    }
    port_keys = {"port.name", "port.direction", "port.monitor", "audio.channel", "node.id"}
    result = []
    for r in records:
        kind, ident = r.get("type", "").split(":")[-1], r.get("id")
        info = r.get("info", {})
        if kind == "Node" and ident in connected or kind == "Port" and ident in ports:
            keys = node_keys if kind == "Node" else port_keys
            result.append(
                {
                    "id": ident,
                    "type": kind,
                    "state": info.get("state"),
                    "props": {k: v for k, v in info.get("props", {}).items() if k in keys},
                }
            )
        elif r in links:
            result.append(
                {
                    "id": ident,
                    "type": kind,
                    **{
                        k: v
                        for k, v in info.items()
                        if k
                        in {
                            "state",
                            "error",
                            "input-node-id",
                            "output-node-id",
                            "input-port-id",
                            "output-port-id",
                        }
                    },
                }
            )
    return result


def main():
    report = {
        "time_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "IH AEC nodes, immediate linked endpoints and ports; no audio",
    }
    try:
        proc = subprocess.run(["pw-dump"], capture_output=True, timeout=5, check=True)
        data = json.loads(proc.stdout)
        if not isinstance(data, list):
            raise ValueError("Expected graph array")
        report["graph"] = filtered_graph(data)
        report["note"] = (
            "No IH nodes found"
            if not report["graph"]
            else "Snapshot only; retry during failure if needed"
        )
    except (OSError, subprocess.SubprocessError, ValueError, TypeError, KeyError) as exc:
        # Do not echo arbitrary process stderr or environment.
        report["error"] = type(exc).__name__
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
