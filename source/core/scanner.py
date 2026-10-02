from __future__ import annotations

import os
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from threading import Event
from typing import Callable

from .classifiers import (
    ARCHIVE_EXTENSIONS,
    INSTALLER_EXTENSIONS,
    TEMP_EXTENSIONS,
    VIDEO_EXTENSIONS,
    classify_directory,
    classify_file,
    looks_like_screenshot,
)
from .duplicates import duplicate_groups
from .models import Finding, ProjectInfo, RiskLevel, ScanError, ScanResult
from .project_detector import PRUNE_DIRS, is_inside_dependency_tree, is_project_root, nearest_project, project_type
from .safety import is_blocked_scan_root, is_inside, review_folder

ProgressCallback = Callable[[dict], None]


@dataclass
class ScanOptions:
    large_file_mb: int = 250
    large_folder_mb: int = 500
    age_days: int = 30
    duplicate_min_mb: int = 25
    include_duplicates: bool = True


def _finding(path: Path, item_type: str, size: int, modified: float, category: str, reason: str,
             action: str, risk: RiskLevel, scope: str, project_root: Path | None,
             inside_git: bool, duplicate_group_id: str | None = None) -> Finding:
    recoverable = size if risk != RiskLevel.DO_NOT_TOUCH else 0
    canonical_path = canonicalize(path)
    return Finding(
        id=str(uuid.uuid4()),
        path=str(path),
        name=path.name,
        item_type=item_type,
        size_bytes=size,
        modified_at=modified,
        category=category,
        reason=reason,
        recommended_action=action,
        tags=[category],
        reasons=[reason],
        recommendations=[action],
        canonical_path=canonical_path,
        risk_level=risk,
        recoverable_bytes=recoverable,
        source_scope=scope,
        project_root=str(project_root) if project_root else None,
        is_git_repository=path.is_dir() and (path / ".git").exists(),
        is_inside_git_repository=inside_git,
        duplicate_group_id=duplicate_group_id,
    )


def canonicalize(path: Path) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


