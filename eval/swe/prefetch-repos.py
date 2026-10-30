"""
Prefetch SWE instance base_commits into a shared git mirror cache.

Default cache: eval/swe/cache/mirrors/<github.com_org_repo>/

The SWE adapter reads SWE_MIRROR_CACHE (same path) so later batch runs
reuse these objects instead of hitting GitHub mid-flight.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path


def run(cmd: list[str], cwd: Path | None = None) -> None:
    subprocess.run(cmd, cwd=cwd, check=True)


def run_ok(cmd: list[str], cwd: Path | None = None) -> bool:
    return subprocess.run(cmd, cwd=cwd, capture_output=True).returncode == 0


def safe_repo_dir(repo: str) -> str:
    url = repo if repo.startswith("http") else f"https://github.com/{repo}.git"
    cleaned = (
        url.replace(".git", "")
        .replace("https://", "")
        .replace("http://", "")
        .replace("/", "_")
        .replace(":", "_")
    )
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    return cleaned[:120] or "repo"


def github_url(repo: str) -> str:
    cleaned = repo.replace(".git", "").replace("https://github.com/", "").replace("http://github.com/", "")
    return f"https://github.com/{cleaned}.git"


def ensure_mirror(mirror: Path, url: str) -> None:
    mirror.mkdir(parents=True, exist_ok=True)
    git_dir = mirror / ".git"
    if not git_dir.exists() and not (mirror / "HEAD").exists():
        # bare-ish working repo (same layout as adapter: non-bare with .git)
        if not (mirror / ".git").exists():
            run(["git", "init"], cwd=mirror)
            run(["git", "remote", "add", "origin", url], cwd=mirror)
    else:
        # drop stale locks from crashed fetches
        for lock in mirror.rglob("*.lock"):
            try:
                lock.unlink()
            except OSError:
                pass


def has_commit(mirror: Path, commit: str) -> bool:
    return run_ok(["git", "cat-file", "-e", f"{commit}^{{commit}}"], cwd=mirror)


def fetch_commit(mirror: Path, commit: str, retries: int, sleep_s: float) -> bool:
    if has_commit(mirror, commit):
        return True
    attempts = [
        ["git", "fetch", "--depth", "1", "origin", commit],
        ["git", "fetch", "--depth", "1", "origin", f"+{commit}:refs/swe/{commit}"],
        ["git", "fetch", "--depth", "1", "origin", f"{commit}:refs/swe/{commit}"],
    ]
    last_err = ""
    for i in range(retries):
        for cmd in attempts:
            try:
                run(cmd, cwd=mirror)
                if has_commit(mirror, commit):
                    return True
            except subprocess.CalledProcessError as e:
                last_err = str(e)
        time.sleep(sleep_s * (i + 1))
    print(f"  FAIL {commit[:12]} after {retries} retries: {last_err}", file=sys.stderr)
    return False


def load_instances(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--instances", required=True, help="JSONL of SWE instances")
    parser.add_argument(
        "--cache",
        default=str(Path("eval/swe/cache/mirrors")),
        help="Shared mirror root (set SWE_MIRROR_CACHE to the same path when running batch)",
    )
    parser.add_argument("--retries", type=int, default=5)
    parser.add_argument("--sleep", type=float, default=3.0)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    rows = load_instances(Path(args.instances))
    if args.limit:
        rows = rows[: args.limit]

    by_repo: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        by_repo[row["repo"]].add(row["base_commit"])

    cache = Path(args.cache)
    cache.mkdir(parents=True, exist_ok=True)
    print(f"cache={cache.resolve()}")
    print(f"repos={len(by_repo)} commits={sum(len(v) for v in by_repo.values())}")

    ok = 0
    fail = 0
    for repo, commits in sorted(by_repo.items()):
        url = github_url(repo)
        mirror = cache / safe_repo_dir(repo)
        print(f"\n[{repo}] -> {mirror.name} ({len(commits)} commits)")
        ensure_mirror(mirror, url)
        # ensure remotes/origin
        if not run_ok(["git", "remote", "get-url", "origin"], cwd=mirror):
            run(["git", "remote", "add", "origin", url], cwd=mirror)
        for commit in sorted(commits):
            if has_commit(mirror, commit):
                print(f"  cached {commit[:12]}")
                ok += 1
                continue
            print(f"  fetch  {commit[:12]} ...")
            if fetch_commit(mirror, commit, args.retries, args.sleep):
                print(f"  ok     {commit[:12]}")
                ok += 1
            else:
                fail += 1

    print(f"\nDone. ok={ok} fail={fail}")
    print(f"Next: set SWE_MIRROR_CACHE={cache.resolve()} then npm run swe:baseline:official50")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
