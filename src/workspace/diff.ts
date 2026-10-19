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

function isAgentLocalPath(filePath: string): boolean {
  return filePath.replace(/\\/g, "/").startsWith(".claude/");
}

async function diffUntrackedFile(
  repoPath: string,
  filePath: string,
  execFileFn: ExecFileFn,
): Promise<string> {
  try {
    const { stdout } = await execFileFn(
      "git",
      ["diff", "--no-index", "--", "/dev/null", filePath],
      { cwd: repoPath },
    );
    return stdout;
  } catch (err) {
    // git --no-index exits 1 when a diff exists and still prints it on stdout.
    const e = err as { stdout?: string };
    return e.stdout ?? "";
  }
}

export async function getDiffText(
  repoPath: string,
  baseSha: string,
  execFileFn: ExecFileFn = defaultExec,
  maxChars = 24_000,
): Promise<string> {
  const { stdout } = await execFileFn(
    "git",
    ["diff", baseSha, "--", ".", ":(exclude).claude"],
    { cwd: repoPath },
  );
  const { stdout: untrackedNames } = await execFileFn(
    "git",
    ["ls-files", "--others", "--exclude-standard"],
    { cwd: repoPath },
  ).catch(() => ({ stdout: "" }));
  let text = stdout;
  const names = untrackedNames
    .split(/\r?\n/)
    .map((s) => s.trim())
    .filter((name) => name && !isAgentLocalPath(name));
  for (const name of names.slice(0, 20)) {
    text += await diffUntrackedFile(repoPath, name, execFileFn);
  }
  const trimmed = text.trim();
  if (trimmed.length <= maxChars) return trimmed;
  return trimmed.slice(0, maxChars) + "\n... [diff truncated]";
}
