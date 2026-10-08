export const RULE_WARN_ABOVE = { cpl: 500, cpa: 500, ctr: 20, roas: 10 };
export const RULE_CAPS = { cpl: 10000, cpa: 10000, ctr: 100, roas: 20 };

export { parseApiError } from './apiErrors';

export const validateRuleNumbers = ({ metric, threshold, min_spend, action, budget_adjust_pct }) => {
  const value = Number(threshold);
  const spend = Number(min_spend);
  const cap = RULE_CAPS[metric] || 10000;
  // The server stores threshold and min_spend as integers, so a decimal would come back as a 422.
  if (threshold === '' || threshold == null || !Number.isInteger(value) || value <= 0 || value > cap) return `Threshold must be a whole number from 1 to ${cap}.`;
  if (min_spend === '' || min_spend == null) return action === 'notify' ? null : 'Minimum spend must be at least $1 for this action.';
  if (!Number.isInteger(spend) || spend < 0) return 'Minimum spend must be a whole number of dollars.';
  if (spend < 1 && action !== 'notify') return 'Minimum spend must be at least $1 for this action.';
  if (['increase_budget', 'decrease_budget', 'increase_bid', 'decrease_bid'].includes(action)) {
    const pct = Number(budget_adjust_pct);
    if (!Number.isInteger(pct) || pct < 1 || pct > 100) return 'Adjustment percentage must be a whole number from 1 to 100.';
  }
  return null;
};

// Form inputs hold strings; the API wants integers. An empty notify min_spend becomes 0.
export const ruleNumbersForPayload = ({ threshold, min_spend, budget_adjust_pct }, sendPercent) => ({
  threshold: Number(threshold),
  min_spend: min_spend === '' || min_spend == null ? 0 : Number(min_spend),
  budget_adjust_pct: sendPercent ? Number(budget_adjust_pct) : null,
});
