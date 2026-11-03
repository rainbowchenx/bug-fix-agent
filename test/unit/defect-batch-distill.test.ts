import { describe, expect, it } from "vitest";
import {
  distillDefect,
  extractTitleTag,
  normalizeTestModule,
  splitDescription,
} from "../../src/defect-batch/distill.js";

describe("defect-batch distill", () => {
  it("extracts title tags from 【】 and []", () => {
    expect(extractTitleTag("【回放】卡顿")).toBe("回放");
    expect(extractTitleTag("[AI助手] 失败")).toBe("AI助手");
    expect(extractTitleTag("无括注标题")).toBe("_untagged");
  });

  it("normalizes test module and marks semantic-free", () => {
    expect(normalizeTestModule("预览优化v2.2").testModule).toBe("预览");
    expect(normalizeTestModule(undefined).testModule).toBe("_unmoduled");
    expect(normalizeTestModule("系统").semanticFree).toBe(true);
    expect(normalizeTestModule("【专项测试】foo").semanticFree).toBe(true);
  });

  it("splits description template sections", () => {
    const parts = splitDescription(
      "复现步骤：点开预览\n预期结果：应显示进度条\n实际结果：顶部被遮挡",
    );
    expect(parts.steps).toContain("点开预览");
    expect(parts.expected).toContain("应显示进度条");
    expect(parts.observed).toContain("顶部被遮挡");
  });

  it("builds digest with duplicate flag", () => {
    const d = distillDefect({
      defectId: "1",
      title: "【预览】显示异常",
      description: "预期结果：应显示完整\n实际结果：显示不全靠左",
      testModule: "预览",
      duplicateOf: "0",
    });
    expect(d.duplicate).toBe(true);
    expect(d.titleTag).toBe("预览");
    expect(d.testModule).toBe("预览");
  });
});
