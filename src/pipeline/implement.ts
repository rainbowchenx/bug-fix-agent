import type { RootCauseArtifact, SolutionArtifact } from "../agent/artifacts.js";
import { runAgentSession } from "../agent/sdk-runner.js";
import type { Cluster } from "../types.js";
import { listChangedFiles } from "../workspace/diff.js";
import { checkScopeLock, extractAllowedFiles } from "./scope-lock.js";

export interface ImplementClusterInput {
  cluster: Cluster;
  repoPath: string;
  rootCause: RootCauseArtifact;
  solution: SolutionArtifact;
  baseSha?: string;
  verifyLogTail?: string;
  iteration: number;
  /** reproduce = failing test only; fix = product change (default). */
  phase?: "reproduce" | "fix";
  skillsDir?: string;
  skillIds?: string[];
  mcpServers?: Record<string, unknown>;
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

  if (input.phase === "reproduce") {
    return `Write a minimal failing regression test for cluster ${input.cluster.id}: ${input.cluster.primaryTitle}

Do NOT fix product code in this step. Add one focused test that fails on the current bug.
Place it beside the allowlisted files (same package), named *.test.* or *.spec.*.

${scopeBlock}

Root cause:
${JSON.stringify(input.rootCause, null, 2)}

Solution plan:
${JSON.stringify(input.solution, null, 2)}
`;
  }

  return `Implement a minimal fix for cluster ${input.cluster.id}: ${input.cluster.primaryTitle}

IRON LAW reminder: implement only the evidenced hypothesis; no symptom patches.

Root cause:
${JSON.stringify(input.rootCause, null, 2)}

Solution plan:
${JSON.stringify(input.solution, null, 2)}

${scopeBlock}

Iteration: ${input.iteration}
Previous verify/static/review feedback (if any):
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
    skillsDir: input.skillsDir,
    skillIds: input.skillIds,
    mcpServers: input.mcpServers,
  });

  let changedFiles: string[] = [];
  if (input.baseSha) {
    try {
      changedFiles = await listChangedFiles(input.repoPath, input.baseSha);
    } catch {
      changedFiles = [];
    }
  }

  const scope = checkScopeLock(changedFiles, input.solution);
  return {
    changedFiles,
    agentText: text,
    scopeOk: scope.ok,
    scopeViolations: scope.violations,
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
