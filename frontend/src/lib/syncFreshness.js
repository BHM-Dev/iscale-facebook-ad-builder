// How fresh is the structure data (status, budgets) on Campaign Performance? Those come from the
// local DB, refreshed only by Sync — spend/CPL/ROAS are live. Without a visible age, Joel can act
// on a stale "$50/day" or ACTIVE badge next to a live $400 spend.

export const STALE_AFTER_MINUTES = 30;

const relative = (ms) => {
    const minutes = Math.floor(ms / 60000);
    if (minutes < 1) return 'just now';
    if (minutes < 60) return `${minutes} min ago`;
    const hours = Math.floor(minutes / 60);
    if (hours < 48) return `${hours} h ago`;
    return `${Math.floor(hours / 24)} d ago`;
};

// adsets: rows from /facebook/adsets/saved ({ fb_adset_id, synced_at }).
// Reports the OLDEST row (conservative): one stale ad set makes the whole view "stale".
export const summarizeSyncFreshness = (adsets, now = Date.now()) => {
    // Only rows a Sync can keep fresh and that are actionable: an ad set deleted/archived in Meta is
    // never re-stamped, and would otherwise pin the badge amber forever.
    const rows = (adsets || []).filter(a => a && a.fb_adset_id
        && ['ACTIVE', 'PAUSED'].includes(String(a.status || '').toUpperCase())
        // Leftover test/legacy ad sets under an archived or deleted campaign can never be refreshed.
        && !['ARCHIVED', 'DELETED'].includes(String(a.campaign_status || '').toUpperCase()));
    if (rows.length === 0) return { state: 'empty', label: '', neverCount: 0 };
    const times = rows.map(a => (a.synced_at ? new Date(a.synced_at).getTime() : NaN));
    const neverCount = times.filter(t => !Number.isFinite(t)).length;
    const known = times.filter(Number.isFinite);
    if (known.length === 0) {
        return { state: 'unknown', label: 'Sync time unknown — press Sync', neverCount };
    }
    const oldest = Math.min(...known);
    const age = Math.max(0, now - oldest);
    // Colour follows the age of rows a Sync CAN refresh. Rows that were never stamped even after a
    // Sync (legacy duplicates, ad sets deleted in Meta, another account's) would otherwise pin the
    // badge amber forever; they are reported separately instead of hidden.
    const stale = age > STALE_AFTER_MINUTES * 60000;
    const label = `Synced ${relative(age)}${neverCount > 0 ? ` · ${neverCount} not refreshed` : ''}`;
    return { state: stale ? 'stale' : 'fresh', label, neverCount, oldestAt: new Date(oldest).toISOString() };
};
