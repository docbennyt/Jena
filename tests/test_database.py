from pathlib import Path

from core.scanner import ScanOptions, Scanner
from storage.database import Database
from storage.settings import Settings


def test_database_saves_latest_findings(tmp_path: Path):
    root = tmp_path / "Downloads"
    root.mkdir()
    (root / "setup.exe").write_text("installer")
    result = Scanner(ScanOptions(include_duplicates=False)).scan(root, "Downloads")
    db = Database(tmp_path / "storagepilot.db")

    db.save_scan(result)

    assert len(db.latest_findings()) == 1
    assert db.dashboard_metrics()["finding_count"] == 1
    db.close()


def test_recoverable_counts_physical_item_once(tmp_path: Path):
    root = tmp_path / "Downloads"
    root.mkdir()
    archive = root / "archive.zip"
    archive.write_bytes(b"x" * 100)
    result = Scanner(ScanOptions(large_file_mb=0, include_duplicates=False)).scan(root, "Downloads")
    db = Database(tmp_path / "storagepilot.db")

    db.save_scan(result)

    assert len(db.latest_findings()) == 1
    assert db.dashboard_metrics()["recoverable"] == 100
    db.close()


def test_duplicate_space_counts_only_extra_copies(tmp_path: Path):
    root = tmp_path / "Downloads"
    root.mkdir()
    for name in ["a.bin", "b.bin", "c.bin"]:
        (root / name).write_bytes(b"same content")
    result = Scanner(ScanOptions(large_file_mb=999, duplicate_min_mb=0)).scan(root, "Downloads")
    db = Database(tmp_path / "storagepilot.db")

    db.save_scan(result)

    assert db.dashboard_metrics()["duplicate"] == 2 * len(b"same content")
    db.close()


def test_settings_persist_target_free_space(tmp_path: Path):
    settings_path = tmp_path / "settings.json"
    settings = Settings(settings_path)
    settings.set("target_free_gb", 32)

    reloaded = Settings(settings_path)

    assert reloaded.get("target_free_gb") == 32


def test_database_migrates_project_registry_tables(tmp_path: Path):
    db = Database(tmp_path / "storagepilot.db")

    tables = {
        row[0]
        for row in db.connection.execute(
            "select name from sqlite_master where type = 'table' and name in ('project_libraries', 'project_registry')"
        ).fetchall()
    }

    assert tables == {"project_libraries", "project_registry"}
    db.close()
