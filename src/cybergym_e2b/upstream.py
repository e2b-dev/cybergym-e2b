from __future__ import annotations

import os
import subprocess
import sys
import urllib.request
from pathlib import Path

from cybergym_e2b.config import REPO_ROOT, UpstreamLock

VENDOR_ROOT = REPO_ROOT / "vendor" / "cybergym"
VENDOR_SRC = VENDOR_ROOT / "src"
DATA_CACHE = REPO_ROOT / ".cache" / "dataset"


def ensure_vendor_pin(lock: UpstreamLock) -> None:
    if not (VENDOR_ROOT / ".git").exists():
        raise RuntimeError("vendor/cybergym is not initialized; run git submodule update --init")
    actual = subprocess.run(
        ["git", "-C", str(VENDOR_ROOT), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if actual != lock.code_commit:
        raise RuntimeError(
            f"vendored CyberGym is {actual}; upstream.lock.json requires {lock.code_commit}"
        )


def data_dir(lock: UpstreamLock) -> Path:
    return DATA_CACHE / lock.dataset_commit / "data"


def _difficulty_files(difficulty: str) -> tuple[str, ...]:
    files = {
        "level0": ("repo-vul.tar.gz",),
        "level1": ("repo-vul.tar.gz", "description.txt"),
        "level2": ("repo-vul.tar.gz", "description.txt", "error.txt"),
        "level3": (
            "repo-vul.tar.gz",
            "repo-fix.tar.gz",
            "description.txt",
            "error.txt",
            "patch.diff",
        ),
    }
    try:
        return files[difficulty]
    except KeyError as exc:
        raise ValueError(f"unsupported difficulty: {difficulty}") from exc


def sync_task_data(lock: UpstreamLock, task_id: str, difficulty: str = "level1") -> Path:
    lock.require_task(task_id)
    family, identifier = task_id.split(":", 1)
    task_dir = data_dir(lock) / family / identifier
    task_dir.mkdir(parents=True, exist_ok=True)
    for filename in _difficulty_files(difficulty):
        destination = task_dir / filename
        if destination.exists() and destination.stat().st_size:
            continue
        url = (
            f"https://huggingface.co/datasets/{lock.dataset_repository}/resolve/"
            f"{lock.dataset_commit}/data/{family}/{identifier}/{filename}?download=true"
        )
        temporary = destination.with_suffix(destination.suffix + ".part")
        try:
            with urllib.request.urlopen(url, timeout=300) as response, temporary.open("wb") as out:
                while chunk := response.read(1024 * 1024):
                    out.write(chunk)
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
    return task_dir


def _load_upstream_task_api():
    source = str(VENDOR_SRC)
    if source not in sys.path:
        sys.path.insert(0, source)
    from cybergym.task.gen_task import generate_task
    from cybergym.task.types import TaskConfig, TaskDifficulty

    return generate_task, TaskConfig, TaskDifficulty


def generate_task_workspace(
    lock: UpstreamLock,
    task_id: str,
    difficulty: str,
    server_url: str,
    traffic_token: str,
    agent_id: str,
    output_dir: Path,
):
    ensure_vendor_pin(lock)
    sync_task_data(lock, task_id, difficulty)
    generate_task, task_config, task_difficulty = _load_upstream_task_api()
    output_dir.mkdir(parents=True, exist_ok=True)
    task = generate_task(
        task_config(
            task_id=task_id,
            agent_id=agent_id,
            out_dir=output_dir,
            data_dir=data_dir(lock),
            server=server_url,
            difficulty=task_difficulty(difficulty),
        )
    )
    submit_path = output_dir / "submit.sh"
    submit = submit_path.read_text(encoding="utf-8")
    needle = f"curl -X POST {server_url}/submit-vul \\\n"
    replacement = needle + f"  -H 'e2b-traffic-access-token: {traffic_token}' \\\n"
    if submit.count(needle) != 1:
        raise RuntimeError("upstream submit.template changed; update the compatibility adapter")
    submit_path.write_text(submit.replace(needle, replacement), encoding="utf-8")
    submit_path.chmod(0o755)
    return task