class Scanner:
    def __init__(self, options: ScanOptions | None = None) -> None:
        self.options = options or ScanOptions()

    def scan(self, root: Path, scope: str | None = None, cancel_event: Event | None = None,
             progress: ProgressCallback | None = None) -> ScanResult:
        root = root.expanduser().resolve()
        scope = scope or root.name
        cancel_event = cancel_event or Event()
        if is_blocked_scan_root(root):
            raise ValueError(f"{root} is outside StoragePilot's normal user-folder scope.")
        if not root.exists():
            raise FileNotFoundError(root)

        findings: list[Finding] = []
        projects: dict[str, ProjectInfo] = {}
        errors: list[ScanError] = []
        dir_sizes: defaultdict[str, int] = defaultdict(int)
        dir_modified: defaultdict[str, float] = defaultdict(float)
        files_by_size: defaultdict[int, list[Path]] = defaultdict(list)
        by_canonical_path: dict[str, Finding] = {}
        scanned_items = 0
        scanned_bytes = 0
        large_file_bytes = self.options.large_file_mb * 1024 * 1024
        large_folder_bytes = self.options.large_folder_mb * 1024 * 1024
        old_cutoff = datetime.now() - timedelta(days=self.options.age_days)
        last_progress = time.time()

        def add(item: Finding) -> None:
            existing = by_canonical_path.get(item.canonical_path)
            if existing:
                existing.add_classification(
                    item.category,
                    item.reason,
                    item.recommended_action,
                    item.risk_level,
                    existing.size_bytes,
                )
                if item.duplicate_group_id and not existing.duplicate_group_id:
                    existing.duplicate_group_id = item.duplicate_group_id
                return
            by_canonical_path[item.canonical_path] = item
            findings.append(item)

        for current, dirs, files in os.walk(root, topdown=True, followlinks=False):
            if cancel_event.is_set():
                break
            current_path = Path(current)
            if is_inside(current_path, review_folder()):
                dirs[:] = []
                continue
            dirs[:] = [d for d in dirs if d not in PRUNE_DIRS or d in {"node_modules", ".next", "dist", "build"}]
            project_root = nearest_project(current_path, root)
            inside_git = project_root is not None and (project_root / ".git").exists()

            try:
                stat = current_path.stat()
                dir_modified[str(current_path)] = max(dir_modified[str(current_path)], stat.st_mtime)
            except OSError as exc:
                errors.append(ScanError(str(current_path), str(exc)))
                continue

            if is_project_root(current_path) and not is_inside_dependency_tree(current_path):
                projects.setdefault(
                    str(current_path),
                    ProjectInfo(
                        path=str(current_path),
                        name=current_path.name,
                        size_bytes=0,
                        modified_at=stat.st_mtime,
                        project_type=project_type(current_path),
                        git_repository=(current_path / ".git").exists(),
                    ),
                )

            classified_dir = classify_directory(current_path)
            if classified_dir and current_path != root:
                risk, category, reason = classified_dir
                add(_finding(
                    current_path, "folder", 0, stat.st_mtime, category, reason,
                    "Review first, then move to the review folder only if approved.",
                    risk, scope, project_root, inside_git,
                ))

            for file_name in files:
                if cancel_event.is_set():
                    break
                path = current_path / file_name
                try:
                    file_stat = path.stat()
                except (PermissionError, FileNotFoundError, OSError) as exc:
                    errors.append(ScanError(str(path), str(exc)))
                    continue
                scanned_items += 1
                scanned_bytes += file_stat.st_size
                files_by_size[file_stat.st_size].append(path)
                for parent in [current_path, *current_path.parents]:
                    if parent == root.parent:
                        break
                    dir_sizes[str(parent)] += file_stat.st_size
                    dir_modified[str(parent)] = max(dir_modified[str(parent)], file_stat.st_mtime)

                suffix = path.suffix.lower()
                modified_dt = datetime.fromtimestamp(file_stat.st_mtime)
                file_project = nearest_project(path, root)
                file_inside_git = file_project is not None and (file_project / ".git").exists()

                if file_stat.st_size >= large_file_bytes:
                    risk = classify_file(path, "large_file")
                    add(_finding(path, "file", file_stat.st_size, file_stat.st_mtime, "large_file",
                                 f"One of the larger files in {scope}.",
                                 "Review manually; large does not mean disposable.",
                                 risk, scope, file_project, file_inside_git))
                if root.name.lower() == "downloads" and modified_dt < old_cutoff:
                    risk = classify_file(path, "old_download")
                    add(_finding(path, "file", file_stat.st_size, file_stat.st_mtime, "old_download",
                                 f"Download is older than {self.options.age_days} days.",
                                 "Review whether this inbox item has already been processed.",
                                 risk, scope, file_project, file_inside_git))
                if looks_like_screenshot(path) and modified_dt < old_cutoff:
                    add(_finding(path, "file", file_stat.st_size, file_stat.st_mtime, "old_screenshot",
                                 f"Screenshot-like file is older than {self.options.age_days} days.",
                                 "Review image before moving.",
                                 RiskLevel.REVIEW_REQUIRED, scope, file_project, file_inside_git))
                if suffix in TEMP_EXTENSIONS:
                    add(_finding(path, "file", file_stat.st_size, file_stat.st_mtime, "temporary_file",
                                 "Temporary or partial-download file extension.",
                                 "Usually movable after review.",
                                 classify_file(path, "temporary_file"), scope, file_project, file_inside_git))
                if suffix in INSTALLER_EXTENSIONS:
                    add(_finding(path, "file", file_stat.st_size, file_stat.st_mtime, "old_installer",
                                 "Installer package found.",
                                 "Move after confirming the app is installed or installer is no longer needed.",
                                 classify_file(path, "old_installer"), scope, file_project, file_inside_git))
                if suffix in ARCHIVE_EXTENSIONS:
                    add(_finding(path, "file", file_stat.st_size, file_stat.st_mtime, "archive_file",
                                 "Compressed archive found.",
                                 "Review contents; archives may contain source, assignments, or documents.",
                                 classify_file(path, "archive_file"), scope, file_project, file_inside_git))
                if suffix == ".iso":
                    add(_finding(path, "file", file_stat.st_size, file_stat.st_mtime, "iso_file",
                                 "Disk image found.",
                                 "Move only when you know it is no longer needed.",
                                 classify_file(path, "iso_file"), scope, file_project, file_inside_git))
                if suffix in VIDEO_EXTENSIONS:
                    add(_finding(path, "file", file_stat.st_size, file_stat.st_mtime, "video_file",
                                 "Video file found; videos often consume significant storage.",
                                 "Review manually; do not move personal videos unless approved.",
                                 classify_file(path, "video_file"), scope, file_project, file_inside_git))

                if progress and time.time() - last_progress > 0.25:
                    last_progress = time.time()
                    progress({"current": str(current_path), "items": scanned_items, "bytes": scanned_bytes, "findings": len(findings)})

        for path_text, size in dir_sizes.items():
            path = Path(path_text)
            modified = dir_modified.get(path_text, 0)
            if path_text in projects:
                projects[path_text].size_bytes = size
                projects[path_text].modified_at = modified
            classified_dir = classify_directory(path)
            if classified_dir:
                risk, category, reason = classified_dir
                for item in findings:
                    if item.path == path_text and item.category == category:
                        item.size_bytes = size
                        item.recoverable_bytes = size if item.risk_level != RiskLevel.DO_NOT_TOUCH else 0
                        item.modified_at = modified
                        break
            if size >= large_folder_bytes and path != root:
                project_root = nearest_project(path, root)
                inside_git = project_root is not None and (project_root / ".git").exists()
                add(_finding(path, "folder", size, modified, "large_folder",
                             f"Folder is larger than {self.options.large_folder_mb} MB.",
                             "Review folder contents before moving anything.",
                             RiskLevel.REVIEW_REQUIRED, scope, project_root, inside_git))

        for finding in findings:
            if finding.project_root and finding.risk_level == RiskLevel.SAFE_TO_REGENERATE:
                project = projects.get(finding.project_root)
                if project:
                    project.regenerable_bytes += finding.size_bytes

        if self.options.include_duplicates and not cancel_event.is_set():
            groups = duplicate_groups(files_by_size, self.options.duplicate_min_mb * 1024 * 1024)
            for group_id, paths in groups.items():
                for duplicate in paths[1:]:
                    try:
                        stat = duplicate.stat()
                    except OSError as exc:
                        errors.append(ScanError(str(duplicate), str(exc)))
                        continue
                    project_root = nearest_project(duplicate, root)
                    inside_git = project_root is not None and (project_root / ".git").exists()
                    add(_finding(duplicate, "file", stat.st_size, stat.st_mtime, "duplicate_file",
                                 "Same size and SHA-256 hash as another file in this scan.",
                                 "Review duplicates as a group; StoragePilot will not choose a personal copy automatically.",
                                 classify_file(duplicate, "duplicate_file"), scope, project_root, inside_git, group_id))

        return ScanResult(scope, str(root), findings, sorted(projects.values(), key=lambda p: p.size_bytes, reverse=True),
                          errors, scanned_items, scanned_bytes)
