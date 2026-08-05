from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from dotenv import load_dotenv

from cybergym_e2b.config import (
    DEFAULT_LOCK_PATH,
    DEFAULT_MANIFEST_PATH,
    MAX_SANDBOX_CONCURRENCY,
    TemplateManifest,
    UpstreamLock,
)
from cybergym_e2b.docker_baseline import compare_results, run_docker_baseline
from cybergym_e2b.registry import compressed_image_size, task_images
from cybergym_e2b.runtime import TrialRunner
from cybergym_e2b.templates import build_templates
from cybergym_e2b.upstream import ensure_vendor_pin, sync_task_data


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cybergym-e2b")
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK_PATH)
    subparsers = parser.add_subparsers(dest="command", required=True)

    check = subparsers.add_parser("check", help="validate pins, credentials, and task image sizes")
    check.add_argument("--task", action="append")

    sync = subparsers.add_parser("sync", help="download only the requested pinned task data")
    sync.add_argument("--task", action="append", required=True)
    sync.add_argument("--difficulty", default="level1")

    build = subparsers.add_parser("build", help="build immutable E2B templates")
    build.add_argument("--task", action="append")
    build.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
    build.add_argument("--max-compressed-image-gib", type=float, default=8.0)

    run = subparsers.add_parser("run", help="run Fireworks agents on E2B")
    run.add_argument("--task", action="append")
    run.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
    run.add_argument("--difficulty", default="level1")
    run.add_argument("--model")
    run.add_argument("--cost-limit", type=float, default=0.03)
    run.add_argument("--step-limit", type=int, default=30)
    run.add_argument("--timeout", type=int, default=1800)
    run.add_argument("--workers", type=int)
    run.add_argument("--max-sandbox-concurrency", type=int, default=MAX_SANDBOX_CONCURRENCY)
    run.add_argument("--retain", action="store_true")
    run.add_argument("--artifacts-dir", type=Path, default=Path("artifacts"))

    docker = subparsers.add_parser(
        "docker-baseline", help="run the pinned reference PoC in local Docker"
    )
    docker.add_argument("--task", required=True)
    docker.add_argument("--output", type=Path)

    e2b_baseline = subparsers.add_parser(
        "e2b-baseline", help="run the pinned reference PoC through CyberGym on E2B"
    )
    e2b_baseline.add_argument("--task", required=True)
    e2b_baseline.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
    e2b_baseline.add_argument("--output", type=Path)
    e2b_baseline.add_argument("--retain", action="store_true")

    compare = subparsers.add_parser("compare", help="compare E2B and Docker crash classes")
    compare.add_argument("baseline", type=Path)
    compare.add_argument("candidate", type=Path)
    return parser


def _load_environment(path: Path | None) -> None:
    if path:
        load_dotenv(path, override=False)


def _json_line(value) -> None:
    print(json.dumps(value, default=str, sort_keys=True), flush=True)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    _load_environment(args.env_file)
    lock = UpstreamLock.load(args.lock)

    if args.command == "check":
        ensure_vendor_pin(lock)
        tasks = args.task or list(lock.sample)
        report = {
            "vendor_pin": lock.code_commit,
            "e2b_key": bool(os.environ.get("E2B_API_KEY")),
            "fireworks_key": bool(
                os.environ.get("FIREWORKS_AI_API_KEY") or os.environ.get("FIREWORKS_API_KEY")
            ),
            "tasks": {},
        }
        for task_id in tasks:
            lock.require_task(task_id)
            images = task_images(task_id)
            report["tasks"][task_id] = {
                "vulnerable_image": images.vulnerable,
                "fixed_image": images.fixed,
                "compressed_image_gib": round(
                    (compressed_image_size(images.vulnerable) + compressed_image_size(images.fixed))
                    / 1024**3,
                    3,
                ),
            }
        _json_line(report)
        return 0

    if args.command == "sync":
        for task_id in args.task:
            path = sync_task_data(lock, task_id, args.difficulty)
            _json_line({"task_id": task_id, "data_dir": str(path)})
        return 0

    if args.command == "build":
        tasks = args.task or list(lock.sample)
        manifest = build_templates(
            lock,
            tasks,
            args.manifest,
            max_compressed_image_gib=args.max_compressed_image_gib,
        )
        _json_line({"manifest": str(args.manifest), "tasks": sorted(manifest.tasks)})
        return 0

    if args.command == "run":
        tasks = args.task or list(lock.sample)
        runner = TrialRunner(
            lock,
            TemplateManifest.load(args.manifest),
            max_sandbox_concurrency=args.max_sandbox_concurrency,
            artifacts_dir=args.artifacts_dir,
        )
        results = runner.run_batch(
            tasks,
            workers=args.workers,
            difficulty=args.difficulty,
            model=args.model,
            cost_limit=args.cost_limit,
            step_limit=args.step_limit,
            timeout=args.timeout,
            retain=args.retain,
        )
        for result in results:
            _json_line(result)
        return 1 if any(result.get("error") for result in results) else 0

    if args.command == "docker-baseline":
        result = run_docker_baseline(lock, args.task)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        _json_line(result)
        return 0

    if args.command == "e2b-baseline":
        runner = TrialRunner(lock, TemplateManifest.load(args.manifest))
        result = runner.run_reference(args.task, retain=args.retain)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        _json_line(result)
        return 1 if result.get("error") else 0

    if args.command == "compare":
        result = compare_results(args.baseline, args.candidate)
        _json_line(result)
        return 0 if result["correctness_match"] else 1

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
