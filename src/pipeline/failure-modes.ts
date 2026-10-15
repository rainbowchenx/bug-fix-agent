/** WorkBuddy / gstack-investigator aligned failure mode catalog. */
export const FAILURE_MODES = [
  "race_condition",
  "nil_propagation",
  "state_corruption",
  "integration_failure",
  "configuration_drift",
  "stale_cache",
  "logic_error",
  "api_contract_mismatch",
  "other",
] as const;

export type FailureMode = (typeof FAILURE_MODES)[number];

export const FAILURE_MODE_HINT = FAILURE_MODES.join("|");
