import {
  safeValidateDefectBatch,
  type DefectBatch,
} from "../defect-batch/index.js";
import {
  safeValidateCodeKnowledge,
  type CodeKnowledge,
} from "../code-knowledge/index.js";
import {
  safeValidateAnalysisReport,
  type AnalysisReport,
} from "../defect-analyst/index.js";

export class ArtifactValidationError extends Error {
  constructor(
    public readonly artifact: string,
    public readonly detail: string,
  ) {
    super(`${artifact} validation failed: ${detail}`);
    this.name = "ArtifactValidationError";
  }
}

export function requireDefectBatch(input: unknown): DefectBatch {
  const r = safeValidateDefectBatch(input);
  if (!r.ok) throw new ArtifactValidationError("defect-batch", r.error);
  return r.data;
}

export function requireCodeKnowledge(input: unknown): CodeKnowledge {
  const r = safeValidateCodeKnowledge(input);
  if (!r.ok) throw new ArtifactValidationError("code-knowledge", r.error);
  return r.data;
}

export function requireAnalysisReport(input: unknown): AnalysisReport {
  const r = safeValidateAnalysisReport(input);
  if (!r.ok) throw new ArtifactValidationError("analysis-report", r.error);
  return r.data;
}
