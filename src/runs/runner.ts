import type { RunReport } from "../types.js";
import { updateRunMeta, writeReport } from "./store.js";

/** Fire-and-forget queue. Task 5+ fills real pipeline. */
export function enqueueRun(workDir: string, runId: string): void {
  setImmediate(() => {
    void runPipeline(workDir, runId).catch(async (err) => {
      const message = err instanceof Error ? err.message : String(err);
      await updateRunMeta(workDir, runId, {
        status: "failed",
        error: message,
      });
    });
  });
}

export async function runPipeline(workDir: string, runId: string): Promise<RunReport> {
  await updateRunMeta(workDir, runId, {
    status: "running",
    progress: { phase: "stub", message: "MVP stub runner" },
  });

  const report: RunReport = {
    runId,
    summary: { totalClusters: 0, fixed: 0, unfixed: 0 },
    fixed: [],
    unfixed: [],
  };

  await writeReport(workDir, runId, report);
  await updateRunMeta(workDir, runId, {
    status: "completed",
    progress: {
      phase: "done",
      completedClusters: 0,
      totalClusters: 0,
    },
  });
  return report;
}
