import { describe, expect, it } from "vitest";
import { safeSync } from "../../src/storage/adapter.js";
import { noopStorage } from "../../src/storage/noop.js";

describe("noop storage", () => {
  it("sync methods resolve", async () => {
    await expect(
      noopStorage.syncProgress?.({
        runId: "r",
        workDir: "/tmp",
        status: "running",
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
      }),
    ).resolves.toBeUndefined();
  });

  it("best_effort swallows errors", async () => {
    await expect(
      safeSync("best_effort", async () => {
        throw new Error("network");
      }),
    ).resolves.toBeUndefined();
  });

  it("required rethrows", async () => {
    await expect(
      safeSync("required", async () => {
        throw new Error("network");
      }),
    ).rejects.toThrow("network");
  });
});
