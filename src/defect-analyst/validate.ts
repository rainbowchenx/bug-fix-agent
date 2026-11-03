import { AnalysisReportSchema, type AnalysisReport } from "./types.js";

export function validateAnalysisReport(input: unknown): AnalysisReport {
  return AnalysisReportSchema.parse(input);
}

export function safeValidateAnalysisReport(
  input: unknown,
): { ok: true; data: AnalysisReport } | { ok: false; error: string } {
  const parsed = AnalysisReportSchema.safeParse(input);
  if (!parsed.success) {
    return { ok: false, error: parsed.error.message };
  }
  return { ok: true, data: parsed.data };
}
