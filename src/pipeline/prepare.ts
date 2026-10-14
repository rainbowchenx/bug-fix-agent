import { exec as execCb } from "node:child_process";
import { promisify } from "node:util";
import type { VerifyPlan } from "../profiles/types.js";

const exec = promisify(execCb);

export interface PrepareResult {
  ok: boolean;
  logTail: string;
}

export async function prepareRepo(
  repoPath: string,
  plan: Pick<VerifyPlan, "install">,
  execFn: typeof exec = exec,
): Promise<PrepareResult> {
  if (!plan.install.length) {
    return { ok: true, logTail: "No install commands" };
  }
  const command = plan.install.join(" && ");
  try {
    const { stdout, stderr } = await execFn(command, {
      cwd: repoPath,
      maxBuffer: 8 * 1024 * 1024,
      shell: process.platform === "win32" ? "cmd.exe" : "/bin/sh",
    });
    return { ok: true, logTail: `${stdout}\n${stderr}`.trim().slice(-4000) };
  } catch (err) {
    const e = err as { stdout?: string; stderr?: string; message?: string };
    return {
      ok: false,
      logTail: `${e.stdout ?? ""}\n${e.stderr ?? ""}\n${e.message ?? ""}`.trim().slice(-4000),
    };
  }
}
