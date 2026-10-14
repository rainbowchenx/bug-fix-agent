import type { FixabilityAssessment, RootCauseArtifact } from "../agent/artifacts.js";
import type { ReasonCode } from "../types.js";

export type FixabilityGate =
  | { status: "fixable" }
  | { status: "unfixed"; reasonCode: ReasonCode; reasonDetail: string };

export function gateFromFixability(assessment: FixabilityAssessment): FixabilityGate {
  if (assessment.assessment === "fixable") {
    return { status: "fixable" };
  }
  if (assessment.assessment === "needs_more_context") {
    return {
      status: "unfixed",
      reasonCode: "needs_more_context",
      reasonDetail: assessment.reason,
    };
  }
  return {
    status: "unfixed",
    reasonCode: "not_actionable",
    reasonDetail: assessment.reason,
  };
}

export function gateFromRootCause(rootCause: RootCauseArtifact): FixabilityGate {
  return gateFromFixability(rootCause.fixability);
}
