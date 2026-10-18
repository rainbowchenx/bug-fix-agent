import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemorySaver } from "@langchain/langgraph";
import { createBugfixGraph, invokeBugfixGraph } from "../../src/graph/run-graph.js";
import { runPipeline, type ClusterHandlers } from "../../src/runs/runner.js";
import { createRunDir, readMeta, writeInputDefects } from "../../src/runs/store.js";
import type { CreateRunOptions, Defect, Engine, RunReport } from "../../src/types.js";

const rootCause = {
  headline: "h",
  one_line_description: "root cause d",
  five_whys: [],
  reproduction_steps: [],
  fixability: { assessment: "fixable" as const, reason: "r" },
};
const solution = {
  one_line_summary: "solution s",
  steps: [{ title: "t", description: "d" }],
  target_files: ["src/a.ts"],
};

function defect(id: string, fp: string): Defect {
  return { id, title: `bug ${id}`, repoUrl: "https://gitlab.com/org/app.git", fingerprint: fp };
}

function baseHandlers(workDir: string): Required<
  Omit<ClusterHandlers, "classifyVerifyFailure">
> {
  return {
    ensureRepo: vi.fn(async () => ({ repoPath: path.join(workDir, "r"), headSha: "s" })),
    analyzeCluster: vi.fn(async () => ({ status: "fixable" as const, rootCause, solution })),
    resolveVerifyPlan: vi.fn(async () => ({
      profileId: "node-lib" as const,
      install: [],
      test: ["npm test"],
    })),
    prepareRepo: vi.fn(async () => ({ ok: true, logTail: "" })),
    resolveStaticCheckPlan: vi.fn(async () => ({ commands: [] })),
    runStaticCheck: vi.fn(async () => ({ ok: true, command: "", logTail: "" })),
    implementCluster: vi.fn(async () => ({
      changedFiles: ["src/a.ts"],
      agentText: "ok",
      scopeOk: true,
      scopeViolations: [],
    })),
    runVerify: vi.fn(async () => ({ ok: true, command: "npm test", logTail: "pass" })),
    reviewCluster: vi.fn(async () => ({ decision: "approve" as const, reasons: [] })),
    deliverFix: vi.fn(async (input: { clusterId: string }) => ({
      mrUrl: `https://gitlab.com/org/app/-/merge_requests/${input.clusterId}`,
      branch: "b",
    })),
  };
}

type Handlers = ReturnType<typeof baseHandlers>;

interface Scenario {
  name: string;
  defects: Defect[];
  options: CreateRunOptions;
  token?: string | null;
  tweak?: (h: Handlers) => void;
  expect: (report: RunReport, h: Handlers) => void;
}

