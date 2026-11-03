import type { DefectBatch } from "../defect-batch/types.js";
import type { CodeKnowledge } from "../code-knowledge/types.js";
import {
  ANALYSIS_REPORT_SCHEMA_VERSION,
  type AnalysisReport,
  type TicketReport,
} from "./types.js";
import { validateAnalysisReport } from "./validate.js";

export interface RunDefectAnalystInput {
  workDir: string;
  defectBatch: DefectBatch;
  codeKnowledge: CodeKnowledge;
  openMr?: boolean;
}

export type DefectAnalystFn = (input: RunDefectAnalystInput) => Promise<AnalysisReport>;

const ANALYST_POOLS = new Set(["strict", "locatable_only", "needs_info"]);

/**
 * Agent-3 entrypoint (scaffold).
 * Emits one full ticket report per functional-pool defect with outcome=skipped_scaffold.
 * Real ticket_subgraph lands in S3.
 */
export async function runDefectAnalyst(
  input: RunDefectAnalystInput,
): Promise<AnalysisReport> {
  const openMr = input.openMr ?? false;
  const matchById = new Map(
    input.codeKnowledge.defectCodeMatches.map((m) => [m.defectId, m]),
  );

  const tickets: TicketReport[] = input.defectBatch.tickets
    .filter((t) => ANALYST_POOLS.has(t.pool))
    .map((t) => {
      const m = matchById.get(t.defectId);
      return {
        defectId: t.defectId,
        ticket: {
          title: t.title,
          testModule: t.testModule,
          titleTag: t.titleTag,
          intent: t.intent,
          pool: t.pool,
          observed: t.observed,
          expected: t.expected,
          steps: t.steps,
        },
        localization: {
          candidates: (m?.candidates ?? []).map((c) => ({ ...c })),
          notes: "scaffold: soft-start matches only; localize not run",
        },
        rootCause: {
          summary: "",
          ruledOut: [],
          openQuestions: ["Agent-3 ticket_subgraph not implemented"],
        },
        outcome: "skipped_scaffold" as const,
        proposedFix: null,
        patch: null,
        blockers: {
          kind: "scaffold",
          detail: "defect-analyst stub — replace with analyze+patch subgraph",
        },
        suggestedVerify: { steps: [], executed: false },
        confidence: "low" as const,
        verifyStatus: "skipped" as const,
      };
    });

  const byOutcome: Record<string, number> = {};
  for (const t of tickets) {
    byOutcome[t.outcome] = (byOutcome[t.outcome] ?? 0) + 1;
  }

  return validateAnalysisReport({
    schemaVersion: ANALYSIS_REPORT_SCHEMA_VERSION,
    productLine: input.defectBatch.productLine,
    workDir: input.workDir,
    generatedAt: new Date().toISOString(),
    openMr,
    mrUrl: null,
    summary: { total: tickets.length, byOutcome },
    tickets,
  });
}
