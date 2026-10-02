from __future__ import annotations

import json
import os
import shutil
import subprocess
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
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    INACTIVE = "INACTIVE"
    ARCHIVED = "ARCHIVED"
    NEVER_ARCHIVE = "NEVER_ARCHIVE"
    IGNORED = "IGNORED"


DEPENDENCY_DIRS = {"node_modules", "vendor", ".venv", "venv", "env", "site-packages"}
CACHE_DIRS = {".next", "coverage", "__pycache__", ".pytest_cache", ".mypy_cache"}
BUILD_OUTPUT_DIRS = {"dist", "build"}
IGNORED_SCAN_DIRS = DEPENDENCY_DIRS | CACHE_DIRS | BUILD_OUTPUT_DIRS | {".git", ".cache"}
ASSET_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".psd", ".ai", ".fig", ".mp4", ".mov", ".mkv",
    ".wav", ".mp3", ".pdf", ".pptx", ".docx", ".xlsx",
}
PROJECT_MARKERS = {
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
    "package-lock.json",
    "yarn.lock",
    "Cargo.lock",
    "pom.xml",
    "*.sln",
    "*.csproj",
}
PROJECT_ACTIVITY_MARKERS = {marker for marker in PROJECT_MARKERS if "*" not in marker}


@dataclass
class ProjectBreakdown:
    source_bytes: int = 0
    dependencies_bytes: int = 0
    caches_bytes: int = 0
    assets_bytes: int = 0
    build_output_bytes: int = 0
    other_bytes: int = 0

    @property
    def total_bytes(self) -> int:
        return (
            self.source_bytes
            + self.dependencies_bytes
            + self.caches_bytes
            + self.assets_bytes
            + self.build_output_bytes
            + self.other_bytes
        )

    @property
    def regenerable_bytes(self) -> int:
        return self.dependencies_bytes + self.caches_bytes


@dataclass(frozen=True)
class ProjectLibrary:
    library_id: str
    root_path: str
    display_name: str
    created_at: float

    @classmethod
    def create(cls, root_path: Path, name: str | None = None) -> "ProjectLibrary":
        root = root_path.expanduser().resolve()
        return cls(
            library_id=stable_library_id(root),
            root_path=str(root),
            display_name=name or root.name or str(root),
            created_at=time.time(),
        )


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
    project_id: str = ""
    library_id: str = ""
    canonical_root_path: str = ""
    display_name: str = ""
    detected_markers: list[str] | None = None
    git_repository: bool = False
    git_remote: str | None = None
    git_branch: str | None = None
    git_commit: str | None = None
    git_dirty: bool = False
    pinned: bool = False
    never_archive: bool = False
    last_meaningful_activity: float = 0
    activity_evidence: list[str] | None = None
    analysis_timestamp: float = 0

    @property
    def total_size(self) -> int:
        return self.size_bytes

    @property
    def source_size(self) -> int:
        return self.breakdown.source_bytes

    @property
    def dependency_size(self) -> int:
        return self.breakdown.dependencies_bytes

    @property
    def cache_size(self) -> int:
        return self.breakdown.caches_bytes

    @property
    def asset_size(self) -> int:
        return self.breakdown.assets_bytes

    @property
    def build_output_size(self) -> int:
        return self.breakdown.build_output_bytes

    @property
    def other_size(self) -> int:
        return self.breakdown.other_bytes


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
    payload = json.loads(path.read_text(encoding="utf-8"))
    if "project_states" in payload:
        return payload.get("project_states", {})
    return payload


def save_project_states(data_root: Path, states: dict[str, dict]) -> None:
    data_root.mkdir(parents=True, exist_ok=True)
    payload = {"schema": "jena.project-registry.v1", "project_states": states}
    project_state_path(data_root).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def archived_project_records(data_root: Path) -> list[ProjectRecord]:
    records: list[ProjectRecord] = []
    for original_path, state_entry in load_project_states(data_root).items():
        if _project_state(state_entry.get("state", ProjectState.ACTIVE.value)) != ProjectState.ARCHIVED:
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
        record = ProjectRecord(
                name=str(manifest.get("project_name") or Path(original_path).name),
                path=str(manifest.get("project_path") or original_path),
                project_type=str(manifest.get("project_type") or "Archived project"),
                size_bytes=included_bytes + excluded_bytes,
                modified_at=float(manifest.get("created_at", 0)),
                state=ProjectState.ARCHIVED,
                breakdown=ProjectBreakdown(dependencies_bytes=excluded_bytes, other_bytes=included_bytes),
                archive_manifest=str(manifest_path),
            )
        records.append(finalize_project_record(record, state_entry))
    return sorted(records, key=lambda item: item.size_bytes, reverse=True)


