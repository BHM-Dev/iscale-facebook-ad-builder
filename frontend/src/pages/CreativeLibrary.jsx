import React, { useEffect, useMemo, useState } from 'react';
import { ExternalLink, Film, FolderOpen, Image, RefreshCw, Search } from 'lucide-react';
import { authFetch } from '../lib/facebookApi';
import { useBrands } from '../context/BrandContext';
import { useToast } from '../context/ToastContext';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1';

function formatTimestamp(value) {
  if (!value) return 'Never';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return 'Never';
  return date.toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  });
}

function breadcrumb(path) {
  if (!path) return 'Root';
  return path.split('/').filter(Boolean).join(' / ');
}

function groupAssets(assets) {
  return assets.reduce((groups, asset) => {
    const brandName = asset.brand_name || 'Unmatched Brand';
    const path = asset.folder_path || '';
    const key = `${brandName}__${path}`;
    if (!groups[key]) {
      groups[key] = { brandName, folderPath: path, assets: [] };
    }
    groups[key].assets.push(asset);
    return groups;
  }, {});
}

export default function CreativeLibrary() {
  const { brands } = useBrands();
  const { showSuccess, showError } = useToast();
  const [assets, setAssets] = useState([]);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [selectedBrand, setSelectedBrand] = useState('');
  const [format, setFormat] = useState('');
  const [searchTerm, setSearchTerm] = useState('');

  const fetchAssets = async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (selectedBrand) params.set('brand_id', selectedBrand);
      if (format) params.set('format', format);
      const res = await authFetch(`${API_URL}/drive-assets?${params.toString()}`);
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || 'Could not load Drive assets');
      }
      const data = await res.json();
      setAssets(Array.isArray(data) ? data : []);
    } catch (error) {
      setAssets([]);
      showError(error.message || 'Could not load Drive assets');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchAssets();
  }, [selectedBrand, format]);

  const syncNow = async () => {
    setSyncing(true);
    try {
      const res = await authFetch(`${API_URL}/drive-assets/sync-now`, { method: 'POST' });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(data.detail || 'Drive sync failed');
      }
      showSuccess(`Drive sync complete: ${data.created || 0} new, ${data.updated || 0} updated, ${data.archived || 0} archived`);
      await fetchAssets();
    } catch (error) {
      showError(error.message || 'Drive sync failed');
    } finally {
      setSyncing(false);
    }
  };

  const filteredAssets = useMemo(() => {
    const query = searchTerm.trim().toLowerCase();
    if (!query) return assets;
    return assets.filter(asset => {
      const haystack = `${asset.file_name || ''} ${asset.folder_path || ''} ${asset.brand_name || ''}`.toLowerCase();
      return haystack.includes(query);
    });
  }, [assets, searchTerm]);

  const groups = useMemo(() => {
    return Object.values(groupAssets(filteredAssets)).sort((a, b) => {
      const brandCompare = a.brandName.localeCompare(b.brandName);
      if (brandCompare !== 0) return brandCompare;
      return a.folderPath.localeCompare(b.folderPath);
    });
  }, [filteredAssets]);

  const counts = useMemo(() => {
    return assets.reduce((acc, asset) => {
      acc.total += 1;
      acc[asset.format] = (acc[asset.format] || 0) + 1;
      return acc;
    }, { total: 0, image: 0, video: 0 });
  }, [assets]);

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="border-b border-gray-200 bg-white">
        <div className="px-8 py-6">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <div className="flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-indigo-50 text-indigo-700">
                  <FolderOpen size={20} />
                </div>
                <div>
                  <h1 className="text-2xl font-semibold text-gray-900">Creative Library</h1>
                  <p className="mt-1 text-sm text-gray-500">Google Drive creative synced into the Ad Builder asset store.</p>
                </div>
              </div>
            </div>
            <button
              type="button"
              onClick={syncNow}
              disabled={syncing}
              className="inline-flex items-center justify-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-60"
            >
              <RefreshCw size={16} className={syncing ? 'animate-spin' : ''} />
              {syncing ? 'Syncing' : 'Sync now'}
            </button>
          </div>

          <div className="mt-6 grid gap-3 lg:grid-cols-[1fr_220px_220px]">
            <label className="relative block">
              <Search className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" size={17} />
              <input
                value={searchTerm}
                onChange={(event) => setSearchTerm(event.target.value)}
                placeholder="Search filenames, folders, or brands"
                className="h-11 w-full rounded-lg border border-gray-300 bg-white pl-10 pr-3 text-sm text-gray-900 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100"
              />
            </label>
            <select
              value={selectedBrand}
              onChange={(event) => setSelectedBrand(event.target.value)}
              className="h-11 rounded-lg border border-gray-300 bg-white px-3 text-sm text-gray-900 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100"
            >
              <option value="">All brands</option>
              {brands.map(brand => (
                <option key={brand.id} value={brand.id}>{brand.name}</option>
              ))}
            </select>
            <div className="flex h-11 overflow-hidden rounded-lg border border-gray-300 bg-white">
              {[
                { value: '', label: `All ${counts.total}` },
                { value: 'image', label: `Images ${counts.image || 0}` },
                { value: 'video', label: `Videos ${counts.video || 0}` },
              ].map(option => (
                <button
                  key={option.value || 'all'}
                  type="button"
                  onClick={() => setFormat(option.value)}
                  className={`flex-1 px-3 text-xs font-semibold transition-colors ${
                    format === option.value
                      ? 'bg-gray-900 text-white'
                      : 'text-gray-600 hover:bg-gray-50'
                  }`}
                >
                  {option.label}
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>

      <main className="px-8 py-6">
        {loading ? (
          <div className="flex h-64 items-center justify-center text-sm text-gray-500">Loading Drive assets...</div>
        ) : groups.length === 0 ? (
          <div className="flex h-64 flex-col items-center justify-center rounded-lg border border-dashed border-gray-300 bg-white text-center">
            <FolderOpen className="text-gray-300" size={36} />
            <h2 className="mt-3 text-sm font-semibold text-gray-900">No synced creative found</h2>
            <p className="mt-1 max-w-md text-sm text-gray-500">Run a sync after the Drive migration and service-account env vars are installed.</p>
          </div>
        ) : (
          <div className="space-y-8">
            {groups.map(group => (
              <section key={`${group.brandName}-${group.folderPath}`} className="space-y-3">
                <div className="flex flex-col gap-1 sm:flex-row sm:items-end sm:justify-between">
                  <div>
                    <h2 className="text-base font-semibold text-gray-900">{group.brandName}</h2>
                    <p className="text-sm text-gray-500">{breadcrumb(group.folderPath)}</p>
                  </div>
                  <span className="text-xs font-semibold uppercase text-gray-400">{group.assets.length} assets</span>
                </div>

                <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4 2xl:grid-cols-5">
                  {group.assets.map(asset => (
                    <article key={asset.id} className="overflow-hidden rounded-lg border border-gray-200 bg-white shadow-sm">
                      <div className="relative aspect-[4/3] bg-gray-100">
                        {asset.format === 'video' ? (
                          <video src={asset.r2_key} className="h-full w-full object-cover" muted playsInline preload="metadata" />
                        ) : (
                          <img src={asset.r2_key} alt={asset.file_name} className="h-full w-full object-cover" loading="lazy" />
                        )}
                        <div className="absolute left-2 top-2 inline-flex items-center gap-1 rounded-full bg-white/90 px-2 py-1 text-[11px] font-semibold text-gray-700 shadow-sm">
                          {asset.format === 'video' ? <Film size={12} /> : <Image size={12} />}
                          {asset.format}
                        </div>
                      </div>
                      <div className="space-y-3 p-3">
                        <div>
                          <h3 className="truncate text-sm font-semibold text-gray-900" title={asset.file_name}>{asset.file_name}</h3>
                          <p className="mt-1 text-xs text-gray-500">Synced {formatTimestamp(asset.synced_at)}</p>
                        </div>
                        <a
                          href={asset.r2_key}
                          target="_blank"
                          rel="noreferrer"
                          className="inline-flex items-center gap-1 text-xs font-semibold text-indigo-600 hover:text-indigo-800"
                        >
                          Open asset <ExternalLink size={12} />
                        </a>
                      </div>
                    </article>
                  ))}
                </div>
              </section>
            ))}
          </div>
        )}
      </main>
    </div>
  );
}
