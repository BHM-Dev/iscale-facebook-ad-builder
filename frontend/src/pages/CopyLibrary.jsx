import React, { useEffect, useMemo, useState } from 'react';
import { BookOpen, ChevronDown, RefreshCw, Star, Trash2, X } from 'lucide-react';
import { authFetch } from '../lib/facebookApi';
import { useToast } from '../context/ToastContext';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1';

function SkeletonRows() {
  return (
    <>
      {[0, 1, 2].map(row => (
        <tr key={row} className="border-b border-gray-50">
          <td className="px-5 py-4"><div className="h-4 w-32 bg-gray-100 rounded animate-pulse" /></td>
          <td className="px-5 py-4"><div className="h-4 w-44 bg-gray-100 rounded animate-pulse" /></td>
          <td className="px-5 py-4"><div className="h-4 w-full max-w-xl bg-gray-100 rounded animate-pulse" /></td>
          <td className="px-5 py-4 text-center"><div className="h-8 w-8 mx-auto bg-gray-100 rounded-lg animate-pulse" /></td>
          <td className="px-5 py-4 text-center"><div className="h-8 w-8 mx-auto bg-gray-100 rounded-lg animate-pulse" /></td>
        </tr>
      ))}
    </>
  );
}

function BodyCell({ text }) {
  const [expanded, setExpanded] = useState(false);
  const body = text || '';
  const shouldTruncate = body.length > 120;
  const displayText = expanded || !shouldTruncate ? body : `${body.slice(0, 120)}...`;

  return (
    <div className="max-w-2xl">
      <p className="text-sm text-gray-600 whitespace-pre-wrap leading-relaxed">{displayText}</p>
      {shouldTruncate && (
        <button
          type="button"
          onClick={() => setExpanded(value => !value)}
          className="mt-1 text-xs font-medium text-indigo-600 hover:text-indigo-700"
        >
          {expanded ? 'Show less' : 'Show more'}
        </button>
      )}
    </div>
  );
}

