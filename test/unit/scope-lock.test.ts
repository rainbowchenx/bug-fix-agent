import { describe, expect, it } from "vitest";
import { checkScopeLock, extractAllowedFiles } from "../../src/pipeline/scope-lock.js";

describe("scope lock", () => {
  it("extracts target_files from solution", () => {
    const allowed = extractAllowedFiles({
      one_line_summary: "guard null",
      steps: [{ title: "edit", description: "touch `src/a.ts`" }],
      target_files: ["src/a.ts", "src/b.ts"],
    });
    expect(allowed).toContain("src/a.ts");
    expect(allowed).toContain("src/b.ts");
  });

  it("flags files outside allowlist", () => {
    const result = checkScopeLock(["src/a.ts", "src/unrelated.ts"], {
      one_line_summary: "x",
      steps: [{ title: "t", description: "d" }],
      target_files: ["src/a.ts"],
    });
    expect(result.ok).toBe(false);
    expect(result.violations).toContain("src/unrelated.ts");
  });

  it("passes when changed files subset of allowlist", () => {
    const result = checkScopeLock(["src/a.ts"], {
      one_line_summary: "x",
      steps: [{ title: "t", description: "d" }],
      target_files: ["src/a.ts", "src/b.ts"],
    });
    expect(result.ok).toBe(true);
  });
});
