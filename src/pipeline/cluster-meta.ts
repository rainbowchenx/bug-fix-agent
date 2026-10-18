import type { FixedCluster, VerifyLevel } from "../types.js";

export interface LiveClusterMeta {
  started: number;
  baseSha?: string;
  branch?: string;
  profileId?: string;
  iterations: number;
  skillsInvoked: string[];
  mcpToolsInvoked: string[];
  verifyLevel: VerifyLevel;
  baselineRed: boolean;
}

let current: LiveClusterMeta | undefined;

export function bindClusterMeta(meta: LiveClusterMeta): () => void {
  const prev = current;
  current = meta;
  return () => {
    current = prev;
  };
}

export function currentClusterMeta(): LiveClusterMeta | undefined {
  return current;
}

export function liveClusterFields(): Partial<FixedCluster> {
  if (!current) return {};
  return {
    baseSha: current.baseSha,
    branch: current.branch,
    profileId: current.profileId,
    iterations: current.iterations,
    durationMs: Date.now() - current.started,
    skillsInvoked: current.skillsInvoked,
    mcpToolsInvoked: current.mcpToolsInvoked,
    verifyLevel: current.verifyLevel,
    baselineRed: current.baselineRed,
  };
}
