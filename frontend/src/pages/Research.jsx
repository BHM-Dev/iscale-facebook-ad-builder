import React, { useState, useEffect, useRef, useMemo } from 'react';
import { Ban, FlaskConical, RefreshCw, Star, ExternalLink, ChevronDown, Trash2, Zap, X, Upload, BookOpen, Video, BarChart3 } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { useToast } from '../context/ToastContext';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1';

// ── Angle tag config ────────────────────────────────────────────
const ANGLE_COLORS = {
  fear:         'bg-red-100 text-red-700',
  social_proof: 'bg-blue-100 text-blue-700',
  urgency:      'bg-orange-100 text-orange-700',
  savings:      'bg-green-100 text-green-700',
  authority:    'bg-purple-100 text-purple-700',
  story:        'bg-amber-100 text-amber-700',
  curiosity:    'bg-teal-100 text-teal-700',
};

const ANGLE_LABELS = {
  fear: 'Fear', social_proof: 'Social Proof', urgency: 'Urgency',
  savings: 'Savings', authority: 'Authority', story: 'Story', curiosity: 'Curiosity',
};

const normalizeAdLibraryDate = (value) => {
  if (!value) return '';
  if (/^\d{4}-\d{2}-\d{2}/.test(value)) return value;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toISOString().slice(0, 10);
};

const normalizeAdLibraryImport = (raw, activeVerticalLabel) => {
  const sourceAds = raw.ads || raw.visible_ads || [];
  const videos = raw.videos || [];
  const sourceUrl = raw.source_url || raw.page_url || '';
  const queryFromUrl = (() => {
    try {
      const url = new URL(sourceUrl);
      return url.searchParams.get('q') || '';
    } catch (_) {
      return '';
    }
  })();
  const mappedVideoUrls = new Set(
    sourceAds.flatMap(ad => (
      videos
        .filter(video => video.ad_library_id && video.ad_library_id === (ad.library_id || ad.external_id))
        .map(video => video.url)
        .filter(Boolean)
    )),
  );
  const unmappedVideoCount = videos.filter(video => video.url && !mappedVideoUrls.has(video.url)).length;

  return {
    query: raw.query || queryFromUrl || 'cheap auto insurance',
    country: raw.country || 'US',
    // Chrome-captured JSON never sets `vertical` (the snippet doesn't know
    // which tab you'll paste into), so the active tab is the right default.
    // But a pre-built payload (e.g. from ad_library_prepare_import.py) can
    // declare its own vertical — respect that explicit intent over whatever
    // tab happens to be open, since silently overriding it caused a real
    // mis-import (2026-08-02).
    vertical: raw.vertical || activeVerticalLabel || 'Auto Insurance',
    sort_mode: raw.sort_mode || raw.sort || 'total_impressions_desc',
    source_url: sourceUrl,
    ads: sourceAds
      .filter(ad => ad.library_id || ad.external_id)
      .map((ad, index) => {
        const adVideos = videos
          .filter(video => video.ad_library_id && video.ad_library_id === ad.library_id)
          .slice(0, 3)
          .map(video => video.url)
          .filter(Boolean);
        const preview = ad.body_preview || ad.ad_copy || ad.body || '';
        return {
          library_id: ad.library_id || ad.external_id,
          brand_name: ad.page || ad.brand_name || ad.advertiser || '',
          headline: ad.headline || '',
          ad_copy: ad.ad_copy || preview,
          cta_text: ad.cta || ad.cta_text || '',
          ad_link: ad.ad_link || `https://www.facebook.com/ads/library/?id=${ad.library_id || ad.external_id}`,
          platforms: ad.platforms || ['facebook'],
          start_date: normalizeAdLibraryDate(ad.started_running || ad.start_date || ''),
          media_type: ad.media_type || (adVideos.length ? 'video' : 'image'),
          media_url: ad.media_url || ad.thumbnail_url || '',
          destination_domain: ad.domain || ad.destination_domain || '',
          rank_position: ad.rank_position ?? index + 1,
          is_multiple_versions: Boolean(ad.multiple_versions ?? ad.is_multiple_versions),
          video_urls: ad.video_urls || adVideos,
          thumbnail_url: ad.thumbnail_url || ad.media_url || '',
          creative_intel: {
            visible_copy_preview: preview,
            imported_from_chrome: true,
            unmapped_video_inventory_count: unmappedVideoCount,
          },
        };
      }),
  };
};

