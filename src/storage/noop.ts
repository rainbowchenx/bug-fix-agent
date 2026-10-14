import type { StorageAdapter } from "./adapter.js";

export const noopStorage: StorageAdapter = {
  async syncProgress() {},
  async syncReport() {},
};
