from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from core.models import Finding, RiskLevel
from core.project_library import ProjectRecord, ProjectState
from utils.disk import drive_usage


class StorageState(str, Enum):
    HOT = "HOT"
    WARM = "WARM"
    COLD = "COLD"
    REGENERABLE = "REGENERABLE"
    TEMPORARY = "TEMPORARY"
    PROTECTED = "PROTECTED"
    UNKNOWN = "UNKNOWN"


class RecoveryConfidence(str, Enum):
    UNPROTECTED = "UNPROTECTED"
    REMOTE_UNKNOWN = "REMOTE_UNKNOWN"
    UPLOADED = "UPLOADED"
    REMOTE_CONFIRMED = "REMOTE_CONFIRMED"
    CHECKSUM_VERIFIED = "CHECKSUM_VERIFIED"
    RESTORE_TESTED = "RESTORE_TESTED"


@dataclass
class VolumeState:
    path: str
    total_bytes: int
    used_bytes: int
    free_bytes: int
    percent_used: float
    target_free_bytes: int

    @property
    def free_gap_bytes(self) -> int:
        return max(0, self.target_free_bytes - self.free_bytes)


@dataclass
class Opportunity:
    id: str
    title: str
    category: str
    space_gain_bytes: int
    user_effort: str
    risk: str
    why: str
    recovery_path: str
    confidence_percent: int
    finding_ids: list[str]


@dataclass(frozen=True)
class RegenerabilityEvidence:
    confidence: str
    why: list[str]
    recovery_path: str


@dataclass
class StorageOpportunity:
    id: str
    kind: str
    title: str
    description: str
    estimated_reclaim_bytes: int
    risk: str
    effort: str
    confidence: str
    why: list[str]
    recovery_path: str
    affected_item_ids: list[str]
    requirements: list[str]
    blocked_by: list[str]
    action_type: str

    @property
    def space_gain_bytes(self) -> int:
        return self.estimated_reclaim_bytes

    @property
    def user_effort(self) -> str:
        return self.effort

    @property
    def confidence_percent(self) -> int:
        return {"High": 92, "Medium": 70, "Low": 45}.get(self.confidence, 50)


@dataclass
class ProjectStorageTotals:
    total_bytes: int = 0
    source_bytes: int = 0
    dependencies_bytes: int = 0
    cache_bytes: int = 0
    asset_bytes: int = 0
    build_output_bytes: int = 0
    other_bytes: int = 0


@dataclass
class StorageModel:
    volume: VolumeState
    target_free_bytes: int
    gap_to_target_bytes: int
    known_project_storage_bytes: int
    regenerable_project_storage_bytes: int
    temporary_download_storage_bytes: int
    archive_storage_bytes: int
    review_required_storage_bytes: int
    protected_unknown_storage_bytes: int
    project_totals: ProjectStorageTotals


@dataclass(frozen=True)
class RecoveryPlanStep:
    opportunity: StorageOpportunity
    cumulative_reclaim_bytes: int


@dataclass
class RecoveryPlan:
    required_reclaim_bytes: int
    expected_reclaim_bytes: int
    expected_free_bytes: int
    target_met: bool
    steps: list[RecoveryPlanStep]


@dataclass
class WorkstationSummary:
    volume: VolumeState
    opportunities: list[Opportunity | StorageOpportunity]
    local_only_warnings: list[Finding]
    target_met: bool
    storage_model: StorageModel | None = None
    recovery_plan: RecoveryPlan | None = None


def classify_storage_state(finding: Finding) -> StorageState:
    if finding.risk_level == RiskLevel.DO_NOT_TOUCH:
        return StorageState.PROTECTED
    if finding.risk_level == RiskLevel.SAFE_TO_REGENERATE:
        return StorageState.REGENERABLE
    if any(tag in finding.tags for tag in {"old_installer", "temporary_file", "old_download"}):
        return StorageState.TEMPORARY
    if finding.duplicate_group_id:
        return StorageState.UNKNOWN
    return StorageState.UNKNOWN


def recovery_confidence_for(finding: Finding) -> RecoveryConfidence:
    if classify_storage_state(finding) == StorageState.REGENERABLE:
        return RecoveryConfidence.RESTORE_TESTED
    return RecoveryConfidence.UNPROTECTED


