import path from "node:path";
import { aggregateDefects } from "../pipeline/aggregate.js";
import { normalizeDefects } from "../pipeline/normalize.js";
import type { CreateRunRequest, Defect, RunReport } from "../types.js";
import { runDir } from "../workspace/paths.js";
import {
  readJson,
  updateRunMeta,
  writeClustersPlan,
  writeReport,
} from "./store.js";

/** Fire-and-forget queue. Later tasks fill analyze/implement/deliver. */
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

async function loadRequest(workDir: string, runId: string): Promise<{
  defects: Defect[];
  userPrompt?: string;
  options?: CreateRunRequest["options"];
}> {
  const dir = runDir(workDir, runId);
  try {
    const req = await readJson<CreateRunRequest>(path.join(dir, "input.request.json"));
    return {
      defects: req.defects,
      userPrompt: req.userPrompt,
      options: req.options,
    };
  } catch {
    const defects = await readJson<Defect[]>(path.join(dir, "input.defects.json"));
    return { defects };
  }
}

export async function runPipeline(workDir: string, runId: string): Promise<RunReport> {
  await updateRunMeta(workDir, runId, {
    status: "running",
    progress: { phase: "normalize", message: "Normalizing defects" },
  });

  const loaded = await loadRequest(workDir, runId);
  const defects = normalizeDefects(loaded.defects);
  await updateRunMeta(workDir, runId, {
    progress: { phase: "aggregate", message: "Aggregating clusters" },
  });
  const clusters = aggregateDefects(defects);
  await writeClustersPlan(workDir, runId, clusters);

  // Stub dual-outcome until Task 9–12 wire real cluster processing.
  const report: RunReport = {
    runId,
    summary: {
      totalClusters: clusters.length,
      fixed: 0,
      unfixed: clusters.length,
    },
    fixed: [],
    unfixed: clusters.map((c) => ({
      clusterId: c.id,
      defectIds: c.defectIds,
      reasonCode: "unknown" as const,
      reasonDetail:
        "Pipeline stub: analyze/implement/verify/deliver not yet wired for this cluster.",
    })),
  };

  await writeReport(workDir, runId, report);
  await updateRunMeta(workDir, runId, {
    status: "completed",
    progress: {
      phase: "done",
      completedClusters: clusters.length,
      totalClusters: clusters.length,
    },
  });
  return report;
}
