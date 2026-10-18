import { createHash } from "node:crypto";
import type { Defect } from "../types.js";
import { DefectSchema } from "../types.js";
import { stackSignature } from "./stack-frame.js";

function compact(s: string | undefined): string | undefined {
  if (s === undefined) return undefined;
  const t = s.trim().replace(/\s+/g, " ");
  return t.length ? t : undefined;
}

function normalizeTitleKey(title: string): string {
  return title
    .toLowerCase()
    .replace(/[^a-z0-9\u4e00-\u9fff]+/gi, " ")
    .trim()
    .slice(0, 80);
}

export function deriveFingerprint(defect: Pick<Defect, "title" | "fingerprint" | "stackTrace" | "pageUrl">): string {
  if (defect.fingerprint?.trim()) return defect.fingerprint.trim();
  const basis = [
    normalizeTitleKey(defect.title),
    compact(defect.pageUrl) ?? "",
    stackSignature(defect.stackTrace),
    (compact(defect.stackTrace) ?? "").slice(0, 200),
  ].join("|");
  return createHash("sha1").update(basis).digest("hex").slice(0, 16);
}

export function normalizeDefects(raw: unknown[]): Defect[] {
  return raw.map((item, i) => {
    const parsed = DefectSchema.safeParse(item);
    if (!parsed.success) {
      throw new Error(`Invalid defect at index ${i}: ${parsed.error.message}`);
    }
    const d = parsed.data;
    return {
      ...d,
      title: d.title.trim(),
      description: compact(d.description),
      repoUrl: d.repoUrl.trim().replace(/\/$/, ""),
      branch: compact(d.branch),
      fingerprint: deriveFingerprint(d),
      stackTrace: compact(d.stackTrace),
      pageUrl: compact(d.pageUrl),
      severity: compact(d.severity),
    };
  });
}
