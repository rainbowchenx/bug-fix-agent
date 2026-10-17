import { execFile as execFileCb } from "node:child_process";
import { promisify } from "node:util";
import { createMergeRequest, projectIdFromRepoUrl } from "../gitlab/client.js";
import { hasCodeChanges } from "../workspace/diff.js";
import type { ExecFileFn } from "../workspace/git.js";

const execFile = promisify(execFileCb);

export interface DeliverFixInput {
  repoPath: string;
  runId: string;
  clusterId: string;
  title: string;
  description: string;
  gitlabHost: string;
  token: string;
  repoUrl: string;
  targetBranch?: string;
  projectId?: string | number;
  baseSha?: string;
  draftMr?: boolean;
  defectIds?: string[];
  execFileFn?: ExecFileFn;
  fetchFn?: typeof fetch;
}

export interface DeliverFixResult {
  mrUrl: string;
  branch: string;
}

export class NoChangesError extends Error {
  constructor(message = "No code changes relative to base; refusing to open MR") {
    super(message);
    this.name = "NoChangesError";
  }
}

export function bugfixBranchName(runId: string, clusterId: string): string {
  const safeRun = runId.replace(/[^a-zA-Z0-9_-]/g, "").slice(0, 24);
  const safeCluster = clusterId.replace(/[^a-zA-Z0-9_-]/g, "").slice(0, 24);
  return `bugfix/${safeRun || "run"}/${safeCluster || "cluster"}`;
}

const GIT_IDENTITY = [
  "-c",
  "user.name=bugfix-agent",
  "-c",
  "user.email=bugfix-agent@local",
];

export async function deliverFix(input: DeliverFixInput): Promise<DeliverFixResult> {
  const run = input.execFileFn ?? execFile;
  const branch = bugfixBranchName(input.runId, input.clusterId);
  const target = input.targetBranch ?? "main";

  if (input.baseSha) {
    const changed = await hasCodeChanges(input.repoPath, input.baseSha, run);
    if (!changed) throw new NoChangesError();
  }

  await run("git", ["checkout", "-B", branch], { cwd: input.repoPath });
  await run("git", ["add", "-A"], { cwd: input.repoPath });

  try {
    await run(
      "git",
      [...GIT_IDENTITY, "commit", "-m", `fix: ${input.title.slice(0, 72)}`],
      { cwd: input.repoPath },
    );
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    if (/nothing to commit/i.test(msg)) {
      throw new NoChangesError("git commit: nothing to commit");
    }
    throw err;
  }

  const authArgs = input.token
    ? ["-c", `http.extraHeader=Authorization: Bearer ${input.token}`]
    : [];
  await run("git", [...authArgs, "push", "-u", "origin", branch], {
    cwd: input.repoPath,
  });

  const projectId = input.projectId ?? projectIdFromRepoUrl(input.repoUrl);
  const title = input.draftMr
    ? input.title.startsWith("Draft:")
      ? input.title
      : `Draft: ${input.title}`
    : input.title;

  const mr = await createMergeRequest({
    host: input.gitlabHost,
    token: input.token,
    projectId,
    sourceBranch: branch,
    targetBranch: target,
    title,
    description: input.description,
    fetchFn: input.fetchFn,
  });

  return { mrUrl: mr.mrUrl, branch };
}

export function buildMrDescription(input: {
  rootCauseSummary: string;
  solutionSummary: string;
  defectIds: string[];
  verifyCommand: string;
  verifyLogTail?: string;
  reproductionSteps?: string[];
}): string {
  const parts = [
    `## Defects`,
    input.defectIds.map((id) => `- ${id}`).join("\n") || "- (none)",
    "",
    `## Root cause`,
    input.rootCauseSummary,
    "",
    `## Solution`,
    input.solutionSummary,
  ];
  if (input.reproductionSteps?.length) {
    parts.push("", "## Reproduction", ...input.reproductionSteps.map((s) => `- ${s}`));
  }
  parts.push(
    "",
    "## Verify",
    `\`${input.verifyCommand}\``,
    input.verifyLogTail ? `\n\`\`\`\n${input.verifyLogTail.slice(0, 1500)}\n\`\`\`` : "",
  );
  return parts.filter((p) => p !== undefined).join("\n");
}
