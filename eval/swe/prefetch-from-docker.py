"""
Prefetch SWE base_commits from official swebench eval images into the shared mirror cache.

This avoids flaky GitHub access on the host: each image already contains /testbed
with the needed commit object.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path


def run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=check, capture_output=True, text=True)


def safe_repo_dir(repo: str) -> str:
    url = repo if repo.startswith("http") else f"https://github.com/{repo}.git"
    cleaned = re.sub(r"\.git$", "", url, flags=re.I)
    cleaned = re.sub(r"^https?://", "", cleaned, flags=re.I)
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "_", cleaned)
    return cleaned[:120] or "repo"


def has_commit(mirror: Path, commit: str) -> bool:
    return (
        run(
            ["git", "-C", str(mirror), "cat-file", "-e", f"{commit}^{{commit}}"],
            check=False,
        ).returncode
        == 0
    )


def ensure_mirror(mirror: Path, repo: str) -> None:
    mirror.mkdir(parents=True, exist_ok=True)
    if not (mirror / ".git").exists():
        subprocess.run(["git", "init"], cwd=mirror, check=True)
    url = f"https://github.com/{repo}.git"
    subprocess.run(
        ["git", "remote", "add", "origin", url],
        cwd=mirror,
        check=False,
        capture_output=True,
    )


def fetch_from_local_git(mirror: Path, donor_git: Path, commit: str) -> bool:
    # Absolute path required on Windows; relative paths fail with "not a git repository".
    src = str(donor_git.resolve())
    cmds = [
        ["git", "-C", str(mirror), "fetch", src, f"{commit}:refs/swe/{commit}"],
        ["git", "-C", str(mirror), "fetch", src, commit],
    ]
    for cmd in cmds:
        p = run(cmd, check=False)
        if has_commit(mirror, commit):
            return True
        if p.returncode != 0:
            print(f"  fetch warn: {(p.stderr or '')[-200:]}", file=sys.stderr)
    return has_commit(mirror, commit)


def extract_commit_from_image(image: str, commit: str, work: Path) -> Path | None:
    """Return path to a bare-ish .git directory copied from the image /testbed."""
    import shutil

    name = f"swe_prefetch_{abs(hash(image + commit)) % 10_000_000}"
    run(["docker", "rm", "-f", name], check=False)
    create = run(
        ["docker", "create", "--name", name, "--entrypoint", "sleep", image, "600"],
        check=False,
    )
    if create.returncode != 0:
        pull = run(["docker", "pull", image], check=False)
        if pull.returncode != 0:
            print(f"  pull failed: {pull.stderr[-300:]}", file=sys.stderr)
            return None
        create = run(
            ["docker", "create", "--name", name, "--entrypoint", "sleep", image, "600"],
            check=False,
        )
        if create.returncode != 0:
            print(f"  create failed: {create.stderr[-300:]}", file=sys.stderr)
            return None
    run(["docker", "start", name], check=False)
    check = run(
        ["docker", "exec", name, "git", "-C", "/testbed", "cat-file", "-e", f"{commit}^{{commit}}"],
        check=False,
    )
    if check.returncode != 0:
        print(f"  image missing commit {commit[:12]}", file=sys.stderr)
        run(["docker", "rm", "-f", name], check=False)
        return None
    dest = work / f"donor-{commit[:12]}"
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True)
    # Copy only .git — full tree hits Windows symlink privilege errors.
    cp = run(["docker", "cp", f"{name}:/testbed/.git", str(dest / ".git")], check=False)
    run(["docker", "rm", "-f", name], check=False)
    if cp.returncode != 0:
        print(f"  docker cp failed: {cp.stderr[-300:]}", file=sys.stderr)
        return None
    return dest / ".git"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--images",
        default="eval/swe/data/official-lite-50.images.json",
        help="JSON list with instance_id, repo, base_commit, image",
    )
    parser.add_argument("--cache", default="eval/swe/cache/mirrors")
    parser.add_argument("--work", default="eval/swe/cache/docker-donors")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--skip-pull", action="store_true", help="Only use already-local images")
    args = parser.parse_args()

    rows = json.loads(Path(args.images).read_text(encoding="utf-8"))
    if args.limit:
        rows = rows[: args.limit]

    cache = Path(args.cache)
    work = Path(args.work)
    cache.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)

    ok = fail = skip = 0
    for i, row in enumerate(rows, 1):
        iid = row["instance_id"]
        repo = row["repo"]
        commit = row["base_commit"]
        image = row["image"]
        mirror = cache / safe_repo_dir(repo)
        print(f"[{i}/{len(rows)}] {iid}")
        ensure_mirror(mirror, repo)
        if has_commit(mirror, commit):
            print(f"  cached {commit[:12]}")
            skip += 1
            continue
        if args.skip_pull:
            local = run(["docker", "image", "inspect", image], check=False)
            if local.returncode != 0:
                print(f"  skip (image not local): {image}")
                fail += 1
                continue
        print(f"  from docker {image}")
        t0 = time.time()
        donor_git = extract_commit_from_image(image, commit, work)
        if not donor_git:
            fail += 1
            continue
        if fetch_from_local_git(mirror, donor_git, commit):
            print(f"  ok {commit[:12]} ({time.time() - t0:.0f}s)")
            ok += 1
        else:
            print(f"  FAIL import {commit[:12]}", file=sys.stderr)
            fail += 1
        import shutil

        shutil.rmtree(donor_git.parent, ignore_errors=True)

    print(f"\nDone. imported={ok} already={skip} fail={fail}")
    print(f"SWE_MIRROR_CACHE={cache.resolve()}")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
