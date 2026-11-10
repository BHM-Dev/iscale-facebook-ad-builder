import { describe, expect, it } from 'vitest';
import { resolveDriveRelaunch } from './driveRelaunch';

describe('resolveDriveRelaunch', () => {
    it('selects the picker group containing an exact Drive file id', () => {
        const result = resolveDriveRelaunch([
            { id: 'pair:1', assets: [{ drive_file_id: 'feed-1' }, { drive_file_id: 'story-1' }] },
        ], { drive_file_ids: ['story-1'], drive_file_names: ['Concept-IMG-9x16.png'] });

        expect([...result.selectedGroupIds]).toEqual(['pair:1']);
        expect(result.missingFiles).toEqual([]);
    });

    it('deduplicates a pair and reports every missing file by name', () => {
        const result = resolveDriveRelaunch([
            { id: 'pair:1', assets: [{ drive_file_id: 'feed-1' }, { drive_file_id: 'story-1' }] },
        ], {
            drive_file_ids: ['feed-1', 'story-1', 'missing-1'],
            drive_file_names: ['Concept-IMG-1x1.png', 'Concept-IMG-9x16.png', 'Missing.png'],
        });

        expect([...result.selectedGroupIds]).toEqual(['pair:1']);
        expect(result.missingFiles).toEqual(['Missing.png']);
    });
});
