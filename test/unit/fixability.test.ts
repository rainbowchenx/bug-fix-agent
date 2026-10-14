import { describe, expect, it } from "vitest";
import { gateFromFixability } from "../../src/pipeline/fixability.js";

describe("fixability gate", () => {
  it("allows fixable", () => {
    expect(
      gateFromFixability({ assessment: "fixable", reason: "clear patch" }),
    ).toEqual({ status: "fixable" });
  });

  it("maps needs_more_context to unfixed", () => {
    const g = gateFromFixability({
      assessment: "needs_more_context",
      reason: "missing logs",
    });
    expect(g).toEqual({
      status: "unfixed",
      reasonCode: "needs_more_context",
      reasonDetail: "missing logs",
    });
  });

  it("maps not_actionable to unfixed", () => {
    const g = gateFromFixability({
      assessment: "not_actionable",
      reason: "config only",
    });
    expect(g.status).toBe("unfixed");
    if (g.status === "unfixed") {
      expect(g.reasonCode).toBe("not_actionable");
    }
  });
});
