export type VerifyFailureKind =
  | "product_code"
  | "environment"
  | "bad_assertion"
  | "flaky"
  | "unknown";

export interface VerifyClassification {
  kind: VerifyFailureKind;
  reason: string;
  /** When true, runner should stop iterating and unfixed immediately. */
  stopIterate: boolean;
}

const ENV_PATTERNS: { re: RegExp; label: string }[] = [
  { re: /\bENOENT\b/i, label: "ENOENT" },
  { re: /\bEACCES\b/i, label: "EACCES" },
  { re: /npm ERR!/i, label: "npm ERR!" },
  { re: /ELIFECYCLE/i, label: "ELIFECYCLE" },
  { re: /Cannot find module/i, label: "Cannot find module" },
  { re: /command not found/i, label: "command not found" },
  { re: /ECONNREFUSED/i, label: "ECONNREFUSED" },
  { re: /ENOTFOUND/i, label: "ENOTFOUND" },
  { re: /No such file or directory/i, label: "missing file/dir" },
  { re: /spawn\s+\S+\s+ENOENT/i, label: "spawn ENOENT" },
  { re: /JavaScript heap out of memory/i, label: "OOM" },
];

const FLAKY_PATTERNS: { re: RegExp; label: string }[] = [
  { re: /\bflaky\b/i, label: "flaky marker" },
  { re: /timed?\s*out/i, label: "timeout" },
  { re: /ETIMEDOUT/i, label: "ETIMEDOUT" },
];

const PRODUCT_PATTERNS: RegExp[] = [
  /AssertionError/i,
  /\bexpect\s*\(/i,
  /\bFAILED\b/,
  /\bfail(ing|ed)\b/i,
  /TypeError:/i,
  /ReferenceError:/i,
];

/**
 * Heuristic Smart Routing for verify failures.
 * environment / bad_assertion / flaky → stop iterate; product_code / unknown → may iterate.
 */
export function classifyVerifyFailure(
  logTail: string,
  command = "",
): VerifyClassification {
  const text = `${command}\n${logTail}`;

  for (const p of ENV_PATTERNS) {
    if (p.re.test(text)) {
      return {
        kind: "environment",
        reason: `Environment/setup failure (${p.label}); not a product-code iterate candidate.`,
        stopIterate: true,
      };
    }
  }

  for (const p of FLAKY_PATTERNS) {
    if (p.re.test(text)) {
      return {
        kind: "flaky",
        reason: `Likely flaky/unstable verify (${p.label}); stopping iterate.`,
        stopIterate: true,
      };
    }
  }

  // Assertion mismatch with stack predominantly in *.test.* → bad_assertion
  const hasExpectMismatch =
    /expected\b.+\breceived\b/i.test(text) ||
    /AssertionError/i.test(text) ||
    /Expected:.+Received:/is.test(text);
  if (hasExpectMismatch) {
    const testStackHits = (text.match(/\b[\w./-]+\.(test|spec)\.[jt]sx?:\d+/gi) ?? []).length;
    const srcStackHits = (text.match(/\bsrc\/[\w./-]+\.[jt]sx?:\d+/gi) ?? []).length;
    if (testStackHits > 0 && testStackHits >= srcStackHits && !/\bsrc\//i.test(text.split("AssertionError")[0] ?? "")) {
      // Prefer bad_assertion when failure frames are mostly in test files
      const frames = text.match(/at\s+.+\(([^)]+)\)/g) ?? [];
      const testFrames = frames.filter((f) => /\.(test|spec)\.[jt]sx?/i.test(f)).length;
      const prodFrames = frames.filter(
        (f) => !/\.(test|spec)\.[jt]sx?/i.test(f) && /src\//i.test(f),
      ).length;
      if (testFrames > prodFrames) {
        return {
          kind: "bad_assertion",
          reason:
            "Failure frames concentrate in test/spec files; treat as bad_assertion (do not burn product iterate).",
          stopIterate: true,
        };
      }
    }
  }

  for (const re of PRODUCT_PATTERNS) {
    if (re.test(text)) {
      return {
        kind: "product_code",
        reason: "Looks like product/test assertion failure; eligible for implement iterate.",
        stopIterate: false,
      };
    }
  }

  return {
    kind: "unknown",
    reason: "Unrecognized verify failure; allow limited iterate.",
    stopIterate: false,
  };
}

export function reasonCodeForClassify(
  kind: VerifyFailureKind,
): "env_verify_failed" | "verify_failed" {
  if (kind === "environment" || kind === "flaky") return "env_verify_failed";
  return "verify_failed";
}
