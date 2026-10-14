import { access } from "node:fs/promises";
import { execFile as execFileCb } from "node:child_process";
import { promisify } from "node:util";
import { repoPath } from "./paths.js";

const execFile = promisify(execFileCb);

export type ExecFileFn = (
  file: string,
  args: string[],
  options?: { cwd?: string; env?: NodeJS.ProcessEnv },
) => Promise<{ stdout: string; stderr: string }>;

function withTokenUrl(repoUrl: string, token?: string): string {
  if (!token) return repoUrl;
  try {
    const u = new URL(repoUrl);
    if (u.username || u.password) return repoUrl;
    u.username = "oauth2";
    u.password = token;
    return u.toString();
  } catch {
    return repoUrl;
  }
}

/** Redact token from strings for logs. */
export function redactSecrets(text: string, token?: string): string {
  if (!token) return text;
  return text.split(token).join("***");
}

export interface EnsureRepoInput {
  workDir: string;
  repoUrl: string;
  branch?: string;
  token?: string;
  execFileFn?: ExecFileFn;
}

export interface EnsureRepoResult {
  repoPath: string;
  headSha: string;
}

async function pathExists(p: string): Promise<boolean> {
  try {
    await access(p);
    return true;
  } catch {
    return false;
  }
}

export async function ensureRepo(input: EnsureRepoInput): Promise<EnsureRepoResult> {
  const run = input.execFileFn ?? execFile;
  const dest = repoPath(input.workDir, input.repoUrl);
  const cloneUrl = withTokenUrl(input.repoUrl, input.token);
  const gitDir = `${dest}/.git`;

  if (await pathExists(gitDir)) {
    await run("git", ["fetch", "--all", "--prune"], { cwd: dest });
    if (input.branch) {
      await run("git", ["checkout", input.branch], { cwd: dest });
      await run("git", ["pull", "--ff-only"], { cwd: dest }).catch(() => undefined);
    }
  } else {
    const args = ["clone", "--depth", "50"];
    if (input.branch) args.push("--branch", input.branch);
    args.push(cloneUrl, dest);
    await run("git", args);
  }

  const { stdout } = await run("git", ["rev-parse", "HEAD"], { cwd: dest });
  return { repoPath: dest, headSha: stdout.trim() };
}
