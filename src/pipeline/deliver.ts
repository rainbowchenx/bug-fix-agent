import { execFile as execFileCb } from "node:child_process";
import { promisify } from "node:util";
import { createMergeRequest, projectIdFromRepoUrl } from "../gitlab/client.js";
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
  execFileFn?: ExecFileFn;
  fetchFn?: typeof fetch;
}

export interface DeliverFixResult {
  mrUrl: string;
  branch: string;
}

export function bugfixBranchName(runId: string, clusterId: string): string {
  const safeRun = runId.replace(/[^a-zA-Z0-9_-]/g, "").slice(0, 24);
  const safeCluster = clusterId.replace(/[^a-zA-Z0-9_-]/g, "").slice(0, 24);
  return `bugfix/${safeRun || "run"}/${safeCluster || "cluster"}`;
}

export async function deliverFix(input: DeliverFixInput): Promise<DeliverFixResult> {
  const run = input.execFileFn ?? execFile;
  const branch = bugfixBranchName(input.runId, input.clusterId);
  const target = input.targetBranch ?? "main";

  await run("git", ["checkout", "-B", branch], { cwd: input.repoPath });
  await run("git", ["add", "-A"], { cwd: input.repoPath });
  await run(
    "git",
    ["commit", "-m", `fix: ${input.title.slice(0, 72)}`],
    { cwd: input.repoPath },
  ).catch(async (err) => {
    // nothing to commit?
    const msg = err instanceof Error ? err.message : String(err);
    if (!/nothing to commit/i.test(msg)) throw err;
  });
  await run("git", ["push", "-u", "origin", branch], { cwd: input.repoPath });

  const projectId = input.projectId ?? projectIdFromRepoUrl(input.repoUrl);
  const mr = await createMergeRequest({
    host: input.gitlabHost,
    token: input.token,
    projectId,
    sourceBranch: branch,
    targetBranch: target,
    title: input.title,
    description: input.description,
    fetchFn: input.fetchFn,
  });

  return { mrUrl: mr.mrUrl, branch };
}
