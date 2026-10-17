import { execFile as execFileCb } from "node:child_process";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { promisify } from "node:util";
import { afterEach, describe, expect, it, vi } from "vitest";
import { deliverFix } from "../../src/pipeline/deliver.js";
import { runVerify } from "../../src/pipeline/verify.js";
import { createRunDir, writeInputDefects } from "../../src/runs/store.js";
import { runPipeline } from "../../src/runs/runner.js";
import type { Defect } from "../../src/types.js";
import { listChangedFiles } from "../../src/workspace/diff.js";
import { ensureRepo } from "../../src/workspace/git.js";

const execFile = promisify(execFileCb);

async function git(cwd: string, args: string[]): Promise<string> {
  const { stdout } = await execFile("git", args, { cwd });
  return stdout.trim();
}

describe("e2e bare remote + mock MR", () => {
  let root: string;

  afterEach(async () => {
    if (root) await rm(root, { recursive: true, force: true });
  });

  it("writes fix, runs real npm test, pushes to bare, opens mock MR", async () => {
    root = await mkdtemp(path.join(tmpdir(), "bugfix-e2e-"));
    const source = path.join(root, "source");
    const bare = path.join(root, "remote.git");
    const workDir = path.join(root, "work");
    await mkdir(source, { recursive: true });
    await mkdir(workDir, { recursive: true });

    await writeFile(
      path.join(source, "package.json"),
      JSON.stringify({
        name: "e2e-fixture",
        private: true,
        scripts: { test: "node --test test/sum.test.js" },
      }),
    );
    await mkdir(path.join(source, "src"));
    await mkdir(path.join(source, "test"));
    // Buggy: subtracts instead of adds
    await writeFile(path.join(source, "src", "sum.js"), "exports.sum = (a, b) => a - b;\n");
    await writeFile(
      path.join(source, "test", "sum.test.js"),
      `const { test } = require("node:test");
const assert = require("node:assert/strict");
const { sum } = require("../src/sum.js");
test("sum", () => { assert.equal(sum(2, 3), 5); });
`,
    );

    await git(source, ["init"]);
    await git(source, ["config", "user.email", "e2e@local"]);
    await git(source, ["config", "user.name", "e2e"]);
    await git(source, ["add", "-A"]);
    await git(source, ["commit", "-m", "init"]);
    await git(source, ["branch", "-M", "main"]);
    await execFile("git", ["clone", "--bare", source, bare]);

    const defects: Defect[] = [
      {
        id: "e2e-1",
        title: "sum returns wrong value",
        repoUrl: bare.replace(/\\/g, "/"),
        fingerprint: "sum-wrong",
        branch: "main",
      },
    ];
    const { runId } = await createRunDir(workDir);
    await writeInputDefects(workDir, runId, defects, {
      workDir,
      defects,
      options: { skipReviewer: true, maxIterate: 1 },
    });

    const fetchFn = vi.fn(async () =>
      Response.json({
        web_url: "https://gitlab.example/org/app/-/merge_requests/42",
        iid: 42,
      }),
    );

    const report = await runPipeline(workDir, runId, {
      gitlabToken: "glpat-e2e",
      gitlabHost: "https://gitlab.example",
      handlers: {
        ensureRepo,
        prepareRepo: async () => ({ ok: true, logTail: "skip install" }),
        resolveVerifyPlan: async () => ({
          profileId: "node-lib",
          install: [],
          test: ["npm test"],
        }),
        resolveStaticCheckPlan: async () => ({ commands: [] }),
        runStaticCheck: async () => ({ ok: true, command: "", logTail: "" }),
        analyzeCluster: async () => ({
          status: "fixable",
          rootCause: {
            headline: "wrong operator",
            one_line_description: "sum subtracts",
            five_whys: ["operator"],
            reproduction_steps: ["npm test"],
            fixability: { assessment: "fixable", reason: "change - to +" },
          },
          solution: {
            one_line_summary: "use addition",
            steps: [{ title: "fix", description: "change operator" }],
            target_files: ["src/sum.js"],
          },
        }),
        implementCluster: async (input) => {
          await writeFile(
            path.join(input.repoPath, "src", "sum.js"),
            "exports.sum = (a, b) => a + b;\n",
          );
          const changedFiles = input.baseSha
            ? await listChangedFiles(input.repoPath, input.baseSha)
            : ["src/sum.js"];
          return {
            changedFiles,
            agentText: "fixed sum",
            scopeOk: true,
            scopeViolations: [],
          };
        },
        runVerify,
        deliverFix: async (input) =>
          deliverFix({
            ...input,
            projectId: "org/app",
            fetchFn,
          }),
      },
    });

    expect(report.summary.fixed).toBe(1);
    expect(report.summary.unfixed).toBe(0);
    expect(report.fixed[0]?.mrUrl).toContain("merge_requests/42");
    expect(fetchFn).toHaveBeenCalled();

    // Bare remote received the bugfix branch
    const branches = await git(bare, ["branch", "-a"]);
    expect(branches).toMatch(/bugfix\//);
  }, 120_000);
});
