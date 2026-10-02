from __future__ import annotations

import os
import sys
from pathlib import Path


def app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def data_dir() -> Path:
    root = app_root()
    if (root / "portable.flag").exists():
        target = root / "data"
    else:
        target = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Jena"
    target.mkdir(parents=True, exist_ok=True)
    return target


def logs_dir() -> Path:
    target = app_root() / "logs" if (app_root() / "portable.flag").exists() else data_dir() / "logs"
    target.mkdir(parents=True, exist_ok=True)
    return target


def known_folder(name: str) -> Path:
    profile = Path(os.environ.get("USERPROFILE", str(Path.home())))
    return profile / name
