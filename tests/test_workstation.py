from pathlib import Path

from core.models import Finding, RiskLevel
from core.project_library import ProjectBreakdown, ProjectRecord, ProjectState
from core.workstation import (
    RecoveryConfidence,
    RecoveryPlan,
    StorageState,
    build_opportunities,
    build_recovery_plan,
    build_storage_model,
    build_storage_opportunities,
    classify_storage_state,
    regenerability_evidence_for_project,
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


def project_record(root: Path, name: str, state: ProjectState, breakdown: ProjectBreakdown) -> ProjectRecord:
    return ProjectRecord(
        name=name,
        path=str(root),
        project_type="Node",
        size_bytes=breakdown.total_bytes,
        modified_at=0,
        state=state,
        breakdown=breakdown,
        project_id=f"proj-{name}",
        library_id="lib-test",
        canonical_root_path=str(root).lower(),
        display_name=name,
        detected_markers=["package.json"],
        activity_evidence=["No meaningful source change for 142 days."],
    )


def test_storage_model_counts_unique_finding_bytes_once_and_project_buckets(tmp_path: Path):
    project = project_record(
        tmp_path / "HIT-ASA",
        "HIT-ASA",
        ProjectState.INACTIVE,
        ProjectBreakdown(source_bytes=180, dependencies_bytes=2300, caches_bytes=610, assets_bytes=310, build_output_bytes=40, other_bytes=20),
    )
    one = finding("C:/Downloads/setup.exe", 12, RiskLevel.LIKELY_DISPOSABLE, ["old_download"])
    two = finding("c:/downloads/SETUP.exe", 12, RiskLevel.LIKELY_DISPOSABLE, ["old_installer"])
    two.canonical_path = one.canonical_path

    model = build_storage_model([one, two], [project], 20_000, volume_state=None)

    assert model.known_project_storage_bytes == 3460
    assert model.regenerable_project_storage_bytes == 2910
    assert model.temporary_download_storage_bytes == 12
    assert model.review_required_storage_bytes == 0


def test_regenerability_confidence_uses_dependency_metadata(tmp_path: Path):
    project = tmp_path / "NodeApp"
    (project / "node_modules").mkdir(parents=True)
    (project / "package.json").write_text("{}")
    (project / "package-lock.json").write_text("{}")

    evidence = regenerability_evidence_for_project(project)

    assert evidence.confidence == "High"
    assert "npm install" in evidence.recovery_path


def test_storage_opportunities_respect_policies_and_explain_recovery(tmp_path: Path):
    active_root = tmp_path / "ActiveApp"
    inactive_root = tmp_path / "OldPortfolio"
    protected_root = tmp_path / "Protected"
    for root in [active_root, inactive_root, protected_root]:
        root.mkdir(parents=True)
        (root / "package.json").write_text("{}")
        (root / "package-lock.json").write_text("{}")

    active = project_record(active_root, "ActiveApp", ProjectState.ACTIVE, ProjectBreakdown(source_bytes=100, dependencies_bytes=500))
    inactive = project_record(inactive_root, "OldPortfolio", ProjectState.INACTIVE, ProjectBreakdown(source_bytes=400, dependencies_bytes=1000, caches_bytes=250))
    protected = project_record(protected_root, "Protected", ProjectState.NEVER_ARCHIVE, ProjectBreakdown(source_bytes=400, dependencies_bytes=1000))

    opportunities = build_storage_opportunities(build_storage_model([], [active, inactive, protected], 0, volume_state=None), [active, inactive, protected], [])
    by_id = {item.id: item for item in opportunities}

    assert "archive-project-OldPortfolio" in by_id
    assert by_id["archive-project-Protected"].blocked_by == ["Project is marked Never Archive."]
    assert by_id["archive-project-ActiveApp"].blocked_by == ["Project is Active."]
    assert by_id["clean-dependencies-OldPortfolio"].estimated_reclaim_bytes == 1250
    assert "reinstall dependencies" in by_id["clean-dependencies-OldPortfolio"].recovery_path.lower()
    assert all("source" not in item.action_type for item in opportunities)


def test_recovery_plan_reaches_target_without_double_counting():
    opportunities = [
        _storage_opportunity("cache", 500, risk="Low", confidence="High", action_type="clean_regenerable"),
        _storage_opportunity("downloads", 250, risk="Needs Review", confidence="Medium", action_type="recycle_downloads"),
        _storage_opportunity("archive", 400, risk="Moderate", confidence="High", action_type="archive_project"),
    ]

    plan = build_recovery_plan(opportunities, required_reclaim_bytes=700)

    assert isinstance(plan, RecoveryPlan)
    assert [step.opportunity.id for step in plan.steps] == ["cache", "downloads"]
    assert plan.expected_reclaim_bytes == 750
    assert plan.target_met is True


def test_recovery_plan_reports_insufficient_and_skips_blocked():
    opportunities = [
        _storage_opportunity("blocked", 10_000, blocked_by=["Project is marked Never Archive."]),
        _storage_opportunity("small", 100, risk="Low", confidence="High", action_type="clean_regenerable"),
    ]

    plan = build_recovery_plan(opportunities, required_reclaim_bytes=500)

    assert [step.opportunity.id for step in plan.steps] == ["small"]
    assert plan.expected_reclaim_bytes == 100
    assert plan.target_met is False


def _storage_opportunity(
    opportunity_id: str,
    reclaim: int,
    risk: str = "Low",
    confidence: str = "Medium",
    action_type: str = "review",
    blocked_by: list[str] | None = None,
):
    from core.workstation import StorageOpportunity

    return StorageOpportunity(
        id=opportunity_id,
        kind="test",
        title=opportunity_id,
        description="test",
        estimated_reclaim_bytes=reclaim,
        risk=risk,
        effort="One review",
        confidence=confidence,
        why=["test"],
        recovery_path="test",
        affected_item_ids=[opportunity_id],
        requirements=[],
        blocked_by=blocked_by or [],
        action_type=action_type,
    )
