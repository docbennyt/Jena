from pathlib import Path

from core.models import Finding, RiskLevel
from core.operations import move_to_review, recycle_findings, restore_from_manifest


def make_finding(path: Path, risk: RiskLevel = RiskLevel.LIKELY_DISPOSABLE) -> Finding:
    return Finding(
        id="id",
        path=str(path),
        name=path.name,
        item_type="file",
        size_bytes=path.stat().st_size,
        modified_at=path.stat().st_mtime,
        category="temporary_file",
        reason="test",
        recommended_action="test",
        tags=["temporary_file"],
        reasons=["test"],
        recommendations=["test"],
        canonical_path=str(path).lower(),
        risk_level=risk,
        recoverable_bytes=path.stat().st_size if risk != RiskLevel.DO_NOT_TOUCH else 0,
        source_scope="test",
    )


def test_dry_run_does_not_move(tmp_path: Path):
    source = tmp_path / "old.tmp"
    source.write_text("temporary")
    manifest = move_to_review([make_finding(source)], execute=False, review_root=tmp_path / "review")

    assert source.exists()
    assert manifest["items"][0]["status"] == "DRY_RUN"


def test_do_not_touch_is_skipped(tmp_path: Path):
    source = tmp_path / "assignment.docx"
    source.write_text("important")
    manifest = move_to_review([make_finding(source, RiskLevel.DO_NOT_TOUCH)], execute=True, review_root=tmp_path / "review")

    assert source.exists()
    assert manifest["items"][0]["status"] == "SKIPPED"


def test_move_and_restore(tmp_path: Path):
    source = tmp_path / "old.tmp"
    source.write_text("temporary")
    review = tmp_path / "review"
    manifest = move_to_review([make_finding(source)], execute=True, review_root=review)
    manifest_path = Path(manifest["manifest_path"])

    assert not source.exists()
    assert Path(manifest["items"][0]["destination"]).exists()

    result = restore_from_manifest(manifest_path)

    assert source.exists()
    assert result["results"][0]["status"] == "RESTORED"


def test_recycle_uses_injected_recycle_sender(tmp_path: Path):
    source = tmp_path / "old.tmp"
    source.write_text("temporary")
    calls = []

    manifest = recycle_findings([make_finding(source)], sender=lambda path: calls.append(path))

    assert calls == [str(source)]
    assert manifest["operation"] == "recycle"
    assert manifest["items"][0]["status"] == "RECYCLED"


def test_recycle_skips_protected_items(tmp_path: Path):
    source = tmp_path / "assignment.docx"
    source.write_text("important")
    calls = []

    manifest = recycle_findings([make_finding(source, RiskLevel.DO_NOT_TOUCH)], sender=lambda path: calls.append(path))

    assert calls == []
    assert manifest["items"][0]["status"] == "SKIPPED"
