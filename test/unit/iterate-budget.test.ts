import { describe, expect, it } from "vitest";
import { shouldContinueIterate } from "../../src/pipeline/implement.js";

describe("iterate budget", () => {
  it("stops when verify ok", () => {
    expect(shouldContinueIterate(1, 3, true)).toBe(false);
  });

  it("continues while under max and failing", () => {
    expect(shouldContinueIterate(1, 3, false)).toBe(true);
    expect(shouldContinueIterate(2, 3, false)).toBe(true);
  });

  it("stops at maxIterate", () => {
    expect(shouldContinueIterate(3, 3, false)).toBe(false);
  });
});
