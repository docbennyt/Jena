from pathlib import Path

from selftest import run_project_registry_test, run_self_test, verify_project_registry_persistence, verify_self_test_persistence


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
    assert restart_evidence.exists()


def test_project_registry_selftest_records_required_evidence(tmp_path: Path):
    evidence = tmp_path / "project-registry.json"
    result = run_project_registry_test(evidence, large_entries=200)

    assert result["fixture_a"]["false_projects_absent"] is True
    assert result["fixture_b_monorepo"]["one_primary_project"] is True
    assert result["fixture_c_python"]["virtualenv_packages_absent"] is True
    assert result["fixture_d_large_library"]["streamed_results"] == 4
    assert result["state_persistence_source"] == {
        "HIT-ASA": "Active",
        "Workspace": "Paused",
        "PythonProject": "Never Archive",
    }
    assert result["size_breakdown"]["dependency_bytes"] > 0
    assert result["activity_reasoning"]

    restart = verify_project_registry_persistence(Path(result["fixture_root"]), tmp_path / "registry-restart.json")

    assert restart["state_persistence_after_restart"] == result["state_persistence_source"]
