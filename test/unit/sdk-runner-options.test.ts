import { describe, expect, it } from "vitest";
import { buildSdkOptions } from "../../src/agent/sdk-runner.js";

describe("buildSdkOptions", () => {
  it("analyze mode excludes Edit", () => {
    const opts = buildSdkOptions({
      cwd: "/tmp/repo",
      prompt: "analyze",
      mode: "analyze",
    });
    expect(opts.options.allowedTools).toContain("Read");
    expect(opts.options.allowedTools).toContain("Skill");
    expect(opts.options.allowedTools).not.toContain("Edit");
    expect(opts.options.permissionMode).toBeUndefined();
  });

  it("implement mode includes Edit and acceptEdits", () => {
    const opts = buildSdkOptions({
      cwd: "/tmp/repo",
      prompt: "fix",
      mode: "implement",
    });
    expect(opts.options.allowedTools).toContain("Edit");
    expect(opts.options.permissionMode).toBe("acceptEdits");
  });
});
