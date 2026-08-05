from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

from cybergym_e2b.config import UpstreamLock
from cybergym_e2b.registry import task_images
from cybergym_e2b.scoring import crash_class, score
from cybergym_e2b.upstream import VENDOR_SRC, ensure_vendor_pin


def _load_runner():
    source = str(VENDOR_SRC)
    if source not in sys.path:
        sys.path.insert(0, source)
    from cybergym.server.server_utils import run_container

    return run_container


def _reference_poc(task_id: str, destination: Path) -> None:
    image = task_images(task_id).vulnerable
    subprocess.run(["docker", "pull", "--platform", "linux/amd64", image], check=True)
    container = subprocess.run(
        ["docker", "create", "--platform", "linux/amd64", image],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    try:
        subprocess.run(["docker", "cp", f"{container}:/tmp/poc", str(destination)], check=True)
    finally:
        subprocess.run(["docker", "rm", "-f", container], check=False, capture_output=True)


def run_docker_baseline(lock: UpstreamLock, task_id: str) -> dict[str, Any]:
    ensure_vendor_pin(lock)
    lock.require_task(task_id)
    run_container = _load_runner()
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="cybergym-docker-") as tmp:
        poc_path = Path(tmp) / "reference.poc"
        _reference_poc(task_id, poc_path)
        images = task_images(task_id)
        subprocess.run(["docker", "pull", "--platform", "linux/amd64", images.fixed], check=True)
        mark = time.perf_counter()
        vulnerable_code, _ = run_container(task_id, poc_path, "vul")
        vulnerable_sec = time.perf_counter() - mark
        mark = time.perf_counter()
        fixed_code, _ = run_container(task_id, poc_path, "fix")
        fixed_sec = time.perf_counter() - mark
        return {
            "schema_version": "1",
            "runtime": "docker",
            "runtime_details": {
                "host_machine": platform.machine(),
                "docker_server_version": subprocess.run(
                    ["docker", "version", "--format", "{{.Server.Version}}"],
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout.strip(),
            },
            "run_id": uuid.uuid4().hex,
            "task_id": task_id,
            "upstream": {"code_commit": lock.code_commit},
            "final_poc_sha256": hashlib.sha256(poc_path.read_bytes()).hexdigest(),
            "verification": {
                "vulnerable_exit_code": int(vulnerable_code),
                "fixed_exit_code": int(fixed_code),
                "vulnerable_class": crash_class(int(vulnerable_code)),
                "fixed_class": crash_class(int(fixed_code)),
            },
            "score": {"success": score(int(vulnerable_code), int(fixed_code))},
            "timing": {
                "vulnerable_sec": vulnerable_sec,
                "fixed_sec": fixed_sec,
                "total_sec": time.perf_counter() - started,
            },
        }


def compare_results(baseline_path: Path, candidate_path: Path) -> dict[str, Any]:
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    if baseline["task_id"] != candidate["task_id"]:
        raise ValueError("cannot compare results from different tasks")
    fields = ("vulnerable_class", "fixed_class")
    matches = {
        field: baseline["verification"].get(field) == candidate["verification"].get(field)
        for field in fields
    }
    return {
        "task_id": baseline["task_id"],
        "crash_class_matches": matches,
        "correctness_match": all(matches.values())
        and baseline["score"]["success"] == candidate["score"]["success"],
        "baseline_total_sec": baseline.get("timing", {}).get("total_sec"),
        "candidate_total_sec": candidate.get("timing", {}).get("total_sec"),
    }
