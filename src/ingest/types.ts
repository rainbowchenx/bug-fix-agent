import type { RawDefect, RawDefectsFile } from "../defect-batch/types.js";

export type IngestMode = "mcp" | "crawler" | "preloaded";

export interface IngestRequest {
  mode: IngestMode;
  productLine?: string;
  /** For preloaded: path to JSON file or inline payload */
  source?: string | RawDefectsFile | RawDefect[];
}

export interface IngestResult {
  mode: IngestMode;
  productLine?: string;
  defects: RawDefect[];
}

export interface IngestAdapter {
  readonly mode: IngestMode;
  ingest(req: IngestRequest): Promise<IngestResult>;
}
