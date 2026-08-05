import json
from pathlib import Path

from cybergym_e2b.docker_baseline import compare_results


def test_compare_uses_crash_class_not_log_bytes(tmp_path: Path) -> None:
    baseline = {
        "task_id": "arvo:1065",
        "verification": {"vulnerable_class": "crash", "fixed_class": "clean"},
        "score": {"success": True},
        "timing": {"total_sec": 10},
    }
    candidate = {
        "task_id": "arvo:1065",
        "verification": {"vulnerable_class": "crash", "fixed_class": "clean"},
        "score": {"success": True},
        "timing": {"total_sec": 5},
    }
    baseline_path = tmp_path / "baseline.json"
    candidate_path = tmp_path / "candidate.json"
    baseline_path.write_text(json.dumps(baseline), encoding="utf-8")
    candidate_path.write_text(json.dumps(candidate), encoding="utf-8")
    comparison = compare_results(baseline_path, candidate_path)
    assert comparison["correctness_match"]
    assert comparison["baseline_total_sec"] == 10
    assert comparison["candidate_total_sec"] == 5
