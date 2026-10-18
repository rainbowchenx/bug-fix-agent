import type { Engine, FixedCluster, RunReport, UnfixedCluster } from "../types.js";

export function buildReport(
  runId: string,
  fixed: FixedCluster[],
  unfixed: UnfixedCluster[],
  extra?: { startedAt?: string; finishedAt?: string; engine?: Engine },
): RunReport {
  return {
    runId,
    startedAt: extra?.startedAt,
    finishedAt: extra?.finishedAt,
    engine: extra?.engine,
    summary: {
      totalClusters: fixed.length + unfixed.length,
      fixed: fixed.length,
      unfixed: unfixed.length,
    },
    fixed,
    unfixed,
  };
}
