# Codex Brief — Deploy pipeline reports success but frontend bundle is stale

## Symptom
Pushed commit `afad7a72c5e4eaa20371fea8985720eefc5c2d6f` to `develop` (Bulk Match Import
feature). The `Deploy to VPS` GitHub Action ran and reported success — twice, once
automatically on push and once manually re-triggered via `workflow_dispatch` — but the live
frontend at `https://adbuilder.velocitymx.io` serves the exact same JS bundle
(`/assets/index-CTQUioAq.js`, identical content hash) both times. Confirmed via `curl` with
cache-busting query params and checking response headers — no CDN in front, it's origin nginx
serving directly, so this isn't a caching layer. Grepping that bundle for strings unique to the
new code (`papaparse`, `ad_number`, "Bulk Match") returns zero matches.

Separately, `/api/v1/version` on `adbuilder-api.velocitymx.io` reports the correct commit — but
that's set from a `GIT_COMMIT` environment variable read at container start
(`docker-compose.prod.yml`), not proof the backend code itself was rebuilt. Could not confirm
backend code freshness independently — the one schema I checked via OpenAPI isn't wired to the
route that changed, so it's inconclusive either way.

## What this needs (SSH into the VPS — I don't have access from Claude Code)

1. **Confirm the git state actually advanced:**
   ```bash
   cd /home/ubuntu/iscale-facebook-ad-builder
   git log --oneline -3
   git status
   git rev-parse --is-shallow-repository
   git branch -vv
   ```
   Expecting HEAD at `afad7a7...`. If it's NOT there, or the repo is shallow, or HEAD is
   detached, or there's a branch tracking issue — that's the root cause. `deploy.yml`'s own
   safety check (the one meant to catch exactly this) explicitly **skips itself and passes
   anyway** when the repo is a shallow clone (see the comments in `.github/workflows/deploy.yml`
   around the `EXPECTED_SHA` check) — so if that's the situation, the pipeline has been silently
   lying about deploys for a while, not just this one.

2. **Confirm what Docker actually built:**
   ```bash
   docker compose -f docker-compose.prod.yml images
   docker inspect ad-builder-web --format '{{.Created}}'
   docker inspect ad-builder-api --format '{{.Created}}'
   docker compose -f docker-compose.prod.yml logs frontend --tail 100
   ```
   Check whether the `frontend`/`backend` image `Created` timestamps line up with the deploy run
   time, and whether the build log shows `npm run build` actually running fresh (should show
   Vite output) vs. reusing a cached layer silently.

3. **If git state is fine but Docker is stale:** try a clean rebuild bypassing cache:
   ```bash
   docker compose -f docker-compose.prod.yml build --no-cache frontend backend
   docker compose -f docker-compose.prod.yml up -d
   ```
   Then re-check the served bundle content-hash changes (`curl -s https://adbuilder.velocitymx.io/ | grep -oE '/assets/[^"]+\.js'` should return a DIFFERENT hash than `index-CTQUioAq.js`).

4. **If git state itself is broken** (shallow clone, detached HEAD, wrong remote) — that's a
   bigger fix (re-clone or fix the tracking branch) and probably needs Golden's sign-off since
   it's touching how the VPS's deploy checkout is set up, not just this one deploy.

## Do NOT
- Don't touch `docker-compose.prod.yml`, env vars, or anything beyond diagnosing + (if safe) a
  `--no-cache` rebuild of the existing services.
- Don't restart `postgres` or touch volumes.
- Report back before doing anything destructive — this is a live production app Joel uses daily.

## Report back
Exact root cause (shallow clone? detached HEAD? Docker cache?), whether a `--no-cache` rebuild
fixed it, and the new asset hash if it did. If the root cause is the shallow-clone gap in
`deploy.yml`'s own safety check, flag that separately — it means past "successful" deploys may
also be suspect, not just this one.
