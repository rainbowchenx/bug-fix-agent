import type { RunMeta, RunReport } from "../types.js";
import type { StorageAdapter } from "./adapter.js";

export interface HttpStorageOptions {
  baseUrl: string;
  token?: string;
  fetchFn?: typeof fetch;
}

export function createHttpStorage(options: HttpStorageOptions): StorageAdapter {
  const fetchFn = options.fetchFn ?? fetch;
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (options.token) headers.Authorization = `Bearer ${options.token}`;

  return {
    async syncProgress(meta: RunMeta) {
      const res = await fetchFn(`${options.baseUrl.replace(/\/$/, "")}/progress`, {
        method: "POST",
        headers,
        body: JSON.stringify(meta),
      });
      if (!res.ok) throw new Error(`storage progress sync failed: ${res.status}`);
    },
    async syncReport(report: RunReport, meta: RunMeta) {
      const res = await fetchFn(`${options.baseUrl.replace(/\/$/, "")}/report`, {
        method: "POST",
        headers,
        body: JSON.stringify({ report, meta }),
      });
      if (!res.ok) throw new Error(`storage report sync failed: ${res.status}`);
    },
  };
}