function AngleBadge({ tag }) {
  if (!tag) return null;
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold uppercase tracking-wide ${ANGLE_COLORS[tag] || 'bg-gray-100 text-gray-600'}`}>
      {ANGLE_LABELS[tag] || tag}
    </span>
  );
}

// ── Expandable body text ────────────────────────────────────────
function BodyText({ text }) {
  const [expanded, setExpanded] = useState(false);
  if (!text) return null;
  const shouldTruncate = text.length > 140;
  const display = expanded || !shouldTruncate ? text : `${text.slice(0, 140)}…`;
  return (
    <div>
      <p className="text-sm text-gray-600 leading-relaxed whitespace-pre-wrap">{display}</p>
      {shouldTruncate && (
        <button
          type="button"
          onClick={() => setExpanded(v => !v)}
          className="mt-0.5 text-xs font-medium text-indigo-500 hover:text-indigo-700"
        >
          {expanded ? 'Show less' : 'Show more'}
        </button>
      )}
    </div>
  );
}

// ── Save button with angle picker ───────────────────────────────
function SaveButton({ ad, isSaved, onSave, onUnsave, angleTags }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    if (!open) return;
    const handler = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open]);

  if (isSaved) {
    return (
      <button
        type="button"
        onClick={() => onUnsave(ad)}
        className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg border border-amber-200 bg-amber-50 text-amber-600 text-xs font-medium hover:bg-red-50 hover:border-red-200 hover:text-red-600 transition-colors"
      >
        <Star size={12} fill="currentColor" />
        Saved
      </button>
    );
  }

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen(v => !v)}
        className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg border border-gray-200 text-gray-500 text-xs font-medium hover:border-amber-300 hover:text-amber-600 transition-colors"
      >
        <Star size={12} />
        Save
        <ChevronDown size={10} />
      </button>
      {open && (
        <div className="absolute right-0 top-8 z-10 bg-white border border-gray-200 rounded-xl shadow-lg p-2 min-w-[160px]">
          <p className="text-xs text-gray-400 px-2 py-1 mb-1">Pick an angle (optional)</p>
          <button
            type="button"
            onClick={() => { onSave(ad, null); setOpen(false); }}
            className="w-full text-left px-2 py-1.5 text-xs text-gray-600 hover:bg-gray-50 rounded-lg"
          >
            No tag — just save
          </button>
          {angleTags.map(tag => (
            <button
              key={tag.value}
              type="button"
              onClick={() => { onSave(ad, tag.value); setOpen(false); }}
              className="w-full text-left px-2 py-1.5 text-xs hover:bg-gray-50 rounded-lg"
            >
              <span className={`inline-block px-1.5 py-0.5 rounded text-xs font-semibold mr-1 ${ANGLE_COLORS[tag.value] || ''}`}>
                {tag.label}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Ad Card ─────────────────────────────────────────────────────
function AdCard({ ad, isSaved, onSave, onUnsave, onUseAsInspiration, onBlockPage, angleTags }) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4 hover:shadow-sm transition-shadow flex flex-col gap-3">
      {/* Facebook CDN media URLs are temporary; hide expired thumbnails without disrupting the card. */}
      {ad.media_url && (
        <div className="rounded-lg overflow-hidden bg-gray-100 -mx-4 -mt-4 mb-1">
          <img
            src={ad.media_url}
            alt=""
            className="w-full object-cover max-h-48"
            onError={(e) => { e.target.parentElement.style.display = 'none'; }}
          />
        </div>
      )}

      {/* Header: status dot + advertiser */}
      <div className="flex items-center gap-2">
        <span className={`flex items-center gap-1 text-xs font-medium ${ad.is_active ? 'text-green-600' : 'text-gray-400'}`}>
          <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${ad.is_active ? 'bg-green-500' : 'bg-gray-300'}`} />
          {ad.is_active ? 'ACTIVE' : 'STOPPED'}
        </span>
        {ad.media_type === 'video' && (
          <span className="inline-flex items-center gap-1 text-xs font-medium text-purple-600">
            <Video size={11} />
            VIDEO
          </span>
        )}
        <a
          href={`https://www.facebook.com/ads/library/?active_status=all&ad_type=all&country=US&q=${encodeURIComponent(ad.brand_name || '')}`}
          target="_blank"
          rel="noopener noreferrer"
          className="text-xs font-semibold text-gray-700 hover:text-indigo-600 truncate flex items-center gap-0.5"
        >
          {ad.brand_name || 'Unknown Advertiser'}
          <ExternalLink size={10} className="flex-shrink-0 opacity-50" />
        </a>
      </div>

      {/* Headline */}
      {ad.headline && (
        <p className="font-semibold text-gray-900 text-sm leading-snug">{ad.headline}</p>
      )}

      {/* Body */}
      <BodyText text={ad.ad_copy} />

      {/* Tags + duration */}
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <AngleBadge tag={ad.angle_tag} />
        {ad.volume_score != null && (
          <span className="inline-flex items-center gap-1 text-xs font-semibold text-indigo-600 bg-indigo-50 border border-indigo-100 rounded px-2 py-0.5">
            <BarChart3 size={11} />
            Vol {ad.volume_score}
          </span>
        )}
        {ad.rank_position != null && (
          <span className="text-xs text-gray-400">Rank #{ad.rank_position}</span>
        )}
        {ad.is_multiple_versions && (
          <span className="text-xs text-gray-400">Multiple versions</span>
        )}
        {ad.running_days != null && (
          <span className="text-xs text-gray-400">Running {ad.running_days}d</span>
        )}
        {ad.destination_domain && (
          <span className="text-xs text-gray-400 truncate max-w-[160px]">{ad.destination_domain}</span>
        )}
        {ad.seen_count > 1 && (
          <span className="text-xs text-gray-400">Seen {ad.seen_count}×</span>
        )}
      </div>

      {/* Actions */}
      <div className="flex flex-col gap-1.5 pt-1 border-t border-gray-100">
        {/* Primary row */}
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => onUseAsInspiration(ad)}
            className="flex-1 inline-flex items-center justify-center gap-1 px-3 py-1.5 rounded-lg border border-indigo-200 bg-indigo-50 text-indigo-700 text-xs font-medium hover:bg-indigo-100 transition-colors"
          >
            <Zap size={12} />
            Build from this ad
          </button>
          <SaveButton
            ad={ad}
            isSaved={isSaved}
            onSave={onSave}
            onUnsave={onUnsave}
            angleTags={angleTags}
          />
        </div>
        {/* Secondary row */}
        <div className="flex items-center gap-2">
          <a
            href={`https://www.facebook.com/ads/library/?active_status=active&ad_type=all&country=US&q=${encodeURIComponent(ad.brand_name || '')}`}
            target="_blank"
            rel="noopener noreferrer"
            className="flex-1 inline-flex items-center justify-center gap-1 px-2 py-1 rounded-md border border-gray-200 text-xs font-medium text-gray-500 hover:text-indigo-600 hover:border-indigo-200 transition-colors"
            title="View all ads from this advertiser"
          >
            <ExternalLink size={11} />
            View all ads
          </a>
          <button
            type="button"
            onClick={() => onBlockPage(ad)}
            className="flex-1 inline-flex items-center justify-center gap-1 px-2 py-1 rounded-md border border-gray-200 text-xs font-medium text-gray-500 hover:text-red-500 hover:border-red-200 transition-colors"
            title="Block this advertiser"
          >
            <Ban size={11} />
            Block advertiser
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Saved panel card (compact) ───────────────────────────────────
function SavedCard({ ad, onUnsave, onUseAsInspiration }) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-3 flex flex-col gap-2">
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          <p className="text-xs font-semibold text-gray-500 truncate">{ad.brand_name || '—'}</p>
          {ad.headline && <p className="text-sm font-medium text-gray-900 leading-snug mt-0.5 line-clamp-2">{ad.headline}</p>}
        </div>
        <button
          type="button"
          onClick={() => onUnsave(ad)}
          className="flex-shrink-0 p-1 text-gray-300 hover:text-red-400 transition-colors"
          title="Unsave"
        >
          <X size={14} />
        </button>
      </div>
      <div className="flex items-center gap-1.5 flex-wrap">
        {ad.angle_tag && <AngleBadge tag={ad.angle_tag} />}
        {ad.media_type === 'video' && (
          <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-xs font-semibold bg-purple-50 text-purple-600">
            <Video size={10} />
            Video
          </span>
        )}
        {ad.volume_score != null && (
          <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-xs font-semibold bg-indigo-50 text-indigo-600">
            <BarChart3 size={10} />
            {ad.volume_score}
          </span>
        )}
      </div>
      <button
        type="button"
        onClick={() => onUseAsInspiration(ad)}
        className="w-full inline-flex items-center justify-center gap-1 px-2 py-1.5 rounded-lg border border-indigo-200 bg-indigo-50 text-indigo-700 text-xs font-medium hover:bg-indigo-100 transition-colors"
      >
        <Zap size={11} />
        Build from this ad
      </button>
    </div>
  );
}

