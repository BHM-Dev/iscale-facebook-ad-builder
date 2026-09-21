import React, { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, CheckCircle2, Copy, FolderSearch, RefreshCw } from 'lucide-react';
import { authFetch } from '../lib/facebookApi';
import { useToast } from '../context/ToastContext';

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
  const { showError, showInfo } = useToast();
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

  useEffect(() => {
    loadReport();
  }, []);

  useEffect(() => {
    if (!rebuilding) return undefined;
    const timer = setInterval(() => loadReport({ silent: true }), 15000);
    return () => clearInterval(timer);
  }, [rebuilding]);

  const packages = useMemo(() => {
    const all = report?.packages || [];
    const filtered = onlyIssues ? all.filter(willRefuse) : all;
    // Refusals first: they are the only rows anyone has to act on today.
    return [...filtered].sort((a, b) => (willRefuse(b) ? 1 : 0) - (willRefuse(a) ? 1 : 0));
  }, [report, onlyIssues]);
  const issueCount = report?.packages?.filter((item) => item.issues?.length).length || 0;
  const blockingCount = report?.packages?.filter(willRefuse).length || 0;

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
            <strong>{blockingCount}</strong> of <strong>{report?.packages?.length || 0}</strong> packages will be refused at launch.
            {issueCount > blockingCount && (
              <span className="text-gray-500"> · {issueCount - blockingCount} more have a structural finding that does not block launch.</span>
            )}
          </span>
        </div>
        <label className="flex cursor-pointer items-center gap-2 text-sm font-medium text-gray-700">
          <input type="checkbox" checked={onlyIssues} onChange={(event) => setOnlyIssues(event.target.checked)} className="h-4 w-4 rounded border-gray-300 text-gray-900 focus:ring-gray-500" />
          Only packages that will be refused
        </label>
      </div>
      )}

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
            <p className="font-medium text-gray-900">Nothing will be refused at launch</p>
            <p className="mt-1 text-sm text-gray-500">No packages match this filter.</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] text-left text-sm">
              <thead className="bg-gray-50 text-xs font-semibold uppercase tracking-wide text-gray-500"><tr><th className="px-5 py-3">Package</th><th className="px-4 py-3 text-right">Media</th><th className="px-4 py-3">Copy source</th><th className="px-5 py-3">Issues</th></tr></thead>
              <tbody className="divide-y divide-gray-100">
                {packages.map((item) => <tr key={item.folder_id} className="align-top hover:bg-gray-50">
                  <td className="max-w-md break-words px-5 py-4 font-medium text-gray-900">
                    {/* folder_id is already in the payload -- naming a problem and then
                        making someone hunt for the folder by hand is how a report
                        gets opened once. */}
                    <a href={driveFolderUrl(item.folder_id)} target="_blank" rel="noopener noreferrer" className="text-indigo-700 hover:text-indigo-900 hover:underline">
                      {item.path}
                    </a>
                  </td>
                  <td className="px-4 py-4 text-right tabular-nums text-gray-700">{item.media_count}</td>
                  <td className="px-4 py-4 text-gray-700">{item.copy_source.replace(/_/g, ' ')}</td>
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
        <div className="flex items-center gap-2 border-b border-gray-200 px-5 py-4"><Copy size={17} className="text-gray-500" /><div><h2 className="font-semibold text-gray-900">Cross-package filename collisions</h2><p className="text-xs text-gray-500">These names are reused under the same brand and need package-level copy context.</p></div></div>
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
