#!/usr/bin/env node
import { loadConfig } from "./config.js";

const VERSION = "0.1.0";

function printHelp(): void {
  console.log(`bugfix-agent ${VERSION}

Usage:
  bugfix-agent serve [--port <n>]
  bugfix-agent run --work-dir <path> [--defects <file.json>]
  bugfix-agent version
  bugfix-agent --help

Environment:
  PORT, ANTHROPIC_API_KEY, ANTHROPIC_BASE_URL, ANTHROPIC_MODEL
  GITLAB_TOKEN, GITLAB_HOST
`);
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
    // Wired in Task 4
    const { startServer } = await import("./index.js");
    await startServer({ port });
    return;
  }

  if (cmd === "run") {
    console.error("bugfix-agent run: not yet implemented (see Task 4+)");
    process.exitCode = 1;
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
