import { z } from "zod";

/** Agent-2 artifact schemaVersion — evolve with implementation. */
export const CODE_KNOWLEDGE_SCHEMA_VERSION = "0.1.0";

export const CartographyProfileSchema = z.enum([
  "electron_node",
  "micro_frontend",
  "device_web",
  "unknown",
]);
export type CartographyProfile = z.infer<typeof CartographyProfileSchema>;

export const ConfidenceSchema = z.enum(["high", "medium", "low"]);
export type Confidence = z.infer<typeof ConfidenceSchema>;

export const RepoRootSchema = z.object({
  path: z.string(),
  gitHead: z.string().nullable().optional(),
  fingerprint: z.string().optional(),
});
export type RepoRoot = z.infer<typeof RepoRootSchema>;

export const MatchCandidateSchema = z.object({
  repoPath: z.string().default("."),
  path: z.string(),
  symbol: z.string().optional(),
  why: z.string().default(""),
  source: z.enum(["codegraph", "grep", "heuristic", "stub"]).default("stub"),
});
export type MatchCandidate = z.infer<typeof MatchCandidateSchema>;

export const DefectCodeMatchSchema = z.object({
  defectId: z.string(),
  clusterId: z.string().optional(),
  title: z.string().optional(),
  candidates: z.array(MatchCandidateSchema).default([]),
  confidence: ConfidenceSchema.default("low"),
});
export type DefectCodeMatch = z.infer<typeof DefectCodeMatchSchema>;

export const SpecAtlasSchema = z.object({
  frameworkId: z.string().default("unknown"),
  entries: z.array(z.record(z.string(), z.unknown())).default([]),
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

/**
 * code-knowledge — Agent-2 output contract (v0.1 scaffold).
 * Field set follows 2026-10-30 Agent-2 discussion; thicken in S2.
 */
export const CodeKnowledgeSchema = z.object({
  schemaVersion: z.string(),
  productLine: z.string(),
  workDir: z.string(),
  partial: z.boolean().default(false),
  generatedAt: z.string(),
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
      modules: z.array(z.record(z.string(), z.unknown())).default([]),
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