export default function CopyLibrary() {
  const { showSuccess, showError, showWarning } = useToast();
  const [entries, setEntries] = useState([]);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [selectedNiche, setSelectedNiche] = useState('');
  const [showSyncBanner, setShowSyncBanner] = useState(false);

  const niches = useMemo(() => {
    const values = entries
      .map(entry => entry.niche)
      .filter(Boolean);
    return [...new Set(values)].sort((a, b) => a.localeCompare(b));
  }, [entries]);

  const filteredEntries = useMemo(() => {
    if (!selectedNiche) return entries;
    return entries.filter(entry => entry.niche === selectedNiche);
  }, [entries, selectedNiche]);

  const loadEntries = async () => {
    setLoading(true);
    try {
      const res = await authFetch(`${API_URL}/ad-copy-library/`);
      if (!res.ok) {
        const error = await res.json().catch(() => ({}));
        throw new Error(error.detail || 'Failed to load copy library');
      }
      setEntries(await res.json());
    } catch (error) {
      showError(error.message || 'Failed to load copy library');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadEntries();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const syncFromMeta = async () => {
    setSyncing(true);
    try {
      const res = await authFetch(`${API_URL}/ad-copy-library/sync`, { method: 'POST' });
      if (!res.ok) {
        const error = await res.json().catch(() => ({}));
        throw new Error(error.detail || 'Sync failed');
      }
      const result = await res.json();
      showSuccess(`Library synced: ${result.created || 0} new, ${result.updated || 0} updated`);
      setShowSyncBanner(true);
      await loadEntries();
    } catch (error) {
      showError(error.message || 'Failed to sync copy library');
    } finally {
      setSyncing(false);
    }
  };

  const togglePin = async (entryId) => {
    const previous = entries;
    setEntries(current => current.map(entry => (
      entry.id === entryId ? { ...entry, is_pinned: !entry.is_pinned } : entry
    )));

    try {
      const res = await authFetch(`${API_URL}/ad-copy-library/${entryId}/pin`, { method: 'PATCH' });
      if (!res.ok) {
        const error = await res.json().catch(() => ({}));
        throw new Error(error.detail || 'Failed to update pin');
      }
      const result = await res.json();
      setEntries(current => current.map(entry => (
        entry.id === entryId ? { ...entry, is_pinned: result.is_pinned } : entry
      )));
    } catch (error) {
      setEntries(previous);
      showError(error.message || 'Failed to update pin');
    }
  };

  const deleteEntry = async (entryId) => {
    showWarning('Removing from library...');
    const previous = entries;
    setEntries(current => current.filter(entry => entry.id !== entryId));

    try {
      const res = await authFetch(`${API_URL}/ad-copy-library/${entryId}`, { method: 'DELETE' });
      if (!res.ok) {
        const error = await res.json().catch(() => ({}));
        throw new Error(error.detail || 'Failed to delete entry');
      }
      showSuccess('Removed from library');
    } catch (error) {
      setEntries(previous);
      showError(error.message || 'Failed to delete entry');
    }
  };

  return (
    <div className="max-w-7xl mx-auto space-y-6">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-2">
            <BookOpen size={24} className="text-indigo-600" />
            Copy Library
          </h1>
          <p className="text-sm text-gray-500 mt-1">Joel's real Meta ads for voice-matched copy generation.</p>
        </div>
        <button
          type="button"
          onClick={syncFromMeta}
          disabled={syncing}
          className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium text-white bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          <RefreshCw size={15} className={syncing ? 'animate-spin' : ''} />
          {syncing ? 'Syncing...' : 'Sync from Meta'}
        </button>
      </div>

      {showSyncBanner && (
        <div className="flex items-start justify-between gap-4 px-4 py-3 rounded-xl bg-amber-50 border border-amber-200 text-sm text-amber-800">
          <span>Library synced. The AI will now use these examples to match your voice when generating copy.</span>
          <button
            type="button"
            onClick={() => setShowSyncBanner(false)}
            className="text-amber-600 hover:text-amber-800"
            aria-label="Dismiss sync message"
          >
            <X size={14} />
          </button>
        </div>
      )}

      <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between gap-4">
          <div>
            <h2 className="font-semibold text-gray-900 text-sm">Imported Ads</h2>
            <p className="text-xs text-gray-400 mt-0.5">{filteredEntries.length} shown · {entries.length} total</p>
          </div>
          <div className="relative">
            <select
              value={selectedNiche}
              onChange={event => setSelectedNiche(event.target.value)}
              className="appearance-none bg-white border border-gray-200 rounded-lg pl-3 pr-9 py-2 text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-indigo-400"
            >
              <option value="">All niches</option>
              {niches.map(niche => (
                <option key={niche} value={niche}>{niche}</option>
              ))}
            </select>
            <ChevronDown size={14} className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-gray-400" />
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b border-gray-100">
              <tr className="text-left text-xs font-medium text-gray-500 uppercase tracking-wide">
                <th className="px-5 py-3">Niche</th>
                <th className="px-5 py-3">Headline</th>
                <th className="px-5 py-3">Body</th>
                <th className="px-5 py-3 text-center">Pinned</th>
                <th className="px-5 py-3 text-center">Delete</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {loading ? (
                <SkeletonRows />
              ) : filteredEntries.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-5 py-12 text-center text-sm text-gray-400">
                    No ads in library yet. Click 'Sync from Meta' to import your ads.
                  </td>
                </tr>
              ) : (
                filteredEntries.map(entry => (
                  <tr key={entry.id} className="hover:bg-gray-50 transition-colors align-top">
                    <td className="px-5 py-4 font-medium text-gray-900 whitespace-nowrap">{entry.niche || 'General'}</td>
                    <td className="px-5 py-4 text-gray-800 min-w-48">{entry.headline}</td>
                    <td className="px-5 py-4 min-w-96"><BodyCell text={entry.body} /></td>
                    <td className="px-5 py-4 text-center">
                      <button
                        type="button"
                        onClick={() => togglePin(entry.id)}
                        className={`inline-flex items-center justify-center w-8 h-8 rounded-lg border transition-colors ${
                          entry.is_pinned
                            ? 'bg-amber-50 border-amber-200 text-amber-500'
                            : 'border-gray-200 text-gray-300 hover:text-amber-500 hover:border-amber-200'
                        }`}
                        title={entry.is_pinned ? 'Unpin example' : 'Pin example'}
                      >
                        <Star size={16} fill={entry.is_pinned ? 'currentColor' : 'none'} />
                      </button>
                    </td>
                    <td className="px-5 py-4 text-center">
                      <button
                        type="button"
                        onClick={() => deleteEntry(entry.id)}
                        className="inline-flex items-center justify-center w-8 h-8 rounded-lg border border-red-100 text-red-500 hover:bg-red-50 transition-colors"
                        title="Delete from library"
                      >
                        <Trash2 size={15} />
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
