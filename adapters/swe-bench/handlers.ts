import { execFile as execFileCb } from "node:child_process";
import { mkdir, rm } from "node:fs/promises";
import path from "node:path";
import { promisify } from "node:util";
import type { ClusterHandlers } from "../../src/runs/runner.js";
import type { DeliverFixInput, DeliverFixResult } from "../../src/pipeline/deliver.js";
import { NoChangesError } from "../../src/pipeline/deliver.js";
import type { EnsureRepoInput, EnsureRepoResult, ExecFileFn } from "../../src/workspace/git.js";
import { cleanRepoUrl } from "../../src/workspace/git.js";
import { getDiffText, hasCodeChanges } from "../../src/workspace/diff.js";
import { repoPath, safeRepoDirName, worktreePath } from "../../src/workspace/paths.js";
import { appendPrediction } from "./predictions.js";
import type { SweInstance } from "./types.js";

const defaultExec = promisify(execFileCb) as ExecFileFn;

/**
 * Shared mirror cache filled by `eval/swe/prefetch-repos.py`.
 * When set, all instances of the same GitHub repo reuse one shallow mirror
 * instead of fetching mid-batch on flaky networks.
 */
function resolveMirrorPath(workDir: string, repoUrl: string): string {
  const cacheRoot = process.env.SWE_MIRROR_CACHE?.trim();
  if (cacheRoot) {
    return path.join(cacheRoot, safeRepoDirName(repoUrl));
  }
  return repoPath(workDir, repoUrl);
}

export interface SweHandlerContext {
  instance: SweInstance;
  predictionsPath: string;
  modelName: string;
  skipInstall?: boolean;
  execFileFn?: ExecFileFn;
}

async function gitDirExists(p: string, run: ExecFileFn): Promise<boolean> {
  try {
    await run("git", ["rev-parse", "--git-dir"], { cwd: p });
    return true;
  } catch {
    return false;
  }
}

/**
 * Checkout GitHub repo at instance.base_commit into the core worktree layout.
 * SWE-specific; core ensureRepo stays untouched.
 */
export function createSweEnsureRepo(ctx: SweHandlerContext) {
  return async (input: EnsureRepoInput): Promise<EnsureRepoResult> => {
    const run = ctx.execFileFn ?? input.execFileFn ?? defaultExec;
    const commit = ctx.instance.base_commit;
    const mirror = resolveMirrorPath(input.workDir, input.repoUrl);
    const wt = worktreePath(input.workDir, input.runId, input.clusterId);
    const clean = cleanRepoUrl(input.repoUrl);

    // Shallow fetch of the exact base_commit — full clone is too slow for SWE repos.
    if (!(await gitDirExists(mirror, run))) {
      await mkdir(mirror, { recursive: true });
      await run("git", ["init"], { cwd: mirror });
      await run("git", ["remote", "add", "origin", clean], { cwd: mirror });
    }

    await run("git", ["cat-file", "-e", `${commit}^{commit}`], { cwd: mirror }).catch(async () => {
      await run("git", ["fetch", "--depth", "1", "origin", commit], { cwd: mirror }).catch(
        async () => {
          // Some hosts need the full SHA as ref without depth limits falling back
          await run("git", ["fetch", "--depth", "1", "origin", `+${commit}:refs/swe/${commit}`], {
            cwd: mirror,
          });
        },
      );
    });

    if (await gitDirExists(wt, run)) {
      await run("git", ["reset", "--hard", commit], { cwd: wt });
      await run("git", ["clean", "-fdx"], { cwd: wt });
    } else {
      await rm(wt, { recursive: true, force: true }).catch(() => undefined);
      await mkdir(path.dirname(wt), { recursive: true });
      await run("git", ["worktree", "add", "--detach", wt, commit], { cwd: mirror });
    }

    return {
      repoPath: wt,
      mirrorPath: mirror,
      baseSha: commit,
      headSha: commit,
    };
  };
}

export function createSweDeliverFix(ctx: SweHandlerContext) {
  return async (input: DeliverFixInput): Promise<DeliverFixResult> => {
    const run = ctx.execFileFn ?? input.execFileFn;
    const baseSha = input.baseSha ?? ctx.instance.base_commit;
    const changed = await hasCodeChanges(input.repoPath, baseSha, run);
    if (!changed) throw new NoChangesError("SWE adapter: no diff vs base_commit");

    const patch = await getDiffText(input.repoPath, baseSha, run);
    if (!patch.trim()) throw new NoChangesError("SWE adapter: empty patch text");

    await appendPrediction(ctx.predictionsPath, {
      instance_id: ctx.instance.instance_id,
      model_name_or_path: ctx.modelName,
      model_patch: patch.endsWith("\n") ? patch : `${patch}\n`,
    });

    return {
      mrUrl: `swe-patch://${ctx.instance.instance_id}`,
      branch: `swe/${ctx.instance.instance_id}`.slice(0, 200),
    };
  };
}

function failToPassList(inst: SweInstance): string[] {
  const raw = inst.FAIL_TO_PASS;
  if (!raw) return [];
  if (Array.isArray(raw)) return raw.map(String);
  try {
    const p = JSON.parse(raw) as unknown;
    return Array.isArray(p) ? p.map(String) : [raw];
  } catch {
    return [raw];
  }
}

export function createSweHandlers(ctx: SweHandlerContext): ClusterHandlers {
  return {
    ensureRepo: createSweEnsureRepo(ctx),
    deliverFix: createSweDeliverFix(ctx),
    prepareRepo: ctx.skipInstall
      ? async () => ({ ok: true, logTail: "swe-adapter: skip install" })
      : async () => ({
          ok: true,
          logTail:
            "swe-adapter: install skipped by default (use host venv or Docker eval for deps)",
        }),
    resolveVerifyPlan: async ({ overrides }) => {
      const fail = failToPassList(ctx.instance);
      return {
        profileId: "unknown",
        install: overrides?.install ?? [],
        test:
          overrides?.test ??
          (fail.length
            ? [`python -m pytest -x ${fail.slice(0, 20).join(" ")}`]
            : ["python -m pytest -x"]),
      };
    },
  };
}
