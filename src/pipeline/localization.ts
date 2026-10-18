import type { SolutionArtifact } from "../agent/artifacts.js";

export interface LocalizationArtifact {
  suspectFiles: string[];
  symbols: string[];
  editTargets: string[];
}

export function localizationFromSolution(
  solution?: SolutionArtifact,
  extra?: Partial<LocalizationArtifact>,
): LocalizationArtifact {
  const targets = [
    ...(extra?.editTargets ?? []),
    ...(solution?.target_files ?? []),
  ].filter(Boolean);
  const unique = [...new Set(targets)];
  return {
    suspectFiles: extra?.suspectFiles?.length ? extra.suspectFiles : unique,
    symbols: extra?.symbols ?? [],
    editTargets: unique,
  };
}
