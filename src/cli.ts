#!/usr/bin/env node
import { readFile } from "node:fs/promises";
import path from "node:path";
import { loadConfig } from "./config.js";
import { parseCreateRunRequest, type Engine } from "./types.js";
import { createRunDir, writeInputDefects } from "./runs/store.js";
import { runPipeline } from "./runs/runner.js";

const VERSION = "0.1.0";

function printHelp(): void {
  console.log(`bugfix-agent ${VERSION}

Usage:
  bugfix-agent serve [--port <n>]
  bugfix-agent run --work-dir <path> --defects <file.json> [--engine pipeline|langgraph]
  bugfix-agent version
  bugfix-agent --help

Environment:
  PORT, ANTHROPIC_API_KEY, ANTHROPIC_BASE_URL, ANTHROPIC_MODEL
  GITLAB_TOKEN, GITLAB_HOST
  BUGFIX_EXEC_TIMEOUT_MS, BUGFIX_SDK_TIMEOUT_MS, BUGFIX_MAX_ITERATE
`);
}

function flagValue(args: string[], name: string): string | undefined {
  const idx = args.indexOf(name);
  if (idx < 0) return undefined;
  return args[idx + 1];
}

async function runCommand(args: string[]): Promise<void> {
  const workDir = flagValue(args, "--work-dir") ?? flagValue(args, "--workDir");
  const defectsPath = flagValue(args, "--defects");
  const engineRaw = flagValue(args, "--engine");

  if (!workDir || !defectsPath) {
    console.error("Usage: bugfix-agent run --work-dir <path> --defects <file.json> [--engine pipeline|langgraph]");
    process.exitCode = 1;
    return;
  }

  let engine: Engine | undefined;
  if (engineRaw) {
    if (engineRaw !== "pipeline" && engineRaw !== "langgraph") {
      console.error(`Invalid --engine: ${engineRaw} (expected pipeline|langgraph)`);
      process.exitCode = 1;
      return;
    }
    engine = engineRaw;
  }

  const raw = JSON.parse(await readFile(path.resolve(defectsPath), "utf8")) as unknown;
  const defectsPayload =
    Array.isArray(raw) ? { workDir: path.resolve(workDir), defects: raw } : raw;
  const request = parseCreateRunRequest({
    ...(typeof defectsPayload === "object" && defectsPayload !== null ? defectsPayload : {}),
    workDir: path.resolve(workDir),
  });
  if (engine) {
    request.options = { ...request.options, engine };
  }

  const { runId } = await createRunDir(request.workDir);
  await writeInputDefects(request.workDir, runId, request.defects, request);

  console.log(`runId=${runId} workDir=${request.workDir} engine=${request.options?.engine ?? "pipeline"}`);
  const report = await runPipeline(request.workDir, runId, { engine: request.options?.engine });
  console.log(JSON.stringify(report, null, 2));

  const allFixed =
    report.summary.totalClusters > 0 &&
    report.summary.unfixed === 0 &&
    report.summary.fixed === report.summary.totalClusters;
  process.exitCode = allFixed ? 0 : 1;
}

async function main(argv: string[]): Promise<void> {
  const args = argv.slice(2);
  const cmd = args[0];

  if (!cmd || cmd === "--help" || cmd === "-h" || cmd === "help") {
    printHelp();
    return;
  }

  if (cmd === "version" || cmd === "--version" || cmd === "-v") {
    console.log(VERSION);
    return;
  }

  if (cmd === "serve") {
    const portIdx = args.indexOf("--port");
    const portOverride =
      portIdx >= 0 && args[portIdx + 1] ? Number(args[portIdx + 1]) : undefined;
    const cfg = loadConfig();
    const port = portOverride && Number.isFinite(portOverride) ? portOverride : cfg.port;
    const { startServer } = await import("./index.js");
    await startServer({ port });
    return;
  }

  if (cmd === "run") {
    await runCommand(args);
    return;
  }

  console.error(`Unknown command: ${cmd}`);
  printHelp();
  process.exitCode = 1;
}

main(process.argv).catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
