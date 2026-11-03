import { describe, expect, it } from "vitest";
import {
  CODE_KNOWLEDGE_SCHEMA_VERSION,
  safeValidateCodeKnowledge,
  validateCodeKnowledge,
} from "../../src/contracts/index.js";

describe("code-knowledge contract", () => {
  it("accepts minimal payload", () => {
    const data = validateCodeKnowledge({
      schemaVersion: CODE_KNOWLEDGE_SCHEMA_VERSION,
      productLine: "hc",
      workDir: "/tmp/w",
      generatedAt: new Date().toISOString(),
      defectCodeMatches: [],
    });
    expect(data.cartographyProfile).toBe("unknown");
  });

  it("rejects missing productLine", () => {
    const r = safeValidateCodeKnowledge({
      schemaVersion: CODE_KNOWLEDGE_SCHEMA_VERSION,
      workDir: "/tmp/w",
      generatedAt: new Date().toISOString(),
    });
    expect(r.ok).toBe(false);
  });
});
