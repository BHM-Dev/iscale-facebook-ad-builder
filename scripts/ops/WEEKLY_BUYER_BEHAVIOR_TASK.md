# Weekly buyer-behavior task (prompt)

Schedule: Mondays at 11:00 local.

---

Weekly buyer-behavior and profit review for the BHM Ad Builder's RHO commercial insurance accounts: RHO `act_521142087204815` and RHO 4 `act_737291135429748`. The goal is a growing, evidence-based model of how Joel and Abel manage ad sets, so Steve can scale while maximizing monthly profit.

**Strictly read-only:**
- No Meta changes.
- Don't approve or dismiss proposals.
- No Slack messages.
- No pushes to the Ad Builder repo.

## 1. Read the context

- `/Users/Steve1/Claude/bhm-context/projects/facebook-ad-builder/buyer-behavior.md`: the data traps and the baseline.
- `/Users/Steve1/Claude/AdBuilder/docs/features/approvals-queue.md`.

## 2. Pull the data

Run these scripts inside the production API container:
- `scripts/ops/buyer_behavior_profile.py`, once with `-e DAYS=7` added to the `docker exec` and once without it (default 28).
- `scripts/ops/buyer_reactivation_probe.py`.
- `scripts/ops/proposals_backtest.py`.

To run each one:
```bash
scp -i ~/.ssh/id_ed25519 <file> ubuntu@adbuilder.velocitymx.io:/tmp/<unique>.py
```
```bash
ssh -i ~/.ssh/id_ed25519 ubuntu@adbuilder.velocitymx.io 'docker cp /tmp/<unique>.py ad-builder-api:/tmp/<unique>.py && docker exec -w /app -e PYTHONPATH=/app ad-builder-api python /tmp/<unique>.py; docker exec ad-builder-api rm /tmp/<unique>.py; rm /tmp/<unique>.py'
```

- Never name a temp file after a standard-library module (no `re.py`, `json.py` and so on).
- Space out Meta calls, because Meta rate-limits per ad account.

Also pull:
- `ps.shadow_report(db, acct, 7)` for both accounts;
- the last 7 days of `action_proposals` rows.

## 3. Analyze against the baseline

Cover each of these:
- Changes in the thresholds Joel and Abel use to pause, raise and trim.
- True kills vs edit toggles: exclude pauses that were reactivated within 1 hour.
- Pauses that were profitable by revenue, and what those ad sets did afterwards.
- Raises the queue proposed that people skipped, with the 3-day outcome.
- Revenue-losing ad sets with 3-day spend of $150 or more that nobody paused.
- Weekly profit (Switchboard revenue − Meta spend) vs the prior week, and month-to-date pace.
- Revenue per lead by niche.

## 4. Record the results

- Append a dated entry under "## Weekly log" in `buyer-behavior.md`:
  - numbers first, 5–12 bullets;
  - tag each finding confirmed, emerging or one-off.
- Update the baseline or the "rules" sections only when 3 or more weeks agree.
- Present any trigger change as a proposal that needs Joel's and Abel's sign-off.
- Commit only that file in `~/Claude/bhm-context`, using `git add <path>`, then push.
- If the push is rejected, run `git pull --rebase` **without** `--autostash`. If there are uncommitted local edits, commit nothing else and stop to report instead.

## 5. Finish

End with a 3-line summary:
1. The biggest profit lever.
2. Any change in buyer patterns.
3. Anything that needs Steve.
