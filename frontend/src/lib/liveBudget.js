// Live Meta budget read + change math shared by the Dashboard's budget actions.
// Local-DB budgets go stale (only Sync refreshes them), so any confirm that says "from $X" must read
// the live value first. Returns cents, null (object has no daily budget of its own: lifetime budget
// or CBO child), or undefined (read failed — caller falls back to the cached value and says so).
export async function fetchLiveBudgetCents(authFetch, apiBase, type, id, timeoutMs = 4000) {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), timeoutMs);
    try {
        const res = await authFetch(`${apiBase}/facebook/${type === 'campaign' ? 'campaigns' : 'adsets'}/${encodeURIComponent(id)}`, { signal: ctrl.signal });
        if (!res.ok) return undefined;
        const data = await res.json();
        const cents = Number(data.daily_budget);
        return Number.isFinite(cents) && cents > 0 ? cents : null;
    } catch {
        return undefined;
    } finally {
        clearTimeout(timer);
    }
}

// "+20%" / "-33%"; null when there is no usable "from" value.
export const budgetPercentChange = (fromDollars, toDollars) => {
    const from = Number(fromDollars);
    const to = Number(toDollars);
    if (!Number.isFinite(from) || from <= 0 || !Number.isFinite(to)) return null;
    const pct = Math.round(((to - from) / from) * 100);
    return `${pct >= 0 ? '+' : ''}${pct}%`;
};
