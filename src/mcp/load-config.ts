import { readFile } from "node:fs/promises";
import path from "node:path";
import type { McpServerConfig } from "../types.js";

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
