from __future__ import annotations

from core.models import RiskLevel


RISK_LABELS = {
    RiskLevel.SAFE_TO_REGENERATE: "Safe to Regenerate",
    RiskLevel.LIKELY_DISPOSABLE: "Likely Disposable",
    RiskLevel.REVIEW_REQUIRED: "Needs Review",
    RiskLevel.DO_NOT_TOUCH: "Protected",
}

TAG_LABELS = {
    "archive_file": "Archive",
    "duplicate_file": "Duplicate",
    "git_repository": "Git Repository",
    "iso_file": "Disk Image",
    "large_file": "Large File",
    "large_folder": "Large Folder",
    "node_modules": "Development Dependencies",
    ".next": "Next.js Build Cache",
    "old_download": "Old Download",
    "old_installer": "Installer",
    "old_screenshot": "Old Screenshot",
    "python_virtual_environment": "Python Environment",
    "temporary_file": "Temporary File",
    "video_file": "Video",
    "coverage": "Coverage Output",
    "__pycache__": "Python Cache",
    "dist": "Build Output",
    "build": "Build Output",
}


def risk_label(risk: RiskLevel | str) -> str:
    if isinstance(risk, str):
        risk = RiskLevel(risk)
    return RISK_LABELS[risk]


def tag_label(tag: str) -> str:
    return TAG_LABELS.get(tag, tag.replace("_", " ").replace("-", " ").title())


def tags_label(tags: list[str]) -> str:
    return ", ".join(tag_label(tag) for tag in tags)
