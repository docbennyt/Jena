from utils.disk import drive_usage


def test_drive_usage_shape():
    usage = drive_usage("C:\\")
    assert usage["total"] > 0
    assert usage["free"] >= 0
    assert 0 <= usage["percent_used"] <= 100
