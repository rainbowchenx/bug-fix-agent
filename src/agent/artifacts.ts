import { z } from "zod";

/** Seer-aligned fixability tri-state (轨 B). */
export const FixabilityAssessmentSchema = z.object({
  assessment: z.enum(["fixable", "needs_more_context", "not_actionable"]),
  reason: z.string().min(1),
});
export type FixabilityAssessment = z.infer<typeof FixabilityAssessmentSchema>;

export const RootCauseArtifactSchema = z.object({
  headline: z.string().min(1),
  one_line_description: z.string().min(1),
  five_whys: z.array(z.string()).default([]),
  reproduction_steps: z.array(z.string()).default([]),
  relevant_repo: z.string().nullable().optional(),
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
});
export type SolutionArtifact = z.infer<typeof SolutionArtifactSchema>;

export function parseRootCause(data: unknown): RootCauseArtifact {
  return RootCauseArtifactSchema.parse(data);
}

export function parseSolution(data: unknown): SolutionArtifact {
  return SolutionArtifactSchema.parse(data);
}

/** Extract first JSON object from agent text (tolerant). */
export function extractJsonObject(text: string): unknown {
  const start = text.indexOf("{");
  const end = text.lastIndexOf("}");
  if (start < 0 || end <= start) {
    throw new Error("No JSON object found in text");
  }
  return JSON.parse(text.slice(start, end + 1)) as unknown;
}
