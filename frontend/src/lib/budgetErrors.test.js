import { describe, it, expect } from 'vitest';
import { budgetErrorMessage, describeBudgetRatio } from './budgetErrors';

describe('budgetErrorMessage', () => {
    it('handles string, dict and list details', () => {
        expect(budgetErrorMessage({ detail: 'nope' })).toBe('nope');
        expect(budgetErrorMessage({ detail: { code: 'LARGE_BUDGET_CHANGE', message: 'Confirm to proceed.' } })).toBe('Confirm to proceed.');
        expect(budgetErrorMessage({ detail: [{ msg: 'too small' }, { msg: 'bad' }] })).toBe('too small; bad');
    });
    it('falls back and never prints [object Object]', () => {
        expect(budgetErrorMessage({})).toBe('Failed');
        expect(budgetErrorMessage({ detail: { code: 1 } }, 'x')).toBe('x');
        expect(budgetErrorMessage(null, 'x')).toBe('x');
    });
});

describe('describeBudgetRatio', () => {
    it('describes increases and cuts plainly', () => {
        expect(describeBudgetRatio(10)).toBe('10x increase');
        expect(describeBudgetRatio(0.25)).toBe('75% cut');
        expect(describeBudgetRatio(0.333)).toBe('67% cut');
        expect(describeBudgetRatio(undefined)).toBe('large change');
    });
});
