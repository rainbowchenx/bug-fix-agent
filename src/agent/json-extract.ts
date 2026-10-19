/**
 * Extract a JSON object starting at `start` using brace balancing
 * (ignores braces inside JSON strings).
 */
export function extractBalancedJsonObject(
  text: string,
  start: number,
): { json: string; end: number } | null {
  if (start < 0 || start >= text.length || text[start] !== "{") return null;
  let depth = 0;
  let inString = false;
  let escape = false;
  for (let i = start; i < text.length; i++) {
    const ch = text[i]!;
    if (inString) {
      if (escape) escape = false;
      else if (ch === "\\") escape = true;
      else if (ch === '"') inString = false;
      continue;
    }
    if (ch === '"') {
      inString = true;
      continue;
    }
    if (ch === "{") depth += 1;
    else if (ch === "}") {
      depth -= 1;
      if (depth === 0) {
        return { json: text.slice(start, i + 1), end: i + 1 };
      }
    }
  }
  return null;
}

/** First balanced `{...}` in text. */
export function extractFirstJsonObject(text: string): unknown {
  const start = text.indexOf("{");
  if (start < 0) throw new Error("No JSON object found in text");
  const extracted = extractBalancedJsonObject(text, start);
  if (!extracted) throw new Error("Unbalanced JSON object in text");
  return JSON.parse(extracted.json) as unknown;
}

/** Label token outside JSON strings, so a word inside an earlier object is not a heading. */
export function indexOfLabel(text: string, label: string): number {
  const lower = label.toLowerCase();
  let inString = false;
  let escape = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i]!;
    if (inString) {
      if (escape) escape = false;
      else if (ch === "\\") escape = true;
      else if (ch === '"') inString = false;
      continue;
    }
    if (ch === '"') {
      inString = true;
      continue;
    }
    if (text.slice(i, i + label.length).toLowerCase() !== lower) continue;
    const before = i === 0 ? "" : text[i - 1]!;
    const after = text[i + label.length] ?? "";
    if (!/\w/.test(before) && !/\w/.test(after)) return i;
  }
  return -1;
}

/**
 * Find the object after a heading (ROOT_CAUSE / SOLUTION / LOCALIZATION),
 * or a fenced ```json block after that heading.
 * A missing heading is an error. Falling back to the first object in the
 * text would reuse an earlier artifact (usually ROOT_CAUSE) under the wrong schema.
 */
export function extractLabeledJson(text: string, label: string): unknown {
  const at = indexOfLabel(text, label);
  if (at < 0) throw new Error(`Missing ${label} JSON object`);
  const slice = text.slice(at + label.length);

  const fence = /```(?:json)?\s*([\s\S]*?)```/i.exec(slice);
  if (fence?.[1]) {
    const inner = fence[1].trim();
    if (inner.startsWith("{")) {
      const bal = extractBalancedJsonObject(inner, 0);
      if (bal) return JSON.parse(bal.json) as unknown;
    }
  }

  const brace = slice.indexOf("{");
  if (brace >= 0) {
    const bal = extractBalancedJsonObject(slice, brace);
    if (bal) return JSON.parse(bal.json) as unknown;
  }

  throw new Error(`Missing ${label} JSON object`);
}
