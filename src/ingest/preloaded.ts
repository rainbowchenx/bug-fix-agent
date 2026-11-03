import { readFile } from "node:fs/promises";
import {
  RawDefectSchema,
  RawDefectsFileSchema,
  type RawDefect,
  type RawDefectsFile,
} from "../defect-batch/types.js";
import type { IngestAdapter, IngestRequest, IngestResult } from "./types.js";

function normalizePayload(
  raw: unknown,
  productLine?: string,
): { defects: RawDefect[]; productLine?: string } {
  if (Array.isArray(raw)) {
    return {
      defects: raw.map((item, i) => {
        const parsed = RawDefectSchema.safeParse(item);
        if (!parsed.success) {
          throw new Error(`Invalid raw defect at index ${i}: ${parsed.error.message}`);
        }
        return parsed.data;
      }),
      productLine,
    };
  }
  const file = RawDefectsFileSchema.parse(raw);
  return { defects: file.defects, productLine: file.productLine ?? productLine };
}

export async function loadPreloadedSource(
  source: string | RawDefectsFile | RawDefect[],
  productLine?: string,
): Promise<{ defects: RawDefect[]; productLine?: string }> {
  if (typeof source === "string") {
    const text = await readFile(source, "utf8");
    return normalizePayload(JSON.parse(text) as unknown, productLine);
  }
  return normalizePayload(source, productLine);
}

export const preloadedIngestAdapter: IngestAdapter = {
  mode: "preloaded",
  async ingest(req: IngestRequest): Promise<IngestResult> {
    if (req.source === undefined) {
      throw new Error("preloaded ingest requires req.source (path or payload)");
    }
    const loaded = await loadPreloadedSource(req.source, req.productLine);
    return {
      mode: "preloaded",
      productLine: loaded.productLine ?? req.productLine,
      defects: loaded.defects,
    };
  },
};
