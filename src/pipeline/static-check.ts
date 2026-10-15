import { exec as execCb } from "node:child_process";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { promisify } from "node:util";

const exec = promisify(execCb);

export interface StaticCheckPlan {
  commands: string[];
}

export interface StaticCheckResult {
  ok: boolean;
  command: string;
  logTail: string;
}

async function readPackageJson(
  repoPath: string,
): Promise<Record<string, unknown> | null> {
  try {
    const raw = await readFile(path.join(repoPath, "package.json"), "utf8");
    return JSON.parse(raw) as Record<string, unknown>;
  } catch {
    return null;
  }
}

/** Detect lint/tsc commands from package.json scripts / deps. Empty = skip gate. */
export async function resolveStaticCheckPlan(repoPath: string): Promise<StaticCheckPlan> {
  const pkg = await readPackageJson(repoPath);
  if (!pkg) return { commands: [] };

  const scripts = (pkg.scripts ?? {}) as Record<string, string>;
  const deps = {
    ...(pkg.dependencies as Record<string, string> | undefined),
    ...(pkg.devDependencies as Record<string, string> | undefined),
  };
  const commands: string[] = [];

  if (scripts.typecheck) commands.push("npm run typecheck");
  else if (scripts["tsc"] && /noEmit|--noEmit/.test(scripts["tsc"])) {
    commands.push("npm run tsc");
  } else if (deps.typescript) {
    commands.push("npx tsc --noEmit");
  }

  if (scripts.lint) commands.push("npm run lint");
  else if (deps.eslint) commands.push("npx eslint . --max-warnings=0");

  return { commands };
}

export async function runStaticCheck(
  repoPath: string,
  plan: StaticCheckPlan,
  execFn: typeof exec = exec,
): Promise<StaticCheckResult> {
  if (!plan.commands.length) {
    return { ok: true, command: "", logTail: "No static check commands; skipped" };
  }
  const command = plan.commands.join(" && ");
  try {
    const { stdout, stderr } = await execFn(command, {
      cwd: repoPath,
      maxBuffer: 4 * 1024 * 1024,
      shell: process.platform === "win32" ? "cmd.exe" : "/bin/sh",
    });
    return {
      ok: true,
      command,
      logTail: `${stdout}\n${stderr}`.trim().slice(-4000),
    };
  } catch (err) {
    const e = err as { stdout?: string; stderr?: string; message?: string };
    return {
      ok: false,
      command,
      logTail: `${e.stdout ?? ""}\n${e.stderr ?? ""}\n${e.message ?? ""}`.trim().slice(-4000),
    };
  }
}
