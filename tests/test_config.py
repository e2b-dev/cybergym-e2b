import json
from pathlib import Path

import pytest

from cybergym_e2b.config import (
    MAX_SANDBOX_CONCURRENCY,
    TemplateManifest,
    TemplatePin,
    UpstreamLock,
    validate_concurrency,
)


def test_lock_loads_current_schema() -> None:
    lock = UpstreamLock.load()
    assert len(lock.code_commit) == 40
    assert len(lock.dataset_commit) == 40
    assert set(lock.sample) <= set(lock.tasks)


def test_template_pin_is_immutable() -> None:
    assert (
        TemplatePin("example", "cf7acdff-8394-46bd-bde7-3682524a48f7").reference
        == "example:cf7acdff-8394-46bd-bde7-3682524a48f7"
    )
    with pytest.raises(ValueError, match="invalid immutable"):
        _ = TemplatePin("example", "default").reference


def test_manifest_rejects_upstream_drift(tmp_path: Path) -> None:
    lock = UpstreamLock.load()
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "upstream": {"code_commit": "0" * 40, "dataset_commit": lock.dataset_commit},
                "agent": {"name": "agent", "build_id": "abc123"},
                "executor_base": {"name": "base", "build_id": "def456"},
                "tasks": {},
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="CyberGym commit"):
        TemplateManifest.load(path).validate(lock)


@pytest.mark.parametrize("value", [0, 1, MAX_SANDBOX_CONCURRENCY + 1])
def test_concurrency_cap(value: int) -> None:
    with pytest.raises(ValueError, match="concurrency"):
        validate_concurrency(value)
