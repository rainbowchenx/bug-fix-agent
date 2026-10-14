import { Hono } from "hono";
import { startRun } from "../runs/create-run.js";
import { readMeta, readReport } from "../runs/store.js";

export function createApp(): Hono {
  const app = new Hono();

  app.get("/health", (c) => c.json({ ok: true }));

  app.post("/v1/runs", async (c) => {
    let body: unknown;
    try {
      body = await c.req.json();
    } catch {
      return c.json({ error: "Invalid JSON body" }, 400);
    }
    try {
      const result = await startRun(body);
      return c.json(result, 202);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      return c.json({ error: message }, 400);
    }
  });

  app.get("/v1/runs/:runId", async (c) => {
    const runId = c.req.param("runId");
    const workDir = c.req.query("workDir");
    if (!workDir) {
      return c.json({ error: "workDir query param is required" }, 400);
    }
    try {
      const meta = await readMeta(workDir, runId);
      const report = await readReport(workDir, runId);
      return c.json({ ...meta, report });
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      return c.json({ error: message }, 404);
    }
  });

  return app;
}
