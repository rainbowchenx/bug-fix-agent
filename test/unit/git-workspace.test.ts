import { describe, expect, it, vi } from "vitest";
import { ensureRepo, redactSecrets } from "../../src/workspace/git.js";

describe("ensureRepo", () => {
  it("clones with auth header and adds detach worktree", async () => {
    const calls: { file: string; args: string[] }[] = [];
    const execFileFn = vi.fn(async (file: string, args: string[]) => {
      calls.push({ file, args });
      if (args.includes("rev-parse")) {
        return { stdout: "abc123\n", stderr: "" };
      }
      return { stdout: "", stderr: "" };
    });

    const result = await ensureRepo({
      workDir: "D:/tmp/work",
      runId: "run-1",
      clusterId: "c1",
      repoUrl: "https://gitlab.com/org/app.git",
      branch: "main",
      token: "glpat-secret",
      execFileFn,
    });

    expect(result.baseSha).toBe("abc123");
    expect(result.repoPath).toContain("worktrees");
    const clone = calls.find((c) => c.args.includes("clone"));
    expect(clone).toBeTruthy();
    expect(clone!.args.some((a) => a.includes("Authorization: Bearer"))).toBe(true);
    expect(clone!.args.join(" ")).not.toContain("oauth2:glpat");
    const wt = calls.find((c) => c.args[0] === "worktree");
    expect(wt).toBeTruthy();
    expect(redactSecrets("tok glpat-secret", "glpat-secret")).not.toContain("glpat-secret");
  });
});
