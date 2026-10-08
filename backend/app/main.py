"""
Facebook Ad Builder - Backend API

Created by Jason Akatiff
iSCALE.com | A4D.com
Telegram: @jasonakatiff
Email: jason@jasonakatiff.com
"""

import os
import re
from datetime import datetime, timezone
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import Response
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from app.core.config import settings
from app.core.rate_limit import limiter

PROCESS_STARTED_AT = datetime.now(timezone.utc).isoformat()

app = FastAPI(
    title="Facebook Ad Automation API",
    version="1.0.0",
    openapi_url="/api/v1/openapi.json",
    docs_url="/api/v1/docs",
)

# Register rate limiter
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Security headers middleware
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response: Response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    if request.url.scheme == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response

# Trust proxy headers (Railway uses reverse proxy)
# In production, consider restricting to specific CIDR ranges
trusted_proxies = os.getenv("TRUSTED_PROXIES", "*")
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=[trusted_proxies] if trusted_proxies != "*" else ["*"])

# CORS origins from env var or defaults (include 127.0.0.1 for Docker/same-host access)
default_origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
]
extra_origins = os.getenv("ALLOWED_ORIGINS", "").split(",")
allowed_origins = default_origins + [o.strip() for o in extra_origins if o.strip()]

# CORS Middleware - allow headers requested by preflight (Content-Type, Authorization, etc.)
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Requested-With", "Accept", "Origin"],
    expose_headers=["X-Total-Count"],
    max_age=600,
)

@app.get("/")
async def root():
    return {"message": "Welcome to the Facebook Ad Automation API"}

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

@app.get("/api/v1/version")
async def version():
    return {
        "commit": os.getenv("GIT_COMMIT", "unknown"),
        "started_at": PROCESS_STARTED_AT,
    }

