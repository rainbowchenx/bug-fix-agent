import { createHash } from "node:crypto";
import type { Cluster, Defect } from "../types.js";
import { deriveFingerprint } from "./normalize.js";

function clusterKey(defect: Defect): string {
  const fp = defect.fingerprint ?? deriveFingerprint(defect);
  return `${defect.repoUrl}::${fp}`;
}

function makeClusterId(key: string, index: number): string {
  const hash = createHash("sha1").update(key).digest("hex").slice(0, 10);
  return `c${index + 1}-${hash}`;
}

/**
 * Rule MVP: same repoUrl + same fingerprint → one cluster.
 * Oversized cross-module splits are deferred (TODO).
 */
export function aggregateDefects(defects: Defect[]): Cluster[] {
  const groups = new Map<string, Defect[]>();
  for (const d of defects) {
    const key = clusterKey(d);
    const list = groups.get(key) ?? [];
    list.push(d);
    groups.set(key, list);
  }

  const clusters: Cluster[] = [];
  let i = 0;
  for (const [key, group] of groups) {
    const primary = group[0]!;
    clusters.push({
      id: makeClusterId(key, i),
      defectIds: group.map((d) => d.id),
      repoUrl: primary.repoUrl,
      branch: primary.branch,
      primaryTitle: primary.title,
      fingerprint: primary.fingerprint,
    });
    i += 1;
  }
  return clusters;
}
