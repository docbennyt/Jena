from __future__ import annotations

import os
import subprocess
from pathlib import Path
from zipfile import ZipFile

import pytest

from core.compression import (
    ArchiveFormat,
    BuiltinZipCompressionService,
    CompressionError,
    SevenZipCompressionService,
    find_7zip_executable,
)
from core.tasks import CancellationToken, TaskCancelled


def _make_source(root: Path) -> list[str]:
    files = {
        "src/app.ts": "export const message = 'Jena';\n",
        "docs/read me.md": "Recovery matters.\n",
        "unicode/notes-Ω.txt": "offline and verified\n",
    }
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return list(files)


def test_builtin_zip_service_round_trips_and_lists_entries(tmp_path: Path):
    source = tmp_path / "source"
    members = _make_source(source)
    archive = tmp_path / "archives" / "project.zip"
    extracted = tmp_path / "extracted"
    service = BuiltinZipCompressionService()

    result = service.create(source, members, archive, ArchiveFormat.ZIP)
    entries = service.list_entries(archive)

    assert result.engine == "python-zip"
    assert result.archive_format == ArchiveFormat.ZIP
    assert {entry.path for entry in entries if not entry.is_dir} == set(members)
    assert service.test_archive(archive)

    service.extract(archive, extracted)
    for relative in members:
        assert (extracted / relative).read_bytes() == (source / relative).read_bytes()


def test_builtin_zip_service_rejects_unsafe_archive_members(tmp_path: Path):
    archive = tmp_path / "unsafe.zip"
    with ZipFile(archive, "w") as handle:
        handle.writestr("../outside.txt", "no")

    service = BuiltinZipCompressionService()

    with pytest.raises(CompressionError, match="unsafe path"):
        service.list_entries(archive)
    with pytest.raises(CompressionError, match="unsafe path"):
        service.extract(archive, tmp_path / "extract")


def test_cancelled_compression_stops_before_work(tmp_path: Path):
    source = tmp_path / "source"
    members = _make_source(source)
    token = CancellationToken()
    token.cancel()

    with pytest.raises(TaskCancelled):
        BuiltinZipCompressionService().create(
            source,
            members,
            tmp_path / "cancelled.zip",
            ArchiveFormat.ZIP,
            token=token,
        )


@pytest.mark.skipif(os.name != "nt", reason="Jena's packaged engine target is Windows")
def test_real_7zip_service_creates_tests_lists_and_extracts_zip_and_7z(tmp_path: Path):
    executable = find_7zip_executable()
    if executable is None:
        pytest.skip("7-Zip is not installed or bundled")
    source = tmp_path / "source tree"
    members = _make_source(source)
    service = SevenZipCompressionService(executable)

    for archive_format, suffix in [(ArchiveFormat.ZIP, ".zip"), (ArchiveFormat.SEVEN_ZIP, ".7z")]:
        archive = tmp_path / "archives" / f"project{suffix}"
        extracted = tmp_path / f"extracted-{archive_format.value}"
        result = service.create(source, members, archive, archive_format)

        assert result.engine.startswith("7-Zip ")
        assert result.archive_format == archive_format
        assert service.test_archive(archive)
        assert {entry.path for entry in service.list_entries(archive) if not entry.is_dir} == set(members)

        service.extract(archive, extracted)
        for relative in members:
            assert (extracted / relative).read_bytes() == (source / relative).read_bytes()


def test_seven_zip_processes_are_started_without_console_windows(monkeypatch, tmp_path: Path):
    captured: dict = {}

    class FinishedProcess:
        returncode = 0

        def communicate(self, timeout=None):
            return "", ""

        def terminate(self):
            return None

        def kill(self):
            return None

    def fake_popen(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return FinishedProcess()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    service = SevenZipCompressionService(tmp_path / "7z.exe")
    archive = tmp_path / "archive.zip"

    assert service.test_archive(archive)
    assert captured["kwargs"]["shell"] is False
    if os.name == "nt":
        assert captured["kwargs"]["creationflags"] & subprocess.CREATE_NO_WINDOW

