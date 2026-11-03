import { z } from "zod";

/** Agent-3 artifact schemaVersion — evolve with implementation. */
export const ANALYSIS_REPORT_SCHEMA_VERSION = "0.1.0";

export const TicketOutcomeSchema = z.enum([
  "patch_ready",
  "plan_only",
  "needs_test_env",
  "needs_ticket_info",
  "needs_design_input",
  "not_code",
  "config_or_dependency",
  "unlocalized",
  "other_blocked",
  "skipped_scaffold",
]);
export type TicketOutcome = z.infer<typeof TicketOutcomeSchema>;

export const ConfidenceSchema = z.enum(["high", "medium", "low"]);

export const TicketBlockersSchema = z.object({
  kind: z.string(),
  detail: z.string().default(""),
  missingInfo: z.array(z.string()).optional(),
  envNeeds: z.array(z.string()).optional(),
});
export type TicketBlockers = z.infer<typeof TicketBlockersSchema>;

export const TicketReportSchema = z.object({
  defectId: z.string(),
  ticket: z
    .object({
      title: z.string().optional(),
      testModule: z.string().optional(),
      titleTag: z.string().optional(),
      intent: z.string().optional(),
      pool: z.string().optional(),
      observed: z.string().optional(),
      expected: z.string().optional(),
      steps: z.string().optional(),
    })
    .default({}),
  localization: z
    .object({
      candidates: z.array(z.record(z.string(), z.unknown())).default([]),
      notes: z.string().optional(),
    })
    .default({ candidates: [] }),
  rootCause: z
    .object({
      summary: z.string().default(""),
      ruledOut: z.array(z.string()).default([]),
      openQuestions: z.array(z.string()).default([]),
    })
    .default({ summary: "", ruledOut: [], openQuestions: [] }),
  outcome: TicketOutcomeSchema,
  proposedFix: z
    .object({
      summary: z.string(),
      steps: z.array(z.string()).default([]),
    })
    .nullable()
    .optional(),
  patch: z
    .object({
      path: z.string().optional(),
      summary: z.string().optional(),
    })
    .nullable()
    .optional(),
  blockers: TicketBlockersSchema.nullable().optional(),
  suggestedVerify: z
    .object({
      steps: z.array(z.string()).default([]),
      executed: z.boolean().default(false),
    })
    .default({ steps: [], executed: false }),
  confidence: ConfidenceSchema.default("low"),
  verifyStatus: z.enum(["passed", "failed", "skipped"]).default("skipped"),
});
export type TicketReport = z.infer<typeof TicketReportSchema>;

/**
 * analysis-report — Agent-3 output contract (v0.1 scaffold).
 * Every ticket must appear in `tickets[]` with a full outcome body (D2).
 */
export const AnalysisReportSchema = z.object({
  schemaVersion: z.string(),
  productLine: z.string(),
  workDir: z.string(),
  generatedAt: z.string(),
  openMr: z.boolean().default(false),
  mrUrl: z.string().nullable().optional(),
  summary: z
    .object({
      total: z.number().int().nonnegative(),
      byOutcome: z.record(z.string(), z.number().int().nonnegative()).default({}),
    })
    .optional(),
  tickets: z.array(TicketReportSchema),
});
export type AnalysisReport = z.infer<typeof AnalysisReportSchema>;
