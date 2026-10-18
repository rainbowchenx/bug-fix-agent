import { readdir, readFile } from "node:fs/promises";
import path from "node:path";

const SKIP_DIRS = new Set([
  "node_modules",
  ".git",
  "dist",
  "build",
  "coverage",
  ".bugfix-runs",
  "worktrees",
]);

export interface RepoMap {
  files: string[];
  exports: { file: string; symbols: string[] }[];
}

const cache = new Map<string, RepoMap>();

async function walk(dir: string, root: string, out: string[], maxFiles: number): Promise<void> {
  if (out.length >= maxFiles) return;
  let entries;
  try {
    entries = await readdir(dir, { withFileTypes: true });
  } catch {
    return;
  }
  for (const ent of entries) {
    if (out.length >= maxFiles) return;
    if (ent.name.startsWith(".")) continue;
    const abs = path.join(dir, ent.name);
    if (ent.isDirectory()) {
      if (SKIP_DIRS.has(ent.name)) continue;
      await walk(abs, root, out, maxFiles);
    } else if (/\.(ts|tsx|js|jsx|vue|mjs|cjs)$/.test(ent.name)) {
      out.push(path.relative(root, abs).replace(/\\/g, "/"));
    }
  }
}

function exportSymbols(source: string): string[] {
  const names = new Set<string>();
  const re =
    /export\s+(?:async\s+)?(?:function|class|const|let|var|interface|type|enum)\s+([A-Za-z0-9_]+)/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(source))) {
    if (m[1]) names.add(m[1]);
  }
  return [...names].slice(0, 12);
}

/** Lightweight file tree + exported symbols, cached per repo path. */
export async function buildRepoMap(repoPath: string, maxFiles = 80): Promise<RepoMap> {
  const hit = cache.get(repoPath);
  if (hit) return hit;
  const files: string[] = [];
  await walk(repoPath, repoPath, files, maxFiles);
  files.sort();
  const exports: RepoMap["exports"] = [];
  for (const file of files.slice(0, 40)) {
    try {
      const src = await readFile(path.join(repoPath, file), "utf8");
      const symbols = exportSymbols(src);
      if (symbols.length) exports.push({ file, symbols });
    } catch {
      // unreadable
    }
  }
  const map = { files, exports };
  cache.set(repoPath, map);
  return map;
}

export function formatRepoMap(map: RepoMap, maxChars = 4000): string {
  const lines = ["Files:", ...map.files.slice(0, 60).map((f) => `- ${f}`)];
  if (map.exports.length) {
    lines.push("", "Exports:");
    for (const e of map.exports.slice(0, 30)) {
      lines.push(`- ${e.file}: ${e.symbols.join(", ")}`);
    }
  }
  const text = lines.join("\n");
  return text.length <= maxChars ? text : text.slice(0, maxChars) + "\n...";
}
