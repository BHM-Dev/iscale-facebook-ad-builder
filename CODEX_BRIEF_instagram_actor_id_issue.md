# Codex Brief — instagram_actor_id rejected by Meta despite full permission chain

## Symptom

Bulk Match Import's 9x16 dual-placement feature (Feed square + Stories/Reels vertical, same
copy, via `asset_feed_spec`) fails on the final ad-creation step. Both the creative-only test
and the full ad-creation test consistently return:

```
Facebook API: (#100) Param instagram_actor_id must be a valid Instagram account id
```

Confirmed via a **raw, minimal Graph API Explorer POST** — completely bypassing our backend,
different token, different code path — with the identical error. This rules out anything in
our own code, caching, or request construction. Meta itself is rejecting this specific
`instagram_actor_id` value for this specific ad account, right now, despite every permission
layer checking out.

## Reproduction (still fails as of this writing)

```
POST https://graph.facebook.com/v25.0/act_949433761196746/adcreatives
  ?name=Claude Test Diagnostic
  &object_story_spec={"page_id":"101095108489513","link_data":{"link":"https://dailyinsurance.news","message":"test"}}
  &instagram_actor_id=17841477155657989
```

Response:
```json
{"error": {"message": "(#100) Param instagram_actor_id must be a valid Instagram account id", "type": "OAuthException", "code": 100, "fbtrace_id": "AB4DalfhW0DpLnUQ7v4WuUQ"}}
```

## Key IDs

| Thing | ID |
|---|---|
| Ad account (DIN Auto Insurance) | `act_949433761196746` |
| Facebook Page (DailyInsurance.news) | `101095108489513` |
| Instagram account (@dailyinsurancenews) | `17841477155657989` |
| Business Manager owning the Page/IG asset | Resource Help Online |
| Business Manager the ad account lives in | dailyinsurancenews |
| Meta app used for token | BHM Ad Builder Marketing API |

## What's already fixed / confirmed correct (do not re-investigate these)

1. **Token scope** — `FACEBOOK_ACCESS_TOKEN` was rotated with `instagram_basic`,
   `pages_show_list`, `pages_read_engagement`, `business_management`, `ads_management`,
   `ads_read`. Rotated via a one-off GitHub Actions workflow
   (`.github/workflows/rotate-facebook-token.yml`, `workflow_dispatch`) that reuses the
   existing deploy SSH secrets to edit `.env` and recreate the backend container. This is a
   real, confirmed, permanent fix — keep it.

2. **Code fix already shipped** (commit `c0a6eee` on `develop`,
   `backend/app/services/facebook_service.py`) — added `_get_page_instagram_actor_id(page_id)`
   which reads `Page(page_id).api_get(fields=['instagram_business_account'])` and resolves
   the correct ID (`17841477155657989`, confirmed matches Business Manager exactly). When
   found, sets `object_story_spec['instagram_actor_id']`; when not found, drops
   `instagram_positions` and falls back to Facebook-only placement instead of failing the
   whole ad. This code is correct — verified independently via Graph API Explorer that the
   Page correctly resolves to this exact Instagram ID.

3. **Business Manager permission chain — all four layers confirmed correctly configured**:
   - Page → Instagram Business Account connection: confirmed via Business Manager "Connected
     assets" tab on the Page.
   - Business-to-business asset sharing: Resource Help Online (owner) → shared the Instagram
     account to the `dailyinsurancenews` business via "Assign partner" with Ads permission.
   - Individual person access: `Steve Sun` explicitly assigned "Partial access (Ads)" on the
     Instagram account within the `dailyinsurancenews` business (Instagram account settings →
     People → Assign people).
   - **Ad-account-level asset connection**: Instagram account settings → "Connect assets" →
     "Other business assets" → Ad accounts → added `DIN Auto Insurance`. Confirmed via
     `GET act_949433761196746/instagram_accounts` returning
     `{"data": [{"id": "17841477155657989"}]}` (previously empty `{"data": []}` before this
     step — this actually changed something real, just not enough to fix ad creation).

4. **Account type** — confirmed the Instagram account is already a **Business** account (not
   Creator/Personal) via the mobile app's "Switch account type" option only offering
   Creator/Personal as targets. Ruled out as the cause.

5. **Propagation delay** — waited 3+ minutes between the ad-account connection fix and
   retesting; no change. Also retested well after that. Not a short-timescale propagation
   issue (may still be a longer one — see open questions).

## What's still broken

Despite all of the above, both:
- The full Ad Builder flow (creative → ad, via `/api/v1/facebook/creatives` and
  `/api/v1/facebook/ads`)
- A minimal, hand-built Graph API Explorer request with zero relation to our codebase

...get the identical `(#100) Param instagram_actor_id must be a valid Instagram account id`
error when using `instagram_actor_id=17841477155657989` on `act_949433761196746`.

## Open questions / where to look next

- **Is there a Meta-side approval/review status on the Instagram-to-ad-account connection**
  that isn't exposed in Business Manager's UI or the `instagram_accounts` edge? The edge
  listing the ID doesn't necessarily mean it's *usable* for ad creative purposes yet.
- **Instagram Graph API vs Marketing API permission split** — is there a *separate* consent/
  connection required specifically for using an IG account as an ad "actor" (as opposed to
  just being connected to the Page or ad account)? Check Meta's current docs for
  `instagram_actor_id` requirements — this field's validation rules may have changed and no
  longer just check the `instagram_accounts` edge.
- **Longer propagation** — some developer forum reports (unverified) suggest ad-account-level
  Instagram connections can take hours, not minutes, to activate for ad delivery even after
  the API reflects the connection. Worth an actual multi-hour wait-and-retest as a control.
- **Try a completely different, already-known-working Instagram+ad-account pairing** (e.g.
  whichever IG account/ad account combo BHM already successfully runs Instagram ads on
  elsewhere, if one exists) to confirm this exact `instagram_actor_id` field/flow works at all
  under current Meta API behavior — would isolate whether this is specific to this asset pair
  or a broader issue.
- **Meta Business Help Center case** — not yet filed. If Codex can't find anything further,
  this is the fallback: cite the exact error, ad account ID, Instagram ID, and the fact that
  `instagram_accounts` already lists it as connected.

## Do NOT re-try

- Re-checking token scopes (confirmed correct)
- Re-checking Business Manager sharing at any of the 4 layers above (all confirmed correct,
  re-verified via direct Graph API queries, not just UI inspection)
- Re-checking account type (confirmed Business)
- Short (<10 min) propagation waits (already tried, no change)
