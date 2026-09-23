# Ad Builder — Launcher UX Phase 1
## Claude Build Brief

**Status:** Ready for implementation  
**Scope:** Frontend layout and workflow simplification only  
**Primary user:** Joel Welch, media buyer  
**Primary route:** `/facebook-campaigns`  
**Date:** 2026-09-18

## 1. Executive summary

The Ad Builder launcher is functionally capable but visually clunky. The current experience spreads a single launch workflow across a six-step wizard, conditional modes, nested dialogs, and large components. Joel often has to remember what he selected, how many ads the current inputs will create, which creative source is active, and whether the current screen is setup or review.

Phase 1 should make the launcher feel like one coherent workspace:

```text
Account / Campaign / Ad Set context
              ↓
Creative source + live count
              ↓
Preview and validate
              ↓
One clear launch action
```

The goal is not to add launch capability. The goal is to make existing capability discoverable, understandable, and faster to operate.

The build must preserve the existing Meta payloads, Drive pairing, rate-limit protection, partial-failure handling, auto-skip behavior, naming logic, and launch safety defaults.

## 2. UX principles to apply

These principles are synthesized from the live GetHookd, Adnova, AdEspresso, Birch, RyzeAI, and AdStellar reviews:

1. **Persistent context:** account, campaign, and ad set remain visible after selection.
2. **One primary action per screen:** secondary actions use outline, ghost, or text treatment.
3. **Progressive disclosure:** scan first; edit details in a drawer.
4. **Show the multiplication early:** always show how many ads the current inputs produce.
5. **Make the next action obvious:** every step should have one clear continuation action.
6. **Reuse should be as easy as starting fresh:** Drive, Generated Ads, and existing creative paths must be first-class sources.
7. **Review before spend:** the final screen must show what will actually be sent to Meta.
8. **Use compact summaries:** completed selections should collapse into readable pills instead of taking over the screen.
9. **Layer status communication:** long-running or risky actions need a summary status plus inline detail.
10. **Do not make Joel re-enter information already known to the app.**

## 3. Current flow and files

Current route and major components:

```text
/facebook-campaigns
  FacebookCampaigns.jsx
    CampaignStep.jsx
    AdSetStep.jsx
    AdCreativeStep.jsx
    BulkAdCreation.jsx
```

Relevant existing behavior to preserve:

- Account, campaign, and ad-set selection.
- Drive Creative Library pairing and manifest handling.
- Generated Ads Library selection.
- Upload/manual creative paths.
- Headline/body/CTA validation and Meta limits.
- Dynamic ad naming already wired in bulk creation.
- Live variation math used by `AdCreativeStep.jsx` and `BulkAdCreation.jsx`.
- Preview-grid review screen and per-ad exclusion/undo behavior.
- Meta rate-limit checks and partial-failure reconciliation.
- PAUSED launch safety default unless current product behavior explicitly requires otherwise.
- Existing auto-skip and quick-target handoffs.

Do not touch in this phase:

- `backend/app/services/facebook_service.py`.
- Meta API request shapes.
- Database models or migrations.
- Server-side launch drafts.
- Meta Batch API work.
- Targeting permutations.
- New audience presets.
- New review/approval state.
- New analytics backend.

## 4. Target layout

### Desktop wireframe

```text
┌─────────────────────────────────────────────────────────────────────────┐
│ Launch Ads                                                              │
│ RHO - Commercial Insurance  /  Campaign Name  /  Ad Set Name           │
├────────────────┬───────────────────────────────────────┬────────────────┤
│ LAUNCH STEPS   │ CURRENT WORKSPACE                     │ LAUNCH PLAN    │
│                │                                       │                │
│ ✓ Account      │ Step title                            │ Account        │
│ ✓ Campaign     │ Short explanation                     │ Campaign       │
│ ● Ad Set       │                                       │ Ad set         │
│ ○ Creative     │ Main existing step component           │ Page           │
│ ○ Review       │                                       │ CTA            │
│ ○ Launch       │                                       │ Creatives: 3   │
│                │                                       │ Ads: 12        │
│                │                                       │ Warnings: 0    │
│                │                                       │                │
│                │                                       │ [Continue]     │
└────────────────┴───────────────────────────────────────┴────────────────┘
```

### Responsive behavior

At narrower widths:

- Collapse the left step rail into a horizontal progress bar or compact step dropdown.
- Move the launch summary above the main content as a collapsible panel.
- Keep the primary action sticky at the bottom.
- Do not create horizontal overflow for the main form.

## 5. Detailed implementation spec

### 5.1 Launcher shell

Update `FacebookCampaigns.jsx` to provide a stable workspace shell around the existing step components.

Required regions:

1. **Context header**
   - Page title: `Launch Ads`
   - Account name
   - Campaign name when selected
   - Ad set name when selected
   - Compact edit/back affordances only where the existing flow permits changes.

