// Launch budget guardrail (2026-11-17). Flags a new budget that looks like a typo before anything is
// created in Meta. Seen live in AdStellar: typing 20 into a field already holding 10 produced $1,020/day
// per ad set and the review page didn't blink. The comparison is against what THIS account already runs
// (ACTIVE ad sets / CBO campaigns in the local DB), because "normal" differs by 10x between accounts.
import { useEffect, useState } from 'react';
import { authFetch } from './facebookApi';
import { namingAccountId } from './useNamingPreset';

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1';

// Used when an account has fewer than MIN_SAMPLES active budgets to compare against.
export const FALLBACK_WARN_ABOVE = 500;
const MIN_SAMPLES = 3;
// The launch as a whole is flagged when it adds more than this share of what the account spends today.
const TOTAL_SHARE_WARN = 0.5;
const TOTAL_MIN_WARN = 500;

const money = (n) => `$${Number(n).toLocaleString('en-US', { maximumFractionDigits: 2 })}`;

// Above this daily amount a single budget is called unusual: 3x the typical budget, or 1.5x the largest
// active one, whichever is higher. A $200 test on an account whose biggest ad set is $150 stays quiet.
export function warnAbove(stats) {
    if (!stats || !stats.count || stats.count < MIN_SAMPLES || !stats.median) {
        return Math.max(FALLBACK_WARN_ABOVE, stats?.max ? stats.max * 1.5 : 0);
    }
    return Math.max(stats.median * 3, (stats.max || 0) * 1.5);
}

export function impliedDaily(lifetime, startTime, endTime) {
    const total = Number(lifetime);
    if (!total || !endTime) return null;
    const days = Math.max(1, Math.round((new Date(endTime) - new Date(startTime || Date.now())) / 86400000));
    return Number.isFinite(days) ? total / days : null;
}

// One budget field. Returns a plain-language reason, or null when the amount looks normal.
export function assessBudget({ amount, scheduleType, startTime, endTime, level, baseline }) {
    const daily = scheduleType === 'LIFETIME' ? impliedDaily(amount, startTime, endTime) : Number(amount);
    if (!daily || daily <= 0) return null;
    const stats = level === 'campaign' ? baseline?.cbo : baseline?.adset;
    // A campaign budget covers several ad sets, so with too few CBO campaigns to compare against, allow
    // about four typical ad sets' worth before warning (RHO: $900/day) instead of one.
    const limit = level === 'campaign' && !(stats?.count >= MIN_SAMPLES)
        ? Math.max(FALLBACK_WARN_ABOVE, warnAbove(baseline?.adset) * 4)
        : warnAbove(stats);
    if (daily <= limit) return null;
    const what = level === 'campaign' ? 'campaign budget' : 'ad set budget';
    const shown = scheduleType === 'LIFETIME' ? `${money(amount)} lifetime (about ${money(daily)}/day)` : `${money(daily)}/day`;
    const typical = stats?.count >= MIN_SAMPLES && stats.median
        ? `This account's typical active ${what} is ${money(stats.median)}/day (largest ${money(stats.max)}).`
        : `That's above ${money(limit)}/day.`;
    return `${shown} is unusually high. ${typical} Check for a typo.`;
}

// Everything the Launch button should double-check, for a launch that creates new budgets.
export function assessLaunchBudget({ campaignData, adsetData, adsetCount = 1, baseline, pageWarning = null }) {
    const reasons = pageWarning ? [pageWarning] : [];
    if (!baseline) return reasons;
    const newCampaignBudget = campaignData?.budgetType === 'CBO' && !campaignData?.isExisting;
    const newAdsetBudget = campaignData?.budgetType === 'ABO' && !adsetData?.isExisting;
    let addedDaily = 0;
    if (newCampaignBudget) {
        const lifetime = campaignData.budgetScheduleType === 'LIFETIME';
        const amount = lifetime ? campaignData.lifetimeBudget : campaignData.dailyBudget;
        const reason = assessBudget({ amount, scheduleType: campaignData.budgetScheduleType, startTime: campaignData.startTime, endTime: campaignData.endTime || campaignData.stopTime, level: 'campaign', baseline });
        if (reason) reasons.push(reason);
        addedDaily += (lifetime ? impliedDaily(amount, campaignData.startTime, campaignData.endTime || campaignData.stopTime) : Number(amount)) || 0;
    }
    if (newAdsetBudget) {
        const lifetime = adsetData.budgetScheduleType === 'LIFETIME';
        const amount = lifetime ? adsetData.lifetimeBudget : adsetData.dailyBudget;
        const reason = assessBudget({ amount, scheduleType: adsetData.budgetScheduleType, startTime: adsetData.startTime, endTime: adsetData.endTime, level: 'adset', baseline });
        if (reason) reasons.push(adsetCount > 1 ? `${adsetCount} new ad sets, each at ${reason.charAt(0).toLowerCase()}${reason.slice(1)}` : reason);
        addedDaily += ((lifetime ? impliedDaily(amount, adsetData.startTime, adsetData.endTime) : Number(amount)) || 0) * Math.max(1, adsetCount);
    }
    const today = Number(baseline.active_daily_total) || 0;
    if (addedDaily > TOTAL_MIN_WARN && today > 0 && addedDaily > today * TOTAL_SHARE_WARN) {
        reasons.push(`Together this launch adds about ${money(addedDaily)}/day once activated, ${Math.round((addedDaily / today) * 100)}% of the ${money(today)}/day this account runs today.`);
    }
    return reasons;
}

// Commercial accounts post as DailyInsurance.news. Returns a warning when a Commercial launch is set to
// another named Page (usually a leftover from a Home Services launch), else null.
export function commercialPageWarning(account, pageName) {
    if (!/commercial/i.test(account?.name || '') || !pageName) return null;
    if (String(pageName).trim().toLowerCase() === 'dailyinsurance.news') return null;
    return `This Commercial launch posts as ${pageName}, not DailyInsurance.news. Change it on the Creative step if that's wrong.`;
}

// What to pass when the baseline hasn't loaded or couldn't be read: every check falls back to
// FALLBACK_WARN_ABOVE instead of staying silent.
export const BUDGET_BASELINE_UNKNOWN = Object.freeze({ adset: null, cbo: null, active_daily_total: 0 });

// Fetches the account's baseline once per account. null while loading (callers pass
// BUDGET_BASELINE_UNKNOWN at launch time so a fast click is still checked).
export function useBudgetBaseline(account) {
    const accountId = typeof account === 'string' ? account : namingAccountId(account);
    const [loaded, setLoaded] = useState({ accountId: null, data: null });
    useEffect(() => {
        if (!accountId) return undefined;
        let cancelled = false;
        const empty = BUDGET_BASELINE_UNKNOWN;
        authFetch(`${API_BASE}/facebook/budget-baseline?ad_account_id=${encodeURIComponent(accountId)}`)
            .then(res => (res.ok ? res.json() : null))
            .then(data => { if (!cancelled) setLoaded({ accountId, data: data || empty }); })
            .catch(() => { if (!cancelled) setLoaded({ accountId, data: empty }); });
        return () => { cancelled = true; };
    }, [accountId]);
    return accountId && loaded.accountId === accountId ? loaded.data : null;
}
