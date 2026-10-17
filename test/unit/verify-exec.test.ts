import { describe, expect, it, vi } from "vitest";
import { runVerify } from "../../src/pipeline/verify.js";

vi.mock("../../src/util/exec.js", () => ({
  ExecTimeoutError: class ExecTimeoutError extends Error {
    constructor(cmd: string, ms: number) {
      super(`Command timed out after ${ms}ms: ${cmd}`);
      this.name = "ExecTimeoutError";
    }
  },
  timedExec: vi.fn(async (command: string) => {
    if (command.includes("fail")) {
      throw Object.assign(new Error("fail"), { stderr: "boom", stdout: "" });
    }
    return { stdout: "ok", stderr: "" };
  }),
}));

describe("runVerify", () => {
  it("returns ok when command succeeds", async () => {
    const result = await runVerify("/tmp/repo", { test: ["npm test"] }, 1000);
    expect(result.ok).toBe(true);
    expect(result.command).toBe("npm test");
  });

  it("returns not ok when command throws", async () => {
    const result = await runVerify("/tmp/repo", { test: ["fail test"] }, 1000);
    expect(result.ok).toBe(false);
    expect(result.logTail).toContain("boom");
  });
});
