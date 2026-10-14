import type { FixedCluster, RunReport, UnfixedCluster } from "../types.js";

export function buildReport(
  runId: string,
  fixed: FixedCluster[],
  unfixed: UnfixedCluster[],
): RunReport {
  return {
    runId,
    summary: {
      totalClusters: fixed.length + unfixed.length,
      fixed: fixed.length,
      unfixed: unfixed.length,
    },
    fixed,
    unfixed,
  };
}
