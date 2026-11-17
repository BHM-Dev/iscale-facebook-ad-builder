#!/usr/bin/env python3
"""Nightly feedback worker (Steve, 2026-11-17). Runs on the Mac Mini at 00:30 AST via launchd.

1. Reads open items (status 'new') from the Ad Builder's feedback inbox (app_feedback), including problems the
   11 p.m. ET Drive check filed there. Nothing open -> exits without starting Claude (no subscription usage).
2. Claims them (in_progress), resets its OWN clone of the repo to origin/develop (never the shared checkout).
3. Fetches the context Claude needs itself (recent API errors) so the agent never needs SSH or network.
4. Runs headless Claude Code on Steve's subscription (Sonnet) in restricted mode with the sandbox on: file tools,
   local tests and local git only. It commits a fix on feedback/<id8> or writes a proposal.
5. Safety checks every fix branch (allowed paths, size, secrets, based on develop), then pushes it and opens a PR to
   develop. Nothing is pushed to develop: develop deploys to production, so Steve merges.
6. Notes each item, DMs Steve one summary. A failed run puts its items back to 'new' for the next night.

Auth: Claude Code signed in on this Mac with Steve's subscription (`claude auth login`, stored in the Keychain).
Manual run: double-click "Run Feedback Worker.command", or `python3 worker.py --dry-run` (reads only, no Claude).
"""
import fcntl
import json
import os
import re
import secrets
import signal
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SHARED_REPO = Path("/Users/Steve1/Claude/AdBuilder")
CLONE = Path("/Users/Steve1/Claude/adbuilder-feedback-worker")          # the agent's copy: rebuilt every run, never trusted
CHECKER = Path("/Users/Steve1/Claude/adbuilder-feedback-worker-checker")  # clean copy the worker checks and pushes from
HERE = Path(__file__).resolve().parent
GH_REPO = "BHM-Dev/iscale-facebook-ad-builder"
VPS = "ubuntu@adbuilder.velocitymx.io"
SSH = ["ssh", "-T", "-i", str(Path.home() / ".ssh/id_ed25519"), "-o", "ConnectTimeout=20", "-o", "BatchMode=yes", VPS]
LOCK_FILE = Path.home() / "Library/Caches/adbuilder-feedback-worker.lock"
FAIL_MARKER = Path.home() / "Library/Logs/adbuilder-feedback-worker.FAILED"
MAX_ATTEMPTS = 2
# Every git command the worker itself runs: no hooks, no fsmonitor, no user/system config that could be steered.
GIT = ["git", "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=", "-c", "protocol.ext.allow=never",
       "-c", "diff.external=", "-c", "core.attributesFile=/dev/null"]
GIT_ENV = dict(os.environ, GIT_CONFIG_NOSYSTEM="1", GIT_TERMINAL_PROMPT="0")
MAX_ITEMS = int(os.getenv("FEEDBACK_WORKER_MAX_ITEMS", "3"))
CLAUDE_TIMEOUT = 5400          # 90 min for the whole batch
MAX_CHANGED_LINES = 200
UUID_RE = re.compile(r"^[0-9a-f-]{36}$")
DRY_RUN = "--dry-run" in sys.argv
os.environ["PATH"] = f"/opt/homebrew/bin:/usr/local/bin:{Path.home()}/.local/bin:/usr/bin:/bin:" + os.environ.get("PATH", "")

# A fix branch may only touch these; anything else (launch trigger files, money, auth, migrations, CI/deploy, scripts,
# settings) is refused even if the agent ignored its instructions.
ALLOWED_PREFIXES = ("backend/app/", "backend/tests/", "frontend/src/", "docs/features/")
FORBIDDEN = (
    "frontend/src/components/BulkAdCreation.jsx", "frontend/src/components/AdCreativeStep.jsx",
    "frontend/src/lib/facebookApi.js", "frontend/src/lib/authClient.js", "backend/app/services/facebook_service.py",
    "backend/app/models.py", "backend/app/main.py", "backend/app/core/", "backend/app/api/v1/auth.py",
    "backend/app/api/v1/users.py", "backend/app/api/v1/pnl.py", "backend/alembic/",
    "backend/app/services/drive_sync_service.py", "backend/app/services/drive_manifest_validator.py",
)
REDACT_RE = re.compile(r"(access_token|token|secret|password|api[_-]?key)=[^\s&\"']+", re.IGNORECASE)
SECRET_RE = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY|xox[abpr]-[0-9A-Za-z-]{10,}|sk-ant-[0-9A-Za-z_-]{10,}|gh[pousr]_[0-9A-Za-z]{20,}|AKIA[0-9A-Z]{16}|EAA[A-Za-z0-9]{40,}")


