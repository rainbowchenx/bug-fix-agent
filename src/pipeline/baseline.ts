export interface GateSnapshot {
  ok: boolean;
  command: string;
  logTail: string;
}

/** Stable-ish failure lines used to tell pre-existing red from new regressions. */
export function failureSignatures(log: string): string[] {
  const sigs: string[] = [];
  for (const line of log.split(/\r?\n/)) {
    const t = line.trim();
    if (!t) continue;
    if (/error|fail|TS\d{3,5}|AssertionError|exception/i.test(t)) {
      sigs.push(t.replace(/\d+/g, "#").slice(0, 180));
    }
  }
  return [...new Set(sigs)].sort();
}

/**
 * True when the current gate result introduces a failure that was not in the baseline.
 * A still-red baseline with the same signatures is not a new failure.
 */
export function isNewFailure(baseline: GateSnapshot, current: GateSnapshot): boolean {
  if (current.ok) return false;
  if (baseline.ok) return true;
  const base = new Set(failureSignatures(baseline.logTail));
  const cur = failureSignatures(current.logTail);
  if (!cur.length) return true;
  return cur.some((s) => !base.has(s));
}
