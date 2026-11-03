import { ingestRawDefects } from "../ingest/index.js";
import type { IngestMode } from "../ingest/types.js";
import { prepareDefectBatch, type PrepareBatchInput } from "./prepare.js";
import type { DefectBatch, RawDefect, RawDefectsFile, ScreenProfile } from "./types.js";
import type { ClusterOptions } from "./cluster.js";

export interface RunDefectBatchPrepareInput {
  mode: IngestMode;
  productLine: string;
  posture?: "alpha" | "beta";
  source?: string | RawDefectsFile | RawDefect[];
  profile?: ScreenProfile;
  cluster?: ClusterOptions;
  validate?: boolean;
}

/**
 * Full Agent-1 unit: ingest → prepareDefectBatch → validated defect-batch.
 */
export async function runDefectBatchPrepare(
  input: RunDefectBatchPrepareInput,
): Promise<DefectBatch> {
  const ingested = await ingestRawDefects({
    mode: input.mode,
    productLine: input.productLine,
    source: input.source,
  });
  const prepareInput: PrepareBatchInput = {
    productLine: ingested.productLine ?? input.productLine,
    posture: input.posture,
    defects: ingested.defects,
    profile: input.profile,
    cluster: input.cluster,
    validate: input.validate,
  };
  return prepareDefectBatch(prepareInput);
}
