import { describe, it, expect } from 'vitest';
import { isMetaObjectGone, isHardBlockError, deliveryState, formatCheckedAge, scheduledStartDate, formatScheduledStart } from './liveStatus';

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

describe('scheduled starts', () => {
    const NOW = new Date('2026-10-25T20:00:00Z').getTime();
    it('only a future start time counts as scheduled', () => {
        expect(scheduledStartDate('2026-10-26T07:00:00Z', NOW)?.toISOString()).toBe('2026-10-26T07:00:00.000Z');
        expect(scheduledStartDate('2026-10-25T19:59:00Z', NOW)).toBeNull();   // already passed
        expect(scheduledStartDate(new Date(NOW), NOW)).toBeNull();            // exactly now is not "scheduled"
        expect(scheduledStartDate('', NOW)).toBeNull();
        expect(scheduledStartDate(null, NOW)).toBeNull();
        expect(scheduledStartDate('not a date', NOW)).toBeNull();
        // Meta's offset format has no colon — must still parse (and keep the exact instant)
        expect(scheduledStartDate('2026-10-26T00:00:00-0700', NOW)?.toISOString()).toBe('2026-10-26T07:00:00.000Z');
        expect(scheduledStartDate('2026-10-26T00:00:00+0000', NOW)?.toISOString()).toBe('2026-10-26T00:00:00.000Z');
        expect(scheduledStartDate('2026-10-25T00:00:00-0700', NOW)).toBeNull();   // already passed, still parsed correctly
        // datetime-local (no offset) is unchanged and read in the browser's timezone
        expect(scheduledStartDate('2099-01-01T00:00', NOW)).not.toBeNull();
    });
    it('shows the instant Meta will receive in Pacific time', () => {
        const PT = 'America/Los_Angeles';
        expect(formatScheduledStart(new Date('2026-10-26T07:00:00Z'), PT)).toBe('Mon, Oct 26, 12:00 AM PT');   // PDT
        expect(formatScheduledStart(new Date('2026-11-03T08:00:00Z'), PT)).toBe('Tue, Nov 3, 12:00 AM PT');    // PST after the Nov 1 change
    });
    it('appends the local time only when the browser is not in Pacific time', () => {
        // typed "12:00 AM" in an Eastern browser = 04:00Z = 9:00 PM the previous evening in PT — the mismatch must show
        expect(formatScheduledStart(new Date('2026-10-26T04:00:00Z'), 'America/New_York')).toBe('Sun, Oct 25, 9:00 PM PT (Mon, 12:00 AM EDT your time)');
        expect(formatScheduledStart(new Date('2026-10-26T07:00:00Z'), 'America/Los_Angeles')).toBe('Mon, Oct 26, 12:00 AM PT');
        expect(formatScheduledStart(new Date('2026-10-26T07:00:00Z'), '')).toBe('Mon, Oct 26, 12:00 AM PT');
    });
    it('LIVE becomes SCHEDULED only when everything is ACTIVE and a start is pending', () => {
        const active = { status: 'ACTIVE', effectiveStatus: 'ACTIVE' };
        const future = new Date(NOW + 3600000);
        expect(deliveryState({ campaign: active, adset: active, scheduledStart: future })).toBe('SCHEDULED');
        expect(deliveryState({ campaign: active, scheduledStart: future })).toBe('SCHEDULED');
        expect(deliveryState({ campaign: active, adset: active, scheduledStart: null })).toBe('LIVE');
    });
    it('a pending start never softens a paused, blocked, unknown or unverified state', () => {
        const future = new Date(NOW + 3600000);
        expect(deliveryState({ campaign: { status: 'PAUSED' }, adset: { status: 'ACTIVE' }, scheduledStart: future })).toBe('PAUSED');
        expect(deliveryState({ campaign: { status: 'ACTIVE', effectiveStatus: 'WITH_ISSUES' }, scheduledStart: future })).toBe('unknown');
        expect(deliveryState({ campaign: { status: 'ACTIVE' }, adset: { status: 'IN_PROCESS' }, scheduledStart: future })).toBe('unknown');
        expect(deliveryState({ campaign: { status: 'ACTIVE' }, unverified: true, scheduledStart: future })).toBe('unverified');
    });
});
