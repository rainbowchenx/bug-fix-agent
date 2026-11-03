import {
  safeValidateDefectBatch,
  safeValidateCodeKnowledge,
  safeValidateAnalysisReport,
  type DefectBatch,
  type CodeKnowledge,
  type AnalysisReport,
} from "../contracts/index.js";

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
