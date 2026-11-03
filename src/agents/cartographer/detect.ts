import { access, readdir, readFile } from "node:fs/promises";
import path from "node:path";
import type { CartographyProfile, RepoRoot } from "../../contracts/index.js";

async function exists(p: string): Promise<boolean> {
  try {
    await access(p);
    return true;
  } catch {
    return false;
  }
}

async function readJson(p: string): Promise<Record<string, unknown> | null> {
  try {
    return JSON.parse(await readFile(p, "utf8")) as Record<string, unknown>;
  } catch {
    return null;
  }
}

/** workDir itself + immediate child dirs that look like code roots. */
export async function discoverRepoRoots(workDir: string): Promise<RepoRoot[]> {
  const roots: RepoRoot[] = [];
  const selfPkg = path.join(workDir, "package.json");
  const selfGit = path.join(workDir, ".git");
  if ((await exists(selfPkg)) || (await exists(selfGit))) {
    roots.push({
      path: ".",
      gitHead: null,
      fingerprint: await fingerprintDir(workDir),
    });
  }

  let entries: string[] = [];
  try {
    entries = await readdir(workDir);
  } catch {
    return roots.length ? roots : [{ path: ".", gitHead: null, fingerprint: "empty" }];
  }

  for (const name of entries) {
    if (name.startsWith(".") || name === "node_modules" || name === "dist") continue;
    const child = path.join(workDir, name);
    if ((await exists(path.join(child, "package.json"))) || (await exists(path.join(child, ".git")))) {
      roots.push({
        path: name,
        gitHead: null,
        fingerprint: await fingerprintDir(child),
      });
    }
  }

  if (!roots.length) {
    roots.push({ path: ".", gitHead: null, fingerprint: await fingerprintDir(workDir) });
  }
  return roots;
}

async function fingerprintDir(dir: string): Promise<string> {
  const pkg = await readJson(path.join(dir, "package.json"));
  const name = typeof pkg?.name === "string" ? pkg.name : path.basename(dir);
  const ver = typeof pkg?.version === "string" ? pkg.version : "0";
  return `${name}@${ver}`;
}

export async function detectCartographyProfile(
  workDir: string,
  repoRoots: RepoRoot[],
): Promise<{ profile: CartographyProfile; secondaryHints: string[]; tech: { languages: string[]; frameworks: string[]; notes: string } }> {
  const frameworks = new Set<string>();
  const languages = new Set<string>(["typescript", "javascript"]);
  const hints: string[] = [];
  let profile: CartographyProfile = "unknown";

  for (const root of repoRoots) {
    const abs = path.join(workDir, root.path);
    const pkg = await readJson(path.join(abs, "package.json"));
    const deps = {
      ...(typeof pkg?.dependencies === "object" && pkg.dependencies ? pkg.dependencies : {}),
      ...(typeof pkg?.devDependencies === "object" && pkg.devDependencies ? pkg.devDependencies : {}),
    } as Record<string, string>;

    if (deps.electron || deps["electron-builder"] || deps["electron-vite"]) {
      profile = "electron_node";
      frameworks.add("electron");
      hints.push(`${root.path}:electron`);
    }
    if (deps["single-spa"] || deps["@single-spa/devtools"]) {
      if (profile === "unknown") profile = "micro_frontend";
      frameworks.add("single-spa");
      hints.push(`${root.path}:single-spa`);
    }
    if (deps.vue || deps["vue-router"]) frameworks.add("vue");
    if (deps.react || deps["react-dom"]) frameworks.add("react");
    if (deps["@nestjs/core"]) frameworks.add("nestjs");
  }

  // Weak device_web hint: bridge-ish folder names
  for (const root of repoRoots) {
    const abs = path.join(workDir, root.path);
    let names: string[] = [];
    try {
      names = await readdir(abs);
    } catch {
      continue;
    }
    if (names.some((n) => /bridge|jsbridge|device-web|webview/i.test(n))) {
      if (profile === "unknown") profile = "device_web";
      hints.push(`${root.path}:device-bridge-path`);
    }
  }

  return {
    profile,
    secondaryHints: hints,
    tech: {
      languages: [...languages],
      frameworks: [...frameworks],
      notes: profile === "unknown" ? "no strong cartography signal" : "",
    },
  };
}

export async function readConventions(workDir: string, repoRoots: RepoRoot[]): Promise<{
  fromClaudeMd: string[];
  fromRules: string[];
  boundSkills: string[];
  codeGraph: boolean;
  frameworkId: string;
  entries: { path: string; kind: "guide" | "skill" | "rule" | "unknown"; source: "claude_dir" | "repo_root" }[];
}> {
  const fromClaudeMd: string[] = [];
  const fromRules: string[] = [];
  const boundSkills: string[] = [];
  const entries: { path: string; kind: "guide" | "skill" | "rule" | "unknown"; source: "claude_dir" | "repo_root" }[] = [];
  let codeGraph = false;
  let frameworkId = "unknown";

  for (const root of repoRoots) {
    const abs = path.join(workDir, root.path);
    const claudePath = path.join(abs, "CLAUDE.md");
    if (await exists(claudePath)) {
      entries.push({ path: path.join(root.path, "CLAUDE.md"), kind: "guide", source: "repo_root" });
      try {
        const text = await readFile(claudePath, "utf8");
        const lines = text.split(/\r?\n/).filter((l) => l.trim()).slice(0, 40);
        fromClaudeMd.push(...lines.map((l) => l.replace(/^#+\s*/, "").slice(0, 200)));
        if (/codegraph|code.?graph/i.test(text)) codeGraph = true;
        if (/superpowers/i.test(text)) frameworkId = "superpowers";
        else if (/openspec/i.test(text)) frameworkId = "openspec";
        else if (/trellis/i.test(text)) frameworkId = "trellis";
      } catch {
        /* ignore */
      }
    }

    const skillsDir = path.join(abs, ".claude", "skills");
    if (await exists(skillsDir)) {
      try {
        for (const name of await readdir(skillsDir)) {
          boundSkills.push(name);
          entries.push({
            path: path.join(root.path, ".claude/skills", name),
            kind: "skill",
            source: "claude_dir",
          });
        }
      } catch {
        /* ignore */
      }
    }

    const rulesDir = path.join(abs, ".claude", "rules");
    if (await exists(rulesDir)) {
      try {
        for (const name of await readdir(rulesDir)) {
          fromRules.push(name);
          entries.push({
            path: path.join(root.path, ".claude/rules", name),
            kind: "rule",
            source: "claude_dir",
          });
        }
      } catch {
        /* ignore */
      }
    }
  }

  return { fromClaudeMd, fromRules, boundSkills, codeGraph, frameworkId, entries };
}
