import React, { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, CheckCircle2, Copy, FolderSearch, RefreshCw } from 'lucide-react';
import { authFetch } from '../lib/facebookApi';
import { useToast } from '../context/ToastContext';
import { isArchivedPackage, isArchivedPath } from '../lib/drivePackageHealth';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1';

const driveFolderUrl = (folderId) => `https://drive.google.com/drive/folders/${folderId}`;


// Measured against the live Drive: 144 packages, 132 with no copy source and 111
// flat, but only 7 with a filename problem. Treating all of them as "needs
// attention" produces a wall of amber that buries the handful that actually
// cause a launch refusal -- and a report that cries wolf gets opened once.
// A filename clash only bites when the package has no copy source of its own.
const BLOCKING_ISSUES = new Set(['duplicate_basename_within_package', 'duplicate_basename_across_packages']);
const hasCopySource = (item) => item.copy_source && item.copy_source !== 'none';
// The copy-source exemption applies ONLY to the cross-package clash: a package
// with its own manifest resolves locally and never borrows a sibling's entry.
// A duplicate INSIDE one package is refused either way -- the name maps to a
// single Drive file id, so the second copy of it loses regardless of manifest.
const isBlockingIssue = (issue, item) => (
  issue === 'duplicate_basename_within_package'
    ? true
    : issue === 'duplicate_basename_across_packages' && !hasCopySource(item)
);
const blockingIssues = (item) => (item.issues || []).filter((issue) => isBlockingIssue(issue, item));
const willRefuse = (item) => blockingIssues(item).length > 0;

// Label plus the consequence and the fix. "No copy source" on its own told the
// reader nothing they could act on, and nobody outside the sync code knows what
// a "flat package" is or whether it will hurt them.
const ISSUE_INFO = {
  no_copy_source: {
    label: 'No copy source',
    severity: 'low',
    detail: 'No handoff manifest or recognized copy doc in this folder, so its creatives get no ad copy. Ask creative to add a handoff manifest here.',
  },
  flat_package: {
    label: 'Flat package',
    severity: 'medium',
    detail: 'Images sit directly in the package folder with no 1x1 / 9x16 subfolders and no manifest, so copy cannot be matched reliably. Add a manifest, or move the images into placement subfolders.',
  },
  duplicate_basename_across_packages: {
    label: 'Shared filename',
    severity: 'medium',
    detail: 'A filename here is also used in another package under this brand. Harmless while this package has its own copy source; it causes a launch refusal when it does not.',
  },
  duplicate_basename_within_package: {
    label: 'Duplicate filename',
    severity: 'medium',
    detail: 'The same filename appears twice inside this package. Only one of them can be matched to copy; the other is refused at launch. Rename one and update the copy doc entry.',
  },
};

function IssueChip({ issue, blocking = false }) {
  const info = ISSUE_INFO[issue];
  const high = blocking || info?.severity === 'high';
  return (
    <span
      title={info?.detail || undefined}
      className={`inline-flex rounded-full border px-2 py-0.5 text-xs font-medium ${
        high ? 'border-red-200 bg-red-50 text-red-800' : 'border-amber-200 bg-amber-50 text-amber-800'
      }`}
    >
      {info?.label || issue}
    </span>
  );
}

