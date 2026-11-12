import { describe, expect, it } from 'vitest';
import { writeOutcomeUnknown } from './facebookApi';

// Review S1: a 5xx carrying Meta code 1/2 used to count as "nothing created", so the
// launcher offered a retry that could duplicate a live campaign / ad set / ad.
describe('writeOutcomeUnknown', () => {
    it('treats Meta code 1 and 2 on a 5xx as maybe-created', () => {
        expect(writeOutcomeUnknown(502, 1)).toBe(true);
        expect(writeOutcomeUnknown(502, 2)).toBe(true);
        expect(writeOutcomeUnknown(500, '2')).toBe(true);
    });
    it('treats a 5xx with no Meta code as maybe-created (unchanged)', () => {
        expect(writeOutcomeUnknown(500, undefined)).toBe(true);
        expect(writeOutcomeUnknown(504, null)).toBe(true);
    });
    it('keeps definite Meta rejections retryable', () => {
        expect(writeOutcomeUnknown(502, 100)).toBe(false);   // invalid parameter
        expect(writeOutcomeUnknown(502, 17)).toBe(false);    // throttle
        expect(writeOutcomeUnknown(502, 190)).toBe(false);   // token
    });
    it('never flags a 4xx', () => {
        expect(writeOutcomeUnknown(400, 2)).toBe(false);
        expect(writeOutcomeUnknown(429, null)).toBe(false);
    });
});
