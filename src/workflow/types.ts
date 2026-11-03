import type { DefectBatch } from "../defect-batch/types.js";
import type { RunDefectBatchPrepareInput } from "../defect-batch/run.js";
import type { CodeKnowledge } from "../code-knowledge/types.js";
import type { CodeCartographerFn } from "../code-knowledge/run.js";
import type { AnalysisReport } from "../defect-analyst/types.js";
import type { DefectAnalystFn } from "../defect-analyst/run.js";

export type WorkflowStage = "agent1" | "agent2" | "agent3";

export interface WorkflowArtifacts {
  defectBatch?: DefectBatch;
  codeKnowledge?: CodeKnowledge;
  analysisReport?: AnalysisReport;
}

export interface ThreeAgentWorkflowInput {
  workDir: string;
  productLine: string;
  posture?: "alpha" | "beta";
  /** Agent-1 ingest — required unless `defectBatch` is pre-supplied. */
  ingest?: Omit<RunDefectBatchPrepareInput, "productLine" | "posture">;
  /** Skip Agent-1 and use this validated-or-raw batch. */
  defectBatch?: DefectBatch;
  openMr?: boolean;
  skipAgent2?: boolean;
  skipAgent3?: boolean;
  handlers?: {
    agent2?: CodeCartographerFn;
    agent3?: DefectAnalystFn;
  };
}

export interface ThreeAgentWorkflowResult {
  ok: boolean;
  stage: WorkflowStage | "done";
  error?: string;
  artifacts: WorkflowArtifacts;
}
