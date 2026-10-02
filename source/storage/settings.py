from __future__ import annotations

import json
from pathlib import Path

from utils.paths import data_dir


DEFAULT_SETTINGS = {
    "dry_run": True,
    "theme": "dark",
    "large_file_mb": 250,
    "large_folder_mb": 500,
    "duplicate_min_mb": 25,
    "target_free_gb": 20,
    "project_library_root": "",
    "archive_destination": "",
    "archive_format": "zip",
    "archive_inactive_days": 90,
}


class Settings:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or data_dir() / "settings.json"
        self.values = dict(DEFAULT_SETTINGS)
        self.load()

    def load(self) -> None:
        if self.path.exists():
            self.values.update(json.loads(self.path.read_text(encoding="utf-8")))

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.values, indent=2), encoding="utf-8")

    def get(self, key: str):
        return self.values.get(key)

    def set(self, key: str, value) -> None:
        self.values[key] = value
        self.save()
