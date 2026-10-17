import path from "node:path";
import { loadConfig } from "../config.js";
import type { RootCauseArtifact, SolutionArtifact } from "../agent/artifacts.js";
import { analyzeCluster } from "../pipeline/analyze.js";
import { aggregateDefects } from "../pipeline/aggregate.js";
import { deliverFix } from "../pipeline/deliver.js";
import { implementCluster, shouldContinueIterate } from "../pipeline/implement.js";
import { buildKnownIssuesDetail } from "../pipeline/known-issues.js";
import { snipVerifyLog } from "../pipeline/log-snip.js";
import { normalizeDefects } from "../pipeline/normalize.js";
import { prepareRepo } from "../pipeline/prepare.js";
import { buildReport } from "../pipeline/report.js";
import { reviewCluster } from "../pipeline/review.js";
import { checkScopeLock } from "../pipeline/scope-lock.js";
import {
  resolveStaticCheckPlan,
  runStaticCheck,
} from "../pipeline/static-check.js";
import {
  classifyVerifyFailure,
  reasonCodeForClassify,
} from "../pipeline/verify-classify.js";
import { resolveVerifyPlan, runVerify } from "../pipeline/verify.js";
import type {
  Cluster,
  CreateRunRequest,
  Defect,
  Engine,
  FixedCluster,
  ReasonCode,
  RunReport,
  UnfixedCluster,
} from "../types.js";
import { mergeMcpConfig } from "../mcp/load-config.js";
import { defaultSkillsDir } from "../agent/sdk-runner.js";
import { ensureRepo } from "../workspace/git.js";
import { runDir } from "../workspace/paths.js";
import {
  readJson,
  updateRunMeta,
  writeClusterArtifact,
  writeClustersPlan,
  writeReport,
} from "./store.js";

export interface ClusterHandlers {
  ensureRepo?: typeof ensureRepo;
  analyzeCluster?: typeof analyzeCluster;
  prepareRepo?: typeof prepareRepo;
  implementCluster?: typeof implementCluster;
  runVerify?: typeof runVerify;
  resolveVerifyPlan?: typeof resolveVerifyPlan;
  deliverFix?: typeof deliverFix;
  resolveStaticCheckPlan?: typeof resolveStaticCheckPlan;
  runStaticCheck?: typeof runStaticCheck;
  reviewCluster?: typeof reviewCluster;
  classifyVerifyFailure?: typeof classifyVerifyFailure;
}

export interface RunnerOptions {
  /** Overrides `options.engine` from the run request. */
  engine?: Engine;
  handlers?: ClusterHandlers;
  maxIterate?: number;
  gitlabToken?: string;
  gitlabHost?: string;
}

export function enqueueRun(workDir: string, runId: string, options?: RunnerOptions): void {
  setImmediate(() => {
    void runPipeline(workDir, runId, options).catch(async (err) => {
      const message = err instanceof Error ? err.message : String(err);
      await updateRunMeta(workDir, runId, {
        status: "failed",
        error: message,
      });
    });
  });
}

async function loadRequest(workDir: string, runId: string): Promise<{
  defects: Defect[];
  userPrompt?: string;
  options?: CreateRunRequest["options"];
}> {
  const dir = runDir(workDir, runId);
  try {
    const req = await readJson<CreateRunRequest>(path.join(dir, "input.request.json"));
    return {
      defects: req.defects,
      userPrompt: req.userPrompt,
      options: req.options,
    };
  } catch {
    const defects = await readJson<Defect[]>(path.join(dir, "input.defects.json"));
    return { defects };
  }
}

function unfixedBase(
  cluster: Cluster,
  reasonCode: ReasonCode,
  reasonDetail: string,
  rootCause?: string,
  solution?: string,
): { unfixed: UnfixedCluster } {
  return {
    unfixed: {
      clusterId: cluster.id,
      defectIds: cluster.defectIds,
      reasonCode,
      reasonDetail,
      artifacts:
        rootCause || solution
          ? { rootCause, solution }
          : undefined,
    },
  };
}

