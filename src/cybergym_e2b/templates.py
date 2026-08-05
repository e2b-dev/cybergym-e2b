from __future__ import annotations

import json
from pathlib import Path

from e2b import Template, default_build_logger

from cybergym_e2b.config import (
    DEFAULT_MANIFEST_PATH,
    REPO_ROOT,
    TemplateManifest,
    TemplatePin,
    UpstreamLock,
)
from cybergym_e2b.registry import compressed_image_size, task_images
from cybergym_e2b.upstream import ensure_vendor_pin

GIB = 1024**3


def _pin(name: str, build_info) -> TemplatePin:
    return TemplatePin(name=name, build_id=build_info.build_id)


def _build_agent(lock: UpstreamLock) -> TemplatePin:
    name = f"cybergym-e2b-agent-{lock.agent_version.replace('.', '-')}"
    builder = (
        Template(file_context_path=REPO_ROOT)
        .from_ubuntu_image("24.04")
        .set_user("root")
        .run_cmd(
            "apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y "
            "bash build-essential ca-certificates curl file git jq python3 python3-venv "
            "ripgrep tar && rm -rf /var/lib/apt/lists/*"
        )
        .run_cmd("useradd --create-home --shell /bin/bash agent")
        .run_cmd(
            "python3 -m venv /opt/mini-swe-agent && "
            f"/opt/mini-swe-agent/bin/pip install --no-cache-dir "
            f"{lock.agent_package}=={lock.agent_version} && "
            "ln -sf /opt/mini-swe-agent/bin/mini-swe-agent /usr/local/bin/mini-swe-agent"
        )
        .run_cmd("mkdir -p /workspace && chown agent:agent /workspace")
    )
    info = Template.build(
        builder,
        name,
        cpu_count=4,
        memory_mb=8192,
        on_build_logs=default_build_logger(),
    )
    return _pin(name, info)


def _build_executor_base(lock: UpstreamLock) -> TemplatePin:
    name = f"cybergym-e2b-executor-{lock.code_commit[:12]}"
    builder = (
        Template(
            file_context_path=REPO_ROOT,
            file_ignore_patterns=[
                ".git",
                ".venv",
                ".cache",
                "vendor/cybergym/.git",
                "vendor/cybergym/examples",
            ],
        )
        .from_ubuntu_image("24.04")
        .set_user("root")
        .run_cmd(
            "apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y "
            "ca-certificates curl python3 python3-venv && rm -rf /var/lib/apt/lists/*"
        )
        .run_cmd("curl -fsSL https://get.docker.com | sh")
        .copy("vendor/cybergym/pyproject.toml", "/opt/cybergym/pyproject.toml")
        .copy("vendor/cybergym/README.md", "/opt/cybergym/README.md")
        .copy("vendor/cybergym/src", "/opt/cybergym/src")
        .run_cmd(
            "python3 -m venv /opt/cybergym-venv && "
            "/opt/cybergym-venv/bin/pip install --no-cache-dir '/opt/cybergym[server]'"
        )
        .run_cmd("docker run --rm --network none hello-world >/tmp/docker-smoke.txt")
    )
    info = Template.build(
        builder,
        name,
        cpu_count=4,
        memory_mb=8192,
        on_build_logs=default_build_logger(),
    )
    return _pin(name, info)


def _build_task(
    lock: UpstreamLock,
    task_id: str,
    executor_base: TemplatePin,
    max_compressed_image_gib: float,
) -> TemplatePin:
    images = task_images(task_id)
    compressed = compressed_image_size(images.vulnerable) + compressed_image_size(images.fixed)
    if compressed > max_compressed_image_gib * GIB:
        raise RuntimeError(
            f"{task_id} images are {compressed / GIB:.2f} GiB compressed, above the "
            f"{max_compressed_image_gib:.2f} GiB safety limit for this E2B disk"
        )
    slug = task_id.replace(":", "-")
    name = f"cybergym-e2b-{slug}-{lock.code_commit[:8]}"
    builder = (
        Template()
        .from_template(executor_base.reference)
        .set_user("root")
        .run_cmd(f"docker pull {images.vulnerable}")
        .run_cmd(f"docker pull {images.fixed}")
        .run_cmd(f"docker image inspect {images.vulnerable} {images.fixed} >/dev/null")
    )
    info = Template.build(
        builder,
        name,
        cpu_count=4,
        memory_mb=8192,
        on_build_logs=default_build_logger(),
    )
    return _pin(name, info)


def build_templates(
    lock: UpstreamLock,
    task_ids: list[str],
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
    max_compressed_image_gib: float = 8.0,
) -> TemplateManifest:
    ensure_vendor_pin(lock)
    for task_id in task_ids:
        lock.require_task(task_id)
    agent = _build_agent(lock)
    executor_base = _build_executor_base(lock)
    tasks = {
        task_id: _build_task(lock, task_id, executor_base, max_compressed_image_gib)
        for task_id in task_ids
    }
    manifest = TemplateManifest(
        code_commit=lock.code_commit,
        dataset_commit=lock.dataset_commit,
        agent=agent,
        executor_base=executor_base,
        tasks=tasks,
    )
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "upstream": {
                    "code_commit": manifest.code_commit,
                    "dataset_commit": manifest.dataset_commit,
                },
                "agent": manifest.agent.to_dict(),
                "executor_base": manifest.executor_base.to_dict(),
                "tasks": {key: value.to_dict() for key, value in manifest.tasks.items()},
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return manifest
