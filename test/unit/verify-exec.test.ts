import { describe, expect, it, vi } from "vitest";
import { runVerify } from "../../src/pipeline/verify.js";

describe("runVerify", () => {
  it("returns ok when command succeeds", async () => {
    const execFn = vi.fn(async () => ({ stdout: "ok", stderr: "" }));
    const result = await runVerify("/tmp/repo", { test: ["npm test"] }, execFn as never);
    expect(result.ok).toBe(true);
    expect(result.command).toBe("npm test");
  });

  it("returns not ok when command throws", async () => {
    const execFn = vi.fn(async () => {
      const err = new Error("fail") as Error & { stdout: string; stderr: string };
      err.stdout = "";
      err.stderr = "boom";
      throw err;
    });
    const result = await runVerify("/tmp/repo", { test: ["npm test"] }, execFn as never);
    expect(result.ok).toBe(false);
    expect(result.logTail).toContain("boom");
  });
});
