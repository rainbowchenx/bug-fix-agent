import { z } from "zod";

/** Shared across Agent-2 / Agent-3 artifacts. */
export const ConfidenceSchema = z.enum(["high", "medium", "low"]);
export type Confidence = z.infer<typeof ConfidenceSchema>;

export const CONTRACT_SCHEMA_VERSION = "0.1.0";

/**
 * Default pools Agent-2 matches and Agent-3 analyzes.
 * hard_reject / security / excluded stay out unless a future flag opts in.
 */
export const MATCH_POOLS = ["strict", "locatable_only", "needs_info"] as const;
export type MatchPool = (typeof MATCH_POOLS)[number];

export function isMatchPool(pool: string): pool is MatchPool {
  return (MATCH_POOLS as readonly string[]).includes(pool);
}
