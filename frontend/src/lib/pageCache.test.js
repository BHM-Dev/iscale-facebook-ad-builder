import { describe, it, expect, beforeEach } from 'vitest';
import { readPageCache, writePageCache, minutesAgo } from './pageCache';

describe('pageCache', () => {
    beforeEach(() => sessionStorage.clear());

    it('returns what was written, until it is 30 minutes old', () => {
        writePageCache('k1', { a: 1 }, 1_000);
        expect(readPageCache('k1', 1_000 + 60_000).data).toEqual({ a: 1 });
        expect(readPageCache('k1', 1_000 + 31 * 60_000)).toBeNull();
    });

    it('survives a reload via sessionStorage and ignores junk', () => {
        sessionStorage.setItem('pageCache:k2', JSON.stringify({ at: 5_000, data: { b: 2 } }));
        expect(readPageCache('k2', 6_000).data).toEqual({ b: 2 });
        sessionStorage.setItem('pageCache:k3', '{not json');
        expect(readPageCache('k3', 6_000)).toBeNull();
    });

    it('formats the age plainly', () => {
        expect(minutesAgo(0, 20_000)).toBe('less than a minute ago');
        expect(minutesAgo(0, 4 * 60_000)).toBe('4 min ago');
    });
});
