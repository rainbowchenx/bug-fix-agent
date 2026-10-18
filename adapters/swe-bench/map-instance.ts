import type { CreateRunRequest, Defect } from "../../src/types.js";
import type { SweInstance } from "./types.js";

function asList(raw: string | string[] | undefined): string[] {
  if (!raw) return [];
  if (Array.isArray(raw)) return raw.map(String);
  try {
    const parsed = JSON.parse(raw) as unknown;
    if (Array.isArray(parsed)) return parsed.map(String);
  } catch {
    // plain string
  }
  return raw.trim() ? [raw.trim()] : [];
}

export function githubRepoUrl(repo: string): string {
  const cleaned = repo.replace(/\.git$/i, "").replace(/^https?:\/\/github\.com\//i, "");
  return `https://github.com/${cleaned}.git`;
}

/** Map one SWE instance to a core Defect — no SWE types leak into the runner. */
export function mapInstanceToDefect(inst: SweInstance): Defect {
  const failToPass = asList(inst.FAIL_TO_PASS);
  return {
    id: inst.instance_id,
    title: inst.instance_id,
    description: inst.problem_statement,
    repoUrl: githubRepoUrl(inst.repo),
    fingerprint: inst.instance_id,
    metadata: {
      source: "swe-bench",
      base_commit: inst.base_commit,
      fail_to_pass: failToPass,
      pass_to_pass: asList(inst.PASS_TO_PASS),
      version: inst.version,
    },
  };
}

export function mapInstanceToRequest(
  workDir: string,
  inst: SweInstance,
  opts?: {
    skipReviewer?: boolean;
    maxIterate?: number;
    engine?: "pipeline" | "langgraph";
    failToPassTests?: string[];
  },
): CreateRunRequest {
  const defect = mapInstanceToDefect(inst);
  const tests = opts?.failToPassTests ?? asList(inst.FAIL_TO_PASS);
  const testCmd = tests.length
    ? [`python -m pytest -x ${tests.map(shellQuote).join(" ")}`]
    : ["python -m pytest -x"];

  return {
    workDir,
    defects: [defect],
    userPrompt: [
      "SWE-bench evaluation mode: fix the issue described in the defect.",
      "Prefer minimal patch; do not commit or push.",
      tests.length ? `Focus tests: ${tests.slice(0, 8).join(", ")}` : "",
    ]
      .filter(Boolean)
      .join("\n"),
    options: {
      engine: opts?.engine,
      maxIterate: opts?.maxIterate ?? 3,
      skipReviewer: opts?.skipReviewer ?? true,
      verifyOverrides: {
        install: [],
        test: testCmd,
      },
    },
  };
}

function shellQuote(s: string): string {
  if (/^[A-Za-z0-9_./:-]+$/.test(s)) return s;
  return `"${s.replace(/"/g, '\\"')}"`;
}
