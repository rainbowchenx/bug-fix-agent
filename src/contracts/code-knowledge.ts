import { z } from "zod";
import { CONTRACT_SCHEMA_VERSION, ConfidenceSchema } from "./common.js";

export const CODE_KNOWLEDGE_SCHEMA_VERSION = CONTRACT_SCHEMA_VERSION;

export const CartographyProfileSchema = z.enum([
  "electron_node",
  "micro_frontend",
  "device_web",
  "unknown",
]);
export type CartographyProfile = z.infer<typeof CartographyProfileSchema>;

export const RepoRootSchema = z.object({
  /** Path relative to workDir (`.` = workDir itself). */
  path: z.string().min(1),
  gitHead: z.string().nullable().optional(),
  /** Content/fingerprint cache key; not required to be a git sha. */
  fingerprint: z.string().optional(),
});
export type RepoRoot = z.infer<typeof RepoRootSchema>;

export const MatchCandidateSchema = z.object({
  repoPath: z.string().default("."),
  path: z.string().min(1),
  symbol: z.string().optional(),
  why: z.string().default(""),
  source: z.enum(["codegraph", "grep", "heuristic", "claude_md"]).default("heuristic"),
});
export type MatchCandidate = z.infer<typeof MatchCandidateSchema>;

export const DefectCodeMatchSchema = z.object({
  defectId: z.string().min(1),
  clusterId: z.string().optional(),
  title: z.string().optional(),
  /** Soft start for Agent-3 — may be empty. */
  candidates: z.array(MatchCandidateSchema).default([]),
  confidence: ConfidenceSchema.default("low"),
});
export type DefectCodeMatch = z.infer<typeof DefectCodeMatchSchema>;

export const SpecEntrySchema = z.object({
  path: z.string(),
  kind: z
    .enum(["guide", "skill", "rule", "command", "agent_def", "doc_ref", "dr", "ds", "unknown"])
    .default("unknown"),
  source: z.enum(["claude_dir", "repo_root", "explicit", "follow_ref"]).default("repo_root"),
});
export type SpecEntry = z.infer<typeof SpecEntrySchema>;

export const SpecAtlasSchema = z.object({
  /** Closed known set or `unknown` — never invent brand names. */
  frameworkId: z.string().default("unknown"),
  entries: z.array(SpecEntrySchema).default([]),
  drDs: z
    .array(
      z.object({
        path: z.string(),
        kind: z.enum(["DR", "DS", "unknown"]).default("unknown"),
        moduleHint: z.string().nullable().optional(),
      }),
    )
    .default([]),
  bindings: z.array(z.record(z.string(), z.unknown())).default([]),
});
export type SpecAtlas = z.infer<typeof SpecAtlasSchema>;

export const ArchModuleSchema = z.object({
  id: z.string(),
  path: z.string().optional(),
  role: z.string().optional(),
  shared: z.boolean().optional(),
  notes: z.string().optional(),
});
export type ArchModule = z.infer<typeof ArchModuleSchema>;

/**
 * code-knowledge — Agent-2 → Agent-3 only.
 * Agent-3 must not call Agent-2 internals; only this artifact.
 */
export const CodeKnowledgeSchema = z.object({
  schemaVersion: z.string(),
  productLine: z.string().min(1),
  workDir: z.string().min(1),
  /** true when map/match incomplete (degraded run still valid). */
  partial: z.boolean().default(false),
  generatedAt: z.string().min(1),
  repoRoots: z.array(RepoRootSchema).default([]),
  cartographyProfile: CartographyProfileSchema.default("unknown"),
  secondaryHints: z.array(z.string()).default([]),
  techStack: z
    .object({
      languages: z.array(z.string()).default([]),
      frameworks: z.array(z.string()).default([]),
      notes: z.string().default(""),
    })
    .default({ languages: [], frameworks: [], notes: "" }),
  architecture: z
    .object({
      summary: z.string().default(""),
      entryPoints: z.array(z.string()).default([]),
      modules: z.array(ArchModuleSchema).default([]),
    })
    .default({ summary: "", entryPoints: [], modules: [] }),
  conventions: z
    .object({
      fromClaudeMd: z.array(z.string()).default([]),
      fromRules: z.array(z.string()).default([]),
    })
    .default({ fromClaudeMd: [], fromRules: [] }),
  boundSkills: z.array(z.string()).default([]),
  specAtlas: SpecAtlasSchema.default({
    frameworkId: "unknown",
    entries: [],
    drDs: [],
    bindings: [],
  }),
  capabilities: z
    .object({
      codeGraph: z.boolean().default(false),
      runtimeVerify: z.boolean().default(false),
    })
    .default({ codeGraph: false, runtimeVerify: false }),
  defectCodeMatches: z.array(DefectCodeMatchSchema).default([]),
});
export type CodeKnowledge = z.infer<typeof CodeKnowledgeSchema>;

export function validateCodeKnowledge(input: unknown): CodeKnowledge {
  return CodeKnowledgeSchema.parse(input);
}

export function safeValidateCodeKnowledge(
  input: unknown,
): { ok: true; data: CodeKnowledge } | { ok: false; error: string } {
  const parsed = CodeKnowledgeSchema.safeParse(input);
  if (!parsed.success) return { ok: false, error: parsed.error.message };
  return { ok: true, data: parsed.data };
}
