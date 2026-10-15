export interface KnownIssuesInput {
  iterations: number;
  maxIterate: number;
  verifyCommand: string;
  logTail: string;
  rootCauseSummary?: string;
  solutionSummary?: string;
  actionsTaken?: string[];
}

/** QA-style Known Issues block after iterate budget exhausted. */
export function buildKnownIssuesDetail(input: KnownIssuesInput): string {
  const actions =
    input.actionsTaken?.length
      ? input.actionsTaken.map((a) => `- ${a}`).join("\n")
      : `- Ran implement→verify up to ${input.iterations} iteration(s) (budget ${input.maxIterate})`;
  const tail = input.logTail.trim().slice(-2000);
  return [
    "Known Issues (iterate budget exhausted — stopping further fix loops)",
    "",
    "Done:",
    actions,
    input.rootCauseSummary ? `- Root cause: ${input.rootCauseSummary}` : undefined,
    input.solutionSummary ? `- Solution attempted: ${input.solutionSummary}` : undefined,
    "",
    `Verify command: \`${input.verifyCommand || "(none)"}\``,
    "",
    "Remaining risk / last failure tail:",
    tail || "(empty)",
  ]
    .filter((line) => line !== undefined)
    .join("\n");
}
