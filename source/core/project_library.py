from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
import hashlib

from .compression import ArchiveFormat, compression_service
from .project_detector import is_project_root, project_type
from .tasks import CancellationToken, TaskCancelled


class ProjectState(str, Enum):
    ACTIVE = "Active"
    INACTIVE = "Inactive"
    NEVER_ARCHIVE = "Never Archive"
    ARCHIVED = "Archived"


DEPENDENCY_DIRS = {"node_modules", "vendor", ".venv", "venv", "env", "site-packages"}
CACHE_DIRS = {".next", "dist", "build", "coverage", "__pycache__", ".pytest_cache", ".mypy_cache"}
IGNORED_SCAN_DIRS = DEPENDENCY_DIRS | CACHE_DIRS | {".git", ".cache"}
ASSET_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".psd", ".ai", ".fig", ".mp4", ".mov", ".mkv",
    ".wav", ".mp3", ".pdf", ".pptx", ".docx", ".xlsx",
}


@dataclass
class ProjectBreakdown:
    source_bytes: int = 0
    dependencies_bytes: int = 0
    caches_bytes: int = 0
    assets_bytes: int = 0
    other_bytes: int = 0

    @property
    def total_bytes(self) -> int:
        return self.source_bytes + self.dependencies_bytes + self.caches_bytes + self.assets_bytes + self.other_bytes

    @property
    def regenerable_bytes(self) -> int:
        return self.dependencies_bytes + self.caches_bytes


@dataclass
class ProjectRecord:
    name: str
    path: str
    project_type: str
    size_bytes: int
    modified_at: float
    state: ProjectState
    breakdown: ProjectBreakdown
    archive_manifest: str | None = None


@dataclass
class ArchiveResult:
    project_path: str
    archive_path: str
    manifest_path: str
    included_files: int
    excluded_bytes: int
    archive_bytes: int
    verified: bool
    restored_to: str | None = None
    engine: str = ""
    archive_format: str = ArchiveFormat.ZIP.value


@dataclass(frozen=True)
class ArchiveRecommendation:
    project_name: str
    project_path: str
    days_inactive: int
    project_bytes: int
    minimum_reclaim_bytes: int
    estimated_archive_bytes: int
    reason: str


