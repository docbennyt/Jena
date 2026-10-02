from pathlib import Path

from selftest import run_self_test, verify_self_test_persistence


def test_selftest_persistence_can_be_verified_from_existing_fixture(tmp_path: Path):
    evidence = tmp_path / "evidence.json"
    first_run = run_self_test(evidence)

    assert first_run["compression_service"]["zip"]["verified"] is True
    assert first_run["compression_service"]["zip"]["restored_hashes_equal"] is True
    assert first_run["compression_service"]["seven_zip"]["verified"] is True
    assert first_run["compression_service"]["seven_zip"]["restored_hashes_equal"] is True
    assert first_run["compression_service"]["seven_zip"]["engine"].startswith("7-Zip 26.03")
    assert first_run["archive_container_preview"]["kind"] == "archive"
    assert first_run["archive_container_preview"]["file_count"] > 0
    assert first_run["archive_container_preview"]["has_navigable_entries"] is True

    restart_evidence = tmp_path / "restart.json"
    result = verify_self_test_persistence(tmp_path / "jena-self-test-fixture", restart_evidence)

    assert result["persistence_after_process_restart"] == "Archived"
    assert result["project_detection_after_restart"]["names"] == ["Old Portfolio"]
    assert restart_evidence.exists()
