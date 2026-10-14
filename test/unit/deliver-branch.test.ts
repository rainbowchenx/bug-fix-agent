import { describe, expect, it, vi } from "vitest";
import { bugfixBranchName, deliverFix } from "../../src/pipeline/deliver.js";

describe("deliverFix", () => {
  it("builds branch name and creates MR via GitLab API", async () => {
    const branch = bugfixBranchName("run-abc", "c1-deadbeef");
    expect(branch).toMatch(/^bugfix\//);

    const execFileFn = vi.fn(async () => ({ stdout: "", stderr: "" }));
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
      description: "details",
      gitlabHost: "https://gitlab.com",
      token: "glpat-x",
      repoUrl: "https://gitlab.com/org/app.git",
      execFileFn,
      fetchFn,
    });

    expect(result.mrUrl).toContain("merge_requests/9");
    expect(execFileFn).toHaveBeenCalled();
    const push = execFileFn.mock.calls.find((c) => c[1]?.[0] === "push");
    expect(push).toBeTruthy();
    expect(fetchFn).toHaveBeenCalled();
  });
});
