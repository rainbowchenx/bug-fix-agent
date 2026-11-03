/** @deprecated import from `src/contracts` + `src/agents/cartographer` instead. */
export {
  CODE_KNOWLEDGE_SCHEMA_VERSION,
  CodeKnowledgeSchema,
  CartographyProfileSchema,
  DefectCodeMatchSchema,
  validateCodeKnowledge,
  safeValidateCodeKnowledge,
  type CodeKnowledge,
  type CartographyProfile,
  type DefectCodeMatch,
  type MatchCandidate,
  type Confidence,
} from "../contracts/index.js";

export {
  runCartographer as runCodeCartographer,
  type RunCartographerInput as RunCodeCartographerInput,
  type CartographerFn as CodeCartographerFn,
} from "../agents/cartographer/index.js";