const scenarios: Scenario[] = [
  {
    name: "happy path opens MR after reviewer approval",
    defects: [defect("d1", "fp-ok")],
    options: { maxIterate: 3 },
    expect: (r, h) => {
      expect(r.summary).toEqual({ totalClusters: 1, fixed: 1, unfixed: 0 });
      expect(r.fixed[0]?.mrUrl).toMatch(/merge_requests/);
      expect(h.reviewCluster).toHaveBeenCalledTimes(1);
      expect(h.deliverFix).toHaveBeenCalledTimes(1);
    },
  },
  {
    name: "analyze unfixed short-circuits",
    defects: [defect("d1", "fp-na")],
    options: {},
    tweak: (h) => {
      h.analyzeCluster.mockImplementation(async () => ({
        status: "unfixed" as const,
        reasonCode: "not_actionable" as const,
        reasonDetail: "nope",
        rootCause,
      }));
    },
    expect: (r, h) => {
      expect(r.unfixed[0]?.reasonCode).toBe("not_actionable");
      expect(r.unfixed[0]?.artifacts?.rootCause).toBe("root cause d");
      expect(h.implementCluster).not.toHaveBeenCalled();
    },
  },
  {
    name: "ensureRepo failure → prepare_failed",
    defects: [defect("d1", "fp-repo")],
    options: {},
    tweak: (h) => {
      h.ensureRepo.mockImplementation(async () => {
        throw new Error("clone denied");
      });
    },
    expect: (r) => {
      expect(r.unfixed[0]?.reasonCode).toBe("prepare_failed");
      expect(r.unfixed[0]?.reasonDetail).toMatch(/clone denied/);
    },
  },
  {
    name: "no test command → no_test_command",
    defects: [defect("d1", "fp-notest")],
    options: {},
    tweak: (h) => {
      h.resolveVerifyPlan.mockImplementation(async () => ({
        profileId: "node-lib" as const,
        install: [],
        test: [],
      }));
    },
    expect: (r, h) => {
      expect(r.unfixed[0]?.reasonCode).toBe("no_test_command");
      expect(h.implementCluster).not.toHaveBeenCalled();
    },
  },
  {
    name: "environment verify failure stops after one implement",
    defects: [defect("d1", "fp-env")],
    options: { maxIterate: 3, skipReviewer: true },
    tweak: (h) => {
      h.runVerify.mockImplementation(async () => ({
        ok: false,
        command: "npm test",
        logTail: "Error: Cannot find module 'missing-dep'",
      }));
    },
    expect: (r, h) => {
      expect(h.implementCluster).not.toHaveBeenCalled();
      expect(r.unfixed[0]?.reasonCode).toBe("env_verify_failed");
    },
  },
  {
    name: "product failure then GREEN iterates and feeds back the log",
    defects: [defect("d1", "fp-iter")],
    options: { maxIterate: 3, skipReviewer: true },
    tweak: (h) => {
      let n = 0;
      h.runVerify.mockImplementation(async () => {
        n += 1;
        if (n === 1) return { ok: true, command: "npm test", logTail: "baseline" };
        if (n === 2 || n === 3) {
          return {
            ok: false,
            command: "npm test",
            logTail: "AssertionError: expected 1 to be 2",
          };
        }
        return { ok: true, command: "npm test", logTail: "pass" };
      });
    },
    expect: (r, h) => {
      expect(r.summary.fixed).toBe(1);
      expect(h.implementCluster).toHaveBeenCalledTimes(3);
      const third = h.implementCluster.mock.calls[2]![0] as { verifyLogTail?: string };
      expect(third.verifyLogTail).toMatch(/AssertionError/);
      expect(h.reviewCluster).not.toHaveBeenCalled();
    },
  },
  {
    name: "product failure exhausts maxIterate → verify_failed",
    defects: [defect("d1", "fp-exhaust")],
    options: { maxIterate: 5, skipReviewer: true },
    tweak: (h) => {
      let n = 0;
      h.runVerify.mockImplementation(async () => {
        n += 1;
        if (n === 1) return { ok: true, command: "npm test", logTail: "baseline" };
        return { ok: false, command: "npm test", logTail: "AssertionError: still broken" };
      });
    },
    expect: (r, h) => {
      expect(h.implementCluster).toHaveBeenCalledTimes(6);
      expect(r.unfixed[0]?.reasonCode).toBe("verify_failed");
      expect(h.deliverFix).not.toHaveBeenCalled();
    },
  },
  {
    name: "static check fails once then passes",
    defects: [defect("d1", "fp-static")],
    options: { maxIterate: 2, skipReviewer: true },
    tweak: (h) => {
      h.runStaticCheck
        .mockImplementationOnce(async () => ({ ok: true, command: "tsc", logTail: "" }))
        .mockImplementationOnce(async () => ({ ok: false, command: "tsc", logTail: "TS2322" }))
        .mockImplementation(async () => ({ ok: true, command: "tsc", logTail: "" }));
    },
    expect: (r, h) => {
      expect(r.summary.fixed).toBe(1);
      expect(h.implementCluster).toHaveBeenCalledTimes(3);
      expect(h.runVerify.mock.calls.length).toBeGreaterThanOrEqual(2);
    },
  },
  {
    name: "static check exhausted → static_check_failed",
    defects: [defect("d1", "fp-static-x")],
    options: { maxIterate: 2 },
    tweak: (h) => {
      h.runStaticCheck
        .mockImplementationOnce(async () => ({ ok: true, command: "tsc", logTail: "" }))
        .mockImplementation(async () => ({
          ok: false,
          command: "tsc",
          logTail: "TS2322",
        }));
    },
    expect: (r, h) => {
      expect(r.unfixed[0]?.reasonCode).toBe("static_check_failed");
      expect(h.deliverFix).not.toHaveBeenCalled();
    },
  },
  {
    name: "scope lock violation → implement_failed",
    defects: [defect("d1", "fp-scope")],
    options: {},
    tweak: (h) => {
      h.implementCluster.mockImplementation(async () => ({
        changedFiles: ["src/other.ts"],
        agentText: "ok",
        scopeOk: true,
        scopeViolations: [],
      }));
    },
    expect: (r) => {
      expect(r.unfixed[0]?.reasonCode).toBe("implement_failed");
      expect(r.unfixed[0]?.reasonDetail).toMatch(/src\/other\.ts/);
    },
  },
  {
    name: "reviewer rejects once, then approves",
    defects: [defect("d1", "fp-rev-ok")],
    options: { maxIterate: 3 },
    tweak: (h) => {
      h.reviewCluster
        .mockImplementationOnce(async () => ({
          decision: "request_changes" as const,
          reasons: ["missing null check"],
        }))
        .mockImplementation(async () => ({ decision: "approve" as const, reasons: [] }));
    },
    expect: (r, h) => {
      expect(r.summary.fixed).toBe(1);
      expect(h.implementCluster).toHaveBeenCalledTimes(3);
      const third = h.implementCluster.mock.calls[2]![0] as { verifyLogTail?: string };
      expect(third.verifyLogTail).toMatch(/missing null check/);
    },
  },
  {
    name: "reviewer rejection exhausted → review_failed",
    defects: [defect("d1", "fp-rev")],
    options: { maxIterate: 1 },
    tweak: (h) => {
      h.reviewCluster.mockImplementation(async () => ({
        decision: "request_changes" as const,
        reasons: ["scope creep"],
      }));
    },
    expect: (r, h) => {
      expect(r.unfixed[0]?.reasonCode).toBe("review_failed");
      expect(h.deliverFix).not.toHaveBeenCalled();
    },
  },
  {
    name: "missing GitLab token → push_failed",
    defects: [defect("d1", "fp-token")],
    options: { skipReviewer: true },
    token: null,
    expect: (r) => {
      expect(r.unfixed[0]?.reasonCode).toBe("push_failed");
    },
  },
  {
    name: "multiple clusters produce mixed outcomes in order",
    defects: [defect("d1", "fp-a"), defect("d2", "fp-b"), defect("d3", "fp-a")],
    options: { skipReviewer: true },
    tweak: (h) => {
      h.analyzeCluster
        .mockImplementationOnce(async () => ({ status: "fixable" as const, rootCause, solution }))
        .mockImplementation(async () => ({
          status: "unfixed" as const,
          reasonCode: "needs_more_context" as const,
          reasonDetail: "need logs",
        }));
    },
    expect: (r) => {
      expect(r.summary).toEqual({ totalClusters: 2, fixed: 1, unfixed: 1 });
      expect(r.fixed[0]?.defectIds.sort()).toEqual(["d1", "d3"]);
      expect(r.unfixed[0]?.defectIds).toEqual(["d2"]);
    },
  },
];

