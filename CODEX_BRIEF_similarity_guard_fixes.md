# Codex Brief — Similarity Guard Fixes (Round 2)

Builds on `79cf567`. Review (code-logic + end-user/product, both against the live diff) found the
guard has real coverage gaps and one crash bug. Fix these before this ships — this is the actual
safety mechanism, not polish.

## Must fix

### 1. The guard doesn't check the highest-risk path (`research_inspiration`)
`reconstruct_from_url` builds its prompt context from **both** `research_inspiration` (via
`_format_research_context`, which injects the literal competitor headline/body/CTA text — see
`- Competitor headline to study, not copy: {headline}` etc.) **and** `reference_copy_context` (via
`_format_reference_copy_context`, an AI *analysis* of a reference ad, not the literal ad text).
`_find_reference_similarity` only ever checks against the latter. The Research path — which is the
one carrying real, quotable, literal third-party ad copy into the prompt — is completely unguarded.
This is backwards: fix `_find_reference_similarity` (or add a sibling check) to also compare
generated copy against `research_inspiration`'s `headline`/`body`/`cta` fields directly (the raw
strings, not a re-derivation from `_format_research_context`'s formatted/truncated output — see
point 3). Wire it into both call sites so `reconstruct_from_url` checks against whichever of
`research_inspiration` / `reference_copy_context` (or both) was actually provided.

### 2. `cta_button` is never checked, in either path
`_find_reference_similarity` only concatenates `headline_remix` + `body_copy`. CTAs are short stock
phrases ("Get Your Free Quote Now") — likely to be reused verbatim and, because they're short,
already the least likely to trip a 6-word n-gram even if checked. Add `cta_button` to the generated
text being compared, and also compare it against the competitor CTA field
(`research_inspiration.cta`) directly (a short-phrase equality/near-equality check may make more
sense for CTAs specifically than n-gram overlap — your call on exact approach, but it must not be
silently excluded).

### 3. Compare against raw reference content, not the truncated/formatted prompt text
Currently the comparison corpus is `_format_reference_copy_context(...)`'s full output — which (a)
is capped at 1200 chars per field via `_truncate_for_prompt`, creating a real blind spot for longer
`copy_analysis`/`copy_patterns` content, and (b) includes the function's own instructional
boilerplate sentences mixed in with the actual reference content (harmless in practice, but sloppy
and worth cleaning up while you're in here). Fix: build the similarity-check corpus from the raw,
untruncated `copy_analysis` / `copy_patterns` / `research_inspiration` fields directly — truncation
is a prompt-injection-safety concern for what the *model* sees, it should have nothing to do with
what the *similarity guard* checks against.

### 4. Retry failure must not discard an already-successful generation
`_reconstruct_with_similarity_guard` calls `reconstruct_ad` a second time with no try/except of its
own. If that second call throws (rate limit, transient API error, malformed model output), the
exception propagates to the route's outer `except Exception` and returns a 500 — even though the
*first* generation already succeeded and only carried a soft similarity flag. That breaks the
entire "non-blocking, warn don't fail" premise of this feature. Fix: wrap the retry call in its own
try/except; on failure, fall back to returning the original `ad_concept` with
`similarity_warning` set from the original match (not the retry).

## Should fix (cheap, directly relevant)

### 5. Distinguish "not checked" from "checked and clean"
`similarity_warning` is `None` both when no reference material existed to check against AND when a
check ran and found nothing — the UI can't tell these apart, and "not checked" will happen
routinely (not as an edge case) given how many Ad Remix entry points don't carry reference
material. Doesn't need to change the UI (silence can stay the deliberate choice for both "clean"
states) but should be distinguishable in a debug/log sense at minimum — don't need a schema change
if that's overkill, use your judgment on how much plumbing this warrants.

### 6. Make the warning banner actionable and name the source
Current text: "Reference similarity warning: review copy before launch." plus the matched phrase.
Doesn't say what to do, or what it's being compared against. Both `winningAdTemplate.name` and
`researchInspiration.advertiser` are already in component state elsewhere in `AdRemix.jsx` — thread
whichever is relevant into the banner text (e.g. "...similar to the {template name} reference.").
Also add one concrete action suggestion, e.g. "Regenerate or manually edit the flagged phrase before
launching this ad."

## Not required, flag to Steve instead (don't build without confirming scope)
- **Logging/metrics on how often this fires** — reviewer's point stands (you'll want to know if
  this is a 1%-of-generations thing or a 30%-of-generations thing before trusting buyers to
  self-police off a banner alone), but that's observability scope beyond this brief. Note it in
  your hand-off, don't build it.
- **Cost note**: every flagged generation doubles the Sonnet-4.5 call for that request. Not a bug,
  just surface it in your hand-off note so Steve has the number in mind.

## Hand off
Commit locally, don't push. This will get another review pass given the compliance stakes — call
out in your hand-off note exactly which of the 6 items above you addressed and how, so the review
isn't starting from scratch.
