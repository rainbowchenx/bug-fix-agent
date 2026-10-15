const KEEP_LINE =
  /\b(FAIL|FAILED|Error|Assertion|Expected|Received|TypeError|ReferenceError|at\s+)/i;
const DROP_NOISE =
  /^(npm (notice|warn)|added \d+ packages|audited \d+|found \d+ vulnerabilit|funding|run `npm)/i;

/**
 * Compress verify/static logs for implement iterate prompts.
 * Keeps failure-related lines; drops repetitive npm noise.
 */
export function snipVerifyLog(logTail: string, maxChars = 2500): string {
  if (!logTail) return "";
  const lines = logTail.replace(/\r\n/g, "\n").split("\n");
  const kept: string[] = [];
  let prev = "";
  for (const line of lines) {
    const t = line.trimEnd();
    if (!t.trim()) continue;
    if (DROP_NOISE.test(t.trim())) continue;
    if (t === prev) continue;
    if (KEEP_LINE.test(t) || /[✗×✖]|✔.*fail/i.test(t) || kept.length === 0) {
      kept.push(t);
      prev = t;
    } else if (kept.length > 0 && KEEP_LINE.test(kept[kept.length - 1]!)) {
      // keep a few context lines after a hit
      kept.push(t);
      prev = t;
    }
  }
  // If filter emptied everything, fall back to tail
  const body = (kept.length ? kept.join("\n") : logTail).trim();
  if (body.length <= maxChars) return body;
  return body.slice(-maxChars);
}
