from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile

from .tasks import CancellationToken, TaskCancelled


class ArchiveFormat(str, Enum):
    ZIP = "zip"
    SEVEN_ZIP = "7z"


@dataclass(frozen=True)
class ArchiveEntry:
    path: str
    size_bytes: int
    packed_bytes: int = 0
    modified_at: str = ""
    is_dir: bool = False


@dataclass(frozen=True)
class CompressionResult:
    archive_path: str
    archive_format: ArchiveFormat
    engine: str
    input_bytes: int
    archive_bytes: int
    elapsed_seconds: float


class CompressionError(RuntimeError):
    pass


class BuiltinZipCompressionService:
    engine_name = "python-zip"

    def create(
        self,
        source_root: Path,
        relative_files: list[str],
        destination: Path,
        archive_format: ArchiveFormat = ArchiveFormat.ZIP,
        compression_level: int = 6,
        token: CancellationToken | None = None,
        progress=None,
    ) -> CompressionResult:
        if archive_format != ArchiveFormat.ZIP:
            raise CompressionError("The built-in engine can create ZIP archives only.")
        _raise_if_cancelled(token)
        source_root = source_root.resolve()
        files = _validated_source_files(source_root, relative_files)
        destination = destination.resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        _validate_destination(destination, archive_format)
        partial = _partial_archive_path(destination)
        started = time.perf_counter()
        input_bytes = 0
        try:
            with ZipFile(partial, "w", ZIP_DEFLATED, compresslevel=max(0, min(compression_level, 9))) as archive:
                for index, (relative, source) in enumerate(files, start=1):
                    _raise_if_cancelled(token)
                    archive.write(source, relative)
                    input_bytes += source.stat().st_size
                    if progress and (index == len(files) or index % 100 == 0):
                        progress({"phase": "compressing", "completed": index, "total": len(files)})
            _raise_if_cancelled(token)
            os.replace(partial, destination)
        except Exception:
            partial.unlink(missing_ok=True)
            raise
        return CompressionResult(
            str(destination),
            archive_format,
            self.engine_name,
            input_bytes,
            destination.stat().st_size,
            time.perf_counter() - started,
        )

    def list_entries(self, archive_path: Path, token: CancellationToken | None = None) -> list[ArchiveEntry]:
        _raise_if_cancelled(token)
        try:
            with ZipFile(archive_path, "r") as archive:
                entries = [
                    ArchiveEntry(
                        path=_safe_member_path(info.filename),
                        size_bytes=info.file_size,
                        packed_bytes=info.compress_size,
                        modified_at="-".join(str(part) for part in info.date_time),
                        is_dir=info.is_dir(),
                    )
                    for info in archive.infolist()
                ]
        except BadZipFile as exc:
            raise CompressionError(f"Invalid ZIP archive: {archive_path}") from exc
        return entries

    def test_archive(self, archive_path: Path, token: CancellationToken | None = None) -> bool:
        _raise_if_cancelled(token)
        try:
            self.list_entries(archive_path, token=token)
            with ZipFile(archive_path, "r") as archive:
                return archive.testzip() is None
        except (CompressionError, BadZipFile, OSError):
            return False

    def extract(
        self,
        archive_path: Path,
        destination: Path,
        token: CancellationToken | None = None,
        progress=None,
    ) -> None:
        entries = self.list_entries(archive_path, token=token)
        _prepare_extract_destination(destination, entries)
        with ZipFile(archive_path, "r") as archive:
            for index, entry in enumerate(entries, start=1):
                _raise_if_cancelled(token)
                archive.extract(entry.path, destination)
                if progress and (index == len(entries) or index % 100 == 0):
                    progress({"phase": "extracting", "completed": index, "total": len(entries)})


