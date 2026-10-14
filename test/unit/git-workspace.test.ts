import { describe, expect, it, vi } from "vitest";
import { ensureRepo, redactSecrets } from "../../src/workspace/git.js";

describe("ensureRepo", () => {
  it("calls git clone with tokenized https url when repo missing", async () => {
    const calls: { file: string; args: string[] }[] = [];
    const execFileFn = vi.fn(async (file: string, args: string[]) => {
      calls.push({ file, args });
      if (args[0] === "rev-parse") {
        return { stdout: "abc123\n", stderr: "" };
      }
      return { stdout: "", stderr: "" };
    });

    // Force clone path: access will fail for .git — use fake workDir
    const result = await ensureRepo({
      workDir: "D:/tmp/work",
      repoUrl: "https://gitlab.com/org/app.git",
      branch: "main",
      token: "glpat-secret",
      execFileFn,
    });

    expect(result.headSha).toBe("abc123");
    const clone = calls.find((c) => c.args[0] === "clone");
    expect(clone).toBeTruthy();
    expect(clone!.args).toContain("--branch");
    expect(clone!.args).toContain("main");
    const urlArg = clone!.args.find((a) => a.includes("gitlab.com"));
    expect(urlArg).toContain("oauth2");
    expect(urlArg).toContain("glpat-secret");
    expect(redactSecrets(urlArg!, "glpat-secret")).not.toContain("glpat-secret");
  });
});
