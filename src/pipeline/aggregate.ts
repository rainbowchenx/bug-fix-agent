import { createHash } from "node:crypto";
import type { Cluster, Defect } from "../types.js";
import { deriveFingerprint } from "./normalize.js";
import { topAppFrame } from "./stack-frame.js";

const MAX_CLUSTER_SIZE = 5;

function clusterKey(defect: Defect): string {
  const fp = defect.fingerprint ?? deriveFingerprint(defect);
  return `${defect.repoUrl}::${fp}`;
}

function fileOf(defect: Defect): string | undefined {
  return topAppFrame(defect.stackTrace)?.file.toLowerCase();
}

function makeClusterId(key: string, index: number): string {
  const hash = createHash("sha1").update(key).digest("hex").slice(0, 10);
  return `c${index + 1}-${hash}`;
}

function sameRepoFile(a: Defect[], b: Defect[]): boolean {
  if (!a.length || !b.length || a[0]!.repoUrl !== b[0]!.repoUrl) return false;
  const files = new Set(a.map(fileOf).filter(Boolean) as string[]);
  return b.some((d) => {
    const f = fileOf(d);
    return f ? files.has(f) : false;
  });
}

/**
 * Same repoUrl + fingerprint → one cluster.
 * Second pass merges same-repo clusters that share a top application stack file.
 * Clusters larger than 5 are split.
 */
export function aggregateDefects(defects: Defect[]): Cluster[] {
  const groups: Defect[][] = [];
  const byKey = new Map<string, Defect[]>();
  for (const d of defects) {
    const key = clusterKey(d);
    const list = byKey.get(key);
    if (list) list.push(d);
    else {
      const created = [d];
      byKey.set(key, created);
      groups.push(created);
    }
  }

  const parent = groups.map((_, i) => i);
  const find = (i: number): number => {
    let x = i;
    while (parent[x] !== x) x = parent[x]!;
    return x;
  };
  const union = (i: number, j: number) => {
    const a = find(i);
    const b = find(j);
    if (a !== b) parent[b] = a;
  };
  for (let i = 0; i < groups.length; i++) {
    for (let j = i + 1; j < groups.length; j++) {
      if (sameRepoFile(groups[i]!, groups[j]!)) union(i, j);
    }
  }

  const merged = new Map<number, Defect[]>();
  groups.forEach((g, i) => {
    const root = find(i);
    const acc = merged.get(root) ?? [];
    acc.push(...g);
    merged.set(root, acc);
  });

  const clusters: Cluster[] = [];
  let i = 0;
  for (const group of merged.values()) {
    for (let offset = 0; offset < group.length; offset += MAX_CLUSTER_SIZE) {
      const slice = group.slice(offset, offset + MAX_CLUSTER_SIZE);
      const primary = slice[0]!;
      const key = `${clusterKey(primary)}#${offset}`;
      clusters.push({
        id: makeClusterId(key, i),
        defectIds: slice.map((d) => d.id),
        repoUrl: primary.repoUrl,
        branch: primary.branch,
        primaryTitle: primary.title,
        fingerprint: primary.fingerprint,
      });
      i += 1;
    }
  }
  return clusters;
}
