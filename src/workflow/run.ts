import { runDefectBatchPrepare } from "../defect-batch/index.js";
import { runCodeCartographer } from "../code-knowledge/index.js";
import { runDefectAnalyst } from "../defect-analyst/index.js";
import {
  ArtifactValidationError,
  requireAnalysisReport,
  requireCodeKnowledge,
  requireDefectBatch,
} from "./gates.js";
import type {
  ThreeAgentWorkflowInput,
  ThreeAgentWorkflowResult,
} from "./types.js";

/**
 * Parent workflow: validate → Agent-N → validate.
 * Loose coupling: only artifact I/O; handlers injectable for tests / future graphs.
 */
export async function runThreeAgentWorkflow(
  input: ThreeAgentWorkflowInput,
): Promise<ThreeAgentWorkflowResult> {
  const artifacts: ThreeAgentWorkflowResult["artifacts"] = {};

  try {
    // ── Agent-1 ──────────────────────────────────────────────
    let batch = input.defectBatch;
    if (!batch) {
      if (!input.ingest) {
        return {
          ok: false,
          stage: "agent1",
          error: "ingest or defectBatch is required",
          artifacts,
        };
      }
      batch = await runDefectBatchPrepare({
        ...input.ingest,
        productLine: input.productLine,
        posture: input.posture ?? "beta",
      });
    }
    artifacts.defectBatch = requireDefectBatch(batch);

    if (input.skipAgent2 && input.skipAgent3) {
      return { ok: true, stage: "done", artifacts };
    }

    // ── Agent-2 ──────────────────────────────────────────────
    if (!input.skipAgent2) {
      const agent2 = input.handlers?.agent2 ?? runCodeCartographer;
      const knowledge = await agent2({
        workDir: input.workDir,
        defectBatch: artifacts.defectBatch,
      });
      artifacts.codeKnowledge = requireCodeKnowledge(knowledge);
    }

    if (input.skipAgent3) {
      return { ok: true, stage: "done", artifacts };
    }

    if (!artifacts.codeKnowledge) {
      return {
        ok: false,
        stage: "agent3",
        error: "code-knowledge required for Agent-3 (disable skipAgent2 or supply handler)",
        artifacts,
      };
    }

    // ── Agent-3 ──────────────────────────────────────────────
    const agent3 = input.handlers?.agent3 ?? runDefectAnalyst;
    const report = await agent3({
      workDir: input.workDir,
      defectBatch: artifacts.defectBatch,
      codeKnowledge: artifacts.codeKnowledge,
      openMr: input.openMr ?? false,
    });
    artifacts.analysisReport = requireAnalysisReport(report);

    return { ok: true, stage: "done", artifacts };
  } catch (err) {
    const stage =
      !artifacts.defectBatch ? "agent1" : !artifacts.codeKnowledge ? "agent2" : "agent3";
    const message =
      err instanceof ArtifactValidationError
        ? err.message
        : err instanceof Error
          ? err.message
          : String(err);
    return { ok: false, stage, error: message, artifacts };
  }
}
