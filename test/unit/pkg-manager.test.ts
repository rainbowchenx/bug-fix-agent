import { mkdtemp, mkdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import {
  detectPackageManager,
  resolveVerifyPlan,
} from "../../src/profiles/detect.js";

describe("package manager detect", () => {
  let root: string;

  afterEach(async () => {
    if (root) await rm(root, { recursive: true, force: true });
  });

  it("detects pnpm from lockfile", async () => {
    root = await mkdtemp(path.join(tmpdir(), "bugfix-pm-"));
    const repo = path.join(root, "app");
    await mkdir(repo);
    await writeFile(path.join(repo, "package.json"), JSON.stringify({ scripts: { test: "vitest" } }));
    await writeFile(path.join(repo, "pnpm-lock.yaml"), "lockfileVersion: '9'");
    expect(await detectPackageManager(repo)).toBe("pnpm");
    const plan = await resolveVerifyPlan({ repoPath: repo });
    expect(plan.install[0]).toContain("pnpm");
  });

  it("detects yarn from lockfile", async () => {
    root = await mkdtemp(path.join(tmpdir(), "bugfix-pm-"));
    const repo = path.join(root, "app");
    await mkdir(repo);
    await writeFile(path.join(repo, "package.json"), JSON.stringify({ scripts: { test: "jest" } }));
    await writeFile(path.join(repo, "yarn.lock"), "# yarn");
    expect(await detectPackageManager(repo)).toBe("yarn");
    const plan = await resolveVerifyPlan({ repoPath: repo });
    expect(plan.install[0]).toContain("yarn");
  });

  it("uses npm ci when package-lock present", async () => {
    root = await mkdtemp(path.join(tmpdir(), "bugfix-pm-"));
    const repo = path.join(root, "app");
    await mkdir(repo);
    await writeFile(path.join(repo, "package.json"), JSON.stringify({ scripts: { test: "node test.js" } }));
    await writeFile(path.join(repo, "package-lock.json"), "{}");
    const plan = await resolveVerifyPlan({ repoPath: repo });
    expect(plan.install[0]).toBe("npm ci");
  });
});
