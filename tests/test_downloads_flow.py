import os
import time
from pathlib import Path

from core.downloads import categorize_downloads
from core.operations import recycle_findings


def test_download_categories_and_recycle_sender_fixture(tmp_path: Path):
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    installer = downloads / "setup-old.exe"
    archive = downloads / "backup.zip"
    image = downloads / "screen.png"
    for path in [installer, archive, image]:
        path.write_text("fixture", encoding="utf-8")
        old = time.time() - (40 * 86400)
        os.utime(path, (old, old))

    categories = categorize_downloads(downloads, age_days=30)
    by_name = {category.name: category for category in categories}

    assert by_name["Installers"].count == 1
    assert by_name["Archives"].count == 1
    assert by_name["Images"].count == 1

    sent: list[str] = []
    manifest = recycle_findings(by_name["Installers"].findings, sender=sent.append)

    assert manifest["items"][0]["status"] == "RECYCLED"
    assert sent == [str(installer)]
