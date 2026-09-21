import { describe, it, expect } from 'vitest';
import { isArchivedPackage, isArchivedPath } from '../lib/drivePackageHealth';

// The archive filter hides 110 of 144 packages, so a regex that is too greedy
// silently hides live work and nobody notices it is missing.
describe('isArchivedPackage', () => {
  it('treats the LEGACY IMAGES archive as archived', () => {
    expect(isArchivedPackage({
      path: 'Commercial Insurance / Commercial Insurance - LEGACY IMAGES / Florist / Final Creatives',
    })).toBe(true);
  });

  it('does NOT archive live packages whose name merely contains "Legacy"', () => {
    // Both of these are healthy handoff-manifest packages in production. A
    // substring match on "legacy" would hide them and lose real work.
    expect(isArchivedPackage({
      path: 'Commercial Insurance / Barber Shops | Legacy Control Relaunch',
    })).toBe(false);
    expect(isArchivedPackage({
      path: 'Commercial Insurance / Florist | Legacy Control Relaunch',
    })).toBe(false);
  });

  it('matches only a whole trailing path segment', () => {
    expect(isArchivedPackage({ path: 'Brand / Archive / Old' })).toBe(true);
    expect(isArchivedPackage({ path: 'Brand / Archived' })).toBe(true);
    expect(isArchivedPackage({ path: 'Brand / Archive Strategy Rollout' })).toBe(false);
    expect(isArchivedPackage({ path: 'Brand / Legacy Images Redux' })).toBe(false);
  });

  it('handles a missing path without throwing', () => {
    expect(isArchivedPackage({})).toBe(false);
  });
});

describe('isArchivedPath', () => {
  it('classifies a bare path the same way as a package object', () => {
    // The collisions section only has paths, no package objects, and it must
    // not disagree with the packages table about what is archive.
    const path = 'Commercial Insurance - LEGACY IMAGES / Roofers';
    expect(isArchivedPath(path)).toBe(true);
    expect(isArchivedPath(path)).toBe(isArchivedPackage({ path }));
    expect(isArchivedPath(undefined)).toBe(false);
  });
});
