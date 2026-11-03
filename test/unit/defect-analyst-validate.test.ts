import { describe, expect, it } from "vitest";
import {
  ANALYSIS_REPORT_SCHEMA_VERSION,
  safeValidateAnalysisReport,
  validateAnalysisReport,
} from "../../src/defect-analyst/index.js";

describe("analysis-report validate", () => {
  it("requires tickets array with outcome", () => {
    const data = validateAnalysisReport({
      schemaVersion: ANALYSIS_REPORT_SCHEMA_VERSION,
      productLine: "hc",
      workDir: "/tmp/w",
      generatedAt: new Date().toISOString(),
      tickets: [
        {
          defectId: "1",
          outcome: "needs_ticket_info",
          blockers: { kind: "needs_ticket_info", missingInfo: ["期望结果"], detail: "" },
        },
      ],
    });
    expect(data.tickets).toHaveLength(1);
    expect(data.openMr).toBe(false);
  });

  it("rejects unknown outcome", () => {
    const r = safeValidateAnalysisReport({
      schemaVersion: ANALYSIS_REPORT_SCHEMA_VERSION,
      productLine: "hc",
      workDir: "/tmp/w",
      generatedAt: new Date().toISOString(),
      tickets: [{ defectId: "1", outcome: "not_a_real_outcome" }],
    });
    expect(r.ok).toBe(false);
  });
});
