import { describe, expect, it } from "vitest";
import { parseSolutionText } from "../../src/agent/artifacts.js";
import { analyzeCluster, buildSolutionRepairPrompt } from "../../src/pipeline/analyze.js";
import type { RunAgentSessionInput } from "../../src/agent/sdk-runner.js";

const rootCause = {
  headline: "nested right operand loses its matrix",
  one_line_description: "_cstack assigns 1 instead of the right matrix",
  five_whys: ["the right block is overwritten"],
  reproduction_steps: ["call separability_matrix"],
  hypothesis: "Assign the right ndarray in astropy/modeling/separable.py.",
  evidence: ["astropy/modeling/separable.py:245 assigns 1"],
  fixability: { assessment: "fixable" as const, reason: "one assignment" },
};

const rootBlock = `ROOT_CAUSE\n${JSON.stringify(rootCause)}`;

function runner(replies: string[]) {
  const calls: RunAgentSessionInput[] = [];
  const sessionRunner = async (input: RunAgentSessionInput) => {
    calls.push(input);
    const text = replies[calls.length - 1];
    if (text === undefined) throw new Error("unexpected session");
    return { text };
  };
  return { calls, sessionRunner };
}

describe("solution artifact recovery", () => {
  it("coerces string steps into title and description", () => {
    const text = `SOLUTION
{"one_line_summary":"copy the matrix","steps":["assign right instead of 1"],"files":["astropy/modeling/separable.py"]}`;
    expect(parseSolutionText(text)).toEqual({
      one_line_summary: "copy the matrix",
      steps: [{ title: "Step 1", description: "assign right instead of 1" }],
      target_files: ["astropy/modeling/separable.py"],
    });
  });

  it("asks once for a schema-valid solution when the first reply has only a fixable root cause", async () => {
    const { calls, sessionRunner } = runner([
      rootBlock,
      JSON.stringify({
        one_line_summary: "copy the right matrix",
        steps: [{ title: "fix assignment", description: "use right instead of 1" }],
        target_files: ["astropy/modeling/separable.py"],
      }),
    ]);
    const result = await analyzeCluster({
      cluster: {
        id: "c1",
        defectIds: ["d1"],
        repoUrl: "https://github.com/astropy/astropy.git",
        primaryTitle: "separability",
      },
      defects: [
        {
          id: "d1",
          title: "separability",
          repoUrl: "https://github.com/astropy/astropy.git",
        },
      ],
      repoPath: "D:/no/such/repo",
      sessionRunner,
    });
    expect(result.status).toBe("fixable");
    if (result.status === "fixable") {
      expect(result.solution.target_files).toEqual(["astropy/modeling/separable.py"]);
      expect(result.localization.editTargets).toEqual(["astropy/modeling/separable.py"]);
    }
    expect(calls).toHaveLength(2);
    expect(calls[1]?.maxTurns).toBe(2);
    expect(calls[1]?.disallowedTools).toEqual(
      expect.arrayContaining(["Read", "Grep", "Edit", "Write"]),
    );
    expect(calls[1]?.prompt).toContain("Missing SOLUTION JSON object");
    expect(result.agentTranscript).toContain("--- solution repair ---");
  });

  it("does not open a repair turn when the root cause is not fixable", async () => {
    const blocked = {
      ...rootCause,
      fixability: { assessment: "needs_more_context" as const, reason: "no file evidence" },
    };
    const { calls, sessionRunner } = runner([`ROOT_CAUSE\n${JSON.stringify(blocked)}`]);
    const result = await analyzeCluster({
      cluster: {
        id: "c1",
        defectIds: ["d1"],
        repoUrl: "https://github.com/astropy/astropy.git",
        primaryTitle: "separability",
      },
      defects: [
        {
          id: "d1",
          title: "separability",
          repoUrl: "https://github.com/astropy/astropy.git",
        },
      ],
      repoPath: "D:/no/such/repo",
      sessionRunner,
    });
    expect(result.status).toBe("unfixed");
    if (result.status === "unfixed") expect(result.reasonCode).toBe("needs_more_context");
    expect(calls).toHaveLength(1);
  });

  it("keeps the parser error when the repair reply is still not a solution", async () => {
    const { sessionRunner } = runner([rootBlock, "I would change the assignment."]);
    const result = await analyzeCluster({
      cluster: {
        id: "c1",
        defectIds: ["d1"],
        repoUrl: "https://github.com/astropy/astropy.git",
        primaryTitle: "separability",
      },
      defects: [
        {
          id: "d1",
          title: "separability",
          repoUrl: "https://github.com/astropy/astropy.git",
        },
      ],
      repoPath: "D:/no/such/repo",
      sessionRunner,
    });
    expect(result.status).toBe("unfixed");
    if (result.status === "unfixed") {
      expect(result.reasonCode).toBe("analyze_failed");
      expect(result.reasonDetail).toContain("Missing SOLUTION JSON object");
      expect(result.reasonDetail).toContain("repair failed");
      expect(result.agentTranscript).toContain("I would change the assignment.");
    }
  });

  it("repair prompt forbids a new hypothesis", () => {
    const prompt = buildSolutionRepairPrompt(rootCause, "steps must be objects");
    expect(prompt).toContain("steps must be objects");
    expect(prompt).toMatch(/Do not invent files/i);
    expect(prompt).toContain("astropy/modeling/separable.py");
  });
});
