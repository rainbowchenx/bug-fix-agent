import type { RunMeta, RunReport } from "../types.js";

export type StorageSyncMode = "best_effort" | "required" | "off";

export interface StorageAdapter {
  syncProgress?(meta: RunMeta): Promise<void>;
  syncReport?(report: RunReport, meta: RunMeta): Promise<void>;
}

export async function safeSync(
  mode: StorageSyncMode,
  fn: () => Promise<void>,
): Promise<void> {
  if (mode === "off") return;
  try {
    await fn();
  } catch (err) {
    if (mode === "required") throw err;
    // best_effort: swallow
  }
}
