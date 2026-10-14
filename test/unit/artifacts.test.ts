import { describe, expect, it } from "vitest";
import {
  extractJsonObject,
  parseRootCause,
  parseSolution,
} from "../../src/agent/artifacts.js";

describe("RootCauseArtifact", () => {
  it("parses Seer-aligned root cause with fixability", () => {
    const rc = parseRootCause({
      headline: "Null crash in login handler",
      one_line_description: "user is undefined when session expired",
      five_whys: ["why crash", "why null", "why no guard"],
      reproduction_steps: ["open app", "expire session", "click login"],
      relevant_repo: "org/app",
      fixability: {
        assessment: "fixable",
        reason: "Add null check and redirect",
      },
    });
    expect(rc.fixability.assessment).toBe("fixable");
  });

  it("rejects unknown fixability assessment", () => {
    expect(() =>
      parseRootCause({
        headline: "x",
        one_line_description: "y",
        five_whys: [],
        fixability: { assessment: "maybe", reason: "nope" },
      }),
    ).toThrow();
  });
});

describe("SolutionArtifact", () => {
  it("requires at least one step", () => {
    const sol = parseSolution({
      one_line_summary: "Guard null user",
      steps: [{ title: "Add guard", description: "Check user before use" }],
    });
    expect(sol.steps).toHaveLength(1);
  });
});

describe("extractJsonObject", () => {
  it("pulls JSON from surrounding prose", () => {
    const raw = extractJsonObject('Here is the result:\n{"a":1}\nThanks');
    expect(raw).toEqual({ a: 1 });
  });
});
