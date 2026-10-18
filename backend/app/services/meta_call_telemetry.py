"""Count every Meta Graph API call by caller, so a throttle can be attributed.

Why: on 2026-10-14 Meta rate-limited the whole app (code 4 / subcode 1504022) and
there was no record of which feature was spending the budget; container logs are
wiped by each deploy. This wraps FacebookAdsApi.call (the single choke point the
facebook_business SDK routes every request through, including the separate
sessions FacebookService builds) and aggregates in memory, flushing hourly
buckets to meta_call_stats every minute.

NOT counted (they use raw `requests`, not the SDK, but still draw on the app's
budget): video/thumbnail fetches in facebook_service.py, capi_quality_service,
token_monitor, and the Ad Library scrapers (scraper.py, brand_scraper.py). If a
throttle is not explained by the counted callers, look there next.

Telemetry must never break a Meta call: every hook is wrapped so a failure here
is swallowed (logged once) and the real call proceeds untouched.
"""
import json
import logging
import re
import sys
import threading
import time
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

FLUSH_INTERVAL_SECONDS = 60
THROTTLE_CODES = {4, 17, 32, 613}
# Only these gate the WHOLE app. 80000-80014 (business-use-case limits), 32 (page) and
# 613 (can be per object) are scoped to one account/object, so they are counted as
# throttles but must not pause every other account's background work. Code 17 is a
# user-level limit; the backend uses a single token, so it is effectively app-wide.
APP_WIDE_CODES = {4, 17}
APP_WIDE_SUBCODES = {1504022}
_BUCKET_LIMIT = 5000  # hard cap on distinct keys held between flushes

_lock = threading.Lock()
_buckets: dict[tuple, dict] = {}
_installed = False
_warned = False
_dropped = 0

# Throttle backoff + alerting. When Meta throttles the app, scheduled jobs should stop
# adding load until the window passes, and Steve should hear about it before a buyer
# does. State is per-process (the backend runs a single uvicorn worker).
THROTTLE_BACKOFF_SECONDS = 600
USAGE_ALERT_PCT = 70
THROTTLE_ALERT_COOLDOWN_SECONDS = 30 * 60
USAGE_ALERT_COOLDOWN_SECONDS = 60 * 60
_throttled_until = 0.0
_last_alert = {'throttle': 0.0, 'usage': 0.0}

_ID_RE = re.compile(r'^(act_)?\d{5,}$')
_VERSION_RE = re.compile(r'^v\d+\.\d+$')
_SKIP_FILES = ('facebook_business', 'meta_call_telemetry', 'facebook_service.py', 'threading.py', 'concurrent')


def normalize_endpoint(path) -> str:
    """'/v24.0/act_123/adsets' -> 'act/adsets'; numeric object ids -> '{id}'."""
    if isinstance(path, (list, tuple)):
        parts = [str(p) for p in path]
    else:
        text = str(path).split('?')[0]
        text = re.sub(r'^https?://[^/]+', '', text)
        parts = [p for p in text.split('/') if p]
    out = []
    for p in parts:
        if _VERSION_RE.match(p):
            continue
        if p.startswith('act_') and _ID_RE.match(p):
            out.append('act')
        elif _ID_RE.match(p) or (p.isdigit() and len(p) >= 5):
            out.append('{id}')
        else:
            out.append(p)
    return '/'.join(out) or '(root)'


def _caller() -> str:
    """First stack frame outside the SDK/service plumbing: 'api/v1/auto_pause.py:_run_check'."""
    service_fn = None
    try:
        frame = sys._getframe(2)
        while frame is not None:
            filename = frame.f_code.co_filename
            if not any(skip in filename for skip in _SKIP_FILES):
                marker = filename.rfind('/app/')
                short = filename[marker + 5:] if marker != -1 else filename.rsplit('/', 1)[-1]
                return f"{short}:{frame.f_code.co_name}"
            if service_fn is None and 'facebook_service.py' in filename:
                service_fn = f"services/facebook_service.py:{frame.f_code.co_name}"
            frame = frame.f_back
    except Exception:
        pass
    # Worker threads (ThreadPoolExecutor) lose the route frame; the service
    # method that issued the call is still a useful label.
    return service_fn or 'unknown'


