# Ad Builder — Research Library UX Reset

## Executive summary

The current Research page opens on a raw scrape gallery. That makes its useful output—reviewed competitor patterns—hard to find and makes the page feel like an admin console rather than a media-buying tool.

The MVP makes the default view a **Research Brief** for the selected vertical. It surfaces only reviewed external discoveries, the audience/segment, the reusable structural takeaway, and a direct path to inspect or build from that reference. The raw Ad Library remains available as a secondary workspace for operator search and capture.

## Flow

`Research → choose Commercial / Auto / Home Services → Research Brief → inspect a finding → Build from this ad`

`Research Brief → Open Ad Library → search/capture/filter raw competitor ads`

## MVP specification

- Default to **Research Brief**; retain selection across the current browser session.
- Show only externally reviewed source captures in the Brief, clearly labeled as directional source research—not performance or claim proof.
- Keep the selected vertical visible and make Home Services sub-vertical selection explicit.
- Move import, refresh, and clear actions under **Manage research**. They are operator controls, not the primary user task.
- Keep the full card gallery, query search, filters, boards, and raw-capture workflow under **Ad Library**.
- Empty Brief state directs the user to the Ad Library without implying an API refresh is the only way to add insight.

## Measurement

- Track first interaction: Brief finding opened, Ad Library opened, source saved, Build from this ad.
- Success metric: Joel can identify one usable competitor pattern and enter the build flow in under two minutes.

## Phase 2

- Brief-level brand summaries: active ads, format mix, top landings, and latest capture date from public Meta captures.
- Pin/retire reviewed findings and support a one-sentence BHM takeaway separate from source copy.
