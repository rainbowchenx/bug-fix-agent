import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { createApp } from "../../src/http/app.js";

async function waitForCompleted(
  app: ReturnType<typeof createApp>,
  runId: string,
  workDir: string,
  timeoutMs = 5000,
): Promise<Record<string, unknown>> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const res = await app.request(
      `/v1/runs/${runId}?workDir=${encodeURIComponent(workDir)}`,
    );
    const body = (await res.json()) as { status?: string };
    if (body.status === "completed" || body.status === "failed") {
      return body as Record<string, unknown>;
    }
    await new Promise((r) => setTimeout(r, 20));
  }
  throw new Error("Timed out waiting for run completion");
}

describe("runs API", () => {
  let workDir: string;

  afterEach(async () => {
    if (workDir) await rm(workDir, { recursive: true, force: true });
  });

  it("POST /v1/runs then GET reaches completed with empty report", async () => {
    workDir = await mkdtemp(path.join(tmpdir(), "bugfix-api-"));
    const app = createApp();

    const health = await app.request("/health");
    expect(health.status).toBe(200);
    expect(await health.json()).toEqual({ ok: true });

    const create = await app.request("/v1/runs", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        workDir,
        defects: [
          {
            id: "d1",
            title: "sample crash",
            repoUrl: "https://gitlab.com/example/app.git",
          },
        ],
      }),
    });
    expect(create.status).toBe(202);
    const created = (await create.json()) as { runId: string };
    expect(created.runId).toBeTruthy();

    const final = await waitForCompleted(app, created.runId, workDir);
    expect(final.status).toBe("completed");
    const report = final.report as {
      summary: { fixed: number; unfixed: number; totalClusters: number };
    };
    expect(report.summary.fixed).toBe(0);
    expect(report.summary.totalClusters).toBe(1);
    expect(report.summary.unfixed).toBe(1);
  });
});
