import { config as loadDotenv } from "dotenv";

export interface AppConfig {
  port: number;
  anthropicApiKey: string | undefined;
  anthropicBaseUrl: string | undefined;
  anthropicModel: string | undefined;
  gitlabToken: string | undefined;
  gitlabHost: string;
  maxIterate: number;
  defaultConcurrency: number;
}

function parsePort(raw: string | undefined, fallback: number): number {
  if (raw === undefined || raw === "") return fallback;
  const n = Number(raw);
  if (!Number.isFinite(n) || n <= 0 || n > 65535) {
    throw new Error(`Invalid PORT: ${raw}`);
  }
  return Math.floor(n);
}

function parsePositiveInt(raw: string | undefined, fallback: number): number {
  if (raw === undefined || raw === "") return fallback;
  const n = Number(raw);
  if (!Number.isFinite(n) || n < 1) {
    throw new Error(`Invalid positive integer: ${raw}`);
  }
  return Math.floor(n);
}

/** Load app config from process.env (optionally after dotenv). */
export function loadConfig(env: NodeJS.ProcessEnv = process.env): AppConfig {
  loadDotenv();
  return {
    port: parsePort(env.PORT, 8787),
    anthropicApiKey: env.ANTHROPIC_API_KEY || undefined,
    anthropicBaseUrl: env.ANTHROPIC_BASE_URL || undefined,
    anthropicModel: env.ANTHROPIC_MODEL || undefined,
    gitlabToken: env.GITLAB_TOKEN || undefined,
    gitlabHost: env.GITLAB_HOST || "https://gitlab.com",
    maxIterate: parsePositiveInt(env.BUGFIX_MAX_ITERATE, 3),
    defaultConcurrency: parsePositiveInt(env.BUGFIX_DEFAULT_CONCURRENCY, 1),
  };
}
