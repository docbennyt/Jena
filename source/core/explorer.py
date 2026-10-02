from __future__ import annotations

import os
import subprocess
from pathlib import Path


def open_in_explorer(path: Path) -> None:
    target = Path(path).expanduser().resolve()
    if not target.exists():
        raise FileNotFoundError(target)
    os.startfile(str(target))  # type: ignore[attr-defined]


def reveal_in_explorer(path: Path) -> None:
    target = Path(path).expanduser().resolve()
    if not target.exists():
        raise FileNotFoundError(target)
    if os.name == "nt":
        subprocess.Popen(["explorer", "/select,", str(target)], shell=False)
        return
    open_in_explorer(target.parent)
