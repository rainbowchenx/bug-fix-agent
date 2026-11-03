import {
  CODE_KNOWLEDGE_SCHEMA_VERSION,
  isMatchPool,
  validateCodeKnowledge,
  type CodeKnowledge,
  type DefectBatch,
} from "../../contracts/index.js";
import { detectCartographyProfile, discoverRepoRoots, readConventions } from "./detect.js";
import { matchTickets } from "./match.js";

export interface RunCartographerInput {
  workDir: string;
  defectBatch: DefectBatch;
}

export type CartographerFn = (input: RunCartographerInput) => Promise<CodeKnowledge>;

/**
 * Agent-2 public entry — consumes validated defect-batch only.
 * Deterministic bootstrap + heuristic match (LangGraph/SDK sessions land later).
 */
export async function runCartographer(input: RunCartographerInput): Promise<CodeKnowledge> {
  const batch = input.defectBatch;
  const repoRoots = await discoverRepoRoots(input.workDir);
  const detected = await detectCartographyProfile(input.workDir, repoRoots);
  const conventions = await readConventions(input.workDir, repoRoots);

  const matchTicketsList = batch.tickets.filter((t) => isMatchPool(t.pool));
  const defectCodeMatches = await matchTickets(input.workDir, repoRoots, matchTicketsList);

  const partial =
    detected.profile === "unknown" ||
    defectCodeMatches.every((m) => m.candidates.length === 0);

  return validateCodeKnowledge({
    schemaVersion: CODE_KNOWLEDGE_SCHEMA_VERSION,
    productLine: batch.productLine,
    workDir: input.workDir,
    partial,
    generatedAt: new Date().toISOString(),
    repoRoots,
    cartographyProfile: detected.profile,
    secondaryHints: detected.secondaryHints,
    techStack: detected.tech,
    architecture: {
      summary:
        detected.profile === "unknown"
          ? "Profile unknown; architecture map deferred to SDK session"
          : `Detected ${detected.profile} across ${repoRoots.length} repo root(s)`,
      entryPoints: [],
      modules: repoRoots.map((r) => ({
        id: r.path,
        path: r.path,
        role: "repo_root",
      })),
    },
    conventions: {
      fromClaudeMd: conventions.fromClaudeMd.slice(0, 30),
      fromRules: conventions.fromRules,
    },
    boundSkills: conventions.boundSkills,
    specAtlas: {
      frameworkId: conventions.frameworkId,
      entries: conventions.entries,
      drDs: [],
      bindings: [],
    },
    capabilities: {
      codeGraph: conventions.codeGraph,
      runtimeVerify: false,
    },
    defectCodeMatches,
  });
}

/** @deprecated alias — prefer runCartographer */
export const runCodeCartographer = runCartographer;
export type RunCodeCartographerInput = RunCartographerInput;
export type CodeCartographerFn = CartographerFn;
