import { serve } from "@hono/node-server";
import { loadConfig, type AppConfig } from "./config.js";
import { createApp } from "./http/app.js";

export { loadConfig, type AppConfig } from "./config.js";
export { createApp } from "./http/app.js";
export { startRun } from "./runs/create-run.js";
export { runPipeline } from "./runs/runner.js";
export * from "./types.js";
export * from "./agent/artifacts.js";

export interface StartServerOptions {
  port?: number;
  hostname?: string;
}

export async function startServer(options: StartServerOptions = {}): Promise<void> {
  const cfg = loadConfig();
  const port = options.port ?? cfg.port;
  const hostname = options.hostname ?? "127.0.0.1";
  const app = createApp();

  serve({ fetch: app.fetch, port, hostname }, (info) => {
    console.log(`bugfix-agent listening on http://${hostname}:${info.port}`);
  });
}
