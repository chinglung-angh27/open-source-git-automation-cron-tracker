#!/usr/bin/env node
/**
 * Open-Source Git Automation & Cron Tracker — bot.js
 * Node.js port of bot.py — same behavior, same robustness.
 *
 * Usage: node bot.js
 * Requires: Node >= 18, git in PATH
 */
import { execSync, spawnSync } from "node:child_process";
import { appendFileSync, readFileSync, existsSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = __dirname;
const LOG_FILE = join(REPO_ROOT, "learning-log.txt");
const BRANCH = "main";
const MAX_PUSH_RETRIES = 4;
const RETRY_BASE_SECONDS = 5;

const QUOTES = [
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
];

function run(cmd, opts = {}) {
  const { check = true, capture = false } = opts;
  console.log(`$ ${cmd}`);
  const result = spawnSync(cmd, { shell: true, cwd: REPO_ROOT, encoding: "utf-8" });
  if (capture && result.stdout) console.log(result.stdout.trim());
  if (result.stderr) console.error(result.stderr.trim());
  if (check && result.status !== 0) throw new Error(`Command failed (${result.status}): ${cmd}`);
  return result;
}

function ensureGitRepo() {
  if (!existsSync(join(REPO_ROOT, ".git"))) {
    console.error("ERROR: Not a git repository. Run `git init` first.");
    process.exit(1);
  }
}

function getCurrentBranch() {
  const r = run("git rev-parse --abbrev-ref HEAD", { capture: true, check: false });
  return r.stdout.trim();
}

function hasRemote() {
  const r = run("git remote", { capture: true, check: false });
  return Boolean(r.stdout.trim());
}

function hasUpstream() {
  const r = spawnSync("git rev-parse --abbrev-ref --symbolic-full-name @{u}", {
    shell: true, cwd: REPO_ROOT, encoding: "utf-8",
  });
  return r.status === 0;
}

function syncWithRemote(branch) {
  if (!hasRemote()) { console.log("No remote — skipping sync."); return; }
  if (!hasUpstream()) { console.log(`No upstream for ${branch} — skipping pull.`); return; }

  console.log(`Fetching and rebasing onto origin/${branch}...`);
  run(`git fetch origin ${branch}`, { check: false });

  const lr = run(`git rev-list --left-right --count origin/${branch}...HEAD`, { capture: true, check: false });
  if (lr.status === 0) {
    const [behind, ahead] = lr.stdout.trim().split(/\s+/).map(Number);
    if (behind === 0) { console.log(`Already up-to-date with origin/${branch} (ahead ${ahead}).`); return; }
    console.log(`Behind ${behind}, ahead ${ahead} — rebasing...`);
  }

  const result = run(`git pull --rebase --autostash origin ${branch}`, { check: false });
  if (result.status !== 0) {
    console.error("Rebase failed — handling conflict...");
    const status = run("git status --porcelain", { capture: true, check: false });
    if (status.stdout.trim()) {
      console.error("Conflict detected. Aborting rebase, resetting to remote...");
      run("git rebase --abort", { check: false });
      run('git stash push -m "bot-autostash-conflict" --keep-index', { check: false });
      run(`git reset --hard origin/${branch}`, { check: false });
      const stashed = run("git stash list", { capture: true, check: false });
      if (stashed.stdout.includes("bot-autostash-conflict")) run("git stash pop", { check: false });
    } else {
      run("git rebase --abort", { check: false });
      throw new Error("Rebase failed for unknown reason");
    }
  }
}

function appendLogEntry() {
  const now = new Date();
  const utc = now.toISOString().replace("T", " ").slice(0, 19) + " UTC";
  const quote = QUOTES[Math.floor(Math.random() * QUOTES.length)];
  const entry = `[${utc}] ${quote}\n`;

  if (existsSync(LOG_FILE)) {
    const lines = readFileSync(LOG_FILE, "utf-8").split("\n").slice(-5);
    const minuteKey = utc.slice(0, 16); // YYYY-MM-DD HH:MM
    if (lines.some((l) => l.includes(minuteKey))) {
      console.log("Entry for this minute already exists — skipping (idempotent).");
      return false;
    }
  }
  appendFileSync(LOG_FILE, entry, "utf-8");
  console.log(`Appended: ${entry.trim()}`);
  return true;
}

function sleep(ms) { Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms); }

function gitCommitAndPush(branch) {
  run(`git add "${LOG_FILE}"`);
  const diff = run("git diff --cached --quiet", { check: false });
  if (diff.status === 0) { console.log("No staged changes — nothing to commit."); return; }

  const now = new Date().toISOString().slice(0, 10);
  run(`git commit -m "chore(log): daily update ${now} [skip ci]"`);

  if (!hasRemote()) { console.log("No remote — commit created locally only."); return; }

  for (let attempt = 1; attempt <= MAX_PUSH_RETRIES; attempt++) {
    const result = run(`git push origin ${branch}`, { check: false });
    if (result.status === 0) { console.log(`Pushed to origin/${branch} (attempt ${attempt}).`); return; }

    const stderr = (result.stderr || "") + (result.stdout || "");
    const lower = stderr.toLowerCase();
    const isNetwork = ["timeout", "unable to access", "could not resolve", "connection", "rpc failed", "broken pipe"].some(s => lower.includes(s));
    const isNonFastForward = lower.includes("non-fast-forward") || lower.includes("fetch first");

    if (isNonFastForward) {
      console.log(`Push rejected (non-fast-forward) — re-syncing (attempt ${attempt}/${MAX_PUSH_RETRIES})...`);
      syncWithRemote(branch);
      appendLogEntry();
      run(`git add "${LOG_FILE}"`, { check: false });
      const d2 = run("git diff --cached --quiet", { check: false });
      if (d2.status !== 0) run(`git commit -m "chore(log): retry update ${now} [skip ci]"`, { check: false });
      continue;
    }
    if (isNetwork && attempt < MAX_PUSH_RETRIES) {
      const wait = RETRY_BASE_SECONDS * Math.pow(2, attempt - 1) * 1000 + Math.random() * 1000;
      console.log(`Network error — retrying in ${(wait/1000).toFixed(1)}s...`);
      sleep(wait);
      continue;
    }
    if (attempt === MAX_PUSH_RETRIES) {
      console.error(`Push failed after ${MAX_PUSH_RETRIES} attempts.`);
      console.error(stderr);
      process.exit(1);
    }
    sleep(RETRY_BASE_SECONDS * attempt * 1000);
  }
}

function main() {
  console.log(`=== Git Automation Bot — ${new Date().toISOString()} ===`);
  ensureGitRepo();
  let branch = getCurrentBranch();
  if (branch === "HEAD") { console.log(`Detached HEAD — using ${BRANCH}`); branch = BRANCH; }

  const email = spawnSync("git config user.email", { shell: true, cwd: REPO_ROOT, encoding: "utf-8" }).stdout.trim();
  const name = spawnSync("git config user.name", { shell: true, cwd: REPO_ROOT, encoding: "utf-8" }).stdout.trim();
  if (!email) { console.log("No git user.email — setting bot identity."); run('git config user.email "4bd23cs046@bietdvg.edu"'); }
  if (!name) run('git config user.name "automation-bot"');

  syncWithRemote(branch);
  appendLogEntry();
  gitCommitAndPush(branch);
  console.log("=== Done ===");
}

main();
