/** @deprecated import from `src/contracts` + `src/agents/analyst` instead. */
export {
  ANALYSIS_REPORT_SCHEMA_VERSION,
  AnalysisReportSchema,
  TicketReportSchema,
  TicketOutcomeSchema,
  validateAnalysisReport,
  safeValidateAnalysisReport,
  type AnalysisReport,
  type TicketReport,
  type TicketOutcome,
  type TicketBlockers,
} from "../contracts/index.js";

export {
  runAnalyst as runDefectAnalyst,
  type RunAnalystInput as RunDefectAnalystInput,
  type AnalystFn as DefectAnalystFn,
} from "../agents/analyst/index.js";
