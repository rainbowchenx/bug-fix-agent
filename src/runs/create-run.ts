import type { CreateRunRequest } from "../types.js";
import { parseCreateRunRequest } from "../types.js";
import { createRunDir, updateRunMeta, writeInputDefects } from "./store.js";
import { enqueueRun } from "./runner.js";

export interface CreateRunResult {
  runId: string;
  status: "queued";
}

export async function startRun(input: unknown): Promise<CreateRunResult> {
  const request: CreateRunRequest = parseCreateRunRequest(input);
  const { runId } = await createRunDir(request.workDir);
  await writeInputDefects(request.workDir, runId, request.defects, request);
  await updateRunMeta(request.workDir, runId, { status: "queued" });
  enqueueRun(request.workDir, runId);
  return { runId, status: "queued" };
}
