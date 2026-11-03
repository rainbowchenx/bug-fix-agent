import { serve } from "@hono/node-server";
import { loadConfig, type AppConfig } from "./config.js";
import { createApp } from "./http/app.js";

export { loadConfig, type AppConfig } from "./config.js";
export { createApp } from "./http/app.js";
export { startRun } from "./runs/create-run.js";
export { runPipeline } from "./runs/runner.js";
export type { RunnerOptions, ClusterHandlers } from "./runs/runner.js";
export * from "./graph/index.js";
export * from "./types.js";
export * from "./agent/artifacts.js";
export { listBuiltinSkills, filterSkills } from "./skills/manifest.js";
export { mergeMcpConfig, expandEnvVars } from "./mcp/load-config.js";
export { noopStorage } from "./storage/noop.js";
export { createHttpStorage } from "./storage/http.js";
export { safeSync } from "./storage/adapter.js";
export type { StorageAdapter, StorageSyncMode } from "./storage/adapter.js";
export { checkScopeLock, extractAllowedFiles } from "./pipeline/scope-lock.js";
export { buildKnownIssuesDetail } from "./pipeline/known-issues.js";
export { FAILURE_MODES } from "./pipeline/failure-modes.js";
export { classifyVerifyFailure } from "./pipeline/verify-classify.js";
export { snipVerifyLog } from "./pipeline/log-snip.js";
export { resolveStaticCheckPlan, runStaticCheck } from "./pipeline/static-check.js";
export { reviewCluster, parseReviewResult } from "./pipeline/review.js";

/** Agent-1 */
export * from "./defect-batch/index.js";
export {
  ingestRawDefects,
  getIngestAdapter,
  preloadedIngestAdapter,
  mcpIngestAdapter,
  crawlerIngestAdapter,
} from "./ingest/index.js";
export type { IngestAdapter, IngestMode, IngestRequest, IngestResult } from "./ingest/index.js";

/** Cross-agent contracts (preferred import surface for I/O) */
export * from "./contracts/index.js";

/** Agent-2 / Agent-3 packages */
export * from "./agents/index.js";

/** Parent workflow */
export * from "./workflow/index.js";

export interface StartServerOptions {
  port?: number;
  hostname?: string;
}

export async function startServer(options: StartServerOptions = {}): Promise<void> {
  const cfg = loadConfig();
  const port = options.port ?? cfg.port;
  const hostname = options.hostname ?? "127.0.0.1";
  const app = createApp();

  serve({ fetch: app.fetch, port, hostname }, (info) => {
    console.log(`bugfix-agent listening on http://${hostname}:${info.port}`);
  });
}
