import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import {
  createRunDir,
  readMeta,
  readReport,
  updateRunMeta,
  writeInputDefects,
  writeReport,
} from "../../src/runs/store.js";

describe("run store", () => {
  let workDir: string;

  afterEach(async () => {
    if (workDir) await rm(workDir, { recursive: true, force: true });
  });

  it("creates run dir and persists input + report", async () => {
    workDir = await mkdtemp(path.join(tmpdir(), "bugfix-run-"));
    const { runId, dir } = await createRunDir(workDir);
    expect(dir).toContain(runId);

    await writeInputDefects(workDir, runId, [
      {
        id: "d1",
        title: "crash",
        repoUrl: "https://gitlab.com/a/b.git",
      },
    ]);

    await updateRunMeta(workDir, runId, {
      status: "running",
      progress: { phase: "aggregate", totalClusters: 1 },
    });

    const meta = await readMeta(workDir, runId);
    expect(meta.status).toBe("running");
    expect(meta.progress?.phase).toBe("aggregate");

    await writeReport(workDir, runId, {
      runId,
      summary: { totalClusters: 0, fixed: 0, unfixed: 0 },
      fixed: [],
      unfixed: [],
    });

    const report = await readReport(workDir, runId);
    expect(report?.runId).toBe(runId);
    expect(report?.summary.fixed).toBe(0);
  });
});
