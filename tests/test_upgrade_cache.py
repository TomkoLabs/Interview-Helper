"""Real stale pyc/launcher regressions; no ASR, pip install or model requests."""

import fcntl
import json
import os
from pathlib import Path
import py_compile
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).parents[1]


def run(root, *args, check=True):
    return subprocess.run(
        args,
        cwd=root,
        env={
            **os.environ,
            "PYTHON": sys.executable,
            "PYTHONPATH": str(root / "src"),
            "PATH": str(root / "bin") + ":" + os.environ["PATH"],
        },
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=check,
    )


def source(path, text):
    path.write_text(text)
    os.utime(path, (1700000000, 1700000000))


def stale_installation(root):
    for name in (
        "start.sh",
        "install.sh",
        "run.sh",
        "scripts/refresh_bytecode.py",
        "scripts/start_prerequisites.py",
        "config.example.toml",
    ):
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, target)
    package = root / "src/interview_helper"
    package.mkdir(parents=True)
    init = package / "__init__.py"
    module = package / "example.py"
    source(init, '__version__ = "0.1.15"\n')
    source(module, 'VALUE = "before"\n')
    (package / "__main__.py").write_text(
        "import json, sys\nfrom . import __version__\nfrom .example import VALUE\n"
        'print(json.dumps({"version": __version__, "value": VALUE, "args": sys.argv[1:]}))\n'
    )
    (root / ".local").mkdir()
    # Seed the old content marker before creating the old timestamp bytecode.
    run(root, sys.executable, "scripts/refresh_bytecode.py")
    for p in (init, module):
        py_compile.compile(
            str(p), doraise=True, invalidation_mode=py_compile.PycInvalidationMode.TIMESTAMP
        )
    source(init, '__version__ = "0.1.16"\n')  # Same byte count and mtime as .15.
    source(module, 'VALUE = "after!"\n')
    assert json.loads(run(root, sys.executable, "-m", "interview_helper").stdout) == {
        "version": "0.1.15",
        "value": "before",
        "args": [],
    }
    binary = root / ".venv/bin/python"
    binary.parent.mkdir(parents=True)
    # Execute Python for real. Only metadata/pip are simulated to prevent installs;
    # the simulated installer deliberately imports IH to enforce ordering.
    binary.write_text("""#!/bin/sh
case "$*" in
  *environment_ready.py*) test -f .local/installed ;;
  "-m pip "*)
    "$PYTHON" -c 'import interview_helper; assert interview_helper.__version__ == "0.1.16"' || exit 1
    echo install >> .local/pip-calls
    touch .local/installed ;;
  *) exec "$PYTHON" "$@" ;;
esac
""")
    binary.chmod(0o700)
    (root / "bin").mkdir()
    for name in ("pactl", "parec"):
        p = root / "bin" / name
        p.write_text("#!/bin/sh\nexit 0\n")
        p.chmod(0o700)
    (root / "config.local.toml").write_text('[asr]\ndevice = "cpu"\n')
    for name in (
        ".local/openai-api-key",
        ".local/config.local-connection.json",
        "Models/kept",
        "Transcribed/kept/transcript.txt",
        ".venv/lib/dependency.pyc",
    ):
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("private fixture sentinel")
    return {
        str(p.relative_to(root)): p.read_bytes()
        for p in root.rglob("*")
        if p.is_file()
        and (
            p.name == "config.local.toml"
            or p.name == "openai-api-key"
            or p.name == "config.local-connection.json"
            or p.is_relative_to(root / "Models")
            or p.is_relative_to(root / "Transcribed")
            or p.is_relative_to(root / ".venv")
        )
    }


@pytest.mark.parametrize("entry", ["start", "install", "run", "archive-update"])
def test_same_timestamp_size_upgrade_imports_new_source_before_application_code(tmp_path, entry):
    protected = stale_installation(tmp_path)
    if entry == "archive-update":
        command = [
            "flock",
            "-n",
            ".local/runtime.lock",
            ".venv/bin/python",
            "scripts/refresh_bytecode.py",
        ]
    else:
        command = {
            "start": ["./start.sh", "--no-browser"],
            "install": ["./install.sh", "--cpu", "--if-needed"],
            "run": ["./run.sh", "probe"],
        }[entry]
    result = run(tmp_path, *command)
    if entry in {"start", "run"}:
        calls = [json.loads(line) for line in result.stdout.splitlines() if line.startswith("{")]
        assert len(calls) == (2 if entry == "start" else 1)
        assert all(c["version"] == "0.1.16" and c["value"] == "after!" for c in calls)
    imported = json.loads(run(tmp_path, sys.executable, "-m", "interview_helper").stdout)
    assert imported["version"] == "0.1.16" and imported["value"] == "after!"
    marker = tmp_path / ".local/application-source.sha256"
    unchanged = [marker, *(tmp_path / "src/interview_helper").rglob("*.pyc")]
    if (tmp_path / ".local/pip-calls").exists():
        unchanged.append(tmp_path / ".local/pip-calls")
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in unchanged}
    run(tmp_path, *command)
    assert all((p.read_bytes(), p.stat().st_mtime_ns) == value for p, value in before.items())
    assert all((tmp_path / name).read_bytes() == data for name, data in protected.items())


@pytest.mark.parametrize("entry", ["run.sh", "install.sh"])
def test_active_runtime_blocks_source_cache_invalidation(tmp_path, entry):
    stale_installation(tmp_path)
    before = {p: p.read_bytes() for p in (tmp_path / "src").rglob("*.pyc")}
    with (tmp_path / ".local/runtime.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
        result = run(tmp_path, "./" + entry, check=False)
    assert result.returncode and "Stop Interview Helper" in result.stderr
    assert all(p.read_bytes() == data for p, data in before.items())
