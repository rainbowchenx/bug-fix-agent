export {
  CODE_KNOWLEDGE_SCHEMA_VERSION,
  CodeKnowledgeSchema,
  CartographyProfileSchema,
  DefectCodeMatchSchema,
  type CodeKnowledge,
  type CartographyProfile,
  type DefectCodeMatch,
  type MatchCandidate,
  type Confidence,
} from "./types.js";
export { validateCodeKnowledge, safeValidateCodeKnowledge } from "./validate.js";
export { runCodeCartographer } from "./run.js";
export type { RunCodeCartographerInput, CodeCartographerFn } from "./run.js";