2. **Step rail**
   - Account
   - Campaign
   - Ad Set
   - Creative
   - Review
   - Launch

Each step must show one of:

- Complete: check icon and muted label.
- Current: filled accent state and short description.
- Available: normal label.
- Blocked: muted label with a reason on hover/focus.

Clicking a completed step may navigate back. Clicking a blocked/future step must not bypass validation.

3. **Main workspace**
   - Existing child component remains the source of truth for each step's fields.
   - Add a consistent title, explanation, and action footer around it.
   - Do not duplicate form fields in the shell.

4. **Launch summary rail**
   - Account.
   - Campaign.
   - Ad set.
   - Facebook Page.
   - Creative source.
   - Creative count.
   - Headline count.
   - Body count.
   - Total ad count.
   - Validation warning count.
   - Launch status.

The summary rail should update from existing CampaignContext and child state. If a value is not known, show `Not selected`, not a misleading placeholder.

### 5.2 Creative source selection

The current creative step exposes multiple source paths with insufficient hierarchy. Reframe the top of `AdCreativeStep.jsx` as a source chooser.

Recommended copy:

```text
Choose your creative source
Select from an existing library, upload new media, or build the combinations manually.
```

Source cards/buttons:

```text
Drive Creative Library
Use synced Feed and Stories assets
[Browse Drive Library] [N assets]

Generated Ads
Reuse images already generated in Ad Builder
[Browse Generated Ads]

Upload or build manually
Add new media and enter copy yourself
[Upload media]
```

The Drive path should be the most prominent because it is the primary bulk workflow.

Do not remove any source path. This is a hierarchy change, not a capability removal.

The Drive picker may remain a modal in Phase 1, but it must have:

- clear selected count;
- persistent selected-assets tray or summary;
- obvious `Add selected creatives` action;
- clear Cancel action;
- no ambiguous button labels.

### 5.2.1 Visual review corrections before Phase 1B

The deployed Phase 1A shell was visually checked in the authenticated production browser. Keep these corrections explicit in the next pass:

- Keep the current three-column hierarchy: left step rail, center workspace, right Launch Plan. It reads well and should not be redesigned.
- Keep `Launch Ads` as the page title. It is clearer and more action-oriented than `Facebook Campaigns`.
- Keep the right rail compact. It should summarize state, not repeat editable form fields. `Not selected` is correct when a value is not yet available.
- Make the step vocabulary consistent everywhere: use `Review` and `Launch` in the rail, and reserve `Review & Launch` for explanatory copy only if needed.
- In the Drive picker, change `Select first (most recent)` to copy that states the scope, such as `Select first N matching assets`, and show the exact resulting range before selection is committed.
- Keep selected and blocked assets visually distinct in the Drive grid. Joel should be able to identify selected, unavailable, mismatched, and already-added assets without opening each card.
- Preserve the current source-card hierarchy with Drive first. Do not add another source mode or another confirmation screen.
- Treat the current dense Drive modal as a Phase 1B density problem, not a reason to redesign the launcher shell.

These are small clarity corrections, not a new phase. Do not change API payloads, selection semantics, or existing launch safety behavior while applying them.

### 5.3 Live variation counter

Move the existing variation math into a visible summary at the top of the Creative step.

Copy:

```text
3 creatives × 2 headlines × 2 primary texts = 12 ads
```

Use the actual existing permutation rules, including per-creative Drive copy overrides. Do not create a second divergent calculation.

States:

- `Select media, headlines, and primary text to calculate ads.`
- `3 creatives × 2 headlines × 2 primary texts = 12 ads`
- `12 ads ready for review`
- `0 ads — add at least one creative, headline, and primary text`

The count should be visible before Joel leaves the Creative step.

### 5.4 Review step

Keep the current preview-card functionality but improve the surrounding layout.

Required structure:

```text
Review 12 ads
12 ads will be created in RHO - Commercial Insurance.

[All] [Ready] [Warnings]                 [Sort: source order]

┌─────────────┐ ┌─────────────┐
│ ad preview  │ │ ad preview  │
│ status      │ │ status      │
│ name        │ │ name        │
│ [Edit] [×]  │ │ [Edit] [×]  │
└─────────────┘ └─────────────┘
```

Each card should prioritize:

1. Actual media preview.
2. Page name and placement/format.
3. Headline.
4. Primary text preview.
5. CTA.
6. Ad name.
7. Validation state.
8. Edit and exclude actions.

Editing should open a right-side drawer or expandable detail panel. Do not turn every card into a permanently open form.

The review header must show:

- total ads;
- ready count;
- warning count;
- excluded count;
- selected launch status.

### 5.5 Primary action hierarchy

Each screen gets one solid primary action:

| Step | Primary action |
|---|---|
| Account | Continue to campaign |
| Campaign | Continue to ad set |
| Ad Set | Continue to creative |
| Creative | Continue to review |
| Review | Launch N ads |
| Launching | View progress |
| Complete | Open Campaign Performance |

