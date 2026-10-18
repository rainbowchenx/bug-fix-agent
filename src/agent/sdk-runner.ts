import path from "node:path";
import { fileURLToPath } from "node:url";
import { loadConfig } from "../config.js";

export type AgentMode = "analyze" | "implement" | "review";

export interface RunAgentSessionInput {
  cwd: string;
  prompt: string;
  mode: AgentMode;
  maxTurns?: number;
  mcpServers?: Record<string, unknown>;
  skillsDir?: string;
  /** Skill ids to expose (after enabled/disabled filter). */
  skillIds?: string[];
  allowedExtraTools?: string[];
  disallowedTools?: string[];
  model?: string;
  timeoutMs?: number;
  /** Injected for tests — real SDK query is optional at runtime. */
  queryFn?: (options: SdkQueryOptions) => AsyncIterable<unknown>;
}

export interface SdkQueryOptions {
  prompt: string;
  options: {
    cwd: string;
    allowedTools: string[];
    permissionMode?: string;
    maxTurns: number;
    mcpServers?: Record<string, unknown>;
    disallowedTools?: string[];
    settingSources?: string[];
    env?: Record<string, string | undefined>;
    model?: string;
    plugins?: unknown[];
    skills?: string[];
  };
}

const ANALYZE_TOOLS = ["Read", "Glob", "Grep", "Skill"] as const;
const IMPLEMENT_TOOLS = ["Read", "Glob", "Grep", "Skill", "Edit", "Write"] as const;

export function buildSdkOptions(input: RunAgentSessionInput): SdkQueryOptions {
  const allowedTools =
    input.mode === "implement" ? [...IMPLEMENT_TOOLS] : [...ANALYZE_TOOLS];

  const options: SdkQueryOptions["options"] = {
    cwd: input.cwd,
    allowedTools,
    maxTurns: input.maxTurns ?? 30,
    settingSources: input.skillsDir ? ["project"] : [],
    env: {
      ANTHROPIC_API_KEY: process.env.ANTHROPIC_API_KEY,
      ANTHROPIC_BASE_URL: process.env.ANTHROPIC_BASE_URL,
      ANTHROPIC_MODEL: process.env.ANTHROPIC_MODEL,
      CI: "1",
      FORCE_COLOR: "0",
    },
  };

  if (input.mode === "implement") {
    options.permissionMode = "acceptEdits";
  }
  if (input.mcpServers) {
    options.mcpServers = input.mcpServers;
  }
  if (input.model) {
    options.model = input.model;
  }
  if (input.skillsDir) {
    options.plugins = [{ type: "local", path: input.skillsDir }];
  }
  if (input.skillIds?.length) {
    options.skills = input.skillIds;
  }
  if (input.disallowedTools?.length) {
    options.disallowedTools = input.disallowedTools;
  }

  return { prompt: input.prompt, options };
}

export function defaultSkillsDir(fromModuleUrl = import.meta.url): string {
  const here = path.dirname(fileURLToPath(fromModuleUrl));
  return path.resolve(here, "..", "..", "skills");
}

async function withTimeout<T>(promise: Promise<T>, ms: number, label: string): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    return await Promise.race([
      promise,
      new Promise<T>((_, reject) => {
        timer = setTimeout(
          () => reject(new Error(`${label} timed out after ${ms}ms`)),
          ms,
        );
      }),
    ]);
  } finally {
    if (timer) clearTimeout(timer);
  }
}

export async function runAgentSession(
  input: RunAgentSessionInput,
): Promise<{ text: string; options: SdkQueryOptions }> {
  const opts = buildSdkOptions(input);
  const timeoutMs = input.timeoutMs ?? loadConfig().sdkTimeoutMs;

  const run = async (): Promise<{ text: string; options: SdkQueryOptions }> => {
    if (input.queryFn) {
      const parts: string[] = [];
      for await (const msg of input.queryFn(opts)) {
        if (typeof msg === "string") parts.push(msg);
        else if (msg && typeof msg === "object" && "text" in msg) {
          parts.push(String((msg as { text: unknown }).text));
        }
      }
      return { text: parts.join("\n"), options: opts };
    }

    const { query } = await import("@anthropic-ai/claude-agent-sdk");
    const parts: string[] = [];
    for await (const message of query({
      prompt: opts.prompt,
      options: opts.options as never,
    })) {
      if (
        message &&
        typeof message === "object" &&
        "type" in message &&
        (message as { type: string }).type === "assistant"
      ) {
        const content = (message as { message?: { content?: unknown } }).message?.content;
        if (typeof content === "string") parts.push(content);
        else if (Array.isArray(content)) {
          for (const block of content) {
            if (block && typeof block === "object" && "text" in block) {
              parts.push(String((block as { text: unknown }).text));
            }
          }
        }
      }
    }
    return { text: parts.join("\n"), options: opts };
  };

  return withTimeout(run(), timeoutMs, "Agent SDK session");
}
