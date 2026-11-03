/**
 * Public defect-batch contract (Agent-1 → Agent-2 / Agent-3).
 * Implementation lives in `src/defect-batch`; this module is the cross-agent surface.
 */
export {
  SCHEMA_VERSION as DEFECT_BATCH_SCHEMA_VERSION,
  DefectBatchSchema,
  BatchTicketSchema,
  BatchClusterSchema,
  PoolSchema,
  IntentSchema,
  ExpectQualitySchema,
  type DefectBatch,
  type BatchTicket,
  type BatchCluster,
  type Pool,
  type Intent,
  type ExpectQuality,
} from "../defect-batch/types.js";

export {
  validateDefectBatch,
  safeValidateDefectBatch,
} from "../defect-batch/validate.js";
