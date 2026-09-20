# DevOps Automation Lab — Git Internals & Cron on GitHub Actions

> Lab repo demonstrating Git plumbing, resilient Python scripting, and production cron on GitHub Actions — not a streak hack. A transparent, interview-ready showcase for DevOps workflows.

[![Daily Log Automation](https://github.com/chinglung-angh27/open-source-git-automation-cron-tracker/actions/workflows/automation.yml/badge.svg)](https://github.com/chinglung-angh27/open-source-git-automation-cron-tracker/actions/workflows/automation.yml)
[![Last Update](https://img.shields.io/badge/auto--updated-daily-blue?logo=github-actions)](./learning-log.txt)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

**Transparency Notice:** This is a **DevOps lab**, not a contribution hack. Every commit is bot-generated and fully disclosed to demonstrate `fetch`/`rebase`/`autostash`, idempotent scripting, and Actions cron. Reviewers: treat the graph here as automation evidence and judge real work from pinned repos below.

---

## Why This Exists — For Reviewers

This lab is a **hiring signal for DevOps basics**, not a replacement for product work:

- **Git internals** — content-addressed objects, plumbing vs porcelain, `pull --rebase --autostash`, divergence/conflict recovery
- **Resilient scripting** — Python + Node ports with idempotency, `rev-list` checks, and exponential backoff for transient network failures
- **CI/CD** — Actions `cron`, `contents: write` scoping, `GITHUB_TOKEN` push from an ephemeral runner, and log observability

Use this repo to answer "can you automate Git reliably?" — judge real product skill from my pinned repos.

---

## How It Works

```
Cron (GitHub Actions — 08:30 UTC daily)
        │
        ▼
  Checkout repo (fetch-depth: 0)
        │
        ▼
  bot.py (or bot.js)
   ├─ 1. Append timestamp + random technical quote → learning-log.txt
   ├─ 2. Sync with remote (fetch + pull --rebase --autostash)
   │     └─ handles diverged history / merge conflicts
   ├─ 3. git add → git commit -m "chore(log): daily update ..."
   └─ 4. git push with exponential backoff (retries on network drops)
        │
        ▼
  learning-log.txt updated on `main` — 1 contribution/day
```

### Stack

| Layer | Tool | Role |
|-------|------|------|
| **Scheduler** | GitHub Actions `cron: "30 8 * * *"` | Triggers daily at 08:30 UTC (no server needed) |
| **Runner** | `ubuntu-latest` + `GITHUB_TOKEN` | Ephemeral VM with `contents: write` to push back |
| **Script** | `bot.py` (Python 3.11) / `bot.js` (Node 20) | Appends to `learning-log.txt`, runs Git plumbing |
| **Git strategy** | `pull --rebase --autostash` + retry | Avoids merge commits, recovers from conflicts and network failures |
| **Idempotency** | Minute-level dedup check | Safe to re-run manually without duplicate entries |

---

## Repository Structure

```
.
├── bot.py                          # Python automation (primary)
├── bot.js                          # Node.js port (alternative)
├── learning-log.txt                # Daily-append log — the artifact
├── .github/workflows/automation.yml # Cron + push workflow
├── package.json                    # Node metadata (for bot.js)
└── README.md                       # You are here
```

---

## Quick Start

### 1. Create the repo
```bash
# On GitHub, create an empty public repo: open-source-git-automation-cron-tracker
# Do NOT initialize with README — you will push this one
```

### 2. Push this project
```bash
git clone https://github.com/chinglung-angh27/open-source-git-automation-cron-tracker.git
cd open-source-git-automation-cron-tracker
# copy files from ~/open-source-git-automation-cron-tracker into here, then:
git add .
git commit -m "init: open-source git automation tracker"
git branch -M main
git push -u origin main
```

### 3. Configure Git identity (so contributions count)
In `.github/workflows/automation.yml`, change:
```yaml
git config user.email "bot@users.noreply.github.com"
```
to your verified GitHub email (or your noreply `ID+USERNAME@users.noreply.github.com` from https://github.com/settings/emails). Otherwise commits won't count on your graph.

If the repo is **private**, enable: `GitHub → Settings → Profile → Include private contributions on my profile`.

### 4. Test manually
`GitHub → Actions → Daily Log Automation → Run workflow → Run workflow`. Check `learning-log.txt` and `git log`.

### 5. Local run (optional)
```bash
python3 bot.py        # or: node bot.js
cat learning-log.txt  # tail the new entry
```

---

## Script Details

### `bot.py` (primary)
- Picks a random technical quote from `QUOTES[]` and writes `[YYYY-MM-DD HH:MM:SS UTC] <quote>` to `learning-log.txt`
- **Idempotent**: skips if an entry for the current minute already exists
- **Sync**: `git fetch` + `git pull --rebase --autostash` — handles remote-ahead and diverged history
- **Conflict recovery**: on rebase conflict → `rebase --abort`, stash, `reset --hard origin/main`, re-apply log entry
- **Push retries**: exponential backoff (5s → 10s → 20s → 40s) for `timeout`/`connection`/`RPC failed`; special handling for `non-fast-forward` (re-syncs and retries)
- Auto-sets `user.name`/`user.email` if missing (runner-safe)

`bot.js` mirrors the same logic for Node.js stacks — swap the workflow step to use it.

---

## Workflow Details

`/.github/workflows/automation.yml`:
```yaml
on:
  schedule:
    - cron: "30 8 * * *"   # daily 08:30 UTC
  workflow_dispatch:         # manual trigger

permissions:
  contents: write            # required — lets GITHUB_TOKEN push

jobs:
  update-log:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4  # fetch-depth: 0 for full history / rebase
      - uses: actions/setup-python@v5
      - run: git config user.name ... && git config user.email ...
      - run: python3 bot.py
```

> **Cron note:** GitHub schedules are UTC and may lag ~0–15 min. Use `workflow_dispatch` for instant testing.

---

## Customization

- **Time:** edit `cron: "30 8 * * *"` via https://crontab.guru
- **Intensity:** commit 2–3x/day for darker graph squares — duplicate the bot step or adjust the quote loop
- **Content:** replace `QUOTES` with your TILs, LeetCode log, or habit tracker to make entries meaningful
- **Branch:** set `BRANCH = "master"` in `bot.py`/`bot.js` if your default branch differs
- **Node vs Python:** comment out the Python step and uncomment the Node step in the workflow to switch runtimes

---

## What Recruiters Should See Here

1. **Git fluency** — `fetch` → `rev-list` → `rebase --autostash` → conflict `abort`/`stash`/`reset`
2. **Resilient scripting** — retries, idempotency (minute dedup), and runner-safe identity setup
3. **CI/CD literacy** — cron scheduling, least-privilege `contents: write`, ephemeral runner debugging via `Verify push` logs
4. **Engineering honesty** — disclosed, auditable (`learning-log.txt` + Actions), not inflated

Pair with pinned product repos — this lab proves you can own automation, product repos prove you can ship features.

---

## License

MIT — use, fork, and adapt for your own portfolio. Attribution appreciated.

---

*Maintained as a live demo. Last automated update: see [`learning-log.txt`](./learning-log.txt) and [Actions](../../actions).*
