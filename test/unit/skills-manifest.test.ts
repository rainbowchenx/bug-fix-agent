import { describe, expect, it } from "vitest";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { filterSkills, filterSkillsForProfile, listBuiltinSkills } from "../../src/skills/manifest.js";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const skillsDir = path.join(repoRoot, "skills");

describe("skills manifest", () => {
  it("lists at least 6 builtin skills", async () => {
    const skills = await listBuiltinSkills(skillsDir);
    expect(skills.length).toBeGreaterThanOrEqual(10);
    expect(skills.some((s) => s.id === "verify-green-gate")).toBe(true);
  });

  it("respects disabled filter", async () => {
    const skills = await listBuiltinSkills(skillsDir);
    const filtered = filterSkills(skills, { disabled: ["vue-debug"] });
    expect(filtered.every((s) => s.id !== "vue-debug")).toBe(true);
  });

  it("hides profile-specific skills", async () => {
    const skills = await listBuiltinSkills(skillsDir);
    const lib = filterSkillsForProfile(skills, "node-lib");
    expect(lib.some((s) => s.id === "vue-debug")).toBe(false);
    expect(lib.some((s) => s.id === "electron-process-boundary")).toBe(false);
    expect(filterSkillsForProfile(skills, "electron").some((s) => s.id === "electron-process-boundary")).toBe(
      true,
    );
  });
});
