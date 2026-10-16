"""No paid calls: setup guards, cached ASR and actual shell install selection."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from interview_helper.config import Config
from interview_helper.connections import select
from interview_helper.setup import ensure_credentials, prepare

ROOT = Path(__file__).parents[1]


def configured(tmp_path):
    path = tmp_path / "config.local.toml"
    path.write_bytes((ROOT / "config.example.toml").read_bytes())
    path.write_text(
        path.read_text()
        .replace('device = "cuda"', 'device = "cpu"')
        .replace('compute_type = "float16"', 'compute_type = "int8"')
    )
    return Config.load(path)


def test_noninteractive_missing_key_does_not_prompt_or_change_provider(tmp_path, monkeypatch):
    c = configured(tmp_path)
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts/configure_openai.py").write_text("")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    with pytest.raises(ValueError, match="interactive terminal"):
        ensure_credentials(c)
    assert c.endpoints[0].backend == "openai_api"
    assert not (tmp_path / ".local/openai-api-key").exists()


def test_precedence_saved_local_and_subscription_are_preserved(tmp_path, monkeypatch):
    c = configured(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-environment")
    monkeypatch.setattr("subprocess.run", lambda *_a, **_k: pytest.fail("Unexpected key prompt"))
    ensure_credentials(c)
    select(c, {"provider": "local"})
    loaded = Config.load(tmp_path / "config.local.toml")
    ensure_credentials(loaded)
    assert not loaded.endpoints
    select(c, {"provider": "chatgpt", "account": "a" * 24, "model": "gpt-6-luna"})
    loaded = Config.load(tmp_path / "config.local.toml")
    with pytest.raises(ValueError, match="No API fallback"):
        ensure_credentials(loaded)
    assert loaded.endpoints[0].backend == "chatgpt"


async def test_asr_preparation_reuses_cache_and_invalidates_changed_selection(
    tmp_path, monkeypatch
):
    c = configured(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "fixture")
    calls = []

    async def load(recognizer):
        calls.append(recognizer.config.model_revision)
        c.model_dir.mkdir(exist_ok=True)
        (c.model_dir / "model.bin").write_bytes(b"synthetic cache marker, not weights")

    monkeypatch.setattr("interview_helper.asr.Recognizer.load", load)
    await prepare(c)
    await prepare(c)
    assert len(calls) == 1
    c.model_revision = "changed-selection"
    await prepare(c)
    assert len(calls) == 2
    (c.model_dir / "model.bin").unlink()
    await prepare(c)
    assert len(calls) == 3
    assert (tmp_path / ".local/asr-ready.json").stat().st_mode & 0o777 == 0o600


def test_key_helper_refuses_noninteractive_stdin(tmp_path):
    helper = tmp_path / "scripts/configure_openai.py"
    helper.parent.mkdir()
    helper.write_bytes((ROOT / "scripts/configure_openai.py").read_bytes())
    result = subprocess.run(
        [sys.executable, str(helper)], input="fixture-key\n", text=True, capture_output=True
    )
    assert result.returncode and "Interactive terminal required" in result.stderr
    assert not (tmp_path / ".local/openai-api-key").exists()
    assert "fixture-key" not in result.stdout + result.stderr


def test_installer_reuses_environment_and_preserves_private_state(tmp_path):
    # Exercise real install.sh; simulate pip/metadata only, never install network packages.
    for name in ("install.sh", "config.example.toml"):
        (tmp_path / name).write_bytes((ROOT / name).read_bytes())
    binary = tmp_path / ".venv/bin/python"
    binary.parent.mkdir(parents=True)
    binary.write_text("""#!/bin/sh
case "$*" in
  *environment_ready.py*) test -f .local/fixture-installed ;;
  *) echo "$*" >> .local/fixture-pip; touch .local/fixture-installed ;;
esac
""")
    binary.chmod(0o700)
    env = {**os.environ, "PYTHON": sys.executable}
    command = ["bash", "install.sh", "--cpu", "--if-needed"]
    subprocess.run(command, cwd=tmp_path, env=env, check=True, capture_output=True)
    c = Config.load(tmp_path / "config.local.toml")
    assert c.device == "cpu" and c.endpoints[0].parameters["service_tier"] == "ultrafast"
    sentinels = [
        "config.local.toml",
        ".local/openai-api-key",
        ".local/config.local-connection.json",
        "Transcribed/kept/transcript.txt",
        "Models/kept",
        ".venv/kept",
    ]
    for name in sentinels[1:]:
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps({"provider": "local"}) if "connection" in name else "private fixture"
        )
    before = {name: (tmp_path / name).read_bytes() for name in sentinels}
    pip_before = (tmp_path / ".local/fixture-pip").read_bytes()
    subprocess.run(command, cwd=tmp_path, env=env, check=True, capture_output=True)
    assert (tmp_path / ".local/fixture-pip").read_bytes() == pip_before
    assert all((tmp_path / name).read_bytes() == data for name, data in before.items())
    import fcntl

    with (tmp_path / ".local/runtime.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
        result = subprocess.run(command, cwd=tmp_path, env=env, capture_output=True, text=True)
        assert result.returncode and "Stop Interview Helper" in result.stderr
    assert all((tmp_path / name).read_bytes() == data for name, data in before.items())


def test_one_command_prerequisites_and_launch_preserve_existing_cpu_choice(tmp_path):
    import shutil

    (tmp_path / "scripts").mkdir()
    for name in ("start.sh", "scripts/start_prerequisites.py"):
        shutil.copy2(ROOT / name, tmp_path / name)
    (tmp_path / "config.local.toml").write_text('[asr]\ndevice = "cpu"\n')
    binaries = tmp_path / "bin"
    binaries.mkdir()
    for name in ("pactl", "parec"):
        p = binaries / name
        p.write_text("#!/bin/sh\nexit 0\n")
        p.chmod(0o700)
    for name in ("install.sh", "run.sh"):
        p = tmp_path / name
        p.write_text('#!/bin/sh\necho "' + name + ' $*" >> launch-log\n')
        p.chmod(0o700)
    env = {**os.environ, "PYTHON": sys.executable, "PATH": str(binaries) + ":" + os.environ["PATH"]}
    for _ in range(2):
        subprocess.run(
            ["./start.sh", "--no-browser"],
            cwd=tmp_path,
            env=env,
            stdin=subprocess.DEVNULL,
            check=True,
            capture_output=True,
        )
    assert (tmp_path / "launch-log").read_text().splitlines() == [
        "install.sh --cpu --if-needed",
        "run.sh prepare",
        "run.sh serve --no-browser",
    ] * 2
    assert (tmp_path / "config.local.toml").read_text() == '[asr]\ndevice = "cpu"\n'