def build_volume_state(target_free_bytes: int, path: str = "C:\\") -> VolumeState:
    usage = drive_usage(path)
    return VolumeState(
        path=path,
        total_bytes=usage["total"],
        used_bytes=usage["used"],
        free_bytes=usage["free"],
        percent_used=usage["percent_used"],
        target_free_bytes=target_free_bytes,
    )


def build_opportunities(findings: list[Finding]) -> list[Opportunity]:
    opportunities: list[Opportunity] = []
    regenerable = [item for item in findings if classify_storage_state(item) == StorageState.REGENERABLE]
    temporary = [
        item for item in findings
        if classify_storage_state(item) == StorageState.TEMPORARY and item.risk_level != RiskLevel.DO_NOT_TOUCH
    ]
    duplicates = [item for item in findings if item.duplicate_group_id and item.risk_level != RiskLevel.DO_NOT_TOUCH]

    if regenerable:
        opportunities.append(_opportunity(
            "dev-caches",
            "Clean regenerable development data",
            "Development caches",
            regenerable,
            "One confirmation",
            "Very low",
            "These are dependency, cache, or build artifacts Jena classified as normally reproducible.",
            "Recreate with the project package manager or build tool.",
            92,
        ))
    if temporary:
        opportunities.append(_opportunity(
            "temporary-downloads",
            "Recycle temporary or expired downloads",
            "Downloads inbox",
            temporary,
            "One review",
            "Low",
            "These are installers, temporary files, or old Downloads inbox items.",
            "Restore from Windows Recycle Bin if needed.",
            78,
        ))
    if duplicates:
        opportunities.append(_opportunity(
            "duplicates",
            "Review duplicate copies",
            "Duplicates",
            duplicates,
            "Manual review",
            "Medium",
            "Duplicate groups have matching size and hash, but Jena will not choose personal copies automatically.",
            "Keep the best-located copy; restore from Recycle Bin if removed.",
            70,
        ))

    return sorted(opportunities, key=lambda item: item.space_gain_bytes, reverse=True)


def build_workstation_summary(
    findings: list[Finding],
    target_free_bytes: int,
    volume_path: str = "C:\\",
    projects: list[ProjectRecord] | None = None,
) -> WorkstationSummary:
    volume = build_volume_state(target_free_bytes, volume_path)
    projects = projects or []
    model = build_storage_model(findings, projects, target_free_bytes, volume_state=volume)
    storage_opportunities = build_storage_opportunities(model, projects, findings)
    plan = build_recovery_plan(storage_opportunities, volume.free_gap_bytes, current_free_bytes=volume.free_bytes)
    warnings = [
        item for item in findings
        if item.risk_level == RiskLevel.DO_NOT_TOUCH and recovery_confidence_for(item) == RecoveryConfidence.UNPROTECTED
    ][:5]
    return WorkstationSummary(
        volume=volume,
        opportunities=storage_opportunities or build_opportunities(findings),
        local_only_warnings=warnings,
        target_met=volume.free_gap_bytes == 0,
        storage_model=model,
        recovery_plan=plan,
    )


def _opportunity(
    opportunity_id: str,
    title: str,
    category: str,
    findings: list[Finding],
    effort: str,
    risk: str,
    why: str,
    recovery_path: str,
    confidence: int,
) -> Opportunity:
    return Opportunity(
        id=opportunity_id,
        title=title,
        category=category,
        space_gain_bytes=sum_unique_recoverable(findings),
        user_effort=effort,
        risk=risk,
        why=why,
        recovery_path=recovery_path,
        confidence_percent=confidence,
        finding_ids=[item.id for item in findings],
    )


def sum_unique_recoverable(findings: list[Finding]) -> int:
    seen: set[str] = set()
    total = 0
    for finding in findings:
        key = _canonical_identity(finding.canonical_path or finding.path)
        if key in seen:
            continue
        seen.add(key)
        total += finding.recoverable_bytes
    return total


