import { END, START, StateGraph } from "@langchain/langgraph";
import { defaultSkillsDir } from "../agent/sdk-runner.js";
import { loadConfig } from "../config.js";
import {
  ANALYZE_WRITE_DENY,
  McpPolicyError,
  assertStdioAllowlist,
  defaultDeniedToolsForAnalyze,
  mergeMcpConfig,
  normalizeMcpInput,
} from "../mcp/load-config.js";
import { isNewFailure } from "../pipeline/baseline.js";
import { currentClusterMeta } from "../pipeline/cluster-meta.js";
import { detectProfile } from "../profiles/detect.js";
import { analyzeCluster } from "../pipeline/analyze.js";
import {
  NoChangesError,
  buildMrDescription,
  deliverFix,
} from "../pipeline/deliver.js";
import { implementCluster, shouldContinueIterate } from "../pipeline/implement.js";
import { buildKnownIssuesDetail } from "../pipeline/known-issues.js";
import { snipVerifyLog } from "../pipeline/log-snip.js";
import { prepareRepo } from "../pipeline/prepare.js";
import { reviewCluster } from "../pipeline/review.js";
import { checkScopeLock } from "../pipeline/scope-lock.js";
import { resolveStaticCheckPlan, runStaticCheck } from "../pipeline/static-check.js";
import {
  classifyVerifyFailure,
  reasonCodeForClassify,
} from "../pipeline/verify-classify.js";
import { resolveVerifyPlan, runVerify } from "../pipeline/verify.js";
import { writeClusterArtifact } from "../runs/store.js";
import type { ClusterHandlers } from "../runs/runner.js";
import {
  filterSkills,
  filterSkillsForProfile,
  listBuiltinSkills,
  mountSkillsIntoCwd,
} from "../skills/manifest.js";
import type { ReasonCode } from "../types.js";
import { getDiffText } from "../workspace/diff.js";
import { ensureRepo } from "../workspace/git.js";
import {
  ClusterStateAnnotation,
  type ClusterState,
  type ClusterUpdate,
} from "./state.js";

export interface BugfixGraphOptions {
  /** Override individual pipeline steps (tests / custom integrations). */
  handlers?: ClusterHandlers;
  maxIterate?: number;
  gitlabToken?: string;
  gitlabHost?: string;
}

function resolveMaxIterate(state: ClusterState, opts: BugfixGraphOptions): number {
  return opts.maxIterate ?? state.options?.maxIterate ?? loadConfig().maxIterate;
}

function unfixed(
  state: ClusterState,
  reasonCode: ReasonCode,
  reasonDetail: string,
  withArtifacts = true,
): ClusterUpdate {
  const rootCause = withArtifacts ? state.rootCause?.one_line_description : undefined;
  const solution = withArtifacts ? state.solution?.one_line_summary : undefined;
  return {
    outcome: {
      unfixed: {
        clusterId: state.cluster.id,
        defectIds: state.cluster.defectIds,
        reasonCode,
        reasonDetail,
        artifacts: rootCause || solution ? { rootCause, solution } : undefined,
        ...liveFields(),
      },
    },
  };
}

function liveFields() {
  const m = currentClusterMeta();
  if (!m) return {};
  return {
    baseSha: m.baseSha,
    branch: m.branch,
    profileId: m.profileId,
    iterations: m.iterations,
    durationMs: Date.now() - m.started,
    skillsInvoked: m.skillsInvoked,
    mcpToolsInvoked: m.mcpToolsInvoked,
    verifyLevel: m.verifyLevel,
    baselineRed: m.baselineRed,
  };
}

function knownIssues(
  state: ClusterState,
  maxIterate: number,
  verifyCommand: string,
  logTail: string,
  actionsTaken?: string[],
): string {
  return buildKnownIssuesDetail({
    iterations: state.iteration,
    maxIterate,
    verifyCommand,
    logTail,
    rootCauseSummary: state.rootCause?.one_line_description,
    solutionSummary: state.solution?.one_line_summary,
    actionsTaken,
  });
}

const doneOr =
  <T extends string>(next: T | ((s: ClusterState) => T)) =>
  (s: ClusterState): T | typeof END => {
    if (s.outcome) return END;
    return typeof next === "function" ? next(s) : next;
  };

/**
 * Builds the per-cluster subgraph. Mirrors the legacy `processCluster` loop:
 * implement → static_check → verify → (classify | review) → implement … → deliver.
 */
