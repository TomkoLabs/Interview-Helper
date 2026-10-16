"""Stopped-app, copy/verify/switch migration. Originals are never removed."""

from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import os
from pathlib import Path
import re
import shutil
import tempfile
import tomllib

from .storage import SESSION_ID, SessionStore


@contextmanager
def stopped(root):
    private = root / ".local"
    private.mkdir(mode=0o700, exist_ok=True)
    with (private / "runtime.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("Stop IH recording and its launcher before migrating") from None
        yield


def files(path):
    result = {}
    for p in path.rglob("*"):
        if p.is_symlink() or not (p.is_dir() or p.is_file()):
            raise ValueError("Migration refuses symlinks or special files")
        if p.is_file():
            result[str(p.relative_to(path))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return result


def migrate(config_path):
    config_path = config_path.expanduser().absolute()
    if config_path.is_symlink():
        raise ValueError("Migration refuses a symlinked configuration")
    root = config_path.parent
    with stopped(root):
        original = config_path.read_bytes()
        raw = tomllib.loads(original.decode())
        configured = (root / raw.get("data_dir", ".local/sessions")).resolve()
        source, target = root / ".local/sessions", root / "Transcribed"
        if source.is_symlink() or target.is_symlink():
            raise ValueError("Migration refuses symlinked session roots")
        if configured not in {source.resolve(), target.resolve()}:
            return {"status": "custom data_dir preserved", "data_dir": str(configured)}
        target.mkdir(mode=0o700, exist_ok=True)
        os.chmod(target, 0o700)
        plans = []
        for src in sorted(source.iterdir()) if source.exists() else []:
            if not SESSION_ID.fullmatch(src.name):
                raise ValueError("Unexpected legacy entry; inspect it manually before migration")
            if src.is_symlink() or not src.is_dir():
                raise ValueError("Invalid legacy session directory")
            if any(
                not (src / name).is_file()
                for name in ("metadata.json", "transcript.jsonl", "hints.jsonl")
            ):
                raise ValueError("Missing authoritative session file; inspect legacy session")
            before = files(src)
            data = SessionStore.inspect(source, src.name)
            # Preserve the old readable bytes alongside the clean derived view.
            expected = dict(before)
            clean = data["readable"]
            if data["partial_tail"]:
                clean += "\n[RECOVERY] Incomplete final journal record excluded.\n"
            if "transcript.txt" in before:
                prior = "transcript.pre-0.1.8.txt"
                if prior in before and before[prior] != before["transcript.txt"]:
                    raise ValueError("Legacy readable backup collision")
                expected[prior] = before["transcript.txt"]
            expected["transcript.txt"] = hashlib.sha256(clean.encode()).hexdigest()
            dst = target / src.name
            if dst.exists() or dst.is_symlink():
                if dst.is_symlink() or not dst.is_dir() or files(dst) != expected:
                    raise ValueError(f"Destination conflict: {src.name}; nothing overwritten")
            plans.append((src, dst, before, expected, clean))
        # Preflight all conflicts before copying anything or switching config.
        for src, dst, before, expected, clean in plans:
            if dst.exists():
                continue
            stage = Path(tempfile.mkdtemp(prefix=".migration-", dir=target))
            try:
                shutil.copytree(src, stage, dirs_exist_ok=True)
                if files(stage) != before or files(src) != before:
                    raise ValueError("Session changed during copy; configuration unchanged")
                if (stage / "transcript.txt").exists():
                    shutil.copyfile(stage / "transcript.txt", stage / "transcript.pre-0.1.8.txt")
                (stage / "transcript.txt").write_text(clean)
                for p in [stage, *stage.rglob("*")]:
                    os.chmod(p, 0o700 if p.is_dir() else 0o600)
                    if p.is_file():
                        with p.open("rb") as f:
                            os.fsync(f.fileno())
                assert files(stage) == expected
                stage.rename(dst)
            finally:
                if stage.exists():
                    shutil.rmtree(stage)
        for src, dst, before, expected, _ in plans:
            if files(src) != before or files(dst) != expected:
                raise ValueError("Verification failed; configuration unchanged")
            for p in [dst, *dst.rglob("*")]:
                os.chmod(p, 0o700 if p.is_dir() else 0o600)
        sync_directory(target)
        backup = None
        if configured != target.resolve():
            text = original.decode()
            head, sep, tail = text.partition("\n[")
            if re.search(r"^\s*data_dir\s*=", head, re.M):
                head = re.sub(
                    r"^\s*data_dir\s*=.*$", 'data_dir = "Transcribed"', head, count=1, flags=re.M
                )
            else:
                head = 'data_dir = "Transcribed"\n' + head
            updated = (head + sep + tail).encode()
            parsed = tomllib.loads(updated.decode())
            assert parsed == {**raw, "data_dir": "Transcribed"}
            if config_path.read_bytes() != original:
                raise ValueError("Configuration changed during migration")
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            backup = root / ".local" / f"{config_path.name}.before-transcribed-{stamp}"
            with backup.open("xb") as f:
                os.chmod(backup, 0o600)
                f.write(original)
                f.flush()
                os.fsync(f.fileno())
            temporary = config_path.with_name(config_path.name + ".migration-tmp")
            with temporary.open("xb") as f:
                os.chmod(temporary, 0o600)
                f.write(updated)
                f.flush()
                os.fsync(f.fileno())
            temporary.replace(config_path)
            sync_directory(root)
        return {
            "status": "verified",
            "sessions": len(plans),
            "data_dir": str(target),
            "config_backup": str(backup) if backup else None,
            "originals": "retained",
        }


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
