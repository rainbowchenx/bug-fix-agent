import type { StackProfile } from "./types.js";

export const nodeWebProfile: StackProfile = {
  id: "node-web",
  detect(ctx) {
    const deps = {
      ...(ctx.packageJson?.dependencies as Record<string, string> | undefined),
      ...(ctx.packageJson?.devDependencies as Record<string, string> | undefined),
    };
    let score = 0;
    if (deps.vue || deps.react || deps.vite || deps.webpack) score += 3;
    if (ctx.files.has("vite.config.ts") || ctx.files.has("vite.config.js")) score += 2;
    if (ctx.files.has("vue.config.js")) score += 2;
    return score;
  },
  defaultInstall: ["npm install"],
  defaultTest: ["npm test"],
};