async function processCluster(args: {
  workDir: string;
  runId: string;
  cluster: Cluster;
  defects: Defect[];
  userPrompt?: string;
  options?: CreateRunRequest["options"];
  runner: RunnerOptions;
}): Promise<{ fixed?: FixedCluster; unfixed?: UnfixedCluster }> {
  const h = { ...args.runner.handlers };
  const cfg = loadConfig();
  const maxIterate = args.runner.maxIterate ?? args.options?.maxIterate ?? cfg.maxIterate;
  const token = args.runner.gitlabToken ?? cfg.gitlabToken;
  const host = args.runner.gitlabHost ?? cfg.gitlabHost;
  const skipReviewer = args.options?.skipReviewer === true;
  const clusterDefects = args.defects.filter((d) => args.cluster.defectIds.includes(d.id));

  let repoPath: string;
  try {
    const ensure = h.ensureRepo ?? ensureRepo;
    const ensured = await ensure({
      workDir: args.workDir,
      repoUrl: args.cluster.repoUrl,
      branch: args.cluster.branch,
      token,
    });
    repoPath = ensured.repoPath;
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return unfixedBase(args.cluster, "prepare_failed", `Failed to ensure repo: ${message}`);
  }

  const mcpServers = await mergeMcpConfig({
    workDir: args.workDir,
    runMcp: args.options?.mcp,
  });
  const skillsDir = defaultSkillsDir();

  const analyze = h.analyzeCluster ?? analyzeCluster;
  const analysis = await analyze({
    cluster: args.cluster,
    defects: clusterDefects,
    repoPath,
    userPrompt: args.userPrompt,
    mcpServers,
    skillsDir,
  });

  if (analysis.rootCause) {
    await writeClusterArtifact(
      args.workDir,
      args.runId,
      args.cluster.id,
      "root-cause.json",
      analysis.rootCause,
    );
  }
  if (analysis.solution) {
    await writeClusterArtifact(
      args.workDir,
      args.runId,
      args.cluster.id,
      "solution.json",
      analysis.solution,
    );
  }

  if (analysis.status === "unfixed") {
    return unfixedBase(
      args.cluster,
      analysis.reasonCode,
      analysis.reasonDetail,
      analysis.rootCause?.one_line_description,
      analysis.solution?.one_line_summary,
    );
  }

  const resolvePlan = h.resolveVerifyPlan ?? resolveVerifyPlan;
  const plan = await resolvePlan({
    repoPath,
    userPrompt: args.userPrompt,
    overrides: args.options?.verifyOverrides,
  });

  if (!plan.test.length) {
    return unfixedBase(
      args.cluster,
      "no_test_command",
      "No verify/test command detected; refusing to open MR without GREEN gate.",
      analysis.rootCause.one_line_description,
      analysis.solution.one_line_summary,
    );
  }

  const prepare = h.prepareRepo ?? prepareRepo;
  const prepared = await prepare(repoPath, plan);
  if (!prepared.ok) {
    return unfixedBase(
      args.cluster,
      "prepare_failed",
      `Install failed: ${prepared.logTail}`,
    );
  }

  const resolveStatic = h.resolveStaticCheckPlan ?? resolveStaticCheckPlan;
  const staticPlan = await resolveStatic(repoPath);
  const runStatic = h.runStaticCheck ?? runStaticCheck;
  const implement = h.implementCluster ?? implementCluster;
  const verify = h.runVerify ?? runVerify;
  const classify = h.classifyVerifyFailure ?? classifyVerifyFailure;
  const review = h.reviewCluster ?? reviewCluster;

  let feedbackLog = "";
  let lastVerifyLog = "";
  let verifyOk = false;
  let verifyCommand = plan.test.join(" && ");
  let iteration = 0;
  let lastStaticFail = false;
  let stopReason: { reasonCode: ReasonCode; detail: string } | null = null;

  while (true) {
    iteration += 1;
    try {
      const impl = await implement({
        cluster: args.cluster,
        repoPath,
        rootCause: analysis.rootCause,
        solution: analysis.solution,
        verifyLogTail: feedbackLog || undefined,
        iteration,
      });
      const scope =
        impl.scopeOk === false
          ? { ok: false, violations: impl.scopeViolations }
          : checkScopeLock(impl.changedFiles ?? [], analysis.solution);
      if (!scope.ok) {
        await writeClusterArtifact(args.workDir, args.runId, args.cluster.id, "scope-lock.json", scope);
        return unfixedBase(
          args.cluster,
          "implement_failed",
          `Scope lock violated — edits outside solution target_files: ${scope.violations.join(", ")}`,
          analysis.rootCause.one_line_description,
          analysis.solution.one_line_summary,
        );
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      return unfixedBase(args.cluster, "implement_failed", message);
    }

    const staticResult = await runStatic(repoPath, staticPlan);
    await writeClusterArtifact(
      args.workDir,
      args.runId,
      args.cluster.id,
      "static-check.json",
      staticResult,
    );
    if (!staticResult.ok) {
      lastStaticFail = true;
      feedbackLog = snipVerifyLog(staticResult.logTail);
      if (!shouldContinueIterate(iteration, maxIterate, false)) {
        stopReason = {
          reasonCode: "static_check_failed",
          detail: buildKnownIssuesDetail({
            iterations: iteration,
            maxIterate,
            verifyCommand: staticResult.command,
            logTail: staticResult.logTail,
            rootCauseSummary: analysis.rootCause.one_line_description,
            solutionSummary: analysis.solution.one_line_summary,
            actionsTaken: [
              `Static check failed after ${iteration} iteration(s)`,
              `Command: ${staticResult.command}`,
            ],
          }),
        };
        break;
      }
      continue;
    }
    lastStaticFail = false;

    const result = await verify(repoPath, plan);
    verifyCommand = result.command;
    lastVerifyLog = result.logTail;
    await writeClusterArtifact(args.workDir, args.runId, args.cluster.id, "verify.json", result);
    verifyOk = result.ok;

    if (!verifyOk) {
      const classification = classify(result.logTail, result.command);
      await writeClusterArtifact(
        args.workDir,
        args.runId,
        args.cluster.id,
        "verify-classify.json",
        classification,
      );
      if (classification.stopIterate) {
        stopReason = {
          reasonCode: reasonCodeForClassify(classification.kind),
          detail: [
            `Smart Routing: ${classification.kind}`,
            classification.reason,
            "",
            snipVerifyLog(result.logTail),
          ].join("\n"),
        };
        break;
      }
      feedbackLog = snipVerifyLog(result.logTail);
      if (!shouldContinueIterate(iteration, maxIterate, false)) {
        stopReason = {
          reasonCode: "verify_failed",
          detail: buildKnownIssuesDetail({
            iterations: iteration,
            maxIterate,
            verifyCommand,
            logTail: lastVerifyLog,
            rootCauseSummary: analysis.rootCause.one_line_description,
            solutionSummary: analysis.solution.one_line_summary,
            actionsTaken: [
              `Analyzed cluster ${args.cluster.id}`,
              `Implement→static→verify ${iteration} time(s)`,
              `Last classify: ${classification.kind}`,
            ],
          }),
        };
        break;
      }
      continue;
    }

    // Verify GREEN — optional reviewer
    if (!skipReviewer) {
      const reviewResult = await review({
        repoPath,
        rootCause: analysis.rootCause,
        solution: analysis.solution,
        verifyCommand,
        verifyLogTail: snipVerifyLog(lastVerifyLog),
        iteration,
      });
      await writeClusterArtifact(
        args.workDir,
        args.runId,
        args.cluster.id,
        "review.json",
        reviewResult,
      );
      if (reviewResult.decision === "request_changes") {
        feedbackLog = [
          "Reviewer request_changes:",
          ...reviewResult.reasons.map((r) => `- ${r}`),
        ].join("\n");
        if (!shouldContinueIterate(iteration, maxIterate, false)) {
          stopReason = {
            reasonCode: "review_failed",
            detail: buildKnownIssuesDetail({
              iterations: iteration,
              maxIterate,
              verifyCommand,
              logTail: feedbackLog,
              rootCauseSummary: analysis.rootCause.one_line_description,
              solutionSummary: analysis.solution.one_line_summary,
              actionsTaken: [
                "Verify was GREEN",
                `Reviewer rejected ${iteration} time(s)`,
                ...reviewResult.reasons,
              ],
            }),
          };
          break;
        }
        verifyOk = false;
        continue;
      }
    }

    break;
  }

  if (stopReason) {
    return unfixedBase(
      args.cluster,
      stopReason.reasonCode,
      stopReason.detail,
      analysis.rootCause.one_line_description,
      analysis.solution.one_line_summary,
    );
  }

  if (!verifyOk || lastStaticFail) {
    return unfixedBase(
      args.cluster,
      lastStaticFail ? "static_check_failed" : "verify_failed",
      buildKnownIssuesDetail({
        iterations: iteration,
        maxIterate,
        verifyCommand,
        logTail: lastVerifyLog || feedbackLog,
        rootCauseSummary: analysis.rootCause.one_line_description,
        solutionSummary: analysis.solution.one_line_summary,
      }),
      analysis.rootCause.one_line_description,
      analysis.solution.one_line_summary,
    );
  }

  if (!token) {
    return unfixedBase(
      args.cluster,
      "push_failed",
      "GITLAB_TOKEN not set; local verify GREEN but cannot open MR.",
      analysis.rootCause.one_line_description,
      analysis.solution.one_line_summary,
    );
  }

  try {
    const deliver = h.deliverFix ?? deliverFix;
    const delivered = await deliver({
      repoPath,
      runId: args.runId,
      clusterId: args.cluster.id,
      title: `fix: ${args.cluster.primaryTitle}`.slice(0, 200),
      description: [
        analysis.rootCause.one_line_description,
        "",
        analysis.solution.one_line_summary,
        "",
        `Verify: \`${verifyCommand}\``,
      ].join("\n"),
      gitlabHost: host,
      token,
      repoUrl: args.cluster.repoUrl,
      targetBranch: args.cluster.branch,
      projectId: args.options?.gitlabProjectId,
    });

    return {
      fixed: {
        clusterId: args.cluster.id,
        defectIds: args.cluster.defectIds,
        mrUrl: delivered.mrUrl,
        rootCauseSummary: analysis.rootCause.one_line_description,
        verify: { command: verifyCommand, ok: true, logTail: lastVerifyLog },
      },
    };
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return unfixedBase(
      args.cluster,
      "push_failed",
      message,
      analysis.rootCause.one_line_description,
      analysis.solution.one_line_summary,
    );
  }
}

export async function runPipeline(
  workDir: string,
  runId: string,
  options: RunnerOptions = {},
): Promise<RunReport> {
  const loaded = await loadRequest(workDir, runId);
  const engine = options.engine ?? loaded.options?.engine ?? "pipeline";
  if (engine === "langgraph") {
    const { invokeBugfixGraph } = await import("../graph/run-graph.js");
    return invokeBugfixGraph(
      {
        workDir,
        runId,
        defects: loaded.defects,
        userPrompt: loaded.userPrompt,
        options: loaded.options,
      },
      {
        handlers: options.handlers,
        maxIterate: options.maxIterate,
        gitlabToken: options.gitlabToken,
        gitlabHost: options.gitlabHost,
      },
    );
  }

  await updateRunMeta(workDir, runId, {
    status: "running",
    progress: { phase: "normalize", message: "Normalizing defects" },
  });

  const defects = normalizeDefects(loaded.defects);
  await updateRunMeta(workDir, runId, {
    progress: { phase: "aggregate", message: "Aggregating clusters" },
  });
  const clusters = aggregateDefects(defects);
  await writeClustersPlan(workDir, runId, clusters);

  const fixed: FixedCluster[] = [];
  const unfixed: UnfixedCluster[] = [];

  for (let i = 0; i < clusters.length; i++) {
    const cluster = clusters[i]!;
    await updateRunMeta(workDir, runId, {
      progress: {
        phase: "cluster",
        currentClusterId: cluster.id,
        completedClusters: i,
        totalClusters: clusters.length,
        message: `Processing ${cluster.id}`,
      },
    });

    const outcome = await processCluster({
      workDir,
      runId,
      cluster,
      defects,
      userPrompt: loaded.userPrompt,
      options: loaded.options,
      runner: options,
    });
    if (outcome.fixed) fixed.push(outcome.fixed);
    if (outcome.unfixed) unfixed.push(outcome.unfixed);
  }

  const report = buildReport(runId, fixed, unfixed);
  await writeReport(workDir, runId, report);
  await updateRunMeta(workDir, runId, {
    status: "completed",
    progress: {
      phase: "done",
      completedClusters: clusters.length,
      totalClusters: clusters.length,
    },
  });
  return report;
}

export type { RootCauseArtifact, SolutionArtifact };
