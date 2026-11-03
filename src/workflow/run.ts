import { runDefectBatchPrepare } from "../defect-batch/index.js";
import { runCartographer } from "../agents/cartographer/index.js";
import { runAnalyst } from "../agents/analyst/index.js";
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
 * Parent workflow only: validate → agent → validate.
 * No cross-agent internal imports — handlers injectable.
 */
export async function runThreeAgentWorkflow(
  input: ThreeAgentWorkflowInput,
): Promise<ThreeAgentWorkflowResult> {
  const artifacts: ThreeAgentWorkflowResult["artifacts"] = {};

  try {
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

    if (!input.skipAgent2) {
      const agent2 = input.handlers?.agent2 ?? runCartographer;
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
        error: "code-knowledge required for Agent-3",
        artifacts,
      };
    }

    const agent3 = input.handlers?.agent3 ?? runAnalyst;
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
