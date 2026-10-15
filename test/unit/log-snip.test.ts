import { describe, expect, it } from "vitest";
import { snipVerifyLog } from "../../src/pipeline/log-snip.js";

describe("snipVerifyLog", () => {
  it("keeps AssertionError and drops npm noise", () => {
    const noise = Array.from({ length: 40 }, (_, i) => `npm notice line ${i}`).join("\n");
    const raw = `${noise}\nAssertionError: expected true\n    at src/a.ts:1\n${noise}`;
    const snip = snipVerifyLog(raw, 800);
    expect(snip).toContain("AssertionError");
    expect(snip.length).toBeLessThan(raw.length);
    expect(snip).not.toMatch(/npm notice line 0/);
  });

  it("respects maxChars", () => {
    const raw = `FAIL\n${"x".repeat(5000)}`;
    expect(snipVerifyLog(raw, 100).length).toBeLessThanOrEqual(100);
  });
});
