from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from core.models import Finding, RiskLevel
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


@dataclass
class WorkstationSummary:
    volume: VolumeState
    opportunities: list[Opportunity]
    local_only_warnings: list[Finding]
    target_met: bool


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


def build_workstation_summary(findings: list[Finding], target_free_bytes: int, volume_path: str = "C:\\") -> WorkstationSummary:
    volume = build_volume_state(target_free_bytes, volume_path)
    warnings = [
        item for item in findings
        if item.risk_level == RiskLevel.DO_NOT_TOUCH and recovery_confidence_for(item) == RecoveryConfidence.UNPROTECTED
    ][:5]
    return WorkstationSummary(
        volume=volume,
        opportunities=build_opportunities(findings),
        local_only_warnings=warnings,
        target_met=volume.free_gap_bytes == 0,
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
        key = finding.canonical_path or finding.path
        if key in seen:
            continue
        seen.add(key)
        total += finding.recoverable_bytes
    return total
