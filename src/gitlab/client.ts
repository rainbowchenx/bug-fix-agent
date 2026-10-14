export interface GitLabMrInput {
  host: string;
  token: string;
  projectId: string | number;
  sourceBranch: string;
  targetBranch: string;
  title: string;
  description: string;
  fetchFn?: typeof fetch;
}

export interface GitLabMrResult {
  mrUrl: string;
  iid: number;
}

function apiBase(host: string): string {
  return `${host.replace(/\/$/, "")}/api/v4`;
}

export async function createMergeRequest(input: GitLabMrInput): Promise<GitLabMrResult> {
  const fetchFn = input.fetchFn ?? fetch;
  const url = `${apiBase(input.host)}/projects/${encodeURIComponent(String(input.projectId))}/merge_requests`;
  const res = await fetchFn(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "PRIVATE-TOKEN": input.token,
    },
    body: JSON.stringify({
      source_branch: input.sourceBranch,
      target_branch: input.targetBranch,
      title: input.title,
      description: input.description,
      remove_source_branch: false,
    }),
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`GitLab MR create failed (${res.status}): ${body.slice(0, 500)}`);
  }
  const data = (await res.json()) as { web_url?: string; iid?: number };
  if (!data.web_url || data.iid === undefined) {
    throw new Error("GitLab MR response missing web_url/iid");
  }
  return { mrUrl: data.web_url, iid: data.iid };
}

/** Best-effort project path from https git URL → URL-encoded path. */
export function projectIdFromRepoUrl(repoUrl: string): string {
  const u = new URL(repoUrl.replace(/\.git$/i, ""));
  return u.pathname.replace(/^\//, "");
}