export function createClusterGraph(opts: BugfixGraphOptions = {}) {
  const h = opts.handlers ?? {};

  const artifact = (s: ClusterState, name: string, data: unknown) =>
    writeClusterArtifact(s.workDir, s.runId, s.cluster.id, name, data);

  const ensureRepoNode = async (s: ClusterState): Promise<ClusterUpdate> => {
    try {
      const ensured = await (h.ensureRepo ?? ensureRepo)({
        workDir: s.workDir,
        runId: s.runId,
        clusterId: s.cluster.id,
        repoUrl: s.cluster.repoUrl,
        branch: s.cluster.branch,
        token: opts.gitlabToken ?? loadConfig().gitlabToken,
      });
      const skillsDir = defaultSkillsDir();
      const profileGuess = await detectProfile(ensured.repoPath).catch(() => "unknown" as const);
      const skillMetas = filterSkillsForProfile(
        filterSkills(await listBuiltinSkills(skillsDir), s.options?.skills),
        profileGuess,
      );
      await mountSkillsIntoCwd(ensured.repoPath, skillMetas).catch(() => undefined);
      const meta = currentClusterMeta();
      if (meta) {
        meta.baseSha = ensured.baseSha ?? ensured.headSha;
        meta.branch = s.cluster.branch;
        meta.profileId = profileGuess;
        meta.skillsInvoked = skillMetas.map((x) => x.id);
      }
      return {
        repoPath: ensured.repoPath,
        baseSha: ensured.baseSha ?? ensured.headSha,
      };
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      return unfixed(s, "prepare_failed", `Failed to ensure repo: ${message}`, false);
    }
  };

  const analyzeNode = async (s: ClusterState): Promise<ClusterUpdate> => {
    const mcpNorm = normalizeMcpInput(s.options?.mcp);
    if (mcpNorm.enabled && mcpNorm.mode === "required") {
      try {
        assertStdioAllowlist(mcpNorm.servers);
      } catch (err) {
        if (err instanceof McpPolicyError) return unfixed(s, "prepare_failed", err.message, false);
        throw err;
      }
    }
    const meta = currentClusterMeta();
    if (meta) meta.mcpToolsInvoked = mcpNorm.allowedTools;
    const mcpServers = mcpNorm.enabled
      ? await mergeMcpConfig({ workDir: s.workDir, runMcp: mcpNorm.servers })
      : {};
    const skillsDir = defaultSkillsDir();
    const skillIds = filterSkillsForProfile(
      filterSkills(await listBuiltinSkills(skillsDir), s.options?.skills),
      meta?.profileId ?? "unknown",
    ).map((x) => x.id);
    const analysis = await (h.analyzeCluster ?? analyzeCluster)({
      cluster: s.cluster,
      defects: s.defects,
      repoPath: s.repoPath!,
      userPrompt: s.userPrompt,
      mcpServers,
      skillsDir,
      skillIds,
      disallowedTools: [
        ...new Set([
          ...mcpNorm.deniedTools,
          ...ANALYZE_WRITE_DENY,
          ...defaultDeniedToolsForAnalyze(mcpNorm.allowedTools),
        ]),
      ],
    });
    if (analysis.agentTranscript) {
      await artifact(s, "analyze-transcript.json", { text: analysis.agentTranscript });
    }
    if (analysis.rootCause) await artifact(s, "root-cause.json", analysis.rootCause);
    if (analysis.solution) await artifact(s, "solution.json", analysis.solution);
    if (analysis.localization) {
      await artifact(s, "localization.json", analysis.localization);
      if (analysis.solution && !analysis.solution.target_files?.length) {
        analysis.solution.target_files = analysis.localization.editTargets;
      }
    }

    const update: ClusterUpdate = {
      rootCause: analysis.rootCause,
      solution: analysis.solution,
    };
    if (analysis.status === "unfixed") {
      return {
        ...update,
        ...unfixed(
          { ...s, rootCause: analysis.rootCause, solution: analysis.solution },
          analysis.reasonCode,
          analysis.reasonDetail,
        ),
      };
    }
    return update;
  };

  const prepareNode = async (s: ClusterState): Promise<ClusterUpdate> => {
    const plan = await (h.resolveVerifyPlan ?? resolveVerifyPlan)({
      repoPath: s.repoPath!,
      userPrompt: s.userPrompt,
      overrides: s.options?.verifyOverrides,
    });
    const meta = currentClusterMeta();
    if (meta) meta.profileId = plan.profileId;
    if (!plan.test.length) {
      return unfixed(
        s,
        "no_test_command",
        "No verify/test command detected; refusing to open MR without GREEN gate.",
      );
    }
    const prepared = await (h.prepareRepo ?? prepareRepo)(s.repoPath!, plan);
    if (!prepared.ok) {
      return unfixed(s, "prepare_failed", `Install failed: ${prepared.logTail}`, false);
    }
    const staticPlan = await (h.resolveStaticCheckPlan ?? resolveStaticCheckPlan)(s.repoPath!);
    return { verifyPlan: plan, staticPlan, verifyCommand: plan.test.join(" && ") };
  };

  const baselineNode = async (s: ClusterState): Promise<ClusterUpdate> => {
    const staticResult = await (h.runStaticCheck ?? runStaticCheck)(s.repoPath!, s.staticPlan!);
    const verifyResult = await (h.runVerify ?? runVerify)(s.repoPath!, s.verifyPlan!);
    await artifact(s, "baseline.json", { static: staticResult, verify: verifyResult });
    const meta = currentClusterMeta();
    if (meta && (!staticResult.ok || !verifyResult.ok)) meta.baselineRed = true;
    if (!verifyResult.ok) {
      const baselineClass = (h.classifyVerifyFailure ?? classifyVerifyFailure)(
        verifyResult.logTail,
        verifyResult.command,
      );
      if (baselineClass.stopIterate) {
        return unfixed(
          s,
          reasonCodeForClassify(baselineClass.kind),
          `Baseline verify is not runnable (${baselineClass.kind}): ${baselineClass.reason}`,
        );
      }
    }
    return {
      baselineStatic: {
        ok: staticResult.ok,
        command: staticResult.command,
        logTail: staticResult.logTail,
      },
      baselineVerify: {
        ok: verifyResult.ok,
        command: verifyResult.command,
        logTail: verifyResult.logTail,
      },
    };
  };

  const reproduceNode = async (s: ClusterState): Promise<ClusterUpdate> => {
    try {
      await (h.implementCluster ?? implementCluster)({
        cluster: s.cluster,
        repoPath: s.repoPath!,
        rootCause: s.rootCause!,
        solution: s.solution!,
        baseSha: s.baseSha,
        iteration: 0,
        phase: "reproduce",
        skillsDir: defaultSkillsDir(),
      });
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      return unfixed(s, "implement_failed", `Reproduction step failed: ${message}`, false);
    }
    const repro = await (h.runVerify ?? runVerify)(s.repoPath!, s.verifyPlan!);
    const base = s.baselineVerify ?? { ok: true, command: repro.command, logTail: "" };
    const novel = isNewFailure(base, {
      ok: repro.ok,
      command: repro.command,
      logTail: repro.logTail,
    });
    if (!repro.ok && novel) {
      const reproClass = (h.classifyVerifyFailure ?? classifyVerifyFailure)(
        repro.logTail,
        repro.command,
      );
      if (reproClass.stopIterate) {
        return unfixed(
          s,
          reasonCodeForClassify(reproClass.kind),
          `Reproduction verify blocked (${reproClass.kind}): ${reproClass.reason}`,
        );
      }
      const meta = currentClusterMeta();
      if (meta) meta.verifyLevel = "reproduced";
    }
    return {};
  };

  const implementNode = async (s: ClusterState): Promise<ClusterUpdate> => {
    const iteration = s.iteration + 1;
    const meta = currentClusterMeta();
    if (meta) meta.iterations = iteration;
    try {
      const skillsDir = defaultSkillsDir();
      const skillIds = filterSkills(
        await listBuiltinSkills(skillsDir),
        s.options?.skills,
      ).map((x) => x.id);
      const impl = await (h.implementCluster ?? implementCluster)({
        cluster: s.cluster,
        repoPath: s.repoPath!,
        rootCause: s.rootCause!,
        solution: s.solution!,
        baseSha: s.baseSha,
        verifyLogTail: s.feedbackLog || undefined,
        iteration,
        skillsDir,
        skillIds,
      });
      const scope =
        impl.scopeOk === false
          ? { ok: false, violations: impl.scopeViolations }
          : checkScopeLock(impl.changedFiles ?? [], s.solution!);
      if (!scope.ok) {
        await artifact(s, "scope-lock.json", scope);
        return {
          iteration,
          ...unfixed(
            s,
            "implement_failed",
            `Scope lock violated — edits outside solution target_files: ${scope.violations.join(", ")}`,
          ),
        };
      }
      return { iteration };
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      return { iteration, ...unfixed(s, "implement_failed", message, false) };
    }
  };

  const staticCheckNode = async (s: ClusterState): Promise<ClusterUpdate> => {
    const result = await (h.runStaticCheck ?? runStaticCheck)(s.repoPath!, s.staticPlan!);
    await artifact(s, "static-check.json", result);
    const base = s.baselineStatic ?? { ok: true, command: result.command, logTail: "" };
    if (result.ok || !isNewFailure(base, result)) return { staticOk: true };

    const feedbackLog = snipVerifyLog(result.logTail);
    const maxIterate = resolveMaxIterate(s, opts);
    if (!shouldContinueIterate(s.iteration, maxIterate, false)) {
      return unfixed(
        s,
        "static_check_failed",
        knownIssues(s, maxIterate, result.command, result.logTail, [
          `Static check failed after ${s.iteration} iteration(s)`,
          `Command: ${result.command}`,
        ]),
      );
    }
    return { staticOk: false, feedbackLog };
  };

  const verifyNode = async (s: ClusterState): Promise<ClusterUpdate> => {
    const result = await (h.runVerify ?? runVerify)(s.repoPath!, s.verifyPlan!);
    await artifact(s, "verify.json", result);
    const base = s.baselineVerify ?? { ok: true, command: result.command, logTail: "" };
    const novel = isNewFailure(base, {
      ok: result.ok,
      command: result.command,
      logTail: result.logTail,
    });
    if (!result.ok && !novel) {
      const meta = currentClusterMeta();
      if (meta) meta.baselineRed = true;
    }
    return {
      verifyOk: result.ok || !novel,
      verifyCommand: result.command,
      lastVerifyLog: result.logTail,
    };
  };

  const classifyNode = async (s: ClusterState): Promise<ClusterUpdate> => {
    const classification = (h.classifyVerifyFailure ?? classifyVerifyFailure)(
      s.lastVerifyLog,
      s.verifyCommand,
    );
    await artifact(s, "verify-classify.json", classification);
    if (classification.stopIterate) {
      return unfixed(
        s,
        reasonCodeForClassify(classification.kind),
        [
          `Smart Routing: ${classification.kind}`,
          classification.reason,
          "",
          snipVerifyLog(s.lastVerifyLog),
        ].join("\n"),
      );
    }
    const maxIterate = resolveMaxIterate(s, opts);
    if (!shouldContinueIterate(s.iteration, maxIterate, false)) {
      return unfixed(
        s,
        "verify_failed",
        knownIssues(s, maxIterate, s.verifyCommand, s.lastVerifyLog, [
          `Analyzed cluster ${s.cluster.id}`,
          `Implement→static→verify ${s.iteration} time(s)`,
          `Last classify: ${classification.kind}`,
        ]),
      );
    }
    return { feedbackLog: snipVerifyLog(s.lastVerifyLog) };
  };

  const reviewNode = async (s: ClusterState): Promise<ClusterUpdate> => {
    let result;
    try {
      const diffText = s.baseSha
        ? await getDiffText(s.repoPath!, s.baseSha).catch(() => "")
        : "";
      const skillsDir = defaultSkillsDir();
      const skillIds = filterSkills(
        await listBuiltinSkills(skillsDir),
        s.options?.skills,
      ).map((x) => x.id);
      result = await (h.reviewCluster ?? reviewCluster)({
        repoPath: s.repoPath!,
        rootCause: s.rootCause!,
        solution: s.solution!,
        verifyCommand: s.verifyCommand,
        verifyLogTail: snipVerifyLog(s.lastVerifyLog),
        diffText,
        iteration: s.iteration,
        skillsDir,
        skillIds,
      });
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      return unfixed(s, "review_failed", `Reviewer failed (cluster-local): ${message}`);
    }
    await artifact(s, "review.json", result);
    if (result.decision !== "request_changes") return { reviewApproved: true };

    const feedbackLog = [
      "Reviewer request_changes:",
      ...result.reasons.map((r) => `- ${r}`),
    ].join("\n");
    const maxIterate = resolveMaxIterate(s, opts);
    if (!shouldContinueIterate(s.iteration, maxIterate, false)) {
      return unfixed(
        s,
        "review_failed",
        knownIssues(s, maxIterate, s.verifyCommand, feedbackLog, [
          "Verify was GREEN",
          `Reviewer rejected ${s.iteration} time(s)`,
          ...result.reasons,
        ]),
      );
    }
    return { reviewApproved: false, feedbackLog };
  };

  const deliverNode = async (s: ClusterState): Promise<ClusterUpdate> => {
    const cfg = loadConfig();
    const token = opts.gitlabToken ?? cfg.gitlabToken;
    if (!token) {
      return unfixed(
        s,
        "push_failed",
        "GITLAB_TOKEN not set; local verify GREEN but cannot open MR.",
      );
    }
    try {
      const delivered = await (h.deliverFix ?? deliverFix)({
        repoPath: s.repoPath!,
        runId: s.runId,
        clusterId: s.cluster.id,
        title: `fix: ${s.cluster.primaryTitle}`.slice(0, 200),
        description: buildMrDescription({
          rootCauseSummary: s.rootCause!.one_line_description,
          solutionSummary: s.solution!.one_line_summary,
          defectIds: s.cluster.defectIds,
          verifyCommand: s.verifyCommand,
          verifyLogTail: s.lastVerifyLog,
          reproductionSteps: s.rootCause!.reproduction_steps,
        }),
        gitlabHost: opts.gitlabHost ?? cfg.gitlabHost,
        token,
        repoUrl: s.cluster.repoUrl,
        targetBranch: s.cluster.branch,
        projectId: s.options?.gitlabProjectId,
        baseSha: s.baseSha,
        draftMr: s.options?.draftMr ?? currentClusterMeta()?.verifyLevel === "regression_only",
        defectIds: s.cluster.defectIds,
      });
      return {
        outcome: {
          fixed: {
            clusterId: s.cluster.id,
            defectIds: s.cluster.defectIds,
            mrUrl: delivered.mrUrl,
            rootCauseSummary: s.rootCause!.one_line_description,
            verify: { command: s.verifyCommand, ok: true, logTail: s.lastVerifyLog, exitCode: 0 },
            ...liveFields(),
          },
        },
      };
    } catch (err) {
      if (err instanceof NoChangesError) {
        return unfixed(s, "no_changes", err.message);
      }
      const message = err instanceof Error ? err.message : String(err);
      return unfixed(s, "push_failed", message);
    }
  };

  return new StateGraph(ClusterStateAnnotation)
    .addNode("ensure_repo", ensureRepoNode)
    .addNode("analyze", analyzeNode)
    .addNode("prepare", prepareNode)
    .addNode("baseline", baselineNode)
    .addNode("reproduce", reproduceNode)
    .addNode("implement", implementNode)
    .addNode("static_check", staticCheckNode)
    .addNode("verify", verifyNode)
    .addNode("classify", classifyNode)
    .addNode("review", reviewNode)
    .addNode("deliver", deliverNode)
    .addEdge(START, "ensure_repo")
    .addConditionalEdges("ensure_repo", doneOr("analyze"), ["analyze", END])
    .addConditionalEdges("analyze", doneOr("prepare"), ["prepare", END])
    .addConditionalEdges("prepare", doneOr("baseline"), ["baseline", END])
    .addConditionalEdges("baseline", doneOr("reproduce"), ["reproduce", END])
    .addConditionalEdges("reproduce", doneOr("implement"), ["implement", END])
    .addConditionalEdges("implement", doneOr("static_check"), ["static_check", END])
    .addConditionalEdges(
      "static_check",
      doneOr((s) => (s.staticOk ? "verify" : "implement")),
      ["verify", "implement", END],
    )
    .addConditionalEdges(
      "verify",
      doneOr((s) => {
        if (!s.verifyOk) return "classify";
        return s.options?.skipReviewer === true ? "deliver" : "review";
      }),
      ["classify", "review", "deliver", END],
    )
    .addConditionalEdges("classify", doneOr("implement"), ["implement", END])
    .addConditionalEdges(
      "review",
      doneOr((s) => (s.reviewApproved ? "deliver" : "implement")),
      ["deliver", "implement", END],
    )
    .addEdge("deliver", END)
    .compile();
}
