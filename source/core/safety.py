from __future__ import annotations

import os
from pathlib import Path

from .models import Finding, RiskLevel


REVIEW_FOLDER_NAME = "_REVIEW_BEFORE_DELETE"


def user_profile() -> Path:
    return Path(os.environ.get("USERPROFILE", str(Path.home()))).resolve()


def review_folder() -> Path:
    return user_profile() / REVIEW_FOLDER_NAME


def is_inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except (ValueError, OSError):
        return False


def is_blocked_scan_root(path: Path) -> bool:
    resolved = path.resolve()
    blocked_names = {"Windows", "Program Files", "Program Files (x86)", "System32"}
    if str(resolved).lower() in {"c:\\", "c:/"}:
        return True
    return any(part in blocked_names for part in resolved.parts)


def can_move_to_review(finding: Finding) -> tuple[bool, str]:
    source = Path(finding.path)
    if finding.risk_level == RiskLevel.DO_NOT_TOUCH:
        return False, "Protected items cannot be moved by normal cleanup controls."
    if is_inside(source, review_folder()):
        return False, "Item is already in the review folder."
    if finding.is_git_repository or finding.is_inside_git_repository:
        return False, "Items in Git repositories require explicit separate review."
    if not source.exists():
        return False, "Item no longer exists at its original path."
    return True, ""
