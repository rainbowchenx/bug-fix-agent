/** SWE-bench style instance — kept inside the adapter only. */
export interface SweInstance {
  instance_id: string;
  repo: string;
  base_commit: string;
  problem_statement: string;
  /** JSON string or string[] of failing test node ids / paths */
  FAIL_TO_PASS?: string | string[];
  PASS_TO_PASS?: string | string[];
  version?: string;
  environment_setup_commit?: string;
  [key: string]: unknown;
}

export interface SwePrediction {
  instance_id: string;
  model_name_or_path: string;
  model_patch: string;
}

export interface SweBatchOptions {
  workDir: string;
  instances: SweInstance[];
  /** Max instances to run (default all). */
  limit?: number;
  modelName?: string;
  predictionsPath: string;
  /** Skip reviewer for cheaper baseline runs. Default true. */
  skipReviewer?: boolean;
  maxIterate?: number;
  engine?: "pipeline" | "langgraph";
  /** When true, do not run prepare/install (verify may still run). */
  skipInstall?: boolean;
}
