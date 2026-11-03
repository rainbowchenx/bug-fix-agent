import { CodeKnowledgeSchema, type CodeKnowledge } from "./types.js";

export function validateCodeKnowledge(input: unknown): CodeKnowledge {
  return CodeKnowledgeSchema.parse(input);
}

export function safeValidateCodeKnowledge(
  input: unknown,
): { ok: true; data: CodeKnowledge } | { ok: false; error: string } {
  const parsed = CodeKnowledgeSchema.safeParse(input);
  if (!parsed.success) {
    return { ok: false, error: parsed.error.message };
  }
  return { ok: true, data: parsed.data };
}
