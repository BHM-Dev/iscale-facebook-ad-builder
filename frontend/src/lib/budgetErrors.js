// Turns a budget-route error body into a readable string. The backend now returns a dict `detail`
// for 409 LARGE_BUDGET_CHANGE and a list for 422; `new Error(detail)` would print "[object Object]".
export const budgetErrorMessage = (body, fallback = 'Failed') => {
    const d = body?.detail;
    if (typeof d === 'string') return d;
    if (d && typeof d === 'object' && !Array.isArray(d) && d.message) return d.message;
    if (Array.isArray(d)) return d.map(x => x?.msg).filter(Boolean).join('; ') || fallback;
    return fallback;
};

// "3.0x increase" / "70% cut" — a raw ratio like 0.33 reads as nonsense for a decrease.
export const describeBudgetRatio = (ratio) => {
    const r = Number(ratio);
    if (!Number.isFinite(r) || r <= 0) return 'large change';
    return r >= 1 ? `${Number(r.toFixed(1))}x increase` : `${Math.round((1 - r) * 100)}% cut`;
};
