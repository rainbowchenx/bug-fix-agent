import { describe, expect, it } from "vitest";
import {
  extractFirstJsonObject,
  extractLabeledJson,
} from "../../src/agent/json-extract.js";

describe("json extract", () => {
  it("splits ROOT_CAUSE and SOLUTION when both appear in one blob", () => {
    const text = `Here is analysis.
ROOT_CAUSE
{"headline":"null crash","one_line_description":"user undefined","five_whys":["a"],"fixability":{"assessment":"fixable","reason":"guard"}}
some prose with { braces } that should not confuse
SOLUTION
{"one_line_summary":"add guard","steps":[{"title":"g","description":"check"}],"target_files":["src/a.ts"]}
Thanks.`;
    const rc = extractLabeledJson(text, "ROOT_CAUSE") as { headline: string };
    const sol = extractLabeledJson(text, "SOLUTION") as { one_line_summary: string };
    expect(rc.headline).toBe("null crash");
    expect(sol.one_line_summary).toBe("add guard");
  });

  it("extracts fenced json after label", () => {
    const text = `SOLUTION
\`\`\`json
{"one_line_summary":"x","steps":[{"title":"t","description":"d"}]}
\`\`\`
`;
    const sol = extractLabeledJson(text, "SOLUTION") as { one_line_summary: string };
    expect(sol.one_line_summary).toBe("x");
  });

  it("does not swallow second object via greedy last brace", () => {
    const text = `ROOT_CAUSE {"a":1} SOLUTION {"b":2}`;
    expect(extractLabeledJson(text, "ROOT_CAUSE")).toEqual({ a: 1 });
    expect(extractLabeledJson(text, "SOLUTION")).toEqual({ b: 2 });
  });

  it("does not treat a missing SOLUTION label as the root-cause object", () => {
    const text = `ROOT_CAUSE
{"headline":"null crash","one_line_description":"user undefined","fixability":{"assessment":"fixable","reason":"guard"}}`;
    expect(() => extractLabeledJson(text, "SOLUTION")).toThrow(/Missing SOLUTION JSON object/);
  });

  it("ignores the word solution inside an earlier JSON string", () => {
    const text = `ROOT_CAUSE
{"headline":"the solution is wrong","one_line_description":"x","fixability":{"assessment":"fixable","reason":"r"}}
SOLUTION
{"one_line_summary":"add guard","steps":[{"title":"g","description":"check"}]}`;
    const sol = extractLabeledJson(text, "SOLUTION") as { one_line_summary: string };
    expect(sol.one_line_summary).toBe("add guard");
  });

  it("handles nested braces inside strings", () => {
    const text = `{"msg":"has } brace","n":{"x":1}}`;
    expect(extractFirstJsonObject(text)).toEqual({ msg: "has } brace", n: { x: 1 } });
  });
});
