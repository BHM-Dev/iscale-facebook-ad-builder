import { describe, it, expect, vi } from 'vitest';
import { fetchLiveBudgetCents, budgetPercentChange } from './liveBudget';

describe('budgetPercentChange', () => {
    it('formats increases, cuts and unusable inputs', () => {
        expect(budgetPercentChange(50, 60)).toBe('+20%');
        expect(budgetPercentChange(100, 33)).toBe('-67%');
        expect(budgetPercentChange(60, 600)).toBe('+900%');
        expect(budgetPercentChange(0, 10)).toBeNull();
        expect(budgetPercentChange(null, 10)).toBeNull();
    });
});

describe('fetchLiveBudgetCents', () => {
    const res = (ok, body) => ({ ok, json: async () => body });
    it('returns cents for a daily budget', async () => {
        const f = vi.fn().mockResolvedValue(res(true, { daily_budget: '5000' }));
        expect(await fetchLiveBudgetCents(f, '/api', 'adset', '1')).toBe(5000);
        expect(f.mock.calls[0][0]).toBe('/api/facebook/adsets/1');
    });
    it('returns null when the object has no daily budget (lifetime / CBO child)', async () => {
        expect(await fetchLiveBudgetCents(vi.fn().mockResolvedValue(res(true, { daily_budget: null })), '/api', 'adset', '1')).toBeNull();
    });
    it('returns undefined when the read fails so callers can fall back and say so', async () => {
        expect(await fetchLiveBudgetCents(vi.fn().mockResolvedValue(res(false, {})), '/api', 'campaign', '1')).toBeUndefined();
        expect(await fetchLiveBudgetCents(vi.fn().mockRejectedValue(new Error('x')), '/api', 'campaign', '1')).toBeUndefined();
    });
});