def log(msg):
    print(f"{datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%SZ} {msg}", flush=True)


def run(cmd, cwd=None, check=True, input_text=None, timeout=600, env=None):
    result = subprocess.run(cmd, cwd=cwd, input=input_text, capture_output=True, text=True, timeout=timeout, env=env)
    if check and result.returncode != 0:
        raise RuntimeError(f"{' '.join(map(str, cmd[:3]))}... failed ({result.returncode}): {result.stderr.strip()[:400]}")
    return result


def keychain(service):
    out = run(["security", "find-generic-password", "-a", os.environ.get("USER", "Steve1"), "-s", service, "-w"], check=False)
    return out.stdout.strip() or None


def sql(statement):
    """SQL against prod Postgres over SSH: reading the inbox and this worker's own status/note bookkeeping only."""
    return run(SSH + ["docker exec -i ad-builder-db psql -U postgres -d facebook_ad_builder -tA -v ON_ERROR_STOP=1"],
               input_text=statement, timeout=60).stdout.strip()


def lit(text):
    """Dollar-quoted literal with a random tag: nothing inside the text can end it."""
    tag = "q" + secrets.token_hex(6)
    return f"${tag}${str(text).replace(chr(0), '')}${tag}$"


def dm(text, failure=False):
    """DM Steve. If Slack can't be reached, fall back to a macOS notification and a marker file next to the log."""
    if DRY_RUN:
        log(f"DM (dry run, not sent): {text[:400]}")
        return
    token = keychain("bhm-slack-bot-token")
    ok = False
    if token:
        payload = json.dumps({"channel": "U6M6033G9", "text": ":hammer_and_wrench: *[Ad Builder feedback worker]*\n" + text[:3800],
                              "unfurl_links": False})
        out = run(["curl", "-sS", "-m", "20", "-X", "POST", "https://slack.com/api/chat.postMessage", "-H", f"Authorization: Bearer {token}",
                   "-H", "Content-Type: application/json; charset=utf-8", "-d", payload], check=False)
        try:
            ok = bool(json.loads(out.stdout or "{}").get("ok"))
        except ValueError:
            ok = False
    if not ok or failure:
        FAIL_MARKER.write_text(f"{datetime.now(timezone.utc).isoformat()} {text[:2000]}\n")
    if not ok:
        log(f"SLACK DM FAILED: {text[:400]}")
        run(["osascript", "-e", f'display notification "{text[:180].replace(chr(34), chr(39))}" with title "Ad Builder feedback worker"'], check=False)


def preflight():
    problems = []
    status = run(["claude", "auth", "status"], check=False)
    try:
        signed_in = json.loads(status.stdout or "{}").get("loggedIn") is True
    except ValueError:
        signed_in = False
    if not signed_in:
        problems.append("Claude Code isn't signed in on the Mini (run `claude auth login` in Terminal)")
    if run(["gh", "auth", "status"], check=False).returncode != 0:
        problems.append("gh is not signed in")
    if run(["which", "claude"], check=False).returncode != 0:
        problems.append("claude CLI not found")
    return problems


def open_items():
    raw = sql("SELECT coalesce(json_agg(t), '[]') FROM (SELECT id, created_at, user_email, page_path, message, "
              "screenshot_url, context FROM app_feedback WHERE status = 'new' ORDER BY created_at "
              f"LIMIT {MAX_ITEMS}) t;")
    return [i for i in json.loads(raw or "[]") if UUID_RE.match(str(i.get("id", "")))]


def recent_errors():
    out = run(SSH + ["docker logs --since 24h ad-builder-api 2>&1 | grep -E 'ERROR|Traceback|Exception|WARNING|\" [45][0-9][0-9] ' | tail -150"],
              check=False, timeout=60)
    if out.returncode != 0 and not out.stdout:
        return "(LOG FETCH FAILED: no API logs available tonight; don't conclude there were no errors)"
    text = REDACT_RE.sub(r"\1=[redacted]", out.stdout[-12000:])
    return SECRET_RE.sub("[redacted]", text)


