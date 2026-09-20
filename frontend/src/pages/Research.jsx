import React, { useState, useEffect, useRef, useMemo } from 'react';
import { Ban, FlaskConical, RefreshCw, Star, ExternalLink, ChevronDown, Trash2, Zap, X, Upload, BookOpen, Video, BarChart3 } from 'lucide-react';
import { NavLink, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { useToast } from '../context/ToastContext';
import {
  addResearchBoardItem,
  createResearchBoard,
  deleteResearchBoard,
  deleteResearchBoardItem,
  getResearchBoardItems,
  getResearchBoards,
  searchAndSave,
} from '../api/research';

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

const QUERY_PRESETS = [
  'Auto insurance — cheap quote',
  'Commercial insurance — niche/industry',
  'Reverse mortgage — homeowner benefit',
];

const normalizeAdLibraryDate = (value) => {
  if (!value) return '';
  if (/^\d{4}-\d{2}-\d{2}/.test(value)) return value;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toISOString().slice(0, 10);
};

const sortResearchAds = (ads, sortBy) => {
  const sorted = [...ads];
  const dateValue = (value) => {
    if (!value) return null;
    const timestamp = new Date(value).getTime();
    return Number.isFinite(timestamp) ? timestamp : null;
  };
  sorted.sort((a, b) => {
    if (sortBy === 'longest_running') {
      const av = dateValue(a.start_date);
      const bv = dateValue(b.start_date);
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      return av - bv;
    }
    if (sortBy === 'most_sightings') {
      return (b.seen_count || 0) - (a.seen_count || 0);
    }
    if (sortBy === 'multiple_versions') {
      const versionOrder = Number(Boolean(b.is_multiple_versions)) - Number(Boolean(a.is_multiple_versions));
      if (versionOrder !== 0) return versionOrder;
      const av = dateValue(a.last_seen);
      const bv = dateValue(b.last_seen);
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      return bv - av;
    }
    const av = dateValue(a.last_seen);
    const bv = dateValue(b.last_seen);
    if (av == null && bv == null) return 0;
    if (av == null) return 1;
    if (bv == null) return -1;
    return bv - av;
  });
  return sorted;
};

const withDerivedResearchStatus = (ad) => {
  const lastSeen = ad.last_seen ? new Date(ad.last_seen).getTime() : NaN;
  const isActive = Number.isFinite(lastSeen) && (Date.now() - lastSeen) <= 30 * 24 * 60 * 60 * 1000;
  return { ...ad, is_active: ad.is_active ?? isActive };
};

const isUnknownMedia = (mediaType) => !['image', 'video', 'carousel'].includes((mediaType || '').toLowerCase());

const filterResearchAds = (ads, { angleFilter, mediaTypeFilter, advertiserFilter, activeOnly, sortBy }) => {
  const advertiser = advertiserFilter.trim().toLowerCase();
  return sortResearchAds(ads.filter(ad => (
    (!angleFilter || ad.angle_tag === angleFilter) &&
    (!mediaTypeFilter || (mediaTypeFilter === 'unknown' ? isUnknownMedia(ad.media_type) : ad.media_type === mediaTypeFilter)) &&
    (!advertiser || (ad.brand_name || '').toLowerCase().includes(advertiser)) &&
    (!activeOnly || withDerivedResearchStatus(ad).is_active)
  )), sortBy);
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
          platforms: ad.platforms || null,
          start_date: normalizeAdLibraryDate(ad.started_running || ad.start_date || ''),
          media_type: ad.media_type || (adVideos.length ? 'video' : null),
          media_url: ad.media_url || ad.thumbnail_url || '',
          destination_domain: ad.domain || ad.destination_domain || '',
          rank_position: ad.rank_position ?? null,
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
function BoardSaveButton({ ad, boards, onAdd, onCreate }) {
  const [open, setOpen] = useState(false);
  const [newBoardName, setNewBoardName] = useState('');
  const [creating, setCreating] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    if (!open) return;
    const handler = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open]);

  const handleCreate = async () => {
    if (!newBoardName.trim() || creating) return;
    setCreating(true);
    try {
      await onCreate(newBoardName.trim(), ad);
      setNewBoardName('');
      setOpen(false);
    } finally {
      setCreating(false);
    }
  };

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen(v => !v)}
        className="w-full inline-flex items-center justify-center gap-1 px-2 py-1.5 rounded-lg border border-indigo-200 bg-indigo-50 text-indigo-700 text-xs font-medium hover:bg-indigo-100 transition-colors"
        aria-expanded={open}
      >
        <Star size={11} />
        Save to board
        <ChevronDown size={10} />
      </button>
      {open && (
        <div className="absolute left-0 right-0 bottom-9 z-20 bg-white border border-gray-200 rounded-xl shadow-lg p-2 min-w-[210px]">
          <p className="text-xs text-gray-400 px-2 py-1 mb-1">Choose a shared board</p>
          {boards.map(board => (
            <button
              key={board.id}
              type="button"
              onClick={async () => { await onAdd(board.id, ad); setOpen(false); }}
              className="w-full flex items-center justify-between gap-2 text-left px-2 py-1.5 text-xs text-gray-700 hover:bg-gray-50 rounded-lg"
            >
              <span className="truncate">{board.name}</span>
              <span className="text-gray-400">{board.item_count}</span>
            </button>
          ))}
          <div className="border-t border-gray-100 mt-2 pt-2">
            <p className="text-xs text-gray-400 px-2 mb-1">New board</p>
            <div className="flex gap-1">
              <input
                type="text"
                value={newBoardName}
                onChange={e => setNewBoardName(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter') handleCreate(); }}
                placeholder="Board name"
                className="min-w-0 flex-1 rounded-md border border-gray-200 px-2 py-1.5 text-xs focus:ring-1 focus:ring-indigo-400"
              />
              <button
                type="button"
                onClick={handleCreate}
                disabled={creating || !newBoardName.trim()}
                className="rounded-md bg-indigo-600 px-2 py-1.5 text-xs font-medium text-white disabled:opacity-50"
              >
                {creating ? '…' : 'Add'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function AdCard({ ad, isSaved, onSave, onUnsave, onUseAsInspiration, onBlockPage, angleTags, boards, onAddToBoard, onCreateBoard, onRemoveFromBoard }) {
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
          {ad.is_active ? 'RECENT CAPTURE' : 'NOT RECENTLY CAPTURED'}
        </span>
        {ad.media_type === 'video' && (
          <span className="inline-flex items-center gap-1 text-xs font-medium text-purple-600">
            <Video size={11} />
            VIDEO
          </span>
        )}
        {isUnknownMedia(ad.media_type) && (
          <span className="text-xs font-medium text-gray-400" title="The source did not provide a supported media format">UNKNOWN FORMAT</span>
        )}
        {['image', 'carousel'].includes((ad.media_type || '').toLowerCase()) && (
          <span className="text-xs font-medium text-gray-400">{ad.media_type.toUpperCase()}</span>
        )}
        {Array.isArray(ad.platforms) && ad.platforms.length > 0 && (
          <span className="text-xs text-gray-400" title="Platforms reported by the Ad Library capture">
            {ad.platforms.join(' · ')}
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
          <span className="inline-flex items-center gap-1 text-xs font-semibold text-indigo-600 bg-indigo-50 border border-indigo-100 rounded px-2 py-0.5" title="Directional capture signal based on rank, age, repeat versions, and media presence—not spend or impressions.">
            <BarChart3 size={11} />
            Signal {ad.volume_score}
          </span>
        )}
        {ad.rank_position != null && (
          <span className="text-xs text-gray-400" title="Position in the imported Ad Library capture, not a performance ranking">Capture rank #{ad.rank_position}</span>
        )}
        {ad.is_multiple_versions && (
          <span className="text-xs text-gray-400">Multiple versions</span>
        )}
        {ad.running_days != null && (
          <span className="text-xs text-gray-400" title="Calculated from the source-provided start date; not confirmation of current delivery">Observed {ad.running_days}d</span>
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
        <BoardSaveButton ad={ad} boards={boards} onAdd={onAddToBoard} onCreate={onCreateBoard} />
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
          {onRemoveFromBoard && (
            <button
              type="button"
              onClick={() => onRemoveFromBoard(ad)}
              className="inline-flex items-center justify-center gap-1 px-2 py-1 rounded-md border border-gray-200 text-xs font-medium text-gray-500 hover:text-red-500 hover:border-red-200 transition-colors"
            >
              <X size={11} />
              Remove
            </button>
          )}
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
function SavedCard({ ad, onUnsave, onUseAsInspiration, boards, onAddToBoard, onCreateBoard, onNotesSaved }) {
  const [editingNotes, setEditingNotes] = useState(false);
  const [notes, setNotes] = useState({ hook_type: ad.hook_type || '', persona: ad.persona || '', promise: ad.promise || '', proof_type: ad.proof_type || '', funnel_stage: ad.funnel_stage || '', pacing: ad.pacing || '', numbers_used: ad.numbers_used || '' });
  const [savingNotes, setSavingNotes] = useState(false);
  const { showSuccess, showError } = useToast();
  // authFetch is a hook value (useAuth()), not a module-level import — every
  // other call site in this file is inside the main Research() component,
  // where it's already destructured (search "const { authFetch } = useAuth()"
  // below). SavedCard is a separate component and never had it in scope,
  // so clicking "Save notes" threw "authFetch is not defined" at runtime —
  // missed by static review since the diff itself compiles fine; caught by
  // actually clicking it live in production.
  const { authFetch } = useAuth();
  const saveNotes = async () => {
    setSavingNotes(true);
    try {
      const res = await authFetch(`${API_URL}/research/scraped-ads/${ad.id}/strategy-notes`, {
        method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(notes),
      });
      if (!res.ok) { const body = await res.json().catch(() => ({})); throw new Error(body.detail || 'Failed to save strategy notes'); }
      // Update via the parent's state setter, not a direct prop mutation —
      // `ad` here and the `browseAds` copy of the same underlying row are
      // separate object instances from separate fetches. Mutating `ad` in
      // place only updated this card's own render; clicking "Build from
      // this ad" on the Browse panel's copy of the same ad afterward would
      // silently carry stale (pre-edit) strategy fields into the AI prompt
      // (code-auditor pre-push review, MEDIUM).
      onNotesSaved(ad.id, notes);
      setEditingNotes(false);
      showSuccess('Strategy notes saved');
    } catch (error) { showError(error.message); } finally { setSavingNotes(false); }
  };
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
        {ad.funnel_stage && <span className="rounded bg-violet-50 px-1.5 py-0.5 text-xs font-semibold text-violet-700">{ad.funnel_stage}</span>}
        {ad.media_type === 'video' && (
          <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-xs font-semibold bg-purple-50 text-purple-600">
            <Video size={10} />
            Video
          </span>
        )}
        {isUnknownMedia(ad.media_type) && (
          <span className="rounded bg-gray-100 px-1.5 py-0.5 text-xs font-semibold text-gray-500" title="The source did not provide a supported media format">Unknown format</span>
        )}
        {['image', 'carousel'].includes((ad.media_type || '').toLowerCase()) && (
          <span className="rounded bg-gray-100 px-1.5 py-0.5 text-xs font-semibold text-gray-500">{ad.media_type}</span>
        )}
        {ad.volume_score != null && (
          <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-xs font-semibold bg-indigo-50 text-indigo-600" title="Directional capture signal—not spend or impressions.">
            <BarChart3 size={10} />
            Signal {ad.volume_score}
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
      <button type="button" onClick={() => setEditingNotes(value => !value)} className="text-left text-xs font-medium text-indigo-500 hover:text-indigo-700">
        {editingNotes ? 'Hide strategy notes' : 'Add strategy notes'}
      </button>
      {editingNotes && (
        <div className="space-y-2 rounded-lg border border-indigo-100 bg-indigo-50/40 p-2">
          {[
            ['hook_type', 'Hook type'], ['persona', 'Persona'], ['proof_type', 'Proof type'], ['funnel_stage', 'Funnel stage'], ['pacing', 'Pacing'], ['numbers_used', 'Numbers/$ used'],
          ].map(([key, label]) => (
            <input key={key} value={notes[key]} onChange={event => setNotes(prev => ({ ...prev, [key]: event.target.value }))} placeholder={label} className="w-full rounded border border-gray-200 bg-white px-2 py-1.5 text-xs focus:border-indigo-400 focus:outline-none" />
          ))}
          {/* Textarea, not a single-line input — `promise` is a Text column
              meant for a real sentence, not a short label like the other
              four fields (joel-perspective pre-push review, P2: a cramped
              one-line box discouraged actually writing anything useful here). */}
          <textarea
            value={notes.promise}
            onChange={event => setNotes(prev => ({ ...prev, promise: event.target.value }))}
            placeholder="Promise"
            rows={2}
            className="w-full rounded border border-gray-200 bg-white px-2 py-1.5 text-xs focus:border-indigo-400 focus:outline-none resize-y"
          />
          <button type="button" onClick={saveNotes} disabled={savingNotes} className="rounded bg-indigo-600 px-2.5 py-1.5 text-xs font-medium text-white disabled:opacity-50">{savingNotes ? 'Saving…' : 'Save notes'}</button>
        </div>
      )}
      <BoardSaveButton ad={ad} boards={boards} onAdd={onAddToBoard} onCreate={onCreateBoard} />
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
  const [query, setQuery] = useState('');
  const [queryLoading, setQueryLoading] = useState(false);
  const [boards, setBoards] = useState([]);
  const [activeBoardId, setActiveBoardId] = useState(null);
  const [boardAds, setBoardAds] = useState([]);
  const [boardsLoading, setBoardsLoading] = useState(false);
  const [newBoardName, setNewBoardName] = useState('');
  const [creatingBoard, setCreatingBoard] = useState(false);
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
  const [mediaTypeFilter, setMediaTypeFilter] = useState('');
  const [sortBy, setSortBy] = useState('newest_seen');
  const [activeOnly, setActiveOnly] = useState(false);
  const [advertiserFilter, setAdvertiserFilter] = useState('');
  const [resultMode, setResultMode] = useState('browse');
  const [searchResultAds, setSearchResultAds] = useState([]);
  const [browseReloadKey, setBrowseReloadKey] = useState(0);
  const browseRequestRef = useRef(0);
  const searchRequestRef = useRef(0);
  const refreshRequestRef = useRef(0);
  const contextGenerationRef = useRef(0);
  const activeVerticalRef = useRef(activeVertical);
  const activeSubVerticalRef = useRef(activeSubVertical);

  // ── Boot ─────────────────────────────────────────────────────
  useEffect(() => {
    contextGenerationRef.current += 1;
    activeVerticalRef.current = activeVertical;
    activeSubVerticalRef.current = activeSubVertical;
    setQueryLoading(false);
  }, [activeVertical, activeSubVertical]);

  useEffect(() => {
    loadConfig();
    loadBoards();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (activeBoardId) {
      loadBoardItems(activeBoardId);
    } else {
      setBoardAds([]);
    }
  }, [activeBoardId]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!verticalConfig) return;
    setRefreshSummary(null);
    setResultMode('browse');
    setSearchResultAds([]);
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
    const requestId = ++browseRequestRef.current;
    setBrowseLoading(true);
    setBrowseError('');
    setBrowseAds([]);
    try {
      const params = new URLSearchParams();
      if (activeSubVertical) params.set('sub_vertical', activeSubVertical);
      if (angleFilter) params.set('angle_tag', angleFilter);
      if (mediaTypeFilter) params.set('media_type', mediaTypeFilter);
      if (activeOnly) params.set('active_only', 'true');
      if (advertiserFilter.trim()) params.set('advertiser', advertiserFilter.trim());
      params.set('sort_by', sortBy);
      params.set('limit', '500');

      const res = await authFetch(`${API_URL}/research/config-verticals/${activeVertical}/browse-ads?${params}`);
      if (!res.ok) throw new Error('Failed to load ads');
      const ads = await res.json();
      if (requestId === browseRequestRef.current) setBrowseAds(ads.map(withDerivedResearchStatus));
    } catch (e) {
      if (requestId === browseRequestRef.current) setBrowseError(e.message || 'Failed to load ads');
    } finally {
      if (requestId === browseRequestRef.current) setBrowseLoading(false);
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

  // Updates the SAME underlying ad's strategy-note fields wherever it
  // currently sits in local state — savedAds and browseAds are populated by
  // two separate fetches and hold separate object instances for the same
  // scraped_ads row, so a card in one array being edited must not leave the
  // other array's copy stale (code-auditor pre-push review, MEDIUM — a stale
  // browseAds copy silently carried old strategy fields into the AI prompt
  // via "Build from this ad" until the next full reload).
  const handleStrategyNotesSaved = (adId, notes) => {
    setSavedAds(prev => prev.map(a => (a.id === adId ? { ...a, ...notes } : a)));
    setBrowseAds(prev => prev.map(a => (a.id === adId ? { ...a, ...notes } : a)));
  };

  const loadBoards = async () => {
    setBoardsLoading(true);
    try {
      const result = await getResearchBoards();
      setBoards(result);
    } catch (e) {
      showError(e.message || 'Failed to load research boards');
    } finally {
      setBoardsLoading(false);
    }
  };

  const loadBoardItems = async (boardId) => {
    try {
      setBoardAds(await getResearchBoardItems(boardId));
    } catch (e) {
      showError(e.message || 'Failed to load board ads');
      setBoardAds([]);
    }
  };

  const handleCreateBoard = async (name = newBoardName, firstAd = null) => {
    const trimmedName = name.trim();
    if (!trimmedName || creatingBoard) return null;
    setCreatingBoard(true);
    try {
      const board = await createResearchBoard(trimmedName, activeVertical);
      setBoards(prev => [board, ...prev]);
      setNewBoardName('');
      setActiveBoardId(board.id);
      if (firstAd) {
        // Use the server's response, not the raw `firstAd` object — it's the
        // only place `board_item_id` actually gets set (see the comment on
        // handleAddToBoard below for why that matters). Using `firstAd`
        // directly here left the board's only item permanently un-removable
        // until a reload (code-auditor pre-push review, HIGH).
        const savedItem = await addResearchBoardItem(board.id, firstAd.id);
        setBoardAds([savedItem]);
        setBoards(prev => prev.map(item => item.id === board.id ? { ...item, item_count: 1 } : item));
      }
      showSuccess(`Board “${board.name}” created`);
      return board;
    } catch (e) {
      showError(e.message || 'Failed to create research board');
      return null;
    } finally {
      setCreatingBoard(false);
    }
  };

  const handleAddToBoard = async (boardId, ad) => {
    try {
      // `ad` here is a browse/saved-ad object with no `board_item_id` — that
      // field only exists on the response from this call (or from
      // getResearchBoardItems). Optimistically inserting the raw `ad` left
      // "Remove" a silent no-op on it until the board was reloaded
      // (code-auditor pre-push review, HIGH) — use the server's response
      // instead, same fix as handleCreateBoard's firstAd path above.
      const savedItem = await addResearchBoardItem(boardId, ad.id);
      if (activeBoardId === boardId && !boardAds.some(item => item.id === ad.id)) {
        setBoardAds(prev => [savedItem, ...prev]);
      }
      loadBoards();
      showSuccess('Ad added to board');
    } catch (e) {
      showError(e.message || 'Failed to add ad to board');
    }
  };

  const handleRemoveFromBoard = async (item) => {
    if (!activeBoardId || !item.board_item_id) return;
    try {
      await deleteResearchBoardItem(activeBoardId, item.board_item_id);
      setBoardAds(prev => prev.filter(ad => ad.id !== item.id));
      setBoards(prev => prev.map(board => board.id === activeBoardId ? { ...board, item_count: Math.max(0, (board.item_count || 0) - 1) } : board));
    } catch (e) {
      showError(e.message || 'Failed to remove ad from board');
    }
  };

  const handleDeleteBoard = async (board) => {
    try {
      await deleteResearchBoard(board.id);
      setBoards(prev => prev.filter(item => item.id !== board.id));
      if (activeBoardId === board.id) setActiveBoardId(null);
      showSuccess(`Board “${board.name}” deleted`);
    } catch (e) {
      showError(e.message || 'Failed to delete research board');
    }
  };

  const handleQuerySearch = async (event) => {
    event.preventDefault();
    const trimmedQuery = query.trim();
    if (!trimmedQuery || queryLoading || refreshing || clearing) return;
    const requestId = ++searchRequestRef.current;
    const searchVertical = activeVertical;
    const searchSubVertical = activeSubVertical;
    const searchContextGeneration = contextGenerationRef.current;
    setQueryLoading(true);
    setResultMode('search');
    setBrowseAds([]);
    setBrowseLoading(false);
    setBrowseError('');
    setRefreshSummary(null);
    try {
      // Uses the shared searchAndSave() helper (frontend/src/api/research.js)
      // rather than a second hand-built fetch call against the same endpoint
      // — the two had already started drifting in header/error-shape
      // handling (code-auditor pre-push review, LOW).
      const result = await searchAndSave({ query: trimmedQuery, platform: 'facebook', limit: 30, country: 'US', search_type: 'one_time' });
      if (
        requestId !== searchRequestRef.current
        || searchVertical !== activeVerticalRef.current
        || searchSubVertical !== activeSubVerticalRef.current
        || searchContextGeneration !== contextGenerationRef.current
      ) return;
      const normalized = (result.ads || []).map(withDerivedResearchStatus);
      browseRequestRef.current += 1;
      setBrowseError('');
      setSearchResultAds(normalized);
      setResultMode('search');
      const filtered = filterResearchAds(normalized, { angleFilter, mediaTypeFilter, advertiserFilter, activeOnly, sortBy });
      setBrowseAds(filtered);
      showSuccess(`Search saved — ${filtered.length} matching ads shown`);
      loadBoards();
      loadSavedAds();
    } catch (e) {
      if (requestId === searchRequestRef.current && searchVertical === activeVerticalRef.current && searchSubVertical === activeSubVerticalRef.current && searchContextGeneration === contextGenerationRef.current) {
        setBrowseError(e.message || 'Search failed');
        showError(e.message || 'Search failed');
      }
    } finally {
      if (requestId === searchRequestRef.current) setQueryLoading(false);
    }
  };

  // Re-run browse when filters change (with debounce on advertiser text)
  useEffect(() => {
    if (!verticalConfig) return;
    if (resultMode === 'search') {
      setBrowseAds(filterResearchAds(searchResultAds, { angleFilter, mediaTypeFilter, advertiserFilter, activeOnly, sortBy }));
      return undefined;
    }
    const t = setTimeout(() => loadBrowseAds(), advertiserFilter ? 400 : 0);
    return () => clearTimeout(t);
  }, [angleFilter, mediaTypeFilter, sortBy, activeOnly, advertiserFilter, resultMode, searchResultAds, browseReloadKey]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Actions ──────────────────────────────────────────────────
  const handleRefresh = async ({ allowWhileClearing = false } = {}) => {
    if (queryLoading || (clearing && !allowWhileClearing)) {
      showWarning('Finish the current Search or Clear operation before refreshing.');
      return;
    }
    const requestId = ++refreshRequestRef.current;
    const refreshVertical = activeVertical;
    const refreshSubVertical = activeSubVertical;
    const refreshContextGeneration = contextGenerationRef.current;
    setResultMode('browse');
    setSearchResultAds([]);
    searchRequestRef.current += 1;
    setQueryLoading(false);
    setRefreshSummary(null);
    setBrowseError('');
    setBrowseLoading(false);
    browseRequestRef.current += 1;
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
      if (requestId !== refreshRequestRef.current || refreshVertical !== activeVerticalRef.current || refreshSubVertical !== activeSubVerticalRef.current || refreshContextGeneration !== contextGenerationRef.current) return;
      setRefreshSummary(result);
      if (result.rate_limited) {
        showInfo(`Refresh stopped at the research rate limit after ${result.keywords_run} keywords. ${result.total_new} new ads were saved; retry after the limit resets.`);
        setBrowseReloadKey(value => value + 1);
        loadSavedAds();
      } else if (result.keywords_run === 0 && result.first_error) {
        showError(`Refresh failed — ${result.first_error}`);
      } else if (result.first_error) {
        showInfo(`Refresh partially completed — ${result.keywords_run} keywords checked, ${result.total_new} new ads. First error: ${result.first_error}`);
        setBrowseReloadKey(value => value + 1);
        loadSavedAds();
      } else if (result.total_new === 0) {
        const duplicateText = result.total_duplicate > 0 ? `, ${result.total_duplicate} duplicates seen` : '';
        showInfo(`No new ads — ${result.keywords_run} keywords checked${duplicateText}`);
        setBrowseReloadKey(value => value + 1);
        loadSavedAds();
      } else {
        showSuccess(result.message || `Refresh complete — ${result.total_new} new ads`);
        setBrowseReloadKey(value => value + 1);
        loadSavedAds();
      }
    } catch (e) {
      if (requestId !== refreshRequestRef.current || refreshVertical !== activeVerticalRef.current || refreshSubVertical !== activeSubVerticalRef.current || refreshContextGeneration !== contextGenerationRef.current) return;
      if (e.name === 'AbortError') {
        setRefreshSummary({ status: 'timed_out', keywords_run: 0, total_new: 0, total_duplicate: 0, first_error: 'Request timed out; earlier keywords may have completed and saved results.' });
        setBrowseReloadKey(value => value + 1);
        showError('Refresh timed out — try a single sub-vertical tab instead of pulling all at once.');
      } else {
        setRefreshSummary({ status: 'failed', keywords_run: 0, total_new: 0, total_duplicate: 0, first_error: e.message || 'Refresh failed before completion.' });
        setBrowseError('');
        showError(e.message || 'Refresh failed');
      }
    } finally {
      clearTimeout(timeoutId);
      if (requestId === refreshRequestRef.current) setRefreshing(false);
    }
  };

  const handleClear = async () => {
    if (queryLoading || refreshing) {
      showWarning('Finish the current Search or Refresh operation before clearing ads.');
      return;
    }
    setClearing(true);
    setShowClearModal(false);
    browseRequestRef.current += 1;
    searchRequestRef.current += 1;
    refreshRequestRef.current += 1;
    setQueryLoading(false);
    try {
      const clearParams = activeSubVertical ? `?sub_vertical=${encodeURIComponent(activeSubVertical)}` : '';
      const res = await authFetch(`${API_URL}/research/config-verticals/${activeVertical}/ads${clearParams}`, {
        method: 'DELETE',
      });
      if (!res.ok) throw new Error('Clear failed');
      const result = await res.json();
      setBrowseAds([]);
      setSearchResultAds([]);
      showSuccess(`Cleared ${result.deleted} ads — pulling fresh results now…`);
      await handleRefresh({ allowWhileClearing: true });
    } catch (e) {
      setRefreshSummary({ status: 'clear_failed', keywords_run: 0, total_new: 0, total_duplicate: 0, first_error: 'Clear failed; current ads were not deleted.' });
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
      // authFetch resolves with the Response instead of throwing on an auth
      // failure, so the status has to be checked for the optimistic unsave above
      // to get rolled back.
      const res = await authFetch(`${API_URL}/research/scraped-ads/${ad.id}/save`, { method: 'DELETE' });
      if (!res.ok) throw new Error(`Failed to unsave ad (${res.status})`);
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
      hook_type: ad.hook_type,
      persona: ad.persona,
      promise: ad.promise,
      proof_type: ad.proof_type,
      funnel_stage: ad.funnel_stage,
      pacing: ad.pacing,
      numbers_used: ad.numbers_used,
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
        showError('Could not block advertiser — try again.');
        return;
      }
      const normalizedPageName = pageName.toLowerCase();
      setBrowseAds(prev => prev.filter(a => (a.brand_name || '').toLowerCase() !== normalizedPageName));
      setSearchResultAds(prev => prev.filter(a => (a.brand_name || '').toLowerCase() !== normalizedPageName));
      showSuccess(`${pageName} blocked — won't appear again`);
    } catch (e) {
      showError('Could not block advertiser — try again.');
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

  const visibleSavedAds = activeBoardId ? boardAds : savedAds;

  // ── Render ────────────────────────────────────────────────────
    return (
    <div className="max-w-7xl mx-auto space-y-5">
      <nav className="flex items-center gap-5 border-b border-gray-200" aria-label="Research sections">
        {[
          { label: 'Research', path: '/research' },
          { label: 'Scrape Brand Ads', path: '/research/brand-scrapes' },
          { label: 'Settings', path: '/research/settings' },
        ].map(item => (
          <NavLink
            key={item.path}
            to={item.path}
            end={item.path === '/research'}
            className={({ isActive }) => `border-b-2 px-1 py-2.5 text-sm font-medium -mb-px transition-colors ${
              isActive ? 'border-gray-900 text-gray-900' : 'border-transparent text-gray-500 hover:text-gray-800'
            }`}
          >
            {item.label}
          </NavLink>
        ))}
      </nav>
      {/* Page header */}
      <div className="flex items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-2">
            <FlaskConical size={24} className="text-indigo-600" />
            Research Library
          </h1>
          <p className="text-sm text-gray-500 mt-0.5">Study captured competitor patterns before you write.</p>
        </div>
        <div className="flex flex-col items-end gap-1">
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setShowImportModal(true)}
              disabled={refreshing || clearing || queryLoading}
              className="flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium text-indigo-700 border border-indigo-200 bg-indigo-50 hover:bg-indigo-100 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              title="Import Chrome-captured Ad Library examples"
            >
              <Upload size={14} />
              Import Intel
            </button>
            <button
              type="button"
              onClick={() => setShowClearModal(true)}
              disabled={clearing || refreshing || queryLoading}
              className="flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium text-red-600 border border-red-200 hover:bg-red-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              title="Delete all unsaved ads for this vertical"
            >
              <Trash2 size={14} />
              {clearing ? 'Clearing…' : 'Clear Ads'}
            </button>
            <button
              type="button"
              onClick={handleRefresh}
              disabled={refreshing || clearing || queryLoading}
              className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium text-white bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              <RefreshCw size={15} className={refreshing ? 'animate-spin' : ''} />
              {refreshing ? 'Refreshing…' : 'Refresh Vertical'}
            </button>
          </div>
          {refreshing && (
            <p className="text-xs text-gray-400">Pulling ads from Facebook — may take up to 3 minutes</p>
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
          <form onSubmit={handleQuerySearch} className="bg-white rounded-xl border border-indigo-200 px-4 py-3">
            <div className="flex items-center gap-2">
              <input
                type="search"
                value={query}
                onChange={e => setQuery(e.target.value)}
                placeholder="Search the Ad Library by keyword…"
                className="min-w-0 flex-1 rounded-lg border border-gray-200 px-3 py-2 text-sm focus:border-indigo-400 focus:outline-none focus:ring-2 focus:ring-indigo-300"
                aria-label="Research query"
              />
              <button
                type="submit"
                disabled={queryLoading || refreshing || clearing || !query.trim()}
                className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"
              >
                <RefreshCw size={14} className={queryLoading ? 'animate-spin' : ''} />
                {queryLoading ? 'Searching…' : 'Search'}
              </button>
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-1.5">
              <span className="mr-1 text-xs text-gray-400">Try:</span>
              {QUERY_PRESETS.map(preset => (
                <button
                  key={preset}
                  type="button"
                  onClick={() => setQuery(preset)}
                  className="rounded-full border border-gray-200 px-2.5 py-1 text-xs text-gray-600 hover:border-indigo-300 hover:bg-indigo-50 hover:text-indigo-700"
                >
                  {preset}
                </button>
              ))}
            </div>
            <p className="mt-2 text-[11px] text-gray-400">Keyword Search is global; the selected vertical scopes Browse and Refresh.</p>
          </form>
          {/* Filter bar */}
          <div className="bg-white rounded-xl border border-gray-200 px-4 py-3 flex items-center gap-4 flex-wrap">
            <div className="flex items-center gap-2 flex-1 min-w-0">
              <span className="text-xs font-medium text-gray-500 whitespace-nowrap">
                {resultMode === 'search' ? 'SEARCH RESULTS' : 'BROWSE'}
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

              {/* Media type filter — captured metadata, not classifier output */}
              <select
                value={mediaTypeFilter}
                onChange={e => setMediaTypeFilter(e.target.value)}
                className="text-xs border-0 text-gray-600 bg-transparent focus:ring-0 cursor-pointer pr-6 py-0"
                title="Filter by media type captured from the Ad Library"
              >
                <option value="">All media</option>
                <option value="image">Images</option>
                <option value="video">Videos</option>
                <option value="carousel">Carousels</option>
                <option value="unknown">Unknown format</option>
              </select>

              <div className="h-4 w-px bg-gray-200" />

              <span className="text-xs text-gray-400 whitespace-nowrap" title="These are internal Ad Library capture signals, not spend, reach, or market prevalence.">
                Sort by
              </span>
              <select
                value={sortBy}
                onChange={e => setSortBy(e.target.value)}
                className="text-xs border-0 text-gray-600 bg-transparent focus:ring-0 cursor-pointer pr-6 py-0"
                title="Sort by source-backed research signals"
              >
                <option value="newest_seen">Last captured</option>
                <option value="longest_running">Longest running</option>
                <option value="most_sightings">Captured most often</option>
                <option value="multiple_versions">Multiple versions</option>
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
                  Captured in last 30 days
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

          {refreshSummary?.first_error && (
            <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
              {refreshSummary.status === 'timed_out' ? 'Refresh timed out' : refreshSummary.status === 'failed' ? 'Refresh failed' : refreshSummary.status === 'clear_failed' ? 'Clear failed' : 'Refresh was partial'}: {refreshSummary.first_error} {refreshSummary.status !== 'partial' && 'Showing the last successful capture where available.'}
            </div>
          )}

          {/* Card gallery */}
          {browseLoading ? (
            <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4">
              {[1,2,3,4,5,6].map(i => <SkeletonCard key={i} />)}
            </div>
          ) : browseError ? (
            <div className="bg-white rounded-xl border border-red-100 px-6 py-16 text-center">
              <p className="text-red-600 font-medium mb-1">{resultMode === 'search' ? `Search failed for “${query}”` : `Couldn’t load ads for ${currentVerticalLabel}`}</p>
              <p className="text-sm text-gray-400 mb-4">{browseError}</p>
              <button
                type="button"
                onClick={resultMode === 'search' ? () => document.querySelector('[aria-label="Research query"]')?.focus() : loadBrowseAds}
                className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium text-red-600 border border-red-200 hover:bg-red-50 transition-colors"
              >
                <RefreshCw size={14} />
                {resultMode === 'search' ? 'Edit search' : 'Try again'}
              </button>
            </div>
          ) : browseAds.length === 0 ? (
            <div className="bg-white rounded-xl border border-gray-200 px-6 py-16 text-center">
              <p className="text-gray-500 font-medium mb-1">{resultMode === 'search' ? `No ads found for “${query}”` : `No ads yet for ${currentVerticalLabel}`}</p>
              <p className="text-sm text-gray-400 mb-4">
                {refreshSummary
                  ? `${refreshSummary.keywords_run || 0} keywords checked. ${refreshSummary.total_duplicate || 0} duplicates seen, no new ads kept.${refreshSummary.first_error ? ` Refresh note: ${refreshSummary.first_error}` : ''}`
                  : resultMode === 'search'
                    ? <>Try a broader keyword or edit the global Search above.</>
                    : <>Click <strong>Refresh Vertical</strong> to pull competitor ads from the Facebook Ad Library.</>}
              </p>
              <button
                type="button"
                onClick={resultMode === 'search' ? () => document.querySelector('[aria-label="Research query"]')?.focus() : handleRefresh}
                disabled={refreshing}
                className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium text-white bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 transition-colors"
              >
                <RefreshCw size={14} className={refreshing ? 'animate-spin' : ''} />
                {resultMode === 'search' ? 'Edit search' : refreshing ? 'Refreshing…' : 'Pull Ads Now'}
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
                  boards={boards}
                  onAddToBoard={handleAddToBoard}
                  onCreateBoard={handleCreateBoard}
                />
              ))}
            </div>
          )}
        </div>

        {/* Research boards panel — 30% */}
        <div className="flex-[3] min-w-0 space-y-3 sticky top-6">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
              RESEARCH BOARDS
            </span>
            <span className="text-xs text-gray-400">Shared workspace</span>
          </div>

          <div className="bg-white rounded-xl border border-gray-200 p-3 space-y-1">
            <button
              type="button"
              onClick={() => setActiveBoardId(null)}
              className={`w-full flex items-center justify-between gap-2 rounded-lg px-3 py-2 text-left text-xs ${!activeBoardId ? 'bg-indigo-50 text-indigo-700 font-semibold' : 'text-gray-600 hover:bg-gray-50'}`}
            >
              <span>Saved library</span>
              <span className="text-gray-400">{savedAds.length}</span>
            </button>
            {boardsLoading ? (
              <p className="px-3 py-2 text-xs text-gray-400">Loading boards…</p>
            ) : boards.map(board => (
              <div key={board.id} className="flex items-center gap-1">
                <button
                  type="button"
                  onClick={() => setActiveBoardId(board.id)}
                  className={`min-w-0 flex-1 flex items-center justify-between gap-2 rounded-lg px-3 py-2 text-left text-xs ${activeBoardId === board.id ? 'bg-indigo-50 text-indigo-700 font-semibold' : 'text-gray-600 hover:bg-gray-50'}`}
                >
                  <span className="truncate">{board.name}</span>
                  <span className="text-gray-400">{board.item_count}</span>
                </button>
                <button
                  type="button"
                  onClick={() => handleDeleteBoard(board)}
                  className="rounded p-1 text-gray-300 hover:bg-red-50 hover:text-red-500"
                  aria-label={`Delete ${board.name} board`}
                >
                  <Trash2 size={13} />
                </button>
              </div>
            ))}
            <div className="border-t border-gray-100 pt-2 mt-2">
              <div className="flex gap-1">
                <input
                  type="text"
                  value={newBoardName}
                  onChange={e => setNewBoardName(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); handleCreateBoard(); } }}
                  placeholder="New board name"
                  className="min-w-0 flex-1 rounded-md border border-gray-200 px-2.5 py-1.5 text-xs focus:ring-1 focus:ring-indigo-400"
                />
                <button
                  type="button"
                  onClick={() => handleCreateBoard()}
                  disabled={creatingBoard || !newBoardName.trim()}
                  className="rounded-md bg-indigo-600 px-2.5 py-1.5 text-xs font-medium text-white disabled:opacity-50"
                >
                  {creatingBoard ? '…' : '+ New'}
                </button>
              </div>
            </div>
          </div>

          {visibleSavedAds.length === 0 ? (
            <div className="bg-white rounded-xl border border-dashed border-gray-200 px-4 py-8 text-center">
              <Star size={20} className="mx-auto text-gray-300 mb-2" />
              <p className="text-xs text-gray-400 leading-relaxed">
                {activeBoardId ? 'This board is empty. Add ads from the research cards.' : 'Save competitor ads you want to reference. They’ll appear in the saved library.'}
              </p>
            </div>
          ) : (
            <div className="space-y-2 max-h-[calc(100vh-220px)] overflow-y-auto pr-1">
              {activeBoardId ? visibleSavedAds.map(ad => (
                <AdCard
                  key={ad.id}
                  ad={ad}
                  isSaved={savedAdIds.has(ad.id)}
                  onSave={handleSave}
                  onUnsave={handleUnsave}
                  onUseAsInspiration={handleUseAsInspiration}
                  onBlockPage={handleBlockPage}
                  angleTags={angleTags}
                  boards={boards}
                  onAddToBoard={handleAddToBoard}
                  onCreateBoard={handleCreateBoard}
                  onRemoveFromBoard={handleRemoveFromBoard}
                />
              )) : visibleSavedAds.map(ad => (
                <SavedCard
                  key={ad.id}
                  ad={ad}
                  onUnsave={handleUnsave}
                  onUseAsInspiration={handleUseAsInspiration}
                  boards={boards}
                  onAddToBoard={handleAddToBoard}
                  onCreateBoard={handleCreateBoard}
                  onNotesSaved={handleStrategyNotesSaved}
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
                <>{activeSubVertical
                  ? <>This removes all non-saved ads for the <strong>{subVerticals[activeSubVertical]?.label || activeSubVertical}</strong> sub-vertical.</>
                  : <>This removes all non-saved ads across <strong>all Home Services sub-verticals</strong>.</>}
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
