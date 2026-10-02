from __future__ import annotations

import os
import shutil
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .project_detector import is_project_root
from .safety import is_blocked_scan_root

try:
    from send2trash import send2trash
except ImportError:  # pragma: no cover
    send2trash = None


class DeleteMode(str, Enum):
    RECYCLE = "RECYCLE"
    PERMANENT = "PERMANENT"


@dataclass
class DeletePlan:
    targets: list[Path]
    total_bytes: int
    item_count: int
    high_risk: bool
    risk_reasons: list[str]
    blocked: list[str]


def build_delete_plan(paths: list[Path]) -> DeletePlan:
    targets = _dedupe_targets(paths)
    total = 0
    count = 0
    high_risk = False
    reasons: list[str] = []
    blocked: list[str] = []
    for target in targets:
        if is_restricted_path(target):
            blocked.append(f"{target}: restricted path")
            continue
        size, items = measure_path(target)
        total += size
        count += items
        if target.is_dir() and is_project_root(target):
            high_risk = True
            reasons.append(f"{target.name}: project root")
        if target.is_dir() and (target / ".git").exists():
            high_risk = True
            reasons.append(f"{target.name}: Git repository")
        if size >= 1024 * 1024 * 1024 or items >= 1000:
            high_risk = True
            reasons.append("large selection")
    return DeletePlan(targets, total, count, high_risk, sorted(set(reasons)), blocked)


def recycle_paths(paths: list[Path], sender=None, progress=None, token=None) -> dict:
    sender = sender or send2trash
    if sender is None:
        raise RuntimeError("Recycle Bin support is unavailable.")
    return _delete_paths(paths, DeleteMode.RECYCLE, sender, progress, token)


def permanently_delete_paths(paths: list[Path], progress=None, token=None) -> dict:
    return _delete_paths(paths, DeleteMode.PERMANENT, None, progress, token)


def _delete_paths(paths: list[Path], mode: DeleteMode, sender=None, progress=None, token=None) -> dict:
    plan = build_delete_plan(paths)
    manifest = {
        "operation_id": str(uuid.uuid4()),
        "created_at": time.time(),
        "operation": "recycle" if mode == DeleteMode.RECYCLE else "permanent_delete",
        "total_bytes": plan.total_bytes,
        "item_count": plan.item_count,
        "items": [],
        "blocked": plan.blocked,
    }
    processed = 0
    for target in plan.targets:
        if token and token.cancelled:
            break
        row = {"source": str(target), "status": "PENDING", "error": ""}
        if is_restricted_path(target):
            row["status"] = "SKIPPED"
            row["error"] = "Restricted path."
        elif not target.exists():
            row["status"] = "SKIPPED"
            row["error"] = "Path no longer exists."
        else:
            try:
                if mode == DeleteMode.RECYCLE:
                    sender(str(target))
                    row["status"] = "RECYCLED"
                elif target.is_dir():
                    shutil.rmtree(target)
                    row["status"] = "DELETED"
                else:
                    target.unlink()
                    row["status"] = "DELETED"
            except Exception as exc:
                row["status"] = "FAILED"
                row["error"] = str(exc)
        processed += 1
        if progress:
            progress({"processed": processed, "total": len(plan.targets), "current": str(target)})
        manifest["items"].append(row)
    statuses = {item["status"] for item in manifest["items"]}
    if "FAILED" in statuses:
        manifest["result"] = "Partial" if any(status in statuses for status in {"DELETED", "RECYCLED"}) else "Failed"
    elif "SKIPPED" in statuses:
        manifest["result"] = "Partial"
    else:
        manifest["result"] = "Completed"
    return manifest


def is_restricted_path(path: Path) -> bool:
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path.absolute()
    lower = str(resolved).lower()
    restricted_exact = {
        "c:\\",
        str(Path(os.environ.get("WINDIR", "C:\\Windows")).resolve()).lower(),
        "c:\\program files",
        "c:\\program files (x86)",
        "c:\\windows\\system32",
    }
    if lower in restricted_exact:
        return True
    if is_blocked_scan_root(resolved):
        return True
    app_root = Path(__file__).resolve().parents[2]
    data_root = app_root / "data"
    return _is_inside(resolved, app_root / "dist") or _is_inside(resolved, data_root)


def measure_path(path: Path) -> tuple[int, int]:
    if not path.exists():
        return 0, 0
    if path.is_file():
        try:
            return path.stat().st_size, 1
        except OSError:
            return 0, 1
    total = 0
    count = 0
    for current, _dirs, files in os.walk(path, followlinks=False):
        count += 1
        for file_name in files:
            count += 1
            try:
                total += (Path(current) / file_name).stat().st_size
            except OSError:
                continue
    return total, count


def _dedupe_targets(paths: list[Path]) -> list[Path]:
    resolved = []
    for path in paths:
        try:
            resolved.append(path.resolve())
        except OSError:
            resolved.append(path.absolute())
    unique = sorted(set(resolved), key=lambda p: len(p.parts))
    result: list[Path] = []
    for path in unique:
        if not any(_is_inside(path, parent) for parent in result):
            result.append(path)
    return result


def _is_inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except (ValueError, OSError):
        return False