def set_project_state(
    data_root: Path,
    project_path: Path,
    state: ProjectState,
    archive_manifest: Path | None = None,
    library_id: str = "",
) -> None:
    states = load_project_states(data_root)
    key = _canonical(project_path)
    entry = states.get(key, {})
    entry["state"] = state.value
    if library_id:
        entry["library_id"] = library_id
    entry["pinned"] = state in {ProjectState.ACTIVE, ProjectState.PAUSED, ProjectState.NEVER_ARCHIVE}
    entry["never_archive"] = state == ProjectState.NEVER_ARCHIVE
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


def discover_project_library(library_root: Path, data_root: Path | None = None, library_id: str = "") -> list[ProjectRecord]:
    library_root = library_root.expanduser().resolve()
    library_id = library_id or stable_library_id(library_root)
    states = load_project_states(data_root) if data_root else {}
    projects: list[ProjectRecord] = []
    for current, dirs, _files in os.walk(library_root, topdown=True, followlinks=False):
        current_path = Path(current)
        if current_path.name in IGNORED_SCAN_DIRS and current_path != library_root:
            dirs[:] = []
            continue
        if is_project_root(current_path):
            projects.append(build_project_record(current_path, states.get(_canonical(current_path), {}), library_id=library_id))
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


def project_record_from_cache(project_path: Path, data_root: Path, library_id: str = "") -> ProjectRecord:
    project_path = project_path.expanduser().resolve()
    states = load_project_states(data_root)
    cache = load_project_cache(data_root)
    key = _canonical(project_path)
    entry = cache.get(key, {})
    state_entry = states.get(key, {})
    breakdown_payload = entry.get("breakdown") or {}
    breakdown = ProjectBreakdown(**{field: int(breakdown_payload.get(field, 0)) for field in ProjectBreakdown.__dataclass_fields__})
    state = _project_state(state_entry.get("state", ProjectState.ACTIVE.value))
    markers = entry.get("detected_markers") or detected_markers(project_path)
    git_info = entry.get("git") or git_state(project_path)
    library_id = library_id or state_entry.get("library_id") or entry.get("library_id") or stable_library_id(project_path.parent)
    record = ProjectRecord(
        name=project_path.name,
        path=str(project_path),
        project_type=project_type(project_path),
        size_bytes=int(entry.get("size_bytes", breakdown.total_bytes)),
        modified_at=float(entry.get("modified_at", project_path.stat().st_mtime if project_path.exists() else 0)),
        state=state,
        breakdown=breakdown,
        archive_manifest=state_entry.get("archive_manifest"),
        library_id=library_id,
        detected_markers=markers,
        git_remote=git_info.get("remote"),
        git_branch=git_info.get("branch"),
        git_commit=git_info.get("commit"),
        git_dirty=bool(git_info.get("dirty")),
        last_meaningful_activity=float(entry.get("last_meaningful_activity", 0)),
        activity_evidence=entry.get("activity_evidence") or [],
        analysis_timestamp=float(entry.get("analysis_timestamp", entry.get("last_scan_time", 0))),
    )
    return finalize_project_record(record, state_entry)


def analyze_and_cache_project(
    project_path: Path,
    data_root: Path,
    token: CancellationToken | None = None,
    progress=None,
    library_id: str = "",
) -> ProjectRecord:
    project_path = project_path.expanduser().resolve()
    breakdown, modified_at, last_meaningful_activity, evidence = analyze_project_activity(project_path, token=token, progress=progress)
    markers = detected_markers(project_path)
    git_info = git_state(project_path)
    library_id = library_id or stable_library_id(project_path.parent)
    cache = load_project_cache(data_root)
    key = _canonical(project_path)
    cache[key] = {
        "project_root": str(project_path),
        "project_id": stable_project_id(library_id, project_path),
        "library_id": library_id,
        "last_scan_time": time.time(),
        "size_bytes": breakdown.total_bytes,
        "modified_at": modified_at,
        "last_meaningful_activity": last_meaningful_activity,
        "activity_evidence": evidence,
        "detected_markers": markers,
        "git": git_info,
        "analysis_timestamp": time.time(),
        "breakdown": asdict(breakdown),
    }
    save_project_cache(data_root, cache)
    states = load_project_states(data_root)
    return build_project_record(
        project_path,
        states.get(key, {}),
        breakdown=breakdown,
        modified_at=modified_at,
        library_id=library_id,
        last_meaningful_activity=last_meaningful_activity,
        activity_evidence=evidence,
        detected=markers,
        git_info=git_info,
        analysis_timestamp=cache[key]["analysis_timestamp"],
    )


