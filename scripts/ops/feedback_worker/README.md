# Nightly feedback worker (Mac Mini)

Every night at **00:30 AST**, this job works the Ad Builder's feedback inbox (`/feedback`). That covers items people
sent with **Send feedback**, plus problems the **11 p.m. ET Drive check** filed because the Ad Builder has to fix
them (not manifest mistakes, which go to Joel).

- If nothing is open, it exits without starting Claude, so no usage.
- Otherwise it runs **Claude Code on Steve's subscription** (Sonnet), never the API.
- Each item becomes either a **pull request to `develop`** with a small, tested, reviewed fix, or a written proposal.
- It never pushes to `develop` (that deploys to production). Steve merges.
- Up to 3 items a night, 90-minute cap.
- One Slack DM to Steve with the results. Each item's note in the inbox gets the PR link or proposal.

**Run it now:** double-click `Run Feedback Worker.command`, or `python3 worker.py --dry-run` to see what it would
pick up without changing anything.

**Files:** `worker.py` (the job), `prompt.md` (Claude's instructions and limits),
`com.bhm.adbuilder-feedback-worker.plist` (installed in `~/Library/LaunchAgents`).
Log: `~/Library/Logs/adbuilder-feedback-worker.log`.
Worktree: `~/Claude/adbuilder-feedback-worker`. It's separate from the shared checkout.

**Needs:** Claude Code logged in on the Mini (steve1), `gh` logged in with push access to BHM-Dev, the VPS SSH key,
and Keychain item `bhm-slack-bot-token`. It's a user LaunchAgent because `claude` and `gh` keep their sign-in in
steve1's login keychain, which a system daemon can't read.
