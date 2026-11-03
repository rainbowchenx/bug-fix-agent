import type {
  BatchTicket,
  DefectCodeMatch,
  TicketOutcome,
  TicketReport,
} from "../../contracts/index.js";

export function sliceTicket(t: BatchTicket): TicketReport["ticket"] {
  return {
    title: t.title,
    testModule: t.testModule,
    titleTag: t.titleTag,
    intent: t.intent,
    pool: t.pool,
    observed: t.observed,
    expected: t.expected,
    steps: t.steps,
    status: t.status,
    severity: t.severity,
    reasonCode: t.reasonCode,
    reasonDetail: t.reasonDetail,
  };
}

/**
 * Deterministic first-pass router (no LLM).
 * Real rootCause/patch sessions plug in later; outcomes stay contract-valid.
 */
export function routeTicket(
  ticket: BatchTicket,
  match: DefectCodeMatch | undefined,
): Pick<
  TicketReport,
  | "outcome"
  | "proposedFix"
  | "patch"
  | "blockers"
  | "rootCause"
  | "localization"
  | "suggestedVerify"
  | "confidence"
  | "verifyStatus"
> {
  const candidates = (match?.candidates ?? []).map((c) => ({
    repoPath: c.repoPath,
    path: c.path,
    symbol: c.symbol,
    why: c.why,
    source: c.source,
  }));

  if (ticket.pool === "needs_info") {
    return {
      outcome: "needs_ticket_info",
      proposedFix: null,
      patch: null,
      blockers: {
        kind: "needs_ticket_info",
        detail: ticket.reasonDetail ?? "screen funnel marked needs_info",
        missingInfo: missingFromTicket(ticket),
      },
      rootCause: {
        summary: "Insufficient ticket information to localize or propose a reliable fix",
        ruledOut: [],
        openQuestions: missingFromTicket(ticket),
      },
      localization: { candidates, notes: "soft-start matches retained; analysis blocked on ticket info" },
      suggestedVerify: { steps: ["补充缺陷单信息后重跑 Agent-3"], executed: false },
      confidence: "low",
      verifyStatus: "skipped",
    };
  }

  if (!candidates.length) {
    const outcome: TicketOutcome = "unlocalized";
    return {
      outcome,
      proposedFix: null,
      patch: null,
      blockers: {
        kind: "unlocalized",
        detail: "no code candidates from Agent-2 soft-start; SDK re-search not yet enabled",
      },
      rootCause: {
        summary: "Unable to localize to code with current code-knowledge matches",
        ruledOut: [],
        openQuestions: ["需要 CodeGraph/SDK 二次检索", "确认测试模块与代码目录映射"],
      },
      localization: { candidates: [], notes: "empty defectCodeMatches.candidates", degradedSearch: false },
      suggestedVerify: { steps: [], executed: false },
      confidence: "low",
      verifyStatus: "skipped",
    };
  }

  // Has candidates → plan_only (deterministic plan; patch deferred to SDK editor)
  const targets = candidates.map((c) => (c.repoPath === "." ? c.path : `${c.repoPath}/${c.path}`));
  return {
    outcome: "plan_only",
    proposedFix: {
      summary: `Inspect and fix around soft-matched paths for: ${ticket.title.slice(0, 80)}`,
      steps: [
        "Review soft-start candidates from code-knowledge",
        "Confirm root cause with Read/Grep (SDK session)",
        "Apply minimal-diff patch under scope lock",
      ],
      targetFiles: targets.slice(0, 5),
    },
    patch: null,
    blockers: null,
    rootCause: {
      summary: "Localization soft-start available; root cause pending Agent-3 SDK analyze session",
      ruledOut: [],
      openQuestions: ["根因待 analyze 会话确认"],
    },
    localization: {
      candidates,
      notes: "consumed Agent-2 defectCodeMatches as soft start (D4)",
    },
    suggestedVerify: {
      steps: ["按业务模块手测复现步骤", "关注 candidate 文件相关单测（若有）"],
      executed: false,
    },
    confidence: match?.confidence ?? "low",
    verifyStatus: "skipped",
  };
}

function missingFromTicket(t: BatchTicket): string[] {
  const missing: string[] = [];
  if (!t.steps?.trim()) missing.push("复现步骤");
  if (!t.expected?.trim()) missing.push("期望结果");
  if (!t.observed?.trim()) missing.push("实际结果");
  if (t.expectQuality === "absent" || t.expectQuality === "ambiguous") {
    missing.push("可判定的期望描述");
  }
  if (t.reasonDetail) missing.push(`筛因补充: ${t.reasonDetail}`);
  return missing.length ? missing : ["更完整的缺陷描述/附件"];
}
