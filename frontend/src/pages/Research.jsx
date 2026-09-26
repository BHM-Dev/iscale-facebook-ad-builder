import React, { useState, useEffect, useRef, useMemo } from 'react';
import { Ban, FlaskConical, RefreshCw, Star, ExternalLink, ChevronDown, Trash2, Zap, X, Upload, BookOpen, Video, Play, ImagePlus, Sparkles, MoreHorizontal, Copy } from 'lucide-react';
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

const RESEARCH_INITIAL_CARD_COUNT = 24;
const RESEARCH_CARD_PAGE_SIZE = 24;
const RESEARCH_SAVED_VIEWS_KEY = 'adbuilder.research.saved-views.v1';
const COPILOT_PROMPTS = {
  commercial_insurance: [
    'Show commercial insurance ads for owner-operators',
    'Find contractor comparison ads with a get quote CTA',
    'Show video ads for security firms',
  ],
  auto_insurance: [
    'Show active auto insurance quote ads',
    'Find auto insurance comparison ads',
    'Show recent auto insurance video ads',
  ],
  home_services: [
    'Show active home services ads',
    'Find home services testimonial ads',
    'Show recent home services video ads',
  ],
};

const readSavedResearchViews = () => {
  if (typeof window === 'undefined') return [];
  try {
    const saved = JSON.parse(window.localStorage.getItem(RESEARCH_SAVED_VIEWS_KEY) || '[]');
    return Array.isArray(saved) ? saved.filter(view => view?.id && view?.name && view?.filters) : [];
  } catch (_) {
    return [];
  }
};

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
const hasVisualCandidate = (ad) => Boolean(
  ad.thumbnail_url || ad.media_url || ad.media_preview_url || (ad.video_urls || []).length,
);
// Older Brand Scrape records could attach Meta's player-control sprite to a
// video ad when no media match existed. Treat that known bad capture as
// missing media instead of presenting it as competitor creative.
const hasMisassignedVideoUiCapture = (ad) => (
  ad.creative_intel?.capture_source === 'brand_scrape'
  && (ad.media_type || '').toLowerCase() === 'image'
  && /0:00\s*\/\s*\d/.test(`${ad.headline || ''} ${ad.ad_copy || ''}`)
);
const hasUsableVisual = (ad) => hasVisualCandidate(ad) && !hasMisassignedVideoUiCapture(ad);

const researchText = (ad) => [ad.headline, ad.ad_copy, ad.cta_text].filter(Boolean).join(' ').trim();

const firstResearchSentence = (value) => {
  const clean = (value || '').replace(/\s+/g, ' ').trim();
  const sentence = clean.match(/^.*?[.!?](?:\s|$)|^.+$/)?.[0]?.trim() || '';
  return sentence.length > 116 ? `${sentence.slice(0, 113).trimEnd()}…` : sentence;
};

const researchMechanism = (ad) => {
  const copy = researchText(ad).toLowerCase();
  if (/\b(?:minutes?|fast|easy|online)\b/.test(copy) && /\b(?:quote|policy|coverage)\b/.test(copy)) return 'Fast online quote';
  if (/\b(?:save|saving|affordable|lower rate|cheap)\b/.test(copy)) return 'Savings-led offer';
  if (/\b(?:compare|comparison|options)\b/.test(copy)) return 'Comparison angle';
  if (/\b(?:protect|protection|covered|coverage)\b/.test(copy)) return 'Protection promise';
  if (/\b(?:custom|tailored|specialist)\b/.test(copy)) return 'Tailored coverage';
  return 'Direct coverage offer';
};

const selectCurrentTestShortlist = (ads) => {
  const seenCreative = new Set();
  const advertiserCounts = new Map();
  return [...ads]
    .filter(ad => ad.creative_intel?.capture_source === 'brand_scrape' && hasUsableVisual(ad))
    .sort((a, b) => new Date(b.last_seen || 0).getTime() - new Date(a.last_seen || 0).getTime())
    .filter(ad => {
      const fingerprint = `${ad.brand_name || ''}|${ad.headline || ''}|${ad.ad_copy || ''}`.toLowerCase().replace(/\s+/g, ' ').trim();
      const advertiser = (ad.brand_name || 'unknown advertiser').trim().toLowerCase();
      if (!fingerprint || seenCreative.has(fingerprint) || (advertiserCounts.get(advertiser) || 0) >= 2) return false;
      seenCreative.add(fingerprint);
      advertiserCounts.set(advertiser, (advertiserCounts.get(advertiser) || 0) + 1);
      return true;
    })
    .slice(0, 3);
};

const capAdsPerAdvertiser = (ads, adsPerAdvertiser) => {
  if (!adsPerAdvertiser) return ads;
  const counts = new Map();
  return ads.filter(ad => {
    const advertiser = ad.brand_name?.trim().toLowerCase();
    // Do not collapse unrelated legacy records simply because their advertiser
    // was not captured. The cap is meaningful only when we know the advertiser.
    if (!advertiser) return true;
    const count = counts.get(advertiser) || 0;
    if (count >= adsPerAdvertiser) return false;
    counts.set(advertiser, count + 1);
    return true;
  });
};

const filterResearchAds = (ads, { angleFilter, mediaTypeFilter, advertiserFilter, creativeTagFilter, ctaTypeFilter, pageTypeFilter, newOnly, needsTagging, hasVisual, activeOnly, sortBy, adsPerAdvertiser }) => {
  const advertiser = advertiserFilter.trim().toLowerCase();
  return capAdsPerAdvertiser(sortResearchAds(ads.filter(ad => (
    (!angleFilter || ad.angle_tag === angleFilter) &&
    (!mediaTypeFilter || (mediaTypeFilter === 'unknown' ? isUnknownMedia(ad.media_type) : ad.media_type === mediaTypeFilter)) &&
    (!advertiser || (ad.brand_name || '').toLowerCase().includes(advertiser)) &&
    (!creativeTagFilter || (ad.creative_tags || []).includes(creativeTagFilter)) &&
    (!ctaTypeFilter || ad.cta_type === ctaTypeFilter) &&
    (!pageTypeFilter || ad.page_type === pageTypeFilter) &&
    (!newOnly || !ad.first_seen || Date.now() - new Date(ad.first_seen).getTime() <= 7 * 24 * 60 * 60 * 1000) &&
    (!needsTagging || !ad.taxonomy_source) &&
    (!hasVisual || hasVisualCandidate(ad)) &&
    (!activeOnly || withDerivedResearchStatus(ad).is_active)
  )), sortBy), adsPerAdvertiser);
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
      .map((ad) => {
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
          creative_tags: ad.creative_tags || [],
          cta_type: ad.cta_type || '',
          page_type: ad.page_type || '',
          video_length_seconds: ad.video_length_seconds ?? null,
          media_preview_url: ad.media_preview_url || adVideos[0] || '',
          creative_intel: {
            visible_copy_preview: preview,
            imported_from_chrome: true,
            unmapped_video_inventory_count: unmappedVideoCount,
          },
        };
      }),
  };
};

