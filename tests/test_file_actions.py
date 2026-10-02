from pathlib import Path

from core.file_actions import build_delete_plan, permanently_delete_paths, recycle_paths


def test_recycle_paths_uses_recycle_sender_without_removing_file(tmp_path: Path):
    target = tmp_path / "old-installer.exe"
    target.write_text("fixture", encoding="utf-8")
    sent: list[str] = []

    manifest = recycle_paths([target], sender=sent.append)

    assert manifest["items"][0]["status"] == "RECYCLED"
    assert sent == [str(target.resolve())]
    assert target.exists()


def test_permanent_delete_removes_disposable_file(tmp_path: Path):
    target = tmp_path / "delete-me.tmp"
    target.write_text("fixture", encoding="utf-8")

    manifest = permanently_delete_paths([target])

    assert manifest["items"][0]["status"] == "DELETED"
    assert not target.exists()


def test_delete_plan_deduplicates_parent_and_child(tmp_path: Path):
    parent = tmp_path / "folder"
    child = parent / "child.txt"
    child.parent.mkdir()
    child.write_text("fixture", encoding="utf-8")

    plan = build_delete_plan([parent, child])

    assert plan.targets == [parent.resolve()]


def test_delete_plan_marks_git_project_as_high_risk(tmp_path: Path):
    project = tmp_path / "Project"
    (project / ".git").mkdir(parents=True)
    (project / "package.json").write_text("{}", encoding="utf-8")

    plan = build_delete_plan([project])

    assert plan.high_risk
    assert any("Git" in reason or "project" in reason for reason in plan.risk_reasons)
