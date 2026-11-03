import type { DefectBatch } from "../defect-batch/types.js";
import {
  CODE_KNOWLEDGE_SCHEMA_VERSION,
  type CodeKnowledge,
} from "./types.js";
import { validateCodeKnowledge } from "./validate.js";

export interface RunCodeCartographerInput {
  workDir: string;
  defectBatch: DefectBatch;
  /** When true, emit a valid empty-ish knowledge artifact (scaffold). */
  stub?: boolean;
}

export type CodeCartographerFn = (
  input: RunCodeCartographerInput,
) => Promise<CodeKnowledge>;

/**
 * Agent-2 entrypoint (scaffold).
 * Default implementation returns a validated stub; replace via workflow handlers.
 */
export async function runCodeCartographer(
  input: RunCodeCartographerInput,
): Promise<CodeKnowledge> {
  const matchPools = new Set(["strict", "locatable_only", "needs_info"]);
  const matches = input.defectBatch.tickets
    .filter((t) => matchPools.has(t.pool))
    .map((t) => ({
      defectId: t.defectId,
      clusterId: t.clusterId,
      title: t.title,
      candidates: [] as { path: string; why: string; source: "stub" }[],
      confidence: "low" as const,
    }));

  const knowledge: CodeKnowledge = validateCodeKnowledge({
    schemaVersion: CODE_KNOWLEDGE_SCHEMA_VERSION,
    productLine: input.defectBatch.productLine,
    workDir: input.workDir,
    partial: true,
    generatedAt: new Date().toISOString(),
    repoRoots: [{ path: ".", gitHead: null, fingerprint: "stub" }],
    cartographyProfile: "unknown",
    secondaryHints: ["scaffold-stub"],
    techStack: { languages: [], frameworks: [], notes: "Agent-2 stub — map_arch not run" },
    architecture: {
      summary: "scaffold stub; replace with LangGraph cartographer",
      entryPoints: [],
      modules: [],
    },
    conventions: { fromClaudeMd: [], fromRules: [] },
    boundSkills: [],
    specAtlas: { frameworkId: "unknown", entries: [], drDs: [], bindings: [] },
    capabilities: { codeGraph: false, runtimeVerify: false },
    defectCodeMatches: matches,
  });

  return knowledge;
}
