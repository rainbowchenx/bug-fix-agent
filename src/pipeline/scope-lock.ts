import type { SolutionArtifact } from "../agent/artifacts.js";

/** Normalize path for allowlist comparison (posix-ish, lower on win). */
export function normalizeRepoPath(p: string): string {
  return p.replace(/\\/g, "/").replace(/^\.\//, "").trim();
}

export function extractAllowedFiles(solution: SolutionArtifact): string[] {
  const fromField = solution.target_files ?? [];
  const fromSteps: string[] = [];
  for (const step of solution.steps) {
    const m = /`([^`]+\.[a-zA-Z0-9]+)`/.exec(step.description);
    if (m?.[1]) fromSteps.push(m[1]);
  }
  const all = [...fromField, ...fromSteps].map(normalizeRepoPath).filter(Boolean);
  return [...new Set(all)];
}

export interface ScopeLockResult {
  ok: boolean;
  allowed: string[];
  changed: string[];
  violations: string[];
}

/**
 * Scope lock: changed files must be within solution allowlist when allowlist is non-empty.
 * Empty allowlist → soft pass (prompt should still request target_files).
 */
export function checkScopeLock(
  changedFiles: string[],
  solution: SolutionArtifact,
): ScopeLockResult {
  const allowed = extractAllowedFiles(solution);
  const changed = changedFiles.map(normalizeRepoPath).filter(Boolean);
  if (!allowed.length || !changed.length) {
    return { ok: true, allowed, changed, violations: [] };
  }
  const allowSet = new Set(allowed.map((a) => a.toLowerCase()));
  const violations = changed.filter((c) => {
    const lower = c.toLowerCase();
    // allow if any allowed path is prefix or exact match
    for (const a of allowSet) {
      if (lower === a || lower.endsWith("/" + a) || lower.includes(a)) return false;
    }
    return true;
  });
  return { ok: violations.length === 0, allowed, changed, violations };
}
