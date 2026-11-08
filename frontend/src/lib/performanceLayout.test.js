import { describe, expect, it } from 'vitest';
import { deepLinkState, maxCplBucket } from './performanceLayout';

describe('maxCplBucket', () => {
  it.each([
    [{ spend: 0, leads: 0 }, { max_cpl: 50 }, true, null],
    [{ spend: 25, leads: 0 }, null, true, 'no_max'],
    [{ spend: 25, leads: 0 }, { max_cpl: 50 }, true, 'under_max'],
    [{ spend: 50, leads: 0 }, { max_cpl: 50 }, true, 'over_max'],
    [{ spend: 50, leads: 1, cpl: 50 }, { max_cpl: 50 }, true, 'under_max'],
    [{ spend: 51, leads: 1, cpl: 51 }, { max_cpl: 50 }, true, 'over_max'],
    [{ spend: 25, leads: 1, cpl: 25 }, { max_cpl: 50 }, false, 'no_max'],
  ])('classifies %o against %o', (insight, max, available, expected) => {
    expect(maxCplBucket(insight, max, available)).toBe(expected);
  });
});

describe('performance deep links', () => {
  it.each([
    ['view=attention', { statusFilter: 'flagged' }],
    ['view=top-performers', { statusFilter: 'top_performers' }],
    ['view=refresh-soon', { statusFilter: 'refresh_soon' }],
    ['view=compass&adsetId=123', { tab: 'adsets', targetAdsetId: '123' }],
    ['niche=Towing', { nicheFilter: 'Towing' }],
    ['adsetId=123', { targetAdsetId: '123' }],
    ['campaign=abc', { campaignFilter: 'abc' }],
    ['proposals=open', { proposalsOpen: true }],
    ['date_preset=last_7d&date_from=2026-11-01&date_to=2026-11-07', { tab: 'adsets' }],
  ])('preserves %s', (query, expected) => {
    expect(deepLinkState(query)).toMatchObject(expected);
  });
});
