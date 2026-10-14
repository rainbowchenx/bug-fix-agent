import { randomUUID } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import type { Cluster, CreateRunRequest, Defect, RunMeta, RunReport, RunStatus } from "../types.js";
import { clusterDir, runDir } from "../workspace/paths.js";

async function ensureDir(dir: string): Promise<void> {
  await mkdir(dir, { recursive: true });
}

export async function writeJson(filePath: string, data: unknown): Promise<void> {
  await ensureDir(path.dirname(filePath));
  await writeFile(filePath, `${JSON.stringify(data, null, 2)}\n`, "utf8");
}

export async function readJson<T>(filePath: string): Promise<T> {
  const raw = await readFile(filePath, "utf8");
  return JSON.parse(raw) as T;
}

export async function createRunDir(
  workDir: string,
  runId: string = randomUUID(),
): Promise<{ runId: string; dir: string }> {
  const dir = runDir(workDir, runId);
  await ensureDir(path.join(dir, "clusters"));
  const now = new Date().toISOString();
  const meta: RunMeta = {
    runId,
    workDir,
    status: "queued",
    createdAt: now,
    updatedAt: now,
  };
  await writeJson(path.join(dir, "meta.json"), meta);
  return { runId, dir };
}

export async function writeInputDefects(
  workDir: string,
  runId: string,
  defects: Defect[],
  request?: CreateRunRequest,
): Promise<void> {
  const dir = runDir(workDir, runId);
  await writeJson(path.join(dir, "input.defects.json"), defects);
  if (request) {
    await writeJson(path.join(dir, "input.request.json"), request);
  }
}

export async function writeClustersPlan(
  workDir: string,
  runId: string,
  clusters: Cluster[],
): Promise<void> {
  await writeJson(path.join(runDir(workDir, runId), "plan.clusters.json"), {
    clusters,
  });
}

export async function writeReport(
  workDir: string,
  runId: string,
  report: RunReport,
): Promise<void> {
  await writeJson(path.join(runDir(workDir, runId), "report.json"), report);
}

export async function readReport(
  workDir: string,
  runId: string,
): Promise<RunReport | null> {
  try {
    return await readJson<RunReport>(path.join(runDir(workDir, runId), "report.json"));
  } catch {
    return null;
  }
}

export async function readMeta(workDir: string, runId: string): Promise<RunMeta> {
  return readJson<RunMeta>(path.join(runDir(workDir, runId), "meta.json"));
}

export async function updateRunMeta(
  workDir: string,
  runId: string,
  patch: Partial<Pick<RunMeta, "status" | "progress" | "error">>,
): Promise<RunMeta> {
  const meta = await readMeta(workDir, runId);
  const next: RunMeta = {
    ...meta,
    ...patch,
    updatedAt: new Date().toISOString(),
  };
  await writeJson(path.join(runDir(workDir, runId), "meta.json"), next);
  return next;
}

export async function writeClusterArtifact(
  workDir: string,
  runId: string,
  clusterId: string,
  name: string,
  data: unknown,
): Promise<void> {
  const dir = clusterDir(workDir, runId, clusterId);
  await writeJson(path.join(dir, name), data);
}

export function newRunId(): string {
  return randomUUID();
}

export type { RunStatus };
