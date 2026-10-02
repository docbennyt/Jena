import os
import time
from pathlib import Path

from core.models import RiskLevel
from core.scanner import ScanOptions, Scanner


def test_scanner_finds_cache_and_protects_documents(tmp_path: Path):
    downloads = tmp_path / "Downloads"
    cache = downloads / "project" / "node_modules"
    cache.mkdir(parents=True)
    document = downloads / "assignment.pdf"
    document.write_text("important")
    old_time = time.time() - 40 * 24 * 60 * 60
    os.utime(document, (old_time, old_time))
    (cache / "cache.bin").write_text("cache")
    (downloads / "setup.exe").write_text("installer")

    result = Scanner(ScanOptions(large_file_mb=999, large_folder_mb=999, include_duplicates=False)).scan(downloads, "Downloads")
    by_path = {Path(f.path).name: f for f in result.findings}

    assert "node_modules" in by_path
    assert by_path["node_modules"].risk_level == RiskLevel.SAFE_TO_REGENERATE
    assert by_path["assignment.pdf"].risk_level == RiskLevel.DO_NOT_TOUCH
    assert by_path["setup.exe"].risk_level == RiskLevel.LIKELY_DISPOSABLE


def test_one_file_has_many_tags_in_one_finding(tmp_path: Path):
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    archive = downloads / "archive.zip"
    archive.write_bytes(b"x" * 1024)
    old_time = time.time() - 40 * 24 * 60 * 60
    os.utime(archive, (old_time, old_time))

    result = Scanner(ScanOptions(large_file_mb=0, large_folder_mb=999, include_duplicates=False)).scan(downloads, "Downloads")
    archive_findings = [finding for finding in result.findings if finding.path_obj == archive]

    assert len(archive_findings) == 1
    assert {"large_file", "old_download", "archive_file"}.issubset(set(archive_findings[0].tags))
