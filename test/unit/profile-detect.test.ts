import { mkdtemp, mkdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { detectProfile, resolveVerifyPlan } from "../../src/profiles/detect.js";

describe("profile detect", () => {
  let root: string;

  afterEach(async () => {
    if (root) await rm(root, { recursive: true, force: true });
  });

  it("detects vue+vite as node-web", async () => {
    root = await mkdtemp(path.join(tmpdir(), "bugfix-prof-"));
    const repo = path.join(root, "app");
    await mkdir(repo);
    await writeFile(
      path.join(repo, "package.json"),
      JSON.stringify({
        name: "app",
        dependencies: { vue: "^3.0.0" },
        devDependencies: { vite: "^5.0.0", vitest: "^2.0.0" },
        scripts: { test: "vitest run" },
      }),
    );
    await writeFile(path.join(repo, "vite.config.ts"), "export default {}");
    expect(await detectProfile(repo)).toBe("node-web");

    const plan = await resolveVerifyPlan({ repoPath: repo });
    expect(plan.profileId).toBe("node-web");
    expect(plan.test).toContain("npm test");
  });

  it("detects electron dependency", async () => {
    root = await mkdtemp(path.join(tmpdir(), "bugfix-prof-"));
    const repo = path.join(root, "app");
    await mkdir(repo);
    await writeFile(
      path.join(repo, "package.json"),
      JSON.stringify({
        name: "desk",
        dependencies: { electron: "^30.0.0" },
        scripts: { test: "vitest run" },
      }),
    );
    expect(await detectProfile(repo)).toBe("electron");
  });
});
