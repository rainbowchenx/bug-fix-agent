from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from bugfix_contracts.common import CONTRACT_SCHEMA_VERSION, Confidence

CODE_KNOWLEDGE_SCHEMA_VERSION = CONTRACT_SCHEMA_VERSION

CartographyProfile = Literal[
    "electron_node",
    "micro_frontend",
    "device_web",
    "unknown",
]
MatchSource = Literal["codegraph", "grep", "heuristic", "claude_md", "model_reported"]
MatchGap = Literal["no_path_token_overlap"]
FactValidity = Literal["unverified", "reference_verified", "rejected"]
FactSource = Literal["model_reported", "tool_observed"]
AcceptanceStatus = Literal["accepted", "rejected", "isolated"]
StorageStatus = Literal["saved", "artifact_error", "not_saved"]
ParseAction = Literal["isolate", "coerce", "drop", "reject", "record"]


class RepoRoot(BaseModel):
    path: str = Field(min_length=1)
    gitHead: Optional[str] = None
    fingerprint: Optional[str] = None


class CodeReference(BaseModel):
    """Fact 引用只说明来源位置；存在路径不等于 claim 因果成立。"""

    model_config = ConfigDict(extra="forbid")

    repoId: str = Field(min_length=1)
    path: str = Field(min_length=1)
    revision: Optional[str] = None
    contentDigest: Optional[str] = None
    snippet: Optional[str] = None
    startLine: Optional[int] = None
    endLine: Optional[int] = None


class InvestigationFact(BaseModel):
    """生产事实。字符串只是适配器输入，不能直接写入本类型。"""

    model_config = ConfigDict(extra="forbid")

    claim: str = Field(min_length=1)
    reference: Optional[CodeReference] = None
    validity: FactValidity = "unverified"
    source: FactSource = "model_reported"


class ParseIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fieldPath: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    action: ParseAction
    rawRef: Optional[str] = None


class RawResponseRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1)
    digest: str = Field(min_length=1)
    callId: str = Field(min_length=1)
    truncated: bool = False


class MatchCandidate(BaseModel):
    repoPath: str = "."
    path: str = Field(min_length=1)
    symbol: Optional[str] = None
    why: str = ""
    source: MatchSource = "heuristic"


class DefectCodeMatch(BaseModel):
    defectId: str = Field(min_length=1)
    clusterId: Optional[str] = None
    title: Optional[str] = None
    candidates: list[MatchCandidate] = Field(default_factory=list)
    confidence: Confidence = "low"
    gap: Optional[MatchGap] = None
    """空候选原因。``no_path_token_overlap`` = 票面词与路径词表不重合，不是检索失败。"""
    investigationStatus: Optional[
        Literal["not_investigated", "search_draft", "partial", "complete", "failed"]
    ] = None
    """Agent-2 逐票覆盖。缺省表示旧产物未声明，不能当成已调查。"""
    searchedScopes: list[str] = Field(default_factory=list)
    observedScopes: list[str] = Field(default_factory=list)
    openQuestions: list[str] = Field(default_factory=list)
    facts: list[InvestigationFact] = Field(default_factory=list)
    hypotheses: list[str] = Field(default_factory=list)
    ruledOut: list[str] = Field(default_factory=list)
    nextChecks: list[str] = Field(default_factory=list)
    investigationSource: Literal["model_reported", "tool_observed"] = "model_reported"
    acceptanceStatus: Optional[AcceptanceStatus] = None
    storageStatus: Optional[StorageStatus] = None


class SpecEntry(BaseModel):
    path: str
    kind: Literal[
        "guide", "skill", "rule", "command", "agent_def", "doc_ref", "dr", "ds", "unknown"
    ] = "unknown"
    source: Literal["claude_dir", "repo_root", "explicit", "follow_ref"] = "repo_root"


class SpecAtlas(BaseModel):
    frameworkId: str = "unknown"
    entries: list[SpecEntry] = Field(default_factory=list)
    drDs: list[dict[str, Any]] = Field(default_factory=list)
    bindings: list[dict[str, Any]] = Field(default_factory=list)


class ArchModule(BaseModel):
    id: str
    path: Optional[str] = None
    role: Optional[str] = None
    shared: Optional[bool] = None
    notes: Optional[str] = None


class TechStack(BaseModel):
    languages: list[str] = Field(default_factory=list)
    frameworks: list[str] = Field(default_factory=list)
    notes: str = ""


class Architecture(BaseModel):
    summary: str = ""
    entryPoints: list[str] = Field(default_factory=list)
    modules: list[ArchModule] = Field(default_factory=list)


class Conventions(BaseModel):
    fromClaudeMd: list[str] = Field(default_factory=list)
    """保留字段，**不再填充**：CLAUDE.md 的正文截取没有任何定位价值，文件本身记在
    ``specAtlas.entries``。留着是为了旧产物还能通过校验。"""
    fromRules: list[str] = Field(default_factory=list)


class Capabilities(BaseModel):
    codeGraph: bool = False
    runtimeVerify: bool = False


class CodeKnowledge(BaseModel):
    runtimeProfile: dict[str, Any] = Field(default_factory=dict)
    skillDiscovery: list[dict[str, Any]] = Field(default_factory=list)
    model_config = ConfigDict(extra="ignore")

    schemaVersion: Literal["0.4.0"]
    productLine: str = Field(min_length=1)
    workDir: str = Field(min_length=1)
    investigationRuns: list[dict[str, Any]] = Field(default_factory=list)
    investigationProgress: dict[str, Any] = Field(default_factory=dict)
    partial: bool = False
    generatedAt: str = Field(min_length=1)
    repoRoots: list[RepoRoot] = Field(default_factory=list)
    cartographyProfile: CartographyProfile = "unknown"
    secondaryHints: list[str] = Field(default_factory=list)
    techStack: TechStack = Field(default_factory=TechStack)
    architecture: Architecture = Field(default_factory=Architecture)
    conventions: Conventions = Field(default_factory=Conventions)
    boundSkills: list[str] = Field(default_factory=list)
    specAtlas: SpecAtlas = Field(default_factory=SpecAtlas)
    capabilities: Capabilities = Field(default_factory=Capabilities)
    defectCodeMatches: list[DefectCodeMatch] = Field(default_factory=list)


class MatchParseResult(BaseModel):
    """不可信模型响应对单票的分层校验结果；不直接写业务文件。"""

    model_config = ConfigDict(extra="forbid")

    accepted: Optional[DefectCodeMatch] = None
    issues: list[ParseIssue] = Field(default_factory=list)
    acceptedFields: list[str] = Field(default_factory=list)
    rejectedFields: list[str] = Field(default_factory=list)
    candidateRefs: list[str] = Field(default_factory=list)
    factRefs: list[str] = Field(default_factory=list)


def validate_code_knowledge(data: Any) -> CodeKnowledge:
    return CodeKnowledge.model_validate(data)


def safe_validate_code_knowledge(data: Any) -> tuple[bool, CodeKnowledge | str]:
    try:
        return True, CodeKnowledge.model_validate(data)
    except Exception as e:  # noqa: BLE001
        return False, str(e)
