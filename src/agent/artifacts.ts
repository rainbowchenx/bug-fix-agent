import { z } from "zod";
import { FAILURE_MODES } from "../pipeline/failure-modes.js";
import {
  extractFirstJsonObject,
  extractLabeledJson,
} from "./json-extract.js";

/** Seer-aligned fixability tri-state (轨 B). */
export const FixabilityAssessmentSchema = z.object({
  assessment: z.enum(["fixable", "needs_more_context", "not_actionable"]),
  reason: z.string().min(1),
});
export type FixabilityAssessment = z.infer<typeof FixabilityAssessmentSchema>;

export const FailureModeSchema = z.enum(FAILURE_MODES);
export type FailureMode = z.infer<typeof FailureModeSchema>;

export const RootCauseArtifactSchema = z.object({
  headline: z.string().min(1),
  one_line_description: z.string().min(1),
  five_whys: z.array(z.string()).default([]),
  reproduction_steps: z.array(z.string()).default([]),
  relevant_repo: z.string().nullable().optional(),
  /** WorkBuddy-style failure mode catalog entry. */
  failure_mode: FailureModeSchema.optional(),
  /** Explicit hypothesis that must be evidenced before implement. */
  hypothesis: z.string().optional(),
  evidence: z.array(z.string()).optional(),
  fixability: FixabilityAssessmentSchema,
});
export type RootCauseArtifact = z.infer<typeof RootCauseArtifactSchema>;

export const SolutionStepSchema = z.object({
  title: z.string().min(1),
  description: z.string().min(1),
});
export type SolutionStep = z.infer<typeof SolutionStepSchema>;

export const SolutionArtifactSchema = z.object({
  one_line_summary: z.string().min(1),
  steps: z.array(SolutionStepSchema).min(1),
  acceptance_criteria: z.array(z.string()).optional(),
  /** Scope lock allowlist — relative paths the implementer may edit. */
  target_files: z.array(z.string()).optional(),
});
export type SolutionArtifact = z.infer<typeof SolutionArtifactSchema>;

export function parseRootCause(data: unknown): RootCauseArtifact {
  return RootCauseArtifactSchema.parse(data);
}

export function parseSolution(data: unknown): SolutionArtifact {
  return SolutionArtifactSchema.parse(data);
}

/** Extract first JSON object from agent text (brace-balanced, tolerant). */
export function extractJsonObject(text: string): unknown {
  return extractFirstJsonObject(text);
}

export { extractLabeledJson, extractFirstJsonObject };
