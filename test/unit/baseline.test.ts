import { describe, expect, it } from "vitest";
import { isNewFailure } from "../../src/pipeline/baseline.js";

describe("baseline diff", () => {
  const snap = (ok: boolean, logTail: string) => ({ ok, command: "tsc", logTail });

  it("ignores the same pre-existing lint error", () => {
    const base = snap(false, "src/a.ts(1,1): error TS2322: bad");
    const cur = snap(false, "src/a.ts(1,1): error TS2322: bad");
    expect(isNewFailure(base, cur)).toBe(false);
  });

  it("flags a new error on top of a red baseline", () => {
    const base = snap(false, "error TS2322: bad");
    const cur = snap(false, "error TS2322: bad\nerror TS2339: missing");
    expect(isNewFailure(base, cur)).toBe(true);
  });

  it("flags any failure when baseline was green", () => {
    expect(isNewFailure(snap(true, ""), snap(false, "AssertionError: x"))).toBe(true);
  });
});
