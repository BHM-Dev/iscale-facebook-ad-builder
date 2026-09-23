import { describe, expect, it } from 'vitest';
import {
    BULK_LAUNCH_BATCH_COOLDOWN_MS,
    BULK_LAUNCH_BATCH_SIZE,
    INTER_REQUEST_DELAY_MS,
    isRateLimitError,
    peakUsagePercent,
    rateLimitStopMessage,
} from './metaRateLimit';

describe('large-launch Meta safeguards', () => {
    it('keeps the bulk queue serial, paced, and bounded', () => {
        expect(INTER_REQUEST_DELAY_MS).toBeGreaterThan(0);
        expect(BULK_LAUNCH_BATCH_SIZE).toBeGreaterThan(0);
        expect(BULK_LAUNCH_BATCH_COOLDOWN_MS).toBeGreaterThan(INTER_REQUEST_DELAY_MS);
    });

    it('recognizes Meta throttle responses without mistaking ordinary errors for a throttle', () => {
        expect(isRateLimitError({ metaErrorCode: 17 })).toBe(true);
        expect(isRateLimitError({ metaErrorCode: 613 })).toBe(true);
        expect(isRateLimitError({ metaErrorCode: 80014 })).toBe(true);
        expect(isRateLimitError({ metaErrorCode: 100 })).toBe(false);
        expect(isRateLimitError(new Error('network failure'))).toBe(false);
    });

    it('tells the buyer to reconcile rather than blindly retry after partial writes', () => {
        const message = rateLimitStopMessage({
            created: 3,
            total: 10,
            attempted: 4,
            regainSeconds: 125,
            notAttemptedNames: ['Ad 5', 'Ad 6', 'Ad 7', 'Ad 8', 'Ad 9', 'Ad 10'],
        });

        expect(message).toContain('3 of 10 created');
        expect(message).toContain('6 not attempted');
        expect(message).toContain('3 minutes');
        expect(message).toContain("Don't press Launch again");
        expect(message).toContain('Add the missing ads in Ads Manager, or start a fresh batch containing only those.');
    });

    it('does not invent rate-limit telemetry when Meta supplied none', () => {
        expect(peakUsagePercent(null)).toBeNull();
        expect(peakUsagePercent({})).toBeNull();
        expect(peakUsagePercent({ call_count: 34, total_cputime: 82, total_time: 17 })).toBe(82);
    });
});
