import { describe, expect, it } from "vitest";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { mkdirSync, writeFileSync, rmSync } from "node:fs";
import { runThreeAgentWorkflow } from "../../src/workflow/index.js";
import {
  CODE_KNOWLEDGE_SCHEMA_VERSION,
  ANALYSIS_REPORT_SCHEMA_VERSION,
} from "../../src/contracts/index.js";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const hc1 = path.join(root, "test/fixtures/defect-batch/hc1-raw.json");

describe("runThreeAgentWorkflow (loose agents + contracts)", () => {
  it("agent1→cartographer→analyst with real outcomes", async () => {
    const workDir = path.join(root, "test/fixtures/mini-workdir");
    mkdirSync(path.join(workDir, "src"), { recursive: true });
    writeFileSync(
      path.join(workDir, "package.json"),
      JSON.stringify({ name: "mini-hc", version: "0.0.1", dependencies: { electron: "30.0.0" } }),
    );
    writeFileSync(path.join(workDir, "CLAUDE.md"), "# Mini\nUse CodeGraph for search.\n");
    writeFileSync(path.join(workDir, "src", "preview-player.ts"), "export const preview = 1;\n");

    const result = await runThreeAgentWorkflow({
      workDir,
      productLine: "hc",
      posture: "alpha",
      ingest: { mode: "preloaded", source: hc1 },
      openMr: false,
    });

    expect(result.ok).toBe(true);
    expect(result.artifacts.defectBatch?.funnel.total).toBe(50);
    expect(result.artifacts.codeKnowledge?.schemaVersion).toBe(CODE_KNOWLEDGE_SCHEMA_VERSION);
    expect(result.artifacts.codeKnowledge?.cartographyProfile).toBe("electron_node");
    expect(result.artifacts.analysisReport?.schemaVersion).toBe(ANALYSIS_REPORT_SCHEMA_VERSION);
    expect(result.artifacts.analysisReport?.tickets.length).toBeGreaterThan(0);
    const outcomes = new Set(result.artifacts.analysisReport?.tickets.map((t) => t.outcome));
    expect([...outcomes].every((o) => o !== "skipped_scaffold")).toBe(true);
    // at least one classified outcome
    expect(
      result.artifacts.analysisReport?.tickets.some((t) =>
        ["plan_only", "unlocalized", "needs_ticket_info"].includes(t.outcome),
      ),
    ).toBe(true);

    rmSync(workDir, { recursive: true, force: true });
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
  });
});
