import { describe, it, expect } from 'vitest';
import { sweepPendingHandoffs, stampPendingWrite, installPendingTimestamps, PENDING_TTL_MS } from './pendingHandoffs';

function mem(initial = {}) {
  const m = new Map(Object.entries(initial));
  return {
    get length() { return m.size; },
    key: (i) => [...m.keys()][i] ?? null,
    getItem: (k) => (m.has(k) ? m.get(k) : null),
    setItem: (k, v) => m.set(k, String(v)),
    removeItem: (k) => m.delete(k),
    _m: m,
  };
}

describe('sweepPendingHandoffs', () => {
  it('keeps a fresh handoff and records when it was first seen', () => {
    const s = mem({ pendingQuickAd: '{}', overlayLogoUrl: 'x' });
    expect(sweepPendingHandoffs(s, 1000)).toEqual([]);
    expect(s.getItem('pendingQuickAd')).toBe('{}');
    expect(JSON.parse(s.getItem('pendingHandoffsSeenAt'))).toEqual({ pendingQuickAd: 1000 });
  });

  it('removes a handoff seen longer than the TTL ago, leaves non-pending keys', () => {
    const s = mem({ pendingQuickAd: '{}', overlayLogoUrl: 'x' });
    sweepPendingHandoffs(s, 1000);
    expect(sweepPendingHandoffs(s, 1000 + PENDING_TTL_MS + 1)).toEqual(['pendingQuickAd']);
    expect(s.getItem('pendingQuickAd')).toBeNull();
    expect(s.getItem('overlayLogoUrl')).toBe('x');
    expect(s.getItem('pendingHandoffsSeenAt')).toBeNull();
  });

  it('prunes the stamp of a key the reader already consumed', () => {
    const s = mem({ pendingQuickAd: '{}' });
    sweepPendingHandoffs(s, 1000);
    s.removeItem('pendingQuickAd'); // reader consumed it
    sweepPendingHandoffs(s, 2000);
    expect(s.getItem('pendingHandoffsSeenAt')).toBeNull();
  });

  it('never expires the Meta-link retry queue', () => {
    const s = mem({ pendingGeneratedAdMetaLinks: '[{"generatedAdId":"g1"}]' });
    stampPendingWrite(s, 'pendingGeneratedAdMetaLinks', 1000);
    expect(s.getItem('pendingHandoffsSeenAt')).toBeNull();
    expect(sweepPendingHandoffs(s, 1000 + 10 * PENDING_TTL_MS)).toEqual([]);
    expect(s.getItem('pendingGeneratedAdMetaLinks')).toBe('[{"generatedAdId":"g1"}]');
  });

  it('never throws when storage is unavailable', () => {
    const broken = { get length() { throw new Error('blocked'); } };
    expect(sweepPendingHandoffs(broken, 0)).toEqual([]);
  });
});

describe('write-time stamps', () => {
  it('a handoff written and never read expires on a later load, even if no sweep saw it', () => {
    const s = mem();
    s.setItem('pendingRemixCreative', '{}');
    stampPendingWrite(s, 'pendingRemixCreative', 1000);       // written mid-session
    // next day: first sweep ever to see it must already remove it
    expect(sweepPendingHandoffs(s, 1000 + PENDING_TTL_MS + 1)).toEqual(['pendingRemixCreative']);
  });

  it('installPendingTimestamps stamps pending* writes and leaves others alone', () => {
    class FakeStorage {
      constructor() { this.m = new Map(); }
      getItem(k) { return this.m.has(k) ? this.m.get(k) : null; }
      setItem(k, v) { this.m.set(k, String(v)); }
    }
    installPendingTimestamps(FakeStorage.prototype);
    const st = new FakeStorage();
    st.setItem('overlayLogoUrl', 'x');
    expect(st.getItem('pendingHandoffsSeenAt')).toBeNull();
    st.setItem('pendingQuickAd', '{}');
    expect(st.getItem('pendingQuickAd')).toBe('{}');
    expect(Object.keys(JSON.parse(st.getItem('pendingHandoffsSeenAt')))).toEqual(['pendingQuickAd']);
  });
});
