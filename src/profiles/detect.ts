import { readFile, readdir } from "node:fs/promises";
import path from "node:path";
import { electronProfile } from "./electron.js";
import { nodeLibProfile } from "./node-lib.js";
import { nodeWebProfile } from "./node-web.js";
import type { ProfileDetectContext, ProfileId, StackProfile, VerifyPlan } from "./types.js";

const PROFILES: StackProfile[] = [electronProfile, nodeWebProfile, nodeLibProfile];

async function readPackageJson(repoPath: string): Promise<Record<string, unknown> | null> {
  try {
    const raw = await readFile(path.join(repoPath, "package.json"), "utf8");
    return JSON.parse(raw) as Record<string, unknown>;
  } catch {
    return null;
  }
}

async function listTopFiles(repoPath: string): Promise<Set<string>> {
  try {
    const entries = await readdir(repoPath);
    return new Set(entries);
  } catch {
    return new Set();
  }
}

export async function buildDetectContext(repoPath: string): Promise<ProfileDetectContext> {
  return {
    packageJson: await readPackageJson(repoPath),
    files: await listTopFiles(repoPath),
  };
}

export function detectProfileFromContext(ctx: ProfileDetectContext): ProfileId {
  let best: { id: ProfileId; score: number } = { id: "unknown", score: 0 };
  for (const p of PROFILES) {
    const score = p.detect(ctx);
    if (score > best.score) best = { id: p.id, score };
  }
  return best.id;
}

export async function detectProfile(repoPath: string): Promise<ProfileId> {
  return detectProfileFromContext(await buildDetectContext(repoPath));
}

function profileById(id: ProfileId): StackProfile | undefined {
  return PROFILES.find((p) => p.id === id);
}

function scriptsFromPackage(pkg: Record<string, unknown> | null): {
  install: string[];
  test: string[];
} {
  const scripts = (pkg?.scripts ?? {}) as Record<string, string>;
  const test: string[] = [];
  if (scripts.test) test.push("npm test");
  else if (scripts["test:unit"]) test.push("npm run test:unit");
  else if (scripts.vitest) test.push("npm run vitest");

  return {
    install: ["npm install"],
    test,
  };
}

function parsePromptOverrides(userPrompt?: string): { install?: string[]; test?: string[] } {
  if (!userPrompt) return {};
  const installMatch = /install:\s*`([^`]+)`/i.exec(userPrompt);
  const testMatch = /(?:test|verify):\s*`([^`]+)`/i.exec(userPrompt);
  return {
    install: installMatch?.[1] ? [installMatch[1]] : undefined,
    test: testMatch?.[1] ? [testMatch[1]] : undefined,
  };
}

export interface ResolveVerifyPlanInput {
  repoPath: string;
  userPrompt?: string;
  overrides?: { install?: string[]; test?: string[] };
}

export async function resolveVerifyPlan(input: ResolveVerifyPlanInput): Promise<VerifyPlan> {
  const ctx = await buildDetectContext(input.repoPath);
  const profileId = detectProfileFromContext(ctx);
  const profile = profileById(profileId);
  const fromPkg = scriptsFromPackage(ctx.packageJson);
  const fromPrompt = parsePromptOverrides(input.userPrompt);

  const install =
    input.overrides?.install ??
    fromPrompt.install ??
    (fromPkg.install.length ? fromPkg.install : profile?.defaultInstall ?? ["npm install"]);

  const test =
    input.overrides?.test ??
    fromPrompt.test ??
    (fromPkg.test.length ? fromPkg.test : profile?.defaultTest ?? []);

  return { profileId, install, test };
}
