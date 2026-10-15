import path from "node:path";
import { loadConfig } from "../config.js";
import type { RootCauseArtifact, SolutionArtifact } from "../agent/artifacts.js";
import { analyzeCluster } from "../pipeline/analyze.js";
import { aggregateDefects } from "../pipeline/aggregate.js";
import { deliverFix } from "../pipeline/deliver.js";
import { implementCluster, shouldContinueIterate } from "../pipeline/implement.js";
import { buildKnownIssuesDetail } from "../pipeline/known-issues.js";
import { normalizeDefects } from "../pipeline/normalize.js";
import { prepareRepo } from "../pipeline/prepare.js";
import { buildReport } from "../pipeline/report.js";
import { checkScopeLock } from "../pipeline/scope-lock.js";
import { resolveVerifyPlan, runVerify } from "../pipeline/verify.js";
import type {
  Cluster,
  CreateRunRequest,
  Defect,
  FixedCluster,
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
}

export interface RunnerOptions {
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
    return {
      unfixed: {
        clusterId: args.cluster.id,
        defectIds: args.cluster.defectIds,
        reasonCode: "prepare_failed",
        reasonDetail: `Failed to ensure repo: ${message}`,
      },
    };
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
    return {
      unfixed: {
        clusterId: args.cluster.id,
        defectIds: args.cluster.defectIds,
        reasonCode: analysis.reasonCode,
        reasonDetail: analysis.reasonDetail,
        artifacts: {
          rootCause: analysis.rootCause?.one_line_description,
          solution: analysis.solution?.one_line_summary,
        },
      },
    };
  }

  const resolvePlan = h.resolveVerifyPlan ?? resolveVerifyPlan;
  const plan = await resolvePlan({
    repoPath,
    userPrompt: args.userPrompt,
    overrides: args.options?.verifyOverrides,
  });

  if (!plan.test.length) {
    return {
      unfixed: {
        clusterId: args.cluster.id,
        defectIds: args.cluster.defectIds,
        reasonCode: "no_test_command",
        reasonDetail: "No verify/test command detected; refusing to open MR without GREEN gate.",
        artifacts: {
          rootCause: analysis.rootCause.one_line_description,
          solution: analysis.solution.one_line_summary,
        },
      },
    };
  }

  const prepare = h.prepareRepo ?? prepareRepo;
  const prepared = await prepare(repoPath, plan);
  if (!prepared.ok) {
    return {
      unfixed: {
        clusterId: args.cluster.id,
        defectIds: args.cluster.defectIds,
        reasonCode: "prepare_failed",
        reasonDetail: `Install failed: ${prepared.logTail}`,
      },
    };
  }

  const implement = h.implementCluster ?? implementCluster;
  const verify = h.runVerify ?? runVerify;
  let lastLog = "";
  let verifyOk = false;
  let verifyCommand = plan.test.join(" && ");
  let iteration = 0;

  while (true) {
    iteration += 1;
    try {
      const impl = await implement({
        cluster: args.cluster,
        repoPath,
        rootCause: analysis.rootCause,
        solution: analysis.solution,
        verifyLogTail: lastLog || undefined,
        iteration,
      });
      const scope =
        impl.scopeOk === false
          ? { ok: false, violations: impl.scopeViolations }
          : checkScopeLock(impl.changedFiles ?? [], analysis.solution);
      if (!scope.ok) {
        await writeClusterArtifact(args.workDir, args.runId, args.cluster.id, "scope-lock.json", scope);
        return {
          unfixed: {
            clusterId: args.cluster.id,
            defectIds: args.cluster.defectIds,
            reasonCode: "implement_failed",
            reasonDetail: `Scope lock violated — edits outside solution target_files: ${scope.violations.join(", ")}`,
            artifacts: {
              rootCause: analysis.rootCause.one_line_description,
              solution: analysis.solution.one_line_summary,
            },
          },
        };
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      return {
        unfixed: {
          clusterId: args.cluster.id,
          defectIds: args.cluster.defectIds,
          reasonCode: "implement_failed",
          reasonDetail: message,
        },
      };
    }

    const result = await verify(repoPath, plan);
    verifyCommand = result.command;
    lastLog = result.logTail;
    await writeClusterArtifact(args.workDir, args.runId, args.cluster.id, "verify.json", result);
    verifyOk = result.ok;
    if (!shouldContinueIterate(iteration, maxIterate, verifyOk)) break;
  }

  if (!verifyOk) {
    return {
      unfixed: {
        clusterId: args.cluster.id,
        defectIds: args.cluster.defectIds,
        reasonCode: "verify_failed",
        reasonDetail: buildKnownIssuesDetail({
          iterations: iteration,
          maxIterate,
          verifyCommand,
          logTail: lastLog,
          rootCauseSummary: analysis.rootCause.one_line_description,
          solutionSummary: analysis.solution.one_line_summary,
          actionsTaken: [
            `Analyzed cluster ${args.cluster.id} (failure_mode=${analysis.rootCause.failure_mode ?? "unspecified"})`,
            `Implemented solution under scope lock (${iteration} attempt(s))`,
            `Verify remained red after budget ${maxIterate}`,
          ],
        }),
        artifacts: {
          rootCause: analysis.rootCause.one_line_description,
          solution: analysis.solution.one_line_summary,
        },
      },
    };
  }

  if (!token) {
    return {
      unfixed: {
        clusterId: args.cluster.id,
        defectIds: args.cluster.defectIds,
        reasonCode: "push_failed",
        reasonDetail: "GITLAB_TOKEN not set; local verify GREEN but cannot open MR.",
        artifacts: {
          rootCause: analysis.rootCause.one_line_description,
          solution: analysis.solution.one_line_summary,
        },
      },
    };
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
        verify: { command: verifyCommand, ok: true, logTail: lastLog },
      },
    };
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return {
      unfixed: {
        clusterId: args.cluster.id,
        defectIds: args.cluster.defectIds,
        reasonCode: "push_failed",
        reasonDetail: message,
        artifacts: {
          rootCause: analysis.rootCause.one_line_description,
          solution: analysis.solution.one_line_summary,
        },
      },
    };
  }
}

export async function runPipeline(
  workDir: string,
  runId: string,
  options: RunnerOptions = {},
): Promise<RunReport> {
  await updateRunMeta(workDir, runId, {
    status: "running",
    progress: { phase: "normalize", message: "Normalizing defects" },
  });

  const loaded = await loadRequest(workDir, runId);
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