def build_project_record(
    project_path: Path,
    state_entry: dict | None = None,
    breakdown: ProjectBreakdown | None = None,
    modified_at: float | None = None,
    library_id: str = "",
    last_meaningful_activity: float | None = None,
    activity_evidence: list[str] | None = None,
    detected: list[str] | None = None,
    git_info: dict | None = None,
    analysis_timestamp: float = 0,
) -> ProjectRecord:
    project_path = project_path.expanduser().resolve()
    state_entry = state_entry or {}
    if breakdown is None or modified_at is None:
        breakdown, modified_at = analyze_project(project_path)
    library_id = library_id or state_entry.get("library_id") or stable_library_id(project_path.parent)
    git_info = git_info or git_state(project_path)
    record = ProjectRecord(
        name=project_path.name,
        path=str(project_path),
        project_type=project_type(project_path),
        size_bytes=breakdown.total_bytes,
        modified_at=modified_at,
        state=_project_state(state_entry.get("state", ProjectState.ACTIVE.value)),
        breakdown=breakdown,
        archive_manifest=state_entry.get("archive_manifest"),
        library_id=library_id,
        detected_markers=detected or detected_markers(project_path),
        git_remote=git_info.get("remote"),
        git_branch=git_info.get("branch"),
        git_commit=git_info.get("commit"),
        git_dirty=bool(git_info.get("dirty")),
        last_meaningful_activity=last_meaningful_activity if last_meaningful_activity is not None else modified_at,
        activity_evidence=activity_evidence or [f"Latest meaningful project file change: {_format_age_time(modified_at)}."],
        analysis_timestamp=analysis_timestamp,
    )
    return finalize_project_record(record, state_entry)


def analyze_project(project_path: Path, token: CancellationToken | None = None, progress=None) -> tuple[ProjectBreakdown, float]:
    breakdown, modified_at, _activity, _evidence = analyze_project_activity(project_path, token=token, progress=progress)
    return breakdown, modified_at


def analyze_project_activity(
    project_path: Path,
    token: CancellationToken | None = None,
    progress=None,
) -> tuple[ProjectBreakdown, float, float, list[str]]:
    breakdown = ProjectBreakdown()
    latest = project_path.stat().st_mtime if project_path.exists() else 0
    source_latest = 0.0
    marker_latest = 0.0
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
            file_bucket = bucket if bucket else _file_bucket(path)
            _add_to_bucket(breakdown, file_bucket, stat.st_size)
            if file_bucket == "source":
                source_latest = max(source_latest, stat.st_mtime)
            if file_name in PROJECT_ACTIVITY_MARKERS:
                marker_latest = max(marker_latest, stat.st_mtime)
            scanned += 1
            if progress and scanned % 250 == 0:
                progress({"project": str(project_path), "current": str(current_path), "bytes": breakdown.total_bytes, "files": scanned})
        dirs[:] = list(dirs)
    git_info = git_state(project_path)
    git_commit_time = float(git_info.get("commit_time") or 0)
    last_meaningful = max(source_latest, marker_latest, git_commit_time, latest if git_info.get("dirty") else 0)
    evidence = activity_evidence(source_latest, marker_latest, git_commit_time, bool(git_info.get("dirty")), last_meaningful)
    return breakdown, latest, last_meaningful, evidence


def _entry_names_indicate_project(entry_names: set[str], path: Path) -> bool:
    marker_names = {marker for marker in PROJECT_MARKERS if "*" not in marker}
    return bool(entry_names & marker_names) or any(any(path.glob(pattern)) for pattern in ("*.sln", "*.csproj"))


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
    if any(part in BUILD_OUTPUT_DIRS for part in rel_parts):
        return "build_output"
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
    elif bucket == "build_output":
        breakdown.build_output_bytes += size
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


def stable_library_id(root_path: Path) -> str:
    return "lib_" + hashlib.sha256(_canonical(root_path.expanduser().resolve()).encode("utf-8")).hexdigest()[:16]


def stable_project_id(library_id: str, project_path: Path) -> str:
    identity = f"{library_id}:{_canonical(project_path.expanduser().resolve())}"
    return "proj_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]


