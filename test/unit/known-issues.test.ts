import { describe, expect, it } from "vitest";
import { buildKnownIssuesDetail } from "../../src/pipeline/known-issues.js";

describe("known issues detail", () => {
  it("includes budget exhausted framing and log tail", () => {
    const text = buildKnownIssuesDetail({
      iterations: 3,
      maxIterate: 3,
      verifyCommand: "npm test",
      logTail: "AssertionError: expected true",
      rootCauseSummary: "null deref",
      solutionSummary: "add guard",
    });
    expect(text).toMatch(/Known Issues/i);
    expect(text).toMatch(/budget exhausted/i);
    expect(text).toContain("null deref");
    expect(text).toContain("AssertionError");
  });
});
