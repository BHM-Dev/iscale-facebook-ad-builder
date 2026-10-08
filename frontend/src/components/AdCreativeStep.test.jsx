import { describe, expect, it } from 'vitest';
import { drivePackageLabel, drivePackagePath } from './AdCreativeStep';

describe('drivePackageLabel', () => {
  it('uses the stable Drive package path rather than a placement subfolder', () => {
    const group = {
      displayAsset: { folder_path: 'CI-CALLOUT/Talking Head Call-Outs/1x1 Images' },
    };
    expect(drivePackagePath(group)).toBe('CI-CALLOUT / Talking Head Call-Outs');
    expect(drivePackageLabel(group)).toBe('Talking Head Call-Outs');
  });

  it('removes real-world placement folder names from the saved package path', () => {
    const group = {
      displayAsset: { folder_path: 'Commercial Van Insurance/01 - Painting Contractors/9x16 Stories and Reels Images' },
    };
    expect(drivePackagePath(group)).toBe('Commercial Van Insurance / 01 - Painting Contractors');
    expect(drivePackageLabel(group)).toBe('01 - Painting Contractors');
  });

  it('does not invent a label when the asset has no Drive folder path', () => {
    expect(drivePackageLabel({ displayAsset: { folder_path: '' } })).toBeNull();
  });
});
