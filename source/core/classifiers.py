from __future__ import annotations

from pathlib import Path

from .models import RiskLevel


SOURCE_EXTENSIONS = {
    ".py", ".pyw", ".js", ".jsx", ".ts", ".tsx", ".java", ".c", ".cpp",
    ".h", ".hpp", ".cs", ".go", ".rs", ".php", ".rb", ".swift", ".kt",
    ".sql", ".ipynb", ".html", ".css", ".scss",
}
DOCUMENT_EXTENSIONS = {
    ".doc", ".docx", ".pdf", ".ppt", ".pptx", ".xls", ".xlsx", ".odt",
    ".ods", ".txt", ".rtf", ".md", ".csv",
}
DATABASE_EXTENSIONS = {".db", ".sqlite", ".sqlite3", ".mdb", ".accdb"}
DESIGN_EXTENSIONS = {".psd", ".ai", ".xd", ".fig", ".blend", ".aep", ".prproj", ".cdr", ".svg"}
PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic", ".raw", ".cr2", ".nef"}
INSTALLER_EXTENSIONS = {".exe", ".msi", ".msp", ".appx", ".msix"}
ARCHIVE_EXTENSIONS = {".zip", ".7z", ".rar", ".tar", ".gz"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".wmv", ".webm", ".m4v"}
TEMP_EXTENSIONS = {".tmp", ".temp", ".bak", ".old", ".dmp", ".crdownload", ".part"}

CACHE_DIRS = {
    "node_modules",
    ".next",
    "coverage",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".parcel-cache",
    ".turbo",
    ".cache",
}
CAUTIOUS_BUILD_DIRS = {"dist", "build"}
VENV_DIRS = {".venv", "venv", "env"}
PROJECT_METADATA = {
    "package.json", "pyproject.toml", "requirements.txt", "Pipfile",
    "poetry.lock", "uv.lock", "Cargo.toml", "go.mod", "CMakeLists.txt",
}


def is_protected_extension(path: Path) -> bool:
    suffix = path.suffix.lower()
    return suffix in SOURCE_EXTENSIONS | DOCUMENT_EXTENSIONS | DATABASE_EXTENSIONS | DESIGN_EXTENSIONS | PHOTO_EXTENSIONS


def classify_file(path: Path, category: str) -> RiskLevel:
    suffix = path.suffix.lower()
    if is_protected_extension(path):
        return RiskLevel.DO_NOT_TOUCH
    if suffix in VIDEO_EXTENSIONS or suffix in ARCHIVE_EXTENSIONS:
        return RiskLevel.REVIEW_REQUIRED
    if suffix in INSTALLER_EXTENSIONS or suffix in TEMP_EXTENSIONS or suffix == ".iso":
        return RiskLevel.LIKELY_DISPOSABLE
    if category in {"old_screenshot", "duplicate_file"}:
        return RiskLevel.REVIEW_REQUIRED
    return RiskLevel.REVIEW_REQUIRED


def classify_directory(path: Path) -> tuple[RiskLevel, str, str] | None:
    name = path.name
    lower_name = name.lower()
    if lower_name == ".git":
        return RiskLevel.DO_NOT_TOUCH, "git_repository", "Git metadata detected."
    if (path / ".git").exists():
        return RiskLevel.DO_NOT_TOUCH, "git_repository", "Git repository detected."
    if lower_name in CACHE_DIRS:
        return RiskLevel.SAFE_TO_REGENERATE, lower_name, "Development cache that is normally regenerable."
    if lower_name in CAUTIOUS_BUILD_DIRS:
        return RiskLevel.REVIEW_REQUIRED, lower_name, "Build output folder; review because it may contain deliverables."
    if lower_name in VENV_DIRS and ((path / "pyvenv.cfg").exists() or (path / "Scripts" / "python.exe").exists()):
        parent = path.parent
        has_metadata = any((parent / marker).exists() for marker in PROJECT_METADATA)
        if has_metadata:
            return RiskLevel.SAFE_TO_REGENERATE, "python_virtual_environment", "Python environment with dependency metadata nearby."
        return RiskLevel.REVIEW_REQUIRED, "python_virtual_environment", "Python environment found without clear dependency metadata."
    return None


def looks_like_screenshot(path: Path) -> bool:
    name = path.name.lower()
    return "screenshot" in name or name.startswith("screen shot") or name.startswith("snip") or name.startswith("capture")
