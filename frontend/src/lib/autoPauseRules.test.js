import { describe, expect, it } from 'vitest';
import { parseApiError, validateRuleNumbers, ruleNumbersForPayload } from './autoPauseRules';

describe('auto-pause rule helpers', () => {
  it('formats string, object, and validation errors', () => {
    expect(parseApiError({ detail: 'Nope' })).toBe('Nope');
    expect(parseApiError({ detail: { message: 'Too large' } })).toBe('Too large');
    expect(parseApiError({ detail: [{ loc: ['body', 'threshold'], msg: 'invalid' }] })).toBe('invalid (threshold)');
  });

  it('rejects unsafe or incomplete rule numbers', () => {
    expect(validateRuleNumbers({ metric: 'cpl', threshold: '', min_spend: 20, action: 'pause' })).toMatch(/threshold/i);
    expect(validateRuleNumbers({ metric: 'ctr', threshold: 101, min_spend: 20, action: 'pause' })).toMatch(/1 to 100/i);
    expect(validateRuleNumbers({ metric: 'cpl', threshold: 50, min_spend: 0, action: 'pause' })).toMatch(/at least \$1/i);
    expect(validateRuleNumbers({ metric: 'cpl', threshold: 50, min_spend: 0, action: 'notify' })).toBeNull();
    expect(validateRuleNumbers({ metric: 'cpl', threshold: 50, min_spend: 20, action: 'increase_budget', budget_adjust_pct: 20 })).toBeNull();
    expect(validateRuleNumbers({ metric: 'cpl', threshold: 50, min_spend: 20, action: 'increase_budget', budget_adjust_pct: 20.5 })).toMatch(/whole number/i);
  });

  it('rejects decimals the integer columns cannot store', () => {
    expect(validateRuleNumbers({ metric: 'cpl', threshold: '12.5', min_spend: 20, action: 'pause' })).toMatch(/whole number/i);
    expect(validateRuleNumbers({ metric: 'roas', threshold: '1.5', min_spend: 20, action: 'pause' })).toMatch(/whole number/i);
    expect(validateRuleNumbers({ metric: 'cpl', threshold: 50, min_spend: '1.5', action: 'pause' })).toMatch(/whole number/i);
    expect(validateRuleNumbers({ metric: 'cpl', threshold: 50, min_spend: '', action: 'notify' })).toBeNull();
    expect(validateRuleNumbers({ metric: 'cpl', threshold: 50, min_spend: '', action: 'pause' })).toMatch(/at least \$1/i);
  });

  it('sends numbers, never strings, and 0 for an empty notify min_spend', () => {
    expect(ruleNumbersForPayload({ threshold: '50', min_spend: '20', budget_adjust_pct: '20' }, true)).toEqual({ threshold: 50, min_spend: 20, budget_adjust_pct: 20 });
    expect(ruleNumbersForPayload({ threshold: '50', min_spend: '', budget_adjust_pct: '20' }, false)).toEqual({ threshold: 50, min_spend: 0, budget_adjust_pct: null });
  });
});
