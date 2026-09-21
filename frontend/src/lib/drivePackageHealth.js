// Shared by the Drive Package Health page and its tests. Kept out of the page
// component so exporting it does not break React fast refresh.

// An archive folder holds retired creative that was never meant to carry copy
// docs, so flagging it is pure noise: 110 of the 144 packages in this Drive live
// under "Commercial Insurance - LEGACY IMAGES", which buried the 7 that actually
// block a launch.
//
// Matched on a whole path SEGMENT ending in "legacy images"/"archive", never a
// bare "legacy" substring -- live packages called "Barber Shops | Legacy Control
// Relaunch" and "Florist | Legacy Control Relaunch" are healthy and must not be
// hidden. Those end in "Relaunch", so they do not match.
const ARCHIVE_SEGMENT = /(?:^|[\s|-])(?:legacy images|archive|archived)$/i;

export const isArchivedPath = (path) => (path || '')
  .split(' / ')
  .some((segment) => ARCHIVE_SEGMENT.test(segment.trim()));

export const isArchivedPackage = (item) => isArchivedPath(item?.path);
