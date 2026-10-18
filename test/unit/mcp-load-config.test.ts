import { mkdtemp, mkdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import {
  McpPolicyError,
  assertStdioAllowlist,
  defaultDeniedToolsForAnalyze,
  expandEnvVars,
  mergeMcpConfig,
  normalizeMcpInput,
} from "../../src/mcp/load-config.js";

describe("mcp load-config", () => {
  let workDir: string;

  afterEach(async () => {
    if (workDir) await rm(workDir, { recursive: true, force: true });
  });

  it("expands ${ENV} placeholders", () => {
    expect(expandEnvVars("token=${MY_TOKEN}", { MY_TOKEN: "abc" })).toBe("token=abc");
  });

  it("merges run options over workDir mcp.json", async () => {
    workDir = await mkdtemp(path.join(tmpdir(), "bugfix-mcp-"));
    await mkdir(path.join(workDir, ".bugfix"), { recursive: true });
    await writeFile(
      path.join(workDir, ".bugfix", "mcp.json"),
      JSON.stringify({
        mcpServers: {
          docs: { url: "http://localhost:9", env: { T: "${T}" } },
          stale: { command: "npx", args: ["old"] },
        },
      }),
    );

    const merged = await mergeMcpConfig({
      workDir,
      runMcp: {
        stale: { command: "npx", args: ["new"] },
      },
      env: { T: "xyz" },
    });

    expect(merged.docs?.env?.T).toBe("xyz");
    expect(merged.stale?.args).toEqual(["new"]);
  });

  it("normalizes policy shape and denies write-like tools", () => {
    const policy = normalizeMcpInput({
      enabled: true,
      mode: "required",
      servers: { fs: { command: "npx", args: ["server"] } },
      allowedTools: ["read_file", "write_file"],
      deniedTools: ["rm"],
    });
    expect(policy.mode).toBe("required");
    expect(defaultDeniedToolsForAnalyze(policy.allowedTools)).toEqual(["write_file"]);
    expect(() =>
      assertStdioAllowlist({ evil: { command: "bash", args: ["-c", "x"] } }),
    ).toThrow(McpPolicyError);
    expect(() => assertStdioAllowlist(policy.servers)).not.toThrow();
  });
});
