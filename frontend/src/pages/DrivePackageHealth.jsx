import React, { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, CheckCircle2, Copy, FolderSearch, RefreshCw } from 'lucide-react';
import { authFetch } from '../lib/facebookApi';
import { useToast } from '../context/ToastContext';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1';

const ISSUE_LABELS = {
  no_copy_source: 'No copy source',
  flat_package: 'Flat package',
  duplicate_basename_across_packages: 'Shared filename',
  duplicate_basename_within_package: 'Duplicate filename',
};

function IssueChip({ issue }) {
  return (
    <span className="inline-flex rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-800">
      {ISSUE_LABELS[issue] || issue}
    </span>
  );
}

export default function DrivePackageHealth() {
  const { showError } = useToast();
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(true);
  const [onlyIssues, setOnlyIssues] = useState(false);

  const loadReport = async () => {
    setLoading(true);
    try {
      const response = await authFetch(`${API_URL}/drive/package-health`);
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || 'Could not inspect Drive package health');
      setReport(data);
    } catch (error) {
      setReport(null);
      showError(error.message || 'Could not inspect Drive package health');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadReport();
  }, []);

  const packages = useMemo(() => {
    const all = report?.packages || [];
    return onlyIssues ? all.filter((item) => item.issues?.length) : all;
  }, [report, onlyIssues]);
  const issueCount = report?.packages?.filter((item) => item.issues?.length).length || 0;

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
          {report?.generated_at && <p className="mt-3 text-xs text-gray-400">Inspected {new Date(report.generated_at).toLocaleString()}</p>}
        </div>
        <button
          type="button"
          onClick={loadReport}
          disabled={loading}
          className="inline-flex items-center gap-2 rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm font-semibold text-gray-700 shadow-sm hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-60"
        >
          <RefreshCw size={16} className={loading ? 'animate-spin' : ''} /> Refresh
        </button>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-gray-200 bg-white px-4 py-3 shadow-sm">
        <div className="flex items-center gap-2 text-sm text-gray-700">
          {issueCount ? <AlertTriangle size={18} className="text-amber-600" /> : <CheckCircle2 size={18} className="text-emerald-600" />}
          <span><strong>{issueCount}</strong> of <strong>{report?.packages?.length || 0}</strong> packages need attention.</span>
        </div>
        <label className="flex cursor-pointer items-center gap-2 text-sm font-medium text-gray-700">
          <input type="checkbox" checked={onlyIssues} onChange={(event) => setOnlyIssues(event.target.checked)} className="h-4 w-4 rounded border-gray-300 text-gray-900 focus:ring-gray-500" />
          Only packages with issues
        </label>
      </div>

      <section className="overflow-hidden rounded-xl border border-gray-200 bg-white shadow-sm">
        <div className="border-b border-gray-200 px-5 py-4"><h2 className="font-semibold text-gray-900">Packages</h2></div>
        {loading ? (
          <div className="p-10 text-center text-sm text-gray-500">Inspecting Drive package structure…</div>
        ) : packages.length === 0 ? (
          <div className="p-10 text-center">
            <CheckCircle2 className="mx-auto mb-3 text-emerald-600" size={28} />
            <p className="font-medium text-gray-900">Everything is clean</p>
            <p className="mt-1 text-sm text-gray-500">No packages match this filter.</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] text-left text-sm">
              <thead className="bg-gray-50 text-xs font-semibold uppercase tracking-wide text-gray-500"><tr><th className="px-5 py-3">Package</th><th className="px-4 py-3 text-right">Media</th><th className="px-4 py-3">Copy source</th><th className="px-5 py-3">Issues</th></tr></thead>
              <tbody className="divide-y divide-gray-100">
                {packages.map((item) => <tr key={item.folder_id} className="align-top hover:bg-gray-50">
                  <td className="max-w-md break-words px-5 py-4 font-medium text-gray-900">{item.path}</td>
                  <td className="px-4 py-4 text-right tabular-nums text-gray-700">{item.media_count}</td>
                  <td className="px-4 py-4 text-gray-700">{item.copy_source.replace(/_/g, ' ')}</td>
                  <td className="px-5 py-4"><div className="flex max-w-sm flex-wrap gap-1.5">{item.issues?.length ? item.issues.map((issue) => <IssueChip key={issue} issue={issue} />) : <span className="text-emerald-700">Healthy</span>}</div></td>
                </tr>)}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {report?.collisions?.length > 0 && <section className="overflow-hidden rounded-xl border border-gray-200 bg-white shadow-sm">
        <div className="flex items-center gap-2 border-b border-gray-200 px-5 py-4"><Copy size={17} className="text-gray-500" /><div><h2 className="font-semibold text-gray-900">Cross-package filename collisions</h2><p className="text-xs text-gray-500">These names are reused under the same brand and need package-level copy context.</p></div></div>
        <div className="divide-y divide-gray-100">{report.collisions.map((collision) => <div key={collision.basename} className="grid gap-2 px-5 py-4 sm:grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)]"><div className="break-all font-mono text-xs text-gray-800">{collision.basename}</div><div className="min-w-0 break-words text-sm text-gray-600">{collision.packages.join(' · ')}</div></div>)}</div>
      </section>}
    </div>
  );
}
