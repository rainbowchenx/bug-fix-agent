import { loadConfig } from "../config.js";
import { resolveVerifyPlan, type ResolveVerifyPlanInput } from "../profiles/detect.js";
import type { VerifyPlan } from "../profiles/types.js";
import { ExecTimeoutError, timedExec } from "../util/exec.js";

export type { VerifyPlan };
export { resolveVerifyPlan };

export interface VerifyResult {
  ok: boolean;
  command: string;
  logTail: string;
  timedOut?: boolean;
}

export async function runVerify(
  repoPath: string,
  plan: Pick<VerifyPlan, "test">,
  timeoutMs?: number,
): Promise<VerifyResult> {
  if (!plan.test.length) {
    return { ok: false, command: "", logTail: "No test command configured" };
  }
  const ms = timeoutMs ?? loadConfig().execTimeoutMs;
  const command = plan.test.join(" && ");
  try {
    const { stdout, stderr } = await timedExec(command, { cwd: repoPath, timeoutMs: ms });
    const log = `${stdout}\n${stderr}`.trim();
    return { ok: true, command, logTail: log.slice(-4000) };
  } catch (err) {
    if (err instanceof ExecTimeoutError) {
      return { ok: false, command, timedOut: true, logTail: err.message };
    }
    const e = err as { stdout?: string; stderr?: string; message?: string };
    const log = `${e.stdout ?? ""}\n${e.stderr ?? ""}\n${e.message ?? ""}`.trim();
    return { ok: false, command, logTail: log.slice(-4000) };
  }
}

export async function resolveAndDescribe(
  input: ResolveVerifyPlanInput,
): Promise<VerifyPlan> {
  return resolveVerifyPlan(input);
}
