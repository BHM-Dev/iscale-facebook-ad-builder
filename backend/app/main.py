"""
Facebook Ad Builder - Backend API

Created by Jason Akatiff
iSCALE.com | A4D.com
Telegram: @jasonakatiff
Email: jason@jasonakatiff.com
"""

import os
import re
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import Response
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from app.core.config import settings
from app.core.rate_limit import limiter

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
            except Exception as exc:
                print(f"⚠️  Auto-pause scheduler error: {exc}")
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
            """Sync all Meta campaigns and ad sets into the DB every 30 minutes.

            Iterates every ad account the token can see (not just the default),
            tagging each campaign/adset with its true fb_account_id so the
            account-scoped saved-adsets list stays authoritative for ALL accounts
            on every cycle — no manual per-account backfill required.
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

        # Store sync functions on app state so auth endpoint can trigger them on login
        app.state.meta_sync_fn = scheduled_meta_sync
        app.state.rt_sync_fn = scheduled_redtrack_sync
        app.state.token_check_fn = scheduled_token_check

        scheduler.add_job(scheduled_check, 'interval', minutes=30, id='auto_pause_check')
        scheduler.add_job(scheduled_redtrack_sync, 'interval', minutes=30, id='redtrack_sync')
        scheduler.add_job(scheduled_token_check, 'cron', hour=13, minute=0, timezone='UTC', id='token_expiry_check')
        # Meta campaign sync runs on login (not on a timer — no value syncing while Joel sleeps)
        scheduler.start()
        app.state.scheduler = scheduler
        print("✅ Scheduler started (auto-pause + RedTrack every 30 min | token expiry daily 13:00 UTC | Meta sync on login)")
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
from app.api.v1 import brands, products, research, generated_ads, templates, facebook, uploads, dashboard, copy_generation, profiles, ad_remix, prompts, ad_styles, auth, users, auto_pause, redtrack, ai_insights, ad_copy_library, intelligence, creative_angles

app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(users.router, prefix="/api/v1/users", tags=["users"])
app.include_router(brands.router, prefix="/api/v1/brands", tags=["brands"])
app.include_router(products.router, prefix="/api/v1/products", tags=["products"])
app.include_router(research.router, prefix="/api/v1/research", tags=["research"])
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
app.include_router(intelligence.router, prefix="/api/v1/intelligence", tags=["intelligence"])
app.include_router(creative_angles.router, prefix="/api/v1/creative-angles", tags=["creative-angles"])

# Mount static files for uploads (same path as generated_ads save location)
uploads_dir = str(settings.upload_dir)
os.makedirs(uploads_dir, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=uploads_dir), name="uploads")
