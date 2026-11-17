import { describe, it, expect } from 'vitest';
import { warnAbove, assessBudget, assessLaunchBudget, commercialPageWarning, FALLBACK_WARN_ABOVE } from './budgetGuard';

// RHO Commercial on 2026-11-17: 90 active ad sets, median $50/day, largest $150.
const rho = { adset: { median: 50, max: 150, count: 90, total: 5000 }, cbo: { median: 87.5, max: 100, count: 2, total: 175 }, active_daily_total: 5175 };

describe('warnAbove', () => {
    it('uses 3x the median or 1.5x the largest, whichever is higher', () => {
        expect(warnAbove(rho.adset)).toBe(225);
        expect(warnAbove({ median: 350, max: 1000, count: 19 })).toBe(1500);
    });
    it('falls back when there is too little to compare against', () => {
        expect(warnAbove({ median: 5, max: 5, count: 1 })).toBe(FALLBACK_WARN_ABOVE);
        expect(warnAbove(null)).toBe(FALLBACK_WARN_ABOVE);
    });
});

describe('assessBudget', () => {
    it('flags the 10-then-20 typo ($1,020/day) on RHO', () => {
        const r = assessBudget({ amount: 1020, scheduleType: 'DAILY', level: 'adset', baseline: rho });
        expect(r).toMatch(/\$1,020\/day is unusually high/);
        expect(r).toMatch(/typical active ad set budget is \$50\/day/);
    });
    it('stays quiet on normal and moderately large test budgets', () => {
        expect(assessBudget({ amount: 50, scheduleType: 'DAILY', level: 'adset', baseline: rho })).toBeNull();
        expect(assessBudget({ amount: 200, scheduleType: 'DAILY', level: 'adset', baseline: rho })).toBeNull();
    });
    it('judges a lifetime budget by its implied daily spend', () => {
        const start = '2026-11-18T00:00';
        expect(assessBudget({ amount: 700, scheduleType: 'LIFETIME', startTime: start, endTime: '2026-11-25T00:00', level: 'adset', baseline: rho })).toBeNull();
        expect(assessBudget({ amount: 7000, scheduleType: 'LIFETIME', startTime: start, endTime: '2026-11-25T00:00', level: 'adset', baseline: rho })).toMatch(/about \$1,000\/day/);
    });
    it('compares a CBO budget to ad set budgets when the account has few CBO campaigns', () => {
        expect(assessBudget({ amount: 600, scheduleType: 'DAILY', level: 'campaign', baseline: rho })).toBeNull();
        expect(assessBudget({ amount: 900, scheduleType: 'DAILY', level: 'campaign', baseline: rho })).toBeNull();
        expect(assessBudget({ amount: 2000, scheduleType: 'DAILY', level: 'campaign', baseline: rho })).toMatch(/unusually high/);
    });
});

describe('assessLaunchBudget', () => {
    const abo = { budgetType: 'ABO', isExisting: true };
    it('ignores launches into an existing ad set (no new budget)', () => {
        expect(assessLaunchBudget({ campaignData: abo, adsetData: { isExisting: true, dailyBudget: 5000 }, baseline: rho })).toEqual([]);
    });
    it('flags a total that is a big share of what the account runs today', () => {
        const reasons = assessLaunchBudget({ campaignData: abo, adsetData: { dailyBudget: 150, budgetScheduleType: 'DAILY' }, adsetCount: 20, baseline: rho });
        expect(reasons).toHaveLength(1);
        expect(reasons[0]).toMatch(/adds about \$3,000\/day/);
    });
    it('names the per-ad-set problem when one-per-media multiplies it', () => {
        const reasons = assessLaunchBudget({ campaignData: abo, adsetData: { dailyBudget: 1020, budgetScheduleType: 'DAILY' }, adsetCount: 2, baseline: rho });
        expect(reasons[0]).toMatch(/^2 new ad sets, each at \$1,020\/day/);
    });
    it('says nothing until the baseline has loaded', () => {
        expect(assessLaunchBudget({ campaignData: abo, adsetData: { dailyBudget: 1020 }, baseline: null })).toEqual([]);
    });
});

describe('commercialPageWarning', () => {
    const commercial = { name: 'RHO 4 - Commercial (New CAPI)' };
    it('warns only for a Commercial account on another named Page', () => {
        expect(commercialPageWarning(commercial, 'DailyInsurance.news')).toBeNull();
        expect(commercialPageWarning(commercial, 'Trusted Home Service')).toMatch(/posts as Trusted Home Service/);
        expect(commercialPageWarning({ name: 'Trusted Home Service' }, 'Trusted Home Service')).toBeNull();
        expect(commercialPageWarning(commercial, null)).toBeNull();
    });
    it('puts the Page warning in the launch confirm even without a baseline', () => {
        expect(assessLaunchBudget({ campaignData: {}, adsetData: {}, baseline: null, pageWarning: 'x' })).toEqual(['x']);
    });
});
