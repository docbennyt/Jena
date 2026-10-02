from __future__ import annotations

from datetime import datetime


def format_bytes(size: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{size} B"


def format_date(timestamp: float) -> str:
    if not timestamp:
        return ""
    then = datetime.fromtimestamp(timestamp)
    today = datetime.now().date()
    if then.date() == today:
        return f"Today {then:%H:%M}"
    if (today - then.date()).days == 1:
        return "Yesterday"
    return then.strftime("%b %d, %Y")
