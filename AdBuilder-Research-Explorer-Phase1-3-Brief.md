# Research Explorer — Phases 1–3

## Executive summary

Research now moves toward a fast, visual competitor catalog rather than a raw scrape report. The economics are simple: better source qualification and faster reuse mean Joel spends less time scrolling irrelevant ads and more time turning proven structures into controlled tests.

```text
Capture / import → indexed catalog → conservative tags + media preview → filter → board → Ad Remix
```

## Delivered scope

| Phase | Delivered |
|---|---|
| 1. Fast catalog | indexed `last_seen`, CTA, and page-type fields; existing vertical browse remains the fast read path rather than invoking a scrape per view |
| 2. Media exploration | thumbnail-first 4:3 cards, video marker/duration support, stable preview URL field, source metadata carried through import |
| 3. Creative taxonomy | nullable controlled themes, CTA/page type, source/confidence, conservative text rules, filters, and Remix handoff metadata |

## Decision logic

| Signal | Treatment |
|---|---|
| Capture supplies a label | keep it as source-backed |
| Visible copy matches a narrow rule | apply low-confidence `rules_v1` tag |
| No evidence | leave the field unknown |
| Commercial browse row lacks insurance intent or is obvious noise | suppress it from the working catalog; retain source record |

## Integration / tracking

`ScrapedAd` is the single catalog object. Import writes the normalized fields; browse returns them; Research filters them; the existing `pendingResearchInspiration` handoff passes them into Ad Remix as strategy context, never source copy.

Recommended follow-up instrumentation: filter-used, results-returned, save-to-board, and Build-from-ad events. Do not add an expensive crawler or AI video analysis until usage justifies it.

## Sign-off criteria

- No performance claim is represented as Meta truth.
- Unknown remains visible unless the user chooses a filter.
- Existing saved boards and Remix flow keep working.
- Migration is additive and safe with the project startup sequence.
