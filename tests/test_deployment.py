"""Offline deployment, preference and spending-boundary regressions."""

import json
from pathlib import Path
import httpx
import pytest
from fastapi.testclient import TestClient
from interview_helper.app import create_app
from interview_helper.budget import Budget
from interview_helper.config import Config
from interview_helper.connections import cloud_endpoint, select
from interview_helper.gateway import Gateway


PROFILE = Path(__file__).parents[1] / "config.kraken.toml"


def profile(tmp_path):
    path = tmp_path / "config.local.toml"
    path.write_bytes(PROFILE.read_bytes())
    return path, Config.load(path)


def test_kraken_profile_and_preferences_survive_restart_without_secrets(tmp_path):
    path, config = profile(tmp_path)
    e = config.endpoints[0]
    assert e.backend == "openai_api" and e.model == "gpt-6.1-sol"
    assert e.transport == "http" and e.timeout == 120 and not e.cancel_supported
    assert e.parameters == {
        "reasoning_effort": "low",
        "service_tier": "ultrafast",
        "max_output_tokens": 1024,
    }
    assert (config.device, config.compute_type) == ("cuda", "float16")
    assert e.api_key_file == str(tmp_path / ".local/openai-api-key")
    select(config, {"provider": "local"})
    assert Config.load(path).endpoints == []  # Explicit local choice wins over cloud TOML.
    choice = {
        "provider": "openai_api",
        "model": "gpt-6.1-sol",
        "reasoning": "low",
        "tier": "ultrafast",
        "transport": "http",
    }
    select(config, choice)
    loaded = Config.load(path)
    assert loaded.endpoints[0].parameters == e.parameters
    assert json.loads(config.selection_file.read_text()) == choice
    assert config.selection_file.stat().st_mode & 0o777 == 0o600
    assert path.read_bytes() == PROFILE.read_bytes()
    # Invalid persisted local choices must not silently revert to a paid default.
    config.selection_file.write_text('{"provider":"local","api_key":"forbidden"}')
    with pytest.raises(ValueError, match="Saved connection"):
        Config.load(path)


def test_existing_local_profiles_remain_available_after_cloud_restart(tmp_path):
    path = tmp_path / "config.local.toml"
    path.write_text("""strategy = "race"
[[endpoints]]
name = "a"
base_url = "http://localhost:8001/v1"
model = "a"
[[endpoints]]
name = "b"
base_url = "http://localhost:8002/v1"
model = "b"
""")
    c = Config.load(path)
    select(c, {"provider": "openai_api", "model": "gpt-6.1-sol", "tier": "ultrafast"})
    c = Config.load(path)
    assert c.strategy == "single" and c.endpoints[0].backend == "openai_api"
    select(c, {"provider": "local"})
    c = Config.load(path)
    assert c.strategy == "race" and [e.name for e in c.endpoints] == ["a", "b"]


def test_ui_selection_is_idle_only_persistent_and_uses_tested_ceiling(tmp_path, monkeypatch):
    path, config = profile(tmp_path)

    async def choices(*_):
        return [{"id": "gpt-6.1-sol", "name": "Sol"}]

    monkeypatch.setattr(Gateway, "model_choices", choices)
    app = create_app(config)
    with TestClient(app, base_url="http://127.0.0.1:8787") as client:
        client.get("/")
        headers = {
            "Origin": "http://127.0.0.1:8787",
            "X-Interview-CSRF": client.get("/api/state").json()["csrf"],
        }
        body = {
            "provider": "openai_api",
            "model": "gpt-6.1-sol",
            "reasoning": "low",
            "tier": "ultrafast",
            "transport": "http",
            "send_transcript_to_openai": True,
        }
        assert (
            client.post(
                "/api/cloud/select",
                json={**body, "send_transcript_to_openai": False},
                headers=headers,
            ).status_code
            == 409
        )
        app.state.session.state = "recording"
        assert client.post("/api/cloud/select", json=body, headers=headers).status_code == 409
        app.state.session.state = "idle"
        assert client.post("/api/cloud/select", json=body, headers=headers).status_code == 200
        assert Config.load(path).endpoints[0].parameters["max_output_tokens"] == 1024
        state = client.get("/api/state").json()
        assert state["backend"][0]["tier"] == "ultrafast"
        assert "api_key" not in json.dumps(state)
        assert client.post("/api/cloud/local", headers=headers).status_code == 200
        assert Config.load(path).endpoints == []


async def test_normal_gateway_ignores_exhausted_benchmark_ledger(tmp_path, monkeypatch):
    _, config = profile(tmp_path)
    ledger = tmp_path / ".local/0.1.3/cost-ledger.json"
    ledger.parent.mkdir(parents=True)
    ledger.write_text(json.dumps({"cap_usd": 5, "requests": {"old": {"reserved_usd": 5}}}))
    before = ledger.read_bytes()

    def forbidden(*_):
        raise AssertionError("Normal session must not access benchmark budget")

    monkeypatch.setattr(Budget, "__init__", forbidden)
    e = cloud_endpoint(config, "openai_api", tier="ultrafast")
    e.api_key = "fixture"
    g = Gateway([e])
    await g.client.aclose()

    def handler(req):
        body = json.loads(req.content)
        assert body["model"] == "gpt-6.1-sol" and body["reasoning"] == {"effort": "low"}
        assert body["service_tier"] == "ultrafast" and body["max_output_tokens"] == 1024
        events = [
            {
                "type": "response.created",
                "response": {"model": "gpt-6.1-sol", "service_tier": "ultrafast"},
            },
            {"type": "response.output_text.delta", "delta": '{"action":"WAIT"}\n{"done":true}\n'},
            {
                "type": "response.completed",
                "response": {
                    "status": "completed",
                    "model": "gpt-6.1-sol",
                    "service_tier": "default",
                },
            },
        ]
        return httpx.Response(200, text="".join("data: " + json.dumps(e) + "\n\n" for e in events))

    g.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    async def emit(*_):
        pass

    try:
        result = await g.stream(
            e,
            [{"role": "system", "content": "fixture"}, {"role": "user", "content": "{}"}],
            "id",
            emit,
        )
        assert not result.error
        assert result.diagnostics["response_service_tier"] == "default"
        assert result.diagnostics["created_service_tier"] == "ultrafast"
        assert ledger.read_bytes() == before
    finally:
        await g.close()


