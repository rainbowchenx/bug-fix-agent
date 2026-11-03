import type { IngestAdapter, IngestRequest, IngestResult } from "./types.js";

/** Crawler backup stub — drop crawler output as preloaded JSON for now. */
export const crawlerIngestAdapter: IngestAdapter = {
  mode: "crawler",
  async ingest(_req: IngestRequest): Promise<IngestResult> {
    throw new Error(
      "Crawler ingest is not configured yet. Export crawler output to JSON and use mode=preloaded.",
    );
  },
};