def build_storage_model(
    findings: list[Finding],
    projects: list[ProjectRecord],
    target_free_bytes: int,
    volume_path: str = "C:\\",
    volume_state: VolumeState | None = None,
) -> StorageModel:
    volume = volume_state or build_volume_state(target_free_bytes, volume_path)
    project_totals = ProjectStorageTotals()
    for project in projects:
        breakdown = project.breakdown
        project_totals.total_bytes += project.size_bytes
        project_totals.source_bytes += breakdown.source_bytes
        project_totals.dependencies_bytes += breakdown.dependencies_bytes
        project_totals.cache_bytes += breakdown.caches_bytes
        project_totals.asset_bytes += breakdown.assets_bytes
        project_totals.build_output_bytes += breakdown.build_output_bytes
        project_totals.other_bytes += breakdown.other_bytes

    temporary = _sum_unique_matching(findings, lambda item: classify_storage_state(item) == StorageState.TEMPORARY)
    archive_storage = _sum_unique_matching(findings, lambda item: "archive_file" in item.tags or item.path.lower().endswith((".zip", ".7z", ".rar", ".tar", ".gz")))
    review_required = _sum_unique_matching(findings, lambda item: item.risk_level == RiskLevel.REVIEW_REQUIRED)
    protected = _sum_unique_matching(findings, lambda item: item.risk_level == RiskLevel.DO_NOT_TOUCH)

    return StorageModel(
        volume=volume,
        target_free_bytes=target_free_bytes,
        gap_to_target_bytes=max(0, target_free_bytes - volume.free_bytes),
        known_project_storage_bytes=project_totals.total_bytes,
        regenerable_project_storage_bytes=project_totals.dependencies_bytes + project_totals.cache_bytes,
        temporary_download_storage_bytes=temporary,
        archive_storage_bytes=archive_storage,
        review_required_storage_bytes=review_required,
        protected_unknown_storage_bytes=protected,
        project_totals=project_totals,
    )


def build_storage_opportunities(
    model: StorageModel,
    projects: list[ProjectRecord],
    findings: list[Finding],
) -> list[StorageOpportunity]:
    opportunities: list[StorageOpportunity] = []
    for project in projects:
        regenerable = project.breakdown.dependencies_bytes + project.breakdown.caches_bytes
        if regenerable:
            evidence = regenerability_evidence_for_project(Path(project.path))
            opportunities.append(StorageOpportunity(
                id=f"clean-dependencies-{project.name}",
                kind="project_regenerable",
                title=f"Clean {project.name} dependencies and caches",
                description=f"Remove reproducible dependency/cache data inside {project.name}.",
                estimated_reclaim_bytes=regenerable,
                risk="Low" if evidence.confidence in {"High", "Medium"} else "Needs Review",
                effort="Reinstall when needed",
                confidence=evidence.confidence,
                why=evidence.why + [f"{project.name} has {regenerable} bytes in dependencies/caches."],
                recovery_path=evidence.recovery_path,
                affected_item_ids=[project.project_id or project.path],
                requirements=[] if evidence.confidence != "Low" else ["Confirm dependency metadata before cleaning."],
                blocked_by=[],
                action_type="clean_regenerable",
            ))
        if project.state in {ProjectState.INACTIVE, ProjectState.PAUSED, ProjectState.ACTIVE, ProjectState.NEVER_ARCHIVE}:
            blocked = _archive_blockers(project)
            opportunities.append(StorageOpportunity(
                id=f"archive-project-{project.name}",
                kind="project_archive",
                title=f"Archive {project.name}",
                description=f"Create a verified Jena archive for {project.name}.",
                estimated_reclaim_bytes=project.size_bytes,
                risk="Moderate",
                effort="Choose archive destination",
                confidence="High" if project.state == ProjectState.INACTIVE else "Medium",
                why=(project.activity_evidence or [f"{project.name} is marked {project.state.value}."]),
                recovery_path="Restore from the verified Jena archive.",
                affected_item_ids=[project.project_id or project.path],
                requirements=["Verified archive must be created before moving original."],
                blocked_by=blocked,
                action_type="archive_project",
            ))

    temporary = [
        item for item in findings
        if classify_storage_state(item) == StorageState.TEMPORARY and item.risk_level != RiskLevel.DO_NOT_TOUCH
    ]
    if temporary:
        opportunities.append(StorageOpportunity(
            id="old-downloads",
            kind="downloads",
            title="Recycle old Downloads",
            description="Review old installers, archives, and temporary downloads.",
            estimated_reclaim_bytes=sum_unique_recoverable(temporary),
            risk="Needs Review",
            effort="Select files",
            confidence="Medium",
            why=["Downloads inbox items are old or temporary and should be reviewed."],
            recovery_path="Restore from Windows Recycle Bin if needed.",
            affected_item_ids=[item.id for item in temporary],
            requirements=["User selects approved files."],
            blocked_by=[],
            action_type="recycle_downloads",
        ))

    return sorted(opportunities, key=_opportunity_rank)


