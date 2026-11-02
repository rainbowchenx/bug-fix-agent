import { DefectBatchSchema, type DefectBatch } from "./types.js";

export function validateDefectBatch(input: unknown): DefectBatch {
  return DefectBatchSchema.parse(input);
}

export function safeValidateDefectBatch(
  input: unknown,
): { ok: true; data: DefectBatch } | { ok: false; error: string } {
  const parsed = DefectBatchSchema.safeParse(input);
  if (!parsed.success) {
    return { ok: false, error: parsed.error.message };
  }
  return { ok: true, data: parsed.data };
}
