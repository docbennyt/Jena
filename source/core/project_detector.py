from __future__ import annotations

from pathlib import Path


PROJECT_MARKERS = {
    ".git",
    "package.json",
    "pyproject.toml",
    "requirements.txt",
    "Pipfile",
    "Cargo.toml",
    "go.mod",
    "CMakeLists.txt",
    "composer.json",
}

DEPENDENCY_DIRS = {
    "node_modules",
    "vendor",
    "site-packages",
    ".venv",
    "venv",
    "env",
    ".git",
    ".next",
    "dist",
    "build",
    "coverage",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
}
PRUNE_DIRS = set(DEPENDENCY_DIRS)


def is_inside_dependency_tree(path: Path) -> bool:
    return any(part in DEPENDENCY_DIRS for part in path.parts)


def is_project_root(path: Path) -> bool:
    return any((path / marker).exists() for marker in PROJECT_MARKERS) or bool(list(path.glob("*.sln")))


def project_type(path: Path) -> str:
    if (path / "package.json").exists():
        if (path / "next.config.js").exists() or (path / "next.config.mjs").exists() or (path / ".next").exists():
            return "Next.js"
        return "Node/JavaScript"
    if (path / "pyproject.toml").exists() or (path / "requirements.txt").exists() or (path / "Pipfile").exists():
        return "Python"
    if (path / "Cargo.toml").exists():
        return "Rust"
    if (path / "go.mod").exists():
        return "Go"
    if (path / "CMakeLists.txt").exists():
        return "C/C++"
    if list(path.glob("*.sln")):
        return ".NET"
    if (path / ".git").exists():
        return "Git repository"
    return "Development project"


def nearest_project(path: Path, stop_at: Path | None = None) -> Path | None:
    stop_at = stop_at.resolve() if stop_at else None
    for parent in [path, *path.parents]:
        if is_project_root(parent) and not is_inside_dependency_tree(parent):
            return parent
        if stop_at and parent.resolve() == stop_at:
            break
    return None
