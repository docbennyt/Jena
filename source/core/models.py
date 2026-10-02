from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional


class RiskLevel(str, Enum):
    SAFE_TO_REGENERATE = "SAFE_TO_REGENERATE"
    LIKELY_DISPOSABLE = "LIKELY_DISPOSABLE"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    DO_NOT_TOUCH = "DO_NOT_TOUCH"


@dataclass
class Finding:
    id: str
    path: str
    name: str
    item_type: str
    size_bytes: int
    modified_at: float
    category: str
    reason: str
    recommended_action: str
    tags: list[str]
    reasons: list[str]
    recommendations: list[str]
    canonical_path: str
    risk_level: RiskLevel
    recoverable_bytes: int
    source_scope: str
    project_root: Optional[str] = None
    is_git_repository: bool = False
    is_inside_git_repository: bool = False
    duplicate_group_id: Optional[str] = None
    selected: bool = False

    @property
    def path_obj(self) -> Path:
        return Path(self.path)

    def add_classification(self, tag: str, reason: str, recommendation: str, risk_level: RiskLevel, recoverable_bytes: int) -> None:
        if tag not in self.tags:
            self.tags.append(tag)
        if reason not in self.reasons:
            self.reasons.append(reason)
        if recommendation not in self.recommendations:
            self.recommendations.append(recommendation)
        self.category = self.tags[0] if self.tags else self.category
        self.reason = "; ".join(self.reasons)
        self.recommended_action = "; ".join(self.recommendations)
        if _risk_rank(risk_level) > _risk_rank(self.risk_level):
            self.risk_level = risk_level
        self.recoverable_bytes = recoverable_bytes if self.risk_level != RiskLevel.DO_NOT_TOUCH else 0


def _risk_rank(risk: RiskLevel) -> int:
    return {
        RiskLevel.SAFE_TO_REGENERATE: 0,
        RiskLevel.LIKELY_DISPOSABLE: 1,
        RiskLevel.REVIEW_REQUIRED: 2,
        RiskLevel.DO_NOT_TOUCH: 3,
    }[risk]


@dataclass
class ProjectInfo:
    path: str
    name: str
    size_bytes: int
    modified_at: float
    project_type: str
    git_repository: bool
    regenerable_bytes: int = 0


@dataclass
class ScanError:
    path: str
    message: str


@dataclass
class ScanResult:
    source_scope: str
    root: str
    findings: list[Finding]
    projects: list[ProjectInfo]
    errors: list[ScanError]
    scanned_items: int
    scanned_bytes: int
