import type { RootCauseArtifact, SolutionArtifact } from "../agent/artifacts.js";
import { runAgentSession } from "../agent/sdk-runner.js";
import type { Cluster } from "../types.js";

export interface ImplementClusterInput {
  cluster: Cluster;
  repoPath: string;
  rootCause: RootCauseArtifact;
  solution: SolutionArtifact;
  verifyLogTail?: string;
  iteration: number;
  /** Test seam */
  mockChangedFiles?: string[];
}

export interface ImplementClusterResult {
  changedFiles: string[];
  agentText: string;
}

function buildImplementPrompt(input: ImplementClusterInput): string {
  return `Implement a minimal fix for cluster ${input.cluster.id}: ${input.cluster.primaryTitle}

Root cause:
${JSON.stringify(input.rootCause, null, 2)}

Solution plan:
${JSON.stringify(input.solution, null, 2)}

Iteration: ${input.iteration}
Previous verify log (if any):
${input.verifyLogTail ?? "(none)"}

Rules:
- Minimal diff only; do not refactor unrelated code.
- Prefer editing existing files over creating new ones.
- Do not commit, push, or open MRs.
`;
}

export async function implementCluster(
  input: ImplementClusterInput,
): Promise<ImplementClusterResult> {
  if (input.mockChangedFiles) {
    return { changedFiles: input.mockChangedFiles, agentText: "(mock)" };
  }
  const { text } = await runAgentSession({
    cwd: input.repoPath,
    prompt: buildImplementPrompt(input),
    mode: "implement",
    maxTurns: 40,
  });
  return { changedFiles: [], agentText: text };
}

export function shouldContinueIterate(
  iteration: number,
  maxIterate: number,
  verifyOk: boolean,
): boolean {
  if (verifyOk) return false;
  return iteration < maxIterate;
}