def prepare_clone():
    """The agent's copy is deleted and re-cloned every run, so nothing it leaves in .git or node_modules survives."""
    if CLONE.exists():
        run(["rm", "-rf", str(CLONE)])
    run(["gh", "repo", "clone", GH_REPO, str(CLONE), "--", "-q"], timeout=600)
    run(GIT + ["checkout", "-q", "--detach", "origin/develop"], cwd=CLONE, env=GIT_ENV)
    run(["npm", "ci", "--no-audit", "--no-fund"], cwd=CLONE / "frontend", timeout=900)
    if not (CHECKER / ".git").exists():
        run(["gh", "repo", "clone", GH_REPO, str(CHECKER), "--", "-q"], timeout=600)
    run(GIT + ["fetch", "-q", "--prune", "origin"], cwd=CHECKER, timeout=300, env=GIT_ENV)
    run(GIT + ["checkout", "-q", "--detach", "origin/develop"], cwd=CHECKER, env=GIT_ENV)
    for branch in run(GIT + ["branch", "--list", "feedback/*", "--format=%(refname:short)"], cwd=CHECKER, env=GIT_ENV).stdout.split():
        run(GIT + ["branch", "-D", branch], cwd=CHECKER, check=False, env=GIT_ENV)
    return run(GIT + ["rev-parse", "origin/develop"], cwd=CHECKER, env=GIT_ENV).stdout.strip()


def claude_settings():
    # Sandbox for every Bash command: no network, writes only inside the clone. Belt and braces on top of the tool
    # allowlist, because the prompt carries text from other people (feedback messages, Drive file names).
    home = str(Path.home())
    deny = [f"{home}/{p}" for p in (".ssh", ".config/gh", "Library/Keychains", ".bhm_secrets", ".aws", ".netrc",
                                    "Claude/AdBuilder", "Claude/bhm-context", str(CHECKER.relative_to(Path.home())))]
    return json.dumps({"sandbox": {"enabled": True, "autoAllowBashIfSandboxed": False, "allowUnsandboxedCommands": False,
                                   "failIfUnavailable": True, "filesystem": {"denyRead": deny}}})


def run_claude(items, errors_text):
    results_path = CLONE / ".feedback-results.json"
    results_path.unlink(missing_ok=True)
    prompt = ((HERE / "prompt.md").read_text()
              + "\n" + json.dumps(items, indent=2, default=str)
              + "\n\nRECENT API ERRORS AND WARNINGS (last 24h, fetched for you; you have no SSH):\n" + (errors_text or "(none)"))
    env = dict(os.environ)
    env.pop("ANTHROPIC_API_KEY", None)   # never fall back to API billing
    git_ok = ["status", "diff", "log", "show", "checkout", "add", "commit", "rev-parse", "restore"]
    cmd = ["claude", "-p", prompt, "--model", "sonnet", "--permission-mode", "acceptEdits", "--max-turns", "150",
           "--restricted", "--settings", claude_settings(),
           "--tools", "Read", "Edit", "Write", "Grep", "Glob", "Agent", "Bash",
           "--allowedTools", "Read", "Edit", "Write", "Grep", "Glob", "Agent",
           *[f"Bash(git {sub}:*)" for sub in git_ok],
           "Bash(python3 -m pytest:*)", "Bash(npx vitest run:*)", "Bash(npx vite build:*)",
           "--disallowedTools", "Bash(git push:*)", "Bash(git remote:*)", "Bash(git config:*)", "Bash(git -C:*)",
           "WebFetch", "WebSearch"]
    proc = subprocess.Popen(cmd, cwd=CLONE, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            start_new_session=True)
    try:
        output, _ = proc.communicate(timeout=CLAUDE_TIMEOUT)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)   # claude and everything it started (tests, builds)
        output, _ = proc.communicate()
        return -9, (output or "")[-2000:] + "\n[timed out]", []
    results = []
    if results_path.exists():
        try:
            results = [r for r in json.loads(results_path.read_text()) if isinstance(r, dict)]
        except ValueError:
            results = []
    return proc.returncode, (output or "").strip(), results


def import_branch(branch):
    """Copy the agent's branch into the clean checker clone. Only objects and the one ref come across; the agent's
    config and hooks are never read (the worker's git runs with hooks off and no repo-steerable config)."""
    run(GIT + ["fetch", "-q", "--no-tags", str(CLONE), f"+refs/heads/{branch}:refs/heads/{branch}"], cwd=CHECKER, env=GIT_ENV)