def _pct_max(headers) -> tuple:
    """Highest (app %, account %) usage found in Meta's usage headers, or None each."""
    app_pct = acct_pct = None
    if not headers:
        return app_pct, acct_pct

    def _get(name):
        try:
            v = headers.get(name)
            if v is None:
                for k, val in headers.items():
                    if str(k).lower() == name:
                        return val
            return v
        except Exception:
            return None

    def _nums(obj):
        vals = []
        if isinstance(obj, dict):
            for key in ('call_count', 'total_cputime', 'total_time', 'acc_id_util_pct'):
                if isinstance(obj.get(key), (int, float)):
                    vals.append(int(obj[key]))
        return vals

    try:
        raw = _get('x-app-usage')
        if raw:
            vals = _nums(json.loads(raw))
            app_pct = max(vals) if vals else None
        for name in ('x-business-use-case-usage', 'x-ad-account-usage'):
            raw = _get(name)
            if not raw:
                continue
            data = json.loads(raw)
            entries = []
            if isinstance(data, dict):
                if 'acc_id_util_pct' in data:  # x-ad-account-usage is a flat object
                    entries.append(data)
                else:
                    for v in data.values():
                        entries.extend(v if isinstance(v, list) else [v])
            vals = [n for e in entries for n in _nums(e)]
            if vals:
                acct_pct = max(vals + ([acct_pct] if acct_pct is not None else []))
    except Exception:
        pass
    return app_pct, acct_pct


def backoff_remaining() -> int:
    """Seconds until scheduled Meta jobs may run again (0 = not throttled)."""
    return max(0, int(_throttled_until - time.monotonic()))


def _alert_async(kind, cooldown, summary, detail):
    """DM Steve at most once per cooldown per kind; never blocks or breaks the Meta call."""
    now = time.monotonic()
    with _lock:
        if _last_alert[kind] and now - _last_alert[kind] < cooldown:
            return
        _last_alert[kind] = now

    def _send():
        try:
            from app.services.slack_service import send_meta_limit_alert
            if not send_meta_limit_alert(summary, detail):
                with _lock:
                    _last_alert[kind] = 0.0  # delivery failed: don't suppress the next attempt
        except Exception:
            with _lock:
                _last_alert[kind] = 0.0
            logger.exception("meta_call_telemetry alert failed")

    threading.Thread(target=_send, name='meta-limit-alert', daemon=True).start()


def _record(method, path, caller, elapsed_ms, headers, error_code, failed, error_subcode=None):
    global _warned
    try:
        hour = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        key = (hour, caller, str(method).upper(), normalize_endpoint(path))
        app_pct, acct_pct = _pct_max(headers)
        throttled = failed and error_code is not None and (error_code in THROTTLE_CODES or 80000 <= error_code <= 80014)
        with _lock:
            b = _buckets.get(key)
            if b is None:
                if len(_buckets) >= _BUCKET_LIMIT:
                    global _dropped
                    _dropped += 1
                    if _dropped in (1, 100, 10000):
                        logger.warning("meta_call_telemetry bucket cap hit; %d call(s) not recorded", _dropped)
                    return
                b = _buckets[key] = {'calls': 0, 'errors': 0, 'throttles': 0, 'total_ms': 0, 'app': None, 'acct': None}
            b['calls'] += 1
            b['total_ms'] += int(elapsed_ms)
            if failed:
                b['errors'] += 1
            if throttled:
                b['throttles'] += 1
            if app_pct is not None:
                b['app'] = app_pct if b['app'] is None else max(b['app'], app_pct)
            if acct_pct is not None:
                b['acct'] = acct_pct if b['acct'] is None else max(b['acct'], acct_pct)
        if throttled:
            if error_code in APP_WIDE_CODES or error_subcode in APP_WIDE_SUBCODES:
                global _throttled_until
                now_m = time.monotonic()
                # Fixed window from the FIRST throttle: retries into a throttle must not
                # keep extending it, or a polling UI would hold background jobs off forever.
                if now_m >= _throttled_until:
                    _throttled_until = now_m + THROTTLE_BACKOFF_SECONDS
            logger.warning("Meta throttle (code %s) on %s %s from %s; app_usage=%s%% account_usage=%s%%",
                           error_code, method, key[3], caller, app_pct, acct_pct)
            _alert_async(
                'throttle', THROTTLE_ALERT_COOLDOWN_SECONDS,
                f"Meta is throttling the app (code {error_code}). The scheduled Meta sync pauses for ~{THROTTLE_BACKOFF_SECONDS // 60} min; launches may fail until it clears.",
                f"First seen on {method} {key[3]} from {caller}. App usage {app_pct}%, account usage {acct_pct}%. Details: GET /api/v1/facebook/meta-call-stats",
            )
        else:
            peak = max([p for p in (app_pct, acct_pct) if p is not None], default=None)
            if peak is not None and peak >= USAGE_ALERT_PCT:
                _alert_async(
                    'usage', USAGE_ALERT_COOLDOWN_SECONDS,
                    f"Meta API usage is at {peak}% of the limit (app {app_pct}%, account {acct_pct}%). Throttling starts at 100%.",
                    f"Latest call: {method} {key[3]} from {caller}. Details: GET /api/v1/facebook/meta-call-stats",
                )
    except Exception:
        if not _warned:
            _warned = True
            logger.exception("meta_call_telemetry record failed (further failures suppressed)")


