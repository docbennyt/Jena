from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .models import Finding, RiskLevel
from .scanner import Scanner, ScanOptions


DOWNLOAD_CATEGORIES = {
    "Installers": {".exe", ".msi", ".msix", ".appx"},
    "Archives": {".zip", ".7z", ".rar", ".tar", ".gz"},
    "Images": {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"},
    "Documents": {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt"},
    "Videos": {".mp4", ".mov", ".avi", ".mkv", ".webm"},
}


@dataclass
class DownloadCategory:
    name: str
    count: int
    size_bytes: int
    findings: list[Finding]


def categorize_downloads(downloads_root: Path, age_days: int = 30) -> list[DownloadCategory]:
    result = Scanner(ScanOptions(age_days=age_days, include_duplicates=False, large_file_mb=1)).scan(downloads_root, "Downloads")
    grouped: dict[str, list[Finding]] = defaultdict(list)
    for finding in result.findings:
        if finding.item_type != "file":
            continue
        grouped[_category_for(Path(finding.path))].append(finding)
    categories = []
    for name in ["Installers", "Archives", "Images", "Documents", "Videos", "Other"]:
        items = grouped.get(name, [])
        categories.append(DownloadCategory(name, len(items), sum(item.size_bytes for item in items), items))
    return categories


def explain_download(finding: Finding) -> str:
    age_days = max(0, (datetime.now().timestamp() - finding.modified_at) // 86400)
    return (
        f"{finding.name} is {age_days:.0f} days old, uses {finding.size_bytes} bytes, "
        f"and is in {finding.path}. Suggested action: {finding.recommended_action}"
    )


def _category_for(path: Path) -> str:
    suffix = path.suffix.lower()
    for category, suffixes in DOWNLOAD_CATEGORIES.items():
        if suffix in suffixes:
            return category
    return "Other"
