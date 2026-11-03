import { isOpenLike } from "./rules.js";
import { defaultIntentClassifier, type IntentClassifier } from "./intent.js";
import type {
  BatchCluster,
  BatchTicket,
  Intent,
  ScreenedTicket,
} from "./types.js";

export interface ClusterOptions {
  intentClassifier?: IntentClassifier;
  /** R5: fraction of strict size */
  fatRatio?: number;
  fatAbsolute?: number;
  /** classify intent for locatable_only too (default false per design) */
  intentOnLocatable?: boolean;
}

export interface ClusterResult {
  clusters: BatchCluster[];
  tickets: BatchTicket[];
}

function clusterIdOf(line: string, module: string, tag: string, intent: Intent, token?: string): string {
  const base = `${line}::${module}::${tag}::${intent}`;
  return token ? `${base}::${token}` : base;
}

function expectRank(q: string): number {
  if (q === "explicit") return 0;
  if (q === "inferred") return 1;
  if (q === "ambiguous") return 2;
  return 3;
}

/**
 * R4–R6: L1/L2 rules + L3 intent (injectable) + fat fallback + sort.
 * Only `strict` enters primary clusters; bypass tickets still appear in tickets[].
 */
export async function clusterScreened(
  screened: ScreenedTicket[],
  productLine: string,
  opts: ClusterOptions = {},
): Promise<ClusterResult> {
  const classify = opts.intentClassifier ?? defaultIntentClassifier;
  const fatRatio = opts.fatRatio ?? 0.25;
  const fatAbsolute = opts.fatAbsolute ?? 40;

  const strict = screened.filter((t) => t.pool === "strict");
  const forIntent = opts.intentOnLocatable
    ? screened.filter((t) => t.pool === "strict" || t.pool === "locatable_only")
    : strict;

  const intentMap = await Promise.resolve(classify(forIntent.map((t) => t.digest)));

  const tickets: BatchTicket[] = [];
  const clusterBuckets = new Map<string, ScreenedTicket[]>();

  for (const t of screened) {
    const dig = t.digest;
    const intentRes =
      intentMap.get(dig.defectId) ??
      ({
        intent: "unclear" as Intent,
        intentSource: "unclear" as const,
        intentConfidence: "low" as const,
        rationale: "not classified",
      });

    const inPrimary = t.pool === "strict";
    const cid = inPrimary
      ? clusterIdOf(productLine, dig.testModule, dig.titleTag, intentRes.intent)
      : undefined;

    if (inPrimary && cid) {
      const list = clusterBuckets.get(cid) ?? [];
      list.push(t);
      clusterBuckets.set(cid, list);
    }

    tickets.push({
      defectId: dig.defectId,
      title: dig.title,
      pool: t.pool,
      clusterId: cid,
      testModule: dig.testModule,
      titleTag: dig.titleTag,
      intent: inPrimary || opts.intentOnLocatable ? intentRes.intent : undefined,
      intentSource: inPrimary || opts.intentOnLocatable ? intentRes.intentSource : undefined,
      intentConfidence: inPrimary || opts.intentOnLocatable ? intentRes.intentConfidence : undefined,
      intentRationale: inPrimary || opts.intentOnLocatable ? intentRes.rationale : undefined,
      fieldType: dig.fieldType,
      expectQuality: t.expectQuality,
      reasonCode: t.reasonCode,
      reasonDetail: t.reasonDetail,
      observed: dig.observed || undefined,
      expected: dig.expected || undefined,
      steps: dig.steps || undefined,
      status: dig.status,
      severity: dig.severity,
      createdAt: dig.createdAt,
      duplicate: dig.duplicate,
      semanticFree: dig.semanticFree,
    });
  }

  // R5 fat fallback: title token buckets
  const strictCount = strict.length || 1;
  const finalBuckets = new Map<string, ScreenedTicket[]>();
  for (const [cid, list] of clusterBuckets) {
    const fat = list.length / strictCount > fatRatio || list.length > fatAbsolute;
    if (!fat) {
      finalBuckets.set(cid, list);
      continue;
    }
    const byToken = new Map<string, ScreenedTicket[]>();
    for (const t of list) {
      const token = titleToken(t.digest.title) || "_misc";
      const key = `${cid}::${token}`;
      const arr = byToken.get(key) ?? [];
      arr.push(t);
      byToken.set(key, arr);
    }
    if (byToken.size <= 1) {
      finalBuckets.set(cid, list);
    } else {
      for (const [key, arr] of byToken) finalBuckets.set(key, arr);
    }
  }

  // rebuild clusterIds on tickets for R5 splits
  const ticketById = new Map(tickets.map((t) => [t.defectId, t]));
  const clusters: BatchCluster[] = [];
  for (const [cid, list] of finalBuckets) {
    const parts = cid.split("::");
    const testModule = parts[1] ?? "_unmoduled";
    const titleTag = parts[2] ?? "_untagged";
    const intent = (parts[3] as Intent) ?? "unclear";
    const oversized =
      list.length / strictCount > fatRatio || list.length > fatAbsolute;
    for (const t of list) {
      const row = ticketById.get(t.digest.defectId);
      if (row) row.clusterId = cid;
    }
    const openCount = list.filter((t) => isOpenLike(t.digest.status)).length;
    clusters.push({
      clusterId: cid,
      testModule,
      titleTag,
      intent,
      size: list.length,
      openCount,
      oversized,
      defectIds: list.map((t) => t.digest.defectId),
    });
  }

  // R6 sort clusters
  clusters.sort((a, b) => {
    if ((b.openCount > 0 ? 1 : 0) !== (a.openCount > 0 ? 1 : 0)) {
      return (b.openCount > 0 ? 1 : 0) - (a.openCount > 0 ? 1 : 0);
    }
    if (b.size !== a.size) return b.size - a.size;
    return a.clusterId.localeCompare(b.clusterId);
  });
  clusters.forEach((c, i) => {
    c.priority = i;
  });

  // R6 sort tickets within / globally: open first, expectQuality, then createdAt
  tickets.sort((a, b) => {
    const ao = isOpenLike(a.status) ? 0 : 1;
    const bo = isOpenLike(b.status) ? 0 : 1;
    if (ao !== bo) return ao - bo;
    const eq = expectRank(a.expectQuality) - expectRank(b.expectQuality);
    if (eq !== 0) return eq;
    return (b.createdAt ?? "").localeCompare(a.createdAt ?? "");
  });
  tickets.forEach((t, i) => {
    t.priority = i;
  });

  return { clusters, tickets };
}

function titleToken(title: string): string {
  const stripped = title
    .replace(/【[^】]+】|\[[^\]]+\]/g, " ")
    .replace(/[（(][^）)]*[）)]/g, " ")
    .replace(/[^\u4e00-\u9fffa-zA-Z0-9]+/g, " ")
    .trim();
  const parts = stripped.split(/\s+/).filter((p) => p.length >= 2);
  return (parts[0] ?? "").slice(0, 24);
}
