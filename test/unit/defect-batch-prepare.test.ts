import { describe, expect, it } from "vitest";
import { prepareDefectBatch } from "../../src/defect-batch/prepare.js";
import { runDefectBatchPrepare } from "../../src/defect-batch/run.js";
import { safeValidateDefectBatch } from "../../src/defect-batch/validate.js";
import type { RawDefect } from "../../src/defect-batch/types.js";

const samples: RawDefect[] = [
  {
    defectId: "1",
    title: "【预览】进度条应显示在底部",
    description: "预期结果：进度条应显示在预览画面底部\n实际结果：显示到顶部遮挡",
    status: "Open",
    testModule: "预览",
  },
  {
    defectId: "2",
    title: "【预览】文案未翻译",
    description: "预期结果：应显示中文词条\n实际结果：显示英文 key",
    status: "New",
    testModule: "预览",
  },
  {
    defectId: "3",
    title: "【列表】筛选后条数与预期不一致",
    description: "实际结果：筛选后列表条数与预期不一致",
    status: "Open",
    testModule: "列表",
  },
  {
    defectId: "4",
    title: "[安全] CVE-2024-1",
    description: "软件成分分析 CVE-2024-1",
    status: "Open",
  },
  {
    defectId: "5",
    title: "列表为空",
    description: "预期结果：应有数据\n实际结果：脏数据导致为空",
    status: "Open",
    testModule: "列表",
  },
];

describe("defect-batch prepare", () => {
  it("builds validated batch with clusters for strict only", async () => {
    const batch = await prepareDefectBatch({
      productLine: "demo",
      posture: "beta",
      defects: samples,
      now: () => "2026-11-02T00:00:00.000Z",
    });

    expect(batch.schemaVersion).toBe("0.1.0");
    expect(batch.funnel.strict).toBeGreaterThanOrEqual(2);
    expect(batch.funnel.security).toBe(1);
    expect(batch.funnel.hard_reject).toBe(1);
    expect(batch.funnel.locatable_only).toBe(1);

    const strictTickets = batch.tickets.filter((t) => t.pool === "strict");
    expect(strictTickets.every((t) => t.clusterId && t.intent)).toBe(true);
    expect(batch.clusters.length).toBeGreaterThanOrEqual(1);
    expect(batch.clusters.every((c) => c.defectIds.length > 0)).toBe(true);

    const checked = safeValidateDefectBatch(batch);
    expect(checked.ok).toBe(true);
  });

  it("runDefectBatchPrepare works with preloaded payload", async () => {
    const batch = await runDefectBatchPrepare({
      mode: "preloaded",
      productLine: "demo",
      source: { productLine: "demo", defects: samples },
      posture: "alpha",
    });
    expect(batch.tickets).toHaveLength(samples.length);
  });
});