def finalize_project_record(record: ProjectRecord, state_entry: dict | None = None) -> ProjectRecord:
    state_entry = state_entry or {}
    path = Path(record.path)
    record.canonical_root_path = _canonical(path)
    record.display_name = record.display_name or record.name
    record.project_id = record.project_id or stable_project_id(record.library_id, path)
    record.git_repository = bool(record.git_repository or (path / ".git").exists() or record.git_commit or record.git_remote)
    record.pinned = bool(state_entry.get("pinned", record.state in {ProjectState.ACTIVE, ProjectState.PAUSED, ProjectState.NEVER_ARCHIVE}))
    record.never_archive = bool(state_entry.get("never_archive", record.state == ProjectState.NEVER_ARCHIVE))
    if record.state == ProjectState.NEVER_ARCHIVE:
        record.never_archive = True
        record.pinned = True
    if record.activity_evidence is None:
        record.activity_evidence = []
    if record.detected_markers is None:
        record.detected_markers = []
    return record


def detected_markers(project_path: Path) -> list[str]:
    markers: list[str] = []
    for marker in sorted(PROJECT_MARKERS):
        if "*" in marker:
            if list(project_path.glob(marker)):
                markers.append(marker)
        elif (project_path / marker).exists():
            markers.append(marker)
    return markers


def git_state(project_path: Path) -> dict:
    if not (project_path / ".git").exists():
        return {"repository": False}
    top_level = _git_output(project_path, ["rev-parse", "--show-toplevel"])
    if not top_level:
        return {"repository": True}
    if _canonical(Path(top_level)) != _canonical(project_path):
        return {"repository": True}
    return {
        "repository": True,
        "remote": _git_output(project_path, ["config", "--get", "remote.origin.url"]),
        "branch": _git_output(project_path, ["rev-parse", "--abbrev-ref", "HEAD"]),
        "commit": _git_output(project_path, ["rev-parse", "HEAD"]),
        "commit_time": _git_timestamp(project_path),
        "dirty": bool(_git_output(project_path, ["status", "--porcelain"])),
    }


def activity_evidence(
    source_latest: float,
    marker_latest: float,
    git_commit_time: float,
    git_dirty: bool,
    last_meaningful: float,
) -> list[str]:
    evidence: list[str] = []
    if source_latest:
        evidence.append(f"Recent source change: {_format_age_time(source_latest)}.")
    if marker_latest:
        evidence.append(f"Recent project-file change: {_format_age_time(marker_latest)}.")
    if git_commit_time:
        evidence.append(f"Last Git commit: {_format_age_time(git_commit_time)}.")
    if git_dirty:
        evidence.append("Git working tree has uncommitted changes.")
    if not evidence and last_meaningful:
        evidence.append(f"Latest meaningful project activity: {_format_age_time(last_meaningful)}.")
    return evidence


def _git_output(project_path: Path, args: list[str]) -> str | None:
    startupinfo = None
    creationflags = 0
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        creationflags = subprocess.CREATE_NO_WINDOW
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=project_path,
            capture_output=True,
            text=True,
            shell=False,
            timeout=3,
            startupinfo=startupinfo,
            creationflags=creationflags,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    value = completed.stdout.strip()
    return value or None


def _git_timestamp(project_path: Path) -> float:
    value = _git_output(project_path, ["log", "-1", "--format=%ct"])
    if not value:
        return 0
    try:
        return float(value)
    except ValueError:
        return 0


def _project_state(value: str | ProjectState) -> ProjectState:
    if isinstance(value, ProjectState):
        return value
    aliases = {
        "Active": ProjectState.ACTIVE,
        "Paused": ProjectState.PAUSED,
        "Inactive": ProjectState.INACTIVE,
        "Archived": ProjectState.ARCHIVED,
        "Never Archive": ProjectState.NEVER_ARCHIVE,
        "Ignored": ProjectState.IGNORED,
    }
    if value in aliases:
        return aliases[value]
    return ProjectState(value)


def state_display(state: ProjectState) -> str:
    return {
        ProjectState.ACTIVE: "Active",
        ProjectState.PAUSED: "Paused",
        ProjectState.INACTIVE: "Inactive",
        ProjectState.ARCHIVED: "Archived",
        ProjectState.NEVER_ARCHIVE: "Never Archive",
        ProjectState.IGNORED: "Ignored",
    }[state]


def _format_age_time(timestamp: float) -> str:
    days = max(0, int((time.time() - timestamp) // 86400))
    if days == 0:
        return "today"
    if days == 1:
        return "1 day ago"
    return f"{days} days ago"


def record_to_json(record: ProjectRecord) -> dict:
    payload = asdict(record)
    payload["state"] = record.state.value
    return payload
