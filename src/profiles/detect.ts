import { access, readFile, readdir } from "node:fs/promises";
import path from "node:path";
import { electronProfile } from "./electron.js";
import { nodeLibProfile } from "./node-lib.js";
import { nodeWebProfile } from "./node-web.js";
import type { ProfileDetectContext, ProfileId, StackProfile, VerifyPlan } from "./types.js";

const PROFILES: StackProfile[] = [electronProfile, nodeWebProfile, nodeLibProfile];

export type PackageManager = "npm" | "pnpm" | "yarn";

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

async function fileExists(p: string): Promise<boolean> {
  try {
    await access(p);
    return true;
  } catch {
    return false;
  }
}

export async function detectPackageManager(repoPath: string): Promise<PackageManager> {
  const pkg = await readPackageJson(repoPath);
  const pmField = typeof pkg?.packageManager === "string" ? pkg.packageManager : "";
  if (pmField.startsWith("pnpm@")) return "pnpm";
  if (pmField.startsWith("yarn@")) return "yarn";
  if (pmField.startsWith("npm@")) return "npm";

  if (await fileExists(path.join(repoPath, "pnpm-lock.yaml"))) return "pnpm";
  if (await fileExists(path.join(repoPath, "yarn.lock"))) return "yarn";
  return "npm";
}

export function installCommandFor(pm: PackageManager, hasLockfile: boolean): string {
  if (pm === "pnpm") return "pnpm install --frozen-lockfile";
  if (pm === "yarn") return "yarn install --frozen-lockfile";
  return hasLockfile ? "npm ci" : "npm install";
}

export function testCommandFor(pm: PackageManager, scriptName: string): string {
  if (pm === "pnpm") return `pnpm run ${scriptName}`;
  if (pm === "yarn") return `yarn ${scriptName}`;
  return scriptName === "test" ? "npm test" : `npm run ${scriptName}`;
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

function scriptsFromPackage(
  pkg: Record<string, unknown> | null,
  pm: PackageManager,
  files: Set<string>,
): { install: string[]; test: string[] } {
  const scripts = (pkg?.scripts ?? {}) as Record<string, string>;
  const hasLock =
    (pm === "npm" && files.has("package-lock.json")) ||
    (pm === "pnpm" && files.has("pnpm-lock.yaml")) ||
    (pm === "yarn" && files.has("yarn.lock"));

  const test: string[] = [];
  if (scripts.test) test.push(testCommandFor(pm, "test"));
  else if (scripts["test:unit"]) test.push(testCommandFor(pm, "test:unit"));
  else if (scripts.vitest) test.push(testCommandFor(pm, "vitest"));

  return {
    install: [installCommandFor(pm, hasLock)],
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

/** Minimal workspace package pick from userPrompt `package: name` or first workspace. */
async function resolveWorkspaceCwd(
  repoPath: string,
  pkg: Record<string, unknown> | null,
  userPrompt?: string,
): Promise<string | undefined> {
  const promptPkg = userPrompt ? /package:\s*`?([^\s`]+)`?/i.exec(userPrompt)?.[1] : undefined;
  const workspaces = pkg?.workspaces;
  let patterns: string[] = [];
  if (Array.isArray(workspaces)) patterns = workspaces.map(String);
  else if (workspaces && typeof workspaces === "object" && Array.isArray((workspaces as { packages?: string[] }).packages)) {
    patterns = (workspaces as { packages: string[] }).packages;
  }
  const hasPnpmWs = await fileExists(path.join(repoPath, "pnpm-workspace.yaml"));
  if (!patterns.length && !hasPnpmWs && !promptPkg) return undefined;
  if (promptPkg) {
    const candidate = path.join(repoPath, promptPkg);
    if (await fileExists(path.join(candidate, "package.json"))) return candidate;
  }
  return undefined;
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
  const pm = await detectPackageManager(input.repoPath);
  const fromPkg = scriptsFromPackage(ctx.packageJson, pm, ctx.files);
  const fromPrompt = parsePromptOverrides(input.userPrompt);
  await resolveWorkspaceCwd(input.repoPath, ctx.packageJson, input.userPrompt);

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
