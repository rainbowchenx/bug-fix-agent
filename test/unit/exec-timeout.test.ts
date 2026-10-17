import { describe, expect, it } from "vitest";
import { ExecTimeoutError, timedExec } from "../../src/util/exec.js";

describe("timedExec timeout", () => {
  it("kills long-running sleep and throws ExecTimeoutError", async () => {
    const cmd =
      process.platform === "win32"
        ? "powershell -Command Start-Sleep -Seconds 999"
        : "sleep 999";
    await expect(
      timedExec(cmd, { cwd: process.cwd(), timeoutMs: 800 }),
    ).rejects.toBeInstanceOf(ExecTimeoutError);
  }, 15_000);
});
