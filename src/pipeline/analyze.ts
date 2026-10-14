import {
  extractJsonObject,
  parseRootCause,
  parseSolution,
  type RootCauseArtifact,
  type SolutionArtifact,
} from "../agent/artifacts.js";
import { runAgentSession } from "../agent/sdk-runner.js";
import type { Cluster, Defect, ReasonCode } from "../types.js";
import { gateFromRootCause } from "./fixability.js";

export interface AnalyzeClusterInput {
  cluster: Cluster;
  defects: Defect[];
  repoPath: string;
  userPrompt?: string;
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

function buildAnalyzePrompt(input: AnalyzeClusterInput): string {
  const defectText = input.defects
    .map(
      (d) =>
        `- [${d.id}] ${d.title}\n  ${d.description ?? ""}\n  stack: ${d.stackTrace ?? "n/a"}`,
    )
    .join("\n");
  return `You are analyzing a defect cluster for an automated bugfix agent.
Cluster: ${input.cluster.id} — ${input.cluster.primaryTitle}
Repo: ${input.cluster.repoUrl}
User guidance: ${input.userPrompt ?? "(none)"}

Defects:
${defectText}

Tasks:
1) Localize likely files/symbols (read-only).
2) Produce a RootCauseArtifact JSON with fixability.assessment in fixable|needs_more_context|not_actionable.
3) If fixable, also produce a SolutionArtifact JSON with concrete steps.

Output TWO JSON objects clearly labeled ROOT_CAUSE and SOLUTION.`;
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
