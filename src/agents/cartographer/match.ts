import { readdir, stat } from "node:fs/promises";
import path from "node:path";
import type { BatchTicket, DefectCodeMatch, RepoRoot } from "../../contracts/index.js";

const SKIP = new Set(["node_modules", "dist", ".git", "coverage", ".bugfix-runs"]);

async function walkFiles(root: string, max = 800): Promise<string[]> {
  const out: string[] = [];
  async function walk(dir: string, relBase: string): Promise<void> {
    if (out.length >= max) return;
    let entries: string[];
    try {
      entries = await readdir(dir);
    } catch {
      return;
    }
    for (const name of entries) {
      if (SKIP.has(name) || name.startsWith(".")) continue;
      const abs = path.join(dir, name);
      const rel = (relBase ? `${relBase}/${name}` : name).replace(/\\/g, "/");
      let st;
      try {
        st = await stat(abs);
      } catch {
        continue;
      }
      if (st.isDirectory()) {
        await walk(abs, rel);
      } else if (/\.(ts|tsx|js|jsx|vue|py|go|java|kt|cs)$/i.test(name)) {
        out.push(rel);
      }
    }
  }
  await walk(root, "");
  return out;
}

function tokensFor(ticket: BatchTicket): string[] {
  const raw = [ticket.titleTag, ticket.testModule, ticket.intent]
    .filter(Boolean)
    .join(" ");
  const parts = raw
    .split(/[\s/|_\-【】\[\]（）()]+/)
    .map((s) => s.trim().toLowerCase())
    .filter((s) => s.length >= 2 && !/^(the|and|for|with|通用)$/i.test(s));
  return [...new Set(parts)].slice(0, 8);
}

/**
 * Heuristic path match — no CodeGraph required.
 * Produces soft-start candidates for Agent-3 (may be empty).
 */
export async function matchTickets(
  workDir: string,
  repoRoots: RepoRoot[],
  tickets: BatchTicket[],
): Promise<DefectCodeMatch[]> {
  const filesByRoot = new Map<string, string[]>();
  for (const root of repoRoots) {
    const abs = path.join(workDir, root.path);
    filesByRoot.set(root.path, await walkFiles(abs));
  }

  return tickets.map((t) => {
    const toks = tokensFor(t);
    const candidates: DefectCodeMatch["candidates"] = [];
    if (toks.length) {
      for (const root of repoRoots) {
        const files = filesByRoot.get(root.path) ?? [];
        for (const f of files) {
          const fl = f.toLowerCase();
          const hit = toks.find((tok) => fl.includes(tok));
          if (hit) {
            candidates.push({
              repoPath: root.path,
              path: f,
              why: `path contains token "${hit}" from titleTag/testModule/intent`,
              source: "heuristic",
            });
            if (candidates.length >= 5) break;
          }
        }
        if (candidates.length >= 5) break;
      }
    }
    const confidence = candidates.length >= 3 ? "medium" : candidates.length ? "low" : "low";
    return {
      defectId: t.defectId,
      clusterId: t.clusterId,
      title: t.title,
      candidates,
      confidence,
    };
  });
}
