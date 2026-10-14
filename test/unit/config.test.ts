import { afterEach, describe, expect, it } from "vitest";
import { loadConfig } from "../../src/config.js";

describe("loadConfig", () => {
  const original = { ...process.env };

  afterEach(() => {
    process.env = { ...original };
  });

  it("defaults PORT to 8787 when unset", () => {
    delete process.env.PORT;
    const cfg = loadConfig(process.env);
    expect(cfg.port).toBe(8787);
  });

  it("reads PORT from env", () => {
    process.env.PORT = "9000";
    const cfg = loadConfig(process.env);
    expect(cfg.port).toBe(9000);
  });

  it("defaults gitlabHost", () => {
    delete process.env.GITLAB_HOST;
    const cfg = loadConfig(process.env);
    expect(cfg.gitlabHost).toBe("https://gitlab.com");
  });

  it("defaults maxIterate to 3", () => {
    delete process.env.BUGFIX_MAX_ITERATE;
    const cfg = loadConfig(process.env);
    expect(cfg.maxIterate).toBe(3);
  });
});
