from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LOCK_PATH = REPO_ROOT / "upstream.lock.json"
DEFAULT_MANIFEST_PATH = REPO_ROOT / "template-manifest.json"
MAX_SANDBOX_CONCURRENCY = 180
CRASH_SENTINELS = frozenset({0, 300})
_BUILD_ID = re.compile(r"^[a-z0-9][a-z0-9-]{7,}$")


@dataclass(frozen=True)
class UpstreamLock:
    code_repository: str
    code_commit: str
    dataset_repository: str
    dataset_commit: str
    agent_package: str
    agent_version: str
    default_model: str
    tasks: dict[str, dict[str, Any]]
    sample: tuple[str, ...]

    @classmethod
    def load(cls, path: Path = DEFAULT_LOCK_PATH) -> UpstreamLock:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if raw.get("schema_version") != 1:
            raise ValueError("unsupported upstream lock schema")
        return cls(
            code_repository=raw["cybergym"]["repository"],
            code_commit=raw["cybergym"]["commit"],
            dataset_repository=raw["dataset"]["repository"],
            dataset_commit=raw["dataset"]["commit"],
            agent_package=raw["agent"]["package"],
            agent_version=raw["agent"]["version"],
            default_model=raw["agent"]["default_model"],
            tasks=raw["tasks"],
            sample=tuple(raw["sample"]),
        )

    def require_task(self, task_id: str) -> None:
        if task_id not in self.tasks:
            raise ValueError(f"task {task_id!r} is not present in upstream.lock.json")


@dataclass(frozen=True)
class TemplatePin:
    name: str
    build_id: str

    @property
    def reference(self) -> str:
        if (
            not self.name
            or self.build_id in {"default", "latest"}
            or not _BUILD_ID.fullmatch(self.build_id)
        ):
            raise ValueError(f"invalid immutable template pin: {self.name}:{self.build_id}")
        return f"{self.name}:{self.build_id}"

    @classmethod
    def from_dict(cls, raw: dict[str, str]) -> TemplatePin:
        return cls(name=raw["name"], build_id=raw["build_id"])

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "build_id": self.build_id}


@dataclass(frozen=True)
class TemplateManifest:
    code_commit: str
    dataset_commit: str
    agent: TemplatePin
    executor_base: TemplatePin
    tasks: dict[str, TemplatePin]

    @classmethod
    def load(cls, path: Path = DEFAULT_MANIFEST_PATH) -> TemplateManifest:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if raw.get("schema_version") != 1:
            raise ValueError("unsupported template manifest schema")
        return cls(
            code_commit=raw["upstream"]["code_commit"],
            dataset_commit=raw["upstream"]["dataset_commit"],
            agent=TemplatePin.from_dict(raw["agent"]),
            executor_base=TemplatePin.from_dict(raw["executor_base"]),
            tasks={key: TemplatePin.from_dict(value) for key, value in raw["tasks"].items()},
        )

    def validate(self, lock: UpstreamLock) -> None:
        if self.code_commit != lock.code_commit:
            raise ValueError("manifest CyberGym commit does not match upstream.lock.json")
        if self.dataset_commit != lock.dataset_commit:
            raise ValueError("manifest dataset commit does not match upstream.lock.json")
        _ = self.agent.reference
        _ = self.executor_base.reference
        for task_id, pin in self.tasks.items():
            lock.require_task(task_id)
            _ = pin.reference


def validate_concurrency(value: int) -> int:
    if not 2 <= value <= MAX_SANDBOX_CONCURRENCY:
        raise ValueError(f"max sandbox concurrency must be between 2 and {MAX_SANDBOX_CONCURRENCY}")
    return value
