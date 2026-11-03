/**
 * Cross-agent contracts — the ONLY allowed coupling surface.
 * Agents must not import each other's internals.
 */
export {
  CONTRACT_SCHEMA_VERSION,
  ConfidenceSchema,
  MATCH_POOLS,
  isMatchPool,
  type Confidence,
  type MatchPool,
} from "./common.js";

export {
  DEFECT_BATCH_SCHEMA_VERSION,
  DefectBatchSchema,
  BatchTicketSchema,
  BatchClusterSchema,
  PoolSchema,
  IntentSchema,
  ExpectQualitySchema,
  validateDefectBatch,
  safeValidateDefectBatch,
  type DefectBatch,
  type BatchTicket,
  type BatchCluster,
  type Pool,
  type Intent,
  type ExpectQuality,
} from "./defect-batch.js";

export {
  CODE_KNOWLEDGE_SCHEMA_VERSION,
  CodeKnowledgeSchema,
  CartographyProfileSchema,
  DefectCodeMatchSchema,
  MatchCandidateSchema,
  SpecAtlasSchema,
  validateCodeKnowledge,
  safeValidateCodeKnowledge,
  type CodeKnowledge,
  type CartographyProfile,
  type DefectCodeMatch,
  type MatchCandidate,
  type SpecAtlas,
  type ArchModule,
  type RepoRoot,
} from "./code-knowledge.js";

export {
  ANALYSIS_REPORT_SCHEMA_VERSION,
  AnalysisReportSchema,
  TicketReportSchema,
  TicketOutcomeSchema,
  TicketBlockersSchema,
  validateAnalysisReport,
  safeValidateAnalysisReport,
  type AnalysisReport,
  type TicketReport,
  type TicketOutcome,
  type TicketBlockers,
  type TicketSlice,
  type Localization,
} from "./analysis-report.js";
