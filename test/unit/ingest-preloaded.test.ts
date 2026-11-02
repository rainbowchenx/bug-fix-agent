import { describe, expect, it } from "vitest";
import { writeFile, mkdtemp } from "node:fs/promises";
import path from "node:path";
import os from "node:os";
import { ingestRawDefects } from "../../src/ingest/index.js";

describe("ingest preloaded", () => {
  it("loads inline array", async () => {
    const r = await ingestRawDefects({
      mode: "preloaded",
      productLine: "hc",
      source: [{ defectId: "1", title: "t" }],
    });
    expect(r.defects).toHaveLength(1);
    expect(r.mode).toBe("preloaded");
  });

  it("loads JSON file", async () => {
    const dir = await mkdtemp(path.join(os.tmpdir(), "raw-defects-"));
    const file = path.join(dir, "raw.json");
    await writeFile(
      file,
      JSON.stringify({
        productLine: "led",
        defects: [{ defectId: "a", title: "【校正】应禁用" }],
      }),
      "utf8",
    );
    const r = await ingestRawDefects({ mode: "preloaded", source: file });
    expect(r.productLine).toBe("led");
    expect(r.defects[0]?.title).toContain("校正");
  });

  it("mcp stub throws until configured", async () => {
    await expect(ingestRawDefects({ mode: "mcp", productLine: "x" })).rejects.toThrow(/not configured/);
  });
});
