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
    it('never-synced rows are called out, not hidden', () => {
        const partial = summarizeSyncFreshness([{ fb_adset_id: '1', status: 'ACTIVE', synced_at: ago(1) }, { fb_adset_id: '2', status: 'PAUSED', synced_at: null }], NOW);
        expect(partial.state).toBe('stale');
        expect(partial.label).toBe('1 of 2 ad sets never synced');
        const none = summarizeSyncFreshness([{ fb_adset_id: '1', status: 'ACTIVE', synced_at: null }], NOW);
        expect(none.state).toBe('unknown');
    });
});
