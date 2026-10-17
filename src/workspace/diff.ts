import { execFile as execFileCb } from "node:child_process";
import { promisify } from "node:util";
import type { ExecFileFn } from "./git.js";

const defaultExec = promisify(execFileCb) as ExecFileFn;

export async function listChangedFiles(
  repoPath: string,
  baseSha: string,
  execFileFn: ExecFileFn = defaultExec,
): Promise<string[]> {
  const { stdout } = await execFileFn(
    "git",
    ["diff", "--name-only", "--diff-filter=ACMR", baseSha],
    { cwd: repoPath },
  );
  const tracked = stdout
    .split(/\r?\n/)
    .map((s) => s.trim())
    .filter(Boolean);

  // Include untracked new files
  const { stdout: untracked } = await execFileFn(
    "git",
    ["ls-files", "--others", "--exclude-standard"],
    { cwd: repoPath },
  ).catch(() => ({ stdout: "" }));
  const extra = untracked
    .split(/\r?\n/)
    .map((s) => s.trim())
    .filter(Boolean);

  // Ignore agent-mounted skills / local Claude project dirs — not product diffs
  const all = [...new Set([...tracked, ...extra])].filter(
    (f) => !f.replace(/\\/g, "/").startsWith(".claude/"),
  );
  return all;
}

export async function hasCodeChanges(
  repoPath: string,
  baseSha: string,
  execFileFn: ExecFileFn = defaultExec,
): Promise<boolean> {
  const files = await listChangedFiles(repoPath, baseSha, execFileFn);
  return files.length > 0;
}

export async function getDiffText(
  repoPath: string,
  baseSha: string,
  execFileFn: ExecFileFn = defaultExec,
  maxChars = 24_000,
): Promise<string> {
  const { stdout } = await execFileFn("git", ["diff", baseSha], { cwd: repoPath });
  const { stdout: untrackedNames } = await execFileFn(
    "git",
    ["ls-files", "--others", "--exclude-standard"],
    { cwd: repoPath },
  ).catch(() => ({ stdout: "" }));
  let text = stdout;
  const names = untrackedNames.split(/\r?\n/).map((s) => s.trim()).filter(Boolean);
  for (const name of names.slice(0, 20)) {
    text += `\n--- /dev/null\n+++ b/${name}\n(new untracked file)\n`;
  }
  const trimmed = text.trim();
  if (trimmed.length <= maxChars) return trimmed;
  return trimmed.slice(0, maxChars) + "\n... [diff truncated]";
}
