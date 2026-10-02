from pathlib import Path

from core.classifiers import classify_file
from core.models import RiskLevel


def test_documents_are_protected():
    assert classify_file(Path("assignment.docx"), "old_download") == RiskLevel.DO_NOT_TOUCH


def test_installers_are_likely_disposable():
    assert classify_file(Path("setup.exe"), "old_installer") == RiskLevel.LIKELY_DISPOSABLE


def test_archives_need_review():
    assert classify_file(Path("project.zip"), "archive_file") == RiskLevel.REVIEW_REQUIRED
