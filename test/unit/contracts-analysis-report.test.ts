import { describe, expect, it } from "vitest";
import {
  ANALYSIS_REPORT_SCHEMA_VERSION,
  safeValidateAnalysisReport,
  validateAnalysisReport,
} from "../../src/contracts/index.js";

describe("analysis-report contract", () => {
  it("requires proposedFix for plan_only", () => {
    const r = safeValidateAnalysisReport({
      schemaVersion: ANALYSIS_REPORT_SCHEMA_VERSION,
      productLine: "hc",
      workDir: "/tmp/w",
      generatedAt: new Date().toISOString(),
      tickets: [{ defectId: "1", outcome: "plan_only" }],
    });
    expect(r.ok).toBe(false);
  });

  it("requires blockers for needs_ticket_info", () => {
    const r = safeValidateAnalysisReport({
      schemaVersion: ANALYSIS_REPORT_SCHEMA_VERSION,
      productLine: "hc",
      workDir: "/tmp/w",
      generatedAt: new Date().toISOString(),
      tickets: [{ defectId: "1", outcome: "needs_ticket_info" }],
    });
    expect(r.ok).toBe(false);
  });

  it("accepts valid plan_only + blockers outcomes", () => {
    const data = validateAnalysisReport({
      schemaVersion: ANALYSIS_REPORT_SCHEMA_VERSION,
      productLine: "hc",
      workDir: "/tmp/w",
      generatedAt: new Date().toISOString(),
      tickets: [
        {
          defectId: "1",
          outcome: "plan_only",
          proposedFix: { summary: "fix layout", steps: [] },
        },
        {
          defectId: "2",
          outcome: "needs_ticket_info",
          blockers: { kind: "needs_ticket_info", missingInfo: ["期望结果"], detail: "" },
        },
      ],
    });
    expect(data.tickets).toHaveLength(2);
  });
});
