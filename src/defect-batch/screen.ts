import { classifyExpectQuality } from "./expect-quality.js";
import {
  isExcludedStatus,
  isOpenLike,
  isSecurityTitle,
  matchDesignUndefined,
  matchNotCode,
  matchRuntimeAttach,
  matchScaCve,
  matchVague,
  SCANNER_RE,
} from "./rules.js";
import type { DefectDigest, ScreenedTicket, ScreenProfile } from "./types.js";

export interface ScreenOptions {
  posture?: "alpha" | "beta";
  profile?: ScreenProfile;
}

/**
 * R0–R3 funnel (rules only). Maps stage1 C* rules into screen-cluster pools.
 */
export function screenDigest(d: DefectDigest, opts: ScreenOptions = {}): ScreenedTicket {
  const profile = opts.profile ?? {};
  const expectQuality = classifyExpectQuality(d);
  const ruleIds: string[] = [];

  // R1 — excluded
  if (isExcludedStatus(d.status)) {
    return ticket(d, "excluded", "EXCLUDED", expectQuality, ruleIds, "R1", "Cancel / Not a bug / void");
  }

  // R1 — security bypass（标题 [安全] 或扫描器语料）
  if (isSecurityTitle(d.title) || SCANNER_RE.test(d.fullText)) {
    return ticket(d, "security", "SECURITY", expectQuality, ruleIds, "R1", "security / SCA bypass");
  }

  // β posture: only Open/New stay in functional funnel
  if (opts.posture === "beta" && d.status && !isOpenLike(d.status)) {
    return ticket(d, "excluded", "EXCLUDED", expectQuality, ruleIds, "R1:beta", "beta posture skips non-Open/New");
  }

  // R2 — hard reject
  const sca = matchScaCve(d, profile);
  if (sca) {
    ruleIds.push(sca.id);
    return ticket(d, "hard_reject", "UNFIXABLE", expectQuality, ruleIds, sca.id, sca.detail);
  }
  const notcode = matchNotCode(d, profile);
  if (notcode) {
    ruleIds.push(notcode.id);
    return ticket(d, "hard_reject", "UNFIXABLE", expectQuality, ruleIds, notcode.id, notcode.detail);
  }

  // R3a — needs_info
  const design = matchDesignUndefined(d);
  if (design) {
    ruleIds.push(design.id);
    return ticket(d, "needs_info", "UNFIXABLE", expectQuality, ruleIds, design.id, design.detail);
  }
  const runtime = matchRuntimeAttach(d);
  if (runtime) {
    ruleIds.push(runtime.id);
    return ticket(d, "needs_info", "UNFIXABLE", expectQuality, ruleIds, runtime.id, runtime.detail);
  }
  const vague = matchVague(d, profile);
  if (vague) {
    ruleIds.push(vague.id);
    return ticket(d, "needs_info", "UNFIXABLE", expectQuality, ruleIds, vague.id, vague.detail);
  }

  // R3b — expect cut among FIXABLE
  if (expectQuality === "explicit" || expectQuality === "inferred") {
    return ticket(d, "strict", "FIXABLE", expectQuality, ruleIds);
  }
  return ticket(d, "locatable_only", "FIXABLE", expectQuality, ruleIds, "R3b", "FIXABLE but expect not unique");
}

export function screenAll(digests: DefectDigest[], opts: ScreenOptions = {}): ScreenedTicket[] {
  return digests.map((d) => screenDigest(d, opts));
}

function ticket(
  digest: DefectDigest,
  pool: ScreenedTicket["pool"],
  verdict: ScreenedTicket["verdict"],
  expectQuality: ScreenedTicket["expectQuality"],
  ruleIds: string[],
  reasonCode?: string,
  reasonDetail?: string,
): ScreenedTicket {
  return {
    digest,
    pool,
    verdict,
    expectQuality,
    ruleIds: [...ruleIds],
    reasonCode,
    reasonDetail,
  };
}

export function funnelCounts(tickets: ScreenedTicket[]): Record<string, number> {
  const out: Record<string, number> = {
    total: tickets.length,
    strict: 0,
    locatable_only: 0,
    needs_info: 0,
    hard_reject: 0,
    security: 0,
    excluded: 0,
    duplicate: 0,
  };
  for (const t of tickets) {
    out[t.pool] = (out[t.pool] ?? 0) + 1;
    if (t.digest.duplicate) out.duplicate = (out.duplicate ?? 0) + 1;
  }
  return out;
}
