export const RULE_WARN_ABOVE = { cpl: 500, cpa: 500, ctr: 20, roas: 10 };
export const RULE_CAPS = { cpl: 10000, cpa: 10000, ctr: 100, roas: 20 };

export const parseApiError = (body, fallback = 'Request failed') => {
  const detail = body?.detail;
  if (typeof detail === 'string') return detail;
  if (detail && typeof detail === 'object' && !Array.isArray(detail)) return detail.message || detail.detail || fallback;
  if (Array.isArray(detail)) return detail.map(item => {
    const location = Array.isArray(item?.loc) ? ` (${item.loc.slice(1).join('.')})` : '';
    return `${item?.msg || item?.detail || JSON.stringify(item)}${location}`;
  }).join('; ') || fallback;
  return fallback;
};

export const validateRuleNumbers = ({ metric, threshold, min_spend, action, budget_adjust_pct }) => {
  const value = Number(threshold);
  const spend = Number(min_spend);
  if (!Number.isFinite(value) || value <= 0 || value > (RULE_CAPS[metric] || 10000)) return `Threshold must be greater than 0 and no more than ${RULE_CAPS[metric] || 10000}.`;
  if (!Number.isFinite(spend) || spend < 1) return action === 'notify' ? null : 'Minimum spend must be at least $1 for this action.';
  if (['increase_budget', 'decrease_budget', 'increase_bid', 'decrease_bid'].includes(action)) {
    const pct = Number(budget_adjust_pct);
    if (!Number.isInteger(pct) || pct < 1 || pct > 100) return 'Adjustment percentage must be a whole number from 1 to 100.';
  }
  return null;
};
