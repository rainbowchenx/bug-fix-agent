import { mkdtemp, mkdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  resolveStaticCheckPlan,
  runStaticCheck,
} from "../../src/pipeline/static-check.js";

describe("static-check", () => {
  let root: string;

  afterEach(async () => {
    if (root) await rm(root, { recursive: true, force: true });
  });

  it("detects typecheck and lint scripts", async () => {
    root = await mkdtemp(path.join(tmpdir(), "bugfix-static-"));
    const repo = path.join(root, "app");
    await mkdir(repo);
    await writeFile(
      path.join(repo, "package.json"),
      JSON.stringify({
        scripts: { typecheck: "tsc --noEmit", lint: "eslint ." },
        devDependencies: { typescript: "^5", eslint: "^9" },
      }),
    );
    const plan = await resolveStaticCheckPlan(repo);
    expect(plan.commands).toContain("npm run typecheck");
    expect(plan.commands).toContain("npm run lint");
  });

  it("skips when no scripts/deps", async () => {
    root = await mkdtemp(path.join(tmpdir(), "bugfix-static-"));
    const repo = path.join(root, "app");
    await mkdir(repo);
    await writeFile(path.join(repo, "package.json"), JSON.stringify({ name: "x" }));
    expect((await resolveStaticCheckPlan(repo)).commands).toEqual([]);
  });

  it("runStaticCheck returns not ok on exec failure", async () => {
    const execFn = vi.fn(async () => {
      throw Object.assign(new Error("fail"), { stderr: "tsc error", stdout: "" });
    });
    const result = await runStaticCheck(
      "/tmp",
      { commands: ["npx tsc --noEmit"] },
      execFn as never,
    );
    expect(result.ok).toBe(false);
    expect(result.logTail).toContain("tsc error");
  });
});
