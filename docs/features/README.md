# Ad Builder — Feature Log

One file per section of the app. Each says **what it does, what protects money, which endpoints it
uses, what is verified vs not, and what's still open** — so anyone (Joel, Golden, Dan, Akini, Codex,
Claude) can see what exists and why before changing it. Update the file in the same PR as the change.

| Section | File | Status |
|---|---|---|
| Campaign Performance (`/campaign-performance`) | [campaign-performance.md](campaign-performance.md) | Money-safety hardening shipped 2026-10-06/07; Pause/Resume live-click verification pending |
| Dashboard (`/`) — budget/scale/pause actions | [dashboard.md](dashboard.md) | Live-budget confirm shipped 2026-10-07; click-through verification pending |
| Ad Launcher (Campaign → Ad Set → Drive picker → Review → Launch) | [ad-launcher.md](ad-launcher.md) | Live status gate shipped; browser-verified 2026-10-06 |

## How to add / update an entry
- Newest change first in the **Changelog**, with the commit hash.
- Mark each claim **Verified in production** (and how/when) or **Unit-tested only** or **Not verified**.
  "Code Claude/Codex said it built it" is not "it's working".
- List known gaps under **Open items** instead of leaving them in chat or commit messages.
- Money-affecting changes: note the guardrail, its threshold, and where it is enforced
  (UI vs server). Server-side is the one that counts.
