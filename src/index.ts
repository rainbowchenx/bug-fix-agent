export { loadConfig, type AppConfig } from "./config.js";

export interface StartServerOptions {
  port?: number;
}

/** Placeholder until Task 4 wires Hono + node-server. */
export async function startServer(options: StartServerOptions = {}): Promise<void> {
  const { loadConfig } = await import("./config.js");
  const cfg = loadConfig();
  const port = options.port ?? cfg.port;
  console.log(`bugfix-agent: server stub listening intent on 127.0.0.1:${port} (Task 4 will bind)`);
}

export function createApp(): never {
  throw new Error("createApp not implemented yet (Task 4)");
}
