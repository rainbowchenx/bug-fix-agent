import type { StackProfile } from "./types.js";

export const electronProfile: StackProfile = {
  id: "electron",
  detect(ctx) {
    const deps = {
      ...(ctx.packageJson?.dependencies as Record<string, string> | undefined),
      ...(ctx.packageJson?.devDependencies as Record<string, string> | undefined),
    };
    let score = 0;
    if (deps.electron) score += 5;
    if (ctx.files.has("electron-builder.yml") || ctx.files.has("electron.vite.config.ts")) {
      score += 2;
    }
    return score;
  },
  defaultInstall: ["npm install"],
  defaultTest: ["npm test"],
};