def check_branch(branch, develop_sha):
    """Hard gate before anything is pushed. Returns a reason string when the branch must not become a PR."""
    if not re.fullmatch(r"feedback/[0-9a-f]{8}", branch or ""):
        return f"unexpected branch name {branch!r}"
    try:
        import_branch(branch)
    except Exception:
        return f"{branch} doesn't exist in the agent's copy"
    g = lambda *args: run(GIT + list(args), cwd=CHECKER, env=GIT_ENV).stdout   # noqa: E731
    if g("merge-base", develop_sha, f"refs/heads/{branch}").strip() != develop_sha:
        return "not based on the current develop"
    diff_opts = ["--no-renames", "--no-textconv", "--no-ext-diff"]
    raw = g("diff", "--raw", *diff_opts, f"{develop_sha}...refs/heads/{branch}")
    if any(" 120000 " in line or " 160000 " in line for line in raw.splitlines()):
        return "adds a symlink or submodule"
    files = [f for f in g("diff", "--name-only", *diff_opts, f"{develop_sha}...refs/heads/{branch}").split("\n") if f]
    if not files:
        return "no changes"
    bad = [f for f in files if not f.startswith(ALLOWED_PREFIXES) or any(f == p or f.startswith(p) for p in FORBIDDEN)]
    if bad:
        return "touches files the worker may not change: " + ", ".join(bad[:5])
    changed = 0
    for line in g("diff", "--numstat", *diff_opts, f"{develop_sha}...refs/heads/{branch}").splitlines():
        added, removed = (line.split("\t") + ["0", "0"])[:2]
        changed += (int(added) if added.isdigit() else 0) + (int(removed) if removed.isdigit() else 0)
    if changed > MAX_CHANGED_LINES:
        return f"too large for an overnight fix ({changed} changed lines)"
    if SECRET_RE.search(g("diff", *diff_opts, f"{develop_sha}...refs/heads/{branch}")):
        return "the diff looks like it contains a secret"
    return None


def open_pr(item, result, develop_sha):
    branch = result.get("branch", "")
    reason = check_branch(branch, develop_sha)
    if reason:
        raise RuntimeError(f"safety check refused the fix: {reason}")
    existing = run(["gh", "pr", "list", "--repo", GH_REPO, "--head", branch, "--json", "url", "--jq", ".[0].url"], check=False).stdout.strip()
    if existing:
        return f"{existing} (already open; left as is)"
    # Explicit full refspec from the clean checker clone: only refs/heads/feedback/<id8>, never develop.
    run(GIT + ["-c", "credential.helper=", "-c", "credential.helper=!gh auth git-credential",
               "push", "-q", "origin", f"refs/heads/{branch}:refs/heads/{branch}"], cwd=CHECKER, timeout=180, env=GIT_ENV)
    if existing:
        return existing
    body = (f"From in-app feedback `{item['id']}` ({item.get('user_email') or 'unknown'}, page `{item.get('page_path')}`):\n\n"
            f"> {str(item.get('message', ''))[:1500]}\n\n**What changed:** {str(result.get('summary', ''))[:1500]}\n\n"
            f"**Verified:** {str(result.get('verification', 'see commits'))[:800]}\n\n"
            "Prepared overnight by the feedback worker (Claude Code on the Mac Mini), passed its path/size/secret checks. "
            "Merging deploys to production.\n\n🤖 Generated with [Claude Code](https://claude.com/claude-code)")
    title = (str(result.get("title") or "").strip() or f"Feedback {item['id'][:8]}")[:120]
    pr = run(["gh", "pr", "create", "--repo", GH_REPO, "--base", "develop", "--head", branch, "--title", title, "--body", body],
             cwd=CHECKER, timeout=120)
    lines = pr.stdout.strip().splitlines()
    return lines[-1] if lines else "(PR created, no URL returned)"


def release(item_ids, reason):
    """Put claimed items back for the next night, unless someone changed them meanwhile. After MAX_ATTEMPTS failed runs
    an item stays in_progress with a note instead, so one bad item can't burn a run every night."""
    if not item_ids:
        return
    ids = ", ".join(lit(i) for i in item_ids)
    attempts = "coalesce((soft_tags->>'worker_attempts')::int, 0) + 1"
    sql(f"UPDATE app_feedback SET updated_at = now(), "
        f"soft_tags = (coalesce(soft_tags::jsonb, '{{}}'::jsonb) || jsonb_build_object('worker_attempts', {attempts}))::json, "
        f"status = CASE WHEN {attempts} >= {MAX_ATTEMPTS} THEN 'in_progress' ELSE 'new' END, "
        f"resolution_note = CASE WHEN {attempts} >= {MAX_ATTEMPTS} "
        f"THEN {lit('Nightly worker failed twice on this item; it needs a look in a session. Last error: ' + reason)} "
        f"ELSE {lit('Nightly worker will retry: ' + reason)} END "
        f"WHERE id IN ({ids}) AND status = 'in_progress';")


def shared_repo_state():
    head = run(["git", "rev-parse", "HEAD"], cwd=SHARED_REPO, check=False).stdout.strip()
    branch = run(["git", "branch", "--show-current"], cwd=SHARED_REPO, check=False).stdout.strip()
    return head, branch