def _wrap(original):
    def call(self, method, path, *args, **kwargs):
        caller = _caller()
        started = time.monotonic()
        try:
            response = original(self, method, path, *args, **kwargs)
        except Exception as exc:
            headers = code = subcode = None
            try:
                headers = exc.http_headers() if callable(getattr(exc, 'http_headers', None)) else None
                code = exc.api_error_code() if callable(getattr(exc, 'api_error_code', None)) else None
                subcode = exc.api_error_subcode() if callable(getattr(exc, 'api_error_subcode', None)) else None
            except Exception:
                pass
            _record(method, path, caller, (time.monotonic() - started) * 1000, headers, code, True, subcode)
            raise
        headers = None
        try:
            headers = response.headers()
        except Exception:
            pass
        _record(method, path, caller, (time.monotonic() - started) * 1000, headers, None, False)
        return response
    call._meta_telemetry = True
    return call


def flush() -> int:
    """Upsert in-memory buckets into meta_call_stats. Returns rows written."""
    with _lock:
        pending = dict(_buckets)
        _buckets.clear()
    if not pending:
        return 0
    from sqlalchemy import text
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        for (hour, caller, method, endpoint), b in pending.items():
            db.execute(text("""
                INSERT INTO meta_call_stats
                    (hour_start, caller, method, endpoint, calls, errors, throttles, total_ms, app_usage_max, account_usage_max)
                VALUES (:hour, :caller, :method, :endpoint, :calls, :errors, :throttles, :total_ms, :app, :acct)
                ON CONFLICT (hour_start, caller, method, endpoint) DO UPDATE SET
                    calls = meta_call_stats.calls + EXCLUDED.calls,
                    errors = meta_call_stats.errors + EXCLUDED.errors,
                    throttles = meta_call_stats.throttles + EXCLUDED.throttles,
                    total_ms = meta_call_stats.total_ms + EXCLUDED.total_ms,
                    app_usage_max = GREATEST(meta_call_stats.app_usage_max, EXCLUDED.app_usage_max),
                    account_usage_max = GREATEST(meta_call_stats.account_usage_max, EXCLUDED.account_usage_max)
            """), {'hour': hour, 'caller': caller, 'method': method, 'endpoint': endpoint,
                   'calls': b['calls'], 'errors': b['errors'], 'throttles': b['throttles'],
                   'total_ms': b['total_ms'], 'app': b['app'], 'acct': b['acct']})
        db.commit()
        return len(pending)
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        # Put the counts back so a transient DB error doesn't lose the window.
        with _lock:
            for key, b in pending.items():
                cur = _buckets.get(key)
                if cur is None:
                    _buckets[key] = b
                else:
                    for f in ('calls', 'errors', 'throttles', 'total_ms'):
                        cur[f] += b[f]
                    for f in ('app', 'acct'):
                        if b[f] is not None:
                            cur[f] = b[f] if cur[f] is None else max(cur[f], b[f])
        logger.exception("meta_call_telemetry flush failed; will retry")
        return 0
    finally:
        db.close()


RETENTION_DAYS = 30
_PRUNE_EVERY_FLUSHES = 60 * 24  # about daily at a 60s flush interval


def prune_old_rows() -> int:
    """Delete buckets older than RETENTION_DAYS; this table is diagnostic, not a ledger."""
    from sqlalchemy import text
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        result = db.execute(
            text("DELETE FROM meta_call_stats WHERE hour_start < now() - make_interval(days => :d)"),
            {'d': RETENTION_DAYS},
        )
        db.commit()
        return result.rowcount or 0
    except Exception:
        db.rollback()
        logger.exception("meta_call_telemetry prune failed")
        return 0
    finally:
        db.close()


def _flush_loop():
    n = 0
    while True:
        time.sleep(FLUSH_INTERVAL_SECONDS)
        try:
            flush()
            n += 1
            if n % _PRUNE_EVERY_FLUSHES == 1:  # first pass after startup, then daily
                prune_old_rows()
        except Exception:
            logger.exception("meta_call_telemetry flush loop error")


def install() -> bool:
    """Wrap FacebookAdsApi.call once and start the flush thread. Safe to call repeatedly."""
    global _installed
    if _installed:
        return False
    try:
        from facebook_business.api import FacebookAdsApi
        if not getattr(FacebookAdsApi.call, '_meta_telemetry', False):
            FacebookAdsApi.call = _wrap(FacebookAdsApi.call)
        threading.Thread(target=_flush_loop, name='meta-call-telemetry', daemon=True).start()
        _installed = True
        return True
    except Exception:
        logger.exception("meta_call_telemetry install failed; continuing without telemetry")
        return False