Back, Cancel, Browse, Edit, and Export must not visually compete with the primary action.

The final action must include the count:

```text
Launch 12 ads
```

If warnings exist:

```text
Review 2 warnings before launch
```

Do not silently launch while warnings are unresolved.

### 5.6 Launch progress and completion

Preserve the existing rate-limit and partial-failure behavior, but present it inside the workspace shell.

Progress copy:

```text
Launching ads
Created 4 of 12 ads
Meta is processing the remaining creatives. Keep this tab open.
```

Partial failure copy:

```text
Launch stopped after 4 of 12 ads
4 ads were created. 8 were not attempted.
Review the named campaign and ad set in Meta before retrying.
```

Completion copy:

```text
Launch complete
12 ads created as PAUSED.
Open Campaign Performance
```

Do not introduce new retry semantics in Phase 1.

## 6. Routing and decision logic

| Condition | UI behavior |
|---|---|
| Account missing | Account step current; all later steps blocked |
| Campaign missing | Campaign step current; later steps blocked |
| Ad set missing | Ad Set step current; later steps blocked |
| No creative source | Creative step shows source chooser and empty state |
| Drive assets selected | Show paired Feed/Stories summary and selected count |
| Copy incomplete | Show inline field error and block Review |
| Zero valid permutations | Keep Review disabled; explain required inputs |
| Review warnings present | Show warning count and require explicit review |
| Ads excluded | Update total and launch count immediately |
| Launch in progress | Disable duplicate launch actions; show progress |
| Partial failure | Show created/failed/not-attempted counts and reconciliation guidance |
| Launch complete | Show status and link to Campaign Performance |

## 7. Integration and data constraints

No new backend endpoints or migrations in Phase 1.

Reuse:

- CampaignContext.
- Existing `AdCreativeStep` state and callbacks.
- Existing `BulkAdCreation` permutation manifest.
- Existing Drive asset grouping/pairing.
- Existing `authFetch` calls.
- Existing Meta launch payloads.
- Existing rate-limit and partial-failure handlers.

Do not change:

- Meta field names.
- Facebook Page resolution rules.
- Feed/Stories pairing rules.
- Ad-set-level brand state.
- `ad.ad_id` handling.
- Launch status semantics.

## 8. Tracking and QA

Add frontend events only if an existing event mechanism is already available. Do not create a new analytics backend in this phase.

Useful events:

- `launcher_opened`
- `launcher_step_viewed`
- `creative_source_selected`
- `drive_picker_opened`
- `drive_assets_added`
- `variation_count_viewed`
- `review_opened`
- `review_ad_excluded`
- `launch_submitted`
- `launch_completed`
- `launch_partial_failure`

Required QA:

- Existing manual creative path still works.
- Drive path still pairs Feed and Stories correctly.
- Generated Ads Library path still works.
- Auto-skip does not loop when navigating Back.
- Variation count matches the Review count exactly.
- Empty/invalid creative rows cannot launch.
- Per-ad exclusion updates counts and payloads.
- Review drawer edits update the actual launch manifest.
- Launch warnings appear both in the summary and on the affected card.
- Rate-limit stop state remains understandable.
- Partial-failure state remains understandable.
- Responsive layout works without horizontal overflow.
- No `alert()` or `confirm()` is introduced.

## 9. Build priority

### Ready for review: Phase 1A

1. Launcher shell with step rail, context header, and summary rail.
2. Creative source hierarchy.
3. Live variation counter.
4. Review header and action hierarchy.

### Ready for review: Phase 1B

1. Review-card spacing/density pass.
2. Right-side edit drawer or expandable detail editor.
3. Launch progress and completion presentation inside the shell.
4. Responsive treatment.

### Deferred Phase 2

- Dedicated Prebuilt Ad Package Import UX for the existing Match by Naming Convention path:
  downloadable CSV template, filename examples, CSV/image-pair preflight, batch-split
  guidance, and alignment with the standard Launch Plan/review drawer.
- Server-side draft persistence.
- Meta Batch API.
- Saved audience/targeting presets.
- Winners/reuse surface.
- Explicit reuse-proven/mix/new dial.
- Review/approval states.
- Brand monitoring.
- Targeting permutations.

## 10. Definition of done

The build is ready for review when Joel can:

1. Open the launcher and immediately see the selected account/campaign/ad set context.
2. Understand the available creative sources without hunting through Step 4.
3. Select Drive or generated assets without losing the current launch context.
4. See the exact number of ads that will be created before Review.
5. Scan the final ads visually in a predictable grid.
6. Edit an individual ad without leaving the review context.
7. See warnings where they occur and in the summary.
8. Click one obvious final action labeled with the launch count.
9. Understand progress, partial failure, and completion without opening a second screen.

The implementation should feel like one launch workspace, not six unrelated forms.
