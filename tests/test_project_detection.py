from pathlib import Path

from core.project_detector import is_project_root, project_type
from core.scanner import ScanOptions, Scanner


def test_detects_next_project(tmp_path: Path):
    project = tmp_path / "app"
    project.mkdir()
    (project / "package.json").write_text("{}")
    (project / "next.config.js").write_text("module.exports = {}")

    assert is_project_root(project)
    assert project_type(project) == "Next.js"


def test_dependency_packages_are_not_detected_as_projects(tmp_path: Path):
    library = tmp_path / "Projects"
    project = library / "HIT-ASA"
    (project / ".git").mkdir(parents=True)
    (project / "src").mkdir()
    (project / "package.json").write_text("{}")
    for package in ["uuid", "react", "next"]:
        package_dir = project / "node_modules" / package
        package_dir.mkdir(parents=True)
        (package_dir / "package.json").write_text("{}")

    result = Scanner(ScanOptions(include_duplicates=False)).scan(library, "Projects")

    assert [item.name for item in result.projects] == ["HIT-ASA"]


def test_scan_does_not_attach_items_to_projects_above_scan_root(tmp_path: Path):
    parent_project = tmp_path / "Documents"
    (parent_project / ".git").mkdir(parents=True)
    downloads = parent_project / "Downloads"
    downloads.mkdir()
    (downloads / "setup.exe").write_text("fixture")

    result = Scanner(ScanOptions(include_duplicates=False, large_file_mb=1)).scan(downloads, "Downloads")

    assert result.findings
    assert all(item.project_root is None for item in result.findings)
    assert all(not item.is_inside_git_repository for item in result.findings)
