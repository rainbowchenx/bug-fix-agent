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

/**
 * Accept root-cause shapes models actually emit.
 * Boolean/empty relevant_repo → null; string arrays stay; common aliases map in.
 */
export function coerceRootCauseInput(data: unknown): unknown {
  if (!data || typeof data !== "object" || Array.isArray(data)) return data;
  const obj = { ...(data as Record<string, unknown>) };

  if (obj.relevant_repo !== undefined && obj.relevant_repo !== null) {
    if (typeof obj.relevant_repo === "boolean") {
      obj.relevant_repo = null;
    } else if (typeof obj.relevant_repo === "number") {
      obj.relevant_repo = String(obj.relevant_repo);
    } else if (typeof obj.relevant_repo === "string") {
      const trimmed = obj.relevant_repo.trim();
      obj.relevant_repo = trimmed || null;
    } else {
      obj.relevant_repo = null;
    }
  }

  for (const key of ["five_whys", "reproduction_steps", "evidence"] as const) {
    if (typeof obj[key] === "string" && obj[key].trim()) {
      obj[key] = [obj[key].trim()];
    }
  }

  if (obj.fixability && typeof obj.fixability === "object" && !Array.isArray(obj.fixability)) {
    const f = { ...(obj.fixability as Record<string, unknown>) };
    if (typeof f.assessment === "string") {
      f.assessment = f.assessment.trim().toLowerCase().replace(/\s+/g, "_");
    }
    if (typeof f.reason !== "string" || !f.reason.trim()) {
      f.reason = typeof f.reason === "string" ? "unspecified" : String(f.reason ?? "unspecified");
    }
    obj.fixability = f;
  }

  return obj;
}

export function parseRootCause(data: unknown): RootCauseArtifact {
  return RootCauseArtifactSchema.parse(coerceRootCauseInput(data));
}

export function parseSolution(data: unknown): SolutionArtifact {
  return SolutionArtifactSchema.parse(data);
}

/**
 * Accept solution shapes models actually emit, without inventing a plan.
 * String steps become {title, description}. Aliases map onto the schema fields.
 */
export function coerceSolutionInput(data: unknown): unknown {
  if (!data || typeof data !== "object" || Array.isArray(data)) return data;
  const obj = { ...(data as Record<string, unknown>) };
  if (typeof obj.one_line_summary !== "string" || !obj.one_line_summary.trim()) {
    for (const key of ["summary", "oneLineSummary"] as const) {
      const value = obj[key];
      if (typeof value === "string" && value.trim()) {
        obj.one_line_summary = value.trim();
        break;
      }
    }
  }
  if (!Array.isArray(obj.target_files)) {
    const files = obj.targetFiles ?? obj.files;
    if (Array.isArray(files)) obj.target_files = files.filter((f) => typeof f === "string");
  }
  if (typeof obj.steps === "string" && obj.steps.trim()) {
    obj.steps = [obj.steps];
  }
  if (Array.isArray(obj.steps)) {
    obj.steps = obj.steps.map((step, i) => {
      if (typeof step === "string" && step.trim()) {
        return { title: `Step ${i + 1}`, description: step.trim() };
      }
      if (step && typeof step === "object" && !Array.isArray(step)) {
        const s = step as Record<string, unknown>;
        const title = String(s.title ?? s.name ?? `Step ${i + 1}`).trim();
        const description = String(s.description ?? s.detail ?? s.action ?? "").trim();
        return {
          title: title || `Step ${i + 1}`,
          description: description || title,
        };
      }
      return step;
    });
  }
  return obj;
}

export function parseSolutionText(text: string, opts?: { allowBare?: boolean }): SolutionArtifact {
  try {
    return parseSolution(coerceSolutionInput(extractLabeledJson(text, "SOLUTION")));
  } catch (labeled) {
    if (!opts?.allowBare) throw labeled;
    return parseSolution(coerceSolutionInput(extractFirstJsonObject(text)));
  }
}

/** Extract first JSON object from agent text (brace-balanced, tolerant). */
export function extractJsonObject(text: string): unknown {
  return extractFirstJsonObject(text);
}

export { extractLabeledJson, extractFirstJsonObject };
