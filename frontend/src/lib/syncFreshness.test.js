import { describe, it, expect } from 'vitest';
import { summarizeSyncFreshness } from './syncFreshness';

const NOW = new Date('2026-10-07T15:00:00Z').getTime();
const ago = (min) => new Date(NOW - min * 60000).toISOString();

describe('summarizeSyncFreshness', () => {
    it('is empty when there are no synced-capable rows', () => {
        expect(summarizeSyncFreshness([], NOW).state).toBe('empty');
        expect(summarizeSyncFreshness([{ synced_at: ago(1) }], NOW).state).toBe('empty');
    });
    it('fresh within 30 minutes, labelled relative', () => {
        const r = summarizeSyncFreshness([{ fb_adset_id: '1', status: 'ACTIVE', synced_at: ago(5) }, { fb_adset_id: '2', status: 'PAUSED', synced_at: ago(12) }], NOW);
        expect(r.state).toBe('fresh');
        expect(r.label).toBe('Synced 12 min ago');
    });
    it('goes stale past 30 minutes and reports hours', () => {
        const r = summarizeSyncFreshness([{ fb_adset_id: '1', status: 'ACTIVE', synced_at: ago(180) }], NOW);
        expect(r.state).toBe('stale');
        expect(r.label).toBe('Synced 3 h ago');
    });
    it('one stale row makes the whole view stale (oldest wins)', () => {
        const r = summarizeSyncFreshness([{ fb_adset_id: '1', status: 'ACTIVE', synced_at: ago(1) }, { fb_adset_id: '2', status: 'PAUSED', synced_at: ago(90) }], NOW);
        expect(r.state).toBe('stale');
        expect(r.label).toBe('Synced 1 h ago');
    });
    it('ignores archived/deleted rows a sync can never refresh', () => {
        const r = summarizeSyncFreshness([{ fb_adset_id: '1', status: 'ACTIVE', synced_at: ago(2) }, { fb_adset_id: '2', status: 'ARCHIVED', synced_at: ago(5000) }], NOW);
        expect(r.state).toBe('fresh');
    });
    it('ignores ad sets whose campaign is archived/deleted', () => {
        const r = summarizeSyncFreshness([{ fb_adset_id: '1', status: 'ACTIVE', synced_at: ago(2) }, { fb_adset_id: '2', status: 'PAUSED', campaign_status: 'ARCHIVED', synced_at: null }], NOW);
        expect(r.state).toBe('fresh');
    });
    it('never-synced rows are reported separately and do not pin the badge amber', () => {
        const partial = summarizeSyncFreshness([{ fb_adset_id: '1', status: 'ACTIVE', synced_at: ago(1) }, { fb_adset_id: '2', status: 'PAUSED', synced_at: null }], NOW);
        expect(partial.state).toBe('fresh');
        expect(partial.label).toBe('Synced 1 min ago · 1 not refreshed');
        expect(partial.neverCount).toBe(1);
        const none = summarizeSyncFreshness([{ fb_adset_id: '1', status: 'ACTIVE', synced_at: null }], NOW);
        expect(none.state).toBe('unknown');
    });
    it('still goes stale on old synced rows even with never-synced ones', () => {
        const r = summarizeSyncFreshness([{ fb_adset_id: '1', status: 'ACTIVE', synced_at: ago(120) }, { fb_adset_id: '2', status: 'PAUSED', synced_at: null }], NOW);
        expect(r.state).toBe('stale');
        expect(r.label).toBe('Synced 2 h ago · 1 not refreshed');
    });
});