// ── Skeleton cards ───────────────────────────────────────────────
function SkeletonCard() {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4 space-y-3 animate-pulse">
      <div className="h-3 w-1/2 bg-gray-100 rounded" />
      <div className="h-4 w-4/5 bg-gray-100 rounded" />
      <div className="space-y-1.5">
        <div className="h-3 w-full bg-gray-100 rounded" />
        <div className="h-3 w-2/3 bg-gray-100 rounded" />
      </div>
      <div className="h-7 bg-gray-100 rounded-lg" />
    </div>
  );
}

function AdLibraryImportModal({ open, onClose, onImport, importing, defaultQuery }) {
  const [payloadText, setPayloadText] = useState('');

  useEffect(() => {
    if (!open) setPayloadText('');
  }, [open]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 bg-black/50 backdrop-blur-sm z-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-xl shadow-xl max-w-2xl w-full p-6">
        <div className="flex items-start justify-between gap-4 mb-4">
          <div>
            <h3 className="text-lg font-semibold text-gray-900">Import Ad Library Intel</h3>
            <p className="text-sm text-gray-500 mt-1">
              Paste the Chrome capture JSON from a US, active, most-impressions Ad Library search.
            </p>
          </div>
          <button type="button" onClick={onClose} className="p-1 text-gray-400 hover:text-gray-600">
            <X size={18} />
          </button>
        </div>

        <div className="bg-indigo-50 border border-indigo-100 rounded-lg p-3 mb-4 text-sm text-indigo-900">
          <div className="font-semibold mb-1">Joel/Saule flow</div>
          <ol className="list-decimal pl-5 space-y-1">
            <li>Open Facebook Ad Library in Chrome.</li>
            <li>Search <strong>{defaultQuery || 'cheap auto insurance'}</strong> or <strong>auto insurance</strong>.</li>
            <li>Use United States, active ads, sorted by most impressions.</li>
            <li>Run <strong>backend/scripts/ad_library_capture_snippet.js</strong> in Chrome DevTools, paste the downloaded JSON here, then review/save the best examples.</li>
          </ol>
        </div>

        <textarea
          value={payloadText}
          onChange={e => setPayloadText(e.target.value)}
          placeholder='{"query":"cheap auto insurance","visible_ads":[...],"videos":[...]}'
          className="w-full h-56 border border-gray-200 rounded-lg p-3 text-xs font-mono focus:ring-2 focus:ring-indigo-400 focus:border-transparent"
        />

        <div className="flex items-center justify-between gap-3 mt-4">
          <p className="text-xs text-gray-400">
            Competitor media is stored as inspiration only. Use BHM-owned/generated video for launch.
          </p>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-sm font-medium text-gray-700 border border-gray-300 rounded-lg hover:bg-gray-50"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={() => onImport(payloadText)}
              disabled={importing || !payloadText.trim()}
              className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium text-white bg-indigo-600 hover:bg-indigo-700 rounded-lg disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <Upload size={15} />
              {importing ? 'Importing...' : 'Import Intel'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Main page ────────────────────────────────────────────────────
export default function Research() {
  const { authFetch } = useAuth();
  const { showSuccess, showError, showInfo, showWarning } = useToast();
  const navigate = useNavigate();

  const [verticalConfig, setVerticalConfig] = useState(null);
  const [activeVertical, setActiveVertical] = useState('commercial_insurance');
  const [activeSubVertical, setActiveSubVertical] = useState(null);
  const [homeServicesOpen, setHomeServicesOpen] = useState(false);
  const homeServicesRef = useRef(null);

  const [browseAds, setBrowseAds] = useState([]);
  const [savedAds, setSavedAds] = useState([]);
  const [savedAdIds, setSavedAdIds] = useState(new Set());
  const [browseLoading, setBrowseLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [browseError, setBrowseError] = useState('');
  const [refreshSummary, setRefreshSummary] = useState(null);
  const [showClearModal, setShowClearModal] = useState(false);
  const [showImportModal, setShowImportModal] = useState(false);
  const [importingIntel, setImportingIntel] = useState(false);
  const [clearing, setClearing] = useState(false);

  // Filters
  const [angleFilter, setAngleFilter] = useState('');
  const [activeOnly, setActiveOnly] = useState(false);
  const [advertiserFilter, setAdvertiserFilter] = useState('');

  // ── Boot ─────────────────────────────────────────────────────
  useEffect(() => {
    loadConfig();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!verticalConfig) return;
    setRefreshSummary(null);
    loadBrowseAds();
    loadSavedAds();
  }, [activeVertical, activeSubVertical, verticalConfig]); // eslint-disable-line react-hooks/exhaustive-deps

  // Close Home Services dropdown on outside click
  useEffect(() => {
    if (!homeServicesOpen) return;
    const handler = (e) => {
      if (homeServicesRef.current && !homeServicesRef.current.contains(e.target)) {
        setHomeServicesOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [homeServicesOpen]);

  const loadConfig = async () => {
    try {
      const res = await authFetch(`${API_URL}/research/vertical-config`);
      if (!res.ok) throw new Error('Failed to load config');
      setVerticalConfig(await res.json());
    } catch (e) {
      showError('Failed to load vertical config');
    }
  };

  const loadBrowseAds = async () => {
    setBrowseLoading(true);
    setBrowseError('');
    setBrowseAds([]);
    try {
      const params = new URLSearchParams();
      if (activeSubVertical) params.set('sub_vertical', activeSubVertical);
      if (angleFilter) params.set('angle_tag', angleFilter);
      if (activeOnly) params.set('active_only', 'true');
      if (advertiserFilter.trim()) params.set('advertiser', advertiserFilter.trim());
      params.set('limit', '500');

      const res = await authFetch(`${API_URL}/research/config-verticals/${activeVertical}/browse-ads?${params}`);
      if (!res.ok) throw new Error('Failed to load ads');
      setBrowseAds(await res.json());
    } catch (e) {
      setBrowseError(e.message || 'Failed to load ads');
    } finally {
      setBrowseLoading(false);
    }
  };

  const loadSavedAds = async () => {
    try {
      const res = await authFetch(`${API_URL}/research/scraped-ads/saved`);
      if (!res.ok) return;
      const all = await res.json();
      setSavedAds(all);
      setSavedAdIds(new Set(all.map(a => a.id)));
    } catch (e) { /* non-blocking */ }
  };

  // Re-run browse when filters change (with debounce on advertiser text)
  useEffect(() => {
    if (!verticalConfig) return;
    const t = setTimeout(() => loadBrowseAds(), advertiserFilter ? 400 : 0);
    return () => clearTimeout(t);
  }, [angleFilter, activeOnly, advertiserFilter]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Actions ──────────────────────────────────────────────────
  const handleRefresh = async () => {
    setRefreshing(true);
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 180000); // 3 min cap

    try {
      const params = new URLSearchParams({ vertical_id: activeVertical });
      if (activeSubVertical) params.set('sub_vertical', activeSubVertical);
      params.set('limit_per_keyword', '20');

      const res = await authFetch(`${API_URL}/research/search-and-save-vertical?${params}`, {
        method: 'POST',
        signal: controller.signal,
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'Refresh failed');
      }
      const result = await res.json();
      setRefreshSummary(result);
      if (result.keywords_run === 0) {
        showError('Refresh failed — Facebook token may be missing. Ping Steve or Golden to check the API config.');
      } else if (result.first_error) {
        showInfo(`Refresh partially completed — ${result.keywords_run} keywords checked, ${result.total_new} new ads. First error: ${result.first_error}`);
        loadBrowseAds();
        loadSavedAds();
      } else if (result.total_new === 0) {
        const duplicateText = result.total_duplicate > 0 ? `, ${result.total_duplicate} duplicates seen` : '';
        showInfo(`No new ads — ${result.keywords_run} keywords checked${duplicateText}`);
        loadBrowseAds();
        loadSavedAds();
      } else {
        showSuccess(result.message || `Refresh complete — ${result.total_new} new ads`);
        loadBrowseAds();
        loadSavedAds();
      }
    } catch (e) {
      if (e.name === 'AbortError') {
        showError('Refresh timed out — try a single sub-vertical tab instead of pulling all at once.');
      } else {
        showError(e.message || 'Refresh failed');
      }
    } finally {
      clearTimeout(timeoutId);
      setRefreshing(false);
    }
  };

  const handleClear = async () => {
    setClearing(true);
    setShowClearModal(false);
    try {
      const res = await authFetch(`${API_URL}/research/config-verticals/${activeVertical}/ads`, {
        method: 'DELETE',
      });
      if (!res.ok) throw new Error('Clear failed');
      const result = await res.json();
      showSuccess(`Cleared ${result.deleted} ads — pulling fresh results now…`);
      handleRefresh();
    } catch (e) {
      showError(e.message || 'Clear failed');
    } finally {
      setClearing(false);
    }
  };

  const handleSave = async (ad, angleTag) => {
    // Optimistic update
    setSavedAdIds(prev => new Set([...prev, ad.id]));
    setSavedAds(prev => [{ ...ad, is_saved: true, angle_tag: angleTag }, ...prev.filter(a => a.id !== ad.id)]);

    try {
      const params = new URLSearchParams();
      if (angleTag) params.set('angle_tag', angleTag);
      const res = await authFetch(
        `${API_URL}/research/scraped-ads/${ad.id}/save?${params}`,
        { method: 'POST' },
      );
      if (!res.ok) throw new Error('Save failed');
      showSuccess('Ad saved to research library');
    } catch (e) {
      // Roll back
      setSavedAdIds(prev => { const s = new Set(prev); s.delete(ad.id); return s; });
      setSavedAds(prev => prev.filter(a => a.id !== ad.id));
      showError('Failed to save ad');
    }
  };

  const handleUnsave = async (ad) => {
    setSavedAdIds(prev => { const s = new Set(prev); s.delete(ad.id); return s; });
    setSavedAds(prev => prev.filter(a => a.id !== ad.id));

    try {
      await authFetch(`${API_URL}/research/scraped-ads/${ad.id}/save`, { method: 'DELETE' });
    } catch (e) {
      // Reload to correct state
      loadSavedAds();
    }
  };

  const handleImportIntel = async (payloadText) => {
    setImportingIntel(true);
    try {
      const raw = JSON.parse(payloadText);
      const payload = normalizeAdLibraryImport(raw, currentVerticalLabel);
      if (!payload.ads.length) {
        throw new Error('No ads found in pasted JSON');
      }
      if (raw.vertical && raw.vertical.trim().toLowerCase() !== (currentVerticalLabel || '').trim().toLowerCase()) {
        showWarning(`Pasted JSON specifies vertical "${raw.vertical}" — importing there, not into the "${currentVerticalLabel}" tab you have open.`);
      }
      const res = await authFetch(`${API_URL}/research/ad-library-import`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const result = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(result.detail || 'Import failed');
      const quality = result.quality || {};
      const qualityBits = [
        `${quality.with_media ?? 0} with media`,
        `${quality.with_video ?? 0} with mapped video`,
        `${quality.multiple_versions ?? 0} multi-version`,
      ];
      if (quality.unmapped_video_inventory) {
        qualityBits.push(`${quality.unmapped_video_inventory} unmapped videos observed`);
      }
      if ((quality.with_media ?? 0) === 0 || (quality.with_video ?? 0) === 0) {
        showInfo(`Import saved as text intel: ${qualityBits.join(', ')}`);
      } else {
        showSuccess(`${result.message || `Imported ${payload.ads.length} ads`} — ${qualityBits.join(', ')}`);
      }
      setShowImportModal(false);
      loadBrowseAds();
      loadSavedAds();
    } catch (e) {
      showError(e.message || 'Import failed');
    } finally {
      setImportingIntel(false);
    }
  };

  const handleUseAsInspiration = (ad) => {
    localStorage.setItem('pendingResearchInspiration', JSON.stringify({
      headline: ad.headline,
      body: ad.ad_copy,
      advertiser: ad.brand_name,
      cta: ad.cta_text,
      mediaUrl: ad.media_url,
      mediaType: ad.media_type,
      videoUrls: ad.video_urls || [],
      thumbnailUrl: ad.thumbnail_url,
      destinationDomain: ad.destination_domain,
      volumeScore: ad.volume_score,
      rankPosition: ad.rank_position,
      isMultipleVersions: ad.is_multiple_versions,
      creativeIntel: ad.creative_intel,
      adLink: ad.ad_link,
      scrapedAdId: ad.id,
      vertical: currentVerticalLabel,
      angle: ad.angle_tag,
      source: 'research',
    }));
    navigate('/ad-remix');
  };

  const handleBlockPage = async (ad) => {
    const pageName = ad.brand_name || '';
    if (!pageName) {
      showInfo('Page already blocked');
      return;
    }

    try {
      const res = await authFetch(
        `${API_URL}/research/blacklist?page_name=${encodeURIComponent(pageName)}&reason=user_blocked`,
        { method: 'POST' },
      );
      if (!res.ok) {
        showInfo('Page already blocked');
        return;
      }
      setBrowseAds(prev => prev.filter(a => a.brand_name !== pageName));
      showSuccess(`${pageName} blocked — won't appear again`);
    } catch (e) {
      showInfo('Page already blocked');
    }
  };

  // ── Derived ───────────────────────────────────────────────────
  const angleTags = verticalConfig?.angle_tags || [];
  const config = verticalConfig?.verticals || {};
  const subVerticals = config['home_services']?.sub_verticals || {};

  const currentVerticalLabel = useMemo(() => {
    if (activeVertical === 'home_services' && activeSubVertical) {
      return subVerticals[activeSubVertical]?.label || 'Home Services';
    }
    return config[activeVertical]?.label || activeVertical;
  }, [activeVertical, activeSubVertical, config, subVerticals]);

  // ── Render ────────────────────────────────────────────────────
  return (
    <div className="max-w-7xl mx-auto space-y-5">
      {/* Page header */}
      <div className="flex items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-2">
            <FlaskConical size={24} className="text-indigo-600" />
            Research Library
          </h1>
          <p className="text-sm text-gray-500 mt-0.5">Study what's working in your markets before you write.</p>
        </div>
        <div className="flex flex-col items-end gap-1">
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setShowImportModal(true)}
              disabled={refreshing || clearing}
              className="flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium text-indigo-700 border border-indigo-200 bg-indigo-50 hover:bg-indigo-100 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              title="Import Chrome-captured Ad Library examples"
            >
              <Upload size={14} />
              Import Intel
            </button>
            <button
              type="button"
              onClick={() => setShowClearModal(true)}
              disabled={clearing || refreshing}
              className="flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium text-red-600 border border-red-200 hover:bg-red-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              title="Delete all unsaved ads for this vertical"
            >
              <Trash2 size={14} />
              {clearing ? 'Clearing…' : 'Clear Ads'}
            </button>
            <button
              type="button"
              onClick={handleRefresh}
              disabled={refreshing || clearing}
              className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium text-white bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              <RefreshCw size={15} className={refreshing ? 'animate-spin' : ''} />
              {refreshing ? 'Refreshing…' : 'Refresh Vertical'}
            </button>
          </div>
          {refreshing && (
            <p className="text-xs text-gray-400">Pulling ads from Facebook — may take up to 60s</p>
          )}
        </div>
      </div>

      {/* Chrome import tutorial */}
      <div className="bg-white border border-indigo-100 rounded-xl p-4">
        <div className="flex items-start gap-3">
          <div className="w-9 h-9 rounded-lg bg-indigo-50 flex items-center justify-center flex-shrink-0">
            <BookOpen size={18} className="text-indigo-600" />
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <h2 className="text-sm font-semibold text-gray-900">Ad Library Intel workflow</h2>
              <span className="text-xs px-2 py-0.5 rounded-full bg-green-50 text-green-700 border border-green-100">Prototype</span>
            </div>
            <p className="text-sm text-gray-600 mt-1">
              For auto insurance, use Chrome instead of the weak API path: search <strong>cheap auto insurance</strong> or <strong>auto insurance</strong>,
              set United States, active ads, and sort by most impressions. Import the capture, then save the best examples for the video agent.
            </p>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mt-3">
              <div className="flex items-center gap-2 text-xs text-gray-600">
                <BarChart3 size={14} className="text-indigo-500" />
                Volume score is directional, not spend truth
              </div>
              <div className="flex items-center gap-2 text-xs text-gray-600">
                <Video size={14} className="text-indigo-500" />
                Video URLs are inspiration-only and may expire
              </div>
              <div className="flex items-center gap-2 text-xs text-gray-600">
                <Zap size={14} className="text-indigo-500" />
                Build from this ad sends the angle to Ad Remix
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Vertical tabs */}
      <div className="flex items-center gap-1 border-b border-gray-200 pb-0">
        {['commercial_insurance', 'auto_insurance'].map(vid => (
          <button
            key={vid}
            type="button"
            onClick={() => { setActiveVertical(vid); setActiveSubVertical(null); }}
            className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors whitespace-nowrap -mb-px ${
              activeVertical === vid
                ? 'border-indigo-600 text-indigo-600'
                : 'border-transparent text-gray-500 hover:text-gray-800'
            }`}
          >
            {config[vid]?.label || vid}
          </button>
        ))}

        {/* Home Services dropdown */}
        <div ref={homeServicesRef} className="relative -mb-px">
          <button
            type="button"
            onClick={() => setHomeServicesOpen(v => !v)}
            className={`inline-flex items-center gap-1 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors whitespace-nowrap ${
              activeVertical === 'home_services'
                ? 'border-indigo-600 text-indigo-600'
                : 'border-transparent text-gray-500 hover:text-gray-800'
            }`}
          >
            Home Services
            <ChevronDown size={14} className={`transition-transform ${homeServicesOpen ? 'rotate-180' : ''}`} />
          </button>
          {homeServicesOpen && (
            <div className="absolute left-0 top-full mt-1 z-20 bg-white border border-gray-200 rounded-xl shadow-lg py-1.5 min-w-[200px]">
              <button
                type="button"
                onClick={() => {
                  setActiveVertical('home_services');
                  setActiveSubVertical(null);
                  setHomeServicesOpen(false);
                }}
                className={`w-full text-left px-4 py-2 text-sm hover:bg-gray-50 ${activeVertical === 'home_services' && !activeSubVertical ? 'font-semibold text-indigo-600' : 'text-gray-700'}`}
              >
                All Home Services
              </button>
              <div className="h-px bg-gray-100 mx-3 my-1" />
              {Object.entries(subVerticals).map(([key, sv]) => (
                <button
                  key={key}
                  type="button"
                  onClick={() => {
                    setActiveVertical('home_services');
                    setActiveSubVertical(key);
                    setHomeServicesOpen(false);
                  }}
                  className={`w-full text-left px-4 py-2 text-sm hover:bg-gray-50 ${activeSubVertical === key ? 'font-semibold text-indigo-600' : 'text-gray-700'}`}
                >
                  {sv.label}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Two-column layout */}
      <div className="flex gap-5 items-start">
        {/* Browse panel — 70% */}
        <div className="flex-[7] min-w-0 space-y-4">
          {/* Filter bar */}
          <div className="bg-white rounded-xl border border-gray-200 px-4 py-3 flex items-center gap-4 flex-wrap">
            <div className="flex items-center gap-2 flex-1 min-w-0">
              <span className="text-xs font-medium text-gray-500 whitespace-nowrap">
                BROWSE
                {!browseLoading && <span className="ml-1 text-gray-400">({browseAds.length})</span>}
              </span>
              <div className="h-4 w-px bg-gray-200" />

              {/* Angle filter */}
              <select
                value={angleFilter}
                onChange={e => setAngleFilter(e.target.value)}
                className="text-xs border-0 text-gray-600 bg-transparent focus:ring-0 cursor-pointer pr-6 py-0"
              >
                <option value="">All angles</option>
                {angleTags.map(t => (
                  <option key={t.value} value={t.value}>{t.label}</option>
                ))}
              </select>

              <div className="h-4 w-px bg-gray-200" />

              {/* Active only */}
              <label className="flex items-center gap-1.5 cursor-pointer text-xs text-gray-600 whitespace-nowrap">
                <input
                  type="checkbox"
                  checked={activeOnly}
                  onChange={e => setActiveOnly(e.target.checked)}
                  className="rounded text-indigo-600 focus:ring-indigo-500"
                />
                Active only
              </label>
            </div>

            {/* Advertiser search */}
            <input
              type="text"
              value={advertiserFilter}
              onChange={e => setAdvertiserFilter(e.target.value)}
              placeholder="Filter by advertiser…"
              className="text-xs border border-gray-200 rounded-lg px-3 py-1.5 focus:ring-2 focus:ring-indigo-400 focus:border-transparent w-44"
            />
          </div>

          {/* Card gallery */}
          {browseLoading ? (
            <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4">
              {[1,2,3,4,5,6].map(i => <SkeletonCard key={i} />)}
            </div>
          ) : browseError ? (
            <div className="bg-white rounded-xl border border-red-100 px-6 py-16 text-center">
              <p className="text-red-600 font-medium mb-1">Couldn’t load ads for {currentVerticalLabel}</p>
              <p className="text-sm text-gray-400 mb-4">{browseError}</p>
              <button
                type="button"
                onClick={loadBrowseAds}
                className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium text-red-600 border border-red-200 hover:bg-red-50 transition-colors"
              >
                <RefreshCw size={14} />
                Try again
              </button>
            </div>
          ) : browseAds.length === 0 ? (
            <div className="bg-white rounded-xl border border-gray-200 px-6 py-16 text-center">
              <p className="text-gray-500 font-medium mb-1">No ads yet for {currentVerticalLabel}</p>
              <p className="text-sm text-gray-400 mb-4">
                {refreshSummary
                  ? `${refreshSummary.keywords_run || 0} keywords checked. ${refreshSummary.total_duplicate || 0} duplicates seen, no new ads kept.`
                  : <>Click <strong>Refresh Vertical</strong> to pull competitor ads from the Facebook Ad Library.</>}
              </p>
              <button
                type="button"
                onClick={handleRefresh}
                disabled={refreshing}
                className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium text-white bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 transition-colors"
              >
                <RefreshCw size={14} className={refreshing ? 'animate-spin' : ''} />
                {refreshing ? 'Refreshing…' : 'Pull Ads Now'}
              </button>
            </div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4">
              {browseAds.map(ad => (
                <AdCard
                  key={ad.id}
                  ad={ad}
                  isSaved={savedAdIds.has(ad.id)}
                  onSave={handleSave}
                  onUnsave={handleUnsave}
                  onUseAsInspiration={handleUseAsInspiration}
                  onBlockPage={handleBlockPage}
                  angleTags={angleTags}
                />
              ))}
            </div>
          )}
        </div>

        {/* Saved panel — 30% */}
        <div className="flex-[3] min-w-0 space-y-3 sticky top-6">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
              SAVED
              <span className="ml-1 font-normal text-gray-400">({savedAds.length})</span>
            </span>
            <span className="text-xs text-gray-400">All verticals</span>
          </div>

          {savedAds.length === 0 ? (
            <div className="bg-white rounded-xl border border-dashed border-gray-200 px-4 py-8 text-center">
              <Star size={20} className="mx-auto text-gray-300 mb-2" />
              <p className="text-xs text-gray-400 leading-relaxed">
                Save competitor ads you want to reference. They'll appear here for quick inspiration.
              </p>
            </div>
          ) : (
            <div className="space-y-2 max-h-[calc(100vh-220px)] overflow-y-auto pr-1">
              {savedAds.map(ad => (
                <SavedCard
                  key={ad.id}
                  ad={ad}
                  onUnsave={handleUnsave}
                  onUseAsInspiration={handleUseAsInspiration}
                />
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Clear Ads confirmation modal */}
      {showClearModal && (
        <div className="fixed inset-0 bg-black/50 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-white rounded-xl shadow-xl max-w-md w-full p-6">
            <h3 className="text-lg font-semibold text-gray-900 mb-2">Clear all unsaved ads?</h3>
            <p className="text-sm text-gray-600 mb-6">
              {activeVertical === 'home_services' ? (
                <>This removes all non-saved ads across <strong>all Home Services sub-verticals</strong>.
                Use this after tightening keyword filters to remove irrelevant ads pulled by old searches.
                Your <strong>saved ads are kept</strong>.</>
              ) : (
                <>This removes all non-saved ads for the <strong>{activeVertical.replace(/_/g, ' ')}</strong> vertical.
                Use this after tightening keyword filters to remove irrelevant ads pulled by old searches.
                Your <strong>saved ads are kept</strong>.</>
              )}
            </p>
            <div className="flex gap-3 justify-end">
              <button
                type="button"
                onClick={() => setShowClearModal(false)}
                className="px-4 py-2 text-sm font-medium text-gray-700 border border-gray-300 rounded-lg hover:bg-gray-50"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleClear}
                className="px-4 py-2 text-sm font-medium text-white bg-red-600 hover:bg-red-700 rounded-lg"
              >
                Clear Ads
              </button>
            </div>
          </div>
        </div>
      )}

      <AdLibraryImportModal
        open={showImportModal}
        onClose={() => setShowImportModal(false)}
        onImport={handleImportIntel}
        importing={importingIntel}
        defaultQuery={activeVertical === 'auto_insurance' ? 'cheap auto insurance' : currentVerticalLabel}
      />
    </div>
  );
}
