#!/usr/bin/env python3
"""
Open-Source Git Automation & Cron Tracker — bot.py
Appends a timestamped entry to learning-log.txt and pushes via Git.

Features:
- Randomized technical quotes / TIL entries
- Robust Git error handling: pull --rebase, merge conflicts, network retries
- Idempotent: safe to run multiple times per day (appends only once if needed)
- Works locally and on GitHub Actions runner
"""
import subprocess
import sys
import random
import time
from datetime import datetime, timezone
from pathlib import Path

# --- Config ---
REPO_ROOT = Path(__file__).parent.resolve()
LOG_FILE = REPO_ROOT / "learning-log.txt"
BRANCH = "main"  # change if default branch is `master`
MAX_PUSH_RETRIES = 4
RETRY_BASE_SECONDS = 5

QUOTES = [
    "Git internals: A commit is a snapshot, not a diff — objects are content-addressed via SHA-1/SHA-256.",
    "DevOps note: Cron runs in UTC on GitHub Actions — always reason in UTC, display in local.",
    "Git tip: `git pull --rebase --autostash` keeps history linear and avoids merge commits on bot repos.",
    "Automation: Idempotency matters — a cron job should be safe to re-run without side effects.",
    "GitHub Actions: `contents: write` + `GITHUB_TOKEN` gives the runner push access without PATs.",
    "Networking: Transient failures are normal — exponential backoff beats immediate retry storms.",
    "Rebase mental model: Replay local commits on top of remote — cleaner than merging bot noise.",
    "Observability: Every auto-commit should log UTC timestamp + runner context for auditability.",
    "Git plumbing: `git rev-parse --abbrev-ref HEAD` and `git ls-remote` are safer than parsing `git status`.",
    "Cron: `0 8 * * *` is 08:00 UTC daily — verify with https://crontab.guru",
    "TIL: `git diff --quiet` exits 1 when dirty — perfect for CI gates.",
    "Resilience: Handle diverged history before push, or you'll loop on non-fast-forward errors.",
]

def run(cmd: list[str], check: bool = True, capture: bool = False) -> subprocess.CompletedProcess:
    """Run a shell command, log it, return result."""
    print(f"$ {' '.join(cmd)}")
    result = subprocess.run(
        cmd, cwd=REPO_ROOT, check=False,
        capture_output=capture, text=True
    )
    if capture and result.stdout:
        print(result.stdout.strip())
    if capture and result.stderr:
        print(result.stderr.strip(), file=sys.stderr)
    if check and result.returncode != 0:
        raise subprocess.CalledProcessError(result.returncode, cmd, result.stdout, result.stderr)
    return result

def ensure_git_repo() -> None:
    if not (REPO_ROOT / ".git").exists():
        print("ERROR: Not a git repository. Run `git init` first.", file=sys.stderr)
        sys.exit(1)

def get_current_branch() -> str:
    res = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], capture=True)
    return res.stdout.strip()

def has_remote() -> bool:
    res = run(["git", "remote"], capture=True, check=False)
    return bool(res.stdout.strip())

