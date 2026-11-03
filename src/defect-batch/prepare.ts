import { clusterScreened, type ClusterOptions } from "./cluster.js";
import { distillAll } from "./distill.js";
import { funnelCounts, screenAll, type ScreenOptions } from "./screen.js";
import {
  SCHEMA_VERSION,
  type DefectBatch,
  type RawDefect,
  type ScreenProfile,
} from "./types.js";
import { validateDefectBatch } from "./validate.js";

export interface PrepareBatchInput {
  productLine: string;
  posture?: "alpha" | "beta";
  defects: RawDefect[];
  profile?: ScreenProfile;
  cluster?: ClusterOptions;
  /** When false, skip zod validate (default true). */
  validate?: boolean;
  now?: () => string;
}

/**
 * Agent-1 deterministic pipeline after ingest:
 * distill → screen (R0–R3) → cluster (R4–R6) → defect-batch
 */
export async function prepareDefectBatch(input: PrepareBatchInput): Promise<DefectBatch> {
  const posture = input.posture ?? "beta";
  const digests = distillAll(input.defects);
  const screenOpts: ScreenOptions = { posture, profile: input.profile };
  const screened = screenAll(digests, screenOpts);
  const { clusters, tickets } = await clusterScreened(
    screened,
    input.productLine,
    input.cluster,
  );

  const batch: DefectBatch = {
    schemaVersion: SCHEMA_VERSION,
    productLine: input.productLine,
    posture,
    generatedAt: (input.now ?? (() => new Date().toISOString()))(),
    funnel: funnelCounts(screened),
    clusters,
    tickets,
  };

  if (input.validate === false) return batch;
  return validateDefectBatch(batch);
}
