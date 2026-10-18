import { Annotation } from "@langchain/langgraph";
import type { RootCauseArtifact, SolutionArtifact } from "../agent/artifacts.js";
import type { GateSnapshot } from "../pipeline/baseline.js";
import type { StaticCheckPlan } from "../pipeline/static-check.js";
import type { VerifyPlan } from "../pipeline/verify.js";
import type {
  Cluster,
  CreateRunOptions,
  Defect,
  FixedCluster,
  RunReport,
  UnfixedCluster,
} from "../types.js";

export interface ClusterGraphOutcome {
  fixed?: FixedCluster;
  unfixed?: UnfixedCluster;
}

function appendList<T>(left: T[], right: T[] | undefined): T[] {
  return right?.length ? [...left, ...right] : left;
}

/** Per-cluster subgraph state: analyze → implement/static/verify/review loop → deliver. */
export const ClusterStateAnnotation = Annotation.Root({
  workDir: Annotation<string>(),
  runId: Annotation<string>(),
  cluster: Annotation<Cluster>(),
  defects: Annotation<Defect[]>(),
  userPrompt: Annotation<string | undefined>(),
  options: Annotation<CreateRunOptions | undefined>(),

  repoPath: Annotation<string | undefined>(),
  baseSha: Annotation<string | undefined>(),
  rootCause: Annotation<RootCauseArtifact | undefined>(),
  solution: Annotation<SolutionArtifact | undefined>(),
  verifyPlan: Annotation<VerifyPlan | undefined>(),
  staticPlan: Annotation<StaticCheckPlan | undefined>(),
  baselineStatic: Annotation<GateSnapshot | undefined>(),
  baselineVerify: Annotation<GateSnapshot | undefined>(),

  iteration: Annotation<number>(),
  feedbackLog: Annotation<string>(),
  lastVerifyLog: Annotation<string>(),
  verifyCommand: Annotation<string>(),
  staticOk: Annotation<boolean>(),
  verifyOk: Annotation<boolean>(),
  reviewApproved: Annotation<boolean>(),

  /** Set exactly once by whichever node terminates the cluster. */
  outcome: Annotation<ClusterGraphOutcome | undefined>(),
});

export type ClusterState = typeof ClusterStateAnnotation.State;
export type ClusterUpdate = typeof ClusterStateAnnotation.Update;

/** Top-level run graph state. Input keys: workDir, defects, userPrompt?, options?, runId?. */
export const RunStateAnnotation = Annotation.Root({
  workDir: Annotation<string>(),
  runId: Annotation<string | undefined>(),
  defects: Annotation<Defect[]>(),
  userPrompt: Annotation<string | undefined>(),
  options: Annotation<CreateRunOptions | undefined>(),

  clusters: Annotation<Cluster[]>(),
  clusterIndex: Annotation<number>(),
  fixed: Annotation<FixedCluster[]>({ reducer: appendList, default: () => [] }),
  unfixed: Annotation<UnfixedCluster[]>({ reducer: appendList, default: () => [] }),

  report: Annotation<RunReport | undefined>(),
});

export type RunState = typeof RunStateAnnotation.State;
export type RunUpdate = typeof RunStateAnnotation.Update;
