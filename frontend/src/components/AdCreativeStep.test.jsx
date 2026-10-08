import { describe, expect, it } from 'vitest';
import { drivePackageLabel } from './AdCreativeStep';

describe('drivePackageLabel', () => {
  it('uses the stable Drive package path rather than a placement subfolder', () => {
    expect(drivePackageLabel({
      displayAsset: { folder_path: 'CI-CALLOUT/Talking Head Call-Outs/1x1 Images' },
    })).toBe('CI-CALLOUT / Talking Head Call-Outs');
  });

  it('does not invent a label when the asset has no Drive folder path', () => {
    expect(drivePackageLabel({ displayAsset: { folder_path: '' } })).toBeNull();
  });
});
