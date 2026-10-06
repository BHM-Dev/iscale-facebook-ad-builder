import { describe, it, expect } from 'vitest';
import { isMetaObjectGone, isHardBlockError, deliveryState, formatCheckedAge } from './liveStatus';

describe('isMetaObjectGone', () => {
    it('flags ARCHIVED/DELETED in status or effective_status', () => {
        expect(isMetaObjectGone({ status: 'ARCHIVED' })).toBe(true);
        expect(isMetaObjectGone({ status: 'PAUSED', effective_status: 'DELETED' })).toBe(true);
    });
    it('does not flag normal or missing objects', () => {
        expect(isMetaObjectGone({ status: 'ACTIVE', effective_status: 'ACTIVE' })).toBe(false);
        expect(isMetaObjectGone(null)).toBe(false);
    });
});

describe('isHardBlockError', () => {
    it('blocks only 404 with Meta code 100', () => {
        expect(isHardBlockError({ httpStatus: 404, metaErrorCode: 100 })).toBe(true);
        expect(isHardBlockError({ httpStatus: 404 })).toBe(false);
        expect(isHardBlockError({ httpStatus: 429, metaErrorCode: 17 })).toBe(false);
        expect(isHardBlockError({ httpStatus: 504 })).toBe(false);
    });
});

describe('deliveryState', () => {
    const on = { status: 'ACTIVE', effectiveStatus: 'ACTIVE' };
    const off = { status: 'PAUSED', effectiveStatus: 'PAUSED' };
    it('LIVE only when everything is ACTIVE', () => {
        expect(deliveryState({ campaign: on })).toBe('LIVE');
        expect(deliveryState({ campaign: on, adset: on })).toBe('LIVE');
    });
    it('PAUSED when any known parent is paused', () => {
        expect(deliveryState({ campaign: on, adset: off })).toBe('PAUSED');
        expect(deliveryState({ campaign: off })).toBe('PAUSED');
    });
    it('never claims LIVE/PAUSED for unclear states', () => {
        expect(deliveryState({ campaign: { status: 'ACTIVE', effectiveStatus: 'WITH_ISSUES' } })).toBe('unknown');
        expect(deliveryState({ campaign: { status: 'ACTIVE', effectiveStatus: 'CAMPAIGN_PAUSED' }, adset: on })).toBe('unknown');
        expect(deliveryState({ campaign: { status: '' } })).toBe('unknown');
        expect(deliveryState({ campaign: on, adset: { status: 'ARCHIVED' } })).toBe('unknown');
    });
    it('unverified wins', () => {
        expect(deliveryState({ campaign: on, unverified: true })).toBe('unverified');
    });
});

describe('formatCheckedAge', () => {
    it('ticks with the supplied clock', () => {
        const t = '2026-10-06T18:00:00.000Z';
        const base = new Date(t).getTime();
        expect(formatCheckedAge(t, base + 10_000)).toMatch(/just now/);
        expect(formatCheckedAge(t, base + 3 * 60_000)).toMatch(/3 min ago/);
    });
});
