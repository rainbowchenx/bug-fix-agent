import { z } from "zod";

export const SCHEMA_VERSION = "0.1.0";

export const ExpectQualitySchema = z.enum(["explicit", "inferred", "ambiguous", "absent"]);
export type ExpectQuality = z.infer<typeof ExpectQualitySchema>;

export const PoolSchema = z.enum([
  "strict",
  "locatable_only",
  "needs_info",
  "hard_reject",
  "security",
  "excluded",
]);
export type Pool = z.infer<typeof PoolSchema>;

export const IntentSchema = z.enum([
  "ui_layout",
  "i18n",
  "logic",
  "data_wrong",
  "perf",
  "compat",
  "config",
  "security_scan",
  "crash",
  "unclear",
]);
export type Intent = z.infer<typeof IntentSchema>;

export const IntentSourceSchema = z.enum(["ai", "heuristic", "field_fallback", "unclear"]);
export type IntentSource = z.infer<typeof IntentSourceSchema>;

/** Ingest boundary: creation-time fields only (no closed-loop fields). */
export const RawDefectSchema = z.object({
  defectId: z.string().min(1),
  title: z.string().min(1),
  description: z.string().optional().default(""),
  status: z.string().optional(),
  flowStatus: z.string().optional(),
  testModule: z.string().optional(),
  fieldType: z.string().optional(),
  severity: z.string().optional(),
  createdAt: z.string().optional(),
  duplicateOf: z.string().optional(),
  productLine: z.string().optional(),
  metadata: z.record(z.string(), z.unknown()).optional(),
});
export type RawDefect = z.infer<typeof RawDefectSchema>;

export const RawDefectsFileSchema = z.object({
  schemaVersion: z.string().optional(),
  productLine: z.string().optional(),
  posture: z.enum(["alpha", "beta"]).optional(),
  defects: z.array(RawDefectSchema),
});
export type RawDefectsFile = z.infer<typeof RawDefectsFileSchema>;

export const DefectDigestSchema = z.object({
  defectId: z.string(),
  title: z.string(),
  description: z.string(),
  status: z.string().optional(),
  testModuleRaw: z.string().optional(),
  fieldType: z.string().optional(),
  severity: z.string().optional(),
  createdAt: z.string().optional(),
  duplicateOf: z.string().optional(),
  duplicate: z.boolean(),
  titleTag: z.string(),
  testModule: z.string(),
  semanticFree: z.boolean(),
  observed: z.string(),
  expected: z.string(),
  steps: z.string(),
  fullText: z.string(),
});
export type DefectDigest = z.infer<typeof DefectDigestSchema>;

export const ScreenedTicketSchema = z.object({
  digest: DefectDigestSchema,
  pool: PoolSchema,
  reasonCode: z.string().optional(),
  reasonDetail: z.string().optional(),
  expectQuality: ExpectQualitySchema,
  verdict: z.enum(["FIXABLE", "UNFIXABLE", "EXCLUDED", "SECURITY"]),
  ruleIds: z.array(z.string()).default([]),
});
export type ScreenedTicket = z.infer<typeof ScreenedTicketSchema>;

export const BatchTicketSchema = z.object({
  defectId: z.string(),
  title: z.string(),
  pool: PoolSchema,
  clusterId: z.string().optional(),
  testModule: z.string().optional(),
  titleTag: z.string().optional(),
  intent: IntentSchema.optional(),
  intentSource: IntentSourceSchema.optional(),
  intentConfidence: z.enum(["high", "medium", "low"]).optional(),
  intentRationale: z.string().optional(),
  fieldType: z.string().optional(),
  expectQuality: ExpectQualitySchema,
  reasonCode: z.string().optional(),
  reasonDetail: z.string().optional(),
  observed: z.string().optional(),
  expected: z.string().optional(),
  steps: z.string().optional(),
  status: z.string().optional(),
  severity: z.string().optional(),
  createdAt: z.string().optional(),
  duplicate: z.boolean().optional(),
  semanticFree: z.boolean().optional(),
  priority: z.number().optional(),
});
export type BatchTicket = z.infer<typeof BatchTicketSchema>;

export const BatchClusterSchema = z.object({
  clusterId: z.string(),
  testModule: z.string(),
  titleTag: z.string(),
  intent: IntentSchema,
  size: z.number().int().nonnegative(),
  openCount: z.number().int().nonnegative(),
  oversized: z.boolean().optional(),
  priority: z.number().optional(),
  defectIds: z.array(z.string()),
});
export type BatchCluster = z.infer<typeof BatchClusterSchema>;

export const DefectBatchSchema = z.object({
  schemaVersion: z.string(),
  productLine: z.string(),
  posture: z.enum(["alpha", "beta"]).default("beta"),
  generatedAt: z.string(),
  funnel: z.record(z.string(), z.number().int().nonnegative()),
  clusters: z.array(BatchClusterSchema),
  tickets: z.array(BatchTicketSchema),
});
export type DefectBatch = z.infer<typeof DefectBatchSchema>;

export interface ScreenProfile {
  rejectEmptyTemplate?: boolean;
  devicePatterns?: RegExp[];
  notcodeExtra?: RegExp[];
  disabledNotcode?: string[];
  scaSource?: RegExp;
  scaVuln?: RegExp;
}
