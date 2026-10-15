import { describe, expect, it } from "vitest";
import { buildAnalyzePrompt } from "../../src/pipeline/analyze.js";
import { buildImplementPrompt } from "../../src/pipeline/implement.js";

describe("P0 prompt discipline", () => {
  it("analyze prompt includes IRON LAW and failure modes", () => {
    const prompt = buildAnalyzePrompt({
      cluster: {
        id: "c1",
        defectIds: ["d1"],
        repoUrl: "https://gitlab.com/a/b.git",
        primaryTitle: "crash",
      },
      defects: [
        {
          id: "d1",
          title: "crash",
          repoUrl: "https://gitlab.com/a/b.git",
        },
      ],
      repoPath: "/tmp/repo",
    });
    expect(prompt).toMatch(/IRON LAW/i);
    expect(prompt).toMatch(/nil_propagation/);
    expect(prompt).toMatch(/target_files/);
    expect(prompt).toMatch(/BugFix light path/i);
  });

  it("implement prompt includes scope lock", () => {
    const prompt = buildImplementPrompt({
      cluster: {
        id: "c1",
        defectIds: ["d1"],
        repoUrl: "https://gitlab.com/a/b.git",
        primaryTitle: "crash",
      },
      repoPath: "/tmp/repo",
      rootCause: {
        headline: "null",
        one_line_description: "null deref",
        five_whys: [],
        reproduction_steps: [],
        failure_mode: "nil_propagation",
        hypothesis: "user is undefined",
        fixability: { assessment: "fixable", reason: "add guard" },
      },
      solution: {
        one_line_summary: "guard",
        steps: [{ title: "g", description: "check" }],
        target_files: ["src/login.ts"],
      },
      iteration: 1,
    });
    expect(prompt).toMatch(/SCOPE LOCK/i);
    expect(prompt).toContain("src/login.ts");
  });
});
