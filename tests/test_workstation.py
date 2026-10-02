from pathlib import Path

from core.models import Finding, RiskLevel
from core.workstation import (
    RecoveryConfidence,
    StorageState,
    build_opportunities,
    classify_storage_state,
    recovery_confidence_for,
    sum_unique_recoverable,
)


def finding(path: str, size: int, risk: RiskLevel, tags: list[str], recoverable: int | None = None) -> Finding:
    return Finding(
        id=path,
        path=path,
        name=Path(path).name,
        item_type="file",
        size_bytes=size,
        modified_at=0,
        category=tags[0],
        reason="test",
        recommended_action="test",
        tags=tags,
        reasons=["test"],
        recommendations=["test"],
        canonical_path=path.lower(),
        risk_level=risk,
        recoverable_bytes=size if recoverable is None and risk != RiskLevel.DO_NOT_TOUCH else (recoverable or 0),
        source_scope="test",
    )


def test_storage_state_and_recovery_confidence_for_regenerable():
    item = finding("C:/p/node_modules", 100, RiskLevel.SAFE_TO_REGENERATE, ["node_modules"])

    assert classify_storage_state(item) == StorageState.REGENERABLE
    assert recovery_confidence_for(item) == RecoveryConfidence.RESTORE_TESTED


def test_storage_state_for_protected_local_only():
    item = finding("C:/school/assignment.pdf", 100, RiskLevel.DO_NOT_TOUCH, ["old_download"], recoverable=0)

    assert classify_storage_state(item) == StorageState.PROTECTED
    assert recovery_confidence_for(item) == RecoveryConfidence.UNPROTECTED


def test_sum_unique_recoverable_counts_canonical_path_once():
    one = finding("C:/Downloads/archive.zip", 100, RiskLevel.LIKELY_DISPOSABLE, ["old_download"])
    two = finding("c:/downloads/ARCHIVE.zip", 100, RiskLevel.LIKELY_DISPOSABLE, ["archive_file"])
    two.canonical_path = one.canonical_path

    assert sum_unique_recoverable([one, two]) == 100


def test_build_opportunities_orders_by_space_gain():
    cache = finding("C:/p/node_modules", 500, RiskLevel.SAFE_TO_REGENERATE, ["node_modules"])
    installer = finding("C:/Downloads/setup.exe", 100, RiskLevel.LIKELY_DISPOSABLE, ["old_installer"])

    opportunities = build_opportunities([installer, cache])

    assert [item.id for item in opportunities] == ["dev-caches", "temporary-downloads"]
    assert opportunities[0].space_gain_bytes == 500
    assert "Recreate" in opportunities[0].recovery_path
