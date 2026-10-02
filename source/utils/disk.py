from __future__ import annotations

import shutil
from pathlib import Path


def drive_usage(path: Path | str = "C:\\") -> dict:
    usage = shutil.disk_usage(path)
    return {
        "total": usage.total,
        "used": usage.used,
        "free": usage.free,
        "percent_used": (usage.used / usage.total * 100) if usage.total else 0,
    }
