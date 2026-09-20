import { describe, expect, it } from 'vitest';
import { countCreativeVariations } from './launchPlan';

describe('countCreativeVariations', () => {
    it('counts standard combinations from non-empty shared fields', () => {
        expect(countCreativeVariations({ creatives: [{ id: 'a' }, { id: 'b' }, { id: 'c' }], headlines: ['H1', ' ', 'H2'], bodies: ['B1', 'B2'] })).toMatchObject({ media: 3, headlines: 2, bodies: 2, total: 12 });
    });

    it('counts Drive rows using their per-creative copy', () => {
        expect(countCreativeVariations({ creatives: [{ source: 'drive', headline: 'H1', body: 'B1' }, { source: 'drive', headline: 'H2', body: 'B2' }], headlines: ['fallback'], bodies: ['fallback'] })).toMatchObject({ media: 2, headlines: 2, bodies: 2, total: 2 });
    });

    it('uses shared copy for a manual row without overrides', () => {
        expect(countCreativeVariations({ creatives: [{ source: 'drive', headline: 'H1', body: 'B1' }, { id: 'manual' }], headlines: ['fallback 1', 'fallback 2'], bodies: ['fallback'] })).toMatchObject({ media: 2, headlines: 3, bodies: 2, total: 3 });
    });

    it('returns zero when a required dimension is empty', () => {
        expect(countCreativeVariations({ creatives: [{ id: 'a' }], headlines: [''], bodies: ['Body'] }).total).toBe(0);
    });

    it('falls back to the shared headline pool for a whitespace-only override, matching Review', () => {
        // Review's missingCopy filter falls back to creativeData.headlines[0]
        // for a non-drive row whose own headline doesn't survive .trim() — it
        // is NOT treated as a satisfied 1-count override, so the count must
        // multiply across the full shared pool just like a row with no
        // override at all.
        expect(countCreativeVariations({ creatives: [{ headline: '   ', body: 'Body' }], headlines: ['H1', 'H2'], bodies: ['B1', 'B2'] })).toMatchObject({ total: 2, headlines: 2, bodies: 1 });
    });
});
