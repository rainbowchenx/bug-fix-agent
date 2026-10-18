import { readFile } from "node:fs/promises";
import path from "node:path";
import type { CreateRunOptions, McpPolicy, McpServerConfig } from "../types.js";

export type McpServers = Record<string, McpServerConfig>;

const WRITE_TOOL_HINT =
  /(write|edit|delete|remove|create_file|update_file|put_|post_|patch_)/i;

export function expandEnvVars(
  value: string,
  env: NodeJS.ProcessEnv = process.env,
): string {
  return value.replace(/\$\{([A-Z0-9_]+)\}/gi, (_, key: string) => env[key] ?? "");
}

export function expandMcpServers(
  servers: McpServers,
  env: NodeJS.ProcessEnv = process.env,
): McpServers {
  const out: McpServers = {};
  for (const [name, cfg] of Object.entries(servers)) {
    out[name] = {
      ...cfg,
      command: cfg.command ? expandEnvVars(cfg.command, env) : cfg.command,
      url: cfg.url ? expandEnvVars(cfg.url, env) : cfg.url,
      args: cfg.args?.map((a) => expandEnvVars(a, env)),
      env: cfg.env
        ? Object.fromEntries(
            Object.entries(cfg.env).map(([k, v]) => [k, expandEnvVars(v, env)]),
          )
        : undefined,
    };
  }
  return out;
}

export async function loadWorkDirMcp(workDir: string): Promise<McpServers> {
  const file = path.join(workDir, ".bugfix", "mcp.json");
  try {
    const raw = await readFile(file, "utf8");
    const parsed = JSON.parse(raw) as { mcpServers?: McpServers } | McpServers;
    if (parsed && typeof parsed === "object" && "mcpServers" in parsed) {
      return (parsed.mcpServers as McpServers) ?? {};
    }
    return parsed as McpServers;
  } catch {
    return {};
  }
}

/** Run options override workDir file. */
export async function mergeMcpConfig(input: {
  workDir: string;
  runMcp?: McpServers;
  env?: NodeJS.ProcessEnv;
}): Promise<McpServers> {
  const fileCfg = await loadWorkDirMcp(input.workDir);
  const merged = { ...fileCfg, ...(input.runMcp ?? {}) };
  return expandMcpServers(merged, input.env ?? process.env);
}

/** Heuristic: deny write-like MCP tool names during analyze. */
export function defaultDeniedToolsForAnalyze(toolNames: string[]): string[] {
  return toolNames.filter((n) => WRITE_TOOL_HINT.test(n));
}

export interface NormalizedMcp {
  enabled: boolean;
  servers: McpServers;
  allowedTools: string[];
  deniedTools: string[];
  mode: "optional" | "required";
}

function isPolicy(mcp: object): mcp is McpPolicy {
  return (
    "servers" in mcp ||
    "allowedTools" in mcp ||
    "deniedTools" in mcp ||
    "mode" in mcp ||
    "enabled" in mcp
  );
}

export function normalizeMcpInput(mcp: CreateRunOptions["mcp"]): NormalizedMcp {
  if (!mcp) {
    return { enabled: true, servers: {}, allowedTools: [], deniedTools: [], mode: "optional" };
  }
  if (isPolicy(mcp)) {
    return {
      enabled: mcp.enabled !== false,
      servers: mcp.servers ?? {},
      allowedTools: mcp.allowedTools ?? [],
      deniedTools: mcp.deniedTools ?? [],
      mode: mcp.mode ?? "optional",
    };
  }
  return {
    enabled: true,
    servers: mcp,
    allowedTools: [],
    deniedTools: [],
    mode: "optional",
  };
}

const DEFAULT_STDIO_ALLOW = new Set([
  "node",
  "npx",
  "npm",
  "pnpm",
  "yarn",
  "python",
  "python3",
  "uv",
  "uvx",
  "docker",
]);

export class McpPolicyError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "McpPolicyError";
  }
}

/** Reject stdio commands whose basename is outside the allowlist. */
export function assertStdioAllowlist(
  servers: McpServers,
  allow: Set<string> = DEFAULT_STDIO_ALLOW,
): void {
  for (const [name, cfg] of Object.entries(servers)) {
    if (!cfg.command) continue;
    const bin = path
      .basename(cfg.command)
      .replace(/\.cmd$/i, "")
      .replace(/\.exe$/i, "");
    if (!allow.has(bin)) {
      throw new McpPolicyError(`MCP stdio command not allowlisted: ${name} (${bin})`);
    }
  }
}

export const ANALYZE_WRITE_DENY = ["Edit", "Write", "Bash", "create_file", "update_file", "delete_file"];
