import { describe, expect, it, vi } from "vitest";
import {
  bugfixBranchName,
  buildMrDescription,
  deliverFix,
  NoChangesError,
} from "../../src/pipeline/deliver.js";
import { projectIdFromRepoUrl } from "../../src/gitlab/client.js";

describe("deliverFix", () => {
  it("builds branch name and creates MR via GitLab API", async () => {
    const branch = bugfixBranchName("run-abc", "c1-deadbeef");
    expect(branch).toMatch(/^bugfix\//);

    const execFileFn = vi.fn(async (_f: string, args: string[]) => {
      if (args.includes("diff") && args.includes("--name-only")) {
        return { stdout: "src/a.ts\n", stderr: "" };
      }
      if (args.includes("ls-files")) return { stdout: "", stderr: "" };
      return { stdout: "", stderr: "" };
    });
    const fetchFn = vi.fn(async () =>
      Response.json({
        web_url: "https://gitlab.com/org/app/-/merge_requests/9",
        iid: 9,
      }),
    );

    const result = await deliverFix({
      repoPath: "/tmp/repo",
      runId: "run-abc",
      clusterId: "c1-deadbeef",
      title: "fix: null crash",
      description: buildMrDescription({
        rootCauseSummary: "null",
        solutionSummary: "guard",
        defectIds: ["d1"],
        verifyCommand: "npm test",
      }),
      gitlabHost: "https://gitlab.com",
      token: "glpat-x",
      repoUrl: "https://gitlab.com/org/app.git",
      baseSha: "abc",
      execFileFn,
      fetchFn,
    });

    expect(result.mrUrl).toContain("merge_requests/9");
    expect(execFileFn.mock.calls.some((c) => c[1]?.includes("user.name=bugfix-agent"))).toBe(
      true,
    );
    expect(fetchFn).toHaveBeenCalled();
    const body = JSON.parse(
      (fetchFn.mock.calls[0]![1] as { body: string }).body,
    ) as { description: string };
    expect(body.description).toContain("d1");
  });

  it("throws NoChangesError when base has no diff", async () => {
    const execFileFn = vi.fn(async (_f: string, args: string[]) => {
      if (args.includes("--name-only") || args.includes("ls-files")) {
        return { stdout: "", stderr: "" };
      }
      return { stdout: "", stderr: "" };
    });
    await expect(
      deliverFix({
        repoPath: "/tmp/repo",
        runId: "r",
        clusterId: "c",
        title: "t",
        description: "d",
        gitlabHost: "https://gitlab.com",
        token: "t",
        repoUrl: "https://gitlab.com/o/a.git",
        baseSha: "sha",
        execFileFn,
      }),
    ).rejects.toBeInstanceOf(NoChangesError);
  });

  it("parses ssh gitlab urls", () => {
    expect(projectIdFromRepoUrl("git@gitlab.com:group/sub/repo.git")).toBe("group/sub/repo");
  });
});
