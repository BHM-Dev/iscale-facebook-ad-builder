import { describe, expect, it } from 'vitest';
import { parseApiError, validateRuleNumbers } from './autoPauseRules';

describe('auto-pause rule helpers', () => {
  it('formats string, object, and validation errors', () => {
    expect(parseApiError({ detail: 'Nope' })).toBe('Nope');
    expect(parseApiError({ detail: { message: 'Too large' } })).toBe('Too large');
    expect(parseApiError({ detail: [{ loc: ['body', 'threshold'], msg: 'invalid' }] })).toBe('invalid (threshold)');
  });

  it('rejects unsafe or incomplete rule numbers', () => {
    expect(validateRuleNumbers({ metric: 'cpl', threshold: '', min_spend: 20, action: 'pause' })).toMatch(/threshold/i);
    expect(validateRuleNumbers({ metric: 'ctr', threshold: 101, min_spend: 20, action: 'pause' })).toMatch(/no more than 100/i);
    expect(validateRuleNumbers({ metric: 'cpl', threshold: 50, min_spend: 0, action: 'pause' })).toMatch(/at least \$1/i);
    expect(validateRuleNumbers({ metric: 'cpl', threshold: 50, min_spend: 0, action: 'notify' })).toBeNull();
    expect(validateRuleNumbers({ metric: 'cpl', threshold: 50, min_spend: 20, action: 'increase_budget', budget_adjust_pct: 20 })).toBeNull();
    expect(validateRuleNumbers({ metric: 'cpl', threshold: 50, min_spend: 20, action: 'increase_budget', budget_adjust_pct: 20.5 })).toMatch(/whole number/i);
  });
});
