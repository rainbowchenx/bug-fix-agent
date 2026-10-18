import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createRunDir, writeInputDefects } from "../../src/runs/store.js";
import { runPipeline } from "../../src/runs/runner.js";
import type { Defect } from "../../src/types.js";

const baseDefects = (fp: string): Defect[] => [
  {
    id: "d1",
    title: "bug",
    repoUrl: "https://gitlab.com/org/app.git",
    fingerprint: fp,
  },
];

describe("runner quality gates", () => {
  let workDir: string;

  afterEach(async () => {
    if (workDir) await rm(workDir, { recursive: true, force: true });
  });

  it("stops iterate on environment verify failure (single implement)", async () => {
    workDir = await mkdtemp(path.join(tmpdir(), "bugfix-qg-env-"));
    const { runId } = await createRunDir(workDir);
    const defects = baseDefects("fp-env");
    await writeInputDefects(workDir, runId, defects, {
      workDir,
      defects,
      options: { maxIterate: 3, skipReviewer: true },
    });

    const implement = vi.fn(async () => ({
      changedFiles: ["src/a.ts"],
      agentText: "ok",
      scopeOk: true,
      scopeViolations: [],
    }));

    const report = await runPipeline(workDir, runId, {
      gitlabToken: "glpat-x",
      handlers: {
        ensureRepo: async () => ({ repoPath: path.join(workDir, "r"), headSha: "s" }),
        analyzeCluster: async () => ({
          status: "fixable",
          rootCause: {
            headline: "h",
            one_line_description: "d",
            five_whys: [],
            reproduction_steps: [],
            fixability: { assessment: "fixable", reason: "r" },
          },
          solution: {
            one_line_summary: "s",
            steps: [{ title: "t", description: "d" }],
            target_files: ["src/a.ts"],
          },
        }),
        resolveVerifyPlan: async () => ({
          profileId: "node-lib",
          install: [],
          test: ["npm test"],
        }),
        prepareRepo: async () => ({ ok: true, logTail: "" }),
        resolveStaticCheckPlan: async () => ({ commands: [] }),
        runStaticCheck: async () => ({ ok: true, command: "", logTail: "" }),
        implementCluster: implement,
        runVerify: async () => ({
          ok: false,
          command: "npm test",
          logTail: "Error: Cannot find module 'missing-dep'",
        }),
      },
    });

    expect(implement).not.toHaveBeenCalled();
    expect(report.summary.fixed).toBe(0);
    expect(report.unfixed[0]?.reasonCode).toBe("env_verify_failed");
  });

  it("review request_changes exhausted yields review_failed without mrUrl", async () => {
    workDir = await mkdtemp(path.join(tmpdir(), "bugfix-qg-rev-"));
    const { runId } = await createRunDir(workDir);
    const defects = baseDefects("fp-rev");
    await writeInputDefects(workDir, runId, defects, {
      workDir,
      defects,
      options: { maxIterate: 1, skipReviewer: false },
    });

    const report = await runPipeline(workDir, runId, {
      gitlabToken: "glpat-x",
      handlers: {
        ensureRepo: async () => ({ repoPath: path.join(workDir, "r"), headSha: "s" }),
        analyzeCluster: async () => ({
          status: "fixable",
          rootCause: {
            headline: "h",
            one_line_description: "d",
            five_whys: [],
            reproduction_steps: [],
            fixability: { assessment: "fixable", reason: "r" },
          },
          solution: {
            one_line_summary: "s",
            steps: [{ title: "t", description: "d" }],
            target_files: ["src/a.ts"],
          },
        }),
        resolveVerifyPlan: async () => ({
          profileId: "node-lib",
          install: [],
          test: ["npm test"],
        }),
        prepareRepo: async () => ({ ok: true, logTail: "" }),
        resolveStaticCheckPlan: async () => ({ commands: [] }),
        runStaticCheck: async () => ({ ok: true, command: "", logTail: "" }),
        implementCluster: async () => ({
          changedFiles: ["src/a.ts"],
          agentText: "ok",
          scopeOk: true,
          scopeViolations: [],
        }),
        runVerify: async () => ({ ok: true, command: "npm test", logTail: "pass" }),
        reviewCluster: async () => ({
          decision: "request_changes",
          reasons: ["scope creep"],
        }),
        deliverFix: async () => {
          throw new Error("should not deliver");
        },
      },
    });

    expect(report.summary.fixed).toBe(0);
    expect(report.fixed).toHaveLength(0);
    expect(report.unfixed[0]?.reasonCode).toBe("review_failed");
    expect(report.unfixed[0]?.reasonDetail).toMatch(/request_changes|scope creep|Known Issues/i);
  });
});