def has_upstream() -> bool:
    res = run(["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
              capture=True, check=False)
    return res.returncode == 0

def sync_with_remote(branch: str) -> None:
    """
    Rebase local branch onto remote to handle diverged history.
    Handles merge conflicts gracefully.
    """
    if not has_remote():
        print("No remote configured — skipping sync.")
        return
    if not has_upstream():
        print(f"No upstream for {branch} — skipping pull. First push will set upstream.")
        return

    print(f"Fetching and rebasing onto origin/{branch}...")
    run(["git", "fetch", "origin", branch], check=False)

    # Check if push is needed at all
    res = run(["git", "rev-list", "--left-right", "--count", f"origin/{branch}...HEAD"],
              capture=True, check=False)
    if res.returncode == 0:
        behind, ahead = map(int, res.stdout.strip().split())
        if behind == 0:
            print(f"Already up-to-date with origin/{branch} (ahead {ahead}).")
            return
        print(f"Behind {behind}, ahead {ahead} — rebasing...")

    result = run(["git", "pull", "--rebase", "--autostash", "origin", branch], check=False)
    if result.returncode != 0:
        print("Rebase failed — attempting conflict handling...", file=sys.stderr)
        # Check for conflicts
        status = run(["git", "status", "--porcelain"], capture=True, check=False)
        if status.stdout.strip():
            print("Conflict markers detected. Aborting rebase and resetting to remote...", file=sys.stderr)
            run(["git", "rebase", "--abort"], check=False)
            # Strategy: for this bot repo, prefer remote + re-apply log entry
            # Stash our log change, reset to remote, then re-apply
            print("Stashing local changes, resetting to origin...")
            run(["git", "stash", "push", "-m", "bot-autostash-conflict", "--keep-index"], check=False)
            run(["git", "reset", "--hard", f"origin/{branch}"], check=False)
            stashed = run(["git", "stash", "list"], capture=True, check=False)
            if "bot-autostash-conflict" in stashed.stdout:
                # Pop and keep our log entry — will be re-appended below
                run(["git", "stash", "pop"], check=False)
            print("Recovered from conflict — log file will be re-appended.")
        else:
            run(["git", "rebase", "--abort"], check=False)
            raise RuntimeError("Rebase failed for unknown reason")

def append_log_entry() -> bool:
    """Append timestamp + random quote to learning-log.txt. Returns True if file changed."""
    now = datetime.now(timezone.utc)
    quote = random.choice(QUOTES)
    entry = f"[{now.strftime('%Y-%m-%d %H:%M:%S UTC')}] {quote}\n"

    # Avoid duplicate entry within same minute on re-runs
    if LOG_FILE.exists():
        last_lines = LOG_FILE.read_text(encoding="utf-8").splitlines()[-5:]
        if any(now.strftime('%Y-%m-%d %H:%M') in line for line in last_lines):
            print("Entry for this minute already exists — skipping append (idempotent).")
            return False

    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(entry)
    print(f"Appended: {entry.strip()}")
    return True

def git_commit_and_push(branch: str) -> None:
    # Stage
    run(["git", "add", str(LOG_FILE.relative_to(REPO_ROOT))])

    # Check if anything to commit
    diff = run(["git", "diff", "--cached", "--quiet"], check=False)
    if diff.returncode == 0:
        print("No staged changes — nothing to commit.")
        return

    # Commit
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    run(["git", "commit", "-m", f"chore(log): daily update {now} [skip ci]"])

    if not has_remote():
        print("No remote — commit created locally only. Add remote to push.")
        return

    # Push with exponential backoff for network drops
    for attempt in range(1, MAX_PUSH_RETRIES + 1):
        result = run(["git", "push", "origin", branch], check=False)
        if result.returncode == 0:
            print(f"Pushed to origin/{branch} (attempt {attempt}).")
            return

        stderr = (result.stderr or "") + (result.stdout or "")
        is_network = any(s in stderr.lower() for s in ["timeout", "unable to access", "could not resolve", "connection", "rpc failed", "broken pipe"])
        is_non_fast_forward = "non-fast-forward" in stderr.lower() or "fetch first" in stderr.lower()

        if is_non_fast_forward:
            print(f"Push rejected (non-fast-forward) — re-syncing (attempt {attempt}/{MAX_PUSH_RETRIES})...")
            sync_with_remote(branch)
            # After rebase, amend or create new commit if log was reset
            if not append_log_entry():
                # If file was reset, ensure we have an entry
                pass
            run(["git", "add", str(LOG_FILE.relative_to(REPO_ROOT))], check=False)
            if run(["git", "diff", "--cached", "--quiet"], check=False).returncode != 0:
                run(["git", "commit", "-m", f"chore(log): retry update {now} [skip ci]"], check=False)
            continue

        if is_network and attempt < MAX_PUSH_RETRIES:
            wait = RETRY_BASE_SECONDS * (2 ** (attempt - 1)) + random.uniform(0, 1)
            print(f"Network error — retrying in {wait:.1f}s (attempt {attempt}/{MAX_PUSH_RETRIES})...")
            time.sleep(wait)
            continue

        if attempt == MAX_PUSH_RETRIES:
            print(f"Push failed after {MAX_PUSH_RETRIES} attempts.", file=sys.stderr)
            print(stderr, file=sys.stderr)
            sys.exit(1)
        else:
            wait = RETRY_BASE_SECONDS * attempt
            print(f"Push failed — retrying in {wait}s...")
            time.sleep(wait)

def main() -> None:
    print(f"=== Git Automation Bot — {datetime.now(timezone.utc).isoformat()} ===")
    ensure_git_repo()

    actual_branch = get_current_branch()
    target_branch = actual_branch if actual_branch != "HEAD" else BRANCH
    if actual_branch == "HEAD":
        print(f"Detached HEAD — using configured branch {BRANCH}")

    # Ensure git identity exists (required in fresh Actions runner)
    email = run(["git", "config", "user.email"], capture=True, check=False).stdout.strip()
    name = run(["git", "config", "user.name"], capture=True, check=False).stdout.strip()
    if not email:
        print("No git user.email — setting bot identity. Update to your GitHub email for contributions to count.")
        run(["git", "config", "user.email", "4bd23cs046@bietdvg.edu"])
    if not name:
        run(["git", "config", "user.name", "automation-bot"])

    sync_with_remote(target_branch)
    changed = append_log_entry()
    if not changed:
        # Still try to push if we are ahead
        git_commit_and_push(target_branch)
    else:
        git_commit_and_push(target_branch)

    print("=== Done ===")

if __name__ == "__main__":
    main()
