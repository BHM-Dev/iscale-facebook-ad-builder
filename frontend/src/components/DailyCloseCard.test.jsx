import { describe, expect, it } from 'vitest';
import { formatCloseForSlack } from './DailyCloseCard';

describe('formatCloseForSlack', () => {
  it('uses Joel’s exact whole-dollar format and minus sign', () => {
    expect(formatCloseForSlack({ day: '2026-11-03', profit: 1301, spend: 4234, revenue: 5535, roas: 1.31,
      mtd: { profit: 2940 }, movers: { up: [{ name: 'Top one', profit: 310 }, { name: 'Top two', profit: 188 }], down: [{ name: 'Bottom', profit: -96 }] } }))
      .toBe('*Tuesday closed at +$1,301:* $4,234 Meta spend, $5,535 Everflow revenue (1.31x)\nMTD +$2,940 · Up: Top one +$310, Top two +$188 · Down: Bottom −$96');
  });
});
