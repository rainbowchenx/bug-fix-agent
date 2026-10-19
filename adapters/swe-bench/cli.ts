#!/usr/bin/env node
/**
 * SWE-bench adapter CLI — independent of core CLI.
 *
 *   npx tsx adapters/swe-bench/cli.ts \
 *     --instances path/to/instances.jsonl \
 *     --work-dir D:/eval/swe \
 *     --predictions D:/eval/swe/predictions.jsonl \
 *     --limit 20
 *
 * Then score with the official harness (separate process):
 *   python -m swebench.harness.run_evaluation --predictions_path ... --run_id ...
 */
import path from "node:path";
import { config as loadDotenv } from "dotenv";
import { loadSweInstances } from "./load-instances.js";
import { runSweBatch } from "./run-batch.js";

loadDotenv();

function flag(args: string[], name: string): string | undefined {
  const i = args.indexOf(name);
  return i >= 0 ? args[i + 1] : undefined;
}

function flagNum(args: string[], name: string): number | undefined {
  const v = flag(args, name);
  if (v === undefined) return undefined;
  const n = Number(v);
  return Number.isFinite(n) ? n : undefined;
}

async function main(argv: string[]): Promise<void> {
  const args = argv.slice(2);
  if (!args.length || args.includes("-h") || args.includes("--help")) {
    console.log(`Usage:
  npx tsx adapters/swe-bench/cli.ts --instances <file.json|jsonl> --work-dir <dir> --predictions <out.jsonl> [--limit N] [--engine pipeline|langgraph] [--model-name NAME]

Environment: ANTHROPIC_API_KEY, ANTHROPIC_BASE_URL, ANTHROPIC_MODEL
`);
    return;
  }

  const instancesPath = flag(args, "--instances");
  const workDir = flag(args, "--work-dir") ?? flag(args, "--workDir");
  const predictionsPath = flag(args, "--predictions");
  if (!instancesPath || !workDir || !predictionsPath) {
    console.error("Required: --instances --work-dir --predictions");
    process.exitCode = 1;
    return;
  }

  const engineRaw = flag(args, "--engine");
  const engine =
    engineRaw === "langgraph" || engineRaw === "pipeline" ? engineRaw : undefined;

  if (!process.env.ANTHROPIC_API_KEY) {
    console.error(
      "ANTHROPIC_API_KEY is not set. Create a .env in the repo root (see .env.example) before running the baseline.",
    );
    process.exitCode = 2;
    return;
  }

  const instances = await loadSweInstances(path.resolve(instancesPath));
  console.log(`Loaded ${instances.length} instances; limit=${flagNum(args, "--limit") ?? "all"}`);

  const { results, predictionsPath: out } = await runSweBatch({
    workDir: path.resolve(workDir),
    instances,
    predictionsPath: path.resolve(predictionsPath),
    limit: flagNum(args, "--limit"),
    modelName: flag(args, "--model-name"),
    engine,
    skipReviewer: !args.includes("--reviewer"),
    maxIterate: flagNum(args, "--max-iterate") ?? 3,
    skipInstall: !args.includes("--install"),
  });

  const fixed = results.filter((r) => r.outcome === "fixed").length;
  const unfixed = results.filter((r) => r.outcome === "unfixed").length;
  const errors = results.filter((r) => r.outcome === "error").length;
  console.log(JSON.stringify({ fixed, unfixed, errors, predictions: out, results }, null, 2));
  process.exitCode = fixed === results.length && results.length > 0 ? 0 : 1;
}

main(process.argv).catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
