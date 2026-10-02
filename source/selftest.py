from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import time
from pathlib import Path

from core.compression import ArchiveFormat
from core.downloads import categorize_downloads
from core.file_actions import permanently_delete_paths, recycle_paths
from core.operations import recycle_findings
from core.preview import PreviewService
from core.project_library import (
    ProjectState,
    analyze_and_cache_project,
    archive_project,
    discover_project_library,
    project_record_from_cache,
    quick_discover_project_roots,
    restore_project,
    set_project_state,
    state_display,
    stable_library_id,
    verify_archive,
    verify_restored_project,
)
from core.tasks import TaskEvent, TaskManager, TaskState


def run_self_test(output_path: Path) -> dict:
    root = output_path.parent / "jena-self-test-fixture"
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    data = root / "data"
    projects_root = root / "Projects"
    downloads_root = root / "Downloads"
    archive_root = root / "Archives"
    restore_root = root / "Restore"
    project = _make_project(projects_root, "Old Portfolio")
    _make_downloads(downloads_root)

    records = discover_project_library(projects_root, data)
    set_project_state(data, project, ProjectState.INACTIVE)
    persisted = discover_project_library(projects_root, data)

    recycled: list[str] = []
    downloads = categorize_downloads(downloads_root)
    installer_items = next(item for item in downloads if item.name == "Installers").findings
    recycle_manifest = recycle_findings(installer_items, sender=recycled.append)

    archive = archive_project(project, archive_root, data)
    restored = restore_project(Path(archive.manifest_path), restore_root)
    restored_path = Path(restored.restored_to or "")
    compact_archive = archive_project(project, archive_root, data, archive_format=ArchiveFormat.SEVEN_ZIP)
    compact_restored = restore_project(Path(compact_archive.manifest_path), root / "Restore7z")
    compact_restored_path = Path(compact_restored.restored_to or "")
    archive_preview = PreviewService(root / "preview-cache").preview(Path(compact_archive.archive_path))

    result = {
        "project_detection": {
            "count": len(records),
            "names": [record.name for record in records],
            "no_dependency_false_positives": [record.name for record in records] == ["Old Portfolio"],
        },
        "storage_accounting": {
            "project_size_bytes": records[0].size_bytes if records else 0,
            "regenerable_bytes": records[0].breakdown.regenerable_bytes if records else 0,
        },
        "persistence_after_restart": state_display(persisted[0].state) if persisted else "missing",
        "recycle_bin_test": {
            "status": recycle_manifest["items"][0]["status"] if recycle_manifest["items"] else "missing",
            "sender_received": recycled,
        },
        "archive_verification": {
            "verified": archive.verified and verify_archive(Path(archive.archive_path), Path(archive.manifest_path)),
            "archive_path": archive.archive_path,
            "manifest_path": archive.manifest_path,
            "excluded_bytes": archive.excluded_bytes,
        },
        "restore_hash_equality": {
            "verified": verify_restored_project(restored_path, Path(archive.manifest_path)),
            "restored_to": str(restored_path),
            "source_equal": (restored_path / "src" / "app.ts").read_bytes() == (project / "src" / "app.ts").read_bytes(),
        },
        "compression_service": {
            "zip": {
                "engine": archive.engine,
                "format": archive.archive_format,
                "verified": archive.verified and verify_archive(Path(archive.archive_path), Path(archive.manifest_path)),
                "restored_hashes_equal": verify_restored_project(restored_path, Path(archive.manifest_path)),
            },
            "seven_zip": {
                "engine": compact_archive.engine,
                "format": compact_archive.archive_format,
                "verified": compact_archive.verified and verify_archive(
                    Path(compact_archive.archive_path),
                    Path(compact_archive.manifest_path),
                ),
                "restored_hashes_equal": verify_restored_project(
                    compact_restored_path,
                    Path(compact_archive.manifest_path),
                ),
            },
        },
        "archive_container_preview": {
            "kind": archive_preview.kind,
            "file_count": int((archive_preview.metadata or {}).get("file_count", 0)),
            "has_navigable_entries": bool((archive_preview.metadata or {}).get("entries")),
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def verify_self_test_persistence(fixture_root: Path, output_path: Path) -> dict:
    data = fixture_root / "data"
    projects_root = fixture_root / "Projects"
    records = discover_project_library(projects_root, data)
    result = {
        "project_detection_after_restart": {
            "count": len(records),
            "names": [record.name for record in records],
        },
        "persistence_after_process_restart": state_display(records[0].state) if records else "missing",
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def run_project_registry_test(output_path: Path, large_entries: int = 20000) -> dict:
    root = output_path.parent / "jena-project-registry-fixture"
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    data = root / "data"

    documents = _make_fixture_a(root / "FixtureA" / "Documents")
    workspace = _make_fixture_b(root / "FixtureB" / "Workspace")
    python_project = _make_fixture_c(root / "FixtureC" / "PythonProject")
    large_library = root / "FixtureD" / "LargeLibrary"
    _make_large_project_library(large_library, large_entries)

    documents_library_id = stable_library_id(documents)
    roots_a = quick_discover_project_roots(documents, max_depth=3)
    records_a = discover_project_library(documents, data, library_id=documents_library_id)
    roots_b = quick_discover_project_roots(workspace.parent, max_depth=4)
    roots_c = quick_discover_project_roots(python_project.parent, max_depth=4)

    set_project_state(data, roots_a[0], ProjectState.ACTIVE, library_id=documents_library_id)
    project_b = workspace
    set_project_state(data, project_b, ProjectState.PAUSED, library_id=stable_library_id(workspace.parent))
    set_project_state(data, python_project, ProjectState.NEVER_ARCHIVE, library_id=stable_library_id(python_project.parent))

    events: queue.Queue = queue.Queue()
    manager = TaskManager(events, max_workers=2)
    task = manager.submit("registry.discover", _registry_discovery_job, large_library, data)
    streamed = 0
    completed = None
    started = time.time()
    while time.time() - started < 90:
        event: TaskEvent = events.get(timeout=10)
        if event.kind == "progress" and event.payload.get("event") == "project_found":
            streamed += 1
        if event.task_id == task.id and event.state == TaskState.COMPLETED:
            completed = event.payload
            break
    if completed is None:
        raise RuntimeError("Project Registry large-library test did not complete.")

    analyzed = analyze_and_cache_project(roots_a[0], data, library_id=documents_library_id)
    state_records = [
        project_record_from_cache(roots_a[0], data, library_id=documents_library_id),
        project_record_from_cache(project_b, data, library_id=stable_library_id(workspace.parent)),
        project_record_from_cache(python_project, data, library_id=stable_library_id(python_project.parent)),
    ]

    result = {
        "fixture_a": {
            "library": str(documents),
            "detected": [path.name for path in roots_a],
            "records": [record.name for record in records_a],
            "false_projects_absent": [path.name for path in roots_a] == ["HIT-ASA"],
        },
        "fixture_b_monorepo": {
            "detected": [path.name for path in roots_b],
            "one_primary_project": [path.name for path in roots_b] == ["Workspace"],
        },
        "fixture_c_python": {
            "detected": [path.name for path in roots_c],
            "virtualenv_packages_absent": [path.name for path in roots_c] == ["PythonProject"],
        },
        "fixture_d_large_library": {
            "fixture_entries": large_entries,
            "streamed_results": streamed,
            "discovered": completed["projects"],
            "elapsed_seconds": round(time.time() - started, 2),
            "bounded_discovery": completed["projects"] == ["CPPProject", "Monorepo", "NextApp", "PythonProject"],
        },
        "state_persistence_source": {
            record.name: state_display(record.state)
            for record in state_records
        },
        "size_breakdown": {
            "project": analyzed.name,
            "source_bytes": analyzed.source_size,
            "dependency_bytes": analyzed.dependency_size,
            "cache_bytes": analyzed.cache_size,
            "asset_bytes": analyzed.asset_size,
            "build_output_bytes": analyzed.build_output_size,
            "other_bytes": analyzed.other_size,
        },
        "activity_reasoning": analyzed.activity_evidence,
        "fixture_root": str(root),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def verify_project_registry_persistence(fixture_root: Path, output_path: Path) -> dict:
    data = fixture_root / "data"
    documents = fixture_root / "FixtureA" / "Documents"
    workspace = fixture_root / "FixtureB" / "Workspace"
    python_project = fixture_root / "FixtureC" / "PythonProject"
    records = [
        project_record_from_cache(documents / "Projects" / "HIT-ASA", data, library_id=stable_library_id(documents)),
        project_record_from_cache(workspace, data, library_id=stable_library_id(workspace.parent)),
        project_record_from_cache(python_project, data, library_id=stable_library_id(python_project.parent)),
    ]
    result = {
        "state_persistence_after_restart": {
            record.name: state_display(record.state)
            for record in records
        }
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def run_reliability_test(output_path: Path, large_entries: int = 20000) -> dict:
    root = output_path.parent / "jena-reliability-fixture"
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    data = root / "data"
    library = root / "TestProjects"
    _make_large_project_library(library, large_entries)

    events: queue.Queue = queue.Queue()
    manager = TaskManager(events, max_workers=2)
    task = manager.submit("reliability.discover", _discover_reliability_job, library, data)
    streamed = 0
    completed = None
    started = time.time()
    while time.time() - started < 60:
        event: TaskEvent = events.get(timeout=10)
        if event.kind == "progress" and event.payload.get("event") == "project_found":
            streamed += 1
        if event.task_id == task.id and event.state == TaskState.COMPLETED:
            completed = event.payload
            break
    if completed is None:
        raise RuntimeError("Project discovery reliability test did not complete.")

    preview_result = _run_preview_reliability(root)
    delete_result = _run_delete_reliability(root)

    result = {
        "large_library": {
            "fixture_entries": large_entries,
            "discovered": completed["projects"],
            "streamed_results": streamed,
            "elapsed_seconds": round(time.time() - started, 2),
            "bounded_discovery": completed["projects"] == ["CPPProject", "Monorepo", "NextApp", "PythonProject"],
        },
        "preview": preview_result,
        "delete": delete_result,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def _discover_reliability_job(token, progress, library: Path, data: Path) -> dict:
    roots: list[Path] = []

    def on_project(path: Path) -> None:
        roots.append(path)
        progress({"event": "project_found", "path": str(path), "found": len(roots)})

    quick_discover_project_roots(library, max_depth=3, token=token, on_project=on_project)
    for root in roots:
        analyze_and_cache_project(root, data, token=token)
    return {"projects": sorted(path.name for path in roots)}


def _registry_discovery_job(token, progress, library: Path, data: Path) -> dict:
    roots: list[Path] = []

    def on_project(path: Path) -> None:
        roots.append(path)
        progress({"event": "project_found", "path": str(path), "found": len(roots)})

    quick_discover_project_roots(library, max_depth=3, token=token, on_project=on_project)
    for root in roots:
        analyze_and_cache_project(root, data, token=token, library_id=stable_library_id(library))
    return {"projects": sorted(path.name for path in roots)}


def _make_fixture_a(documents: Path) -> Path:
    (documents / "Study").mkdir(parents=True)
    (documents / "RandomFiles").mkdir()
    project = documents / "Projects" / "HIT-ASA"
    (project / ".git").mkdir(parents=True)
    _write(project / "package.json", "{}")
    _write(project / "src" / "app.ts", "console.log('hit asa')")
    for package in ["uuid", "react"]:
        _write(project / "node_modules" / package / "package.json", "{}")
    return documents


def _make_fixture_b(workspace: Path) -> Path:
    (workspace / ".git").mkdir(parents=True)
    _write(workspace / "package.json", "{}")
    _write(workspace / "pnpm-workspace.yaml", "packages: []")
    _write(workspace / "apps" / "web" / "package.json", "{}")
    _write(workspace / "apps" / "api" / "package.json", "{}")
    _write(workspace / "packages" / "shared" / "package.json", "{}")
    _write(workspace / "node_modules" / "react" / "package.json", "{}")
    return workspace


def _make_fixture_c(project: Path) -> Path:
    (project / ".git").mkdir(parents=True)
    _write(project / "pyproject.toml", "[project]\nname='fixture'")
    _write(project / "src" / "app.py", "print('fixture')")
    for index in range(100):
        _write(project / ".venv" / "Lib" / "site-packages" / f"pkg_{index}" / "pyproject.toml", "[project]\nname='dependency'")
    return project


def _make_large_project_library(library: Path, entries: int) -> None:
    _make_node_project(library / "NextApp", entries // 4)
    _make_python_project(library / "PythonProject", entries // 4)
    _make_cpp_project(library / "CPPProject", entries // 4)
    _make_monorepo(library / "Monorepo", entries // 8)
    ordinary = library / "RandomDocuments"
    for index in range(max(1, entries // 8)):
        _write(ordinary / f"nested-{index // 100}" / f"file-{index}.txt", "ordinary")


def _make_node_project(project: Path, files: int) -> None:
    _write(project / "package.json", "{}")
    _write(project / "src" / "app.ts", "console.log('fixture')")
    for index in range(files):
        _write(project / "node_modules" / "pkg" / f"file-{index}.js", "x")


def _make_python_project(project: Path, files: int) -> None:
    _write(project / "pyproject.toml", "[project]\nname='fixture'")
    _write(project / "src" / "app.py", "print('fixture')")
    for index in range(files):
        _write(project / ".venv" / "Lib" / "site-packages" / "pkg" / f"file-{index}.py", "x")


def _make_cpp_project(project: Path, files: int) -> None:
    _write(project / "CMakeLists.txt", "cmake_minimum_required(VERSION 3.20)")
    _write(project / "src" / "main.cpp", "int main() { return 0; }")
    for index in range(files):
        _write(project / "build" / f"obj-{index}.o", "x")


def _make_monorepo(project: Path, files: int) -> None:
    (project / ".git").mkdir(parents=True)
    _write(project / "package.json", "{}")
    _write(project / "pnpm-workspace.yaml", "packages: []")
    _write(project / "apps" / "web" / "package.json", "{}")
    _write(project / "apps" / "api" / "package.json", "{}")
    _write(project / "packages" / "shared" / "package.json", "{}")
    for index in range(files):
        _write(project / "node_modules" / "pkg" / f"file-{index}.js", "x")


def _run_preview_reliability(root: Path) -> dict:
    preview_root = root / "PreviewFiles"
    cache = root / "preview-cache"
    service = PreviewService(cache)
    from PIL import Image

    image_path = preview_root / "photo.png"
    image_path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (240, 120), "green").save(image_path)
    text_path = preview_root / "notes.txt"
    _write(text_path, "text preview")

    import fitz
    pdf_path = preview_root / "assignment.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "PDF reliability preview")
    doc.save(pdf_path)
    doc.close()

    import docx
    docx_path = preview_root / "assignment.docx"
    word = docx.Document()
    word.add_paragraph("DOCX reliability preview")
    word.save(docx_path)

    import imageio_ffmpeg
    video_path = preview_root / "screen-capture.mp4"
    subprocess.run(
        [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-f", "lavfi", "-i", "color=c=red:s=160x90:d=1", str(video_path)],
        check=True,
        capture_output=True,
    )
    previews = {path.name: service.preview(path) for path in [image_path, text_path, pdf_path, docx_path, video_path]}
    return {
        name: {"kind": result.kind, "has_image": bool(result.image_path), "has_text": bool(result.text.strip())}
        for name, result in previews.items()
    }


def _run_delete_reliability(root: Path) -> dict:
    delete_root = root / "DeleteTest"
    recycle_file = delete_root / "recycle.tmp"
    permanent_file = delete_root / "permanent.tmp"
    _write(recycle_file, "recycle")
    _write(permanent_file, "permanent")
    sent: list[str] = []
    recycle_manifest = recycle_paths([recycle_file], sender=sent.append)
    permanent_manifest = permanently_delete_paths([permanent_file])
    return {
        "recycle_status": recycle_manifest["items"][0]["status"],
        "recycle_sender_received": bool(sent),
        "recycle_file_still_exists_in_fixture": recycle_file.exists(),
        "permanent_status": permanent_manifest["items"][0]["status"],
        "permanent_file_removed": not permanent_file.exists(),
    }


def _make_project(root: Path, name: str) -> Path:
    project = root / name
    (project / ".git").mkdir(parents=True)
    _write(project / "package.json", "{}")
    _write(project / "src" / "app.ts", "console.log('jena');\n")
    _write(project / "node_modules" / "react" / "package.json", "x" * 4096)
    _write(project / ".next" / "cache.bin", "c" * 2048)
    _write(project / "assets" / "hero.png", "i" * 1024)
    return project


def _make_downloads(root: Path) -> None:
    root.mkdir(parents=True)
    old = time.time() - 40 * 86400
    for name in ["setup-old.exe", "backup.zip", "screen.png"]:
        path = root / name
        _write(path, "fixture")
        os.utime(path, (old, old))


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
