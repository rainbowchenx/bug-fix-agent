import { z } from "zod";
import { CONTRACT_SCHEMA_VERSION, ConfidenceSchema } from "./common.js";

export const ANALYSIS_REPORT_SCHEMA_VERSION = CONTRACT_SCHEMA_VERSION;

/**
 * Per-ticket outcome (D2). Mutually exclusive bodies:
 * - patch_ready / plan_only → proposedFix required
 * - needs_* / unlocalized / … → blockers required
 */
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
]);
export type TicketOutcome = z.infer<typeof TicketOutcomeSchema>;

export const TicketBlockersSchema = z.object({
  kind: z.string().min(1),
  detail: z.string().default(""),
  missingInfo: z.array(z.string()).optional(),
  envNeeds: z.array(z.string()).optional(),
});
export type TicketBlockers = z.infer<typeof TicketBlockersSchema>;

export const TicketSliceSchema = z.object({
  title: z.string().optional(),
  testModule: z.string().optional(),
  titleTag: z.string().optional(),
  intent: z.string().optional(),
  pool: z.string().optional(),
  observed: z.string().optional(),
  expected: z.string().optional(),
  steps: z.string().optional(),
  status: z.string().optional(),
  severity: z.string().optional(),
  reasonCode: z.string().optional(),
  reasonDetail: z.string().optional(),
});
export type TicketSlice = z.infer<typeof TicketSliceSchema>;

export const LocalizationSchema = z.object({
  candidates: z
    .array(
      z.object({
        repoPath: z.string().default("."),
        path: z.string(),
        symbol: z.string().optional(),
        why: z.string().optional(),
        source: z.string().optional(),
      }),
    )
    .default([]),
  notes: z.string().optional(),
  /** true when Agent-3 re-searched beyond Agent-2 matches. */
  degradedSearch: z.boolean().optional(),
});
export type Localization = z.infer<typeof LocalizationSchema>;

export const TicketReportSchema = z
  .object({
    defectId: z.string().min(1),
    ticket: TicketSliceSchema.default({}),
    localization: LocalizationSchema.default({ candidates: [] }),
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
        summary: z.string().min(1),
        steps: z.array(z.string()).default([]),
        targetFiles: z.array(z.string()).optional(),
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
  })
  .superRefine((val, ctx) => {
    const actionable = val.outcome === "patch_ready" || val.outcome === "plan_only";
    if (actionable && (!val.proposedFix || !val.proposedFix.summary)) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: `${val.outcome} requires proposedFix.summary`,
        path: ["proposedFix"],
      });
    }
    if (!actionable && !val.blockers) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: `${val.outcome} requires blockers`,
        path: ["blockers"],
      });
    }
  });
export type TicketReport = z.infer<typeof TicketReportSchema>;

/**
 * analysis-report — Agent-3 → human / downstream.
 * Every analyzed ticket must appear with a full outcome body (D2).
 */
export const AnalysisReportSchema = z.object({
  schemaVersion: z.string(),
  productLine: z.string().min(1),
  workDir: z.string().min(1),
  generatedAt: z.string().min(1),
  openMr: z.boolean().default(false),
  mrUrl: z.string().nullable().optional(),
  integrateMode: z.enum(["none", "single_mr"]).default("none"),
  summary: z
    .object({
      total: z.number().int().nonnegative(),
      byOutcome: z.record(z.string(), z.number().int().nonnegative()).default({}),
    })
    .optional(),
  tickets: z.array(TicketReportSchema),
});
export type AnalysisReport = z.infer<typeof AnalysisReportSchema>;

export function validateAnalysisReport(input: unknown): AnalysisReport {
  return AnalysisReportSchema.parse(input);
}

export function safeValidateAnalysisReport(
  input: unknown,
): { ok: true; data: AnalysisReport } | { ok: false; error: string } {
  const parsed = AnalysisReportSchema.safeParse(input);
  if (!parsed.success) return { ok: false, error: parsed.error.message };
  return { ok: true, data: parsed.data };
}
