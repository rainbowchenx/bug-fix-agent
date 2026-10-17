import { exec as execCb, type ExecOptions } from "node:child_process";
import { promisify } from "node:util";

const execAsync = promisify(execCb);

export class ExecTimeoutError extends Error {
  constructor(command: string, timeoutMs: number) {
    super(`Command timed out after ${timeoutMs}ms: ${command}`);
    this.name = "ExecTimeoutError";
  }
}

export interface TimedExecResult {
  stdout: string;
  stderr: string;
}

/** exec with timeout + CI-friendly env. */
export async function timedExec(
  command: string,
  options: {
    cwd: string;
    timeoutMs: number;
    env?: NodeJS.ProcessEnv;
  },
): Promise<TimedExecResult> {
  const shell = process.platform === "win32" ? "cmd.exe" : "/bin/sh";
  const opts: ExecOptions = {
    cwd: options.cwd,
    maxBuffer: 8 * 1024 * 1024,
    shell,
    timeout: options.timeoutMs,
    killSignal: "SIGKILL",
    env: {
      ...process.env,
      CI: "1",
      FORCE_COLOR: "0",
      ...options.env,
    },
  };
  try {
    const { stdout, stderr } = await execAsync(command, opts);
    return {
      stdout: typeof stdout === "string" ? stdout : stdout.toString(),
      stderr: typeof stderr === "string" ? stderr : stderr.toString(),
    };
  } catch (err) {
    const e = err as {
      killed?: boolean;
      signal?: string;
      code?: string | number;
      stdout?: string;
      stderr?: string;
      message?: string;
    };
    if (e.killed || e.signal === "SIGTERM" || e.signal === "SIGKILL" || e.code === "ETIMEDOUT") {
      throw new ExecTimeoutError(command, options.timeoutMs);
    }
    throw err;
  }
}
