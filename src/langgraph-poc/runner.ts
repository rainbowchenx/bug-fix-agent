/**
 * LangGraph POC - Runner
 * 
 * 展示如何使用LangGraph版本的bugfix agent，并与原始实现保持API兼容
 */

import type { CreateRunRequest, RunReport } from "../types.js";
import { runBugfixGraph } from "./graph.js";
import { updateRunMeta, writeReport } from "../runs/store.js";

/**
 * 使用LangGraph引擎运行bugfix pipeline
 * 
 * 这个函数可以替换原来的 `runPipeline` 函数
 */
export async function runPipelineWithLangGraph(
  workDir: string,
  runId: string,
): Promise<RunReport> {
  // 更新状态：开始运行
  await updateRunMeta(workDir, runId, {
    status: "running",
    progress: { phase: "langgraph", message: "Initializing LangGraph workflow" },
  });

  try {
    // 从存储加载请求数据（与原始实现相同）
    const { readJson } = await import("../runs/store.js");
    const { runDir } = await import("../workspace/paths.js");
    const path = await import("node:path");

    const dir = runDir(workDir, runId);
    const request = await readJson<CreateRunRequest>(path.join(dir, "input.request.json"));

    // 运行LangGraph
    const report = await runBugfixGraph({
      runId,
      workDir,
      defects: request.defects,
      userPrompt: request.userPrompt,
      options: request.options,
    });

    // 保存报告
    await writeReport(workDir, runId, report);

    // 更新状态：完成
    await updateRunMeta(workDir, runId, {
      status: "completed",
      progress: {
        phase: "done",
        completedClusters: report.summary.totalClusters,
        totalClusters: report.summary.totalClusters,
      },
    });

    return report;
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);

    await updateRunMeta(workDir, runId, {
      status: "failed",
      error: message,
    });

    throw err;
  }
}

/**
 * 异步入队运行（与原始实现API兼容）
 */
export function enqueueRunWithLangGraph(workDir: string, runId: string): void {
  setImmediate(() => {
    void runPipelineWithLangGraph(workDir, runId).catch(async (err) => {
      const message = err instanceof Error ? err.message : String(err);
      await updateRunMeta(workDir, runId, {
        status: "failed",
        error: message,
      });
    });
  });
}

/**
 * 统一的Runner接口：支持选择引擎
 */
export type ExecutionEngine = "claude-sdk" | "langgraph";

export interface UnifiedRunnerOptions {
  engine?: ExecutionEngine;
  // 其他原有的options（token, host等）可以继续保留
  maxIterate?: number;
  gitlabToken?: string;
  gitlabHost?: string;
}

/**
 * 统一的运行函数：根据engine参数选择执行引擎
 */
export async function runPipelineUnified(
  workDir: string,
  runId: string,
  options: UnifiedRunnerOptions = {},
): Promise<RunReport> {
  const engine = options.engine ?? "claude-sdk"; // 默认保持向后兼容

  if (engine === "langgraph") {
    return runPipelineWithLangGraph(workDir, runId);
  } else {
    // 使用原始的Claude SDK实现
    const { runPipeline } = await import("../runs/runner.js");
    return runPipeline(workDir, runId, {
      maxIterate: options.maxIterate,
      gitlabToken: options.gitlabToken,
      gitlabHost: options.gitlabHost,
    });
  }
}

/**
 * 统一的入队函数
 */
export function enqueueRunUnified(
  workDir: string,
  runId: string,
  options: UnifiedRunnerOptions = {},
): void {
  const engine = options.engine ?? "claude-sdk";

  if (engine === "langgraph") {
    enqueueRunWithLangGraph(workDir, runId);
  } else {
    // 使用原始实现
    void import("../runs/runner.js").then(({ enqueueRun }) => {
      enqueueRun(workDir, runId, {
        maxIterate: options.maxIterate,
        gitlabToken: options.gitlabToken,
        gitlabHost: options.gitlabHost,
      });
    });
  }
}

/**
 * 使用示例
 */
export const exampleUsage = `
// 方式1：直接使用LangGraph
import { runBugfixGraph } from "./langgraph-poc/graph.js";

const report = await runBugfixGraph({
  runId: "test-123",
  workDir: "/tmp/work",
  defects: [
    {
      id: "1",
      title: "Null pointer crash",
      repoUrl: "https://gitlab.com/org/repo.git",
    }
  ]
});

// 方式2：通过统一接口（保持HTTP API不变）
import { runPipelineUnified } from "./langgraph-poc/runner.js";

const report = await runPipelineUnified(
  "/tmp/work",
  "test-123",
  { engine: "langgraph" } // 或 "claude-sdk"
);

// 方式3：在HTTP API中支持选择引擎
// POST /v1/runs
{
  "workDir": "/tmp/work",
  "defects": [...],
  "options": {
    "engine": "langgraph"  // 新增字段，可选
  }
}
`;
