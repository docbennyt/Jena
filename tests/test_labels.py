from core.models import RiskLevel
from utils.labels import risk_label, tag_label, tags_label


def test_internal_labels_are_user_friendly():
    assert risk_label(RiskLevel.DO_NOT_TOUCH) == "Protected"
    assert risk_label(RiskLevel.REVIEW_REQUIRED) == "Needs Review"
    assert tag_label("archive_file") == "Archive"
    assert tags_label(["old_download", "archive_file"]) == "Old Download, Archive"