def main():
    lock = open(LOCK_FILE, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)   # released by the OS if this process dies
    except BlockingIOError:
        log("already running")
        return 0
    claimed = []
    try:
        try:
            items = open_items()
        except Exception as exc:
            dm(f"Couldn't read the feedback inbox: {str(exc)[:300]}")
            return 1
        if not items:
            log("nothing open")
            return 0
        problems = preflight()
        if problems:
            dm(f"{len(items)} feedback item(s) are waiting, but the worker can't run: " + "; ".join(problems))
            return 1
        if DRY_RUN:
            log(f"dry run: would work {len(items)} item(s): " + ", ".join(i['id'][:8] for i in items))
            return 0
        ids = ", ".join(lit(i["id"]) for i in items)
        got = sql(f"UPDATE app_feedback SET status = 'in_progress', updated_at = now(), resolution_note = "
                  f"'Nightly worker started ' || now()::date WHERE id IN ({ids}) AND status = 'new' RETURNING id;")
        claimed = [line.strip() for line in got.splitlines() if UUID_RE.match(line.strip())]
        items = [i for i in items if i["id"] in claimed]
        if not items:
            log("items were claimed elsewhere")
            return 0
        ids = ", ".join(lit(i) for i in claimed)
        shared_before = shared_repo_state()
        develop_sha = prepare_clone()
        rc, final_text, results = run_claude(items, recent_errors())
        run(GIT + ["fetch", "-q", "origin"], cwd=CHECKER, timeout=300, env=GIT_ENV)
        develop_after = run(GIT + ["rev-parse", "origin/develop"], cwd=CHECKER, env=GIT_ENV).stdout.strip()
        alarms = []
        if develop_after != develop_sha:
            alarms.append(f"origin/develop moved during the run ({develop_sha[:7]} -> {develop_after[:7]}); usually someone else's push, but check it wasn't the worker")
        if shared_repo_state() != shared_before:
            alarms.append("the shared checkout's HEAD/branch changed during the run; check it")
        if rc != 0 and not results:
            # A usage limit, expired login or crash is not a verdict on the items: put them back for tomorrow.
            release(claimed, "Claude didn't finish")
            claimed = []
            dm(f"Claude didn't finish (exit {rc}); {len(items)} item(s) returned to the queue (each gets {MAX_ATTEMPTS} tries).\n"
               f"{final_text[-600:]}" + ("\n:rotating_light: " + " | ".join(alarms) if alarms else ""), failure=True)
            return 1
        by_id = {r.get("id"): r for r in results}
        lines = []
        for item in items:
            result = by_id.get(item["id"])
            short = f"#{item['id'][:6]} ({item.get('page_path')})"
            if not result:
                note, line = "Nightly worker produced no result for this item; it needs a look in a session.", f"• {short}: no result, needs a look"
            elif result.get("outcome") == "pr":
                try:
                    url = open_pr(item, result, develop_sha)
                    note, line = f"Fix ready for review: {url}", f"• {short}: PR {url} — {str(result.get('summary', ''))[:200]}"
                except Exception as exc:
                    note = f"A fix was prepared but not opened as a PR: {str(exc)[:300]}"
                    line = f"• {short}: fix NOT opened ({str(exc)[:200]})"
            else:
                note = f"Proposed (no code changed): {str(result.get('summary', ''))}"[:3800]
                line = f"• {short}: proposal — {str(result.get('summary', ''))[:250]}"
            sql(f"UPDATE app_feedback SET resolution_note = {lit(note)}, updated_at = now() WHERE id = {lit(item['id'])} AND status = 'in_progress';")
            lines.append(line)
        claimed = []
        header = f"{len(items)} feedback item(s) worked overnight:"
        if alarms:
            header = ":rotating_light: " + " | ".join(alarms) + "\n" + header
        dm(header + "\n" + "\n".join(lines) + "\nMerge a PR to deploy it; mark items Done in the Feedback inbox.", failure=bool(alarms))
        if not alarms:
            FAIL_MARKER.unlink(missing_ok=True)
        log(header.replace("\n", " ") + " " + " | ".join(lines))
        return 0
    except Exception as exc:
        if claimed:
            try:
                release(claimed, "worker failed: " + str(exc)[:300])
            except Exception:
                pass
        dm(f"Feedback worker failed: {str(exc)[:500]}" + (f" ({len(claimed)} item(s) returned to the queue)" if claimed else ""), failure=True)
        log(f"failed: {exc}")
        return 1
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()


if __name__ == "__main__":
    sys.exit(main())