def build_recovery_plan(
    opportunities: list[StorageOpportunity],
    required_reclaim_bytes: int,
    current_free_bytes: int = 0,
) -> RecoveryPlan:
    steps: list[RecoveryPlanStep] = []
    recovered = 0
    for opportunity in sorted(opportunities, key=_opportunity_rank):
        if opportunity.blocked_by or opportunity.estimated_reclaim_bytes <= 0:
            continue
        if recovered >= required_reclaim_bytes:
            break
        recovered += opportunity.estimated_reclaim_bytes
        steps.append(RecoveryPlanStep(opportunity=opportunity, cumulative_reclaim_bytes=recovered))
    return RecoveryPlan(
        required_reclaim_bytes=required_reclaim_bytes,
        expected_reclaim_bytes=recovered,
        expected_free_bytes=current_free_bytes + recovered,
        target_met=recovered >= required_reclaim_bytes,
        steps=steps,
    )


def regenerability_evidence_for_project(project_path: Path) -> RegenerabilityEvidence:
    node_manifest = project_path / "package.json"
    node_locks = ["package-lock.json", "pnpm-lock.yaml", "yarn.lock", "bun.lock", "bun.lockb"]
    if node_manifest.exists():
        if any((project_path / name).exists() for name in node_locks):
            return RegenerabilityEvidence(
                confidence="High",
                why=["package.json and a lockfile are present."],
                recovery_path="Reinstall dependencies with npm ci, pnpm install --frozen-lockfile, yarn install --frozen-lockfile, or bun install.",
            )
        return RegenerabilityEvidence(
            confidence="Medium",
            why=["package.json is present, but no lockfile was found."],
            recovery_path="Reinstall dependencies with the project package manager.",
        )
    python_markers = ["pyproject.toml", "requirements.txt", "poetry.lock", "uv.lock", "Pipfile", "Pipfile.lock"]
    found_python = [name for name in python_markers if (project_path / name).exists()]
    if found_python:
        confidence = "High" if any(name.endswith(".lock") or name in {"requirements.txt", "uv.lock"} for name in found_python) else "Medium"
        return RegenerabilityEvidence(
            confidence=confidence,
            why=[f"Python dependency metadata found: {', '.join(found_python)}."],
            recovery_path="Recreate the virtual environment from the project dependency metadata.",
        )
    return RegenerabilityEvidence(
        confidence="Low",
        why=["No clear dependency metadata was found."],
        recovery_path="Confirm the project can recreate dependencies before cleaning them.",
    )


def _archive_blockers(project: ProjectRecord) -> list[str]:
    blockers: list[str] = []
    if project.state == ProjectState.NEVER_ARCHIVE or project.never_archive:
        blockers.append("Project is marked Never Archive.")
    if project.state == ProjectState.ACTIVE:
        blockers.append("Project is Active.")
    if project.pinned and project.state not in {ProjectState.NEVER_ARCHIVE, ProjectState.ACTIVE}:
        blockers.append("Project is pinned.")
    return blockers


def _opportunity_rank(opportunity: StorageOpportunity) -> tuple[int, int, int]:
    action_rank = {
        "clean_regenerable": 0,
        "recycle_downloads": 1,
        "review_duplicates": 2,
        "archive_project": 3,
    }.get(opportunity.action_type, 5)
    risk_rank = {"Low": 0, "Very low": 0, "Needs Review": 1, "Moderate": 2, "Medium": 2, "High": 3}.get(opportunity.risk, 2)
    confidence_rank = {"High": 0, "Medium": 1, "Low": 2}.get(opportunity.confidence, 1)
    blocked_rank = 1 if opportunity.blocked_by else 0
    return (blocked_rank, action_rank + risk_rank, confidence_rank, -opportunity.estimated_reclaim_bytes)


def _sum_unique_matching(findings: list[Finding], predicate) -> int:
    seen: set[str] = set()
    total = 0
    for finding in findings:
        if not predicate(finding):
            continue
        key = _canonical_identity(finding.canonical_path or finding.path)
        if key in seen:
            continue
        seen.add(key)
        total += finding.size_bytes
    return total


def _canonical_identity(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))