export default function DrivePackageHealth() {
  const { showError, showInfo, showSuccess, showWarning } = useToast();
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(true);
  // Tracked separately from `report`. Clearing the report on failure made a
  // failed inspection render as "0 of 0 packages need attention" plus a green
  // "Everything is clean" -- byte-identical to a healthy Drive, with only a
  // 5-second toast to say otherwise. On a page whose whole job is to report
  // problems, "it didn't run" must never look like "nothing is wrong".
  const [error, setError] = useState(null);
  const [rebuilding, setRebuilding] = useState(false);
  const [onlyIssues, setOnlyIssues] = useState(false);
  const [showArchive, setShowArchive] = useState(false);
  const [manifestText, setManifestText] = useState('');
  const [manifestFolderId, setManifestFolderId] = useState('');
  const [manifestResult, setManifestResult] = useState(null);
  const [validatingManifest, setValidatingManifest] = useState(false);

  const loadReport = async ({ silent = false } = {}) => {
    if (!silent) setLoading(true);
    setError(null);
    try {
      const response = await authFetch(`${API_URL}/drive/package-health`);
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || 'Could not inspect Drive package health');
      setReport(data);
      setRebuilding(Boolean(data.rebuilding));
    } catch (err) {
      const message = err.message || 'Could not inspect Drive package health';
      setError(message);
      showError(message);
    } finally {
      if (!silent) setLoading(false);
    }
  };

  // The build takes minutes, so Refresh starts it and we poll the snapshot
  // instead of holding a request open.
  const startRebuild = async () => {
    setError(null);
    try {
      const response = await authFetch(`${API_URL}/drive/package-health/refresh`, { method: 'POST' });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || 'Could not start the Drive inspection');
      setRebuilding(true);
      showInfo('Inspecting Drive. This takes a few minutes — the page updates itself when it finishes.');
    } catch (err) {
      const message = err.message || 'Could not start the Drive inspection';
      setError(message);
      showError(message);
    }
  };

  const validateManifest = async () => {
    if (!manifestText.trim()) {
      showWarning('Paste your copy file first.');
      return;
    }
    setValidatingManifest(true);
    try {
      const response = await authFetch(`${API_URL}/drive-assets/validate-manifest`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          text: manifestText,
          ...(manifestFolderId.trim() ? { folder_id: manifestFolderId.trim() } : {}),
        }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || 'Could not check this copy file');
      setManifestResult(data);
      if (!data.ok) showWarning('This copy file is not ready yet. Fix the items listed, then check it again.');
      else showSuccess(data.warnings?.length ? 'Ready to save to Drive (with a few notes).' : 'Ready to save to Drive.');
    } catch (err) {
      showError(err.message || 'Could not check this copy file');
    } finally {
      setValidatingManifest(false);
    }
  };

  useEffect(() => {
    loadReport();
  }, []);

  useEffect(() => {
    if (!rebuilding) return undefined;
    const timer = setInterval(() => loadReport({ silent: true }), 15000);
    return () => clearInterval(timer);
  }, [rebuilding]);

  // Every count on this page is over live packages only. Including the archive
  // made the headline read "133 of 144 need attention" when the real number of
  // folders anyone has to touch is a fraction of that.
  const livePackages = useMemo(
    () => (report?.packages || []).filter((item) => !isArchivedPackage(item)),
    [report],
  );
  const archivedPackages = useMemo(
    () => (report?.packages || []).filter(isArchivedPackage),
    [report],
  );
  const packages = useMemo(() => {
    const all = showArchive ? (report?.packages || []) : livePackages;
    const filtered = onlyIssues ? all.filter(willRefuse) : all;
    // Refusals first: they are the only rows anyone has to act on today.
    return [...filtered].sort((a, b) => (willRefuse(b) ? 1 : 0) - (willRefuse(a) ? 1 : 0));
  }, [report, livePackages, onlyIssues, showArchive]);
  // Counted over whatever set the table is showing. Pinning these to
  // livePackages left the headline claiming "7 of 34" while 144 rows rendered
  // below it -- and with "only refused" also on, the visible row count WAS the
  // honest blocking number and did not match the sentence above it.
  const counted = showArchive ? (report?.packages || []) : livePackages;
  const issueCount = counted.filter((item) => item.issues?.length).length;
  const blockingCount = counted.filter(willRefuse).length;
  const archivedIssueCount = archivedPackages.filter((item) => item.issues?.length).length;

  return (
    <div className="mx-auto max-w-7xl space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-gray-900 text-white"><FolderSearch size={22} /></div>
            <div>
              <h1 className="text-3xl font-bold tracking-tight text-gray-900">Drive Package Health</h1>
              <p className="mt-1 text-sm text-gray-600">Find ambiguous source packages before they reach the ad launcher.</p>
            </div>
          </div>
          <p className="mt-3 text-xs text-gray-400">
            {report?.generated_at
              ? `Inspected ${new Date(report.generated_at).toLocaleString()} · rebuilt hourly`
              : 'Not inspected yet · rebuilt hourly'}
            {rebuilding ? ' · inspecting now…' : ''}
          </p>
          {report?.drive_media_total !== undefined && (
            <div className="mt-2 text-sm">
              <p className={`font-medium ${report.missing_total > 0 || report.stale ? 'text-amber-700' : 'text-gray-600'}`}>
                In Drive: {(report.drive_media_total ?? 0).toLocaleString()} files · In the picker: {(report.library_media_total ?? 0).toLocaleString()}
                {report.age_seconds != null ? ` · checked ${Math.max(0, Math.floor(report.age_seconds / 60))} min ago` : ''}
                {report.stale ? ' · this check is overdue, so numbers may be out of date' : ''}
              </p>
              {report.missing_total > 0 && (
                <div className="mt-1 text-amber-800">
                  <p>{report.missing_total.toLocaleString()} file{report.missing_total === 1 ? ' is' : 's are'} in Drive but not in the picker yet. New uploads usually appear within an hour; if a package is still listed here after the next check, tell Steve.</p>
                  {report.missing_packages?.length > 0 && (
                    <ul className="mt-1 list-disc space-y-0.5 pl-5 text-xs">
                      {report.missing_packages.map((pkg) => (
                        <li key={pkg.folder_id}>{pkg.path} — {pkg.missing_count} of {pkg.media_count} not in the picker</li>
                      ))}
                    </ul>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
        <button
          type="button"
          onClick={startRebuild}
          disabled={loading || rebuilding}
          className="inline-flex items-center gap-2 rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm font-semibold text-gray-700 shadow-sm hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-60"
        >
          <RefreshCw size={16} className={loading || rebuilding ? 'animate-spin' : ''} /> {rebuilding ? 'Inspecting…' : 'Re-inspect Drive'}
        </button>
      </div>

      {!error && report?.status === 'ready' && (report.stale || report.last_error) && (
        <div className="rounded-xl border border-amber-300 bg-amber-50 px-4 py-3 shadow-sm">
          <div className="flex items-start gap-2">
            <AlertTriangle size={18} className="mt-0.5 shrink-0 text-amber-600" />
            <div className="min-w-0">
              <p className="text-sm font-semibold text-amber-900">
                {report.last_error ? 'The last inspection failed' : 'This report is out of date'}
              </p>
              <p className="mt-0.5 text-sm text-amber-800">
                {report.last_error
                  ? `Showing the previous result from ${new Date(report.generated_at).toLocaleString()}. Drive may have changed since. Error: ${report.last_error}`
                  : `Last successful inspection was ${new Date(report.generated_at).toLocaleString()}. Rebuilds run hourly, so this suggests they are failing.`}
              </p>
            </div>
          </div>
        </div>
      )}
      {error ? (
        <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 shadow-sm">
          <div className="flex items-start gap-2">
            <AlertTriangle size={18} className="mt-0.5 shrink-0 text-red-600" />
            <div className="min-w-0">
              <p className="text-sm font-semibold text-red-900">Drive inspection did not run</p>
              <p className="mt-0.5 text-sm text-red-800">{error}</p>
              <p className="mt-1 text-xs text-red-700">This is not an all-clear — nothing was checked. Fix the Drive connection and try again.</p>
              <button
                type="button"
                onClick={() => loadReport()}
                disabled={loading}
                className="mt-2 inline-flex items-center gap-2 rounded-lg border border-red-300 bg-white px-3 py-1.5 text-xs font-semibold text-red-800 hover:bg-red-100 disabled:opacity-60"
              >
                <RefreshCw size={14} className={loading ? 'animate-spin' : ''} /> Try again
              </button>
            </div>
          </div>
        </div>
      ) : (
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-gray-200 bg-white px-4 py-3 shadow-sm">
        <div className="flex items-center gap-2 text-sm text-gray-700">
          {blockingCount ? <AlertTriangle size={18} className="text-red-600" /> : <CheckCircle2 size={18} className="text-emerald-600" />}
          <span>
            <strong>{blockingCount}</strong> of <strong>{counted.length}</strong> {showArchive ? 'packages' : 'active packages'} will be refused at launch.
            {issueCount > blockingCount && (
              <span className="text-gray-500"> · {issueCount - blockingCount} more have a structural finding that does not block launch.</span>
            )}
            {!showArchive && archivedPackages.length > 0 && (
              <span className="text-gray-400">
                {' '}Excludes {archivedPackages.length} archive folders
                {archivedIssueCount > 0 ? ` (${archivedIssueCount} with findings)` : ''}, which are not expected to carry copy docs.
              </span>
            )}
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-4">
          {archivedPackages.length > 0 && (
            <button
              type="button"
              onClick={() => setShowArchive((current) => !current)}
              aria-pressed={showArchive}
              className={`rounded-lg border px-3 py-1 text-xs font-semibold transition-colors ${
                showArchive ? 'border-gray-400 bg-gray-100 text-gray-800' : 'border-gray-300 text-gray-600 hover:bg-gray-50'
              }`}
            >
              {showArchive
                ? `Hide archive (${archivedPackages.length})`
                : `Show ${archivedPackages.length} archive folders`}
            </button>
          )}
          <label className="flex cursor-pointer items-center gap-2 text-sm font-medium text-gray-700">
            <input type="checkbox" checked={onlyIssues} onChange={(event) => setOnlyIssues(event.target.checked)} className="h-4 w-4 rounded border-gray-300 text-gray-900 focus:ring-gray-500" />
            Only packages that will be refused
          </label>
        </div>
      </div>
      )}

      <section className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="font-semibold text-gray-900">Check a copy file</h2>
            <p className="mt-1 max-w-2xl text-sm text-gray-600">Paste your copy file (the one ending in HANDOFF-MANIFEST.txt) before saving it to Drive. This tells you what to fix so the ads import with the right copy. Nothing is saved by checking.</p>
          </div>
          <button
            type="button"
            onClick={validateManifest}
            disabled={validatingManifest || !manifestText.trim()}
            className="inline-flex items-center gap-2 rounded-lg bg-gray-900 px-3 py-2 text-sm font-semibold text-white hover:bg-gray-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {validatingManifest ? <RefreshCw size={16} className="animate-spin" /> : <CheckCircle2 size={16} />}
            {validatingManifest ? 'Checking…' : 'Check copy file'}
          </button>
          {!manifestText.trim() && <p className="w-full text-xs text-gray-500 sm:w-auto sm:self-end">Paste your file below to enable the check.</p>}
        </div>
        <textarea
          value={manifestText}
          onChange={(event) => { setManifestText(event.target.value); setManifestResult(null); }}
          placeholder={'PACKAGE: Vertical | Package name\nFINAL HANDOFF MANIFEST — LAUNCHER COPY MAP\n\nMeta Button\nGet Quote\n\n## PKG-01-IMG\n...'}
          rows={12}
          className="mt-4 w-full rounded-lg border border-gray-300 px-3 py-2 font-mono text-xs text-gray-800 shadow-inner focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-100"
        />
        <label className="mt-3 block max-w-md text-xs font-semibold text-gray-600">
          Drive folder link (optional)
          <input
            value={manifestFolderId}
            onChange={(event) => { setManifestFolderId(event.target.value); setManifestResult(null); }}
            placeholder="Paste the package folder's link to also check the filenames"
            className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm font-normal text-gray-800 focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-100"
          />
        </label>
        {manifestResult && (
          <div className="mt-4 rounded-lg border border-gray-200 bg-gray-50 p-4">
            <div className={`rounded-lg px-4 py-3 text-base font-semibold ${manifestResult.ok ? 'bg-emerald-100 text-emerald-900' : 'bg-red-100 text-red-900'}`}>
              {manifestResult.ok
                ? (manifestResult.warnings?.length
                    ? `Ready to save to Drive — ${manifestResult.warnings.length} note${manifestResult.warnings.length === 1 ? '' : 's'} below`
                    : 'Ready to save to Drive')
                : `Not ready — ${manifestResult.errors.length} thing${manifestResult.errors.length === 1 ? '' : 's'} to fix`}
              {manifestResult.package && <span className="ml-2 text-sm font-normal opacity-80">{manifestResult.package}</span>}
            </div>
            {manifestResult.errors?.length > 0 && (
              <div className="mt-3">
                <p className="text-xs font-semibold uppercase tracking-wide text-red-700">Fix these</p>
                <ul className="mt-1 list-disc space-y-1 pl-5 text-sm text-red-800">{manifestResult.errors.map((item) => <li key={item}>{item}</li>)}</ul>
              </div>
            )}
            {manifestResult.warnings?.length > 0 && (
              <div className="mt-3">
                <p className="text-xs font-semibold uppercase tracking-wide text-amber-700">Worth a look (won't stop it importing)</p>
                <ul className="mt-1 list-disc space-y-1 pl-5 text-sm text-amber-800">{manifestResult.warnings.map((item) => <li key={item}>{item}</li>)}</ul>
              </div>
            )}
            {manifestResult.entries && Object.keys(manifestResult.entries).length > 0 && (
              <div className="mt-4 overflow-x-auto">
                <p className="text-xs font-semibold uppercase tracking-wide text-gray-600">Ads we found</p>
                <table className="mt-1 w-full min-w-[540px] text-left text-xs">
                  <thead className="text-gray-500"><tr><th className="py-1 pr-3">Ad</th><th className="py-1 pr-3">Headline</th><th className="py-1">Placements</th></tr></thead>
                  <tbody className="divide-y divide-gray-200">{Object.values(manifestResult.entries).map((entry) => (
                    <tr key={entry.copy_id} className="align-top"><td className="py-2 pr-3 font-mono text-gray-700">{entry.copy_id}</td><td className="py-2 pr-3 text-gray-700">{entry.headline || '—'}</td><td className="py-2 text-gray-600">{(entry.placements || []).map((placement) => `${placement.aspect} ${placement.media_type}`).join(' · ') || '—'}</td></tr>
                  ))}</tbody>
                </table>
              </div>
            )}
          </div>
        )}
      </section>

      <section className="overflow-hidden rounded-xl border border-gray-200 bg-white shadow-sm">
        <div className="border-b border-gray-200 px-5 py-4"><h2 className="font-semibold text-gray-900">Packages</h2></div>
        {loading ? (
          <div className="p-10 text-center text-sm text-gray-500">Loading the latest inspection…</div>
        ) : error && !report ? (
          <div className="p-10 text-center">
            <AlertTriangle className="mx-auto mb-3 text-red-600" size={28} />
            <p className="font-medium text-gray-900">Inspection unavailable</p>
            <p className="mt-1 text-sm text-gray-500">Nothing was checked, so this is not an all-clear.</p>
          </div>
        ) : report?.status === 'pending' ? (
          <div className="p-10 text-center">
            <FolderSearch className="mx-auto mb-3 text-gray-400" size={28} />
            <p className="font-medium text-gray-900">No inspection yet</p>
            <p className="mt-1 text-sm text-gray-500">Nothing has been checked, so this is not an all-clear. Run one with Re-inspect Drive, or wait for the hourly rebuild.</p>
          </div>
        ) : packages.length === 0 ? (
          <div className="p-10 text-center">
            <CheckCircle2 className="mx-auto mb-3 text-emerald-600" size={28} />
            <p className="font-medium text-gray-900">
              {!showArchive && archivedPackages.length > 0 ? 'Nothing active will be refused at launch' : 'Nothing will be refused at launch'}
            </p>
            <p className="mt-1 text-sm text-gray-500">No packages match this filter.</p>
            {!showArchive && archivedPackages.length > 0 && (
              // Said after the all-clear, never instead of it: the claim above
              // is scoped to live packages and the reader has to know that.
              <p className="mt-1 text-sm text-gray-500">{archivedPackages.length} archive folders are hidden and were not counted.</p>
            )}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] text-left text-sm">
              <thead className="bg-gray-50 text-xs font-semibold uppercase tracking-wide text-gray-500"><tr><th className="px-5 py-3">Package</th><th className="px-4 py-3 text-right">Media</th><th className="px-4 py-3">Copy source</th><th className="px-5 py-3">Issues</th></tr></thead>
              <tbody className="divide-y divide-gray-100">
                {packages.map((item) => <tr key={item.folder_id} className="align-top hover:bg-gray-50">
                  <td className="max-w-md break-words px-5 py-4 font-medium text-gray-900">
                    {isArchivedPackage(item) && (
                      <span className="mr-2 rounded bg-gray-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-gray-500">Archive</span>
                    )}
                    {/* folder_id is already in the payload -- naming a problem and then
                        making someone hunt for the folder by hand is how a report
                        gets opened once. */}
                    <a href={driveFolderUrl(item.folder_id)} target="_blank" rel="noopener noreferrer" className="text-indigo-700 hover:text-indigo-900 hover:underline">
                      {item.path}
                    </a>
                  </td>
                  <td className="px-4 py-4 text-right tabular-nums text-gray-700">{item.media_count}</td>
                  <td className="px-4 py-4 text-gray-700">
                    <div>{item.copy_source.replace(/_/g, ' ')}</div>
                    {item.manifest_status && (
                      <div className={`mt-1 text-xs font-medium ${item.manifest_status === 'error' ? 'text-red-700' : item.manifest_status === 'warn' ? 'text-amber-700' : 'text-emerald-700'}`}>
                        Copy file: {item.manifest_status === 'error' ? 'has problems' : item.manifest_status === 'warn' ? 'has notes' : 'looks good'}
                      </div>
                    )}
                    {item.manifest_messages?.length > 0 && (
                      <ul className="mt-1 list-disc space-y-0.5 pl-4 text-xs text-gray-600">
                        {item.manifest_messages.slice(0, 5).map((entry) => <li key={entry.message} className={entry.severity === 'error' ? 'text-red-700' : 'text-amber-700'}>{entry.message}</li>)}
                        {item.manifest_messages.length > 5 && <li>…and {item.manifest_messages.length - 5} more (paste the file into "Check a copy file" to see all)</li>}
                      </ul>
                    )}
                  </td>
                  <td className="px-5 py-4">
                    <div className="flex max-w-sm flex-wrap items-center gap-1.5">
                      {willRefuse(item) && (
                        <span className="inline-flex rounded-full bg-red-600 px-2 py-0.5 text-xs font-semibold text-white">Refused at launch</span>
                      )}
                      {item.issues?.length
                        ? item.issues.map((issue) => <IssueChip key={issue} issue={issue} blocking={isBlockingIssue(issue, item)} />)
                        : <span className="text-emerald-700">Healthy</span>}
                    </div>
                  </td>
                </tr>)}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {report?.collisions?.length > 0 && <section className="overflow-hidden rounded-xl border border-gray-200 bg-white shadow-sm">
        <div className="flex items-center gap-2 border-b border-gray-200 px-5 py-4"><Copy size={17} className="text-gray-500" /><div><h2 className="font-semibold text-gray-900">Cross-package filename collisions</h2><p className="text-xs text-gray-500">These names are reused under the same brand and need package-level copy context. Computed across every folder, archive included — so a live package can appear here because of an archived twin.</p></div></div>
        <div className="divide-y divide-gray-100">{report.collisions.map((collision, index) => (
          // Key includes the index: the same basename can collide under two
          // different brands, producing two entries with the same basename.
          <div key={`${collision.basename}-${index}`} className="grid gap-2 px-5 py-4 sm:grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)]">
            <div className="break-all font-mono text-xs text-gray-800">
              {collision.basename}
              <span className="ml-2 font-sans text-[11px] text-gray-500">in {collision.packages.length} packages</span>
            </div>
            <div className="min-w-0 break-words text-sm text-gray-600">
              {(collision.package_folders || collision.packages.map((path) => ({ path, folder_id: null }))).map((entry, entryIndex) => (
                <span key={entry.folder_id || `${entry.path}-${entryIndex}`}>
                  {entryIndex > 0 && ' · '}
                  {/* Badged here too: the packages table can be hiding these
                      rows, and an unlabelled archive path in a section the
                      reader thinks is scoped to live folders is misleading. */}
                  {isArchivedPath(entry.path) && (
                    <span className="mr-1 rounded bg-gray-100 px-1 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-gray-500">Archive</span>
                  )}
                  {entry.folder_id
                    ? <a href={driveFolderUrl(entry.folder_id)} target="_blank" rel="noopener noreferrer" className="text-indigo-700 hover:text-indigo-900 hover:underline">{entry.path}</a>
                    : entry.path}
                </span>
              ))}
            </div>
          </div>
        ))}</div>
      </section>}
    </div>
  );
}
