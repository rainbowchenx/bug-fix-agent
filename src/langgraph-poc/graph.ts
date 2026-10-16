/**
 * LangGraph POC - BugFix Agent State Graph实现
 * 
 * 这是概念验证代码，展示如何将现有pipeline改造为LangGraph
 */

import { StateGraph, END, START, Annotation } from "@langchain/langgraph";
import type {
  Cluster,
  Defect,
  FixedCluster,
  UnfixedCluster,
  ReasonCode,
  CreateRunOptions,
  RunReport,
} from "../types.js";
import type { RootCauseArtifact, SolutionArtifact } from "../agent/artifacts.js";

/**
 * LangGraph状态定义
 * 使用Annotation API定义状态schema和reducer
 */
const BugfixStateAnnotation = Annotation.Root({
  // 输入参数
  runId: Annotation<string>(),
  workDir: Annotation<string>(),
  defects: Annotation<Defect[]>(),
  userPrompt: Annotation<string | undefined>(),
  options: Annotation<CreateRunOptions | undefined>(),

  // 处理状态
  clusters: Annotation<Cluster[]>(),
  currentClusterIndex: Annotation<number>({
    reducer: (left, right) => right ?? left ?? 0,
    default: () => 0,
  }),
  currentCluster: Annotation<Cluster | undefined>(),

  // Repo信息
  repoPath: Annotation<string | undefined>(),
  skillsDir: Annotation<string | undefined>(),

  // Analyze产物
  rootCause: Annotation<RootCauseArtifact | undefined>(),
  solution: Annotation<SolutionArtifact | undefined>(),

  // Implement迭代状态
  iteration: Annotation<number>({
    reducer: (left, right) => right ?? left ?? 0,
    default: () => 0,
  }),
  feedbackLog: Annotation<string>({
    default: () => "",
  }),
  lastVerifyLog: Annotation<string>({
    default: () => "",
  }),
  verifyOk: Annotation<boolean>({
    default: () => false,
  }),
  lastStaticOk: Annotation<boolean>({
    default: () => true,
  }),

  // 累积结果（使用append reducer）
  fixed: Annotation<FixedCluster[]>({
    reducer: (left, right) => {
      if (!right) return left ?? [];
      return [...(left ?? []), ...right];
    },
    default: () => [],
  }),
  unfixed: Annotation<UnfixedCluster[]>({
    reducer: (left, right) => {
      if (!right) return left ?? [];
      return [...(left ?? []), ...right];
    },
    default: () => [],
  }),

  // 控制流
  stopReason: Annotation<{ reasonCode: ReasonCode; detail: string } | undefined>(),

  // 最终报告
  report: Annotation<RunReport | undefined>(),
});

export type BugfixAgentState = typeof BugfixStateAnnotation.State;

/**
 * 创建BugFix Agent的LangGraph
 */
