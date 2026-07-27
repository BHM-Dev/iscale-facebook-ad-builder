# Ad Builder — Raw Feedback from Joel & Abel (source material for synthesis)

Extracted from Slack #media-buying (C08G7PJJ6NB) + auto group DM (C0BG015BAJU), 2026-06 → 2026-07-23.
This is the RAW source. The synthesis/ranking task is defined in the Codex prompt that accompanies this file.

---

## Steven's 6 homework questions (asked 2026-07-20) — STILL UNANSWERED
Joel + Abel plan to answer these together on a joint call (Abel wants to align with Joel first). No written answers yet.
1. When you build a new ad today, where do you actually do it, and what's step one? (Ads Manager, Canva, designer, etc.)
2. Biggest reason you DON'T create ads in the app — rank: image quality / output looks too "AI" / too slow / doesn't fit your process / output needs rework before runnable / something else.
3. Do you start from a proven winner and iterate, or from scratch? If from a winner — what do you keep vs. swap?
4. The AI-generated images — runnable as-is, need edits, or not usable? What's off (wrong scene / looks AI / baked-on text style)?
5. One thing the app could nail that would make you build in it instead of Meta?
6. (optional) What does the app already do that you'd miss if it vanished?

---

## Abel — feedback (newest first, 2026-07-23)
- **BIGGEST ISSUE (accuracy):** "revenue is inaccurate and getting pulled from somewhere inflating ROAS" — on BOTH DIN Auto and THS. (2 screenshots with notes were attached in Slack — not captured here.)
- After the scoped-403 fix: "dashboard metrics are accurate now for both accounts" — so the account-scoping/metrics-loading is resolved; revenue/ROAS inflation is a SEPARATE, still-open problem.
- **"Needs Attention" notice** firing oddly — flagged on THS (which is paused): "pointing that 'Needs Attention' notice out now in case it's something that will continue to occur across accounts." (i.e. paused accounts/ad sets may be wrongly flagged as needing attention.)
- Earlier (the now-FIXED scoped-403 bug): error top-right on login, dashboard no data, Campaign Performance showed campaign/ad set NAMES but no metrics, Sync errored. RESOLVED in commit 300661c.

## Joel — feedback themes (verbatim highlights, newest first)
- **Arcads tool interest (2026-06-18, 2026-07-23):** "I just found a CRAZY ad workflow... Arcads, they do video, but now they have workflows and they do static." / "we should crank out a few creatives with the tools as well, a few videos... see which tool is best." (Actively comparing our tool vs. Arcads for creative generation.)
- **Profit column (2026-06-17):** "I think we need a profit column. ROAS is great and helpful, but we want to know profit right?"
- **Model competitor landing pages (2026-06-17, 2026-06-20):** shared Geico (`geico.com/landingpage/go558`) — "SO Good"; commercial trucking quote form — "Thats a great page for trucking. Maybe we can model it for something else?"
- **Research → Build-from-ad was broken (2026-06-17):** "I tried making an ad from the research tab, but it didn't work. It took me to a screen and asked if I wanted to model a live ad, but the goal was to model an ad that was found." → FIXED (drops into Brand step now).
- **Dashboard/pausing usefulness (2026-06-14):** "Thing like pausing to save is not that helpful, there are a lot of layers — ad sets, ads, are we split testing landing pages behind it, what day of the week is it." / "this needs a lot of thought or it will just be a lot of bloat." Prefers date views: previous day, last 3, last 7, last 14.
- **CBO/ABO budget display confusion (2026-06-16):** rows showed "CBO" with no dollar amount / some showed ad set not campaign budget. → mostly FIXED (Sync populates, +20% tooltip clarifies campaign-level).
- **Image niche-awareness (2026-06-12):** barber/bartender wrong-scene bug → FIXED (niche-aware prompt).
- Tracking/click-loss issues (2026-06-16, 2026-06-22): "Missing about half of our clicks", Meta burst-spending — these are MetaSide/RedTrack tracking issues, largely NOT app bugs.
- Quick Generate (shipped 2026-07-23): feedback requested, not yet returned.

## Codex/ChatGPT pre-push review flags (2026-07-23, still-open UX risks)
- **P1:** Dashboard called `/facebook/adsets/saved` without `ad_account_id` while metrics were account-scoped → names from both accounts, numbers only for selected. (May be resolved by the scoped-default fix — needs confirming.)
- **P1:** Account switcher changes header immediately but old ad set rows persist until fetch returns (stale clickable rows).
- **P2:** RedTrack manual Sync only accepts `date_preset`, refreshes global cache (not account/custom-date scoped) — misleading for custom ranges.
- **P2:** Ad-level RedTrack pull (`/redtrack/report/sub1`) is global, not account-scoped; stale `rtAdsBulk` can persist on fetch failure.
- **P2:** "Quick Generate from winners" button shows on EVERY ad, not just winners — Joel may generate from a loser thinking it's a winner.

## Already shipped this cycle (do NOT re-rank as new work)
Account switcher; account-scoped campaign list; hard per-account enforcement; scoped-403 fix; Copy Library spend+CPL + CPL-weighted few-shot; Quick Generate from winner; niche-aware images; Research build-from-ad fix; CBO budget display.
