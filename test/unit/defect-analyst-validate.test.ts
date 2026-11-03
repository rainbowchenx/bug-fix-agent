import { describe, expect, it } from "vitest";
import { routeTicket } from "../../src/agents/analyst/index.js";
import type { BatchTicket } from "../../src/contracts/index.js";

const base = (over: Partial<BatchTicket>): BatchTicket =>
  ({
    defectId: "1",
    title: "t",
    pool: "strict",
    expectQuality: "explicit",
    ...over,
  }) as BatchTicket;

describe("analyst router", () => {
  it("maps needs_info pool to needs_ticket_info", () => {
    const r = routeTicket(base({ pool: "needs_info", expected: "" }), undefined);
    expect(r.outcome).toBe("needs_ticket_info");
    expect(r.blockers?.missingInfo?.length).toBeGreaterThan(0);
  });

  it("maps empty candidates to unlocalized", () => {
    const r = routeTicket(base({ pool: "strict" }), {
      defectId: "1",
      candidates: [],
      confidence: "low",
    });
    expect(r.outcome).toBe("unlocalized");
  });

  it("maps candidates to plan_only", () => {
    const r = routeTicket(base({ pool: "locatable_only" }), {
      defectId: "1",
      candidates: [{ repoPath: ".", path: "src/a.ts", why: "hit", source: "heuristic" }],
      confidence: "medium",
    });
    expect(r.outcome).toBe("plan_only");
    expect(r.proposedFix?.targetFiles?.[0]).toBe("src/a.ts");
  });
});