export function createBugfixGraph() {
  const workflow = new StateGraph(BugfixStateAnnotation);

  // ==================== 节点定义 ====================

  /**
   * 1. Normalize: 标准化defects
   */
  const normalizeNode = async (state: BugfixAgentState) => {
    // 导入实际的normalize函数
    const { normalizeDefects } = await import("../pipeline/normalize.js");
    const normalized = normalizeDefects(state.defects);
    return { defects: normalized };
  };

  /**
   * 2. Aggregate: 聚类defects
   */
  const aggregateNode = async (state: BugfixAgentState) => {
    const { aggregateDefects } = await import("../pipeline/aggregate.js");
    const clusters = aggregateDefects(state.defects);
    return { clusters };
  };

  /**
   * 3. Prepare Cluster: 准备当前要处理的cluster
   */
  const prepareClusterNode = (state: BugfixAgentState) => {
    const cluster = state.clusters[state.currentClusterIndex];
    if (!cluster) {
      // 所有cluster处理完毕
      return { currentCluster: undefined };
    }
    // 重置cluster状态
    return {
      currentCluster: cluster,
      iteration: 0,
      feedbackLog: "",
      lastVerifyLog: "",
      verifyOk: false,
      lastStaticOk: true,
      stopReason: undefined,
      rootCause: undefined,
      solution: undefined,
    };
  };

  /**
   * 4. Ensure Repo: 确保repo已clone并checkout
   */
  const ensureRepoNode = async (state: BugfixAgentState) => {
    const { ensureRepo } = await import("../workspace/git.js");
    const { loadConfig } = await import("../config.js");
    const cfg = loadConfig();

    try {
      const result = await ensureRepo({
        workDir: state.workDir,
        repoUrl: state.currentCluster!.repoUrl,
        branch: state.currentCluster!.branch,
        token: cfg.gitlabToken,
      });
      return { repoPath: result.repoPath };
    } catch (err) {
      return {
        stopReason: {
          reasonCode: "prepare_failed" as ReasonCode,
          detail: `Failed to ensure repo: ${err instanceof Error ? err.message : String(err)}`,
        },
      };
    }
  };

  /**
   * 5. Analyze: 分析cluster，产出RootCause和Solution
   */
  const analyzeNode = async (state: BugfixAgentState) => {
    const { analyzeCluster } = await import("../pipeline/analyze.js");
    const { defaultSkillsDir } = await import("../agent/sdk-runner.js");

    const clusterDefects = state.defects.filter((d) =>
      state.currentCluster!.defectIds.includes(d.id),
    );

    try {
      const result = await analyzeCluster({
        cluster: state.currentCluster!,
        defects: clusterDefects,
        repoPath: state.repoPath!,
        userPrompt: state.userPrompt,
        mcpServers: state.options?.mcp,
        skillsDir: defaultSkillsDir(),
      });

      if (result.status === "unfixed") {
        return {
          stopReason: {
            reasonCode: result.reasonCode,
            detail: result.reasonDetail,
          },
          rootCause: result.rootCause,
          solution: result.solution,
        };
      }

      return {
        rootCause: result.rootCause,
        solution: result.solution,
      };
    } catch (err) {
      return {
        stopReason: {
          reasonCode: "analyze_failed" as ReasonCode,
          detail: `Analyze failed: ${err instanceof Error ? err.message : String(err)}`,
        },
      };
    }
  };

  /**
   * 6. Prepare Repo: 安装依赖等
   */
  const prepareRepoNode = async (state: BugfixAgentState) => {
    const { prepareRepo } = await import("../pipeline/prepare.js");
    const { resolveVerifyPlan } = await import("../pipeline/verify.js");

    const plan = await resolveVerifyPlan({
      repoPath: state.repoPath!,
      userPrompt: state.userPrompt,
      overrides: state.options?.verifyOverrides,
    });

    if (!plan.test.length) {
      return {
        stopReason: {
          reasonCode: "no_test_command" as ReasonCode,
          detail: "No verify/test command detected",
        },
      };
    }

    const prepared = await prepareRepo(state.repoPath!, plan);
    if (!prepared.ok) {
      return {
        stopReason: {
          reasonCode: "prepare_failed" as ReasonCode,
          detail: `Install failed: ${prepared.logTail}`,
        },
      };
    }

    return {};
  };

  /**
   * 7. Implement: 实现修复
   */
  const implementNode = async (state: BugfixAgentState) => {
    const { implementCluster } = await import("../pipeline/implement.js");

    const result = await implementCluster({
      cluster: state.currentCluster!,
      repoPath: state.repoPath!,
      rootCause: state.rootCause!,
      solution: state.solution!,
      verifyLogTail: state.feedbackLog || undefined,
      iteration: state.iteration + 1,
    });

    return {
      iteration: state.iteration + 1,
      // 注：实际的scope check会在这里或下一步进行
    };
  };

  /**
   * 8. Static Check: 运行静态检查（typecheck/lint）
   */
  const staticCheckNode = async (state: BugfixAgentState) => {
    const { resolveStaticCheckPlan, runStaticCheck } = await import("../pipeline/static-check.js");
    const { snipVerifyLog } = await import("../pipeline/log-snip.js");

    const plan = await resolveStaticCheckPlan(state.repoPath!);
    const result = await runStaticCheck(state.repoPath!, plan);

    if (!result.ok) {
      return {
        lastStaticOk: false,
        feedbackLog: snipVerifyLog(result.logTail),
      };
    }

    return { lastStaticOk: true };
  };

  /**
   * 9. Verify: 运行测试验证
   */
  const verifyNode = async (state: BugfixAgentState) => {
    const { resolveVerifyPlan, runVerify } = await import("../pipeline/verify.js");

    const plan = await resolveVerifyPlan({
      repoPath: state.repoPath!,
      userPrompt: state.userPrompt,
      overrides: state.options?.verifyOverrides,
    });

    const result = await runVerify(state.repoPath!, plan);

    return {
      verifyOk: result.ok,
      lastVerifyLog: result.logTail,
    };
  };

  /**
   * 10. Classify: 分类verify失败原因，决定是否继续迭代
   */
  const classifyNode = async (state: BugfixAgentState) => {
    const { classifyVerifyFailure } = await import("../pipeline/verify-classify.js");
    const { snipVerifyLog } = await import("../pipeline/log-snip.js");

    const classification = classifyVerifyFailure(state.lastVerifyLog, "test");

    if (classification.stopIterate) {
      return {
        stopReason: {
          reasonCode: "env_verify_failed" as ReasonCode, // 或其他reasonCode
          detail: `Smart Routing: ${classification.kind}\n${classification.reason}`,
        },
      };
    }

    return {
      feedbackLog: snipVerifyLog(state.lastVerifyLog),
    };
  };

  /**
   * 11. Review: 只读审查
   */
  const reviewNode = async (state: BugfixAgentState) => {
    const { reviewCluster } = await import("../pipeline/review.js");
    const { snipVerifyLog } = await import("../pipeline/log-snip.js");

    const result = await reviewCluster({
      repoPath: state.repoPath!,
      rootCause: state.rootCause!,
      solution: state.solution!,
      verifyCommand: "test", // 从state获取
      verifyLogTail: snipVerifyLog(state.lastVerifyLog),
      iteration: state.iteration,
    });

    if (result.decision === "request_changes") {
      const feedback = ["Reviewer request_changes:", ...result.reasons.map((r) => `- ${r}`)].join(
        "\n",
      );

      return {
        feedbackLog: feedback,
        verifyOk: false, // 强制重新实现
      };
    }

    return {};
  };

  /**
   * 12. Deliver: 推送到GitLab并创建MR
   */
  const deliverNode = async (state: BugfixAgentState) => {
    const { deliverFix } = await import("../pipeline/deliver.js");
    const { loadConfig } = await import("../config.js");
    const cfg = loadConfig();

    try {
      const delivered = await deliverFix({
        repoPath: state.repoPath!,
        runId: state.runId,
        clusterId: state.currentCluster!.id,
        title: `fix: ${state.currentCluster!.primaryTitle}`.slice(0, 200),
        description: [
          state.rootCause!.one_line_description,
          "",
          state.solution!.one_line_summary,
        ].join("\n"),
        gitlabHost: cfg.gitlabHost,
        token: cfg.gitlabToken!,
        repoUrl: state.currentCluster!.repoUrl,
        targetBranch: state.currentCluster!.branch,
        projectId: state.options?.gitlabProjectId,
      });

      // 添加到fixed列表
      const fixedCluster: FixedCluster = {
        clusterId: state.currentCluster!.id,
        defectIds: state.currentCluster!.defectIds,
        mrUrl: delivered.mrUrl,
        rootCauseSummary: state.rootCause!.one_line_description,
        verify: {
          command: "test",
          ok: true,
          logTail: state.lastVerifyLog,
        },
      };

      return {
        fixed: [fixedCluster],
      };
    } catch (err) {
      return {
        stopReason: {
          reasonCode: "push_failed" as ReasonCode,
          detail: `Deliver failed: ${err instanceof Error ? err.message : String(err)}`,
        },
      };
    }
  };

  /**
   * 13. Add Unfixed: 将当前cluster标记为unfixed
   */
  const addUnfixedNode = (state: BugfixAgentState) => {
    const unfixedCluster: UnfixedCluster = {
      clusterId: state.currentCluster!.id,
      defectIds: state.currentCluster!.defectIds,
      reasonCode: state.stopReason!.reasonCode,
      reasonDetail: state.stopReason!.detail,
      artifacts:
        state.rootCause || state.solution
          ? {
              rootCause: state.rootCause?.one_line_description,
              solution: state.solution?.one_line_summary,
            }
          : undefined,
    };

    return {
      unfixed: [unfixedCluster],
    };
  };

  /**
   * 14. Next Cluster: 移到下一个cluster
   */
  const nextClusterNode = (state: BugfixAgentState) => {
    return {
      currentClusterIndex: state.currentClusterIndex + 1,
    };
  };

  /**
   * 15. Build Report: 构建最终报告
   */
  const buildReportNode = async (state: BugfixAgentState) => {
    const { buildReport } = await import("../pipeline/report.js");
    const report = buildReport(state.runId, state.fixed, state.unfixed);
    return { report };
  };

  // ==================== 添加所有节点 ====================

  workflow.addNode("normalize", normalizeNode);
  workflow.addNode("aggregate", aggregateNode);
  workflow.addNode("prepare_cluster", prepareClusterNode);
  workflow.addNode("ensure_repo", ensureRepoNode);
  workflow.addNode("analyze", analyzeNode);
  workflow.addNode("prepare_repo", prepareRepoNode);
  workflow.addNode("implement", implementNode);
  workflow.addNode("static_check", staticCheckNode);
  workflow.addNode("verify", verifyNode);
  workflow.addNode("classify", classifyNode);
  workflow.addNode("review", reviewNode);
  workflow.addNode("deliver", deliverNode);
  workflow.addNode("add_unfixed", addUnfixedNode);
  workflow.addNode("next_cluster", nextClusterNode);
  workflow.addNode("build_report", buildReportNode);

  // ==================== 添加边 ====================

  // 线性流程：normalize → aggregate → prepare_cluster
  workflow.addEdge(START, "normalize");
  workflow.addEdge("normalize", "aggregate");
  workflow.addEdge("aggregate", "prepare_cluster");

  // Conditional: prepare_cluster后检查是否还有cluster
  workflow.addConditionalEdges(
    "prepare_cluster",
    (state) => {
      if (!state.currentCluster) {
        return "build_report";
      }
      return "ensure_repo";
    },
    {
      ensure_repo: "ensure_repo",
      build_report: "build_report",
    },
  );

  // Conditional: ensure_repo后检查是否成功
  workflow.addConditionalEdges(
    "ensure_repo",
    (state) => {
      if (state.stopReason) return "add_unfixed";
      return "analyze";
    },
    {
      analyze: "analyze",
      add_unfixed: "add_unfixed",
    },
  );

  // Conditional: analyze后检查fixability
  workflow.addConditionalEdges(
    "analyze",
    (state) => {
      if (state.stopReason || !state.solution) return "add_unfixed";
      return "prepare_repo";
    },
    {
      prepare_repo: "prepare_repo",
      add_unfixed: "add_unfixed",
    },
  );

  // Conditional: prepare_repo后检查是否成功
  workflow.addConditionalEdges(
    "prepare_repo",
    (state) => {
      if (state.stopReason) return "add_unfixed";
      return "implement";
    },
    {
      implement: "implement",
      add_unfixed: "add_unfixed",
    },
  );

  // 线性：implement → static_check
  workflow.addEdge("implement", "static_check");

  // Conditional: static_check后决定继续或重试
  workflow.addConditionalEdges(
    "static_check",
    (state) => {
      if (state.lastStaticOk) return "verify";
      const maxIterate = state.options?.maxIterate ?? 3;
      if (state.iteration >= maxIterate) return "add_unfixed";
      return "implement";
    },
    {
      verify: "verify",
      implement: "implement",
      add_unfixed: "add_unfixed",
    },
  );

  // Conditional: verify后决定下一步
  workflow.addConditionalEdges(
    "verify",
    (state) => {
      if (state.verifyOk) {
        return state.options?.skipReviewer ? "deliver" : "review";
      }
      return "classify";
    },
    {
      review: "review",
      deliver: "deliver",
      classify: "classify",
    },
  );

  // Conditional: classify后决定继续或停止
  workflow.addConditionalEdges(
    "classify",
    (state) => {
      if (state.stopReason) return "add_unfixed";
      const maxIterate = state.options?.maxIterate ?? 3;
      if (state.iteration >= maxIterate) return "add_unfixed";
      return "implement";
    },
    {
      implement: "implement",
      add_unfixed: "add_unfixed",
    },
  );

  // Conditional: review后决定accept或request_changes
  workflow.addConditionalEdges(
    "review",
    (state) => {
      if (!state.verifyOk) {
        // reviewer要求修改
        const maxIterate = state.options?.maxIterate ?? 3;
        if (state.iteration >= maxIterate) return "add_unfixed";
        return "implement";
      }
      return "deliver";
    },
    {
      deliver: "deliver",
      implement: "implement",
      add_unfixed: "add_unfixed",
    },
  );

  // Conditional: deliver后检查是否成功
  workflow.addConditionalEdges(
    "deliver",
    (state) => {
      if (state.stopReason) return "add_unfixed";
      return "next_cluster";
    },
    {
      add_unfixed: "add_unfixed",
      next_cluster: "next_cluster",
    },
  );

  // 汇总：unfixed和next_cluster都回到prepare_cluster
  workflow.addEdge("add_unfixed", "next_cluster");
  workflow.addEdge("next_cluster", "prepare_cluster");

  // 最终：build_report → END
  workflow.addEdge("build_report", END);

  // ==================== 编译图 ====================

  return workflow.compile();
}

/**
 * 辅助函数：运行LangGraph的bugfix流程
 */
export async function runBugfixGraph(input: {
  runId: string;
  workDir: string;
  defects: Defect[];
  userPrompt?: string;
  options?: CreateRunOptions;
}): Promise<RunReport> {
  const graph = createBugfixGraph();

  const initialState: Partial<BugfixAgentState> = {
    runId: input.runId,
    workDir: input.workDir,
    defects: input.defects,
    userPrompt: input.userPrompt,
    options: input.options,
  };

  const result = await graph.invoke(initialState as BugfixAgentState);

  if (!result.report) {
    throw new Error("Graph execution completed but no report generated");
  }

  return result.report;
}
