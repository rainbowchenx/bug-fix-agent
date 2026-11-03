import { describe, expect, it } from "vitest";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { runDefectBatchPrepare, safeValidateDefectBatch } from "../../src/defect-batch/index.js";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const fx = (...p: string[]) => path.join(root, "test/fixtures/defect-batch", ...p);

describe("defect-batch fixtures from Excel demos", () => {
  it("hc1 alpha produces validated batch with mixed pools", async () => {
    const batch = await runDefectBatchPrepare({
      mode: "preloaded",
      productLine: "hc",
      posture: "alpha",
      source: fx("hc1-raw.json"),
    });
    expect(safeValidateDefectBatch(batch).ok).toBe(true);
    expect(batch.funnel.total).toBe(50);
    expect(batch.funnel.excluded).toBeGreaterThan(0); // Not a bug etc.
    expect(batch.tickets).toHaveLength(50);
    // strict clusters only contain strict tickets
    for (const c of batch.clusters) {
      for (const id of c.defectIds) {
        const t = batch.tickets.find((x) => x.defectId === id);
        expect(t?.pool).toBe("strict");
      }
    }
  });

  it("hcp xunjian beta keeps Open tickets in functional funnel", async () => {
    const batch = await runDefectBatchPrepare({
      mode: "preloaded",
      productLine: "hcp",
      posture: "beta",
      source: fx("hcp-xunjian-raw.json"),
    });
    expect(batch.funnel.total).toBe(30);
    expect(batch.funnel.security).toBeGreaterThan(0); // security bypasses beta Open filter
    // Functional pools (not security/excluded) must be Open/New under beta
    const functional = batch.tickets.filter(
      (t) => !["excluded", "security"].includes(t.pool),
    );
    expect(functional.length).toBeGreaterThan(0);
    expect(functional.every((t) => /^(?:Open|New)$/i.test(t.status ?? ""))).toBe(true);
  });

  it("hitools sample screens without throwing", async () => {
    const batch = await runDefectBatchPrepare({
      mode: "preloaded",
      productLine: "hitools",
      posture: "alpha",
      source: fx("hitools-sample80-raw.json"),
    });
    expect(batch.funnel.total).toBe(80);
    expect(batch.schemaVersion).toBe("0.1.0");
  });
});
