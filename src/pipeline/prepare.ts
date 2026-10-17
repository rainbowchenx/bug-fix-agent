import { loadConfig } from "../config.js";
import { ExecTimeoutError, timedExec } from "../util/exec.js";
import type { VerifyPlan } from "../profiles/types.js";

export interface PrepareResult {
  ok: boolean;
  logTail: string;
  timedOut?: boolean;
}

export async function prepareRepo(
  repoPath: string,
  plan: Pick<VerifyPlan, "install">,
  timeoutMs?: number,
): Promise<PrepareResult> {
  if (!plan.install.length) {
    return { ok: true, logTail: "No install commands" };
  }
  const ms = timeoutMs ?? loadConfig().execTimeoutMs;
  const command = plan.install.join(" && ");
  try {
    const { stdout, stderr } = await timedExec(command, { cwd: repoPath, timeoutMs: ms });
    return { ok: true, logTail: `${stdout}\n${stderr}`.trim().slice(-4000) };
  } catch (err) {
    if (err instanceof ExecTimeoutError) {
      return { ok: false, timedOut: true, logTail: err.message };
    }
    const e = err as { stdout?: string; stderr?: string; message?: string };
    return {
      ok: false,
      logTail: `${e.stdout ?? ""}\n${e.stderr ?? ""}\n${e.message ?? ""}`.trim().slice(-4000),
    };
  }
}