function stripRunId(report: RunReport) {
  const { runId: _runId, startedAt: _s, finishedAt: _f, engine: _e, ...rest } = report;
  const scrub = <T extends { durationMs?: number }>(row: T) => {
    const { durationMs: _d, ...kept } = row;
    return kept;
  };
  return {
    ...rest,
    fixed: rest.fixed.map(scrub),
    unfixed: rest.unfixed.map(scrub),
  };
}

describe("LangGraph engine parity with legacy pipeline", () => {
  const dirs: string[] = [];

  afterEach(async () => {
    vi.unstubAllEnvs();
    await Promise.all(dirs.splice(0).map((d) => rm(d, { recursive: true, force: true })));
  });

  async function run(engine: Engine, sc: Scenario) {
    const workDir = await mkdtemp(path.join(tmpdir(), `bugfix-${engine}-`));
    dirs.push(workDir);
    vi.stubEnv("GITLAB_TOKEN", "");
    const { runId } = await createRunDir(workDir);
    await writeInputDefects(workDir, runId, sc.defects, {
      workDir,
      defects: sc.defects,
      options: { ...sc.options, engine },
    });
    const h = baseHandlers(workDir);
    sc.tweak?.(h);
    const report = await runPipeline(workDir, runId, {
      handlers: h,
      gitlabToken: sc.token === null ? undefined : (sc.token ?? "glpat-x"),
    });
    return { report, h, workDir, runId };
  }

  for (const sc of scenarios) {
    it(sc.name, async () => {
      const legacy = await run("pipeline", sc);
      const graph = await run("langgraph", sc);

      sc.expect(legacy.report, legacy.h);
      sc.expect(graph.report, graph.h);

      const normalizeMr = (r: RunReport) =>
        JSON.parse(JSON.stringify(stripRunId(r)));
      expect(normalizeMr(graph.report)).toEqual(normalizeMr(legacy.report));
      for (const key of Object.keys(legacy.h) as (keyof Handlers)[]) {
        expect(graph.h[key].mock.calls.length, key).toBe(legacy.h[key].mock.calls.length);
      }

      const meta = await readMeta(graph.workDir, graph.runId);
      expect(meta.status).toBe("completed");
    });
  }
});

