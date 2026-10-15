import {
  extractJsonObject,
  parseRootCause,
  parseSolution,
  type RootCauseArtifact,
  type SolutionArtifact,
} from "../agent/artifacts.js";
import { runAgentSession } from "../agent/sdk-runner.js";
import type { Cluster, Defect, ReasonCode } from "../types.js";
import { FAILURE_MODE_HINT } from "./failure-modes.js";
import { gateFromRootCause } from "./fixability.js";

export interface AnalyzeClusterInput {
  cluster: Cluster;
  defects: Defect[];
  repoPath: string;
  userPrompt?: string;
  mcpServers?: Record<string, unknown>;
  skillsDir?: string;
  /** Test seam / offline mode */
  mockArtifacts?: {
    rootCause: RootCauseArtifact;
    solution?: SolutionArtifact;
  };
}

export type AnalyzeClusterResult =
  | {
      status: "fixable";
      rootCause: RootCauseArtifact;
      solution: SolutionArtifact;
    }
  | {
      status: "unfixed";
      reasonCode: ReasonCode;
      reasonDetail: string;
      rootCause?: RootCauseArtifact;
      solution?: SolutionArtifact;
    };

export function buildAnalyzePrompt(input: AnalyzeClusterInput): string {
  const defectText = input.defects
    .map(
      (d) =>
        `- [${d.id}] ${d.title}\n  ${d.description ?? ""}\n  stack: ${d.stackTrace ?? "n/a"}`,
    )
    .join("\n");
  return `You are analyzing a defect cluster for an automated bugfix agent (batch mode, no human wait).

IRON LAW: No code changes without a proven hypothesis. Every later edit must trace to evidenced root cause. If you cannot evidence a hypothesis, set fixability to needs_more_context or not_actionable — do NOT invent a large refactor plan.

This is a BugFix light path (not a greenfield feature): localize → root cause → minimal solution. Skip product/architecture redesign.

Cluster: ${input.cluster.id} — ${input.cluster.primaryTitle}
Repo: ${input.cluster.repoUrl}
User guidance: ${input.userPrompt ?? "(none)"}

Defects:
${defectText}

Tasks (read-only tools only):
1) Localize likely files/symbols.
2) Map to a failure_mode in: ${FAILURE_MODE_HINT}
3) State hypothesis + evidence bullets.
4) Produce RootCauseArtifact JSON with fixability.assessment in fixable|needs_more_context|not_actionable.
5) If fixable, produce SolutionArtifact JSON with concrete steps AND target_files (relative paths allowlist for scope lock).

Output TWO JSON objects clearly labeled ROOT_CAUSE and SOLUTION.

ROOT_CAUSE fields: headline, one_line_description, five_whys, reproduction_steps, failure_mode, hypothesis, evidence, fixability{assessment,reason}, relevant_repo?
SOLUTION fields: one_line_summary, steps[{title,description}], target_files[], acceptance_criteria?`;
}

function parseLabeled(text: string, label: string): unknown {
  const re = new RegExp(`${label}[\\s\\S]*?(\\{[\\s\\S]*\\})`, "i");
  const m = re.exec(text);
  if (m?.[1]) return JSON.parse(m[1]);
  return extractJsonObject(text);
}

export async function analyzeCluster(
  input: AnalyzeClusterInput,
): Promise<AnalyzeClusterResult> {
  try {
    let rootCause: RootCauseArtifact;
    let solution: SolutionArtifact | undefined;

    if (input.mockArtifacts) {
      rootCause = input.mockArtifacts.rootCause;
      solution = input.mockArtifacts.solution;
    } else {
      const { text } = await runAgentSession({
        cwd: input.repoPath,
        prompt: buildAnalyzePrompt(input),
        mode: "analyze",
        maxTurns: 25,
        mcpServers: input.mcpServers,
        skillsDir: input.skillsDir,
      });
      rootCause = parseRootCause(parseLabeled(text, "ROOT_CAUSE"));
      try {
        solution = parseSolution(parseLabeled(text, "SOLUTION"));
      } catch {
        solution = undefined;
      }
    }

    const gate = gateFromRootCause(rootCause);
    if (gate.status === "unfixed") {
      return {
        status: "unfixed",
        reasonCode: gate.reasonCode,
        reasonDetail: gate.reasonDetail,
        rootCause,
        solution,
      };
    }

    if (!solution) {
      return {
        status: "unfixed",
        reasonCode: "analyze_failed",
        reasonDetail: "Root cause is fixable but solution artifact missing or invalid.",
        rootCause,
      };
    }

    return { status: "fixable", rootCause, solution };
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return {
      status: "unfixed",
      reasonCode: "analyze_failed",
      reasonDetail: `Analyze failed: ${message}`,
    };
  }
}
