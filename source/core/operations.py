from __future__ import annotations

import json
import shutil
import uuid
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from .models import Finding
from .safety import can_move_to_review, review_folder

try:
    from send2trash import send2trash
except ImportError:  # pragma: no cover
    send2trash = None


def destination_for(source: Path, review_root: Path | None = None) -> Path:
    review_root = review_root or review_folder()
    drive = source.drive.replace(":", "") or "drive"
    try:
        relative = source.resolve().relative_to(source.anchor)
    except (ValueError, OSError):
        relative = Path(source.name)
    destination = review_root / drive / relative
    if not destination.exists():
        return destination
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return destination.with_name(f"{destination.name}.{stamp}")


def move_to_review(findings: list[Finding], execute: bool = False, review_root: Path | None = None) -> dict:
    review_root = review_root or review_folder()
    operation_id = str(uuid.uuid4())
    manifest = {
        "operation_id": operation_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "execute": execute,
        "review_root": str(review_root),
        "items": [],
    }
    if execute:
        review_root.mkdir(parents=True, exist_ok=True)
    for finding in findings:
        source = Path(finding.path)
        allowed, reason = can_move_to_review(finding)
        destination = destination_for(source, review_root)
        row = {
            "finding": _json_ready(asdict(finding)),
            "source": str(source),
            "destination": str(destination),
            "status": "DRY_RUN",
            "error": "",
        }
        if not allowed:
            row["status"] = "SKIPPED"
            row["error"] = reason
        elif execute:
            try:
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(source), str(destination))
                row["status"] = "MOVED"
            except OSError as exc:
                row["status"] = "FAILED"
                row["error"] = str(exc)
        manifest["items"].append(row)
    if execute:
        manifest_path = review_root / f"operation-{operation_id}.json"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        manifest["manifest_path"] = str(manifest_path)
    return manifest


def _json_ready(value):
    if isinstance(value, dict):
        return {key: _json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    if hasattr(value, "value"):
        return value.value
    return value


def restore_from_manifest(manifest_path: Path, item_indexes: list[int] | None = None) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    indexes = item_indexes if item_indexes is not None else list(range(len(manifest.get("items", []))))
    results = []
    for index in indexes:
        item = manifest["items"][index]
        if item.get("status") != "MOVED":
            results.append({"index": index, "status": "SKIPPED", "error": "Item was not moved."})
            continue
        source = Path(item["source"])
        destination = Path(item["destination"])
        if not destination.exists():
            results.append({"index": index, "status": "FAILED", "error": "Reviewed item is missing."})
            continue
        restore_target = source
        if restore_target.exists():
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            restore_target = source.with_name(f"{source.name}.restored-{stamp}")
        try:
            restore_target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(destination), str(restore_target))
            item["status"] = "RESTORED"
            item["restored_to"] = str(restore_target)
            results.append({"index": index, "status": "RESTORED", "restored_to": str(restore_target)})
        except OSError as exc:
            results.append({"index": index, "status": "FAILED", "error": str(exc)})
    manifest["restored_at"] = datetime.now().isoformat(timespec="seconds")
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return {"manifest_path": str(manifest_path), "results": results}


def recycle_findings(findings: list[Finding], sender=None) -> dict:
    sender = sender or send2trash
    if sender is None:
        raise RuntimeError("Recycle Bin support is unavailable because send2trash is not installed.")
    operation_id = str(uuid.uuid4())
    manifest = {
        "operation_id": operation_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "operation": "recycle",
        "items": [],
    }
    for finding in findings:
        source = Path(finding.path)
        allowed, reason = can_move_to_review(finding)
        row = {
            "finding": _json_ready(asdict(finding)),
            "source": str(source),
            "status": "PENDING",
            "error": "",
        }
        if not allowed:
            row["status"] = "SKIPPED"
            row["error"] = reason
        else:
            try:
                sender(str(source))
                row["status"] = "RECYCLED"
            except Exception as exc:
                row["status"] = "FAILED"
                row["error"] = str(exc)
        manifest["items"].append(row)
    return manifest
