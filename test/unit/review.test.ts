import { describe, expect, it } from "vitest";
import { parseReviewResult, reviewCluster } from "../../src/pipeline/review.js";
import { buildSdkOptions } from "../../src/agent/sdk-runner.js";

describe("review", () => {
  it("parses approve JSON", () => {
    const r = parseReviewResult('{"decision":"approve","reasons":["looks good"]}');
    expect(r.decision).toBe("approve");
    expect(r.reasons[0]).toContain("looks good");
  });

  it("parses request_changes", () => {
    const r = parseReviewResult(
      'Here is my review:\n{"decision":"request_changes","reasons":["scope creep"]}\n',
    );
    expect(r.decision).toBe("request_changes");
  });

  it("review mode excludes Edit", () => {
    const opts = buildSdkOptions({
      cwd: "/tmp",
      prompt: "review",
      mode: "review",
    });
    expect(opts.options.allowedTools).not.toContain("Edit");
    expect(opts.options.allowedTools).toContain("Read");
  });

  it("mockResult short-circuits SDK", async () => {
    const r = await reviewCluster({
      repoPath: "/tmp",
      rootCause: {
        headline: "h",
        one_line_description: "d",
        five_whys: [],
        reproduction_steps: [],
        fixability: { assessment: "fixable", reason: "r" },
      },
      solution: {
        one_line_summary: "s",
        steps: [{ title: "t", description: "d" }],
      },
      verifyCommand: "npm test",
      iteration: 1,
      mockResult: { decision: "approve", reasons: ["ok"] },
    });
    expect(r.decision).toBe("approve");
  });
});
