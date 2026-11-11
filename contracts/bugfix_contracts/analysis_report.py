from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from bugfix_contracts.common import CONTRACT_SCHEMA_VERSION, Confidence

ANALYSIS_REPORT_SCHEMA_VERSION = CONTRACT_SCHEMA_VERSION

TicketOutcome = Literal[
    "patch_ready",
    "plan_only",
    "needs_test_env",
    "needs_ticket_info",
    "needs_design_input",
    "not_code",
    "config_or_dependency",
    "unlocalized",
    "other_blocked",
]


class TicketBlockers(BaseModel):
    kind: str = Field(min_length=1)
    detail: str = ""
    missingInfo: Optional[list[str]] = None
    envNeeds: Optional[list[str]] = None


class TicketSlice(BaseModel):
    title: Optional[str] = None
    testModule: Optional[str] = None
    titleTag: Optional[str] = None
    intent: Optional[str] = None
    pool: Optional[str] = None
    observed: Optional[str] = None
    expected: Optional[str] = None
    steps: Optional[str] = None
    status: Optional[str] = None
    severity: Optional[str] = None
    reasonCode: Optional[str] = None
    reasonDetail: Optional[str] = None


class LocCandidate(BaseModel):
    repoPath: str = "."
    path: str
    symbol: Optional[str] = None
    why: Optional[str] = None
    source: Optional[str] = None


class Localization(BaseModel):
    candidates: list[LocCandidate] = Field(default_factory=list)
    notes: Optional[str] = None
    degradedSearch: Optional[bool] = None


class RootCause(BaseModel):
    summary: str = ""
    ruledOut: list[str] = Field(default_factory=list)
    openQuestions: list[str] = Field(default_factory=list)


class ProposedFix(BaseModel):
    summary: str = Field(min_length=1)
    steps: list[str] = Field(default_factory=list)
    targetFiles: Optional[list[str]] = None


class PatchInfo(BaseModel):
    path: Optional[str] = None
    summary: Optional[str] = None


class SuggestedVerify(BaseModel):
    steps: list[str] = Field(default_factory=list)
    executed: bool = False


class TicketReport(BaseModel):
    model_config = ConfigDict(extra="ignore")

    defectId: str = Field(min_length=1)
    ticket: TicketSlice = Field(default_factory=TicketSlice)
    localization: Localization = Field(default_factory=Localization)
    rootCause: RootCause = Field(default_factory=RootCause)
    outcome: TicketOutcome
    proposedFix: Optional[ProposedFix] = None
    patch: Optional[PatchInfo] = None
    blockers: Optional[TicketBlockers] = None
    suggestedVerify: SuggestedVerify = Field(default_factory=SuggestedVerify)
    confidence: Confidence = "low"
    verifyStatus: Literal["passed", "failed", "skipped"] = "skipped"

    @model_validator(mode="after")
    def _outcome_body(self) -> TicketReport:
        actionable = self.outcome in ("patch_ready", "plan_only")
        if actionable and (self.proposedFix is None or not self.proposedFix.summary):
            raise ValueError(f"{self.outcome} requires proposedFix.summary")
        if not actionable and self.blockers is None:
            raise ValueError(f"{self.outcome} requires blockers")
        return self


class ReportSummary(BaseModel):
    total: int = Field(ge=0)
    byOutcome: dict[str, int] = Field(default_factory=dict)


class AnalysisReport(BaseModel):
    model_config = ConfigDict(extra="ignore")

    schemaVersion: str
    productLine: str = Field(min_length=1)
    workDir: str = Field(min_length=1)
    generatedAt: str = Field(min_length=1)
    openMr: bool = False
    applyFix: bool = False
    mrUrl: Optional[str] = None
    integrateMode: Literal["none", "single_mr"] = "none"
    summary: Optional[ReportSummary] = None
    boundSkills: list[str] = Field(default_factory=list)
    tickets: list[TicketReport]


def validate_analysis_report(data: Any) -> AnalysisReport:
    return AnalysisReport.model_validate(data)


def safe_validate_analysis_report(data: Any) -> tuple[bool, AnalysisReport | str]:
    try:
        return True, AnalysisReport.model_validate(data)
    except Exception as e:  # noqa: BLE001
        return False, str(e)
