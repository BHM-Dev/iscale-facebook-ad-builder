# Codex Brief — Post-Generation Similarity Guard for Reference Copy

Approved as proposed. Building on `b2b3b00` (prompt hardening) — this adds the verification layer
that was flagged as missing: prompt instructions alone aren't a strong enough control for a
regulated vertical where the reference is often a competitor's live ad.

## Scope
1. Only runs when `reference_copy_context` was actually provided (has real `copy_analysis` and/or
   `copy_patterns` content) — zero cost/behavior change when it wasn't, matching the existing
   no-op discipline from `b2b3b00`.
2. Pure-Python overlap check, no extra LLM call for the check itself: compare `headline_remix` +
   `body_copy` from the generated `AdConcept` against the reference text (`copy_analysis` and
   `copy_patterns`, same formatted strings `_format_reference_copy_context` already builds/
   truncates — reuse that, don't reimplement text extraction). Flag on 6+ consecutive shared
   words (word-level n-gram match, case-insensitive, punctuation-normalized) — tune the exact
   threshold as you build it, 6 is a reasonable starting point per your own proposal.
3. If flagged: retry generation **once** with a stricter instruction appended (e.g. "Your previous
   output was too similar to the reference material — rewrite the headline and body copy with
   completely different wording, sentence structure, and framing while keeping the same strategic
   pattern."). Re-run the same overlap check on the retry.
4. If still flagged after the retry: do NOT block or fail. Return the result with a warning field
   set — Joel needs to see it and decide, not hit a dead end.
5. If never flagged (first pass or after retry): warning field is `null`/absent, no UX change.

## Where things go
- **New backend utility**, small and testable in isolation — put it in `api/v1/ad_remix.py`
  alongside the other prompt helpers (`_format_reference_copy_context`, `_build_prompt_context`),
  or a new `_similarity_guard.py` in the same directory if it grows past a few functions. Your
  call on file split.
- **Response schema**: add `similarity_warning: Optional[str] = None` to `AdConcept`
  (`backend/app/schemas/ad_blueprint.py:42-48`). Both `/reconstruct` and `/reconstruct-from-url`
  return `AdConcept` — wire the check into both call sites in `ad_remix.py` (same two spots that
  already call `_build_prompt_context`), not just one.
- **No migration, no new DB field** — this is a transient per-request warning, not persisted.
  Confirm nothing in the generation pipeline tries to save `AdConcept` to a table with a fixed
  column set that would choke on the new optional field (check `GeneratedAd` model / wherever a
  generated concept gets persisted after the user accepts it — if `similarity_warning` shouldn't be
  stored long-term, just don't include it in whatever `create()`/`insert()` call persists the
  accepted ad; don't add a DB column for this unless you find a real need to keep it after the
  session).
- **Frontend**: in `AdRemix.jsx`, when the response includes `similarity_warning`, show it near the
  generated copy — a visible but non-blocking banner, something like *"Reference similarity
  warning: review copy before launch."* Use the existing `useToast`/`showWarning` pattern if that
  fits, or an inline banner near the generated headline/body if a toast would get missed — your
  call on which reads better in context, but it must NOT block the wizard from proceeding.

## What "done" looks like
1. Generate from a template with strong reference copy_analysis/copy_patterns content, force a
   near-verbatim output somehow (or write a quick unit test directly against the overlap function)
   to confirm detection fires.
2. Confirm the retry actually happens once, with the stricter instruction, and doesn't loop forever.
3. Confirm a flagged-after-retry result still returns normally (200, not an error) with the warning
   set, and the UI shows it without blocking Next/Generate.
4. Confirm zero behavior change (no warning field appears at all, same response shape as before)
   when no reference_copy_context was ever provided — this must stay a true no-op path.

## Hand off
Commit locally, don't push. Note what changed for the Claude Code review pass — this will get the
same 2-agent review the last copy-context change did, given it's still generation/AI-output logic.
