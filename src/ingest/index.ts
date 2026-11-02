import { crawlerIngestAdapter } from "./crawler.js";
import { mcpIngestAdapter } from "./mcp.js";
import { preloadedIngestAdapter } from "./preloaded.js";
import type { IngestAdapter, IngestMode, IngestRequest, IngestResult } from "./types.js";

export type { IngestAdapter, IngestMode, IngestRequest, IngestResult } from "./types.js";
export { preloadedIngestAdapter } from "./preloaded.js";
export { mcpIngestAdapter } from "./mcp.js";
export { crawlerIngestAdapter } from "./crawler.js";

const ADAPTERS: Record<IngestMode, IngestAdapter> = {
  preloaded: preloadedIngestAdapter,
  mcp: mcpIngestAdapter,
  crawler: crawlerIngestAdapter,
};

export function getIngestAdapter(mode: IngestMode): IngestAdapter {
  return ADAPTERS[mode];
}

/** Pull raw-defects via the selected adapter (Agent-1 ingest boundary). */
export async function ingestRawDefects(req: IngestRequest): Promise<IngestResult> {
  return getIngestAdapter(req.mode).ingest(req);
}
