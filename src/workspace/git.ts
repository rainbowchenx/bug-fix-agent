import { access, mkdir } from "node:fs/promises";
import { execFile as execFileCb } from "node:child_process";
import { promisify } from "node:util";
import { repoPath, worktreePath } from "./paths.js";

const execFile = promisify(execFileCb);

export type ExecFileFn = (
  file: string,
  args: string[],
  options?: { cwd?: string; env?: NodeJS.ProcessEnv },
) => Promise<{ stdout: string; stderr: string }>;

/** Redact token from strings for logs. */
export function redactSecrets(text: string, token?: string): string {
  if (!token) return text;
  return text.split(token).join("***");
}

export function cleanRepoUrl(repoUrl: string): string {
  try {
    if (repoUrl.startsWith("git@")) return repoUrl;
    const u = new URL(repoUrl);
    u.username = "";
    u.password = "";
    return u.toString();
  } catch {
    return repoUrl;
  }
}

function authExtraArgs(token?: string): string[] {
  if (!token) return [];
  // Avoid persisting token in remote URL / .git/config
  return ["-c", `http.extraHeader=Authorization: Bearer ${token}`];
}

export interface EnsureRepoInput {
  workDir: string;
  runId: string;
  clusterId: string;
  repoUrl: string;
  branch?: string;
  token?: string;
  execFileFn?: ExecFileFn;
}

export interface EnsureRepoResult {
  /** Cluster worktree cwd */
  repoPath: string;
  /** Shared clone with .git */
  mirrorPath: string;
  baseSha: string;
  /** @deprecated alias of baseSha at ensure time */
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

async function ensureMirror(
  run: ExecFileFn,
  mirror: string,
  repoUrl: string,
  branch: string | undefined,
  token: string | undefined,
): Promise<void> {
  const clean = cleanRepoUrl(repoUrl);
  const auth = authExtraArgs(token);
  const gitDir = `${mirror}/.git`;

  if (await pathExists(gitDir)) {
    await run("git", [...auth, "fetch", "--all", "--prune"], { cwd: mirror });
    if (branch) {
      await run("git", ["checkout", branch], { cwd: mirror }).catch(() => undefined);
      await run("git", [...auth, "pull", "--ff-only"], { cwd: mirror }).catch(() => undefined);
    }
  } else {
    await mkdir(mirror, { recursive: true });
    const args = [...auth, "clone", "--depth", "50"];
    if (branch) args.push("--branch", branch);
    args.push(clean, mirror);
    await run("git", args);
    // Ensure remote URL has no embedded credentials
    await run("git", ["remote", "set-url", "origin", clean], { cwd: mirror });
  }
}

/**
 * Ensure shared mirror + per-cluster worktree.
 * Pipeline cwd is the worktree path.
 */
export async function ensureRepo(input: EnsureRepoInput): Promise<EnsureRepoResult> {
  const run = input.execFileFn ?? execFile;
  const mirror = repoPath(input.workDir, input.repoUrl);
  const wt = worktreePath(input.workDir, input.runId, input.clusterId);

  await ensureMirror(run, mirror, input.repoUrl, input.branch, input.token);

  const { stdout: shaOut } = await run("git", ["rev-parse", "HEAD"], { cwd: mirror });
  const baseSha = shaOut.trim();

  if (await pathExists(wt)) {
    // Reuse existing worktree: reset to base
    await run("git", ["reset", "--hard", baseSha], { cwd: wt });
    await run("git", ["clean", "-fdx"], { cwd: wt });
  } else {
    await mkdir(wt, { recursive: true });
    // Remove empty dir so worktree add can create it
    const { rm } = await import("node:fs/promises");
    await rm(wt, { recursive: true, force: true });
    await run(
      "git",
      ["worktree", "add", "--detach", wt, baseSha],
      { cwd: mirror },
    );
  }

  return {
    repoPath: wt,
    mirrorPath: mirror,
    baseSha,
    headSha: baseSha,
  };
}

export async function removeWorktree(
  mirrorPath: string,
  worktree: string,
  execFileFn: ExecFileFn = execFile,
): Promise<void> {
  await execFileFn("git", ["worktree", "remove", "--force", worktree], {
    cwd: mirrorPath,
  }).catch(() => undefined);
}
