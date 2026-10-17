import { z } from "zod";

export const ReasonCodeSchema = z.enum([
  "not_actionable",
  "needs_more_context",
  "verify_failed",
  "env_verify_failed",
  "static_check_failed",
  "review_failed",
  "no_test_command",
  "push_failed",
  "localize_failed",
  "prepare_failed",
  "implement_failed",
  "no_changes",
  "aggregate_skipped",
  "analyze_failed",
  "validation_failed",
  "cancelled",
  "unknown",
]);
export type ReasonCode = z.infer<typeof ReasonCodeSchema>;

export const DefectSchema = z.object({
  id: z.string().min(1),
  title: z.string().min(1),
  description: z.string().optional(),
  repoUrl: z.string().min(1),
  branch: z.string().optional(),
  fingerprint: z.string().optional(),
  stackTrace: z.string().optional(),
  pageUrl: z.string().optional(),
  severity: z.string().optional(),
  metadata: z.record(z.string(), z.unknown()).optional(),
});
export type Defect = z.infer<typeof DefectSchema>;

export const ClusterSchema = z.object({
  id: z.string().min(1),
  defectIds: z.array(z.string()).min(1),
  repoUrl: z.string().min(1),
  branch: z.string().optional(),
  primaryTitle: z.string().min(1),
  fingerprint: z.string().optional(),
});
export type Cluster = z.infer<typeof ClusterSchema>;

export const ClusterOutcomeSchema = z.enum(["fixed", "unfixed"]);
export type ClusterOutcome = z.infer<typeof ClusterOutcomeSchema>;

export const VerifySummarySchema = z.object({
  command: z.string(),
  ok: z.boolean(),
  logTail: z.string().optional(),
});
export type VerifySummary = z.infer<typeof VerifySummarySchema>;

export const FixedClusterSchema = z.object({
  clusterId: z.string(),
  defectIds: z.array(z.string()),
  mrUrl: z.string().url().or(z.string().min(1)),
  rootCauseSummary: z.string().optional(),
  verify: VerifySummarySchema.optional(),
});
export type FixedCluster = z.infer<typeof FixedClusterSchema>;

export const UnfixedClusterSchema = z.object({
  clusterId: z.string(),
  defectIds: z.array(z.string()),
  reasonCode: ReasonCodeSchema,
  reasonDetail: z.string().min(1),
  artifacts: z
    .object({
      rootCause: z.string().optional(),
      solution: z.string().optional(),
    })
    .optional(),
});
export type UnfixedCluster = z.infer<typeof UnfixedClusterSchema>;

export const RunReportSchema = z.object({
  runId: z.string().min(1),
  summary: z.object({
    totalClusters: z.number().int().nonnegative(),
    fixed: z.number().int().nonnegative(),
    unfixed: z.number().int().nonnegative(),
  }),
  fixed: z.array(FixedClusterSchema),
  unfixed: z.array(UnfixedClusterSchema),
});
export type RunReport = z.infer<typeof RunReportSchema>;

export const RunStatusSchema = z.enum([
  "queued",
  "running",
  "completed",
  "failed",
]);
export type RunStatus = z.infer<typeof RunStatusSchema>;

export const RunMetaSchema = z.object({
  runId: z.string(),
  workDir: z.string(),
  status: RunStatusSchema,
  createdAt: z.string(),
  updatedAt: z.string(),
  progress: z
    .object({
      phase: z.string().optional(),
      currentClusterId: z.string().optional(),
      completedClusters: z.number().int().nonnegative().optional(),
      totalClusters: z.number().int().nonnegative().optional(),
      message: z.string().optional(),
    })
    .optional(),
  error: z.string().optional(),
});
export type RunMeta = z.infer<typeof RunMetaSchema>;

export const McpServerConfigSchema = z.object({
  command: z.string().optional(),
  args: z.array(z.string()).optional(),
  url: z.string().optional(),
  env: z.record(z.string(), z.string()).optional(),
  transport: z.enum(["stdio", "sse", "http"]).optional(),
});
export type McpServerConfig = z.infer<typeof McpServerConfigSchema>;

export const EngineSchema = z.enum(["pipeline", "langgraph"]);
export type Engine = z.infer<typeof EngineSchema>;

export const CreateRunOptionsSchema = z.object({
  /** Orchestrator: legacy imperative `pipeline` (default) or the `langgraph` StateGraph. */
  engine: EngineSchema.optional(),
  maxIterate: z.number().int().positive().optional(),
  concurrency: z.number().int().positive().optional(),
  verifyOverrides: z
    .object({
      install: z.array(z.string()).optional(),
      test: z.array(z.string()).optional(),
    })
    .optional(),
  skills: z
    .object({
      enabled: z.array(z.string()).optional(),
      disabled: z.array(z.string()).optional(),
    })
    .optional(),
  mcp: z.record(z.string(), McpServerConfigSchema).optional(),
  gitlabProjectId: z.union([z.string(), z.number()]).optional(),
  /** Skip readonly reviewer gate (debug / fast path). Default false = reviewer on. */
  skipReviewer: z.boolean().optional(),
  /** Open GitLab MR as Draft. */
  draftMr: z.boolean().optional(),
});
export type CreateRunOptions = z.infer<typeof CreateRunOptionsSchema>;

export const CreateRunRequestSchema = z.object({
  workDir: z.string().min(1),
  defects: z.array(DefectSchema).min(1),
  userPrompt: z.string().optional(),
  options: CreateRunOptionsSchema.optional(),
});
export type CreateRunRequest = z.infer<typeof CreateRunRequestSchema>;

export function parseReport(data: unknown): RunReport {
  return RunReportSchema.parse(data);
}

export function parseCreateRunRequest(data: unknown): CreateRunRequest {
  return CreateRunRequestSchema.parse(data);
}
