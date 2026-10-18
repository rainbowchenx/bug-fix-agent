import { END, START, StateGraph, type BaseCheckpointSaver } from "@langchain/langgraph";
import type { RunnableConfig } from "@langchain/core/runnables";
import { loadConfig } from "../config.js";
import { aggregateDefects } from "../pipeline/aggregate.js";
import { normalizeDefects } from "../pipeline/normalize.js";
import { bindClusterMeta } from "../pipeline/cluster-meta.js";
import { buildReport } from "../pipeline/report.js";
import {
  createRunDir,
  readMeta,
  updateRunMeta,
  writeClustersPlan,
  writeInputDefects,
  writeReport,
} from "../runs/store.js";
import { parseCreateRunRequest, type CreateRunRequest, type RunReport } from "../types.js";
import { createClusterGraph, type BugfixGraphOptions } from "./cluster-graph.js";
import { RunStateAnnotation, type RunState, type RunUpdate } from "./state.js";

export interface CreateBugfixGraphOptions extends BugfixGraphOptions {
  checkpointer?: BaseCheckpointSaver;
}

/** Upper bound on supersteps for one cluster: 4 setup nodes + up to 5 nodes per iteration. */
export function clusterRecursionLimit(maxIterate: number): number {
  return 16 + maxIterate * 8;
}

/** Upper bound on supersteps for the run graph (clusters ≤ defects). */
export function runRecursionLimit(defectCount: number): number {
  return 10 + defectCount * 2;
}

/**
 * Builds the top-level LangGraph for a batch run. Artifacts and meta are persisted to
 * `{workDir}/.bugfix-runs/{runId}/` exactly like the legacy pipeline, so `GET /v1/runs/:id`
 * works regardless of engine. When invoked without `runId` (e.g. LangGraph Server / Studio),
 * a run directory is created on the fly.
 */
export function createBugfixGraph(opts: CreateBugfixGraphOptions = {}) {
  const clusterGraph = createClusterGraph(opts);

  const initNode = async (s: RunState): Promise<RunUpdate> => {
    const request: CreateRunRequest = parseCreateRunRequest({
      workDir: s.workDir,
      defects: s.defects,
      userPrompt: s.userPrompt,
      options: s.options,
    });
    let runId = s.runId;
    if (runId) {
      try {
        await readMeta(request.workDir, runId);
      } catch {
        await createRunDir(request.workDir, runId);
        await writeInputDefects(request.workDir, runId, request.defects, request);
      }
    } else {
      runId = (await createRunDir(request.workDir)).runId;
      await writeInputDefects(request.workDir, runId, request.defects, request);
    }
    await updateRunMeta(request.workDir, runId, {
      status: "running",
      progress: { phase: "normalize", message: "Normalizing defects" },
    });
    return { runId, clusterIndex: 0 };
  };

  const normalizeNode = async (s: RunState): Promise<RunUpdate> => {
    return { defects: normalizeDefects(s.defects) };
  };

  const aggregateNode = async (s: RunState): Promise<RunUpdate> => {
    await updateRunMeta(s.workDir, s.runId!, {
      progress: { phase: "aggregate", message: "Aggregating clusters" },
    });
    const clusters = aggregateDefects(s.defects);
    await writeClustersPlan(s.workDir, s.runId!, clusters);
    return { clusters };
  };

  const processClusterNode = async (
    s: RunState,
    config?: RunnableConfig,
  ): Promise<RunUpdate> => {
    const cluster = s.clusters[s.clusterIndex]!;
    await updateRunMeta(s.workDir, s.runId!, {
      progress: {
        phase: "cluster",
        currentClusterId: cluster.id,
        completedClusters: s.clusterIndex,
        totalClusters: s.clusters.length,
        message: `Processing ${cluster.id}`,
      },
    });

    const maxIterate = opts.maxIterate ?? s.options?.maxIterate ?? loadConfig().maxIterate;
    const unbind = bindClusterMeta({
      started: Date.now(),
      branch: cluster.branch,
      iterations: 0,
      skillsInvoked: [],
      mcpToolsInvoked: [],
      verifyLevel: "regression_only",
      baselineRed: false,
    });
    const result = await clusterGraph.invoke(
      {
        workDir: s.workDir,
        runId: s.runId!,
        cluster,
        defects: s.defects.filter((d) => cluster.defectIds.includes(d.id)),
        userPrompt: s.userPrompt,
        options: s.options,
        iteration: 0,
        feedbackLog: "",
        lastVerifyLog: "",
        verifyCommand: "",
        staticOk: false,
        verifyOk: false,
        reviewApproved: false,
      },
      { ...config, recursionLimit: clusterRecursionLimit(maxIterate) },
    );
    unbind();

    const outcome = result.outcome ?? {
      unfixed: {
        clusterId: cluster.id,
        defectIds: cluster.defectIds,
        reasonCode: "unknown" as const,
        reasonDetail: "Cluster graph finished without an outcome.",
      },
    };
    return {
      clusterIndex: s.clusterIndex + 1,
      fixed: outcome.fixed ? [outcome.fixed] : [],
      unfixed: outcome.unfixed ? [outcome.unfixed] : [],
    };
  };

  const reportNode = async (s: RunState): Promise<RunUpdate> => {
    const report = buildReport(s.runId!, s.fixed, s.unfixed, {
      startedAt: new Date().toISOString(),
      finishedAt: new Date().toISOString(),
      engine: "langgraph",
    });
    await writeReport(s.workDir, s.runId!, report);
    await updateRunMeta(s.workDir, s.runId!, {
      status: "completed",
      progress: {
        phase: "done",
        completedClusters: s.clusters.length,
        totalClusters: s.clusters.length,
      },
    });
    return { report };
  };

  const nextCluster = (s: RunState) =>
    s.clusterIndex < s.clusters.length ? "process_cluster" : "build_report";

  return new StateGraph(RunStateAnnotation)
    .addNode("init", initNode)
    .addNode("normalize", normalizeNode)
    .addNode("aggregate", aggregateNode)
    .addNode("process_cluster", processClusterNode)
    .addNode("build_report", reportNode)
    .addEdge(START, "init")
    .addEdge("init", "normalize")
    .addEdge("normalize", "aggregate")
    .addConditionalEdges("aggregate", nextCluster, ["process_cluster", "build_report"])
    .addConditionalEdges("process_cluster", nextCluster, ["process_cluster", "build_report"])
    .addEdge("build_report", END)
    .compile({ checkpointer: opts.checkpointer });
}

export interface InvokeBugfixGraphInput {
  workDir: string;
  runId?: string;
  defects: CreateRunRequest["defects"];
  userPrompt?: string;
  options?: CreateRunRequest["options"];
}

/** Runs the LangGraph engine end-to-end and returns the dual-outcome report. */
export async function invokeBugfixGraph(
  input: InvokeBugfixGraphInput,
  opts: CreateBugfixGraphOptions = {},
  config: RunnableConfig = {},
): Promise<RunReport> {
  const graph = createBugfixGraph(opts);
  const result = await graph.invoke(input, {
    recursionLimit: runRecursionLimit(input.defects.length),
    ...config,
  });
  if (!result.report) {
    throw new Error("LangGraph run finished without a report");
  }
  return result.report;
}
