import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { runPipeline } from "../../src/runs/runner.js";
import { createRunDir, writeInputDefects } from "../../src/runs/store.js";
import { createSweHandlers } from "./handlers.js";
import { mapInstanceToRequest } from "./map-instance.js";
import { ensurePredictionsFile } from "./predictions.js";
import type { SweBatchOptions, SweInstance } from "./types.js";

export interface SweInstanceResult {
  instance_id: string;
  runId: string;
  outcome: "fixed" | "unfixed" | "error";
  reasonCode?: string;
  reasonDetail?: string;
  mrUrl?: string;
}

export interface SweBatchResult {
  results: SweInstanceResult[];
  predictionsPath: string;
}

/**
 * Run the core pipeline once per SWE instance via handlers injection.
 * Does not import SWE types into src/.
 */
export async function runSweBatch(opts: SweBatchOptions): Promise<SweBatchResult> {
  const modelName = opts.modelName ?? process.env.ANTHROPIC_MODEL ?? "bugfix-agent";
  const limit = opts.limit ?? opts.instances.length;
  const slice = opts.instances.slice(0, limit);

  await mkdir(opts.workDir, { recursive: true });
  await ensurePredictionsFile(opts.predictionsPath);

  const summaryPath = path.join(opts.workDir, "swe-batch-summary.json");
  const results: SweInstanceResult[] = [];

  for (const inst of slice) {
    const result = await runOne(inst, opts, modelName);
    results.push(result);
    await writeFile(summaryPath, `${JSON.stringify({ results }, null, 2)}\n`, "utf8");
  }

  return { results, predictionsPath: opts.predictionsPath };
}

async function runOne(
  inst: SweInstance,
  opts: SweBatchOptions,
  modelName: string,
): Promise<SweInstanceResult> {
  const instanceWork = path.join(opts.workDir, "instances", inst.instance_id);
  await mkdir(instanceWork, { recursive: true });

  const request = mapInstanceToRequest(instanceWork, inst, {
    skipReviewer: opts.skipReviewer ?? true,
    maxIterate: opts.maxIterate,
    engine: opts.engine,
  });

  const { runId } = await createRunDir(instanceWork);
  await writeInputDefects(instanceWork, runId, request.defects, request);

  const handlers = createSweHandlers({
    instance: inst,
    predictionsPath: opts.predictionsPath,
    modelName,
    skipInstall: opts.skipInstall ?? true,
  });

  try {
    // Dummy token: core requires a token before calling deliverFix;
    // SWE deliverFix never talks to GitLab.
    const report = await runPipeline(instanceWork, runId, {
      engine: opts.engine,
      gitlabToken: "swe-eval-noop",
      gitlabHost: "https://swe.local",
      maxIterate: opts.maxIterate,
      handlers,
    });

    if (report.fixed[0]) {
      return {
        instance_id: inst.instance_id,
        runId,
        outcome: "fixed",
        mrUrl: report.fixed[0].mrUrl,
      };
    }
    const u = report.unfixed[0];
    return {
      instance_id: inst.instance_id,
      runId,
      outcome: "unfixed",
      reasonCode: u?.reasonCode,
      reasonDetail: u?.reasonDetail,
    };
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return {
      instance_id: inst.instance_id,
      runId,
      outcome: "error",
      reasonDetail: message,
    };
  }
}
