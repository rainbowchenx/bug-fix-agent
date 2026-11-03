import {
  ANALYSIS_REPORT_SCHEMA_VERSION,
  isMatchPool,
  validateAnalysisReport,
  type AnalysisReport,
  type CodeKnowledge,
  type DefectBatch,
  type TicketReport,
} from "../../contracts/index.js";
import { routeTicket, sliceTicket } from "./route.js";

export interface RunAnalystInput {
  workDir: string;
  defectBatch: DefectBatch;
  codeKnowledge: CodeKnowledge;
  openMr?: boolean;
}

export type AnalystFn = (input: RunAnalystInput) => Promise<AnalysisReport>;

/**
 * Agent-3 public entry — reads only defect-batch + code-knowledge contracts.
 * Deterministic route for v0.1; SDK ticket_subgraph plugs in later.
 */
export async function runAnalyst(input: RunAnalystInput): Promise<AnalysisReport> {
  const openMr = input.openMr ?? false;
  const matchById = new Map(
    input.codeKnowledge.defectCodeMatches.map((m) => [m.defectId, m] as const),
  );

  const tickets: TicketReport[] = input.defectBatch.tickets
    .filter((t) => isMatchPool(t.pool))
    .map((t) => {
      const routed = routeTicket(t, matchById.get(t.defectId));
      return {
        defectId: t.defectId,
        ticket: sliceTicket(t),
        ...routed,
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
    integrateMode: openMr ? "single_mr" : "none",
    summary: { total: tickets.length, byOutcome },
    tickets,
  });
}

/** @deprecated alias */
export const runDefectAnalyst = runAnalyst;
export type RunDefectAnalystInput = RunAnalystInput;
export type DefectAnalystFn = AnalystFn;
