import {
  extractJsonObject,
  type RootCauseArtifact,
  type SolutionArtifact,
} from "../agent/artifacts.js";
import { runAgentSession } from "../agent/sdk-runner.js";

export type ReviewDecision = "approve" | "request_changes";

export interface ReviewResult {
  decision: ReviewDecision;
  reasons: string[];
}

export interface ReviewClusterInput {
  repoPath: string;
  rootCause: RootCauseArtifact;
  solution: SolutionArtifact;
  verifyCommand: string;
  verifyLogTail?: string;
  /** Unified diff text from orchestrator (preferred over blind review). */
  diffText?: string;
  iteration: number;
  skillsDir?: string;
  skillIds?: string[];
  mcpServers?: Record<string, unknown>;
  /** Test seam */
  mockResult?: ReviewResult;
}

export function parseReviewResult(text: string): ReviewResult {
  let raw: unknown;
  try {
    raw = extractJsonObject(text);
  } catch {
    const m = /"decision"\s*:\s*"(approve|request_changes)"/i.exec(text);
    if (m?.[1]) {
      return {
        decision: m[1].toLowerCase() as ReviewDecision,
        reasons: ["Parsed decision from partial reviewer output"],
      };
    }
    throw new Error("Reviewer output missing JSON decision");
  }
  const obj = raw as { decision?: string; reasons?: unknown };
  const decision = String(obj.decision ?? "").toLowerCase();
  if (decision !== "approve" && decision !== "request_changes") {
    throw new Error(`Invalid review decision: ${obj.decision}`);
  }
  const reasons = Array.isArray(obj.reasons)
    ? obj.reasons.map(String)
    : ["(no reasons provided)"];
  return { decision, reasons };
}

export function buildReviewPrompt(input: ReviewClusterInput): string {
  const diffBlock =
    input.diffText && input.diffText.trim()
      ? input.diffText.trim().slice(0, 24_000)
      : "(no diff provided — request_changes if you cannot verify the patch)";
  return `You are a readonly code reviewer for an automated bugfix agent.
Do NOT edit files. Decide only from the provided context and DIFF.

Root cause:
${JSON.stringify(input.rootCause, null, 2)}

Solution:
${JSON.stringify(input.solution, null, 2)}

Verify: ${input.verifyCommand} (already GREEN)
Verify log tail:
${input.verifyLogTail ?? "(none)"}

DIFF (vs base):
\`\`\`diff
${diffBlock}
\`\`\`

Iteration: ${input.iteration}

Checks:
- Diff stays within scope (target_files) and matches root cause
- No drive-by refactors or weakened tests without cause
- Residual risks called out

Output ONE JSON object only (no other braces outside it):
{ "decision": "approve" | "request_changes", "reasons": ["..."] }
`;
}

export async function reviewCluster(input: ReviewClusterInput): Promise<ReviewResult> {
  if (input.mockResult) return input.mockResult;

  const tryOnce = async (prompt: string): Promise<ReviewResult> => {
    const { text } = await runAgentSession({
      cwd: input.repoPath,
      prompt,
      mode: "review",
      maxTurns: 20,
      skillsDir: input.skillsDir,
      skillIds: input.skillIds,
      mcpServers: input.mcpServers,
    });
    return parseReviewResult(text);
  };

  try {
    return await tryOnce(buildReviewPrompt(input));
  } catch (first) {
    // One retry: short prompt asking for JSON only
    try {
      return await tryOnce(
        `Previous review output was invalid JSON. Reply with ONLY:\n{"decision":"approve"|"request_changes","reasons":["..."]}\nContext: ${input.rootCause.one_line_description}`,
      );
    } catch {
      throw first instanceof Error ? first : new Error(String(first));
    }
  }
}