# Database Connection Validation
@app.on_event("startup")
async def startup_event():
    """Validate PostgreSQL connection on startup, then start background scheduler."""
    from app.database import engine
    from sqlalchemy import text

    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT version()"))
            version = result.scalar()
            print(f"✅ Connected to PostgreSQL")
            print(f"   Version: {version}")
    except Exception as e:
        sanitized_url = re.sub(r'://[^:]+:[^@]+@', '://***:***@', settings.DATABASE_URL)
        print(f"❌ Failed to connect to database: {e}")
        print(f"   DATABASE_URL: {sanitized_url}")
        raise RuntimeError(f"Database connection failed: {e}")

    # Start APScheduler — runs auto-pause check every 30 minutes
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from app.database import SessionLocal
        from app.api.v1.auto_pause import _run_check

        scheduler = BackgroundScheduler()

        def scheduled_check():
            db = SessionLocal()
            try:
                result = _run_check(db)
                if result["paused"]:
                    print(f"⏸  Auto-pause fired: {result['paused']}")
                if result.get("notified"):
                    print(f"🔔 Notify rule(s) fired: {result['notified']}")
                if result.get("budget_adjusted"):
                    print(f"💰 Budget rule(s) fired: {result['budget_adjusted']}")
                if result.get("bid_adjusted"):
                    print(f"🎯 Bid rule(s) fired: {result['bid_adjusted']}")
                if result.get("duplicated"):
                    print(f"🔀 Duplicate rule(s) fired: {result['duplicated']}")
            except Exception as exc:
                print(f"⚠️  Auto-pause scheduler error: {exc}")
                try:
                    from app.services.slack_service import send_check_summary
                    send_check_summary(rules_evaluated=0, paused_count=0,
                                       errors=[{"error": f"Auto-pause check CRASHED, no rules were enforced this cycle: {exc}"}])
                except Exception:
                    import logging
                    logging.getLogger(__name__).exception("Could not send scheduler-crash alert")
            finally:
                db.close()

        def scheduled_redtrack_sync():
            """Refresh RedTrack cache every 30 minutes for today, yesterday, and last_7d.

            Three presets are pre-warmed so the Dashboard never triggers a slow
            live-fetch for the most common date selections. Each preset is one
            independent RT API call; failures are isolated per-preset.
            """
            from app.services.redtrack_service import RedTrackService
            from app.models import RedTrackCache
            svc = RedTrackService()
            if not svc.is_configured():
                return

            import uuid
            from datetime import date as _date

            for preset in ("today", "yesterday", "last_7d"):
                db = SessionLocal()
                try:
                    date_from_str, date_to_str = svc.preset_to_dates(preset)
                    report = svc.get_report_by_adset(date_from_str, date_to_str)
                    if not report:
                        print(f"ℹ️  RedTrack: no data returned for {preset}")
                        continue
                    date_from = _date.fromisoformat(date_from_str)
                    date_to   = _date.fromisoformat(date_to_str)
                    db.query(RedTrackCache).filter(
                        RedTrackCache.date_from == date_from,
                        RedTrackCache.date_to   == date_to,
                    ).delete()
                    for fb_adset_id, metrics in report.items():
                        db.add(RedTrackCache(
                            id=str(uuid.uuid4()),
                            fb_adset_id=fb_adset_id,
                            date_from=date_from,
                            date_to=date_to,
                            **metrics,
                        ))
                    db.commit()
                    print(f"✅ RedTrack cache refreshed: {len(report)} ad sets ({preset})")
                except Exception as exc:
                    print(f"⚠️  RedTrack sync error ({preset}): {exc}")
                finally:
                    db.close()

            # Phase 3: ad-level performance sync — join sub1 (Meta ad id) onto
            # generated_ads.fb_ad_id, writing revenue/profit/last_synced_at.
            db = SessionLocal()
            try:
                from app.services.redtrack_service import sync_generated_ad_performance
                summary = sync_generated_ad_performance(db, svc, "last_7d")
                print(f"✅ RedTrack ad-perf sync: {summary.get('matched')} matched, "
                      f"{summary.get('pushed_ads_no_match')} pushed-no-match, "
                      f"{summary.get('outliers')} outliers")
            except Exception as exc:
                print(f"⚠️  RedTrack ad-perf sync error: {exc}")
            finally:
                db.close()

        def scheduled_meta_sync():
            """Sync all Meta campaigns and ad sets into the DB.

            Iterates every ad account the token can see (not just the default),
            tagging each campaign/adset with its true fb_account_id so the
            account-scoped saved-adsets list stays authoritative for ALL accounts
            on every cycle — no manual per-account backfill required.

            NOT on a 30-min scheduler.add_job() timer and no longer triggered on
            login either (that full-account-sweep-on-login call was removed —
            it could span every visible ad account and several Meta API calls,
            delaying the login response). Currently only reachable via
            app.state.meta_sync_fn if something explicitly invokes it — kept
            defined rather than deleted while that trigger path gets sorted out
            elsewhere, but it is not part of any automatic cadence right now.
            """
            from app.services.facebook_service import FacebookService
            from app.models import FacebookCampaign, FacebookAdSet, normalize_account_id
            import uuid as _uuid
            db = SessionLocal()
            try:
                svc = FacebookService()
                svc.initialize()

                # Build the account list. Prefer all visible accounts; fall back to
                # the default account id if the accounts lookup fails.
                account_ids = []
                try:
                    for acc in (svc.get_ad_accounts() or []):
                        aid = normalize_account_id(acc.get("id") or acc.get("account_id"))
                        if aid:
                            account_ids.append(aid)
                except Exception as exc:
                    print(f"⚠️  Meta sync: could not list ad accounts ({exc}); using default only")
                if not account_ids:
                    default_aid = normalize_account_id(getattr(svc, "ad_account_id", None))
                    account_ids = [default_aid] if default_aid else [None]

                created_c = updated_c = created_a = updated_a = 0
                for synced_account in account_ids:
                    try:
                        campaigns_raw = svc.get_campaigns(ad_account_id=synced_account)
                    except Exception as exc:
                        print(f"⚠️  Meta sync: get_campaigns failed for {synced_account}: {exc}")
                        continue
                    for c in campaigns_raw:
                        fb_id = str(c.get("id") or "")
                        if not fb_id:
                            continue
                        existing = db.query(FacebookCampaign).filter(FacebookCampaign.fb_campaign_id == fb_id).first()
                        if existing:
                            existing.name = c.get("name", existing.name)
                            existing.status = c.get("status", existing.status)
                            if synced_account:
                                existing.fb_account_id = synced_account
                            updated_c += 1
                            campaign_db = existing
                        else:
                            campaign_db = FacebookCampaign(
                                id=str(_uuid.uuid4()),
                                name=c.get("name", "Imported Campaign"),
                                objective=c.get("objective", "OUTCOME_LEADS"),
                                budget_type="CBO" if c.get("daily_budget") or c.get("lifetime_budget") else "ABO",
                                status=c.get("status", "PAUSED"),
                                fb_campaign_id=fb_id,
                                fb_account_id=synced_account,
                                special_ad_categories=c.get("special_ad_categories", []),
                            )
                            db.add(campaign_db)
                            created_c += 1
                        db.flush()
                        try:
                            adsets_raw = svc.get_adsets(ad_account_id=synced_account, campaign_id=fb_id)
                        except Exception:
                            continue
                        for a in adsets_raw:
                            fb_as_id = str(a.get("id") or "")
                            if not fb_as_id:
                                continue
                            existing_as = db.query(FacebookAdSet).filter(FacebookAdSet.fb_adset_id == fb_as_id).first()
                            if existing_as:
                                existing_as.name = a.get("name", existing_as.name)
                                existing_as.status = a.get("status", existing_as.status)
                                if synced_account:
                                    existing_as.fb_account_id = synced_account
                                updated_a += 1
                            else:
                                db.add(FacebookAdSet(
                                    id=str(_uuid.uuid4()),
                                    campaign_id=campaign_db.id,
                                    name=a.get("name", "Imported Ad Set"),
                                    optimization_goal=a.get("optimization_goal", "LEAD_GENERATION"),
                                    status=a.get("status", "PAUSED"),
                                    fb_adset_id=fb_as_id,
                                    fb_account_id=synced_account,
                                    daily_budget=int(a["daily_budget"]) if a.get("daily_budget") else None,
                                    budget_schedule_type="DAILY" if a.get("daily_budget") else "LIFETIME",
                                ))
                                created_a += 1
                db.commit()
                print(f"✅ Meta sync ({len(account_ids)} accounts): {created_c} campaigns created, {updated_c} updated | {created_a} ad sets created, {updated_a} updated")
            except Exception as exc:
                print(f"⚠️  Meta sync error: {exc}")
            finally:
                db.close()

        def scheduled_token_check():
            """Daily: warn before the personal FACEBOOK_ACCESS_TOKEN expires.

            The token runs the entire Meta integration (push, insights, research)
            and lapses every ~60 days. Alert at <=7 days out, or immediately if it
            reads as invalid — so rotation is a calendar item, not an outage.
            Warns daily inside the window; the countdown makes urgency obvious.
            """
            try:
                from app.services.token_monitor import check_token_expiry
                from app.services import slack_service
                import time as _time
                r = check_token_expiry()
                if not r["checked"]:
                    print(f"⚠️  Token expiry check skipped: {r.get('error')}")
                    return
                if r["never_expires"]:
                    print("✅ Token check: never-expires token, nothing to warn")
                    return
                days = r["days_left"]
                if (not r["is_valid"]) or (days is not None and days <= 7):
                    expires_on = _time.strftime("%Y-%m-%d", _time.gmtime(r["expires_at"])) if r["expires_at"] else "unknown"
                    slack_service.send_token_expiry_alert(days, expires_on, r["is_valid"])
                    print(f"🔔 Token expiry alert sent (valid={r['is_valid']}, days_left={days})")
                else:
                    print(f"✅ Token check: valid, {days:.0f} days left — no alert")
            except Exception as exc:
                print(f"⚠️  Token expiry check error: {exc}")

        def scheduled_capi_quality_sync():
            """Daily: pull Meta's Dataset Quality (Event Match Quality) for every
            pixel currently in use, one snapshot per pixel per day.

            EMQ moves slowly (it's a rolling quality signal, not a live metric),
            so once a day is plenty — this exists to build a trend, not to catch
            same-day swings.
            """
            db = SessionLocal()
            try:
                from app.services.capi_quality_service import sync_capi_quality
                result = sync_capi_quality(db)
                if result.get("skipped_reason"):
                    print(f"⚠️  CAPI quality sync skipped: {result['skipped_reason']}")
                else:
                    print(
                        f"✅ CAPI quality sync: {result.get('synced', 0)} pixel(s) synced, "
                        f"{result.get('failed', 0)} failed, {result.get('tracked_pixels', 0)} tracked"
                    )
            except Exception as exc:
                print(f"⚠️  CAPI quality sync error: {exc}")
            finally:
                db.close()

        def _run_drive_drift_guard(db, report):
            """Heal Drive-vs-picker gaps found by the snapshot; alert if they persist."""
            import json as _json
            from sqlalchemy import text as _text
            from app.services import slack_service
            from app.services.drive_drift_guard import STATE_KEY, run_guard
            from app.services.drive_sync_service import DriveSyncService

            def load_state():
                row = db.execute(_text("SELECT value FROM drive_sync_state WHERE key = :k"), {"k": STATE_KEY}).first()
                # End the read transaction now: the re-syncs below can run for minutes and
                # must not leave this connection idle-in-transaction.
                db.rollback()
                try:
                    return _json.loads(row[0]) if row and row[0] else None
                except (TypeError, ValueError):
                    return None

            def save_state(state):
                db.execute(
                    _text("""
                        INSERT INTO drive_sync_state (key, value, updated_at) VALUES (:k, :v, NOW())
                        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
                    """),
                    {"k": STATE_KEY, "v": _json.dumps(state)},
                )
                db.commit()

            def heal_package(folder_id):
                heal_db = SessionLocal()
                try:
                    outcome = DriveSyncService(heal_db).sync_once(folder_id=folder_id)
                    if outcome.get("errors"):
                        # A re-sync that hit file errors did not heal the package; do not spend
                        # one of its limited attempts on it.
                        raise RuntimeError(f"re-sync finished with {outcome['errors']} error(s)")
                finally:
                    heal_db.close()

            try:
                outcome = run_guard(
                    report,
                    load_state=load_state,
                    save_state=save_state,
                    heal=heal_package,
                    alert=lambda summary, detail: slack_service.send_drive_sync_alert(
                        summary, detail, headline="Google Drive library is out of step with Drive"
                    ),
                )
                if outcome["gaps"]:
                    print(f"🩹 Drive drift guard: {outcome['gaps']} package(s) with gaps, re-synced {len(outcome['healed'])}, {outcome['persistent']} persistent")
            except Exception as exc:
                print(f"⚠️  Drive drift guard error: {exc}")

        def scheduled_drive_health_snapshot():
            """Precompute the Drive package health report into drive_sync_state.

            The endpoint only ever reads this row. Building inline would mean a
            multi-minute HTTP request that also pins a DB connection for its
            whole duration.
            """
            db = SessionLocal()
            try:
                from app.api.v1.drive_health import refresh_package_health_snapshot
                report = refresh_package_health_snapshot(db)
                flagged = sum(1 for package in report.get("packages", []) if package.get("issues"))
                print(
                    "✅ Drive package health: "
                    f"{len(report.get('packages', []))} packages, {flagged} flagged, "
                    f"{len(report.get('collisions', []))} filename collisions"
                )
                _run_drive_drift_guard(db, report)
            except Exception as exc:
                print(f"⚠️  Drive package health snapshot error: {exc}")
            finally:
                db.close()

        def scheduled_drive_sync():
            """Pull shared Google Drive creative into the existing R2-backed library."""
            for attempt in range(1, 3):
                db = SessionLocal()
                try:
                    from app.services.drive_sync_service import DriveSyncService
                    result = DriveSyncService(db).sync_once()
                    # New media and its copy document frequently land in separate
                    # Drive events. A media-first event is intentionally imported
                    # but marked unverified; immediately retry those known rows so
                    # this scheduled sync heals them without requiring Joel
                    # to press Refresh copy in the launcher. This is bounded and
                    # package-targeted, not a whole-library crawl.
                    auto_repair = DriveSyncService(db).refresh_unverified_copy_assets()
                    changed = result.get("created", 0) + result.get("updated", 0) + result.get("archived", 0)
                    errors = result.get("errors", 0)
                    print(
                        "✅ Drive creative sync: "
                        f"{result.get('processed', 0)} processed, {result.get('created', 0)} created, "
                        f"{result.get('updated', 0)} updated, {result.get('archived', 0)} archived, "
                        f"{result.get('skipped', 0)} skipped, {errors} errors"
                    )
                    if not changed:
                        print("ℹ️  Drive creative sync: no asset changes")
                    if errors:
                        print(f"⚠️  Drive creative sync: {errors} file(s) failed and were isolated (see warnings above)")
                    if auto_repair.get("processed") or auto_repair.get("errors"):
                        print(
                            "🔁 Drive copy auto-repair: "
                            f"{auto_repair.get('processed', 0)} checked, "
                            f"{auto_repair.get('updated', 0)} updated, "
                            f"{auto_repair.get('errors', 0)} still failing"
                        )
                    # The persistent run log keeps exhausted file failures visible
                    # to the recovery job and watchdog. Do not post operational
                    # alerts to Slack from this scheduler.
                    exhausted = result.get("retries_exhausted") or []
                    if exhausted:
                        lines = [f"{item['name']} — {item.get('error') or 'unknown error'}" for item in exhausted[:8]]
                        if len(exhausted) > 8:
                            lines.append(f"…and {len(exhausted) - 8} more")
                        print(f"⚠️  Drive creative sync: {len(exhausted)} file(s) still failing after automatic retries: {'; '.join(lines)}")
                    return
                except Exception as exc:
                    # The run logger records the failed attempt independently.
                    # One immediate retry covers transient Drive/network failures
                    # without waiting until tomorrow's scheduled sync.
                    if attempt == 1 and getattr(exc, "status_code", None) != 409:
                        print(f"⚠️  Drive creative sync attempt 1 failed; retrying once: {exc}")
                        continue
                    print(f"⚠️  Drive creative sync error: {exc}")
                    return
                finally:
                    # Do not keep the attempt's connection open while a retry
                    # starts a fresh transaction and advisory-lock attempt.
                    db.close()

        def scheduled_drive_recovery():
            """Retry a failed daily sync or its remaining unverified creatives later that day."""
            db = SessionLocal()
            try:
                from app.services.drive_sync_service import DriveSyncService
                row = db.execute(
                    _text(
                        """
                        SELECT status
                        FROM drive_sync_runs
                        WHERE kind IN ('incremental', 'backfill')
                        ORDER BY started_at DESC, id DESC
                        LIMIT 1
                        """
                    )
                ).first()
                status = row[0] if row else None
                if status in {"error", "ok_with_errors"}:
                    print(f"🔁 Drive recovery: latest sync status is {status}; retrying the changes feed")
                    db.close()
                    db = None
                    scheduled_drive_sync()
                    return
                result = DriveSyncService(db).refresh_unverified_copy_assets()
                if result.get("auto_repair_candidates"):
                    print(
                        "🔁 Drive recovery: "
                        f"{result.get('processed', 0)} unverified creative(s) checked, "
                        f"{result.get('updated', 0)} updated, {result.get('errors', 0)} still failing"
                    )
            except Exception as exc:
                print(f"⚠️  Drive recovery error: {exc}")
            finally:
                if db is not None:
                    db.close()

        def scheduled_drive_reconcile():
            """Daily safety net: import Drive media the change feed never delivered."""
            db = SessionLocal()
            try:
                from app.services.drive_sync_service import DriveSyncService
                result = DriveSyncService(db).reconcile_missing_media()
                if not result.get("ran"):
                    print("ℹ️  Drive reconcile skipped: another sync holds the lock")
                elif result["missing"]:
                    print(
                        f"⚠️  Drive reconcile found {result['missing']} media file(s) missing from the library: "
                        f"{result['created']} imported, {result['errors']} failed, {result['deferred']} deferred"
                        + (f", {result['unmatched_brand']} in folders matching no brand ({', '.join(result.get('unmatched_brand_names') or [])})" if result.get("unmatched_brand") else "")
                    )
                else:
                    print("✅ Drive reconcile: library matches Drive")
                # Files that fail to import land in the sync retry ledger, so the regular
                # sync retries them and alerts once if they stay broken -- no daily repeat here.
            except Exception as exc:
                print(f"⚠️  Drive reconcile error: {exc}")
            finally:
                db.close()

        def scheduled_offer_performance_check():
            """Hourly: catch Everflow conversion-flow outages (e.g. an
            advertiser-side database crash) by comparing each tracked offer's
            just-closed hour against its own trailing 7-day baseline for that
            hour. Stateless — no DB session needed. Posts to Slack only when
            an anomaly is found; silent otherwise. Built 2026-09-09 after
            Justin's DB crash silently zeroed an hour of RHO conversions with
            nobody noticing until Joel/Abel caught it live.
            """
            try:
                from app.services.offer_performance_service import check_offer_performance
                result = check_offer_performance()
                if not result.get("checked"):
                    print(f"⚠️  Offer performance check skipped: {result.get('reason')}")
                elif result.get("alerts"):
                    print(f"🔔 Offer performance alert(s): {result['alerts']}")
                else:
                    print("✅ Offer performance check: no anomalies")
            except Exception as exc:
                print(f"⚠️  Offer performance check error: {exc}")

        # These were stored on app.state so the login endpoint could fire them as
        # background tasks — that login trigger has been removed (see the note
        # above scheduled_meta_sync's docstring). Left assigned here in case
        # something else still reads app.state.*_fn; not currently invoked from
        # anywhere in the app on its own.
        app.state.meta_sync_fn = scheduled_meta_sync
        app.state.rt_sync_fn = scheduled_redtrack_sync
        app.state.token_check_fn = scheduled_token_check
        app.state.drive_sync_fn = scheduled_drive_sync
        app.state.drive_recovery_fn = scheduled_drive_recovery

        scheduler.add_job(scheduled_check, 'interval', minutes=30, id='auto_pause_check')
        scheduler.add_job(scheduled_redtrack_sync, 'interval', minutes=30, id='redtrack_sync')
        # Changes-feed sync every 15 minutes (restored 2026-10-08 at Steve's
        # request): a daily run left Joel's fresh uploads invisible to Abel for
        # up to ~19h. The feed is cheap when nothing changed, and the shared
        # advisory lock plus APScheduler's single-instance default prevent
        # overlap. The expensive full-tree work (health snapshot, reconcile) stays daily.
        scheduler.add_job(scheduled_drive_sync, 'interval', minutes=15, id='drive_creative_sync')
        # Two bounded same-day recovery windows. They only replay the change
        # feed after a failed/partial run; otherwise they re-check existing
        # unverified rows without doing a full Drive crawl.
        scheduler.add_job(
            scheduled_drive_recovery,
            'cron',
            hour='12,17',
            minute=17,
            timezone='UTC',
            id='drive_creative_recovery',
        )
        scheduler.add_job(scheduled_drive_reconcile, 'cron', hour=7, minute=40, timezone='UTC', id='drive_reconcile')
        # One daily structural report. It runs after the daily sync and
        # reconciliation so Drive-vs-picker counts reflect their completed
        # recovery work instead of competing for Drive API quota.
        scheduler.add_job(
            scheduled_drive_health_snapshot,
            'cron',
            hour=8,
            minute=17,
            timezone='UTC',
            id='drive_health_snapshot',
        )
        scheduler.add_job(scheduled_token_check, 'cron', hour=13, minute=0, timezone='UTC', id='token_expiry_check')
        scheduler.add_job(scheduled_capi_quality_sync, 'cron', hour=14, minute=0, timezone='UTC', id='capi_quality_sync')
        # PAUSED at Joel's request (2026-09-13). The hourly offer-performance
        # alert posts to #media-buys whenever an offer's just-closed hour falls
        # below 25% of its own trailing 7-day baseline; Joel asked for it to
        # stop. Paused via env var rather than by deleting this line so it can
        # be switched back on in seconds without a deploy:
        #
        #   OFFER_PERFORMANCE_MONITOR_ENABLED=true   (then restart the backend)
        #
        # Defaults to ENABLED — the monitor is meant to run, and the pause is
        # recorded on the VPS .env (which is gitignored and survives deploys),
        # not smuggled into the code's default. Anyone reading this should see a
        # live feature that is currently switched off, not a deleted one.
        offer_monitor_enabled = os.getenv(
            "OFFER_PERFORMANCE_MONITOR_ENABLED", "true"
        ).strip().lower() in ("1", "true", "yes")
        if offer_monitor_enabled:
            scheduler.add_job(scheduled_offer_performance_check, 'cron', minute=5, id='offer_performance_check')
        else:
            print("⏸  Offer performance monitor DISABLED via OFFER_PERFORMANCE_MONITOR_ENABLED — no hourly #media-buys alerts")
        # Meta/RedTrack syncs no longer fire on login — those jobs can span every
        # visible ad account and several third-party API calls, delaying the login
        # response despite being registered as background tasks. The scheduler
        # (30-min interval jobs above) and the explicit "Sync now" controls in the
        # UI are the only things that trigger a sync now.
        scheduler.start()
        app.state.scheduler = scheduler
        # Report what is actually registered. A startup line that claims the
        # offer-performance job is running while it is switched off would send
        # the next person debugging "why no alerts?" down the wrong path.
        offer_status = "offer performance hourly :05" if offer_monitor_enabled else "offer performance PAUSED"
        print(f"✅ Scheduler started (auto-pause + RedTrack every 30 min | token expiry daily 13:00 UTC | CAPI quality daily 14:00 UTC | {offer_status})")
    except Exception as e:
        print(f"⚠️  Could not start auto-pause scheduler: {e}")


