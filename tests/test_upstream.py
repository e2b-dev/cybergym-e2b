from pathlib import Path

from cybergym_e2b import upstream
from cybergym_e2b.config import UpstreamLock


def test_generated_workspace_keeps_upstream_body_and_adds_only_traffic_header(
    tmp_path: Path, monkeypatch
) -> None:
    lock = UpstreamLock.load()
    data = tmp_path / "data"
    task_data = data / "arvo" / "1065"
    task_data.mkdir(parents=True)
    (task_data / "repo-vul.tar.gz").write_bytes(b"not-a-real-tar-needed-for-generation")
    (task_data / "description.txt").write_text("test vulnerability", encoding="utf-8")

    monkeypatch.setattr(upstream, "data_dir", lambda _lock: data)
    monkeypatch.setattr(upstream, "sync_task_data", lambda _lock, _task_id, _difficulty: task_data)
    output = tmp_path / "workspace"
    task = upstream.generate_task_workspace(
        lock,
        "arvo:1065",
        "level1",
        "https://executor.example",
        "traffic-secret",
        "agent-1",
        output,
    )

    submit = (output / "submit.sh").read_text(encoding="utf-8")
    assert "https://executor.example/submit-vul" in submit
    assert "e2b-traffic-access-token: traffic-secret" in submit
    assert '"task_id": "arvo:1065"' in submit
    assert task.agent_id == "agent-1"
    assert (output / "repo-vul.tar.gz").exists()
    assert not (output / "repo-fix.tar.gz").exists()
    assert not (output / "patch.diff").exists()