def test_key_helper_hidden_entry_private_modes_and_no_overwrite(tmp_path, monkeypatch, capsys):
    import runpy
    import getpass

    scripts = tmp_path / "scripts"
    scripts.mkdir()
    helper = scripts / "configure_openai.py"
    helper.write_bytes((PROFILE.parent / "scripts/configure_openai.py").read_bytes())
    entered = []

    def hidden(prompt):
        entered.append(prompt)
        return "fixture-only-not-a-real-key"

    monkeypatch.setattr(getpass, "getpass", hidden)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    runpy.run_path(str(helper), run_name="__main__")
    key = tmp_path / ".local/openai-api-key"
    assert key.stat().st_mode & 0o777 == 0o600
    assert key.parent.stat().st_mode & 0o777 == 0o700
    assert key.read_text().strip() == "fixture-only-not-a-real-key"
    assert "fixture-only" not in capsys.readouterr().out
    before = key.read_bytes()
    with pytest.raises(SystemExit, match="already exists"):
        runpy.run_path(str(helper), run_name="__main__")
    assert len(entered) == 1 and key.read_bytes() == before


@pytest.mark.parametrize("kraken", [False, True])
def test_installer_preserves_selected_profile_without_real_install(tmp_path, kraken):
    import os
    import subprocess
    import sys

    for name in ("install.sh", "config.example.toml", "config.kraken.toml"):
        (tmp_path / name).write_bytes((PROFILE.parent / name).read_bytes())
    fake = tmp_path / ".venv/bin"
    fake.mkdir(parents=True)
    python = fake / "python"
    python.write_text("#!/bin/sh\nexit 0\n")  # No pip/network/dependency work in this test.
    python.chmod(0o700)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gpu = bin_dir / "nvidia-smi"
    gpu.write_text('#!/bin/sh\nprintf "SIMULATED GPU, fixture driver\\n"\n')
    gpu.chmod(0o700)
    config = tmp_path / "config.local.toml"
    if kraken:
        config.write_bytes(PROFILE.read_bytes())
    env = {**os.environ, "PYTHON": sys.executable, "PATH": str(bin_dir) + ":" + os.environ["PATH"]}
    subprocess.run(
        ["bash", "install.sh", "--gpu" if kraken else "--cpu"],
        cwd=tmp_path,
        env=env,
        check=True,
        capture_output=True,
    )
    loaded = Config.load(config)
    if kraken:
        assert config.read_bytes() == PROFILE.read_bytes()
        assert loaded.endpoints[0].parameters["max_output_tokens"] == 1024
    else:
        assert (
            loaded.device == "cpu"
            and loaded.compute_type == "int8"
            and loaded.endpoints[0].backend == "openai_api"
        )
    before = config.read_bytes()
    subprocess.run(
        ["bash", "install.sh", "--gpu"], cwd=tmp_path, env=env, check=True, capture_output=True
    )
    assert config.read_bytes() == before


def test_saved_chatgpt_account_remains_selected_without_transferring_tokens(tmp_path):
    from interview_helper.session import Session

    path, config = profile(tmp_path)
    account = "a" * 24
    select(config, {"provider": "chatgpt", "account": account, "model": "gpt-6-luna"})
    loaded = Config.load(path)
    assert loaded.endpoints[0].backend == "chatgpt"
    assert Session(loaded).view()["backend"][0]["account"] == account
    assert "access_token" not in loaded.selection_file.read_text()
    assert not loaded.endpoints[0].parameters.get("max_output_tokens")
    assert loaded.endpoints[0].parameters == {"reasoning_effort": "low"}


@pytest.mark.parametrize(
    "script",
    [
        "benchmark",
        "scenario_acceptance",
        "race_acceptance",
        "end_to_end_audio",
        "latency_evaluation",
    ],
)
async def test_legacy_evaluation_rejects_paid_deployment_before_side_effects(
    tmp_path, monkeypatch, script
):
    import runpy
    from types import SimpleNamespace
    import asyncio

    monkeypatch.syspath_prepend(str(PROFILE.parent / "scripts"))
    module = runpy.run_path(str(PROFILE.parent / "scripts" / (script + ".py")))
    path, config = profile(tmp_path)

    async def forbidden(*args, **kwargs):
        raise AssertionError("Guard must run before subprocess/network work")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", forbidden)
    monkeypatch.setattr(Gateway, "race", forbidden)
    monkeypatch.setattr(Gateway, "stream", forbidden)
    if script == "latency_evaluation":
        args = (SimpleNamespace(config=path),)
    elif script == "end_to_end_audio":
        args = (config, tmp_path / "absent.wav", tmp_path / "output")
    else:
        args = (config, tmp_path / "output")
    with pytest.raises(ValueError, match="cost-capped"):
        await module["run"](*args)
    assert not (tmp_path / "output").exists()
