import { readFile } from "node:fs/promises";
import type { SweInstance } from "./types.js";

/** Load SWE instances from .json (array) or .jsonl. */
export async function loadSweInstances(filePath: string): Promise<SweInstance[]> {
  const raw = await readFile(filePath, "utf8");
  const trimmed = raw.trim();
  if (!trimmed) return [];

  if (trimmed.startsWith("[")) {
    const arr = JSON.parse(trimmed) as unknown;
    if (!Array.isArray(arr)) throw new Error("Expected JSON array of instances");
    return arr.map(assertInstance);
  }

  const out: SweInstance[] = [];
  for (const line of trimmed.split(/\r?\n/)) {
    if (!line.trim()) continue;
    out.push(assertInstance(JSON.parse(line)));
  }
  return out;
}

function assertInstance(x: unknown): SweInstance {
  if (!x || typeof x !== "object") throw new Error("Invalid SWE instance");
  const o = x as Record<string, unknown>;
  for (const key of ["instance_id", "repo", "base_commit", "problem_statement"] as const) {
    if (typeof o[key] !== "string" || !o[key]) {
      throw new Error(`SWE instance missing string field: ${key}`);
    }
  }
  return o as SweInstance;
}
