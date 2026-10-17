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

/**
 * Find object after a label (ROOT_CAUSE / SOLUTION) or fenced ```json block near the label.
 */
export function extractLabeledJson(text: string, label: string): unknown {
  const labelRe = new RegExp(`${label}\\b`, "i");
  const labelMatch = labelRe.exec(text);
  const from = labelMatch ? labelMatch.index + labelMatch[0].length : 0;
  const slice = text.slice(from);

  // Prefer fenced block after label
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

  // Fallback: first object in whole text
  return extractFirstJsonObject(text);
}
