#!/usr/bin/env python3
"""Clearly labelled synthetic UI harness; no test routes enter the application."""

import asyncio
from pathlib import Path
import uvicorn
from interview_helper.app import create_app
from interview_helper.config import Config
from interview_helper.session import Session

QUESTIONS = [
    (
        "What is the difference between a process and a thread?",
        "A process owns an isolated address space; threads share their process resources.\n- Use threads for work that benefits from shared memory and low switching overhead.\n- Use processes for isolation and independent failure boundaries.\n- Shared mutable state still needs careful coordination.",
    ),
    (
        "How does Python manage mutable default arguments?",
        "Default arguments are evaluated once when the function is defined.\n- A mutable default can retain changes across calls.\n- Use `None` as a sentinel and create the collection inside the function.\n- An intentionally shared default should be explicit and documented.",
    ),
    (
        "Explain C++ RAII and exception safety.",
        "RAII ties resource ownership to object lifetime, so destructors release resources deterministically.\n- Prefer standard containers and smart pointers over manual cleanup.\n- Stack unwinding calls destructors for fully constructed automatic objects.\n- This protects resources on both normal returns and exceptions.",
    ),
    (
        "How would you investigate a Java deadlock?",
        "Capture thread dumps and identify a cycle of threads waiting for locks held by one another.\n- Take several dumps to distinguish a persistent deadlock from temporary contention.\n- Inspect lock ordering and nested synchronized calls.\n- Reduce lock scope or enforce a consistent acquisition order.",
    ),
    (
        "When should a Perl hash lookup use exists?",
        "Use `exists` when you need to distinguish a missing key from a key whose value is `undef`.\n- A normal lookup returns `undef` for either case.\n- Use `defined` when the value itself must be defined.\n- Avoid accidentally changing nested structures while inspecting them.",
    ),
    (
        "How do you prevent duplicate charges with at-least-once delivery?",
        "Make the payment operation idempotent with a stable key for each intended charge.\n- Pass that key to a payment provider that guarantees idempotent processing.\n- Persist request state and results so retries can recover safely.\n- Reconcile uncertain outcomes instead of issuing a fresh charge blindly.",
    ),
]


async def main():
    config = Config.load(Path(".local/ui-fixture/config.local.toml"))
    config.port = 8788
    session = Session(config)
    session.start(replay=True)
    session.notice("UI VALIDATION FIXTURE — synthetic questions; no live audio or model claims")

    def add(index):
        q, a = QUESTIONS[index % len(QUESTIONS)]
        card = {
            "id": f"fixture-{index}",
            "question": q,
            "answer": a,
            "state": "complete",
            "developing": False,
            "host": "fixture model",
            "revision": index + 1,
            "request_id": f"fixture-{index}",
        }
        session.controller.cards.append(card)
        session.save({"type": "hint", **card}, True)

    for i in range(6):
        add(i)
    session.devices = {
        "fixture": {
            "name": "fixture",
            "label": "Synthetic speaker output",
            "state": "fixture",
            "level": 0.28,
        }
    }
    session.status.update(
        capture="synthetic fixture", asr="fixture only", model="fixture only", save="saved"
    )

    async def commands():
        path = Path(".local/ui-fixture/add-question")
        previous = None
        streamed = None
        stream_path = Path(".local/ui-fixture/stream-question")
        while session.state == "recording":
            if path.exists():
                stamp = path.stat().st_mtime_ns
                if stamp != previous:
                    previous = stamp
                    add(len(session.controller.cards))
            if stream_path.exists() and stream_path.stat().st_mtime_ns != streamed:
                streamed = stream_path.stat().st_mtime_ns
                index = len(session.controller.cards)
                question, answer = QUESTIONS[1]
                card = {
                    "id": f"stream-{streamed}",
                    "request_id": f"stream-{streamed}",
                    "question": question,
                    "answer": "",
                    "state": "generating",
                    "developing": False,
                    "host": "fixture model",
                    "revision": index + 1,
                }
                session.transcript.append(
                    {"text": question, "source_name": "Synthetic playback", "revision": index + 1}
                )
                session.provisional["fixture"] = "Synthetic provisional words…"
                session.status["model"] = "generating fixture"
                for part in answer.split("\n"):
                    card["answer"] += ("\n" if card["answer"] else "") + part
                    await session.publish("draft", card.copy())
                    await asyncio.sleep(3)
                card["state"] = "complete"
                session.controller.cards.append(card)
                session.save({"type": "hint", **card}, True)
                await session.publish("card", card)
                session.status["model"] = "fixture only"
            await asyncio.sleep(0.2)

    task = asyncio.create_task(commands())
    try:
        await uvicorn.Server(
            uvicorn.Config(
                create_app(config, session), host="127.0.0.1", port=8788, access_log=False
            )
        ).serve()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(main())
