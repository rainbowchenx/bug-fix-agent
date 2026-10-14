import { describe, expect, it } from "vitest";
import { aggregateDefects } from "../../src/pipeline/aggregate.js";
import { normalizeDefects } from "../../src/pipeline/normalize.js";

describe("normalize + aggregate", () => {
  it("merges two defects with same fingerprint into one cluster", () => {
    const defects = normalizeDefects([
      {
        id: "1",
        title: "Null crash on login",
        repoUrl: "https://gitlab.com/a/b.git",
        fingerprint: "fp-login",
      },
      {
        id: "2",
        title: "Null crash on login (again)",
        repoUrl: "https://gitlab.com/a/b.git",
        fingerprint: "fp-login",
      },
      {
        id: "3",
        title: "Other bug",
        repoUrl: "https://gitlab.com/a/b.git",
        fingerprint: "fp-other",
      },
    ]);

    const clusters = aggregateDefects(defects);
    expect(clusters).toHaveLength(2);
    const login = clusters.find((c) => c.fingerprint === "fp-login");
    expect(login?.defectIds).toEqual(["1", "2"]);
    expect(login?.repoUrl).toContain("gitlab.com/a/b");
    expect(login?.primaryTitle).toBeTruthy();
  });

  it("does not merge across different repos", () => {
    const defects = normalizeDefects([
      {
        id: "1",
        title: "same title",
        repoUrl: "https://gitlab.com/a/one.git",
        fingerprint: "fp",
      },
      {
        id: "2",
        title: "same title",
        repoUrl: "https://gitlab.com/a/two.git",
        fingerprint: "fp",
      },
    ]);
    expect(aggregateDefects(defects)).toHaveLength(2);
  });
});
