import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { createRunDir, writeInputDefects } from "../../src/runs/store.js";
import { runPipeline } from "../../src/runs/runner.js";
import type { Defect } from "../../src/types.js";

describe("runner dual outcome", () => {
  let workDir: string;

  afterEach(async () => {
    if (workDir) await rm(workDir, { recursive: true, force: true });
  });

  it("marks fixable+GREEN as fixed and not_actionable as unfixed", async () => {
    workDir = await mkdtemp(path.join(tmpdir(), "bugfix-dual-"));
    const { runId } = await createRunDir(workDir);

    const defects: Defect[] = [
      {
        id: "d-fix",
        title: "fixable bug",
        repoUrl: "https://gitlab.com/org/app.git",
        fingerprint: "fp-fix",
      },
      {
        id: "d-skip",
        title: "policy bug",
        repoUrl: "https://gitlab.com/org/app.git",
        fingerprint: "fp-skip",
      },
    ];
    await writeInputDefects(workDir, runId, defects, {
      workDir,
      defects,
      options: { skipReviewer: true },
    });

    const report = await runPipeline(workDir, runId, {
      gitlabToken: "glpat-test",
      gitlabHost: "https://gitlab.com",
      handlers: {
        ensureRepo: async () => ({
          repoPath: path.join(workDir, "repos", "app"),
          headSha: "sha",
        }),
        resolveStaticCheckPlan: async () => ({ commands: [] }),
        runStaticCheck: async () => ({ ok: true, command: "", logTail: "" }),
        analyzeCluster: async ({ cluster }) => {
          if (cluster.fingerprint === "fp-skip" || cluster.defectIds.includes("d-skip")) {
            return {
              status: "unfixed",
              reasonCode: "not_actionable",
              reasonDetail: "Needs product decision",
              rootCause: {
                headline: "policy",
                one_line_description: "not a code bug",
                five_whys: [],
                reproduction_steps: [],
                fixability: {
                  assessment: "not_actionable",
                  reason: "Needs product decision",
                },
              },
            };
          }
          return {
            status: "fixable",
            rootCause: {
              headline: "null crash",
              one_line_description: "null deref",
              five_whys: ["why"],
              reproduction_steps: [],
              fixability: { assessment: "fixable", reason: "add guard" },
            },
            solution: {
              one_line_summary: "add null guard",
              steps: [{ title: "guard", description: "check null" }],
            },
          };
        },
        resolveVerifyPlan: async () => ({
          profileId: "node-lib",
          install: ["npm install"],
          test: ["npm test"],
        }),
        prepareRepo: async () => ({ ok: true, logTail: "ok" }),
        implementCluster: async () => ({
          changedFiles: ["a.ts"],
          agentText: "ok",
          scopeOk: true,
          scopeViolations: [],
        }),
        runVerify: async () => ({ ok: true, command: "npm test", logTail: "pass" }),
        deliverFix: async () => ({
          mrUrl: "https://gitlab.com/org/app/-/merge_requests/1",
          branch: "bugfix/x/y",
        }),
      },
    });

    expect(report.summary.totalClusters).toBe(2);
    expect(report.summary.fixed).toBe(1);
    expect(report.summary.unfixed).toBe(1);
    expect(report.fixed[0]?.mrUrl).toContain("merge_requests/1");
    expect(report.unfixed[0]?.reasonCode).toBe("not_actionable");
    expect(report.unfixed[0]?.reasonDetail).toMatch(/product/i);
  });
});
