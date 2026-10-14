import { exec as execCb } from "node:child_process";
import { promisify } from "node:util";
import { resolveVerifyPlan, type ResolveVerifyPlanInput } from "../profiles/detect.js";
import type { VerifyPlan } from "../profiles/types.js";

const exec = promisify(execCb);

export type { VerifyPlan };
export { resolveVerifyPlan };

export interface VerifyResult {
  ok: boolean;
  command: string;
  logTail: string;
}

export async function runVerify(
  repoPath: string,
  plan: Pick<VerifyPlan, "test">,
  execFn: typeof exec = exec,
): Promise<VerifyResult> {
  if (!plan.test.length) {
    return { ok: false, command: "", logTail: "No test command configured" };
  }
  const command = plan.test.join(" && ");
  try {
    const { stdout, stderr } = await execFn(command, {
      cwd: repoPath,
      maxBuffer: 4 * 1024 * 1024,
      shell: process.platform === "win32" ? "cmd.exe" : "/bin/sh",
    });
    const log = `${stdout}\n${stderr}`.trim();
    return { ok: true, command, logTail: log.slice(-4000) };
  } catch (err) {
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
