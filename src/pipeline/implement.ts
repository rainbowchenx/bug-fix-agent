import type { RootCauseArtifact, SolutionArtifact } from "../agent/artifacts.js";
import { runAgentSession } from "../agent/sdk-runner.js";
import type { Cluster } from "../types.js";
import { checkScopeLock, extractAllowedFiles } from "./scope-lock.js";

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
  scopeOk: boolean;
  scopeViolations: string[];
}

export function buildImplementPrompt(input: ImplementClusterInput): string {
  const allowed = extractAllowedFiles(input.solution);
  const scopeBlock =
    allowed.length > 0
      ? `SCOPE LOCK — you may ONLY edit these files:\n${allowed.map((f) => `- ${f}`).join("\n")}\nEditing any other file is forbidden.`
      : `SCOPE LOCK — only edit files named in the solution steps; do not touch unrelated modules.`;

  return `Implement a minimal fix for cluster ${input.cluster.id}: ${input.cluster.primaryTitle}

IRON LAW reminder: implement only the evidenced hypothesis; no symptom patches.

Root cause:
${JSON.stringify(input.rootCause, null, 2)}

Solution plan:
${JSON.stringify(input.solution, null, 2)}

${scopeBlock}

Iteration: ${input.iteration}
Previous verify log (if any):
${input.verifyLogTail ?? "(none)"}

Rules:
- Minimal diff only; do not refactor unrelated code.
- Prefer editing existing files over creating new ones.
- Prefer fixing product code over weakening tests (unless the test assertion is clearly wrong).
- Do not commit, push, or open MRs.
`;
}

export async function implementCluster(
  input: ImplementClusterInput,
): Promise<ImplementClusterResult> {
  if (input.mockChangedFiles) {
    const scope = checkScopeLock(input.mockChangedFiles, input.solution);
    return {
      changedFiles: input.mockChangedFiles,
      agentText: "(mock)",
      scopeOk: scope.ok,
      scopeViolations: scope.violations,
    };
  }
  const { text } = await runAgentSession({
    cwd: input.repoPath,
    prompt: buildImplementPrompt(input),
    mode: "implement",
    maxTurns: 40,
  });
  // Real SDK sessions do not reliably return a file list here; scope is enforced via prompt.
  // Callers may pass git-diff based lists later.
  return {
    changedFiles: [],
    agentText: text,
    scopeOk: true,
    scopeViolations: [],
  };
}

export function shouldContinueIterate(
  iteration: number,
  maxIterate: number,
  verifyOk: boolean,
): boolean {
  if (verifyOk) return false;
  return iteration < maxIterate;
}
