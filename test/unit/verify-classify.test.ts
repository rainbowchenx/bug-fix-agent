import { describe, expect, it } from "vitest";
import {
  classifyVerifyFailure,
  reasonCodeForClassify,
} from "../../src/pipeline/verify-classify.js";

describe("classifyVerifyFailure", () => {
  it("classifies missing module as environment and stops iterate", () => {
    const c = classifyVerifyFailure("Error: Cannot find module 'foo'\n    at Object.<anonymous>");
    expect(c.kind).toBe("environment");
    expect(c.stopIterate).toBe(true);
    expect(reasonCodeForClassify(c.kind)).toBe("env_verify_failed");
  });

  it("classifies npm ERR! as environment", () => {
    const c = classifyVerifyFailure("npm ERR! code ELIFECYCLE\nnpm ERR! errno 1");
    expect(c.kind).toBe("environment");
    expect(c.stopIterate).toBe(true);
  });

  it("classifies AssertionError as product_code (iterable)", () => {
    const c = classifyVerifyFailure(
      "FAIL src/login.test.ts\nAssertionError: expected true to be false\n    at src/login.ts:42",
    );
    expect(c.kind).toBe("product_code");
    expect(c.stopIterate).toBe(false);
  });

  it("classifies test-file-heavy assertion as bad_assertion", () => {
    const c = classifyVerifyFailure(`
AssertionError: expected 1 to equal 2
    at Object.<anonymous> (tests/unit/foo.test.ts:10:5)
    at Object.<anonymous> (tests/unit/foo.test.ts:12:5)
`);
    expect(c.kind).toBe("bad_assertion");
    expect(c.stopIterate).toBe(true);
  });

  it("classifies timeout as flaky", () => {
    const c = classifyVerifyFailure("Error: Timeout of 5000ms exceeded");
    expect(c.kind).toBe("flaky");
    expect(c.stopIterate).toBe(true);
  });

  it("classifies /bin/sh python: not found as environment", () => {
    const c = classifyVerifyFailure(
      "/bin/sh: 1: python: not found\n\nCommand failed: python -m pytest -x",
    );
    expect(c.kind).toBe("environment");
    expect(c.stopIterate).toBe(true);
    expect(c.reason).toMatch(/not found/i);
  });

  it("classifies ModuleNotFoundError as environment", () => {
    const c = classifyVerifyFailure("ModuleNotFoundError: No module named 'pytest'");
    expect(c.kind).toBe("environment");
    expect(c.stopIterate).toBe(true);
  });
});
