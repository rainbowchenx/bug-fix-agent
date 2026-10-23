import {
  extractLabeledJson,
  parseRootCause,
  parseSolutionText,
  type RootCauseArtifact,
  type SolutionArtifact,
} from "../agent/artifacts.js";
import { runAgentSession, type RunAgentSessionInput } from "../agent/sdk-runner.js";
import type { Cluster, Defect, ReasonCode } from "../types.js";
import { FAILURE_MODE_HINT } from "./failure-modes.js";
import { gateFromRootCause } from "./fixability.js";
import {
  localizationFromSolution,
  type LocalizationArtifact,
} from "./localization.js";
import { buildRepoMap, formatRepoMap } from "./repo-map.js";

export interface AnalyzeClusterInput {
  cluster: Cluster;
  defects: Defect[];
  repoPath: string;
  userPrompt?: string;
  mcpServers?: Record<string, unknown>;
  skillsDir?: string;
  skillIds?: string[];
  disallowedTools?: string[];
  /** Test seam / offline mode */
  mockArtifacts?: {
    rootCause: RootCauseArtifact;
    solution?: SolutionArtifact;
    localization?: LocalizationArtifact;
  };
  /** Test seam. Production uses the Claude Agent SDK session. */
  sessionRunner?: (input: RunAgentSessionInput) => Promise<{ text: string }>;
}

export type AnalyzeClusterResult =
  | {
      status: "fixable";
      rootCause: RootCauseArtifact;
      solution: SolutionArtifact;
      localization: LocalizationArtifact;
      agentTranscript?: string;
    }
  | {
      status: "unfixed";
      reasonCode: ReasonCode;
      reasonDetail: string;
      rootCause?: RootCauseArtifact;
      solution?: SolutionArtifact;
      localization?: LocalizationArtifact;
      /** Raw analyze replies, kept so a bad SOLUTION can be diagnosed later. */
      agentTranscript?: string;
    };

export function buildAnalyzePrompt(input: AnalyzeClusterInput, repoMapText = ""): string {
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

Repo map:
${repoMapText || "(unavailable)"}

Tasks (read-only tools only):
1) Localize likely files/symbols.
2) Map to a failure_mode in: ${FAILURE_MODE_HINT}
3) State hypothesis + evidence bullets.
4) Produce RootCauseArtifact JSON with fixability.assessment in fixable|needs_more_context|not_actionable.
5) If fixable, produce SolutionArtifact JSON with concrete steps AND target_files (relative paths allowlist for scope lock).

Also output LOCALIZATION JSON: { "suspectFiles": [], "symbols": [], "editTargets": [] }.
editTargets should match solution target_files.

Output separate JSON objects clearly labeled ROOT_CAUSE, SOLUTION, and LOCALIZATION.
Prefer each as its own \`\`\`json fenced block after the label. Do not nest them in one object.

ROOT_CAUSE fields: headline, one_line_description, five_whys, reproduction_steps, failure_mode, hypothesis, evidence, fixability{assessment,reason}, relevant_repo?
SOLUTION fields: one_line_summary, steps[{title,description}], target_files[], acceptance_criteria?

Put each label on its own line, immediately before its JSON object. Do not place those label words inside JSON string values.`;
}

const TRANSCRIPT_LIMIT = 100_000;

export function buildSolutionRepairPrompt(rootCause: RootCauseArtifact, parseError: string): string {
  return `The root cause below is already accepted as fixable. Do not re-investigate and do not edit files.
The previous SOLUTION artifact was missing or did not match the schema.

Parse error:
${parseError.slice(0, 1500)}

Root cause:
${JSON.stringify(rootCause, null, 2)}

Reply with ONE JSON object only, labeled SOLUTION on the line before it:
{
  "one_line_summary": "minimal change",
  "steps": [{ "title": "what", "description": "how, tied to the evidence" }],
  "target_files": ["relative/path/from/evidence"],
  "acceptance_criteria": ["observable check"]
}

Rules:
- steps items are objects with title and description, never bare strings.
- target_files are repo-relative paths already named in the root-cause evidence or hypothesis.
- Do not invent files, a broader refactor, or a new hypothesis.
- If the evidence names no file, still return the JSON and use an empty target_files array.`;
}

function formatParseError(err: unknown): string {
  const message = err instanceof Error ? err.message : String(err);
  return message.slice(0, 1500);
}

