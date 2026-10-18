import { appendFile, mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import type { SwePrediction } from "./types.js";

export async function ensurePredictionsFile(filePath: string): Promise<void> {
  await mkdir(path.dirname(filePath), { recursive: true });
  try {
    await writeFile(filePath, "", { flag: "wx" });
  } catch {
    // already exists
  }
}

export async function appendPrediction(
  filePath: string,
  prediction: SwePrediction,
): Promise<void> {
  await ensurePredictionsFile(filePath);
  await appendFile(filePath, `${JSON.stringify(prediction)}\n`, "utf8");
}