@app.on_event("shutdown")
async def shutdown_event():
    """Gracefully shut down the background scheduler."""
    scheduler = getattr(app.state, "scheduler", None)
    if scheduler and scheduler.running:
        scheduler.shutdown(wait=False)
        print("🛑 Auto-pause scheduler stopped")


# Include Routers
from app.api.v1 import brands, products, research, generated_ads, templates, facebook, uploads, dashboard, copy_generation, profiles, ad_remix, prompts, ad_styles, auth, users, auto_pause, redtrack, ai_insights, ad_copy_library, intelligence, creative_angles, pnl, drive_assets, drive_health, drive_sync_runs, capi_quality, launch_packs

app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(users.router, prefix="/api/v1/users", tags=["users"])
app.include_router(brands.router, prefix="/api/v1/brands", tags=["brands"])
app.include_router(products.router, prefix="/api/v1/products", tags=["products"])
app.include_router(research.router, prefix="/api/v1/research", tags=["research"])
app.include_router(launch_packs.router, prefix="/api/v1/launch-packs", tags=["launch-packs"])
app.include_router(generated_ads.router, prefix="/api/v1/generated-ads", tags=["generated-ads"])
app.include_router(templates.router, prefix="/api/v1/templates", tags=["templates"])
app.include_router(facebook.router, prefix="/api/v1/facebook", tags=["facebook"])
app.include_router(uploads.router, prefix="/api/v1/uploads", tags=["uploads"])
app.include_router(dashboard.router, prefix="/api/v1/dashboard", tags=["dashboard"])
app.include_router(copy_generation.router, prefix="/api/v1/copy-generation", tags=["copy-generation"])
app.include_router(profiles.router, prefix="/api/v1/profiles", tags=["profiles"])
app.include_router(ad_remix.router, prefix="/api/v1/ad-remix", tags=["ad-remix"])
app.include_router(prompts.router, prefix="/api/v1/prompts", tags=["prompts"])
app.include_router(ad_styles.router, prefix="/api/v1/ad-styles", tags=["ad-styles"])
app.include_router(auto_pause.router, prefix="/api/v1/auto-pause", tags=["auto-pause"])
app.include_router(redtrack.router, prefix="/api/v1/redtrack", tags=["redtrack"])
app.include_router(ai_insights.router, prefix="/api/v1/ai-insights", tags=["ai-insights"])
app.include_router(ad_copy_library.router, prefix="/api/v1/ad-copy-library", tags=["ad-copy-library"])
app.include_router(pnl.router, prefix="/api/v1/pnl", tags=["pnl"])
app.include_router(intelligence.router, prefix="/api/v1/intelligence", tags=["intelligence"])
app.include_router(creative_angles.router, prefix="/api/v1/creative-angles", tags=["creative-angles"])
app.include_router(drive_assets.router, prefix="/api/v1/drive-assets", tags=["drive-assets"])
app.include_router(drive_health.router, prefix="/api/v1/drive", tags=["drive-health"])
app.include_router(drive_sync_runs.router, prefix="/api/v1/drive-assets", tags=["drive-assets"])
app.include_router(capi_quality.router, prefix="/api/v1/capi-quality", tags=["capi-quality"])

# Mount static files for uploads (same path as generated_ads save location)
uploads_dir = str(settings.upload_dir)
os.makedirs(uploads_dir, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=uploads_dir), name="uploads")
