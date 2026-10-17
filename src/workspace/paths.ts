import path from "node:path";

export function runsRoot(workDir: string): string {
  return path.join(workDir, ".bugfix-runs");
}

export function runDir(workDir: string, runId: string): string {
  return path.join(runsRoot(workDir), runId);
}

export function clusterDir(workDir: string, runId: string, clusterId: string): string {
  return path.join(runDir(workDir, runId), "clusters", clusterId);
}

export function reposRoot(workDir: string): string {
  return path.join(workDir, "repos");
}

export function worktreesRoot(workDir: string): string {
  return path.join(workDir, "worktrees");
}

export function safeRepoDirName(repoUrl: string): string {
  const cleaned = repoUrl
    .replace(/\.git$/i, "")
    .replace(/^https?:\/\//i, "")
    .replace(/^git@[^:]+:/i, "")
    .replace(/[^a-zA-Z0-9._-]+/g, "_")
    .replace(/_+/g, "_")
    .replace(/^_|_$/g, "");
  return cleaned.slice(0, 120) || "repo";
}

export function repoPath(workDir: string, repoUrl: string): string {
  return path.join(reposRoot(workDir), safeRepoDirName(repoUrl));
}

export function worktreePath(
  workDir: string,
  runId: string,
  clusterId: string,
): string {
  const safeCluster = clusterId.replace(/[^a-zA-Z0-9._-]+/g, "_").slice(0, 64);
  return path.join(worktreesRoot(workDir), runId, safeCluster);
}