function readLocalization(text: string): LocalizationArtifact | undefined {
  try {
    const raw = extractLabeledJson(text, "LOCALIZATION");
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) return undefined;
    const obj = raw as Record<string, unknown>;
    const strings = (value: unknown) =>
      Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
    return {
      suspectFiles: strings(obj.suspectFiles),
      symbols: strings(obj.symbols),
      editTargets: strings(obj.editTargets),
    };
  } catch {
    return undefined;
  }
}

function clipTranscript(text: string): string {
  return text.length > TRANSCRIPT_LIMIT ? text.slice(0, TRANSCRIPT_LIMIT) : text;
}

export async function analyzeCluster(
  input: AnalyzeClusterInput,
): Promise<AnalyzeClusterResult> {
  try {
    let rootCause: RootCauseArtifact;
    let solution: SolutionArtifact | undefined;
    let localizationExtra: LocalizationArtifact | undefined;

    let agentTranscript: string | undefined;

    if (input.mockArtifacts) {
      rootCause = input.mockArtifacts.rootCause;
      solution = input.mockArtifacts.solution;
      localizationExtra = input.mockArtifacts.localization;
    } else {
      const run = input.sessionRunner ?? runAgentSession;
      const map = await buildRepoMap(input.repoPath).catch(() => undefined);
      const sessionBase = {
        cwd: input.repoPath,
        mode: "analyze" as const,
        mcpServers: input.mcpServers,
        skillsDir: input.skillsDir,
        skillIds: input.skillIds,
        disallowedTools: input.disallowedTools,
      };
      const first = await run({
        ...sessionBase,
        prompt: buildAnalyzePrompt(input, map ? formatRepoMap(map) : ""),
        maxTurns: 50,
      });
      let transcript = first.text;
      agentTranscript = clipTranscript(transcript);
      try {
        rootCause = parseRootCause(extractLabeledJson(first.text, "ROOT_CAUSE"));
      } catch (err) {
        return {
          status: "unfixed",
          reasonCode: "analyze_failed",
          reasonDetail: `Analyze failed: ${formatParseError(err)}`,
          agentTranscript,
        };
      }
      let solutionError = "";
      try {
        solution = parseSolutionText(first.text);
      } catch (err) {
        solutionError = formatParseError(err);
      }
      localizationExtra = readLocalization(first.text);

      const gateNow = gateFromRootCause(rootCause);
      if (gateNow.status === "fixable" && !solution) {
        const repair = await run({
          ...sessionBase,
          prompt: buildSolutionRepairPrompt(rootCause, solutionError),
          maxTurns: 2,
          disallowedTools: [
            ...new Set([
              ...(input.disallowedTools ?? []),
              "Read",
              "Glob",
              "Grep",
              "Edit",
              "Write",
              "Bash",
              "Skill",
            ]),
          ],
        });
        transcript = `${transcript}\n\n--- solution repair ---\n${repair.text}`;
        try {
          solution = parseSolutionText(repair.text, { allowBare: true });
        } catch (err) {
          solutionError = `${solutionError}; repair failed: ${formatParseError(err)}`;
        }
      }
      agentTranscript = clipTranscript(transcript);
      if (!solution && gateNow.status === "fixable") {
        const localization = localizationFromSolution(undefined, localizationExtra);
        return {
          status: "unfixed",
          reasonCode: "analyze_failed",
          reasonDetail: `Root cause is fixable but solution artifact missing or invalid. ${solutionError}`,
          rootCause,
          localization,
          agentTranscript,
        };
      }
    }

    const localization = localizationFromSolution(solution, localizationExtra);

    const gate = gateFromRootCause(rootCause);
    if (gate.status === "unfixed") {
      return {
        status: "unfixed",
        reasonCode: gate.reasonCode,
        reasonDetail: gate.reasonDetail,
        rootCause,
        solution,
        localization,
        agentTranscript,
      };
    }

    if (!solution) {
      return {
        status: "unfixed",
        reasonCode: "analyze_failed",
        reasonDetail: "Root cause is fixable but solution artifact missing or invalid.",
        rootCause,
        localization,
        agentTranscript,
      };
    }

    return { status: "fixable", rootCause, solution, localization, agentTranscript };
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return {
      status: "unfixed",
      reasonCode: "analyze_failed",
      reasonDetail: `Analyze failed: ${message}`,
    };
  }
}
