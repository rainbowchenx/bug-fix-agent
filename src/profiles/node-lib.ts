import type { StackProfile } from "./types.js";

export const nodeLibProfile: StackProfile = {
  id: "node-lib",
  detect(ctx) {
    if (!ctx.packageJson) return 0;
    const deps = {
      ...(ctx.packageJson.dependencies as Record<string, string> | undefined),
      ...(ctx.packageJson.devDependencies as Record<string, string> | undefined),
    };
    let score = 1;
    if (deps.vue || deps.react || deps.electron || deps.vite) score -= 2;
    if (deps.vitest || deps.jest || deps.mocha) score += 1;
    return Math.max(0, score);
  },
  defaultInstall: ["npm install"],
  defaultTest: ["npm test"],
};