const normalizeExternalResearchImport = (raw, activeVerticalLabel) => {
  const sourceAds = Array.isArray(raw) ? raw : (raw.ads || raw.rows || []);
  return {
    source: (Array.isArray(raw) ? 'External research' : raw.source) || 'External research',
    vertical: (Array.isArray(raw) ? null : raw.vertical) || activeVerticalLabel || 'Commercial Insurance',
    query: (Array.isArray(raw) ? null : raw.query) || 'external competitor research',
    source_url: Array.isArray(raw) ? null : (raw.source_url || ''),
    ads: sourceAds.map((ad) => ({
      external_id: ad.external_id || ad.id || '',
      brand_name: ad.brand_name || ad.brand || ad.advertiser || '',
      headline: ad.headline || '',
      primary_text: ad.primary_text || ad.ad_copy || ad.copy || '',
      cta: ad.cta || ad.cta_text || '',
      landing_url: ad.landing_url || ad.destination_url || ad.url || '',
      format: ad.format || ad.media_type || '',
      first_seen: normalizeAdLibraryDate(ad.first_seen || ad.start_date || ''),
      segment: ad.segment || ad.audience || '',
      source_signal: ad.source_signal || ad.performance_signal || ad.signal || '',
      creative_tags: ad.creative_tags || [],
    })).filter(ad => ad.brand_name),
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
        className="inline-flex items-center justify-center rounded-lg border border-emerald-200 bg-emerald-50 p-2 text-emerald-700 hover:bg-red-50 hover:border-red-200 hover:text-red-600 transition-colors"
        title="Remove from your worth-studying saves"
        aria-label="Saved as worth studying; click to remove"
      >
        <Star size={12} fill="currentColor" />
      </button>
    );
  }

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen(v => !v)}
        className="inline-flex items-center justify-center rounded-lg border border-emerald-200 bg-white p-2 text-emerald-700 hover:bg-emerald-50 transition-colors"
        title="Mark as worth studying"
        aria-label="Mark as worth studying"
      >
        <Star size={12} />
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
function BoardSaveButton({ ad, boards, onAdd, onCreate, compact = false }) {
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
        className={`${compact ? 'inline-flex' : 'w-full'} items-center justify-center gap-1 px-2 py-1.5 rounded-lg border border-indigo-200 bg-indigo-50 text-indigo-700 text-xs font-medium hover:bg-indigo-100 transition-colors`}
        aria-expanded={open}
      >
        <Star size={11} />
        {compact ? 'Save' : 'Save to board'}
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

// The research card is an inbox, not an ad-operations console. Keep the
// high-frequency actions visible and move destructive/navigation utilities
// behind one predictable overflow affordance.
function CardOverflowMenu({ ad, advertiserUrl, isReviewed, onInspect, onBlockPage, onSetReviewed, onRemoveFromBoard, boards, onAddToBoard, onCreateBoard, isCompared, onToggleCompare }) {
  return (
    <details className="relative">
      <summary className="flex h-8 w-8 cursor-pointer list-none items-center justify-center rounded-lg border border-slate-200 bg-white text-slate-500 hover:border-indigo-200 hover:bg-indigo-50 hover:text-indigo-700 [&::-webkit-details-marker]:hidden" aria-label="More research actions" title="More research actions">
        <MoreHorizontal size={16} />
      </summary>
      <div className="absolute bottom-10 right-0 z-20 w-52 rounded-xl border border-slate-200 bg-white p-1.5 shadow-xl">
        <button type="button" aria-label="Inspect details" onClick={() => onInspect(ad)} className="flex w-full items-center rounded-lg px-2.5 py-2 text-left text-xs font-medium text-slate-700 hover:bg-slate-50">Inspect details</button>
        {onToggleCompare && <button type="button" aria-label={isCompared ? 'Remove from compare' : 'Add to compare'} onClick={() => onToggleCompare(ad)} className="flex w-full items-center rounded-lg px-2.5 py-2 text-left text-xs font-medium text-slate-700 hover:bg-slate-50">{isCompared ? 'Remove from compare' : 'Add to compare'}</button>}
        <a href={advertiserUrl} target="_blank" rel="noopener noreferrer" className="flex w-full items-center rounded-lg px-2.5 py-2 text-xs font-medium text-slate-700 hover:bg-slate-50">{ad.platform === 'external' ? 'Open source' : 'View advertiser ads'} <ExternalLink size={11} className="ml-auto" /></a>
        {ad.platform !== 'external' && <button type="button" aria-label={isReviewed ? 'Remove from Research Brief' : 'Add to Research Brief'} onClick={() => onSetReviewed(ad, !isReviewed)} className="flex w-full items-center rounded-lg px-2.5 py-2 text-left text-xs font-medium text-slate-700 hover:bg-slate-50">{isReviewed ? 'Remove from Research Brief' : 'Add to Research Brief'}</button>}
        <div className="my-1 border-t border-slate-100" />
        <BoardSaveButton ad={ad} boards={boards} onAdd={onAddToBoard} onCreate={onCreateBoard} />
        {onRemoveFromBoard && <button type="button" aria-label="Remove from board" onClick={() => onRemoveFromBoard(ad)} className="mt-1 flex w-full items-center rounded-lg px-2.5 py-2 text-left text-xs font-medium text-red-600 hover:bg-red-50">Remove from board</button>}
        <button type="button" aria-label="Block advertiser" onClick={() => onBlockPage(ad)} className="mt-1 flex w-full items-center rounded-lg px-2.5 py-2 text-left text-xs font-medium text-red-600 hover:bg-red-50">Block advertiser</button>
      </div>
    </details>
  );
}

function ResearchDetailDrawer({ ad, activeVertical, advertiserSnapshot, retainedVisuals = [], onClose, onBuild, onInspect, onExploreAdvertiser, onBack, canGoBack, onPreviousResult, onNextResult, canGoPrevious, canGoNext, resultPosition, onNotesSaved, onMediaSaved, onReviewSaved, onBriefSaved, boards, onAddToBoard, onCreateBoard }) {
  const { authFetch } = useAuth();
  const { showError, showSuccess } = useToast();
  const [related, setRelated] = useState([]);
  const [notes, setNotes] = useState({ hook_type: '', promise: '' });
  const [savingNotes, setSavingNotes] = useState(false);
  const [videoFailed, setVideoFailed] = useState(false);
  const [uploadingMedia, setUploadingMedia] = useState(false);
  const [visualCandidates, setVisualCandidates] = useState([]);
  const [loadingVisualCandidates, setLoadingVisualCandidates] = useState(false);
  const [adoptingVisualId, setAdoptingVisualId] = useState('');
  const [briefTakeaway, setBriefTakeaway] = useState('');
  const [savingBrief, setSavingBrief] = useState(false);
  const mediaInputRef = useRef(null);
  useEffect(() => { setVideoFailed(false); }, [ad?.id]);
  useEffect(() => {
    if (!ad?.id) return undefined;
    let alive = true;
    const params = new URLSearchParams();
    if (activeVertical) params.set('vertical_id', activeVertical);
    authFetch(`${API_URL}/research/scraped-ads/${ad.id}/related?${params}`).then(res => res.ok ? res.json() : []).then(items => { if (alive) setRelated(items); }).catch(() => { if (alive) setRelated([]); });
    return () => { alive = false; };
  }, [ad?.id, activeVertical]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { setNotes({ hook_type: ad?.hook_type || '', promise: ad?.promise || '' }); }, [ad?.id]);
  useEffect(() => { setBriefTakeaway(ad?.creative_intel?.bhm_takeaway || ''); }, [ad?.id]);
  useEffect(() => {
    if (!ad?.id || ad.thumbnail_url || ad.media_url || ad.platform !== 'external') {
      setVisualCandidates([]);
      return undefined;
    }
    const normalizedBrand = (ad.brand_name || '').trim().toLowerCase();
    const fallbackCandidates = retainedVisuals.filter(candidate => (
      candidate.id !== ad.id
      && (candidate.brand_name || '').trim().toLowerCase() === normalizedBrand
      && (candidate.creative_intel?.capture_source === 'brand_scrape' || candidate.taxonomy_source === 'brand_scrape')
      && (candidate.thumbnail_url || candidate.media_url)
    )).slice(0, 8);
    setVisualCandidates(fallbackCandidates);
    let alive = true;
    setLoadingVisualCandidates(true);
    authFetch(`${API_URL}/research/scraped-ads/${ad.id}/visual-candidates`)
      .then(res => res.ok ? res.json() : [])
      .then(items => { if (alive && Array.isArray(items) && items.length) setVisualCandidates(items); })
      .catch(() => { /* The loaded library is a safe same-session fallback. */ })
      .finally(() => { if (alive) setLoadingVisualCandidates(false); });
    return () => { alive = false; };
  }, [ad?.id, ad?.thumbnail_url, ad?.media_url, ad?.platform, retainedVisuals]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!ad) return undefined;
    const onKeyDown = (event) => { if (event.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [ad, onClose]);
  if (!ad) return null;
  const media = hasMisassignedVideoUiCapture(ad) ? null : (ad.thumbnail_url || ad.media_url);
  // Meta CDN video URLs expire within minutes to hours (same as media_url) —
  // never assume a captured video_urls/media_preview_url is still playable.
  const videoPreview = !videoFailed && (ad.media_preview_url || (ad.video_urls || [])[0]);
  const saveNotes = async () => {
    setSavingNotes(true);
    try {
      const response = await authFetch(`${API_URL}/research/scraped-ads/${ad.id}/strategy-notes`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(notes) });
      if (!response.ok) throw new Error('Could not save notes');
      onNotesSaved(ad.id, await response.json());
      showSuccess('Strategic notes saved');
    } catch (error) { showError(error.message || 'Could not save notes'); } finally { setSavingNotes(false); }
  };
  const attachVisual = async (event) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    setUploadingMedia(true);
    try {
      const form = new FormData();
      form.append('file', file);
      const uploaded = await authFetch(`${API_URL}/uploads/`, { method: 'POST', body: form });
      if (!uploaded.ok) throw new Error((await uploaded.json().catch(() => ({}))).detail || 'Could not upload visual');
      const asset = await uploaded.json();
      const linked = await authFetch(`${API_URL}/research/scraped-ads/${ad.id}/media`, {
        method: 'PATCH', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: asset.url, media_type: asset.media_type }),
      });
      if (!linked.ok) throw new Error((await linked.json().catch(() => ({}))).detail || 'Could not attach visual');
      onMediaSaved(ad.id, await linked.json());
      showSuccess('Visual attached to this research finding');
    } catch (error) { showError(error.message || 'Could not attach visual'); }
    finally { setUploadingMedia(false); }
  };
  const toggleReviewed = async () => {
    const reviewed = !(ad.platform === 'external' || ad.creative_intel?.reviewed);
    try {
      const response = await authFetch(`${API_URL}/research/scraped-ads/${ad.id}/reviewed?reviewed=${reviewed}`, { method: 'PATCH' });
      if (!response.ok) throw new Error('Could not update Brief');
      onReviewSaved(ad.id, await response.json());
      showSuccess(reviewed ? 'Added to Research Brief' : 'Removed from Research Brief');
    } catch (error) { showError(error.message || 'Could not update Brief'); }
  };
  const adoptRetainedVisual = async (sourceAdId) => {
    setAdoptingVisualId(sourceAdId);
    try {
      const response = await authFetch(`${API_URL}/research/scraped-ads/${ad.id}/adopt-visual?source_ad_id=${encodeURIComponent(sourceAdId)}`, { method: 'POST' });
      const attached = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(attached.detail || 'Could not attach retained visual');
      onMediaSaved(ad.id, attached);
      showSuccess('BHM-captured visual attached to this Brief finding');
    } catch (error) { showError(error.message || 'Could not attach retained visual'); }
    finally { setAdoptingVisualId(''); }
  };
  const saveBriefCuration = async (updates, successMessage) => {
    setSavingBrief(true);
    try {
      const response = await authFetch(`${API_URL}/research/scraped-ads/${ad.id}/brief`, {
        method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(updates),
      });
      if (!response.ok) throw new Error('Could not update Research Brief');
      onBriefSaved(ad.id, await response.json());
      showSuccess(successMessage);
    } catch (error) { showError(error.message || 'Could not update Research Brief'); }
    finally { setSavingBrief(false); }
  };
  const copyCreative = async () => {
    const content = [ad.headline, ad.ad_copy].filter(Boolean).join('\n\n');
    if (!content) return;
    try {
      if (!navigator.clipboard?.writeText) throw new Error('Clipboard access is unavailable');
      await navigator.clipboard.writeText(content);
      showSuccess('Creative copied');
    } catch (error) { showError(error.message || 'Could not copy creative'); }
  };
  return <div className="fixed inset-0 z-50 flex justify-end bg-slate-950/30 backdrop-blur-sm" onClick={onClose}>
    <aside className="h-full w-full max-w-xl overflow-y-auto bg-white p-6 shadow-2xl" onClick={event => event.stopPropagation()} aria-label="Creative detail">
      <div className="mb-5 flex items-start justify-between gap-4"><div className="min-w-0 flex items-start gap-2">{canGoBack && <button type="button" onClick={onBack} className="mt-0.5 rounded-lg p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-700" aria-label="Back to previous related creative">←</button>}<div className="min-w-0"><p className="text-xs font-semibold uppercase tracking-wider text-indigo-600">Creative detail{resultPosition ? ` · ${resultPosition.current} of ${resultPosition.total}` : ''}</p><h2 className="mt-1 truncate text-xl font-bold text-slate-900" title={ad.brand_name || 'Unknown advertiser'}>{ad.brand_name || 'Unknown advertiser'}</h2></div></div><div className="flex flex-shrink-0 items-center gap-1"><button type="button" onClick={onPreviousResult} disabled={!canGoPrevious} className="rounded-lg px-2 py-1.5 text-xs font-semibold text-slate-600 hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-30">Previous</button><button type="button" onClick={onNextResult} disabled={!canGoNext} className="rounded-lg px-2 py-1.5 text-xs font-semibold text-slate-600 hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-30">Next</button><button type="button" onClick={onClose} className="rounded-lg p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-700"><X size={20}/></button></div></div>
      {(media || videoPreview) && <div className="relative mb-5 aspect-[4/3] overflow-hidden rounded-xl bg-slate-100">{ad.media_type === 'video' && videoPreview ? <video controls muted playsInline preload="metadata" poster={media || undefined} className="h-full w-full object-contain" onError={() => setVideoFailed(true)}><source src={videoPreview} />Your browser cannot preview this captured video.</video> : <img src={media} alt="Competitor creative" className="h-full w-full object-contain" onError={e => { e.target.style.display = 'none'; }} />}{ad.media_type === 'video' && <span className="absolute bottom-3 left-3 pointer-events-none inline-flex items-center gap-1 rounded-full bg-black/75 px-3 py-1.5 text-xs font-semibold text-white"><Play size={13} fill="currentColor"/> Video{ad.video_length_seconds ? ` · ${ad.video_length_seconds}s` : ''}</span>}</div>}
      <input ref={mediaInputRef} type="file" accept="image/*,video/mp4,video/webm,video/quicktime" className="hidden" onChange={attachVisual} />
      <button type="button" onClick={() => mediaInputRef.current?.click()} disabled={uploadingMedia} className="mb-5 inline-flex items-center gap-2 rounded-lg border border-indigo-200 bg-indigo-50 px-3 py-2 text-xs font-semibold text-indigo-700 hover:bg-indigo-100 disabled:opacity-50"><ImagePlus size={14}/>{uploadingMedia ? 'Uploading…' : media ? 'Replace approved visual' : 'Attach approved visual'}</button>
      {!media && ad.platform === 'external' && (loadingVisualCandidates || visualCandidates.length > 0) && <section className="mb-5 rounded-xl border border-emerald-200 bg-emerald-50/60 p-3"><div><h3 className="text-sm font-semibold text-emerald-950">Retained {ad.brand_name || 'advertiser'} media</h3><p className="mt-1 text-xs leading-5 text-emerald-800">These are BHM’s R2-backed Meta captures from the same advertiser—not copied vendor media. Choose one only when it supports this reviewed pattern.</p></div>{loadingVisualCandidates ? <p className="mt-3 text-xs text-emerald-700">Finding retained captures…</p> : <div className="mt-3 grid grid-cols-2 gap-2">{visualCandidates.map(candidate => <button key={candidate.id} type="button" onClick={() => adoptRetainedVisual(candidate.id)} disabled={Boolean(adoptingVisualId)} className="overflow-hidden rounded-lg border border-emerald-200 bg-white text-left hover:border-emerald-400 disabled:opacity-50">{candidate.thumbnail_url || candidate.media_url ? <img src={candidate.thumbnail_url || candidate.media_url} alt="Retained Meta capture" className="aspect-[4/3] w-full object-cover" /> : <div className="flex aspect-[4/3] items-center justify-center bg-slate-100 text-xs text-slate-500">Visual capture</div>}<span className="block truncate px-2 py-1.5 text-[11px] font-semibold text-slate-700">{adoptingVisualId === candidate.id ? 'Attaching…' : 'Use this visual'}</span></button>)}</div>}</section>}
      {ad.platform !== 'external' && <button type="button" onClick={toggleReviewed} className="mb-5 ml-2 inline-flex rounded-lg border border-slate-200 px-3 py-2 text-xs font-semibold text-slate-700 hover:border-indigo-200 hover:text-indigo-700">{ad.creative_intel?.reviewed ? 'Remove from Brief' : 'Add to Brief'}</button>}
      <button type="button" onClick={() => saveBriefCuration({ pinned: !ad.creative_intel?.pinned }, ad.creative_intel?.pinned ? 'Unpinned from Research Brief' : 'Pinned in Research Brief')} disabled={savingBrief} className="mb-5 ml-2 inline-flex rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs font-semibold text-amber-800 hover:bg-amber-100 disabled:opacity-50">{ad.creative_intel?.pinned ? 'Unpin finding' : 'Pin finding'}</button>
      <div className="mb-5 flex flex-wrap gap-2">{ad.creative_intel?.research_source && <span className="rounded-full bg-amber-50 px-2.5 py-1 text-xs font-semibold text-amber-800">Source: {ad.creative_intel.research_source}</span>}{(ad.creative_tags || []).map(tag => <span key={tag} className="rounded-full bg-violet-50 px-2.5 py-1 text-xs font-semibold text-violet-700">{tag.replaceAll('_', ' ')}</span>)}{ad.cta_type && <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-semibold text-slate-600">CTA: {ad.cta_type.replaceAll('_', ' ')}</span>}</div>
      <div className="flex items-start justify-between gap-3">{ad.headline && <h3 className="text-lg font-semibold leading-snug text-slate-900">{ad.headline}</h3>}{(ad.headline || ad.ad_copy) && <button type="button" onClick={copyCreative} className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs font-semibold text-slate-600 hover:border-indigo-200 hover:text-indigo-700"><Copy size={13}/>Copy</button>}</div>{ad.ad_copy && <p className="mt-3 whitespace-pre-wrap text-sm leading-6 text-slate-600">{ad.ad_copy}</p>}
      <dl className="mt-6 grid grid-cols-2 gap-3 border-t border-slate-100 pt-5 text-sm"><div><dt className="text-xs text-slate-400">Destination</dt><dd className="mt-1 truncate font-medium text-slate-700">{ad.destination_domain || 'Unknown'}</dd></div><div><dt className="text-xs text-slate-400">{ad.platform === 'external' ? 'Source first seen' : 'Observed runtime'}</dt><dd className="mt-1 font-medium text-slate-700">{ad.platform === 'external' ? (ad.creative_intel?.source_first_seen || 'Not supplied') : (ad.running_days != null ? `${ad.running_days} days` : 'Unknown')}</dd></div><div><dt className="text-xs text-slate-400">Platforms</dt><dd className="mt-1 truncate font-medium text-slate-700">{ad.platforms?.length ? ad.platforms.join(' · ') : 'Not supplied'}</dd></div><div><dt className="text-xs text-slate-400">Landing type</dt><dd className="mt-1 font-medium text-slate-700">{ad.page_type?.replaceAll('_', ' ') || 'Not classified'}</dd></div><div><dt className="text-xs text-slate-400">Last captured</dt><dd className="mt-1 font-medium text-slate-700">{ad.last_seen ? new Date(ad.last_seen).toLocaleDateString() : 'Unknown'}</dd></div><div><dt className="text-xs text-slate-400">Tag source</dt><dd className="mt-1 font-medium text-slate-700">{ad.taxonomy_source || 'Not tagged'}</dd></div>{ad.creative_intel?.source_signal && <div className="col-span-2"><dt className="text-xs text-slate-400">Source signal</dt><dd className="mt-1 text-xs font-medium text-amber-800">{ad.creative_intel.source_signal} <span className="font-normal text-slate-400">· directional source context</span></dd></div>}</dl>
      {advertiserSnapshot && <section className="mt-6 rounded-xl border border-slate-200 bg-slate-50 p-4"><div className="flex items-center justify-between gap-3"><div><h3 className="text-sm font-semibold text-slate-900">Advertiser context</h3><p className="mt-1 text-xs text-slate-500">From this library’s current {advertiserSnapshot.captureCount} captured records—not platform performance.</p></div><button type="button" onClick={() => onExploreAdvertiser(ad.brand_name)} className="text-xs font-semibold text-indigo-700 hover:text-indigo-900">Explore all</button></div><div className="mt-3 grid grid-cols-2 gap-3 text-xs"><div><p className="text-slate-400">Active captures</p><p className="mt-1 font-semibold text-slate-800">{advertiserSnapshot.activeCount}</p></div><div><p className="text-slate-400">Format mix</p><p className="mt-1 font-semibold text-slate-800">{advertiserSnapshot.formatMix || 'Unknown'}</p></div><div><p className="text-slate-400">First observed</p><p className="mt-1 font-semibold text-slate-800">{advertiserSnapshot.firstObserved || 'Unknown'}</p></div><div><p className="text-slate-400">Landing domains</p><p className="mt-1 font-semibold text-slate-800">{advertiserSnapshot.domainCount}</p></div></div></section>}
      <section className="mt-6 border-t border-slate-100 pt-5"><h3 className="text-sm font-semibold text-slate-900">Strategic notes</h3><p className="mt-1 text-xs text-slate-400">Your interpretation is passed to Remix as context, never competitor copy.</p><label className="mt-3 block text-xs font-medium text-slate-600">Hook pattern<input value={notes.hook_type} onChange={e => setNotes(prev => ({ ...prev, hook_type: e.target.value }))} placeholder="e.g. Cost shock" className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm" /></label><label className="mt-3 block text-xs font-medium text-slate-600">Why this pattern works<textarea value={notes.promise} onChange={e => setNotes(prev => ({ ...prev, promise: e.target.value }))} placeholder="The promise or reason to test this structure" className="mt-1 min-h-20 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm" /></label><button type="button" onClick={saveNotes} disabled={savingNotes} className="mt-3 rounded-lg border border-indigo-200 bg-indigo-50 px-3 py-2 text-xs font-semibold text-indigo-700 hover:bg-indigo-100 disabled:opacity-50">{savingNotes ? 'Saving…' : 'Save strategic notes'}</button></section>
      <section className="mt-6 border-t border-slate-100 pt-5"><h3 className="text-sm font-semibold text-slate-900">BHM takeaway</h3><p className="mt-1 text-xs text-slate-400">One internal sentence about what to test. This is never shown as source copy.</p><textarea value={briefTakeaway} onChange={event => setBriefTakeaway(event.target.value)} maxLength={500} placeholder="e.g. Test the segment → operational risk → compare-quote sequence with a verified claim." className="mt-3 min-h-20 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm" /><div className="mt-1 flex items-center justify-between"><span className="text-xs text-slate-400">{briefTakeaway.length}/500</span><button type="button" onClick={() => saveBriefCuration({ bhm_takeaway: briefTakeaway }, briefTakeaway.trim() ? 'BHM takeaway saved' : 'BHM takeaway cleared')} disabled={savingBrief} className="rounded-lg border border-indigo-200 bg-indigo-50 px-3 py-2 text-xs font-semibold text-indigo-700 hover:bg-indigo-100 disabled:opacity-50">{savingBrief ? 'Saving…' : 'Save takeaway'}</button></div></section>
      {related.length > 0 && <section className="mt-6 border-t border-slate-100 pt-5"><h3 className="text-sm font-semibold text-slate-900">Related patterns</h3><p className="mt-1 text-xs text-slate-400">Matched on visible creative metadata, not performance.</p><div className="mt-3 space-y-2">{related.map(item => <button type="button" key={item.id} onClick={() => onInspect(item)} className="w-full rounded-lg border border-slate-100 p-3 text-left hover:border-indigo-200 hover:bg-indigo-50/40"><p className="truncate text-sm font-semibold text-slate-700">{item.brand_name || 'Unknown advertiser'}</p><p className="mt-1 text-xs text-slate-500">{item.match_reasons.join(' · ')}</p></button>)}</div></section>}
      <div className="mt-7 grid grid-cols-2 gap-2"><button type="button" onClick={() => onBuild(ad)} className="inline-flex items-center justify-center gap-2 rounded-lg bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-indigo-700"><Zap size={15}/>Use as Inspiration</button>{ad.brand_name && <button type="button" onClick={() => onExploreAdvertiser(ad.brand_name)} className="inline-flex items-center justify-center gap-2 rounded-lg border border-slate-200 px-3 py-2.5 text-sm font-semibold text-slate-700 hover:border-indigo-200 hover:bg-indigo-50 hover:text-indigo-700"><span>Explore advertiser</span></button>}<a href={ad.ad_link} target="_blank" rel="noreferrer" className="col-span-2 inline-flex items-center justify-center gap-2 rounded-lg border border-slate-200 px-3 py-2 text-sm font-medium text-slate-600 hover:bg-slate-50"><ExternalLink size={15}/>{ad.platform === 'external' ? 'Open source link' : 'View in Meta Ad Library'}</a></div>
      <div className="mt-2"><BoardSaveButton ad={ad} boards={boards} onAdd={onAddToBoard} onCreate={onCreateBoard} /></div>
    </aside>
  </div>;
}

function AdCard({ ad, isSaved, onSave, onUnsave, onUseAsInspiration, onInspect, onBlockPage, onSetReviewed, angleTags, boards, onAddToBoard, onCreateBoard, onRemoveFromBoard, onVisualLoadError, isCompared, onToggleCompare }) {
  const [videoPreviewFailed, setVideoPreviewFailed] = useState(false);
  const [imageFailed, setImageFailed] = useState(false);
  const media = imageFailed || hasMisassignedVideoUiCapture(ad) ? null : (ad.thumbnail_url || ad.media_url);
  const videoPreview = ad.media_preview_url || (ad.video_urls || [])[0];
  const hasVisualCapture = Boolean(media || videoPreview);
  const isReviewed = ad.platform === 'external' || Boolean(ad.creative_intel?.reviewed);
  const advertiserUrl = ad.platform === 'external'
    ? ad.ad_link
    : `https://www.facebook.com/ads/library/?active_status=all&ad_type=all&country=US&q=${encodeURIComponent(ad.brand_name || '')}`;
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4 hover:shadow-sm transition-shadow flex flex-col gap-3">
      {/* Facebook CDN media URLs are temporary. A video-only capture can still
          get a useful preview, and falls back to an inspectable state if it expires. */}
      {(media || videoPreview) && (
        <button type="button" onClick={() => onInspect(ad)} className="relative rounded-lg overflow-hidden bg-gray-100 -mx-4 -mt-4 mb-1 aspect-[4/3] text-left" aria-label="Inspect captured creative">
          {media ? <img src={media} alt="" className="w-full h-full object-contain transition-transform duration-500 hover:scale-[1.02]" onError={() => { setImageFailed(true); onVisualLoadError?.(ad.id); }} />
            : !videoPreviewFailed ? <video muted loop playsInline preload="metadata" className="w-full h-full object-contain" onMouseEnter={event => event.currentTarget.play().catch(() => {})} onMouseLeave={event => { event.currentTarget.pause(); event.currentTarget.currentTime = 0; }} onError={() => setVideoPreviewFailed(true)}><source src={videoPreview} /></video>
              : <div className="flex h-full w-full flex-col items-center justify-center gap-2 bg-slate-900 text-white"><Video size={28} /><span className="text-xs font-semibold">Video capture · inspect to review</span></div>}
          {ad.media_type === 'video' && <span className="absolute left-3 bottom-3 inline-flex items-center gap-1.5 rounded-full bg-black/75 px-2.5 py-1 text-[11px] font-semibold text-white"><Play size={12} fill="currentColor" /> Video{ad.video_length_seconds ? ` · ${ad.video_length_seconds}s` : ''}</span>}
        </button>
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
        {!hasVisualCapture ? (
          <span className="text-xs font-medium text-slate-400" title="No usable creative asset was retained with this record.">NO MEDIA RETAINED</span>
        ) : isUnknownMedia(ad.media_type) ? (
          <span className="text-xs font-medium text-gray-400" title="The source did not provide a supported media format">UNKNOWN FORMAT</span>
        ) : ['image', 'carousel'].includes((ad.media_type || '').toLowerCase()) && (
          <span className="text-xs font-medium text-gray-400">{ad.media_type.toUpperCase()}</span>
        )}
        {Array.isArray(ad.platforms) && ad.platforms.length > 0 && (
          <span className="text-xs text-gray-400" title="Platforms reported by the Ad Library capture">
            {ad.platforms.join(' · ')}
          </span>
        )}
        {ad.creative_intel?.research_source && <span className="text-xs font-medium text-amber-700" title="Imported external research source; any signal is directional only">{ad.creative_intel.research_source}</span>}
        {ad.relevance_status === 'needs_review' && <span className="text-xs font-medium text-amber-700" title="This older capture passed the broad vertical gate but lacks a direct commercial-insurance offer signal. Review before using it as an input.">REVIEW RELEVANCE</span>}
        {ad.relevance_status === 'source_reviewed' && <span className="text-xs font-medium text-emerald-700" title="Externally reviewed source capture; still directional research, not performance evidence.">SOURCE REVIEWED</span>}
        <a
          href={advertiserUrl}
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

      {ad.match_reasons?.length > 0 && <p className="rounded-lg bg-violet-50 px-2.5 py-2 text-[11px] font-medium leading-4 text-violet-800"><span className="font-bold">Why it matched: </span>{ad.match_reasons.join(' · ')}</p>}

      {(ad.creative_tags?.length || ad.cta_type || ad.page_type) && <div className="flex flex-wrap gap-1.5">
        {(ad.creative_tags || []).slice(0, 3).map(tag => <span key={tag} className="rounded-full bg-violet-50 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-violet-700">{tag.replaceAll('_', ' ')}</span>)}
        {ad.cta_type && <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-slate-600">{ad.cta_type.replaceAll('_', ' ')}</span>}
        {ad.page_type && <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-slate-600">{ad.page_type}</span>}
      </div>}

      {/* Tags + duration */}
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <AngleBadge tag={ad.angle_tag} />
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
      <div className="mt-auto flex items-center gap-2 border-t border-gray-100 pt-3">
        <div className="flex min-w-0 flex-1 items-center gap-2">
          <button
            type="button"
            onClick={() => onUseAsInspiration(ad)}
            className="inline-flex min-w-0 flex-1 items-center justify-center gap-1.5 rounded-lg bg-indigo-600 px-3 py-2 text-xs font-semibold text-white hover:bg-indigo-700 transition-colors"
          >
            <Zap size={12} />
            Build ad
          </button>
          <SaveButton
            ad={ad}
            isSaved={isSaved}
            onSave={onSave}
            onUnsave={onUnsave}
            angleTags={angleTags}
          />
        </div>
        <CardOverflowMenu ad={ad} advertiserUrl={advertiserUrl} isReviewed={isReviewed} onInspect={onInspect} onBlockPage={onBlockPage} onSetReviewed={onSetReviewed} onRemoveFromBoard={onRemoveFromBoard} boards={boards} onAddToBoard={onAddToBoard} onCreateBoard={onCreateBoard} isCompared={isCompared} onToggleCompare={onToggleCompare} />
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

function ExternalResearchImportModal({ open, onClose, onImport, importing, defaultVertical }) {
  const [payloadText, setPayloadText] = useState('');
  if (!open) return null;
  const close = () => { setPayloadText(''); onClose(); };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 backdrop-blur-sm">
      <div className="w-full max-w-2xl rounded-xl bg-white p-6 shadow-xl">
        <div className="mb-4 flex items-start justify-between gap-4">
          <div>
            <h3 className="text-lg font-semibold text-gray-900">Import External Research</h3>
            <p className="mt-1 text-sm text-gray-500">Bring reviewed competitor rows from any temporary research source into the durable Research library.</p>
          </div>
          <button type="button" onClick={close} className="p-1 text-gray-400 hover:text-gray-600" aria-label="Close external research import"><X size={18} /></button>
        </div>
        <div className="mb-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
          <p className="font-semibold">Source labels stay directional</p>
          <p className="mt-1">A source signal such as “Winning” or “Growing” is kept as vendor context only. It never becomes BHM performance, spend, revenue, or profit data.</p>
        </div>
        <textarea
          value={payloadText}
          onChange={e => setPayloadText(e.target.value)}
          placeholder={JSON.stringify({ source: 'GetHookd', vertical: defaultVertical || 'Commercial Insurance', query: 'commercial insurance', ads: [{ brand_name: 'Example insurer', headline: 'Get a policy online in minutes', primary_text: 'Reviewed competitor copy', cta: 'Get Quote', landing_url: 'https://example.com/quote', format: 'carousel', first_seen: '2026-09-24', segment: 'Small business', source_signal: 'Winning — directional source signal' }] }, null, 2)}
          className="h-64 w-full rounded-lg border border-gray-200 p-3 font-mono text-xs focus:border-transparent focus:ring-2 focus:ring-indigo-400"
        />
        <div className="mt-4 flex items-center justify-between gap-3">
          <p className="text-xs text-gray-400">Required per row: <code>brand_name</code>. Up to 200 rows; media is intentionally not copied.</p>
          <div className="flex gap-2">
            <button type="button" onClick={close} className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50">Cancel</button>
            <button type="button" onClick={() => onImport(payloadText)} disabled={importing || !payloadText.trim()} className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"><Upload size={15} />{importing ? 'Importing...' : 'Import Research'}</button>
          </div>
        </div>
      </div>
    </div>
  );
}

function CompareTray({ ads, onRemove, onClear, onOpen }) {
  if (!ads.length) return null;
  return <div className="fixed bottom-5 left-1/2 z-30 flex w-[min(680px,calc(100vw-2rem))] -translate-x-1/2 items-center gap-3 rounded-xl border border-slate-200 bg-white p-3 shadow-xl">
    <div className="min-w-0 flex-1"><p className="text-xs font-semibold text-slate-700">Compare {ads.length} ad{ads.length === 1 ? '' : 's'}</p><div className="mt-1 flex gap-1 overflow-hidden">{ads.map(ad => { const label = ad.headline || ad.brand_name || 'ad'; return <button type="button" key={ad.id} onClick={() => onRemove(ad.id)} title={`Remove ${label}`} className="max-w-32 truncate rounded bg-slate-100 px-2 py-1 text-[11px] text-slate-600 hover:bg-red-50 hover:text-red-700">{label} ×</button>; })}</div></div>
    <button type="button" onClick={onClear} className="text-xs font-medium text-slate-500 hover:text-slate-800">Clear</button>
    <button type="button" onClick={onOpen} className="rounded-lg bg-indigo-600 px-3 py-2 text-xs font-semibold text-white hover:bg-indigo-700">Compare</button>
  </div>;
}

function ComparePanel({ ads, onClose, onInspect }) {
  if (!ads.length) return null;
  return <div className="fixed inset-0 z-50 flex items-end justify-center bg-slate-950/30 p-4 backdrop-blur-sm sm:items-center" onClick={onClose}>
    <section className="max-h-[85vh] w-full max-w-6xl overflow-auto rounded-2xl bg-white p-5 shadow-2xl" onClick={event => event.stopPropagation()} aria-label="Compare research ads">
      <div className="flex items-center justify-between gap-4"><div><h2 className="text-lg font-semibold text-slate-900">Compare ads</h2><p className="text-xs text-slate-500">Creative structure only—not performance.</p></div><button type="button" onClick={onClose} className="rounded-lg p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-700" aria-label="Close comparison"><X size={18}/></button></div>
      <div className={`mt-5 grid gap-4 ${ads.length === 1 ? 'grid-cols-1' : ads.length === 2 ? 'md:grid-cols-2' : 'md:grid-cols-3'}`}>{ads.map(ad => <article key={ad.id} className="overflow-hidden rounded-xl border border-slate-200"><button type="button" onClick={() => onInspect(ad)} className="w-full border-b border-slate-100 bg-slate-50 p-4 text-left hover:bg-indigo-50"><p className="truncate text-sm font-semibold text-slate-900">{ad.brand_name || 'Unknown advertiser'}</p><p className="mt-1 line-clamp-2 text-sm font-medium leading-5 text-slate-700">{ad.headline || 'No headline captured'}</p></button>{(ad.thumbnail_url || ad.media_url) ? <button type="button" onClick={() => onInspect(ad)} className="flex aspect-[16/9] w-full items-center justify-center overflow-hidden bg-slate-100" title="Inspect creative"><img src={ad.thumbnail_url || ad.media_url} alt="" className="h-full w-full object-contain" /></button> : <div className="flex aspect-[16/9] items-center justify-center bg-slate-50 text-xs font-medium text-slate-400">No retained visual</div>}<div className="space-y-4 p-4"><div><p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">Copy</p><p className="mt-1 whitespace-pre-wrap text-sm leading-6 text-slate-600">{ad.ad_copy || 'No copy captured'}</p></div><div className="flex flex-wrap gap-1.5">{(ad.creative_tags || []).map(tag => <span key={tag} className="rounded-full bg-violet-50 px-2 py-0.5 text-[10px] font-semibold uppercase text-violet-700">{tag.replaceAll('_', ' ')}</span>)}{ad.cta_type && <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-semibold uppercase text-slate-600">{ad.cta_type.replaceAll('_', ' ')}</span>}</div><div className="grid grid-cols-2 gap-2 text-xs"><div><p className="text-slate-400">Format</p><p className="mt-1 font-medium text-slate-700">{ad.media_type || 'Unknown'}</p></div><div><p className="text-slate-400">Visual</p><p className="mt-1 font-medium text-slate-700">Available</p></div></div></div></article>)}</div>
    </section>
  </div>;
}

function ResearchBrief({ findings, testShortlist, visualMatchesByAdvertiser, totalFindings, visualStats, visualFilter, onVisualFilterChange, verticalLabel, onOpenLibrary, onInspect, onBuild, boards, onAddToBoard, onCreateBoard }) {
  return (
    <section className="space-y-4" aria-label="Research brief">
      <div className="rounded-2xl border border-indigo-100 bg-gradient-to-br from-indigo-50 via-white to-white p-5">
        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-indigo-700">Start here</p>
        <div className="mt-2 flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="text-xl font-semibold text-slate-950">{verticalLabel} research brief</h2>
            <p className="mt-1 text-sm text-slate-600">Patterns worth testing. Not performance data.</p>
          </div>
          <button type="button" onClick={onOpenLibrary} className="rounded-lg border border-indigo-200 bg-white px-3.5 py-2 text-sm font-semibold text-indigo-700 hover:bg-indigo-50">Open Ad Library</button>
        </div>
        <div className="mt-5 flex flex-wrap items-center justify-between gap-3 border-t border-indigo-100 pt-4">
          <div className="flex flex-wrap gap-2 text-xs font-medium"><span className="rounded-full bg-white px-2.5 py-1 text-slate-600 ring-1 ring-slate-200">{totalFindings} reviewed</span><span className="rounded-full bg-emerald-50 px-2.5 py-1 text-emerald-700 ring-1 ring-emerald-100">{visualStats.withVisual} visual</span><span className="rounded-full bg-amber-50 px-2.5 py-1 text-amber-800 ring-1 ring-amber-100">{visualStats.needsVisual} need a capture</span></div>
          <div className="inline-flex rounded-lg bg-white p-1 ring-1 ring-slate-200" aria-label="Visual coverage filter">
            {[['all', 'All'], ['with_visual', 'Visual'], ['needs_visual', 'Needs visual']].map(([value, label]) => <button key={value} type="button" onClick={() => onVisualFilterChange(value)} className={`rounded-md px-2.5 py-1 text-xs font-semibold ${visualFilter === value ? 'bg-slate-900 text-white' : 'text-slate-500 hover:text-slate-800'}`}>{label}</button>)}
          </div>
        </div>
      </div>

      {testShortlist.length > 0 && (
        <section className="rounded-xl border border-slate-200 bg-white p-4" aria-label="Current test shortlist">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.14em] text-indigo-700">Current test shortlist</p>
              <p className="mt-1 text-sm text-slate-600">Three recent visual examples worth studying first. Ranked for reviewability and message clarity—not performance.</p>
            </div>
            <button type="button" onClick={onOpenLibrary} className="text-sm font-semibold text-indigo-700 hover:text-indigo-900">Browse all captures</button>
          </div>
          <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {testShortlist.map(ad => (
              <article key={ad.id} className="flex rounded-lg border border-slate-200 bg-slate-50 text-left transition hover:border-indigo-300">
                <button type="button" onClick={() => onInspect(ad)} className="m-3 h-24 w-24 shrink-0 overflow-hidden rounded-md bg-slate-100 sm:h-28 sm:w-28" title="Inspect creative">
                  {ad.media_type === 'video' ? <video muted playsInline preload="metadata" poster={ad.thumbnail_url || undefined} className="h-full w-full object-contain"><source src={ad.media_preview_url || ad.media_url} /></video> : <img src={ad.thumbnail_url || ad.media_url} alt="" className="h-full w-full object-contain" />}
                </button>
                <div className="flex min-w-0 flex-1 flex-col py-3 pr-3">
                  <p className="truncate text-xs font-semibold text-slate-900">{ad.brand_name || 'Verified advertiser'}</p>
                  <p className="mt-1 line-clamp-2 text-sm font-semibold leading-5 text-slate-800">{firstResearchSentence(ad.headline || ad.ad_copy || 'Open captured creative')}</p>
                  <p className="mt-2 text-xs text-slate-500"><span className="font-semibold text-slate-600">Mechanism:</span> {researchMechanism(ad)}</p>
                  <div className="mt-auto flex items-center gap-3 pt-3">
                    <button type="button" onClick={() => onInspect(ad)} className="text-xs font-semibold text-indigo-700 hover:text-indigo-900">Inspect</button>
                    <BoardSaveButton ad={ad} boards={boards} onAdd={onAddToBoard} onCreate={onCreateBoard} compact />
                    <button type="button" onClick={() => onBuild(ad)} className="text-xs font-semibold text-indigo-700 hover:text-indigo-900">Build ad</button>
                  </div>
                </div>
              </article>
            ))}
          </div>
        </section>
      )}

      {findings.length === 0 ? (
        <div className="rounded-xl border border-dashed border-slate-300 bg-white px-6 py-12 text-center">
          <p className="font-medium text-slate-800">No reviewed findings yet for {verticalLabel}.</p>
          <p className="mx-auto mt-1 max-w-lg text-sm text-slate-500">Review ads, then save the patterns you want to test.</p>
          <button type="button" onClick={onOpenLibrary} className="mt-4 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700">Open Ad Library</button>
        </div>
      ) : (
        <div className="grid gap-4 lg:grid-cols-2 xl:grid-cols-3">
          {findings.map(ad => {
            const intel = ad.creative_intel || {};
            const visualMatchCount = visualMatchesByAdvertiser[(ad.brand_name || '').trim().toLowerCase()] || 0;
            return (
              <article key={ad.id} className="flex min-h-64 flex-col overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
                {(ad.thumbnail_url || ad.media_url) ? <button type="button" onClick={() => onInspect(ad)} className="aspect-[16/9] overflow-hidden bg-slate-100 text-left">{ad.media_type === 'video' ? <video muted playsInline preload="metadata" poster={ad.thumbnail_url || undefined} className="h-full w-full object-contain"><source src={ad.media_preview_url || ad.media_url} /></video> : <img src={ad.thumbnail_url || ad.media_url} alt="" className="h-full w-full object-contain" />}</button> : null}
                <div className="flex flex-1 flex-col p-5">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-xs font-semibold uppercase tracking-wide text-indigo-700">{intel.research_source || 'Reviewed research'}</p>
                    <h3 className="mt-1 text-base font-semibold leading-6 text-slate-900">{ad.brand_name}</h3>
                  </div>
                  <div className="flex flex-wrap justify-end gap-1.5">{intel.pinned && <span className="rounded-full bg-amber-50 px-2.5 py-1 text-[11px] font-semibold text-amber-800">Pinned</span>}{intel.segment && <span className="rounded-full bg-slate-100 px-2.5 py-1 text-right text-[11px] font-medium text-slate-600">{intel.segment}</span>}</div>
                </div>
                <p className="mt-4 text-sm font-semibold leading-6 text-slate-900">{firstResearchSentence(ad.headline || 'Reviewed competitor pattern')}</p>
                <p className="mt-2 line-clamp-2 text-sm leading-6 text-slate-600"><span className="font-medium text-slate-700">Pattern:</span> {firstResearchSentence(ad.ad_copy || intel.source_signal || 'Open details for the takeaway.')}</p>
                {!hasUsableVisual(ad) && visualMatchCount > 0 && <button type="button" onClick={() => onInspect(ad)} className="mt-3 inline-flex w-fit items-center rounded-full bg-indigo-50 px-2.5 py-1 text-[11px] font-semibold text-indigo-700 hover:bg-indigo-100">{visualMatchCount} retained visual{visualMatchCount === 1 ? '' : 's'} available</button>}
                {intel.bhm_takeaway && <p className="mt-3 rounded-lg bg-indigo-50 px-3 py-2 text-xs leading-5 text-indigo-950"><span className="font-semibold">BHM takeaway: </span>{intel.bhm_takeaway}</p>}
                <div className="mt-auto flex gap-2 pt-5">
                  <button type="button" onClick={() => onInspect(ad)} className="rounded-lg border border-slate-200 px-3 py-2 text-sm font-semibold text-slate-700 hover:border-indigo-200 hover:text-indigo-700">Inspect</button>
                  <button type="button" onClick={() => onBuild(ad)} className="rounded-lg bg-indigo-600 px-3 py-2 text-sm font-semibold text-white hover:bg-indigo-700">Build ad</button>
                </div>
                </div>
              </article>
            );
          })}
        </div>
      )}
    </section>
  );
}

function AdvertiserDirectory({ directory, loading, error, onExplore }) {
  if (loading) return <div className="rounded-xl border border-slate-200 bg-white px-5 py-12 text-center text-sm text-slate-500">Building the retained advertiser directory…</div>;
  if (error) return <div className="rounded-xl border border-red-100 bg-white px-5 py-12 text-center"><p className="font-medium text-red-700">Couldn’t load the advertiser directory.</p><p className="mt-1 text-sm text-slate-500">{error}</p></div>;
  if (!directory?.advertisers?.length) return <div className="rounded-xl border border-dashed border-slate-300 bg-white px-5 py-12 text-center text-sm text-slate-500">No retained advertisers are available for this vertical yet.</div>;
  return <section className="rounded-xl border border-slate-200 bg-white" aria-label="Retained advertiser directory">
    <div className="flex flex-wrap items-end justify-between gap-3 border-b border-slate-100 px-5 py-4"><div><p className="text-xs font-semibold uppercase tracking-[0.14em] text-indigo-700">Advertiser directory</p><h3 className="mt-1 text-base font-semibold text-slate-900">Choose an advertiser before you wade into ads</h3><p className="mt-1 max-w-2xl text-sm text-slate-500">Counts reflect unique retained creative patterns, not spend, scale, or a claim that an advertiser is currently live.</p>{directory.review_queue_count > 0 && <p className="mt-2 text-xs font-medium text-amber-700">{directory.review_queue_count} broad legacy capture{directory.review_queue_count === 1 ? '' : 's'} stay in Ad examples for relevance review and are excluded here.</p>}</div><span className="rounded-full bg-slate-50 px-2.5 py-1 text-xs font-semibold text-slate-600">{directory.advertisers.length} advertisers</span></div>
    <div className="divide-y divide-slate-100">{directory.advertisers.map(item => <div key={item.advertiser} className="flex flex-col gap-3 px-5 py-4 sm:flex-row sm:items-center"><div className="min-w-0 flex-1"><p className="truncate font-semibold text-slate-900">{item.advertiser}</p><p className="mt-1 truncate text-xs text-slate-500">{item.domains?.join(' · ') || 'No landing domain retained'}{item.latest_seen ? ` · last captured ${new Date(item.latest_seen).toLocaleDateString()}` : ''}</p></div><div className="flex flex-wrap gap-2 text-xs"><span className="rounded-full bg-slate-100 px-2.5 py-1 font-medium text-slate-700">{item.capture_count} capture{item.capture_count === 1 ? '' : 's'}</span>{item.active_capture_count > 0 && <span className="rounded-full bg-emerald-50 px-2.5 py-1 font-medium text-emerald-700">{item.active_capture_count} recent</span>}{item.media_capture_count > 0 && <span className="rounded-full bg-indigo-50 px-2.5 py-1 font-medium text-indigo-700">{item.media_capture_count} with media</span>}{item.formats?.length > 0 && <span className="rounded-full bg-slate-50 px-2.5 py-1 font-medium text-slate-500">{item.formats.join(' / ')}</span>}</div><button type="button" onClick={() => onExplore(item.advertiser)} className="shrink-0 rounded-lg border border-indigo-200 bg-indigo-50 px-3 py-2 text-sm font-semibold text-indigo-700 hover:bg-indigo-100">Explore ads</button></div>)}</div>
  </section>;
}

function ResearchCopilot({ verticalId, verticalLabel, onRunResults }) {
  const { authFetch } = useAuth();
  const { showError } = useToast();
  const [question, setQuestion] = useState('');
  const [loading, setLoading] = useState(false);
  const [response, setResponse] = useState(null);
  useEffect(() => { setResponse(null); }, [verticalId]);
  const executeQuery = async (rawQuestion) => {
    const nextQuestion = rawQuestion.trim();
    if (!nextQuestion) return;
    setQuestion(nextQuestion);
    setLoading(true);
    try {
      const res = await authFetch(`${API_URL}/research/copilot/query`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: nextQuestion, vertical_id: verticalId }),
      });
      const payload = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(payload.detail || 'Research Copilot could not run that query');
      setResponse(payload);
    } catch (error) { showError(error.message || 'Research Copilot could not run that query'); }
    finally { setLoading(false); }
  };
  const runQuery = (event) => { event.preventDefault(); executeQuery(question); };
  const plan = response?.query_plan;
  const suggestedPrompts = COPILOT_PROMPTS[verticalId] || [];
  return <section className="mb-5 rounded-2xl border border-violet-200 bg-gradient-to-br from-violet-50 via-white to-indigo-50 p-4 shadow-sm" aria-label="Ask Research">
    <div className="flex flex-wrap items-start justify-between gap-3"><div><p className="inline-flex items-center gap-1.5 text-xs font-bold uppercase tracking-[0.14em] text-violet-700"><Sparkles size={13}/> Ask Research</p><p className="mt-1 text-sm text-slate-600">Search the retained competitor library.</p></div><span className="rounded-full bg-white px-2.5 py-1 text-xs font-semibold text-slate-500 ring-1 ring-violet-100">{verticalLabel}</span></div>
    <form onSubmit={runQuery} className="mt-3 flex flex-col gap-2 sm:flex-row"><input value={question} onChange={event => setQuestion(event.target.value)} maxLength={500} placeholder="e.g. Show active commercial auto ads for owner-operators running 30+ days" className="min-w-0 flex-1 rounded-xl border border-violet-200 bg-white px-3.5 py-2.5 text-sm text-slate-800 outline-none placeholder:text-slate-400 focus:border-violet-500 focus:ring-2 focus:ring-violet-200" aria-label="Ask Research" /><button type="submit" disabled={loading || !question.trim()} className="inline-flex items-center justify-center gap-2 rounded-xl bg-violet-700 px-4 py-2.5 text-sm font-semibold text-white hover:bg-violet-800 disabled:cursor-not-allowed disabled:opacity-50"><Sparkles size={15}/>{loading ? 'Planning…' : 'Search research'}</button></form>
    {!response && <div className="mt-2 flex flex-wrap items-center gap-1.5"><span className="text-[11px] font-medium text-slate-500">Try:</span>{suggestedPrompts.map(prompt => <button key={prompt} type="button" onClick={() => executeQuery(prompt)} className="rounded-full border border-violet-200 bg-white px-2.5 py-1 text-[11px] font-semibold text-violet-700 hover:bg-violet-50">{prompt}</button>)}</div>}
    {response && <div className="mt-4 rounded-xl border border-violet-100 bg-white/85 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2"><div><p className="text-sm font-semibold text-slate-900">Search plan · {response.coverage.matched} matching capture{response.coverage.matched === 1 ? '' : 's'}</p><p className="mt-0.5 text-xs text-slate-500">Searched {response.coverage.catalog_candidates} retained {verticalLabel.toLowerCase()} capture{response.coverage.catalog_candidates === 1 ? '' : 's'}.</p></div><button type="button" onClick={() => onRunResults(response)} disabled={!response.results.length} className="rounded-lg border border-violet-200 bg-violet-50 px-3 py-1.5 text-xs font-semibold text-violet-800 hover:bg-violet-100 disabled:opacity-50">Review results{response.coverage.returned < response.coverage.matched ? ` (${response.coverage.returned} of ${response.coverage.matched})` : ''}</button></div>
      <div className="mt-2 flex flex-wrap gap-1.5">{plan.segments.map(segment => <span key={segment} className="rounded-full bg-violet-50 px-2 py-1 text-[11px] font-semibold text-violet-700">{segment}</span>)}{plan.creative_tags?.map(tag => <span key={tag} className="rounded-full bg-violet-50 px-2 py-1 text-[11px] font-semibold text-violet-700">{tag.replace('_', ' ')}</span>)}{plan.active_only && <span className="rounded-full bg-violet-50 px-2 py-1 text-[11px] font-semibold text-violet-700">active capture</span>}{plan.min_running_days && <span className="rounded-full bg-violet-50 px-2 py-1 text-[11px] font-semibold text-violet-700">observed {plan.min_running_days}+ days</span>}{plan.captured_within_days && <span className="rounded-full bg-violet-50 px-2 py-1 text-[11px] font-semibold text-violet-700">captured within {plan.captured_within_days} days</span>}{plan.media_type && <span className="rounded-full bg-violet-50 px-2 py-1 text-[11px] font-semibold text-violet-700">{plan.media_type}</span>}{plan.cta_type && <span className="rounded-full bg-violet-50 px-2 py-1 text-[11px] font-semibold text-violet-700">{plan.cta_type.replace('_', ' ')} CTA</span>}{plan.page_type && <span className="rounded-full bg-violet-50 px-2 py-1 text-[11px] font-semibold text-violet-700">{plan.page_type.replace('_', ' ')} destination</span>}</div>
      {response.ai_summary && <div className="mt-3 rounded-lg border border-indigo-100 bg-indigo-50/70 px-3 py-2.5"><p className="text-[11px] font-bold uppercase tracking-[0.12em] text-indigo-700">AI read of these captures</p><p className="mt-1 text-sm leading-5 text-slate-700">{response.ai_summary.answer}</p>{response.ai_summary.patterns?.length > 0 && <div className="mt-2 flex flex-wrap gap-1.5">{response.ai_summary.patterns.map((pattern, index) => <span key={`${pattern}-${index}`} className="rounded-full bg-white px-2 py-1 text-[11px] font-medium text-indigo-800 ring-1 ring-indigo-100">{pattern}</span>)}</div>}</div>}
      {plan.performance_intent && <p className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-900">No verified performance data—showing relevant examples.</p>}
      <p className={`mt-3 text-xs leading-5 ${response.coverage.sufficient ? 'text-slate-600' : 'text-amber-800'}`}>{response.coverage.sufficient ? 'Enough examples to review.' : 'Limited examples in this library.'}</p>
      {response.suggestions?.length > 0 && <div className="mt-3 border-t border-violet-100 pt-3"><p className="text-xs font-semibold text-slate-700">Try a broader retained-catalog search</p><div className="mt-2 flex flex-wrap gap-2">{response.suggestions.map(suggestion => <button key={suggestion.question} type="button" disabled={loading} onClick={() => executeQuery(suggestion.question)} title={suggestion.reason} className="rounded-lg border border-violet-200 bg-white px-2.5 py-1.5 text-left text-xs font-medium text-violet-800 hover:bg-violet-50 disabled:opacity-50"><span className="block">{suggestion.question}</span><span className="mt-0.5 block text-[10px] font-normal text-slate-500">{suggestion.reason}</span></button>)}</div></div>}
      {response.limitations?.map((limitation, index) => <p key={limitation} className={`mt-2 text-xs leading-5 ${index === 0 && plan.performance_intent ? 'font-medium text-amber-800' : 'text-slate-500'}`}>{limitation}</p>)}
    </div>}
  </section>;
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
  const [researchView, setResearchView] = useState('brief');
  const [briefVisualFilter, setBriefVisualFilter] = useState('all');
  const [showCatalogTools, setShowCatalogTools] = useState(false);
  const homeServicesRef = useRef(null);

  const [browseAds, setBrowseAds] = useState([]);
  // A Meta CDN URL can be present in a capture but no longer resolve. Keep
  // those failures client-side so "Has visual capture" means an image/video
  // the researcher can actually see, not merely a stale URL in the database.
  const [failedVisualIds, setFailedVisualIds] = useState(() => new Set());
  const [catalogMode, setCatalogMode] = useState('ads');
  const [advertiserDirectory, setAdvertiserDirectory] = useState(null);
  const [advertiserDirectoryLoading, setAdvertiserDirectoryLoading] = useState(false);
  const [advertiserDirectoryError, setAdvertiserDirectoryError] = useState('');
  const [visibleCardCount, setVisibleCardCount] = useState(RESEARCH_INITIAL_CARD_COUNT);
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
  const [showExternalImportModal, setShowExternalImportModal] = useState(false);
  const [detailAd, setDetailAd] = useState(null);
  const [detailHistory, setDetailHistory] = useState([]);
  const [compareIds, setCompareIds] = useState([]);
  const [compareOpen, setCompareOpen] = useState(false);
  const [importingIntel, setImportingIntel] = useState(false);
  const [clearing, setClearing] = useState(false);

  // Filters
  const [angleFilter, setAngleFilter] = useState('');
  const [mediaTypeFilter, setMediaTypeFilter] = useState('');
  const [sortBy, setSortBy] = useState('newest_seen');
  const [activeOnly, setActiveOnly] = useState(false);
  const [advertiserFilter, setAdvertiserFilter] = useState('');
  const [creativeTagFilter, setCreativeTagFilter] = useState('');
  const [ctaTypeFilter, setCtaTypeFilter] = useState('');
  const [pageTypeFilter, setPageTypeFilter] = useState('');
  const [newOnly, setNewOnly] = useState(false);
  const [needsTagging, setNeedsTagging] = useState(false);
  const [hasVisual, setHasVisual] = useState(false);
  const [adsPerAdvertiser, setAdsPerAdvertiser] = useState(0);
  const [showAdvancedFilters, setShowAdvancedFilters] = useState(false);
  const [savedViews, setSavedViews] = useState(readSavedResearchViews);
  const [savingView, setSavingView] = useState(false);
  const [newViewName, setNewViewName] = useState('');
  const [resultMode, setResultMode] = useState('browse');
  const [searchResultAds, setSearchResultAds] = useState([]);
  const [browseReloadKey, setBrowseReloadKey] = useState(0);
  const browseRequestRef = useRef(0);
  const searchRequestRef = useRef(0);
  const refreshRequestRef = useRef(0);
  const contextGenerationRef = useRef(0);
  const activeVerticalRef = useRef(activeVertical);
  const activeSubVerticalRef = useRef(activeSubVertical);

  const displayedBrowseAds = useMemo(
    () => hasVisual ? browseAds.filter(ad => !failedVisualIds.has(ad.id)) : browseAds,
    [browseAds, failedVisualIds, hasVisual],
  );

  const handleVisualLoadError = (adId) => {
    if (!hasVisual || !adId) return;
    setFailedVisualIds(previous => previous.has(adId) ? previous : new Set([...previous, adId]));
  };

  // A new browse response may contain a refreshed replacement URL for an ad
  // that failed earlier. Let that candidate prove itself again.
  useEffect(() => {
    setFailedVisualIds(new Set());
  }, [browseAds]);

  // ── Boot ─────────────────────────────────────────────────────
  useEffect(() => {
    contextGenerationRef.current += 1;
    activeVerticalRef.current = activeVertical;
    activeSubVerticalRef.current = activeSubVertical;
    setQueryLoading(false);
    setBriefVisualFilter('all');
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

  useEffect(() => {
    if (catalogMode === 'advertisers' && verticalConfig) loadAdvertiserDirectory();
  }, [catalogMode, activeVertical, activeSubVertical, verticalConfig]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    try {
      window.localStorage.setItem(RESEARCH_SAVED_VIEWS_KEY, JSON.stringify(savedViews));
    } catch (_) {
      // Private or storage-restricted browser contexts can still use Research;
      // they simply will not persist view presets between page loads.
    }
  }, [savedViews]);

  // Keep the first paint quick when a catalog or filter result contains many
  // captures. More cards remain one click away; the summary always shows the
  // full filtered count.
  useEffect(() => {
    setVisibleCardCount(RESEARCH_INITIAL_CARD_COUNT);
  }, [browseAds]);

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
      if (creativeTagFilter) params.set('creative_tags', creativeTagFilter);
      if (ctaTypeFilter) params.set('cta_type', ctaTypeFilter);
      if (pageTypeFilter) params.set('page_type', pageTypeFilter);
      if (newOnly) params.set('new_within_days', '7');
      if (needsTagging) params.set('needs_tagging', 'true');
      if (hasVisual) params.set('has_visual', 'true');
      if (adsPerAdvertiser) params.set('ads_per_advertiser', String(adsPerAdvertiser));
      params.set('sort_by', sortBy);
      params.set('limit', '500');

      // Research is an operator-facing, mutable catalog. Never let a browser
      // reuse an older browse response after an import, relevance update, or
      // deploy; stale rows are especially misleading when deciding what to
      // build from.
      const res = await authFetch(`${API_URL}/research/config-verticals/${activeVertical}/browse-ads?${params}`, { cache: 'no-store' });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `Failed to load ads (${res.status})`);
      }
      const ads = await res.json();
      if (requestId === browseRequestRef.current) setBrowseAds(ads.map(withDerivedResearchStatus));
    } catch (e) {
      if (requestId === browseRequestRef.current) setBrowseError(e.message || 'Failed to load ads');
    } finally {
      if (requestId === browseRequestRef.current) setBrowseLoading(false);
    }
  };

  const loadAdvertiserDirectory = async () => {
    setAdvertiserDirectoryLoading(true);
    setAdvertiserDirectoryError('');
    try {
      const params = new URLSearchParams();
      if (activeSubVertical) params.set('sub_vertical', activeSubVertical);
      // Keep the directory in lockstep with the browse catalog. A cached
      // directory could keep previously excluded broad-search advertisers on
      // screen after the underlying relevance rules changed.
      const response = await authFetch(`${API_URL}/research/config-verticals/${activeVertical}/advertisers?${params}`, { cache: 'no-store' });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload.detail || 'Failed to load advertiser directory');
      }
      setAdvertiserDirectory(await response.json());
    } catch (error) {
      setAdvertiserDirectoryError(error.message || 'Failed to load advertiser directory');
    } finally {
      setAdvertiserDirectoryLoading(false);
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
  const handleResearchMediaSaved = (adId, media) => {
    const apply = (ad) => ad.id === adId ? { ...ad, ...media } : ad;
    setSavedAds(prev => prev.map(apply));
    setBrowseAds(prev => prev.map(apply));
    setSearchResultAds(prev => prev.map(apply));
    setBoardAds(prev => prev.map(apply));
    setDetailAd(prev => prev?.id === adId ? apply(prev) : prev);
  };
  const handleResearchReviewSaved = (adId, update) => {
    const apply = (ad) => ad.id === adId ? { ...ad, ...update } : ad;
    setSavedAds(prev => prev.map(apply)); setBrowseAds(prev => prev.map(apply)); setSearchResultAds(prev => prev.map(apply)); setBoardAds(prev => prev.map(apply)); setDetailAd(prev => prev?.id === adId ? apply(prev) : prev);
  };
  const handleSetResearchReviewed = async (ad, reviewed) => {
    try {
      const response = await authFetch(`${API_URL}/research/scraped-ads/${ad.id}/reviewed?reviewed=${reviewed}`, { method: 'PATCH' });
      if (!response.ok) throw new Error('Could not update Research Brief');
      handleResearchReviewSaved(ad.id, await response.json());
      showSuccess(reviewed ? 'Added to Research Brief' : 'Removed from Research Brief');
    } catch (error) {
      showError(error.message || 'Could not update Research Brief');
    }
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
      const filtered = filterResearchAds(normalized, { angleFilter, mediaTypeFilter, advertiserFilter, creativeTagFilter, ctaTypeFilter, pageTypeFilter, newOnly, needsTagging, hasVisual, activeOnly, sortBy, adsPerAdvertiser });
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
      setBrowseAds(filterResearchAds(searchResultAds, { angleFilter, mediaTypeFilter, advertiserFilter, creativeTagFilter, ctaTypeFilter, pageTypeFilter, newOnly, needsTagging, hasVisual, activeOnly, sortBy, adsPerAdvertiser }));
      return undefined;
    }
    const t = setTimeout(() => loadBrowseAds(), advertiserFilter ? 400 : 0);
    return () => clearTimeout(t);
  }, [angleFilter, mediaTypeFilter, sortBy, activeOnly, advertiserFilter, creativeTagFilter, ctaTypeFilter, pageTypeFilter, newOnly, needsTagging, hasVisual, adsPerAdvertiser, resultMode, searchResultAds, browseReloadKey]); // eslint-disable-line react-hooks/exhaustive-deps

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
    // A full vertical refresh walks several live Ad Library queries.  Three
    // minutes regularly aborts a healthy server-side run midway through and
    // leaves the researcher with a misleading partial result.
    const timeoutId = setTimeout(() => controller.abort(), 600000); // 10 min cap

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
        showError('Refresh timed out before the live capture completed. Any earlier keyword results may be available below.');
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

  const handleExternalResearchImport = async (payloadText) => {
    setImportingIntel(true);
    try {
      const payload = normalizeExternalResearchImport(JSON.parse(payloadText), currentVerticalLabel);
      if (!payload.ads.length) throw new Error('No rows with brand_name found in pasted JSON');
      const res = await authFetch(`${API_URL}/research/external-import`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
      });
      const result = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(result.detail || 'External research import failed');
      showSuccess(result.message || `Imported ${payload.ads.length} external research rows`);
      setShowExternalImportModal(false);
      loadBrowseAds();
      loadSavedAds();
    } catch (e) {
      showError(e.message || 'External research import failed');
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
      analystTakeaway: ad.creative_intel?.bhm_takeaway || null,
      researchBoard: boards.find(board => board.id === activeBoardId)?.name || null,
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
      creative_tags: ad.creative_tags || [],
      cta_type: ad.cta_type,
      page_type: ad.page_type,
      video_length_seconds: ad.video_length_seconds,
      taxonomy_source: ad.taxonomy_source,
      taxonomy_confidence: ad.taxonomy_confidence,
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
  const advancedFilterCount = [creativeTagFilter, ctaTypeFilter, pageTypeFilter, activeOnly, newOnly, needsTagging, hasVisual, adsPerAdvertiser].filter(Boolean).length;
  const hasActiveFilters = Boolean(angleFilter || mediaTypeFilter || creativeTagFilter || ctaTypeFilter || pageTypeFilter || activeOnly || newOnly || needsTagging || hasVisual || advertiserFilter || adsPerAdvertiser);
  const clearFilters = () => {
    setAngleFilter(''); setMediaTypeFilter(''); setCreativeTagFilter(''); setCtaTypeFilter('');
    setPageTypeFilter(''); setActiveOnly(false); setNewOnly(false); setNeedsTagging(false); setHasVisual(false); setAdvertiserFilter(''); setAdsPerAdvertiser(0);
  };
  const currentViewFilters = () => ({
    activeVertical, activeSubVertical, angleFilter, mediaTypeFilter, sortBy,
    activeOnly, advertiserFilter, creativeTagFilter, ctaTypeFilter, pageTypeFilter,
    newOnly, needsTagging, hasVisual, adsPerAdvertiser,
  });
  const saveCurrentView = () => {
    const name = newViewName.trim();
    if (!name) return;
    setSavedViews(views => [{ id: `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`, name, filters: currentViewFilters() }, ...views].slice(0, 12));
    setNewViewName('');
    setSavingView(false);
    showSuccess(`Saved view “${name}”`);
  };
  const applySavedView = (view) => {
    const filters = view.filters || {};
    setActiveVertical(filters.activeVertical || activeVertical);
    setActiveSubVertical(filters.activeSubVertical || null);
    setAngleFilter(filters.angleFilter || ''); setMediaTypeFilter(filters.mediaTypeFilter || '');
    setSortBy(filters.sortBy || 'newest_seen'); setActiveOnly(Boolean(filters.activeOnly));
    setAdvertiserFilter(filters.advertiserFilter || ''); setCreativeTagFilter(filters.creativeTagFilter || '');
    setCtaTypeFilter(filters.ctaTypeFilter || ''); setPageTypeFilter(filters.pageTypeFilter || '');
    setNewOnly(Boolean(filters.newOnly)); setNeedsTagging(Boolean(filters.needsTagging));
    setHasVisual(Boolean(filters.hasVisual));
    setAdsPerAdvertiser(Number(filters.adsPerAdvertiser) || 0);
    setResultMode('browse'); setSearchResultAds([]); closeDetail();
    showSuccess(`Applied view “${view.name}”`);
  };
  const deleteSavedView = (viewId) => setSavedViews(views => views.filter(view => view.id !== viewId));
  const inspectCreative = (ad) => {
    setDetailAd(ad);
    setDetailHistory(prev => [...prev.filter(item => item.id !== ad.id), ad]);
  };
  const toggleCompare = (ad) => setCompareIds(ids => ids.includes(ad.id) ? ids.filter(id => id !== ad.id) : [...ids, ad.id].slice(-3));
  const closeDetail = () => { setDetailAd(null); setDetailHistory([]); };
  const goBackInDetail = () => setDetailHistory(prev => {
    const next = prev.slice(0, -1);
    setDetailAd(next[next.length - 1] || null);
    return next;
  });
  const exploreAdvertiser = (advertiser) => {
    // Related-pattern inspection can begin from either Browse or a one-time
    // keyword search. Move back to the durable catalog before applying the
    // advertiser filter, while retaining the analyst's other filters.
    setActiveBoardId(null);
    setCatalogMode('ads');
    setResultMode('browse');
    setSearchResultAds([]);
    setAdvertiserFilter(advertiser);
    closeDetail();
  };
  const handleCopilotResults = (response) => {
    const results = (response.results || []).map(withDerivedResearchStatus);
    setQuery(response.question || '');
    setResearchView('library');
    setActiveBoardId(null);
    setBrowseError('');
    setSearchResultAds(results);
    setBrowseAds(results);
    setResultMode('search');
  };
  const catalogSummary = useMemo(() => ({
    total: displayedBrowseAds.length,
    newCount: displayedBrowseAds.filter(ad => ad.first_seen && Date.now() - new Date(ad.first_seen).getTime() <= 7 * 24 * 60 * 60 * 1000).length,
    videoCount: displayedBrowseAds.filter(ad => ad.media_type === 'video').length,
    mediaCount: displayedBrowseAds.filter(hasVisualCandidate).length,
    taggedCount: displayedBrowseAds.filter(ad => (ad.creative_tags || []).length > 0).length,
    needsReviewCount: displayedBrowseAds.filter(ad => ad.relevance_status === 'needs_review').length,
  }), [displayedBrowseAds]);
  const reviewedFindingsAll = useMemo(() => [...browseAds]
    .filter(ad => ad.platform === 'external' || ad.creative_intel?.reviewed)
    .sort((a, b) => Number(Boolean(b.creative_intel?.pinned)) - Number(Boolean(a.creative_intel?.pinned))), [browseAds]);
  const visualStats = useMemo(() => {
    const withVisual = reviewedFindingsAll.filter(ad => ad.thumbnail_url || ad.media_url).length;
    return { withVisual, needsVisual: reviewedFindingsAll.length - withVisual };
  }, [reviewedFindingsAll]);
  const reviewedFindings = useMemo(() => reviewedFindingsAll.filter(ad => (
    briefVisualFilter === 'all' || (briefVisualFilter === 'with_visual' ? Boolean(ad.thumbnail_url || ad.media_url) : !ad.thumbnail_url && !ad.media_url)
  )), [reviewedFindingsAll, briefVisualFilter]);
  const currentTestShortlist = useMemo(() => selectCurrentTestShortlist(browseAds), [browseAds]);
  const visualMatchesByAdvertiser = useMemo(() => browseAds.reduce((matches, ad) => {
    const advertiser = (ad.brand_name || '').trim().toLowerCase();
    if (!advertiser || ad.creative_intel?.capture_source !== 'brand_scrape' || !hasUsableVisual(ad)) return matches;
    matches[advertiser] = (matches[advertiser] || 0) + 1;
    return matches;
  }, {}), [browseAds]);
  const compareAds = useMemo(() => {
    const byId = new Map([...browseAds, ...savedAds, ...boardAds].map(ad => [ad.id, ad]));
    return compareIds.map(id => byId.get(id)).filter(Boolean);
  }, [browseAds, savedAds, boardAds, compareIds]);
  // The detail drawer must stay in the workspace the user entered from.
  // A Brief finding is not the first item in the raw catalog merely because
  // both records live in the same collection.
  const detailResults = researchView === 'brief' ? reviewedFindings : browseAds;
  const detailResultIndex = detailAd ? detailResults.findIndex(ad => ad.id === detailAd.id) : -1;
  const inspectAdjacentResult = (offset) => {
    const adjacent = detailResults[detailResultIndex + offset];
    if (adjacent) setDetailAd(adjacent);
  };
  const advertiserSnapshot = useMemo(() => {
    const advertiser = detailAd?.brand_name?.trim().toLowerCase();
    if (!advertiser) return null;
    const matches = browseAds.filter(ad => ad.brand_name?.trim().toLowerCase() === advertiser);
    if (!matches.length) return null;
    const formatCounts = matches.reduce((counts, ad) => {
      const format = ad.media_type || 'unknown';
      counts[format] = (counts[format] || 0) + 1;
      return counts;
    }, {});
    const firstObserved = matches.map(ad => ad.start_date).filter(Boolean).sort()[0];
    return {
      captureCount: matches.length,
      activeCount: matches.filter(ad => ad.is_active).length,
      formatMix: Object.entries(formatCounts).map(([format, count]) => `${count} ${format}`).join(' · '),
      firstObserved: firstObserved ? new Date(firstObserved).toLocaleDateString() : null,
      domainCount: new Set(matches.map(ad => ad.destination_domain).filter(Boolean)).size,
    };
  }, [browseAds, detailAd]);

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
          <p className="text-sm text-gray-500 mt-0.5">Find patterns worth testing.</p>
        </div>
        <div className="flex flex-col items-end gap-1">
          <button
            type="button"
            onClick={() => setShowCatalogTools(open => !open)}
            className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-medium text-slate-600 hover:border-slate-300 hover:bg-slate-50"
            aria-expanded={showCatalogTools}
          >
            Manage research
          </button>
          {showCatalogTools && <div className="flex flex-wrap justify-end gap-2">
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
              onClick={() => setShowExternalImportModal(true)}
              disabled={refreshing || clearing || queryLoading}
              className="flex items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm font-medium text-amber-800 transition-colors hover:bg-amber-100 disabled:cursor-not-allowed disabled:opacity-50"
              title="Import reviewed rows from an external research source"
            >
              <Upload size={14} />
              External Research
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
          </div>}
          {refreshing && (
            <p className="text-xs text-gray-400">Pulling live Ad Library examples — a full vertical refresh can take several minutes</p>
          )}
        </div>
      </div>

      {/* Capture guidance belongs to the operator workspace, not the default brief. */}
      {researchView === 'library' && <div className="bg-white border border-indigo-100 rounded-xl p-4">
        <div className="flex items-start gap-3">
          <div className="w-9 h-9 rounded-lg bg-indigo-50 flex items-center justify-center flex-shrink-0">
            <BookOpen size={18} className="text-indigo-600" />
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <h2 className="text-sm font-semibold text-gray-900">Capture inbox</h2>
            </div>
            <p className="text-sm text-gray-600 mt-1">Inspect, save, or build from a captured ad.</p>
          </div>
        </div>
      </div>}

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

      <div className="flex items-center justify-between gap-3">
        <div className="inline-flex rounded-lg bg-slate-100 p-1" aria-label="Research view">
          <button type="button" onClick={() => setResearchView('brief')} className={`rounded-md px-3 py-1.5 text-sm font-semibold transition-colors ${researchView === 'brief' ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500 hover:text-slate-700'}`}>Research Brief</button>
          <button type="button" onClick={() => setResearchView('library')} className={`rounded-md px-3 py-1.5 text-sm font-semibold transition-colors ${researchView === 'library' ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500 hover:text-slate-700'}`}>Ad Library</button>
        </div>
        <span className="text-xs text-slate-500">{resultMode === 'search' ? `${reviewedFindingsAll.length} reviewed in results · ${catalogSummary.total} research results` : `${reviewedFindingsAll.length} reviewed finding${reviewedFindingsAll.length === 1 ? '' : 's'} · ${catalogSummary.total} raw captures`}</span>
      </div>

      <ResearchCopilot verticalId={activeVertical} verticalLabel={currentVerticalLabel} onRunResults={handleCopilotResults} />

      {researchView === 'brief' ? (
        <ResearchBrief
          findings={reviewedFindings}
          testShortlist={currentTestShortlist}
          visualMatchesByAdvertiser={visualMatchesByAdvertiser}
          totalFindings={reviewedFindingsAll.length}
          visualStats={visualStats}
          visualFilter={briefVisualFilter}
          onVisualFilterChange={setBriefVisualFilter}
          verticalLabel={currentVerticalLabel}
          onOpenLibrary={() => setResearchView('library')}
          onInspect={inspectCreative}
          onBuild={handleUseAsInspiration}
          boards={boards}
          onAddToBoard={handleAddToBoard}
          onCreateBoard={handleCreateBoard}
        />
      ) : <>

      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-slate-500" aria-label="Research catalog summary"><span className="font-semibold text-slate-800">{browseLoading ? 'Loading captures…' : `${catalogSummary.total} captured examples`}</span><span className="text-slate-300">·</span><span>{browseLoading ? '—' : `${catalogSummary.newCount} new this week`}</span><span className="text-slate-300">·</span><span>{browseLoading ? '—' : `${catalogSummary.videoCount} video`}</span><span className="text-slate-300">·</span><span>{browseLoading ? '—' : `${catalogSummary.taggedCount} theme tagged`}</span>{catalogSummary.needsReviewCount > 0 && <><span className="text-slate-300">·</span><span className="text-amber-700">{catalogSummary.needsReviewCount} need relevance review</span></>}<span className="text-slate-300">·</span><span className="text-slate-400">Current vertical + filters</span></div>
      {!browseLoading && catalogSummary.total > 0 && catalogSummary.mediaCount === 0 && <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900"><span>No retained assets in this filtered view. Source format labels are still shown, but they are not previews.</span><button type="button" onClick={() => setShowImportModal(true)} className="font-semibold text-indigo-700 hover:text-indigo-900">Import retained captures</button></div>}

      <div className="inline-flex rounded-lg bg-slate-100 p-1" aria-label="Research catalog mode"><button type="button" onClick={() => setCatalogMode('ads')} className={`rounded-md px-3 py-1.5 text-sm font-semibold ${catalogMode === 'ads' ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500 hover:text-slate-700'}`}>Ad examples</button><button type="button" onClick={() => setCatalogMode('advertisers')} className={`rounded-md px-3 py-1.5 text-sm font-semibold ${catalogMode === 'advertisers' ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500 hover:text-slate-700'}`}>Advertisers</button></div>

      {/* Two-column layout */}
      {catalogMode === 'advertisers' ? <AdvertiserDirectory directory={advertiserDirectory} loading={advertiserDirectoryLoading} error={advertiserDirectoryError} onExplore={exploreAdvertiser} /> : <div className="flex gap-5 items-start">
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
            <p className="mt-2 text-[11px] text-gray-400">Search all captures. Browse stays scoped to this vertical.</p>
          </form>
          {/* Filter bar */}
          <div className="flex flex-col gap-3 rounded-xl border border-gray-200 bg-white px-4 py-3 lg:flex-row lg:items-center">
            <div className="flex min-w-0 flex-1 flex-wrap items-center gap-x-2 gap-y-2">
              <span className="text-xs font-medium text-gray-500 whitespace-nowrap">
                {resultMode === 'search' ? 'SEARCH RESULTS' : 'BROWSE'}
                {!browseLoading && <span className="ml-1 text-gray-400">({displayedBrowseAds.length})</span>}
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

              <button type="button" onClick={() => setShowAdvancedFilters(open => !open)} className={`inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium transition-colors ${showAdvancedFilters || advancedFilterCount ? 'bg-indigo-50 text-indigo-700' : 'text-gray-600 hover:bg-gray-100'}`} aria-expanded={showAdvancedFilters}>
                Filters{advancedFilterCount ? ` ${advancedFilterCount}` : ''}<ChevronDown size={13} className={showAdvancedFilters ? 'rotate-180 transition-transform' : 'transition-transform'} />
              </button>
            </div>

            {/* Advertiser search */}
            <input
              type="text"
              value={advertiserFilter}
              onChange={e => setAdvertiserFilter(e.target.value)}
              placeholder="Filter by advertiser…"
              className="w-full shrink-0 rounded-lg border border-gray-200 px-3 py-1.5 text-xs focus:border-transparent focus:ring-2 focus:ring-indigo-400 sm:w-56 lg:w-48"
            />
            {hasActiveFilters && <button type="button" onClick={clearFilters} className="text-xs font-medium text-indigo-600 hover:text-indigo-800">Clear filters</button>}
          </div>
          {showAdvancedFilters && <div className="-mt-3 rounded-b-xl border border-t-0 border-gray-200 bg-slate-50 px-4 py-3"><div className="flex flex-wrap items-center gap-3"><select value={creativeTagFilter} onChange={e => setCreativeTagFilter(e.target.value)} className="rounded-lg border border-gray-200 bg-white px-2.5 py-1.5 text-xs text-gray-600" title="Visible-copy theme labels; unknown ads remain visible by default"><option value="">All themes</option><option value="testimonial">Testimonial</option><option value="problem_agitation">Problem agitation</option><option value="comparison">Comparison</option><option value="review">Review</option><option value="listicle">Listicle</option><option value="educational">Educational</option><option value="ugc">UGC</option></select><select value={ctaTypeFilter} onChange={e => setCtaTypeFilter(e.target.value)} className="rounded-lg border border-gray-200 bg-white px-2.5 py-1.5 text-xs text-gray-600"><option value="">All CTAs</option><option value="get_quote">Get quote</option><option value="learn_more">Learn more</option><option value="sign_up">Sign up</option><option value="apply_now">Apply now</option><option value="contact_us">Contact us</option><option value="shop_now">Shop now</option></select><select value={pageTypeFilter} onChange={e => setPageTypeFilter(e.target.value)} className="rounded-lg border border-gray-200 bg-white px-2.5 py-1.5 text-xs text-gray-600"><option value="">All destinations</option><option value="lead_form">Lead form</option><option value="advertorial">Advertorial</option><option value="ecommerce">Ecommerce</option><option value="homepage">Homepage</option></select><select value={adsPerAdvertiser} onChange={e => setAdsPerAdvertiser(Number(e.target.value))} className="rounded-lg border border-gray-200 bg-white px-2.5 py-1.5 text-xs text-gray-600" title="Keep the gallery varied by limiting how many ads appear from each known advertiser"><option value={0}>All per advertiser</option><option value={1}>1 per advertiser</option><option value={3}>3 per advertiser</option><option value={5}>5 per advertiser</option></select><label className="flex items-center gap-1.5 cursor-pointer text-xs text-gray-600 whitespace-nowrap" title="Only show cards with an actual retained image, thumbnail, or playable video—not source format metadata alone"><input type="checkbox" checked={hasVisual} onChange={e => setHasVisual(e.target.checked)} className="rounded text-indigo-600 focus:ring-indigo-500" />Has visual capture</label><label className="flex items-center gap-1.5 cursor-pointer text-xs text-gray-600 whitespace-nowrap"><input type="checkbox" checked={activeOnly} onChange={e => setActiveOnly(e.target.checked)} className="rounded text-indigo-600 focus:ring-indigo-500" />Captured in last 30 days</label><label className="flex items-center gap-1.5 cursor-pointer text-xs text-gray-600 whitespace-nowrap" title="First captured by this Research catalog in the last seven days"><input type="checkbox" checked={newOnly} onChange={e => setNewOnly(e.target.checked)} className="rounded text-indigo-600 focus:ring-indigo-500" />New captures</label><label className="flex items-center gap-1.5 cursor-pointer text-xs text-gray-600 whitespace-nowrap" title="No theme or CTA label recorded yet"><input type="checkbox" checked={needsTagging} onChange={e => setNeedsTagging(e.target.checked)} className="rounded text-indigo-600 focus:ring-indigo-500" />Needs tagging</label></div></div>}
          {showAdvancedFilters && <div className="-mt-2 flex flex-wrap items-center gap-2 text-xs"><span className="text-slate-400">Save this view</span>{savingView ? <><input autoFocus value={newViewName} onChange={event => setNewViewName(event.target.value)} onKeyDown={event => { if (event.key === 'Enter') saveCurrentView(); if (event.key === 'Escape') { setSavingView(false); setNewViewName(''); } }} placeholder="e.g. Video winners" className="w-40 rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs" /><button type="button" onClick={saveCurrentView} disabled={!newViewName.trim()} className="rounded-lg bg-indigo-600 px-2.5 py-1.5 font-semibold text-white disabled:opacity-50">Save</button><button type="button" onClick={() => { setSavingView(false); setNewViewName(''); }} className="px-1.5 py-1 text-slate-500 hover:text-slate-800">Cancel</button></> : <button type="button" onClick={() => setSavingView(true)} className="rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 font-medium text-slate-700 hover:border-indigo-200 hover:text-indigo-700">Save current view</button>}</div>}
          {advertiserFilter && <div className="-mt-2 flex min-w-0 items-center gap-2 text-xs text-slate-500"><span className="flex-shrink-0">Scoped to</span><button type="button" onClick={() => setAdvertiserFilter('')} className="inline-flex min-w-0 max-w-full items-center gap-1 rounded-full bg-indigo-50 px-2.5 py-1 font-medium text-indigo-700 hover:bg-indigo-100" title="Clear advertiser scope"><span className="truncate">{advertiserFilter}</span><X size={12} className="flex-shrink-0" /></button></div>}
          {savedViews.length > 0 && <div className="-mt-2 flex flex-wrap items-center gap-1.5 text-xs"><span className="mr-1 text-slate-400">Saved views</span>{savedViews.map(view => <span key={view.id} className="inline-flex max-w-full items-center rounded-full border border-slate-200 bg-white text-slate-600"><button type="button" onClick={() => applySavedView(view)} className="max-w-[180px] truncate px-2.5 py-1 hover:text-indigo-700">{view.name}</button><button type="button" onClick={() => deleteSavedView(view.id)} className="border-l border-slate-100 px-1.5 py-1 text-slate-400 hover:text-red-500" aria-label={`Delete saved view ${view.name}`}><X size={11} /></button></span>)}</div>}

          {refreshSummary?.first_error && (
            <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
              {refreshSummary.status === 'timed_out' ? 'Refresh timed out' : refreshSummary.status === 'failed' ? 'Refresh failed' : refreshSummary.status === 'clear_failed' ? 'Clear failed' : 'Refresh was partial'}: {refreshSummary.first_error} {refreshSummary.status !== 'partial' && 'Showing the last successful capture where available.'}
            </div>
          )}

          {/* Card gallery */}
          {browseLoading ? (
            <div className="grid grid-cols-1 lg:grid-cols-2 2xl:grid-cols-3 gap-4">
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
          ) : displayedBrowseAds.length === 0 ? (
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
            <>
              <div className="grid grid-cols-1 lg:grid-cols-2 2xl:grid-cols-3 gap-4">
                {displayedBrowseAds.slice(0, visibleCardCount).map(ad => (
                  <AdCard
                    key={ad.id}
                    ad={ad}
                    isSaved={savedAdIds.has(ad.id)}
                    onSave={handleSave}
                    onUnsave={handleUnsave}
                    onUseAsInspiration={handleUseAsInspiration}
                    onInspect={inspectCreative}
                    onBlockPage={handleBlockPage}
                    onSetReviewed={handleSetResearchReviewed}
                    angleTags={angleTags}
                    boards={boards}
                    onAddToBoard={handleAddToBoard}
                    onCreateBoard={handleCreateBoard}
                    onVisualLoadError={handleVisualLoadError}
                    isCompared={compareIds.includes(ad.id)}
                    onToggleCompare={toggleCompare}
                  />
                ))}
              </div>
              {displayedBrowseAds.length > visibleCardCount && <div className="mt-5 flex flex-col items-center gap-2"><p className="text-xs text-slate-500">Showing {visibleCardCount} of {displayedBrowseAds.length} matching captures</p><button type="button" onClick={() => setVisibleCardCount(count => Math.min(count + RESEARCH_CARD_PAGE_SIZE, displayedBrowseAds.length))} className="rounded-lg border border-slate-200 bg-white px-4 py-2 text-sm font-semibold text-slate-700 hover:border-indigo-200 hover:bg-indigo-50 hover:text-indigo-700">Show {Math.min(RESEARCH_CARD_PAGE_SIZE, displayedBrowseAds.length - visibleCardCount)} more</button></div>}
            </>
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
                  onInspect={inspectCreative}
                  onBlockPage={handleBlockPage}
                  onSetReviewed={handleSetResearchReviewed}
                  angleTags={angleTags}
                  boards={boards}
                  onAddToBoard={handleAddToBoard}
                  onCreateBoard={handleCreateBoard}
                  onRemoveFromBoard={handleRemoveFromBoard}
                  isCompared={compareIds.includes(ad.id)}
                  onToggleCompare={toggleCompare}
                />
              )) : visibleSavedAds.map(ad => (
                <SavedCard
                  key={ad.id}
                  ad={ad}
                  onUnsave={handleUnsave}
                  onUseAsInspiration={handleUseAsInspiration}
                  onInspect={inspectCreative}
                  boards={boards}
                  onAddToBoard={handleAddToBoard}
                  onCreateBoard={handleCreateBoard}
                  onNotesSaved={handleStrategyNotesSaved}
                />
              ))}
            </div>
          )}
        </div>
      </div>}
      </>}

      <CompareTray ads={compareAds} onRemove={id => setCompareIds(ids => ids.filter(item => item !== id))} onClear={() => setCompareIds([])} onOpen={() => setCompareOpen(true)} />
      {compareOpen && <ComparePanel ads={compareAds} onClose={() => setCompareOpen(false)} onInspect={ad => { setCompareOpen(false); inspectCreative(ad); }} />}

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
      <ExternalResearchImportModal
        open={showExternalImportModal}
        onClose={() => setShowExternalImportModal(false)}
        onImport={handleExternalResearchImport}
        importing={importingIntel}
        defaultVertical={currentVerticalLabel}
      />
      <ResearchDetailDrawer ad={detailAd} activeVertical={activeVertical} advertiserSnapshot={advertiserSnapshot} retainedVisuals={browseAds} onClose={closeDetail} onInspect={inspectCreative} onExploreAdvertiser={exploreAdvertiser} onBack={goBackInDetail} canGoBack={detailHistory.length > 1} onPreviousResult={() => inspectAdjacentResult(-1)} onNextResult={() => inspectAdjacentResult(1)} canGoPrevious={detailResultIndex > 0} canGoNext={detailResultIndex >= 0 && detailResultIndex < detailResults.length - 1} resultPosition={detailResultIndex >= 0 ? { current: detailResultIndex + 1, total: detailResults.length } : null} onNotesSaved={handleStrategyNotesSaved} onMediaSaved={handleResearchMediaSaved} onReviewSaved={handleResearchReviewSaved} onBriefSaved={handleResearchReviewSaved} boards={boards} onAddToBoard={handleAddToBoard} onCreateBoard={handleCreateBoard} onBuild={(ad) => { closeDetail(); handleUseAsInspiration(ad); }} />
    </div>
  );
}
