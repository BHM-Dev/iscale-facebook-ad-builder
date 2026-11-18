import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('./facebookApi', () => ({ authFetch: vi.fn(() => Promise.resolve({ ok: true })) }));

describe('usage tracking', () => {
    beforeEach(() => {
        vi.resetModules();
        vi.useFakeTimers();
        Object.defineProperty(document, 'visibilityState', { value: 'visible', configurable: true });
    });

    it('queues one view per page with visible seconds and batches the send', async () => {
        const { authFetch } = await import('./facebookApi');
        const { trackPageView, flushUsage, _usageState } = await import('./usage');
        vi.setSystemTime(0);
        trackPageView('/campaign-performance');
        vi.setSystemTime(30_000);
        trackPageView('/campaign-performance');          // same page re-render: no new view
        trackPageView('/facebook-campaigns');
        expect(_usageState().queue).toEqual([{ event: 'page_view', path: '/campaign-performance', dwell_s: 30 }]);
        flushUsage();
        expect(authFetch).toHaveBeenCalledTimes(1);
        expect(JSON.parse(authFetch.mock.calls[0][1].body).events).toHaveLength(1);
        expect(_usageState().queue).toEqual([]);
    });
});
