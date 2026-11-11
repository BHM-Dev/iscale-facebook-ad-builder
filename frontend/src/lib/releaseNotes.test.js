import { describe, expect, it } from 'vitest';
import { LATEST_RELEASE_ID, RELEASE_NOTES, notesToShow } from './releaseNotes';

describe('release notes', () => {
    it('ids are unique and the latest is the max', () => {
        const ids = RELEASE_NOTES.map(note => note.id);
        expect(new Set(ids).size).toBe(ids.length);
        expect(LATEST_RELEASE_ID).toBe(Math.max(...ids));
    });
    it('shows nothing when the user has seen the latest', () => {
        expect(notesToShow(LATEST_RELEASE_ID)).toEqual([]);
    });
    it('shows only notes newer than what was seen', () => {
        expect(notesToShow(LATEST_RELEASE_ID - 1).map(n => n.id)).toEqual([LATEST_RELEASE_ID]);
    });
    it('first visit shows only the last two weeks', () => {
        const ids = notesToShow(null, new Date('2026-11-20T12:00:00Z')).map(n => n.id);
        expect(ids).toEqual(RELEASE_NOTES.filter(n => n.date >= '2026-11-06').map(n => n.id));
    });
});
