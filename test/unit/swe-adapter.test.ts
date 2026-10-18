import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  createSweDeliverFix,
  githubRepoUrl,
  loadSweInstances,
  mapInstanceToDefect,
  mapInstanceToRequest,
} from "../../adapters/swe-bench/index.js";

describe("swe-bench adapter (decoupled)", () => {
  let root: string;

  afterEach(async () => {
    if (root) await rm(root, { recursive: true, force: true });
  });

  it("maps instance to core Defect without SWE fields on the type surface", () => {
    const defect = mapInstanceToDefect({
      instance_id: "astropy__astropy-12907",
      repo: "astropy/astropy",
      base_commit: "abc123",
      problem_statement: "Fix the bug",
      FAIL_TO_PASS: '["astropy/tests/test_x.py::test_y"]',
    });
    expect(defect.id).toBe("astropy__astropy-12907");
    expect(defect.repoUrl).toBe("https://github.com/astropy/astropy.git");
    expect(defect.fingerprint).toBe("astropy__astropy-12907");
    expect(defect.metadata?.base_commit).toBe("abc123");
    expect(githubRepoUrl("https://github.com/foo/bar.git")).toBe(
      "https://github.com/foo/bar.git",
    );
  });

  it("builds request with pytest override from FAIL_TO_PASS", () => {
    const req = mapInstanceToRequest("/tmp/w", {
      instance_id: "x",
      repo: "a/b",
      base_commit: "c",
      problem_statement: "p",
      FAIL_TO_PASS: ["pkg/test_a.py::test_b"],
    });
    expect(req.defects).toHaveLength(1);
    expect(req.options?.verifyOverrides?.test?.[0]).toContain("pytest");
    expect(req.options?.verifyOverrides?.test?.[0]).toContain("pkg/test_a.py::test_b");
    expect(req.options?.skipReviewer).toBe(true);
  });

  it("loads jsonl instances", async () => {
    root = await mkdtemp(path.join(tmpdir(), "swe-load-"));
    const file = path.join(root, "i.jsonl");
    await writeFile(
      file,
      `${JSON.stringify({
        instance_id: "id1",
        repo: "o/r",
        base_commit: "sha",
        problem_statement: "bug",
      })}\n`,
    );
    const list = await loadSweInstances(file);
    expect(list).toHaveLength(1);
    expect(list[0]?.instance_id).toBe("id1");
  });

  it("deliverFix writes predictions.jsonl and never calls GitLab", async () => {
    root = await mkdtemp(path.join(tmpdir(), "swe-pred-"));
    const pred = path.join(root, "predictions.jsonl");
    const deliver = createSweDeliverFix({
      instance: {
        instance_id: "id-1",
        repo: "o/r",
        base_commit: "base",
        problem_statement: "p",
      },
      predictionsPath: pred,
      modelName: "test-model",
      execFileFn: vi.fn(async (_f: string, args: string[]) => {
        if (args.includes("--name-only") || args.includes("ls-files")) {
          return { stdout: "src/a.py\n", stderr: "" };
        }
        if (args[0] === "diff") {
          return {
            stdout: "diff --git a/src/a.py b/src/a.py\n+fixed\n",
            stderr: "",
          };
        }
        return { stdout: "", stderr: "" };
      }),
    });

    const result = await deliver({
      repoPath: "/tmp/repo",
      runId: "r",
      clusterId: "c",
      title: "t",
      description: "d",
      gitlabHost: "https://gitlab.com",
      token: "ignored",
      repoUrl: "https://github.com/o/r.git",
      baseSha: "base",
    });

    expect(result.mrUrl).toBe("swe-patch://id-1");
    const line = (await readFile(pred, "utf8")).trim();
    const row = JSON.parse(line) as {
      instance_id: string;
      model_patch: string;
      model_name_or_path: string;
    };
    expect(row.instance_id).toBe("id-1");
    expect(row.model_name_or_path).toBe("test-model");
    expect(row.model_patch).toContain("+fixed");
  });
});
