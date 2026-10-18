import { cp, mkdir, readdir, readFile, rm } from "node:fs/promises";
import path from "node:path";
import { defaultSkillsDir } from "../agent/sdk-runner.js";

export interface SkillMeta {
  id: string;
  name: string;
  description: string;
  dir: string;
  profiles?: string[];
}

function parseFrontmatter(md: string): { name?: string; description?: string; profiles?: string[] } {
  if (!md.startsWith("---")) return {};
  const end = md.indexOf("---", 3);
  if (end < 0) return {};
  const block = md.slice(3, end);
  const out: { name?: string; description?: string; profiles?: string[] } = {};
  for (const line of block.split("\n")) {
    const m = /^(\w+):\s*(.*)$/.exec(line.trim());
    if (!m) continue;
    if (m[1] === "name") out.name = m[2]?.trim();
    if (m[1] === "description") out.description = m[2]?.trim();
    if (m[1] === "profiles") {
      out.profiles = m[2]
        ?.split(",")
        .map((s) => s.trim())
        .filter(Boolean);
    }
  }
  return out;
}

export async function listBuiltinSkills(
  skillsDir: string = defaultSkillsDir(),
): Promise<SkillMeta[]> {
  let entries: string[];
  try {
    entries = await readdir(skillsDir);
  } catch {
    return [];
  }
  const skills: SkillMeta[] = [];
  for (const id of entries) {
    if (id.startsWith(".") || id === "skills") continue;
    const dir = path.join(skillsDir, id);
    const skillMd = path.join(dir, "SKILL.md");
    try {
      const md = await readFile(skillMd, "utf8");
      const fm = parseFrontmatter(md);
      skills.push({
        id,
        name: fm.name ?? id,
        description: fm.description ?? "",
        dir,
        profiles: fm.profiles,
      });
    } catch {
      // skip non-skill dirs
    }
  }
  return skills.sort((a, b) => a.id.localeCompare(b.id));
}

export function filterSkills(
  skills: SkillMeta[],
  opts?: { enabled?: string[]; disabled?: string[] },
): SkillMeta[] {
  let list = skills;
  if (opts?.enabled?.length) {
    const allow = new Set(opts.enabled);
    list = list.filter((s) => allow.has(s.id));
  }
  if (opts?.disabled?.length) {
    const deny = new Set(opts.disabled);
    list = list.filter((s) => !deny.has(s.id));
  }
  return list;
}

/** Skills with no profiles list apply everywhere; others must list the profile. */
export function filterSkillsForProfile(skills: SkillMeta[], profileId: string): SkillMeta[] {
  return skills.filter((s) => !s.profiles?.length || s.profiles.includes(profileId));
}

/** Copy selected skills into worktree `.claude/skills` for settingSources:project. */
export async function mountSkillsIntoCwd(
  cwd: string,
  skills: SkillMeta[],
): Promise<void> {
  const targetRoot = path.join(cwd, ".claude", "skills");
  await rm(targetRoot, { recursive: true, force: true });
  await mkdir(targetRoot, { recursive: true });
  for (const s of skills) {
    const dest = path.join(targetRoot, s.id);
    await cp(s.dir, dest, { recursive: true });
  }
}
