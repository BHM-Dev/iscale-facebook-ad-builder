# Switchboard Billable-Revenue Attribution Audit

## Executive summary

The objective is to make Switchboard/Everflow the source of truth for billed revenue while preserving RedTrack as the delivery, timing, and creative-attribution layer. This must not be implemented as a blind row-level join: the systems have different grains and may carry Meta identifiers in different sub fields.

The first deliverable is a read-only coverage and reconciliation audit. It will establish which raw Switchboard conversion rows can be assigned exactly to a Meta ad set, campaign, and ad; quantify the remainder; and prove that the admitted revenue reconciles to the Switchboard portal before any product recommendation is upgraded from directional to confirmed.

## Observed tracking contract

| System | Current identifier | Intended meaning |
|---|---|---|
| Meta | `ad.id` | Creative/ad identity |
| Meta | `adset.id` | Spend and scheduling identity |
| Meta | `campaign.id` | Campaign identity |
| RedTrack | `sub1` | Meta ad ID |
| RedTrack | `sub2` | Meta ad-set ID |
| RedTrack | `sub3` | Meta campaign ID |
| Switchboard/Everflow | raw `sub*` fields | Must be measured, not assumed, before assignment |

## Important finding

The repository’s tracking checklist says the delivered link uses `sub2={{adset.id}}` and `sub3={{campaign.id}}`. The current Switchboard service groups billable revenue by Everflow `sub3` as if it were an ad-set ID. The P&L code separately recognizes `sub3` values that are campaign IDs as legacy/broken attribution.

That is not sufficient evidence that every Switchboard conversion uses `sub3` as an ad-set key. The live raw conversion schema must be profiled first. Do not rewrite URL macros or alter historical attribution based on this finding.

## Proposed architecture

```text
Meta delivery
  ad / ad set / campaign IDs + spend by day/hour
          |
          v
RedTrack
  sub1 ad, sub2 ad set, sub3 campaign + click/conversion timing
          |
          v
Switchboard / Everflow
  billable conversion/event revenue + its passed-through sub fields
          |
          v
Attribution resolver
  1. exact Meta ad-set key          -> confirmed ad-set revenue
  2. known Meta campaign key        -> campaign-only revenue
  3. exact ad key plus RT ad set    -> bridged attribution, labeled
  4. no verified Meta key           -> account-level unattributed revenue
          |
          v
Reconciliation ledger
  Switchboard portal total = exact + bridged + campaign-only + unattributed
```

RedTrack is never used to invent revenue. It can only supply the distribution key (time, creative, ad set) for revenue that Switchboard has already confirmed.

## Phase 1 — read-only audit

For each configured Meta account and mapped Switchboard offer over a 30-day window:

1. Pull raw Switchboard conversions with event, revenue, conversion timestamp, offer, conversion ID, and populated `sub1`–`sub8` values.
2. Pull the local Meta ad/ad-set/campaign identity map and RedTrack raw conversions for the same date range.
3. Classify every Switchboard row into exactly one bucket:
   - `exact_adset`
   - `campaign_only`
   - `ad_via_redtrack`
   - `invalid_or_missing_meta_key`
   - `foreign_or_unmapped_account`
4. Report revenue, events, and percent coverage for each bucket, by account and offer.
5. Reconcile the sum of all buckets to the Switchboard period total within $0.01.
6. Store no per-conversion PII; retain only conversion ID/hash, identifiers, classification, amount, timestamp, and audit reason.

## Product rules after the audit

| Coverage condition | P&L | Best Times | Creative Compass |
|---|---|---|---|
| Exact ad-set revenue | Confirmed | Eligible for High confidence | Eligible for scale/cut rules |
| Billable revenue + RedTrack timing distribution | Billable, directional attribution | Medium/Low only | Label as directional |
| Campaign-only Switchboard revenue | Confirmed campaign total | No ad-set schedule recommendation | Campaign investigation only |
| Unmapped revenue | Account total only | Excluded | Tracking repair queue |

## External dependency

We need access to the configured Switchboard Everflow account and its raw conversion response (read-only) to confirm which `sub` field preserves which Meta macro. The existing environment configuration names are:

- `SWITCHBOARD_EVERFLOW_API_KEY`
- `SWITCHBOARD_EVERFLOW_AD_ACCOUNT_IDS`
- `SWITCHBOARD_EVERFLOW_ACCOUNT_OFFERS`

The first production action should be a read-only audit against one known account/offer, not a broad migration or a tracking-link change.