class SevenZipCompressionService:
    def __init__(self, executable: Path) -> None:
        self.executable = Path(executable)
        self._engine_name: str | None = None

    @property
    def engine_name(self) -> str:
        if self._engine_name is None:
            try:
                output = self._run(["-h"]).stdout
                first_line = next((line.strip() for line in output.splitlines() if line.strip()), "")
                self._engine_name = first_line.split(":", 1)[0].strip() or "7-Zip"
            except CompressionError:
                self._engine_name = "7-Zip"
        return self._engine_name

    def create(
        self,
        source_root: Path,
        relative_files: list[str],
        destination: Path,
        archive_format: ArchiveFormat = ArchiveFormat.ZIP,
        compression_level: int = 5,
        token: CancellationToken | None = None,
        progress=None,
    ) -> CompressionResult:
        _raise_if_cancelled(token)
        source_root = source_root.resolve()
        files = _validated_source_files(source_root, relative_files)
        destination = destination.resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        _validate_destination(destination, archive_format)
        partial = _partial_archive_path(destination)
        input_bytes = sum(path.stat().st_size for _relative, path in files)
        list_path: Path | None = None
        started = time.perf_counter()
        try:
            with tempfile.NamedTemporaryFile("w", suffix=".txt", encoding="utf-8", newline="\n", delete=False) as handle:
                list_path = Path(handle.name)
                for relative, _source in files:
                    handle.write(relative + "\n")
            if progress:
                progress({"phase": "compressing", "completed": 0, "total": len(files)})
            self._run(
                [
                    "a",
                    f"-t{archive_format.value}",
                    f"-mx={max(0, min(compression_level, 9))}",
                    "-mmt=on",
                    "-sse",
                    "-ssp",
                    "-spd",
                    "-bd",
                    "-bb0",
                    "-bso1",
                    "-bse1",
                    "-bsp0",
                    "-scsUTF-8",
                    str(partial),
                    f"@{list_path}",
                ],
                cwd=source_root,
                token=token,
            )
            _raise_if_cancelled(token)
            os.replace(partial, destination)
            if progress:
                progress({"phase": "compressing", "completed": len(files), "total": len(files)})
        except Exception:
            partial.unlink(missing_ok=True)
            raise
        finally:
            if list_path:
                list_path.unlink(missing_ok=True)
        return CompressionResult(
            str(destination),
            archive_format,
            self.engine_name,
            input_bytes,
            destination.stat().st_size,
            time.perf_counter() - started,
        )

    def list_entries(self, archive_path: Path, token: CancellationToken | None = None) -> list[ArchiveEntry]:
        completed = self._run(
            ["l", "-slt", "-sccUTF-8", "--", str(Path(archive_path).resolve())],
            token=token,
        )
        entries = _parse_7zip_listing(completed.stdout)
        for entry in entries:
            _safe_member_path(entry.path)
        return entries

    def test_archive(self, archive_path: Path, token: CancellationToken | None = None) -> bool:
        try:
            self._run(["t", "-bd", "-bb0", "-bso1", "-bse1", "-bsp0", "--", str(Path(archive_path).resolve())], token=token)
            return True
        except TaskCancelled:
            raise
        except CompressionError:
            return False

    def extract(
        self,
        archive_path: Path,
        destination: Path,
        token: CancellationToken | None = None,
        progress=None,
    ) -> None:
        entries = self.list_entries(archive_path, token=token)
        _prepare_extract_destination(destination, entries)
        if progress:
            progress({"phase": "extracting", "completed": 0, "total": len(entries)})
        self._run(
            [
                "x",
                "-y",
                "-aoa",
                "-bd",
                "-bb0",
                "-bso1",
                "-bse1",
                "-bsp0",
                f"-o{destination.resolve()}",
                "--",
                str(Path(archive_path).resolve()),
            ],
            token=token,
        )
        if progress:
            progress({"phase": "extracting", "completed": len(entries), "total": len(entries)})

    def _run(
        self,
        arguments: list[str],
        cwd: Path | None = None,
        token: CancellationToken | None = None,
    ) -> subprocess.CompletedProcess[str]:
        _raise_if_cancelled(token)
        command = [str(self.executable), *arguments]
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        try:
            process = subprocess.Popen(
                command,
                cwd=str(cwd) if cwd else None,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                shell=False,
                creationflags=creationflags,
            )
        except OSError as exc:
            raise CompressionError(f"Unable to start 7-Zip: {exc}") from exc
        while True:
            try:
                stdout, stderr = process.communicate(timeout=0.1)
                break
            except subprocess.TimeoutExpired:
                if token and token.cancelled:
                    process.terminate()
                    try:
                        process.communicate(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.communicate()
                    raise TaskCancelled()
        if process.returncode != 0:
            detail = (stderr or stdout).strip()
            raise CompressionError(f"7-Zip failed with exit code {process.returncode}: {detail[-1200:]}")
        return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def find_7zip_executable() -> Path | None:
    candidates: list[Path] = []
    override = os.environ.get("JENA_7ZIP_PATH")
    if override:
        candidates.append(Path(override))
    if getattr(sys, "frozen", False):
        bundle_root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        candidates.extend([bundle_root / "tools" / "7zip" / "7z.exe", Path(sys.executable).parent / "tools" / "7zip" / "7z.exe"])
    project_root = Path(__file__).resolve().parents[2]
    candidates.append(project_root / "vendor" / "7zip" / "7z.exe")
    for variable in ("ProgramFiles", "ProgramFiles(x86)"):
        root = os.environ.get(variable)
        if root:
            candidates.append(Path(root) / "7-Zip" / "7z.exe")
    discovered = shutil.which("7z.exe") or shutil.which("7zz.exe")
    if discovered:
        candidates.append(Path(discovered))
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    return None


def compression_service(require_format: ArchiveFormat = ArchiveFormat.ZIP):
    executable = find_7zip_executable()
    if executable:
        return SevenZipCompressionService(executable)
    if require_format == ArchiveFormat.ZIP:
        return BuiltinZipCompressionService()
    raise CompressionError("7-Zip is required to work with .7z archives.")


def _validated_source_files(source_root: Path, relative_files: list[str]) -> list[tuple[str, Path]]:
    if not relative_files:
        raise CompressionError("There are no files to archive.")
    validated: list[tuple[str, Path]] = []
    seen: set[str] = set()
    for raw in relative_files:
        relative = _safe_member_path(raw)
        if "\n" in relative or "\r" in relative:
            raise CompressionError("Archive file names cannot contain line breaks.")
        if relative in seen:
            continue
        source = source_root / Path(relative)
        try:
            resolved = source.resolve(strict=True)
            resolved.relative_to(source_root)
        except (OSError, ValueError) as exc:
            raise CompressionError(f"Source file is outside the project: {relative}") from exc
        if source.is_symlink() or not resolved.is_file():
            raise CompressionError(f"Only regular files can be archived: {relative}")
        seen.add(relative)
        validated.append((relative, resolved))
    return validated


def _safe_member_path(raw: str) -> str:
    normalized = raw.replace("\\", "/").rstrip("/")
    path = PurePosixPath(normalized)
    if (
        not normalized
        or normalized.startswith(("/", "//"))
        or path.is_absolute()
        or any(part in {"", ".", ".."} or ":" in part for part in path.parts)
    ):
        raise CompressionError(f"Archive contains an unsafe path: {raw}")
    return path.as_posix()


def _prepare_extract_destination(destination: Path, entries: list[ArchiveEntry]) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    destination_root = destination.resolve()
    for entry in entries:
        relative = _safe_member_path(entry.path)
        target = (destination_root / Path(relative)).resolve()
        try:
            target.relative_to(destination_root)
        except ValueError as exc:
            raise CompressionError(f"Archive contains an unsafe path: {entry.path}") from exc
        if target.exists():
            raise CompressionError(f"Extraction would overwrite an existing item: {target}")


def _validate_destination(destination: Path, archive_format: ArchiveFormat) -> None:
    if destination.exists():
        raise CompressionError(f"Archive already exists: {destination}")
    expected = f".{archive_format.value}"
    if destination.suffix.lower() != expected:
        raise CompressionError(f"{archive_format.value} archives must use the {expected} extension.")


def _partial_archive_path(destination: Path) -> Path:
    return destination.with_name(f".{destination.stem}-{uuid.uuid4().hex}.partial{destination.suffix}")


def _raise_if_cancelled(token: CancellationToken | None) -> None:
    if token:
        token.raise_if_cancelled()


def _parse_7zip_listing(output: str) -> list[ArchiveEntry]:
    entries: list[ArchiveEntry] = []
    in_entries = False
    block: dict[str, str] = {}
    for raw_line in [*output.splitlines(), ""]:
        line = raw_line.rstrip("\r\n")
        if line.startswith("----------"):
            in_entries = True
            block = {}
            continue
        if not in_entries:
            continue
        if not line:
            if block.get("Path"):
                attributes = block.get("Attributes", "")
                folder = block.get("Folder", "-") == "+" or "D" in attributes[:2]
                entries.append(
                    ArchiveEntry(
                        path=_safe_member_path(block["Path"]),
                        size_bytes=int(block.get("Size", "0") or 0),
                        packed_bytes=int(block.get("Packed Size", "0") or 0),
                        modified_at=block.get("Modified", ""),
                        is_dir=folder,
                    )
                )
            block = {}
            continue
        if " = " in line:
            key, value = line.split(" = ", 1)
            block[key] = value
    return entries
