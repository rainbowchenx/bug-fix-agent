export type ProfileId = "node-web" | "node-lib" | "electron" | "unknown";

export interface VerifyPlan {
  profileId: ProfileId;
  install: string[];
  test: string[];
}

export interface StackProfile {
  id: ProfileId;
  detect: (ctx: ProfileDetectContext) => number;
  defaultInstall: string[];
  defaultTest: string[];
}

export interface ProfileDetectContext {
  packageJson: Record<string, unknown> | null;
  files: Set<string>;
}
