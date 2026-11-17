"""Agent-3 修复闭环契约（schema 0.4.0）。旧 Agent 产物明确拒绝，不静默填充证据。"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

REPAIR_SCHEMA_VERSION = "0.4.0"

ExecutionStatus = Literal[
    "queued", "running", "completed", "failed", "interrupted", "skipped"
]
ResolutionStatus = Literal[
    "patch_produced",
    "analysis_only",
    "needs_information",
    "needs_environment",
    "needs_business_decision",
    "external_component",
    "unlocalized",
    "incomplete",
    "excluded",
]
PatchDelivery = Literal["none", "candidate", "diagnostic", "superseded", "withdrawn"]
CheckResult = Literal["passed", "failed", "blocked", "not_run", "not_applicable"]
UserApplication = Literal[
    "unknown", "not_applied", "applied", "partially_applied", "modified", "discarded"
]
UserAcceptance = Literal[
    "pending", "accepted", "partially_resolved", "rejected", "regression_reported"
]
EvidenceValidity = Literal["valid", "pending_review", "invalid", "historical"]
EvidenceCategory = Literal[
    "user_statement", "code_observation", "tool_result", "model_inference"
]
InvestigationStatus = Literal[
    "not_investigated", "search_draft", "partial", "complete", "failed"
]
HypothesisStatus = Literal["proposed", "supported", "refuted", "superseded"]
ScopeStatus = Literal[
    "in_scope", "external_confirmed", "external_suspected", "unknown"
]
PatchFileKind = Literal["add", "modify", "delete", "rename"]
QuestionCategory = Literal["product", "fact", "implementation", "follow_up"]
QuestionStatus = Literal["open", "answered", "resolved", "reopened"]
ResolutionSource = Literal["user_answer", "agent_decision", "existing_rule"]
ResolutionDisposition = Literal["resolved", "insufficient", "conflicting"]


class Evidence(BaseModel):
    model_config = ConfigDict(extra="ignore")

    evidenceId: str = Field(min_length=1)
    category: EvidenceCategory
    source: str = ""
    observedAt: str = ""
    summary: str = ""
    persistentRef: Optional[str] = None
    repoId: Optional[str] = None
    revision: Optional[str] = None
    path: Optional[str] = None
    validity: EvidenceValidity = "pending_review"


class Hypothesis(BaseModel):
    model_config = ConfigDict(extra="ignore")

    claim: str = Field(min_length=1)
    status: HypothesisStatus = "proposed"
    supportRefs: list[str] = Field(default_factory=list)
    contraRefs: list[str] = Field(default_factory=list)
    openChecks: list[str] = Field(default_factory=list)
    changeReason: Optional[str] = None


class Claim(BaseModel):
    claimId: str
    statement: str
    role: Literal["fact", "hypothesis", "conclusion"] = "hypothesis"
    status: Literal["supported", "conditional", "unverified", "refuted"] = "unverified"
    evidenceRefs: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)

class Question(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    kind: Literal["blocking", "choice", "verification", "follow_up"]
    reason: str
    relatedClaimIds: list[str] = Field(default_factory=list)
    requestedEvidence: str = ""
    category: QuestionCategory = "fact"
    status: QuestionStatus = "open"
    predecessorId: Optional[str] = None
    newEvidenceRefs: list[str] = Field(default_factory=list)


class QuestionAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    questionId: str = Field(min_length=1)
    text: str = ""
    answerRevisionId: Optional[str] = None
    source: str = "user"


class QuestionResolution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    questionId: str = Field(min_length=1)
    resolutionSource: ResolutionSource
    revisionId: str = Field(min_length=1)
    answerRevisionId: Optional[str] = None
    targetDigest: str = Field(min_length=1)
    disposition: ResolutionDisposition
    resolutionSummary: str = Field(min_length=1)
    evidenceRefs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _user_answer_has_revision(self) -> QuestionResolution:
        if self.resolutionSource == "user_answer" and not self.answerRevisionId:
            raise ValueError("user_answer requires answerRevisionId")
        if self.resolutionSource != "user_answer" and self.answerRevisionId:
            raise ValueError("non-user resolution cannot forge a user answer")
        return self


class AnalysisSnapshotRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1)
    digest: str = Field(min_length=1)
    attemptId: str = Field(min_length=1)


class PreviousAttemptContext(BaseModel):
    """注入 AnalyzeRequest / FixRequest 的首轮包。关键答案不得被摘要截掉。"""

    model_config = ConfigDict(extra="ignore")

    attemptId: str = Field(min_length=1)
    parentAttemptId: Optional[str] = None
    revisionId: Optional[str] = None
    digest: str = Field(min_length=1)
    workspaceHead: Optional[str] = None
    contentDigest: Optional[str] = None
    currentHead: Optional[str] = None
    currentContentDigest: Optional[str] = None
    sourceDrift: bool = False
    outcome: str = ""
    topCandidates: list[dict[str, Any]] = Field(default_factory=list)
    rootCauseSummary: str = ""
    claims: list[Claim] = Field(default_factory=list)
    ruledOut: list[str] = Field(default_factory=list)
    proposedFix: Optional[dict[str, Any]] = None
    openQuestions: list[Question] = Field(default_factory=list)
    questionResolutions: list[QuestionResolution] = Field(default_factory=list)
    confirmedTarget: str = ""
    latestFeedbackKind: Optional[str] = None
    latestFeedbackText: str = ""
    rejectedHypotheses: list[str] = Field(default_factory=list)
    patchState: Optional[str] = None
    analysisRef: AnalysisSnapshotRef
    questionAnswers: list[QuestionAnswer] = Field(default_factory=list)


class ConvergenceResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resolutions: list[QuestionResolution] = Field(default_factory=list)
    openQuestions: list[Question] = Field(default_factory=list)
    violations: list[str] = Field(default_factory=list)
    needsClosingPass: bool
    analysisIncomplete: bool = False

class EditDecision(BaseModel):
    """第 5 节门槛结论。程序只校验结构；因果由模型解释。"""

    model_config = ConfigDict(extra="ignore")

    behaviorTarget: str = ""
    codeAssociation: str = ""
    mechanism: str = ""
    editRationale: str = ""
    executionPremise: str = ""
    evidenceRefs: list[str] = Field(default_factory=list)
    openQuestions: list[str] = Field(default_factory=list)
    questions: list[Question] | None = None
    allowed: bool = False
    reason: str = ""


class WorkspaceSnapshot(BaseModel):
    model_config = ConfigDict(extra="ignore")

    repoId: str = Field(min_length=1)
    head: Optional[str] = None
    dirty: list[str] = Field(default_factory=list)
    untracked: list[str] = Field(default_factory=list)
    contentDigest: Optional[str] = None
    capturedAt: str = ""
    freezeRoot: Optional[str] = None


class PatchFile(BaseModel):
    model_config = ConfigDict(extra="ignore")

    repoId: str = "."
    path: str = Field(min_length=1)
    kind: PatchFileKind = "modify"
    digest: str = ""
    archivePath: str = ""
    fromPath: Optional[str] = None


class PatchSet(BaseModel):
    model_config = ConfigDict(extra="ignore")

    patchSetId: str = Field(min_length=1)
    delivery: PatchDelivery = "none"
    baselineHead: Optional[str] = None
    summary: str = ""
    patches: list[PatchFile] = Field(default_factory=list)
    replaces: Optional[str] = None
    bundlePath: Optional[str] = None
    baselineDigest: Optional[str] = None

    @model_validator(mode="after")
    def _candidate_complete(self) -> PatchSet:
        if self.delivery != "candidate":
            return self
        if not self.patches:
            raise ValueError("candidate requires complete patch reference")
        for item in self.patches:
            if not item.digest or not item.archivePath:
                raise ValueError("candidate requires complete patch reference")
        return self


class VerificationRun(BaseModel):
    model_config = ConfigDict(extra="ignore")

    command: list[str] = Field(default_factory=list)
    cwd: str = "."
    backend: str = "host"
    timeoutSeconds: int = 120
    exitCode: Optional[int] = None
    logRef: Optional[str] = None
    result: CheckResult = "not_run"
    coverage: str = ""
    candidateDigest: Optional[str] = None

    @model_validator(mode="after")
    def _passed_has_execution(self) -> VerificationRun:
        if self.result == "passed" and self.exitCode is None:
            raise ValueError("passed requires execution record")
        return self


class SkillUsage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    source: str = ""
    repoId: str = "."
    name: str = Field(min_length=1)
    version: str = ""
    selected: bool = False
    applied: bool = False
    blocked: Optional[str] = None


class InputRevision(BaseModel):
    model_config = ConfigDict(extra="ignore")

    revisionId: str = Field(min_length=1)
    defectId: str = Field(min_length=1)
    parentId: Optional[str] = None
    parentRevisionId: Optional[str] = None
    feedbackText: str = ""
    observed: Optional[str] = None
    expected: Optional[str] = None
    steps: Optional[str] = None
    attachments: list[str] = Field(default_factory=list)
    source: str = "ticket"
    questionAnswers: list[QuestionAnswer] = Field(default_factory=list)
    questionResolutions: list[QuestionResolution] = Field(default_factory=list)


class Feedback(BaseModel):
    model_config = ConfigDict(extra="ignore")

    feedbackId: str = Field(min_length=1)
    defectId: str = Field(min_length=1)
    attemptId: Optional[str] = None
    patchSetId: Optional[str] = None
    application: UserApplication = "unknown"
    acceptance: UserAcceptance = "pending"
    kind: Literal["supplement_fact", "change_expected", "acceptance", "reject_hypothesis", "unknown"] = "unknown"
    parentRevisionId: Optional[str] = None
    observed: Optional[str] = None
    expected: Optional[str] = None
    steps: Optional[str] = None
    clearFields: list[Literal["observed", "expected", "steps"]] = Field(default_factory=list)
    removeAttachmentIds: list[str] = Field(default_factory=list)
    text: str = ""
    attachments: list[str] = Field(default_factory=list)
    questionAnswers: list[QuestionAnswer] = Field(default_factory=list)
    formId: Optional[str] = None


class TaskContext(BaseModel):
    """单票分析/编辑共享上下文。T02 组装，后续任务只引用此类型。"""

    model_config = ConfigDict(extra="ignore")

    defectId: str = Field(min_length=1)
    revision: Optional[InputRevision] = None
    snapshot: Optional[WorkspaceSnapshot] = None
    evidence: list[Evidence] = Field(default_factory=list)
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    skills: list[SkillUsage] = Field(default_factory=list)
    conventions: list[str] = Field(default_factory=list)
    specDirs: list[str] = Field(default_factory=list)
    unreadAttachments: list[str] = Field(default_factory=list)
    investigation: dict[str, Any] = Field(default_factory=dict)
    sourceDocument: dict[str, Any] = Field(default_factory=dict)
    currentTarget: str = ""
    claims: list[Claim] = Field(default_factory=list)
    generatePatch: bool = False
    questionResolutions: list[QuestionResolution] = Field(default_factory=list)
    analysisIncomplete: bool = False


class AttemptRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    schemaVersion: str
    attemptId: str = Field(min_length=1)
    defectId: str = Field(min_length=1)
    parentAttemptId: Optional[str] = None
    revisionId: Optional[str] = None
    execution: ExecutionStatus = "queued"
    resolution: ResolutionStatus = "incomplete"
    patchDelivery: PatchDelivery = "none"
    userApplication: UserApplication = "unknown"
    userAcceptance: UserAcceptance = "pending"
    feedbackId: Optional[str] = None
    editDecision: Optional[EditDecision] = None
    patchSet: Optional[PatchSet] = None
    checks: list[VerificationRun] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    sessionId: Optional[str] = None
    cost: Optional[dict[str, Any]] = None
    analysisRef: Optional[AnalysisSnapshotRef] = None
    analysisDigest: Optional[str] = None

    @model_validator(mode="after")
    def _invariants(self) -> AttemptRecord:
        if self.schemaVersion != REPAIR_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported repair schemaVersion {self.schemaVersion!r}; "
                f"expected {REPAIR_SCHEMA_VERSION}, regenerate artifacts"
            )
        if self.userAcceptance == "accepted" and not self.feedbackId:
            raise ValueError("accepted can only be written by feedback")
        return self


class BatchManifest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    schemaVersion: str = REPAIR_SCHEMA_VERSION
    batchId: str = Field(min_length=1)
    productLine: str = ""
    mode: Literal["analyze-only", "generate-patch"] = "analyze-only"
    inputCount: int = 0
    repoIds: list[str] = Field(default_factory=list)


class DefectRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    defectKey: str = Field(min_length=1)
    defectId: str = Field(min_length=1)
    currentRevisionId: Optional[str] = None
    latestAttemptId: Optional[str] = None


def validate_attempt(data: Any) -> AttemptRecord:
    """校验 attempt 文档；旧版本给出明确错误。"""
    return AttemptRecord.model_validate(data)


def safe_validate_attempt(data: Any) -> tuple[bool, AttemptRecord | str]:
    try:
        return True, AttemptRecord.model_validate(data)
    except Exception as err:  # noqa: BLE001
        return False, str(err)