def archive_recommendations(
    projects: list[ProjectRecord],
    now: float | None = None,
    inactive_days: int = 90,
    limit: int = 10,
) -> list[ArchiveRecommendation]:
    current_time = now if now is not None else time.time()
    cutoff = current_time - max(1, inactive_days) * 86400
    recommendations: list[ArchiveRecommendation] = []
    for project in projects:
        if project.state != ProjectState.INACTIVE or project.modified_at > cutoff:
            continue
        days = max(0, int((current_time - project.modified_at) // 86400))
        minimum_reclaim = min(project.size_bytes, project.breakdown.regenerable_bytes)
        recommendations.append(
            ArchiveRecommendation(
                project_name=project.name,
                project_path=project.path,
                days_inactive=days,
                project_bytes=project.size_bytes,
                minimum_reclaim_bytes=minimum_reclaim,
                estimated_archive_bytes=max(project.size_bytes - minimum_reclaim, 0),
                reason=f"Inactive and unchanged for {days} days.",
            )
        )
    recommendations.sort(key=lambda item: (item.project_bytes, item.days_inactive), reverse=True)
    return recommendations[: max(0, limit)]


def project_cache_path(data_root: Path) -> Path:
    return data_root / "project-analysis-cache.json"


def project_state_path(data_root: Path) -> Path:
    return data_root / "project-library.json"


def load_project_states(data_root: Path) -> dict[str, dict]:
    path = project_state_path(data_root)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_project_states(data_root: Path, states: dict[str, dict]) -> None:
    data_root.mkdir(parents=True, exist_ok=True)
    project_state_path(data_root).write_text(json.dumps(states, indent=2), encoding="utf-8")


def archived_project_records(data_root: Path) -> list[ProjectRecord]:
    records: list[ProjectRecord] = []
    for original_path, state_entry in load_project_states(data_root).items():
        if state_entry.get("state") != ProjectState.ARCHIVED.value:
            continue
        manifest_value = state_entry.get("archive_manifest")
        if not manifest_value:
            continue
        manifest_path = Path(manifest_value)
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        included_bytes = int(manifest.get("compression", {}).get("input_bytes", 0))
        if not included_bytes:
            included_bytes = sum(int(item.get("size", 0)) for item in manifest.get("files", []))
        excluded_bytes = int(manifest.get("excluded_bytes", 0))
        records.append(
            ProjectRecord(
                name=str(manifest.get("project_name") or Path(original_path).name),
                path=str(manifest.get("project_path") or original_path),
                project_type=str(manifest.get("project_type") or "Archived project"),
                size_bytes=included_bytes + excluded_bytes,
                modified_at=float(manifest.get("created_at", 0)),
                state=ProjectState.ARCHIVED,
                breakdown=ProjectBreakdown(dependencies_bytes=excluded_bytes, other_bytes=included_bytes),
                archive_manifest=str(manifest_path),
            )
        )
    return sorted(records, key=lambda item: item.size_bytes, reverse=True)


def set_project_state(data_root: Path, project_path: Path, state: ProjectState, archive_manifest: Path | None = None) -> None:
    states = load_project_states(data_root)
    key = _canonical(project_path)
    entry = states.get(key, {})
    entry["state"] = state.value
    if archive_manifest is not None:
        entry["archive_manifest"] = str(archive_manifest)
    states[key] = entry
    save_project_states(data_root, states)


def load_project_cache(data_root: Path) -> dict[str, dict]:
    path = project_cache_path(data_root)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_project_cache(data_root: Path, cache: dict[str, dict]) -> None:
    data_root.mkdir(parents=True, exist_ok=True)
    project_cache_path(data_root).write_text(json.dumps(cache, indent=2), encoding="utf-8")


def discover_project_library(library_root: Path, data_root: Path | None = None) -> list[ProjectRecord]:
    library_root = library_root.expanduser().resolve()
    states = load_project_states(data_root) if data_root else {}
    projects: list[ProjectRecord] = []
    for current, dirs, _files in os.walk(library_root, topdown=True, followlinks=False):
        current_path = Path(current)
        if current_path.name in IGNORED_SCAN_DIRS and current_path != library_root:
            dirs[:] = []
            continue
        if is_project_root(current_path):
            projects.append(build_project_record(current_path, states.get(_canonical(current_path), {})))
            dirs[:] = [name for name in dirs if name not in IGNORED_SCAN_DIRS]
            continue
        dirs[:] = [name for name in dirs if name not in IGNORED_SCAN_DIRS]
    return sorted(projects, key=lambda item: item.size_bytes, reverse=True)


def quick_discover_project_roots(
    library_root: Path,
    max_depth: int = 3,
    token: CancellationToken | None = None,
    on_project=None,
    on_progress=None,
) -> list[Path]:
    library_root = library_root.expanduser().resolve()
    found: list[Path] = []
    stack: list[tuple[Path, int]] = [(library_root, 0)]
    while stack:
        if token and token.cancelled:
            raise TaskCancelled()
        current, depth = stack.pop()
        if on_progress:
            on_progress({"current": str(current), "found": len(found)})
        if current.name in IGNORED_SCAN_DIRS and current != library_root:
            continue
        try:
            entries = list(os.scandir(current))
        except OSError:
            continue
        entry_names = {entry.name for entry in entries}
        if _entry_names_indicate_project(entry_names, current):
            found.append(current)
            if on_project:
                on_project(current)
            continue
        if depth >= max_depth:
            continue
        for entry in reversed(entries):
            if not entry.is_dir(follow_symlinks=False):
                continue
            if entry.name in IGNORED_SCAN_DIRS:
                continue
            stack.append((Path(entry.path), depth + 1))
    return found


def project_record_from_cache(project_path: Path, data_root: Path) -> ProjectRecord:
    states = load_project_states(data_root)
    cache = load_project_cache(data_root)
    key = _canonical(project_path)
    entry = cache.get(key, {})
    state_entry = states.get(key, {})
    breakdown_payload = entry.get("breakdown") or {}
    breakdown = ProjectBreakdown(**{field: int(breakdown_payload.get(field, 0)) for field in ProjectBreakdown.__dataclass_fields__})
    state_value = state_entry.get("state", ProjectState.ACTIVE.value)
    return ProjectRecord(
        name=project_path.name,
        path=str(project_path),
        project_type=project_type(project_path),
        size_bytes=int(entry.get("size_bytes", breakdown.total_bytes)),
        modified_at=float(entry.get("modified_at", project_path.stat().st_mtime if project_path.exists() else 0)),
        state=ProjectState(state_value),
        breakdown=breakdown,
        archive_manifest=state_entry.get("archive_manifest"),
    )


def analyze_and_cache_project(project_path: Path, data_root: Path, token: CancellationToken | None = None, progress=None) -> ProjectRecord:
    breakdown, modified_at = analyze_project(project_path, token=token, progress=progress)
    cache = load_project_cache(data_root)
    key = _canonical(project_path)
    cache[key] = {
        "project_root": str(project_path),
        "last_scan_time": time.time(),
        "size_bytes": breakdown.total_bytes,
        "modified_at": modified_at,
        "breakdown": asdict(breakdown),
    }
    save_project_cache(data_root, cache)
    states = load_project_states(data_root)
    return build_project_record(project_path, states.get(key, {}), breakdown=breakdown, modified_at=modified_at)


def build_project_record(
    project_path: Path,
    state_entry: dict | None = None,
    breakdown: ProjectBreakdown | None = None,
    modified_at: float | None = None,
) -> ProjectRecord:
    state_entry = state_entry or {}
    if breakdown is None or modified_at is None:
        breakdown, modified_at = analyze_project(project_path)
    state_value = state_entry.get("state", ProjectState.ACTIVE.value)
    return ProjectRecord(
        name=project_path.name,
        path=str(project_path),
        project_type=project_type(project_path),
        size_bytes=breakdown.total_bytes,
        modified_at=modified_at,
        state=ProjectState(state_value),
        breakdown=breakdown,
        archive_manifest=state_entry.get("archive_manifest"),
    )


def analyze_project(project_path: Path, token: CancellationToken | None = None, progress=None) -> tuple[ProjectBreakdown, float]:
    breakdown = ProjectBreakdown()
    latest = project_path.stat().st_mtime if project_path.exists() else 0
    scanned = 0
    for current, dirs, files in os.walk(project_path, topdown=True, followlinks=False):
        if token and token.cancelled:
            raise TaskCancelled()
        current_path = Path(current)
        bucket = _bucket_for(current_path, project_path)
        for file_name in files:
            path = current_path / file_name
            try:
                stat = path.stat()
            except OSError:
                continue
            latest = max(latest, stat.st_mtime)
            _add_to_bucket(breakdown, bucket if bucket else _file_bucket(path), stat.st_size)
            scanned += 1
            if progress and scanned % 250 == 0:
                progress({"project": str(project_path), "current": str(current_path), "bytes": breakdown.total_bytes, "files": scanned})
        dirs[:] = list(dirs)
    return breakdown, latest


def _entry_names_indicate_project(entry_names: set[str], path: Path) -> bool:
    marker_names = {
        ".git",
        "package.json",
        "pyproject.toml",
        "requirements.txt",
        "Pipfile",
        "Cargo.toml",
        "go.mod",
        "CMakeLists.txt",
        "composer.json",
        "pnpm-workspace.yaml",
    }
    return bool(entry_names & marker_names) or any(child.suffix == ".sln" for child in path.glob("*.sln"))


def archive_project(
    project_path: Path,
    archive_dir: Path,
    data_root: Path,
    recycle_original: bool = False,
    recycler=None,
    archive_format: ArchiveFormat = ArchiveFormat.ZIP,
    service=None,
    token: CancellationToken | None = None,
    progress=None,
) -> ArchiveResult:
    project_path = project_path.resolve()
    archive_dir = archive_dir.resolve()
    try:
        archive_dir.relative_to(project_path)
    except ValueError:
        pass
    else:
        raise ValueError("The archive destination cannot be inside the project being archived.")
    archive_dir.mkdir(parents=True, exist_ok=True)
    data_root.mkdir(parents=True, exist_ok=True)
    archive_path = _unique_path(archive_dir / f"{project_path.name}.{archive_format.value}")
    manifest_path = archive_path.with_name(f"{archive_path.name}.manifest.json")
    included: list[dict] = []
    excluded_bytes = 0

    for current, dirs, files in os.walk(project_path, topdown=True, followlinks=False):
        if token:
            token.raise_if_cancelled()
        current_path = Path(current)
        excluded = [
            name
            for name in dirs
            if name in DEPENDENCY_DIRS or name in CACHE_DIRS or name == ".git" or (current_path / name).is_symlink()
        ]
        for name in excluded:
            excluded_bytes += directory_size(current_path / name)
        dirs[:] = [name for name in dirs if name not in excluded]
        for file_name in files:
            path = current_path / file_name
            if path.is_symlink():
                continue
            rel = path.relative_to(project_path).as_posix()
            try:
                stat = path.stat()
                digest = sha256_file(path)
            except OSError:
                continue
            included.append({"path": rel, "size": stat.st_size, "sha256": digest})
            if progress and len(included) % 100 == 0:
                progress({"phase": "hashing", "completed": len(included), "current": rel})

    selected_service = service or compression_service(archive_format)
    compression = selected_service.create(
        project_path,
        [item["path"] for item in included],
        archive_path,
        archive_format,
        token=token,
        progress=progress,
    )

    manifest = {
        "schema": "jena.project-archive.v2",
        "project_name": project_path.name,
        "project_path": str(project_path),
        "project_type": project_type(project_path),
        "archive_path": str(archive_path),
        "created_at": time.time(),
        "excluded_dirs": sorted(DEPENDENCY_DIRS | CACHE_DIRS | {".git"}),
        "excluded_bytes": excluded_bytes,
        "compression": {
            "engine": compression.engine,
            "format": compression.archive_format.value,
            "input_bytes": compression.input_bytes,
            "archive_bytes": compression.archive_bytes,
            "elapsed_seconds": compression.elapsed_seconds,
            "profile": "balanced",
        },
        "verification": {"integrity_tested": False, "hashes_verified": False},
        "files": included,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    verified = verify_archive(archive_path, manifest_path, service=selected_service, token=token, progress=progress)
    if not verified:
        raise RuntimeError("Archive verification failed.")
    manifest["verification"] = {
        "integrity_tested": True,
        "hashes_verified": True,
        "verified_at": time.time(),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    set_project_state(data_root, project_path, ProjectState.ARCHIVED, manifest_path)
    if recycle_original:
        if token:
            token.raise_if_cancelled()
        if recycler is None:
            from send2trash import send2trash as recycler
        recycler(str(project_path))
    return ArchiveResult(
        project_path=str(project_path),
        archive_path=str(archive_path),
        manifest_path=str(manifest_path),
        included_files=len(included),
        excluded_bytes=excluded_bytes,
        archive_bytes=archive_path.stat().st_size,
        verified=verified,
        engine=compression.engine,
        archive_format=compression.archive_format.value,
    )


def verify_archive(
    archive_path: Path,
    manifest_path: Path,
    service=None,
    token: CancellationToken | None = None,
    progress=None,
) -> bool:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    archive_format = _archive_format(manifest, archive_path)
    selected_service = service or compression_service(archive_format)
    if progress:
        progress({"phase": "integrity_test"})
    if not selected_service.test_archive(archive_path, token=token):
        return False
    entries = [entry for entry in selected_service.list_entries(archive_path, token=token) if not entry.is_dir]
    expected = {item["path"]: int(item["size"]) for item in manifest["files"]}
    actual = {entry.path: entry.size_bytes for entry in entries}
    if actual != expected:
        return False
    staging = Path(tempfile.mkdtemp(prefix=".jena-verify-", dir=str(archive_path.parent)))
    try:
        selected_service.extract(archive_path, staging, token=token, progress=progress)
        return verify_restored_project(staging, manifest_path, token=token, progress=progress)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def restore_project(
    manifest_path: Path,
    destination_root: Path,
    service=None,
    token: CancellationToken | None = None,
    progress=None,
) -> ArchiveResult:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    archive_path = Path(manifest["archive_path"])
    archive_format = _archive_format(manifest, archive_path)
    selected_service = service or compression_service(archive_format)
    destination_root.mkdir(parents=True, exist_ok=True)
    final_path = destination_root / manifest["project_name"]
    if final_path.exists():
        raise FileExistsError(f"{final_path} already exists.")
    staging = Path(tempfile.mkdtemp(prefix=f".jena-restore-{manifest['project_name']}-", dir=str(destination_root)))
    extracted_project = staging / manifest["project_name"]
    try:
        selected_service.extract(archive_path, extracted_project, token=token, progress=progress)
        if not verify_restored_project(extracted_project, manifest_path, token=token, progress=progress):
            raise RuntimeError("Restored project verification failed.")
        if token:
            token.raise_if_cancelled()
        shutil.move(str(extracted_project), str(final_path))
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
    return ArchiveResult(
        project_path=manifest["project_path"],
        archive_path=str(archive_path),
        manifest_path=str(manifest_path),
        included_files=len(manifest["files"]),
        excluded_bytes=int(manifest.get("excluded_bytes", 0)),
        archive_bytes=archive_path.stat().st_size,
        verified=True,
        restored_to=str(final_path),
        engine=manifest.get("compression", {}).get("engine", selected_service.engine_name),
        archive_format=archive_format.value,
    )


def verify_restored_project(
    project_path: Path,
    manifest_path: Path,
    token: CancellationToken | None = None,
    progress=None,
) -> bool:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for index, item in enumerate(manifest["files"], start=1):
        if token:
            token.raise_if_cancelled()
        path = project_path / Path(item["path"])
        if not path.exists() or path.stat().st_size != item["size"]:
            return False
        if sha256_file(path) != item["sha256"]:
            return False
        if progress and (index == len(manifest["files"]) or index % 100 == 0):
            progress({"phase": "hash_verification", "completed": index, "total": len(manifest["files"])})
    return True


def _archive_format(manifest: dict, archive_path: Path) -> ArchiveFormat:
    value = manifest.get("compression", {}).get("format") or archive_path.suffix.lower().lstrip(".")
    try:
        return ArchiveFormat(value)
    except ValueError as exc:
        raise ValueError(f"Unsupported archive format: {value}") from exc


def directory_size(path: Path) -> int:
    total = 0
    for current, _dirs, files in os.walk(path, followlinks=False):
        for file_name in files:
            try:
                total += (Path(current) / file_name).stat().st_size
            except OSError:
                continue
    return total


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _bucket_for(path: Path, project_path: Path) -> str | None:
    if path == project_path:
        return None
    rel_parts = path.relative_to(project_path).parts
    if any(part in DEPENDENCY_DIRS for part in rel_parts):
        return "dependencies"
    if any(part in CACHE_DIRS for part in rel_parts):
        return "caches"
    return None


def _file_bucket(path: Path) -> str:
    if path.suffix.lower() in ASSET_EXTENSIONS:
        return "assets"
    if path.suffix.lower() in {".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".css", ".json", ".toml", ".md", ".cs", ".go", ".rs"}:
        return "source"
    return "other"


def _add_to_bucket(breakdown: ProjectBreakdown, bucket: str, size: int) -> None:
    if bucket == "dependencies":
        breakdown.dependencies_bytes += size
    elif bucket == "caches":
        breakdown.caches_bytes += size
    elif bucket == "assets":
        breakdown.assets_bytes += size
    elif bucket == "source":
        breakdown.source_bytes += size
    else:
        breakdown.other_bytes += size


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    for index in range(2, 1000):
        candidate = path.with_name(f"{stem}-{index}{suffix}")
        if not candidate.exists():
            return candidate
    raise FileExistsError(path)


def _canonical(path: Path) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


def record_to_json(record: ProjectRecord) -> dict:
    payload = asdict(record)
    payload["state"] = record.state.value
    return payload
