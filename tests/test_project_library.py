import json
import os
import time
from pathlib import Path

import pytest

from core.compression import ArchiveFormat, BuiltinZipCompressionService, find_7zip_executable
from core.project_library import (
    ProjectState,
    archive_recommendations,
    analyze_project,
    analyze_and_cache_project,
    archive_project,
    archived_project_records,
    discover_project_library,
    load_project_cache,
    project_record_from_cache,
    quick_discover_project_roots,
    restore_project,
    set_project_state,
    verify_archive,
    verify_restored_project,
)


def write_bytes(path: Path, size: int, fill: bytes = b"x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(fill * size)


def make_project(root: Path, name: str = "HIT-ASA") -> Path:
    project = root / name
    (project / ".git").mkdir(parents=True)
    write_bytes(project / "package.json", 2, b"{}")
    write_bytes(project / "src" / "app.ts", 10, b"a")
    write_bytes(project / "node_modules" / "react" / "package.json", 20, b"r")
    write_bytes(project / ".next" / "cache.bin", 30, b"c")
    write_bytes(project / "assets" / "hero.png", 40, b"i")
    write_bytes(project / "notes.bin", 50, b"o")
    return project


def test_project_library_discovers_roots_without_dependency_false_positives(tmp_path: Path):
    library = tmp_path / "Projects"
    project = make_project(library)
    nested_package = project / "node_modules" / "react"

    records = discover_project_library(library, tmp_path / "data")

    assert [record.name for record in records] == ["HIT-ASA"]
    assert records[0].path == str(project)
    assert str(nested_package) not in [record.path for record in records]


def test_project_breakdown_accounts_each_byte_once(tmp_path: Path):
    project = make_project(tmp_path)

    breakdown, _modified = analyze_project(project)

    assert breakdown.source_bytes == 14
    assert breakdown.dependencies_bytes == 20
    assert breakdown.caches_bytes == 30
    assert breakdown.assets_bytes == 40
    assert breakdown.other_bytes == 50
    assert breakdown.total_bytes == 154
    assert breakdown.regenerable_bytes == 50


def test_project_state_persists_across_discovery(tmp_path: Path):
    library = tmp_path / "Projects"
    project = make_project(library)
    data = tmp_path / "data"

    set_project_state(data, project, ProjectState.NEVER_ARCHIVE)
    records = discover_project_library(library, data)

    assert records[0].state == ProjectState.NEVER_ARCHIVE


def test_archive_excludes_regenerable_data_verifies_and_restores_hashes(tmp_path: Path):
    library = tmp_path / "Projects"
    project = make_project(library, "Old Portfolio")
    data = tmp_path / "data"
    archives = tmp_path / "archives"

    result = archive_project(project, archives, data)

    assert result.verified
    assert result.excluded_bytes == 50
    assert verify_archive(Path(result.archive_path), Path(result.manifest_path))

    restore_root = tmp_path / "restored"
    restored = restore_project(Path(result.manifest_path), restore_root)

    restored_path = Path(restored.restored_to or "")
    assert verify_restored_project(restored_path, Path(result.manifest_path))
    assert (restored_path / "src" / "app.ts").read_bytes() == (project / "src" / "app.ts").read_bytes()
    assert not (restored_path / "node_modules").exists()
    assert not (restored_path / ".next").exists()


def test_archive_manifest_records_engine_format_and_verified_state(tmp_path: Path):
    project = make_project(tmp_path / "Projects", "Manifested")
    result = archive_project(
        project,
        tmp_path / "archives",
        tmp_path / "data",
        service=BuiltinZipCompressionService(),
    )

    manifest = json.loads(Path(result.manifest_path).read_text(encoding="utf-8"))

    assert manifest["schema"] == "jena.project-archive.v2"
    assert manifest["compression"]["engine"] == "python-zip"
    assert manifest["compression"]["format"] == "zip"
    assert manifest["verification"]["integrity_tested"] is True
    assert manifest["verification"]["hashes_verified"] is True
    assert result.engine == "python-zip"
    assert result.archive_format == "zip"


@pytest.mark.skipif(os.name != "nt" or find_7zip_executable() is None, reason="7-Zip is not available")
def test_project_archive_can_use_7z_and_restore_verified_contents(tmp_path: Path):
    project = make_project(tmp_path / "Projects", "Compact Source")
    result = archive_project(
        project,
        tmp_path / "archives",
        tmp_path / "data",
        archive_format=ArchiveFormat.SEVEN_ZIP,
    )

    assert Path(result.archive_path).suffix == ".7z"
    assert result.verified
    restored = restore_project(Path(result.manifest_path), tmp_path / "restore")
    restored_path = Path(restored.restored_to or "")
    assert verify_restored_project(restored_path, Path(result.manifest_path))
    assert (restored_path / "src" / "app.ts").read_bytes() == (project / "src" / "app.ts").read_bytes()


@pytest.mark.skipif(os.name != "nt" or find_7zip_executable() is None, reason="7-Zip is not available")
def test_zip_and_7z_archives_use_distinct_manifest_paths(tmp_path: Path):
    project = make_project(tmp_path / "Projects", "Two Formats")

    zip_result = archive_project(project, tmp_path / "archives", tmp_path / "data", archive_format=ArchiveFormat.ZIP)
    seven_result = archive_project(project, tmp_path / "archives", tmp_path / "data", archive_format=ArchiveFormat.SEVEN_ZIP)

    assert zip_result.manifest_path != seven_result.manifest_path
    assert Path(zip_result.manifest_path).name == "Two Formats.zip.manifest.json"
    assert Path(seven_result.manifest_path).name == "Two Formats.7z.manifest.json"
    assert verify_archive(Path(zip_result.archive_path), Path(zip_result.manifest_path))
    assert verify_archive(Path(seven_result.archive_path), Path(seven_result.manifest_path))


def test_archive_destination_cannot_be_inside_project(tmp_path: Path):
    project = make_project(tmp_path / "Projects", "Recursive")

    with pytest.raises(ValueError, match="inside the project"):
        archive_project(project, project / "archives", tmp_path / "data")


def test_archived_project_remains_discoverable_after_original_is_recycled(tmp_path: Path):
    project = make_project(tmp_path / "Projects", "Restorable")
    data = tmp_path / "data"

    result = archive_project(
        project,
        tmp_path / "archives",
        data,
        recycle_original=True,
        recycler=lambda path: __import__("shutil").rmtree(path),
    )
    records = archived_project_records(data)

    assert not project.exists()
    assert len(records) == 1
    assert records[0].name == "Restorable"
    assert records[0].state == ProjectState.ARCHIVED
    assert records[0].archive_manifest == result.manifest_path
    assert records[0].size_bytes == 154


def test_restore_refuses_to_overwrite_existing_project(tmp_path: Path):
    library = tmp_path / "Projects"
    project = make_project(library, "Old Portfolio")
    result = archive_project(project, tmp_path / "archives", tmp_path / "data")
    existing = tmp_path / "restore" / "Old Portfolio"
    existing.mkdir(parents=True)

    with pytest.raises(FileExistsError):
        restore_project(Path(result.manifest_path), tmp_path / "restore")


def test_quick_discovery_skips_dependency_projects_and_broad_non_projects(tmp_path: Path):
    documents = tmp_path / "Documents"
    (documents / "Study").mkdir(parents=True)
    (documents / "Files").mkdir()
    hit_asa = make_project(documents / "Projects", "HIT-ASA")
    jena = make_project(documents / "Projects", "Jena")

    roots = quick_discover_project_roots(documents, max_depth=3)

    assert roots == [hit_asa, jena]
    assert documents not in roots
    assert documents / "Study" not in roots
    assert all("node_modules" not in root.parts for root in roots)


def test_quick_discovery_treats_monorepo_as_primary_project(tmp_path: Path):
    workspace = tmp_path / "Workspace"
    (workspace / ".git").mkdir(parents=True)
    (workspace / "package.json").write_text("{}")
    (workspace / "pnpm-workspace.yaml").write_text("packages: []")
    (workspace / "apps" / "web").mkdir(parents=True)
    (workspace / "apps" / "web" / "package.json").write_text("{}")
    (workspace / "packages" / "shared").mkdir(parents=True)
    (workspace / "packages" / "shared" / "package.json").write_text("{}")

    roots = quick_discover_project_roots(tmp_path, max_depth=4)

    assert roots == [workspace]


def test_project_analysis_cache_provides_record_without_rescan(tmp_path: Path):
    data = tmp_path / "data"
    project = make_project(tmp_path / "Projects", "Cached")

    analyzed = analyze_and_cache_project(project, data)
    cache = load_project_cache(data)
    cached = project_record_from_cache(project, data)

    assert cache
    assert cached.size_bytes == analyzed.size_bytes
    assert cached.breakdown.regenerable_bytes == analyzed.breakdown.regenerable_bytes


def test_archive_recommendations_rank_only_old_inactive_projects(tmp_path: Path):
    now = time.time()
    old_small = project_record_from_cache(make_project(tmp_path / "Projects", "Old Small"), tmp_path / "data")
    old_small.state = ProjectState.INACTIVE
    old_small.modified_at = now - 120 * 86400
    old_small.size_bytes = 1_000
    old_small.breakdown.dependencies_bytes = 400

    old_large = project_record_from_cache(make_project(tmp_path / "Projects", "Old Large"), tmp_path / "data")
    old_large.state = ProjectState.INACTIVE
    old_large.modified_at = now - 180 * 86400
    old_large.size_bytes = 5_000
    old_large.breakdown.dependencies_bytes = 2_000

    active = project_record_from_cache(make_project(tmp_path / "Projects", "Active"), tmp_path / "data")
    active.state = ProjectState.ACTIVE
    active.modified_at = now - 365 * 86400
    active.size_bytes = 50_000

    protected = project_record_from_cache(make_project(tmp_path / "Projects", "Protected"), tmp_path / "data")
    protected.state = ProjectState.NEVER_ARCHIVE
    protected.modified_at = now - 365 * 86400

    recent = project_record_from_cache(make_project(tmp_path / "Projects", "Recent"), tmp_path / "data")
    recent.state = ProjectState.INACTIVE
    recent.modified_at = now - 10 * 86400

    recommendations = archive_recommendations(
        [old_small, active, old_large, protected, recent],
        now=now,
        inactive_days=90,
    )

    assert [item.project_name for item in recommendations] == ["Old Large", "Old Small"]
    assert recommendations[0].days_inactive == 180
    assert recommendations[0].minimum_reclaim_bytes == 2_000
