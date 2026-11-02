import type { IngestAdapter, IngestRequest, IngestResult } from "./types.js";

/**
 * MCP ingest stub — wire concrete defect MCP tool names/field maps later.
 * Skill documents usage; adapter must perform the actual pull.
 */
export const mcpIngestAdapter: IngestAdapter = {
  mode: "mcp",
  async ingest(_req: IngestRequest): Promise<IngestResult> {
    throw new Error(
      "MCP ingest is not configured yet. Provide defect MCP tool mapping or use mode=preloaded.",
    );
  },
};
