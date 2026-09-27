import { describe, expect, it } from 'vitest';
import { resolveGlobalWebsiteUrl } from './driveCreativeSelection';

describe('resolveGlobalWebsiteUrl', () => {
    const existingUrl = 'https://www.getbusinesscoverage.com/quote-v2';

    it('preserves the global URL when selected Drive assets have no copy or URL', () => {
        expect(resolveGlobalWebsiteUrl({ previousUrl: existingUrl })).toBe(existingUrl);
    });

    it('adopts one verified Drive destination only when the buyer has not edited the URL', () => {
        expect(resolveGlobalWebsiteUrl({
            previousUrl: existingUrl,
            suggestedUrl: 'https://example.com/verified-drive-package',
        })).toBe('https://example.com/verified-drive-package');
    });

    it('keeps a buyer-entered URL instead of replacing it with Drive metadata', () => {
        expect(resolveGlobalWebsiteUrl({
            previousUrl: existingUrl,
            suggestedUrl: 'https://example.com/verified-drive-package',
            wasManuallyEdited: true,
        })).toBe(existingUrl);
    });

    it('fails closed for conflicting Drive destinations unless the buyer already chose a URL', () => {
        expect(resolveGlobalWebsiteUrl({
            previousUrl: existingUrl,
            hasConflictingDestinations: true,
        })).toBe('');
        expect(resolveGlobalWebsiteUrl({
            previousUrl: existingUrl,
            hasConflictingDestinations: true,
            wasManuallyEdited: true,
        })).toBe(existingUrl);
    });
});
