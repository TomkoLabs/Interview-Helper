import json
import pytest
from interview_helper.config import Config
from interview_helper.gateway import Outcome
from interview_helper.storage import SessionStore
from interview_helper.summary import summarize


@pytest.mark.asyncio
async def test_summary_covers_all_revised_playback_in_bounded_parts(tmp_path, monkeypatch):
    config = Config.load(tmp_path / "missing")
    store = SessionStore(config.data_dir)
    text = "durable requirement " * 700
    event = dict(
        type="transcript",
        segment_id="one",
        source="a",
        source_name="Speaker",
        revision=1,
        start=0,
        end=5,
        text="obsolete",
    )
    store.append(event)
    store.append(dict(event, revision=2, text=text))
    store.append({"type": "hint", "answer": "GENERATED NOT SPOKEN"}, hint=True)
    store.close()
    requests = []

    class Gateway:
        def __init__(self, endpoints):
            pass

        async def race(self, messages, *args):
            request = json.loads(messages[-1]["content"])
            requests.append(request)
            return Outcome("fixture", {"action": "NEW"}, ["Summary"], 0.1, 0.2)

        async def close(self):
            pass

    monkeypatch.setattr("interview_helper.summary.Gateway", Gateway)
    output = await summarize(config, store.id)
    assert len(requests) == 3
    combined = "".join(r["quoted_playback"] for r in requests)
    assert combined == f"[0.0s] Speaker: {text}\n"
    assert all(len(r["quoted_playback"]) <= 6000 for r in requests)
    assert "GENERATED NOT SPOKEN" not in combined and "obsolete" not in combined
    assert len(json.loads(output.read_text())["parts"]) == 3
    assert output.stat().st_mode & 0o777 == 0o600


async def test_cloud_summary_retains_summary_instructions_and_output_limit(tmp_path, monkeypatch):
    import httpx
    from interview_helper.connections import cloud_endpoint
    from interview_helper.gateway import Gateway as RealGateway
    from interview_helper.summary import SUMMARY_PROMPT

    config = Config.load(tmp_path / "config.local.toml")
    endpoint = cloud_endpoint(config, "openai_api", tier="ultrafast")
    endpoint.api_key = "fixture"
    config.endpoints = [endpoint]
    store = SessionStore(config.data_dir)
    store.append(
        dict(
            type="transcript",
            segment_id="one",
            source="a",
            source_name="Speaker",
            revision=1,
            start=0,
            end=1,
            text="Explain Java 8 across multiple JVMs.",
        )
    )
    store.close()
    requests = []

    class Gateway(RealGateway):
        async def race(self, *args, **kwargs):
            await self.client.aclose()

            def handler(request):
                payload = json.loads(request.content)
                requests.append(payload)
                text = (
                    '{"action":"NEW","question":"Playback session summary","developing":false}\n'
                    '{"text":"The remote speaker asked about Java 8 across multiple JVMs."}\n{"done":true}\n'
                )
                events = [
                    {"type": "response.output_text.delta", "delta": text},
                    {
                        "type": "response.completed",
                        "response": {"status": "completed", "service_tier": "ultrafast"},
                    },
                ]
                return httpx.Response(
                    200, text="".join("data: " + json.dumps(e) + "\n\n" for e in events)
                )

            self.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
            return await super().race(*args, **kwargs)

    monkeypatch.setattr("interview_helper.summary.Gateway", Gateway)
    output = await summarize(config, store.id)
    assert requests[0]["instructions"] == SUMMARY_PROMPT
    assert requests[0]["max_output_tokens"] == 1024
    assert requests[0]["service_tier"] == "ultrafast"
    assert config.endpoints[0].compact is True  # Session profile untouched.
    assert "Java 8" in json.loads(output.read_text())["parts"][0]["text"]
