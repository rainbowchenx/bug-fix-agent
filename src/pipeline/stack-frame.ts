export interface AppFrame {
  fn?: string;
  file: string;
}

/** First application stack frame, skipping runtime and dependency frames. */
export function topAppFrame(stack?: string): AppFrame | undefined {
  if (!stack) return undefined;
  for (const line of stack.split(/\n/)) {
    const m = /at\s+(?:async\s+)?(?:([^\s(]+)\s+\()?([^\s()]+):\d+:\d+\)?/.exec(line);
    if (!m?.[2]) continue;
    const file = m[2];
    if (/node_modules|node:internal|node:electron|internal[/\\]process/i.test(file)) continue;
    const base = file.split(/[/\\]/).pop() ?? file;
    return { fn: m[1], file: base };
  }
  return undefined;
}

export function stackSignature(stack?: string): string {
  const frame = topAppFrame(stack);
  if (!frame) return "";
  return `${frame.file}:${frame.fn ?? "?"}`;
}
