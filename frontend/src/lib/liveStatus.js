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

// 'LIVE' | 'PAUSED' | 'unknown' | 'unverified'. LIVE/PAUSED are claimed only when
// every status involved is a plain ACTIVE or PAUSED and nothing is effectively blocked.
export const deliveryState = ({ campaign, adset = null, unverified = false }) => {
    if (unverified) return 'unverified';
    const parts = [campaign, ...(adset ? [adset] : [])];
    if (!parts.every(p => p && KNOWN.has(p.status))) return 'unknown';
    if (parts.every(p => p.status === 'ACTIVE' && (!p.effectiveStatus || p.effectiveStatus === 'ACTIVE'))) return 'LIVE';
    if (parts.some(p => p.status === 'PAUSED')) return 'PAUSED';
    return 'unknown';
};

export const formatCheckedAge = (completedAt, now = Date.now()) => {
    const minutes = Math.max(0, Math.floor((now - new Date(completedAt).getTime()) / 60000));
    const time = new Date(completedAt).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
    return `${time}, ${minutes < 1 ? 'just now' : `${minutes} min ago`}`;
};
