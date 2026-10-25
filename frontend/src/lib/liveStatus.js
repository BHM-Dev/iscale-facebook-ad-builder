// Pure helpers for the Review step's live Meta status check, extracted so the
// safety-critical branches (hard block, LIVE/PAUSED claim) are unit-testable.

const KNOWN = new Set(['ACTIVE', 'PAUSED']);

// Meta returns archived/deleted objects as a normal 200 with this status, not an error.
export const isMetaObjectGone = (obj) => Boolean(obj)
    && ['ARCHIVED', 'DELETED'].some(v => obj.status === v || obj.effective_status === v);

// Only a 404 carrying Meta error code 100 means "object missing"; a bare 404
// (mis-routed proxy, frontend ahead of backend) must stay acknowledgeable.
export const isHardBlockError = (error) => Boolean(error)
    && error.httpStatus === 404 && error.metaErrorCode === 100;

// A start time only counts as "scheduled" while it is still in the future. Accepts an ISO string, a
// datetime-local string (the browser reads those in its own timezone, exactly as the launcher sends them
// to Meta) or a Date. Anything unparseable or already past returns null.
export const scheduledStartDate = (value, now = Date.now()) => {
    if (!value) return null;
    // Meta returns offsets without a colon ("2026-10-26T00:00:00-0700"); Safari/Firefox can't parse that form.
    const text = typeof value === 'string'
        ? value.trim().replace(/(T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?)([+-]\d{2})(\d{2})$/, '$1$2:$3')
        : value;
    const date = text instanceof Date ? text : new Date(text);
    return Number.isNaN(date.getTime()) || date.getTime() <= now ? null : date;
};

// How Joel and Abel talk about launch times ("midnight PT"). Shows the exact instant Meta will receive. When the
// browser is NOT in Pacific time the local equivalent is appended, because a start time typed into the date field is
// read in the browser's timezone — a mismatch (e.g. "12:00 AM" typed in ET is 9:00 PM PT) must be visible.
export const formatScheduledStart = (date, localTimeZone = Intl.DateTimeFormat().resolvedOptions().timeZone) => {
    const pt = new Intl.DateTimeFormat('en-US', {
        timeZone: 'America/Los_Angeles', weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
    }).format(date);
    if (!localTimeZone || localTimeZone === 'America/Los_Angeles') return `${pt} PT`;
    const local = new Intl.DateTimeFormat('en-US', {
        timeZone: localTimeZone, weekday: 'short', hour: 'numeric', minute: '2-digit', timeZoneName: 'short',
    }).format(date);
    return `${pt} PT (${local} your time)`;
};

// 'LIVE' | 'SCHEDULED' | 'PAUSED' | 'unknown' | 'unverified'. LIVE/PAUSED are claimed only when every status
// involved is a plain ACTIVE or PAUSED and nothing is effectively blocked. SCHEDULED is what LIVE becomes when
// the ad set has a future start time: nothing spends until then.
export const deliveryState = ({ campaign, adset = null, unverified = false, scheduledStart = null }) => {
    if (unverified) return 'unverified';
    const parts = [campaign, ...(adset ? [adset] : [])];
    if (!parts.every(p => p && KNOWN.has(p.status))) return 'unknown';
    if (parts.every(p => p.status === 'ACTIVE' && (!p.effectiveStatus || p.effectiveStatus === 'ACTIVE'))) {
        return scheduledStart ? 'SCHEDULED' : 'LIVE';
    }
    if (parts.some(p => p.status === 'PAUSED')) return 'PAUSED';
    return 'unknown';
};

export const formatCheckedAge = (completedAt, now = Date.now()) => {
    const minutes = Math.max(0, Math.floor((now - new Date(completedAt).getTime()) / 60000));
    const time = new Date(completedAt).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
    return `${time}, ${minutes < 1 ? 'just now' : `${minutes} min ago`}`;
};
