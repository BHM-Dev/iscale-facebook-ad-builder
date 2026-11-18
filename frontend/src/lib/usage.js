// Page-usage telemetry (2026-11-18). Records which page is open and for how long, batches the views, and
// sends at most one small request a minute (plus one when the tab is hidden or closed). Never throws, never
// blocks a page. Admins read the totals at /usage/summary (shown on the Feedback inbox).
import { authFetch } from './facebookApi';

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1';
const FLUSH_MS = 60 * 1000;
const MAX_QUEUE = 50;

let queue = [];
let current = null;          // { path, startedAt, visibleMs, visibleSince }
let timer = null;
let installed = false;

function visibleSeconds(view, now) {
    const extra = view.visibleSince != null ? now - view.visibleSince : 0;
    return Math.max(0, Math.round((view.visibleMs + extra) / 1000));   // clock changes can go backwards
}

function closeCurrent(now = Date.now()) {
    if (!current) return;
    queue.push({ event: 'page_view', path: current.path, dwell_s: visibleSeconds(current, now) });
    if (queue.length > MAX_QUEUE) queue = queue.slice(-MAX_QUEUE);
    current = null;
}

export function flushUsage({ keepalive = false } = {}) {
    if (!queue.length) return;
    const events = queue;
    queue = [];
    const requeue = () => { queue = [...events, ...queue].slice(-MAX_QUEUE); };
    authFetch(`${API_BASE}/usage/events`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ events }),
        keepalive,
    }).then(res => { if (!res?.ok && res?.status >= 500) requeue(); }).catch(requeue);
}

function onVisibility() {
    const now = Date.now();
    if (document.visibilityState === 'hidden') {
        // Pause the clock (only visible time counts) and send what's queued; the open view is
        // sent when the person navigates away or closes the tab (pagehide).
        if (current && current.visibleSince != null) { current.visibleMs += now - current.visibleSince; current.visibleSince = null; }
        flushUsage({ keepalive: true });
    } else if (current && current.visibleSince == null) {
        current.visibleSince = now;
    }
}

// Call on every route change with the new pathname.
export function trackPageView(pathname) {
    if (typeof window === 'undefined') return;
    if (!installed) {
        installed = true;
        document.addEventListener('visibilitychange', onVisibility);
        window.addEventListener('pagehide', () => { closeCurrent(); flushUsage({ keepalive: true }); });
        timer = setInterval(() => flushUsage(), FLUSH_MS);
    }
    const now = Date.now();
    if (current && current.path === pathname) return;
    closeCurrent(now);
    const visible = document.visibilityState !== 'hidden';
    current = { path: pathname, startedAt: now, visibleMs: 0, visibleSince: visible ? now : null };
}

// For tests.
export function _usageState() { return { queue, current, timer }; }
