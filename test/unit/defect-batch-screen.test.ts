import { describe, expect, it } from "vitest";
import { distillDefect } from "../../src/defect-batch/distill.js";
import { screenDigest } from "../../src/defect-batch/screen.js";

function dig(partial: {
  defectId?: string;
  title: string;
  description?: string;
  status?: string;
  testModule?: string;
}) {
  return distillDefect({
    defectId: partial.defectId ?? "d1",
    title: partial.title,
    description: partial.description ?? "",
    status: partial.status ?? "Open",
    testModule: partial.testModule,
  });
}

describe("defect-batch screen", () => {
  it("excludes Cancel / Not a bug", () => {
    const r = screenDigest(dig({ title: "x", status: "Cancel" }));
    expect(r.pool).toBe("excluded");
  });

  it("routes [安全] to security pool", () => {
    const r = screenDigest(dig({ title: "[安全] 依赖升级 CVE-2024-1", description: "CVE-2024-1" }));
    expect(r.pool).toBe("security");
  });

  it("hard-rejects SCA+CVE without security title when scanner+cve in body", () => {
    // title not [安全] but scanner+cve → R1 catches scanner → security first
    const r = screenDigest(
      dig({
        title: "组件漏洞",
        description: "软件成分分析发现 CVE-2024-1234",
      }),
    );
    expect(r.pool).toBe("security");
  });

  it("hard-rejects non-code dirty-env", () => {
    const r = screenDigest(
      dig({
        title: "列表为空",
        description: "预期结果：应有数据\n实际结果：脏数据导致列表为空",
      }),
    );
    expect(r.pool).toBe("hard_reject");
    expect(r.reasonCode).toMatch(/C3/);
  });

  it("marks needs_info for design-undefined", () => {
    const r = screenDigest(
      dig({
        title: "两端展示不一致建议统一拍板",
        description: "实际结果：两端不一致，需确认是否统一",
      }),
    );
    expect(r.pool).toBe("needs_info");
    expect(r.reasonCode).toBe("C2");
  });

  it("puts unique expect into strict", () => {
    const r = screenDigest(
      dig({
        title: "【预览】进度条应显示在底部",
        description: "预期结果：进度条应显示在预览画面底部\n实际结果：显示到顶部",
        testModule: "预览",
      }),
    );
    expect(r.pool).toBe("strict");
    expect(r.verdict).toBe("FIXABLE");
    expect(["explicit", "inferred"]).toContain(r.expectQuality);
  });

  it("puts ambiguous expect into locatable_only", () => {
    const r = screenDigest(
      dig({
        title: "【列表】筛选后条数与预期不一致",
        description: "实际结果：筛选后列表条数与预期不一致",
        testModule: "列表",
      }),
    );
    expect(r.verdict).toBe("FIXABLE");
    expect(r.pool).toBe("locatable_only");
  });

  it("beta posture excludes Closed", () => {
    const r = screenDigest(
      dig({
        title: "【预览】应显示完整",
        description: "预期结果：应显示完整\n实际结果：被截断",
        status: "Closed",
      }),
      { posture: "beta" },
    );
    expect(r.pool).toBe("excluded");
  });
});
