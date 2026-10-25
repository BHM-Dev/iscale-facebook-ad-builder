# Security guardrails (permissions, outbound fetches, cost caps)

What the backend enforces today and where. Written 2026-10-25 after the full-app review; other findings from that review are tracked outside this repo.

## Who can change what (server-side — the UI is not the guard)
All routes require a logged-in, **active** user. Mutating routes additionally require a permission (admin holds all of them; today all 6 active users are admins):

| Area | Permission |
|---|---|
| Create/edit/delete auto-pause rules; `POST /facebook/push-to-meta`; CAPI sync; Meta budget/status/delete routes | `campaigns:write` |
| Delete templates (bulk), prompts, ad styles | `templates:delete`; create/edit prompts & styles → `templates:write` |
| Ad Copy Library sync/pin; Drive upload, sync-now, refresh-copy-metadata | `ads:write`; delete copy-library entries → `ads:delete` |
| Delete saved searches / brand scrapes / blacklist entries / a vertical's catalog (Research) | `ads:delete` (boards: creator or `ads:delete`) |
| `GET /generated-ads/test-kie` (spends kie.ai credits) | superuser |
| `POST /research/run-scheduled-searches` | superuser |

`push-to-meta` also normalises `status`: null/blank → `PAUSED`; anything but `ACTIVE`/`PAUSED` → 400.
**Scoped users** (limited to some ad accounts): `POST /ai-insights/query` now resolves/validates the account like the other routes.

## Outbound media fetches — `backend/app/services/safe_fetch.py`
Every place the server downloads a media URL goes through one hardened fetcher: crop-to-aspect (`/uploads/crop-to-aspect`), overlay logo, product-shot reference, Meta image/video upload helpers, and the remix source image.
- http(s) only, no embedded credentials, ports 80/443; refuses any host that resolves to a private, loopback, link-local (incl. the cloud metadata address), CGNAT, multicast or reserved address — including IPv4-mapped IPv6, NAT64, 6to4, Teredo and site-local forms.
- Redirects are followed **manually, max 3, every hop re-validated**; https→http downgrades refused; proxy environment variables ignored.
- Hard size cap and overall time budget while streaming; after connecting, the peer address is checked again (best-effort DNS-rebinding backstop).
- **strict mode** (URLs that arrive from the browser at crop / remix): approved hosts only — Meta CDN suffixes, our R2 public host, our API host. **public mode** (overlay logo, product shots, Meta upload helpers): any *public* host.
- Images are refused before decoding if they exceed a pixel budget (64 MP — covers 48–50 MP phone photos; 16 MP for logos) — blocks decompression bombs on the single worker. A failed/oversized video download no longer leaves a partial temp file.

## Cost caps
- `POST /generated-ads/generate-image`: variations 1–10, ≤6 sizes, **≤30 images per request** (the wizard's own maximums), ≤50 product shots. No per-user daily cap yet — real batch sizes are unknown and a wrong guess would block the buyers; add one once usage is measured.
- AI insights: question ≤1,500 characters, 30 questions / 10 min per user. Research Ask: 20 / 10 min per user. Research searches: `limit` ≤300 and the Meta call budget is checked first (see research.md).

## Verified vs not
- **Unit/route-tested** (`tests/test_permission_hardening.py`, `tests/test_safe_fetch.py`): every gated route 403s a read-only user and names the permission; holding it passes the gate; status validation; scoping; caps; SSRF cases (internal/metadata/redirect/IPv6/numeric hosts/size/time); temp-file cleanup. These were run against the **original** code to confirm they fail there (32 failures; the SSRF tests initially passed on old code and were rewritten to assert no connection is attempted).
- **Verified in production** after deploy: see the Changelog.
- **Not covered:** the DNS-rebinding window is only narrowed (best-effort peer check), not closed by IP pinning. The cloud metadata service answers from inside the app container (HTTP 401 — it wants a token), so the fetcher's block is the protection that matters; an iptables drop for that address from the Docker network would add a second layer (not done).

## Changelog
- 2026-10-25 permission gates, `safe_fetch`, generation/AI caps, push-to-meta status validation.
