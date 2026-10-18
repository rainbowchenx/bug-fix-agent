import { describe, expect, it } from "vitest";
import { parseCreateRunRequest, parseReport, ReasonCodeSchema } from "../../src/types.js";

describe("RunReport schema", () => {
  it("accepts a valid dual-outcome report", () => {
    const report = parseReport({
      runId: "run-1",
      summary: { totalClusters: 2, fixed: 1, unfixed: 1 },
      fixed: [
        {
          clusterId: "c1",
          defectIds: ["d1"],
          mrUrl: "https://gitlab.com/g/p/-/merge_requests/1",
          rootCauseSummary: "null deref in foo",
          verify: { command: "npm test", ok: true, exitCode: 0 },
          verifyLevel: "reproduced",
          baselineRed: false,
          baseSha: "abc",
        },
      ],
      unfixed: [
        {
          clusterId: "c2",
          defectIds: ["d2"],
          reasonCode: "not_actionable",
          reasonDetail: "Needs product decision; no code fix path.",
        },
      ],
    });
    expect(report.summary.fixed).toBe(1);
    expect(report.unfixed[0]?.reasonCode).toBe("not_actionable");
  });

  it("rejects invalid reasonCode", () => {
    expect(() =>
      parseReport({
        runId: "run-1",
        summary: { totalClusters: 1, fixed: 0, unfixed: 1 },
        fixed: [],
        unfixed: [
          {
            clusterId: "c1",
            defectIds: ["d1"],
            reasonCode: "totally_made_up",
            reasonDetail: "x",
          },
        ],
      }),
    ).toThrow();
  });

  it("enumerates known reason codes", () => {
    expect(ReasonCodeSchema.options).toContain("verify_failed");
    expect(ReasonCodeSchema.options).toContain("push_failed");
  });
});

describe("CreateRunRequest", () => {
  it("requires workDir and at least one defect", () => {
    const req = parseCreateRunRequest({
      workDir: "D:/work",
      defects: [
        {
          id: "1",
          title: "crash",
          repoUrl: "https://gitlab.com/a/b.git",
        },
      ],
    });
    expect(req.defects).toHaveLength(1);
  });

  it("rejects empty defects", () => {
    expect(() =>
      parseCreateRunRequest({ workDir: "D:/work", defects: [] }),
    ).toThrow();
  });
});
