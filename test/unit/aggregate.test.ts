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

  it("merges same-repo defects that share a top application stack file", () => {
    const stack = (file: string) =>
      `Error: x\n    at boom (${file}:10:1)\n    at Module._compile (node:internal/modules/cjs/loader.js:1:1)`;
    const defects = normalizeDefects([
      {
        id: "1",
        title: "crash A",
        repoUrl: "https://gitlab.com/a/b.git",
        fingerprint: "fp-a",
        stackTrace: stack("/app/src/login.ts"),
      },
      {
        id: "2",
        title: "crash B",
        repoUrl: "https://gitlab.com/a/b.git",
        fingerprint: "fp-b",
        stackTrace: stack("/app/src/login.ts"),
      },
    ]);
    expect(aggregateDefects(defects)).toHaveLength(1);
  });

  it("splits clusters larger than 5", () => {
    const defects = normalizeDefects(
      Array.from({ length: 6 }, (_, i) => ({
        id: `d${i}`,
        title: "same",
        repoUrl: "https://gitlab.com/a/b.git",
        fingerprint: "fp",
      })),
    );
    const clusters = aggregateDefects(defects);
    expect(clusters).toHaveLength(2);
    expect(clusters[0]?.defectIds).toHaveLength(5);
    expect(clusters[1]?.defectIds).toHaveLength(1);
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
