import type { DefectBatch, CodeKnowledge, AnalysisReport } from "../contracts/index.js";
import type { RunDefectBatchPrepareInput } from "../defect-batch/run.js";
import type { CartographerFn } from "../agents/cartographer/index.js";
import type { AnalystFn } from "../agents/analyst/index.js";

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
  ingest?: Omit<RunDefectBatchPrepareInput, "productLine" | "posture">;
  defectBatch?: DefectBatch;
  openMr?: boolean;
  skipAgent2?: boolean;
  skipAgent3?: boolean;
  handlers?: {
    agent2?: CartographerFn;
    agent3?: AnalystFn;
  };
}

export interface ThreeAgentWorkflowResult {
  ok: boolean;
  stage: WorkflowStage | "done";
  error?: string;
  artifacts: WorkflowArtifacts;
}
