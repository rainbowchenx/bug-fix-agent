import { describe, expect, it } from "vitest";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { runThreeAgentWorkflow } from "../../src/workflow/index.js";
import { CODE_KNOWLEDGE_SCHEMA_VERSION } from "../../src/code-knowledge/index.js";
import { ANALYSIS_REPORT_SCHEMA_VERSION } from "../../src/defect-analyst/index.js";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const hc1 = path.join(root, "test/fixtures/defect-batch/hc1-raw.json");

describe("runThreeAgentWorkflow scaffold", () => {
  it("runs agent1→2→3 stubs with validated artifacts", async () => {
    const result = await runThreeAgentWorkflow({
      workDir: "/tmp/three-agent-scaffold",
      productLine: "hc",
      posture: "alpha",
      ingest: { mode: "preloaded", source: hc1 },
      openMr: false,
    });
    expect(result.ok).toBe(true);
    expect(result.stage).toBe("done");
    expect(result.artifacts.defectBatch?.funnel.total).toBe(50);
    expect(result.artifacts.codeKnowledge?.schemaVersion).toBe(CODE_KNOWLEDGE_SCHEMA_VERSION);
    expect(result.artifacts.codeKnowledge?.partial).toBe(true);
    expect(result.artifacts.codeKnowledge?.defectCodeMatches.length).toBeGreaterThan(0);
    expect(result.artifacts.analysisReport?.schemaVersion).toBe(ANALYSIS_REPORT_SCHEMA_VERSION);
    expect(result.artifacts.analysisReport?.tickets.length).toBeGreaterThan(0);
    expect(
      result.artifacts.analysisReport?.tickets.every((t) => t.outcome === "skipped_scaffold"),
    ).toBe(true);
  });

  it("hard-stops when agent2 returns invalid knowledge", async () => {
    const result = await runThreeAgentWorkflow({
      workDir: "/tmp/three-agent-scaffold",
      productLine: "hc",
      posture: "alpha",
      ingest: { mode: "preloaded", source: hc1 },
      handlers: {
        agent2: async () => ({ broken: true }) as never,
      },
    });
    expect(result.ok).toBe(false);
    expect(result.stage).toBe("agent2");
    expect(result.error).toMatch(/code-knowledge validation failed/);
    expect(result.artifacts.analysisReport).toBeUndefined();
  });

  it("can stop after agent1", async () => {
    const result = await runThreeAgentWorkflow({
      workDir: "/tmp/three-agent-scaffold",
      productLine: "hc",
      posture: "alpha",
      ingest: { mode: "preloaded", source: hc1 },
      skipAgent2: true,
      skipAgent3: true,
    });
    expect(result.ok).toBe(true);
    expect(result.artifacts.defectBatch).toBeDefined();
    expect(result.artifacts.codeKnowledge).toBeUndefined();
  });
});