describe("invokeBugfixGraph (LangGraph-native entry)", () => {
  let workDir: string;

  afterEach(async () => {
    if (workDir) await rm(workDir, { recursive: true, force: true });
  });

  it("creates a run directory when runId is omitted and persists the report", async () => {
    workDir = await mkdtemp(path.join(tmpdir(), "bugfix-native-"));
    const report = await invokeBugfixGraph(
      { workDir, defects: [defect("d1", "fp-native")], options: { skipReviewer: true } },
      { handlers: baseHandlers(workDir), gitlabToken: "glpat-x" },
    );

    expect(report.summary.fixed).toBe(1);
    const meta = await readMeta(workDir, report.runId);
    expect(meta.status).toBe("completed");
    const saved = JSON.parse(
      await readFile(path.join(workDir, ".bugfix-runs", report.runId, "report.json"), "utf8"),
    );
    expect(saved).toEqual(report);
  });

  it("handles more clusters than the default recursion limit and checkpoints state", async () => {
    workDir = await mkdtemp(path.join(tmpdir(), "bugfix-native-many-"));
    const defects = Array.from({ length: 30 }, (_, i) => defect(`d${i}`, `fp-${i}`));
    const checkpointer = new MemorySaver();
    const thread = { configurable: { thread_id: "t-many" } };
    const report = await invokeBugfixGraph(
      { workDir, defects, options: { skipReviewer: true } },
      { handlers: baseHandlers(workDir), gitlabToken: "glpat-x", checkpointer },
      thread,
    );
    expect(report.summary).toEqual({ totalClusters: 30, fixed: 30, unfixed: 0 });

    const snapshot = await createBugfixGraph({ checkpointer }).getState(thread);
    expect(snapshot.values.report).toEqual(report);
    expect(snapshot.next).toEqual([]);
  });

  it("rejects invalid input via the request schema", async () => {
    workDir = await mkdtemp(path.join(tmpdir(), "bugfix-native-bad-"));
    await expect(
      invokeBugfixGraph({ workDir, defects: [] }, { handlers: baseHandlers(workDir) }),
    ).rejects.toThrow();
  });
});
