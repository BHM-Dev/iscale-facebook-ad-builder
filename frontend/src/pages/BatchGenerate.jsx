import React, { useState, useRef, useCallback, useEffect } from 'react';
import { Plus, X, Zap, CheckCircle, AlertCircle, Clock, Upload, Image, ArrowRight, RefreshCw, Repeat2, Rocket, Loader } from 'lucide-react';
import { Link, useSearchParams } from 'react-router-dom';
import { useToast } from '../context/ToastContext';
import { authFetch } from '../lib/facebookApi';
import BatchPushModal from '../components/BatchPushModal';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1';

const SIZE_OPTIONS = [
  { id: 'square',   label: 'Square',   sub: '1:1 · Feed',    width: 1080, height: 1080 },
  { id: 'portrait', label: 'Portrait', sub: '4:5 · Feed',    width: 1080, height: 1350 },
  { id: 'story',    label: 'Story',    sub: '9:16 · Stories', width: 1080, height: 1920 },
];

const CTA_OPTIONS = [
  'Learn More',
  'Get My Quote',
  'See My Rate',
  'Check If I Qualify',
  'Compare Rates',
  'Get a Free Quote',
  'See Options',
  'Find Out Now',
  'Get Started',
  'Apply Now',
  'Contact Us',
  'Sign Up',
];

function newVariant(index = 0) {
  return { id: Date.now() + index, headline: '', body: '', cta: 'Get My Quote' };
}

// ── Status badge ──────────────────────────────────────────────────────────────
function StatusBadge({ status }) {
  if (status === 'idle')       return <span className="text-xs text-gray-400 flex items-center gap-1"><Clock size={11} /> Waiting</span>;
  if (status === 'generating') return <span className="text-xs text-indigo-600 flex items-center gap-1 animate-pulse"><RefreshCw size={11} className="animate-spin" /> Generating…</span>;
  if (status === 'done')       return <span className="text-xs text-green-600 flex items-center gap-1"><CheckCircle size={11} /> Saved to library</span>;
  if (status === 'failed')     return <span className="text-xs text-red-500 flex items-center gap-1"><AlertCircle size={11} /> Failed</span>;
  return null;
}

// ── Result card ───────────────────────────────────────────────────────────────
function ResultCard({ variant, sizeLabel, result, resultKey, onRetry }) {
  const { status, imageUrl, error } = result;
  const [elapsed, setElapsed] = React.useState(0);

  React.useEffect(() => {
    if (status !== 'generating') { setElapsed(0); return; }
    const t = setInterval(() => setElapsed(s => s + 1), 1000);
    return () => clearInterval(t);
  }, [status]);

  const elapsedLabel = elapsed > 0
    ? elapsed < 60 ? `${elapsed}s` : `${Math.floor(elapsed / 60)}m ${elapsed % 60}s`
    : null;

  return (
    <div className={`bg-white rounded-xl border overflow-hidden transition-shadow ${
      status === 'done' ? 'border-green-200 shadow-sm' :
      status === 'failed' ? 'border-red-200' :
      status === 'generating' ? 'border-indigo-200 shadow-md' :
      'border-gray-200'
    }`}>
      {/* Image area */}
      <div className="aspect-square bg-gray-50 relative overflow-hidden">
        {status === 'done' && imageUrl ? (
          <img src={imageUrl} alt={variant.headline} className="w-full h-full object-cover" />
        ) : status === 'generating' ? (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-3">
            <div className="w-10 h-10 rounded-full border-2 border-indigo-200 border-t-indigo-600 animate-spin" />
            <span className="text-xs text-indigo-500 font-medium">Generating image…</span>
            {elapsedLabel && <span className="text-xs text-indigo-400">{elapsedLabel}</span>}
          </div>
        ) : status === 'failed' ? (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 px-4 text-center">
            <AlertCircle size={24} className="text-red-400" />
            <span className="text-xs text-red-500">{error || 'Generation failed'}</span>
            <button
              onClick={() => onRetry(resultKey)}
              className="mt-1 text-xs text-red-600 underline hover:no-underline"
            >
              Retry
            </button>
          </div>
        ) : (
          <div className="absolute inset-0 flex items-center justify-center">
            <Clock size={24} className="text-gray-300" />
          </div>
        )}
      </div>

      {/* Copy summary */}
      <div className="p-3 border-t border-gray-100">
        <div className="text-xs font-semibold text-gray-800 truncate leading-snug">
          {variant.headline || <span className="text-gray-400 italic">No headline</span>}
        </div>
        <div className="mt-1 flex items-center justify-between">
          <span className="text-xs text-gray-400 truncate max-w-[60%]">{sizeLabel} · {variant.cta}</span>
          <StatusBadge status={status} />
        </div>
      </div>
    </div>
  );
}

// Helper: parse result key → { variantId (Number), sizeId (string) }
function parseResultKey(key) {
  const dashIdx = key.lastIndexOf('-');
  return {
    variantId: Number(key.substring(0, dashIdx)),
    sizeId: key.substring(dashIdx + 1),
  };
}

// ── Main page ─────────────────────────────────────────────────────────────────
export default function BatchGenerate() {
  const { showSuccess, showError } = useToast();
  const [searchParams] = useSearchParams();

  // URL params from "Iterate →" button on Performance page
  const iterateAdId       = searchParams.get('adId')       || '';
  const iterateAdName     = searchParams.get('adName')     || '';
  const iterateAdsetName  = searchParams.get('adsetName')  || '';
  const iterateCampaignId = searchParams.get('campaignId') || ''; // Meta campaign ID — pre-selects campaign in BatchPushModal
  const iterateAdsetId    = searchParams.get('adsetId')    || ''; // Meta adset ID — pre-selects "clone from" in BatchPushModal

  // Parse the meaningful niche segment from a verbose ad set name.
  // Handles two naming patterns:
  //   "Apr. 13 - Religious Organizations - Batch 1 - ..."  → "Religious Organizations"
  //   "Jan. 5 - SCALE - Plumbing - ..."                    → "Plumbing"
  // When parts[1] is a known status keyword, skip it and take parts[2].
  const STATUS_KEYWORDS = ['SCALE', 'PAUSE', 'PAUSED', 'TEST', 'NICHE TESTING', 'TESTING', 'CUT', 'HOLD', 'WATCH', 'ACTIVE'];
  const extractNiche = (adsetName) => {
    if (!adsetName) return '';
    const parts = adsetName.split(' - ');
    if (parts.length < 2) return adsetName;
    if (STATUS_KEYWORDS.includes(parts[1]?.trim().toUpperCase()) && parts.length >= 3) {
      return parts[2].trim();
    }
    return parts[1].trim();
  };

  // Reference image
  const [refImageUrl, setRefImageUrl] = useState('');
  const [refImagePreview, setRefImagePreview] = useState('');
  const [uploadingRef, setUploadingRef] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef(null);

  // Settings — multi-size (array, min 1 selected). Persisted to localStorage.
  const [selectedSizes, setSelectedSizes] = useState(() => {
    try {
      const saved = localStorage.getItem('batchSelectedSizes');
      if (saved) {
        const parsed = JSON.parse(saved);
        if (Array.isArray(parsed) && parsed.length > 0) return parsed;
      }
    } catch (_) {}
    return ['square'];
  });
  const [niche, setNiche] = useState('');
  const [iterateLinkUrl, setIterateLinkUrl] = useState(''); // destination URL from source ad creative

  // Text overlay
  const [overlayEnabled, setOverlayEnabled] = useState(true);
  const [overlayNicheLine, setOverlayNicheLine] = useState('');
  const [overlayOfferLine, setOverlayOfferLine] = useState('From $24.95/Month');
  // Logo: persisted in localStorage so Joel doesn't re-upload every session
  const [overlayLogoUrl, setOverlayLogoUrl] = useState(() => {
    try { return localStorage.getItem('overlayLogoUrl') || ''; } catch (_) { return ''; }
  });
  const [overlayLogoPreview, setOverlayLogoPreview] = useState(() => {
    try { return localStorage.getItem('overlayLogoUrl') || ''; } catch (_) { return ''; }
  });
  const [uploadingLogo, setUploadingLogo] = useState(false);
  const logoFileInputRef = useRef(null);

  const toggleSize = useCallback((sizeId) => {
    setSelectedSizes(prev => {
      if (prev.includes(sizeId)) {
        if (prev.length === 1) return prev; // must keep at least one
        const next = prev.filter(s => s !== sizeId);
        localStorage.setItem('batchSelectedSizes', JSON.stringify(next));
        return next;
      }
      const next = [...prev, sizeId];
      localStorage.setItem('batchSelectedSizes', JSON.stringify(next));
      return next;
    });
  }, []);

  // Variants
  const [variants, setVariants] = useState([newVariant(0), newVariant(1)]);

  // Pre-fill variants if arriving from Ad Remix "Batch Generate" button.
  // New format: array of concepts (one per remix variation).
  // Legacy format: single object — pre-fills Variant 1 only.
  // Also reads pendingBatchNiche (set by AdRemix) to auto-populate the niche field.
  useEffect(() => {
    const raw = localStorage.getItem('pendingBatchCopy');
    if (!raw) return;
    try {
      const parsed = JSON.parse(raw);
      localStorage.removeItem('pendingBatchCopy');
      if (Array.isArray(parsed) && parsed.length > 0) {
        // Replace all variants with one per remix concept
        setVariants(parsed.map((copy, i) => ({
          ...newVariant(i),
          headline: copy.headline || '',
          body: copy.body || '',
          cta: copy.cta || 'Get My Quote',
        })));
      } else if (parsed && typeof parsed === 'object') {
        // Legacy single-copy format
        setVariants(prev => prev.map((v, i) =>
          i === 0
            ? { ...v, headline: parsed.headline || '', body: parsed.body || '', cta: parsed.cta || v.cta }
            : v
        ));
      }
    } catch (e) { /* malformed — ignore */ }

    // Auto-populate niche from Ad Remix handoff (parsed from ad set name upstream)
    const storedNiche = localStorage.getItem('pendingBatchNiche');
    if (storedNiche) {
      setNiche(storedNiche);
      localStorage.removeItem('pendingBatchNiche');
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Auto-populate niche from the "Iterate" URL path (adsetName param from Campaign Performance)
  useEffect(() => {
    if (!iterateAdsetName) return;
    const parsed = extractNiche(iterateAdsetName);
    if (parsed) setNiche(parsed);
  }, [iterateAdsetName]); // eslint-disable-line react-hooks/exhaustive-deps

  // Keep overlay niche label in sync with the Niche / Context field.
  // If Joel wants a different label he can edit the Niche Label field directly.
  useEffect(() => {
    setOverlayNicheLine(niche);
  }, [niche]); // eslint-disable-line react-hooks/exhaustive-deps

  // Fetch ad creative data if arriving via the "Iterate" path (adId URL param)
  useEffect(() => {
    if (!iterateAdId) return;
    authFetch(`${API_URL}/facebook/ads/${iterateAdId}/creative`)
      .then(res => res.ok ? res.json() : null)
      .then(creative => {
        if (!creative) return;
        setVariants(prev => prev.map((v, i) =>
          i === 0
            ? { ...v, headline: creative.headline || '', body: creative.body || '' }
            : v
        ));
        if (creative.image_url) {
          setRefImagePreview(creative.image_url);
          setRefImageUrl(creative.image_url);
        }
        // Pre-fill destination URL so Joel doesn't have to type it in the push modal
        if (creative.link_url) setIterateLinkUrl(creative.link_url);
      })
      .catch(() => {});
  }, [iterateAdId]); // eslint-disable-line react-hooks/exhaustive-deps

  // Auto-trigger AI variant generation once when arriving via Iterate with a pre-filled headline.
  // The ref prevents re-firing after the AI variants themselves fill in more headlines.
  const autoTriggeredVariants = useRef(false);
  useEffect(() => {
    if (!iterateAdId) return;
    if (autoTriggeredVariants.current) return;
    if (!variants[0]?.headline.trim()) return;
    autoTriggeredVariants.current = true;
    generateAIVariants();
  }, [variants, iterateAdId]); // eslint-disable-line react-hooks/exhaustive-deps

  // Generation state
  const [running, setRunning] = useState(false);
  const [results, setResults] = useState({});  // `${variantId}-${sizeId}` → { status, imageUrl, error }
  const [allDone, setAllDone] = useState(false);
  const [generatingProgress, setGeneratingProgress] = useState(0);
  const [generatingTotal, setGeneratingTotal] = useState(0);
  const [batchPushOpen, setBatchPushOpen] = useState(false);
  const [generatingAIVariants, setGeneratingAIVariants] = useState(false);

  // ── Ref image upload ────────────────────────────────────────────────────────
  const uploadRefImage = useCallback(async (file) => {
    if (!file || !file.type.startsWith('image/')) {
      showError('Please upload an image file (JPG, PNG, WebP)');
      return;
    }
    setUploadingRef(true);
    setRefImagePreview(URL.createObjectURL(file));
    try {
      const formData = new FormData();
      formData.append('file', file);
      const res = await authFetch(`${API_URL}/uploads/`, {
        method: 'POST',
        body: formData,
      });
      if (!res.ok) throw new Error('Upload failed');
      const data = await res.json();
      const url = data.url || data.file_url || data.path;
      const absUrl = url.startsWith('http') ? url : `${window.location.origin}${url}`;
      setRefImageUrl(absUrl);
    } catch (e) {
      showError(`Image upload failed: ${e.message}`);
      setRefImagePreview('');
    } finally {
      setUploadingRef(false);
    }
  }, [showError]);

  const handleFileDrop = useCallback((e) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files?.[0];
    if (file) uploadRefImage(file);
  }, [uploadRefImage]);

  // ── Logo upload (overlay) ───────────────────────────────────────────────────
  const uploadLogoImage = useCallback(async (file) => {
    if (!file || !file.type.startsWith('image/')) {
      showError('Please upload an image file (PNG with transparency works best)');
      return;
    }
    setUploadingLogo(true);
    setOverlayLogoPreview(URL.createObjectURL(file));
    try {
      const formData = new FormData();
      formData.append('file', file);
      const res = await authFetch(`${API_URL}/uploads/`, {
        method: 'POST',
        body: formData,
      });
      if (!res.ok) throw new Error('Upload failed');
      const data = await res.json();
      const url = data.url || data.file_url || data.path;
      const absUrl = url.startsWith('http') ? url : `${window.location.origin}${url}`;
      setOverlayLogoUrl(absUrl);
      setOverlayLogoPreview(absUrl);
      try { localStorage.setItem('overlayLogoUrl', absUrl); } catch (_) {}
    } catch (e) {
      showError(`Logo upload failed: ${e.message}`);
      setOverlayLogoPreview('');
    } finally {
      setUploadingLogo(false);
    }
  }, [showError]);

  // ── Variant management ──────────────────────────────────────────────────────
  const addVariant = () => setVariants(prev => [...prev, newVariant(prev.length)]);
  const removeVariant = (id) => setVariants(prev => prev.filter(v => v.id !== id));
  const updateVariant = (id, field, value) =>
    setVariants(prev => prev.map(v => v.id === id ? { ...v, [field]: value } : v));

  // ── Generation ──────────────────────────────────────────────────────────────
  const generateOne = useCallback(async (variant, sizeConfig) => {
    const key = `${variant.id}-${sizeConfig.id}`;
    setResults(prev => ({ ...prev, [key]: { status: 'generating', imageUrl: null, error: null } }));

    // When a reference image is provided, we keep a custom prompt so Flux maintains
    // the visual style of that reference. When there's no reference image, we pass
    // the copy + niche as structured fields and let the backend AI (Claude Haiku)
    // generate a proper Flux scene description — it produces far better results than
    // a hand-built string, and it knows the niche context.
    const refPrompt = refImageUrl
      ? `Maintain the exact visual composition, style, lighting, and aesthetic of the reference image.${niche ? ` Ad for ${niche}.` : ''} Keep the same background setting, subject positioning, and overall mood.${variant.headline ? ` The ad headline is: "${variant.headline}".` : ''} High quality photorealistic advertising photography.`
      : null;

    const payload = {
      ...(refPrompt ? { customPrompt: refPrompt } : {}),
      ...(niche ? { niche } : {}),
      count: 1,
      imageSizes: [{ width: sizeConfig.width, height: sizeConfig.height, name: sizeConfig.label }],
      copy: { headline: variant.headline, body: variant.body, cta: variant.cta },
      ...(refImageUrl ? { productShots: [refImageUrl], useProductImage: true } : {}),
      ...(overlayEnabled ? {
        overlay_enabled: true,
        overlay_niche_line: overlayNicheLine,
        overlay_offer_line: overlayOfferLine,
        overlay_cta: variant.cta,
        ...(overlayLogoUrl ? { overlay_logo_url: overlayLogoUrl } : {}),
      } : {}),
    };

    try {
      const res = await authFetch(`${API_URL}/generated-ads/generate-image`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'Generation failed');
      }
      const data = await res.json();
      const imageUrl = data.images?.[0]?.url;
      if (!imageUrl) throw new Error('No image returned');

      // Save to Generated Ads library
      const adId = crypto.randomUUID();
      await authFetch(`${API_URL}/generated-ads/batch`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ads: [{
            id: adId,
            imageUrl,
            headline: variant.headline,
            body: variant.body,
            cta: variant.cta,
            sizeName: sizeConfig.label,
            dimensions: `${sizeConfig.width}x${sizeConfig.height}`,
            mediaType: 'image',
          }],
        }),
      }).catch(() => {});

      setResults(prev => ({ ...prev, [key]: { status: 'done', imageUrl, error: null } }));
      return 'done';
    } catch (e) {
      const msg = e.message === 'Failed to fetch' ? 'Network timeout — try again' : e.message;
      setResults(prev => ({ ...prev, [key]: { status: 'failed', imageUrl: null, error: msg } }));
      return 'failed';
    }
  }, [niche, refImageUrl, overlayEnabled, overlayNicheLine, overlayOfferLine, overlayLogoUrl]);

  const handleGenerate = useCallback(async () => {
    // When overlay is on, headline is optional — the niche label + offer line carry the messaging.
    // When overlay is off, headline is required as the primary ad copy.
    const valid = overlayEnabled
      ? variants.filter(v => v.headline.trim() || v.body.trim() || overlayNicheLine.trim() || overlayOfferLine.trim())
      : variants.filter(v => v.headline.trim());
    if (valid.length === 0) {
      showError(overlayEnabled
        ? 'Fill in at least one variant or add a Niche Label / Offer Line to the overlay'
        : 'Add at least one headline before generating');
      return;
    }

    const sizes = SIZE_OPTIONS.filter(s => selectedSizes.includes(s.id));
    const total = valid.length * sizes.length;

    setRunning(true);
    setAllDone(false);
    setGeneratingProgress(0);
    setGeneratingTotal(total);

    // Initialize all as idle
    const init = {};
    valid.forEach(v => {
      sizes.forEach(s => {
        init[`${v.id}-${s.id}`] = { status: 'idle', imageUrl: null, error: null };
      });
    });
    setResults(init);

    // Sequential — one at a time to avoid rate limiting
    let completed = 0;
    let succeeded = 0;
    let failed = 0;
    for (const variant of valid) {
      for (const size of sizes) {
        const outcome = await generateOne(variant, size);
        if (outcome === 'done') succeeded++;
        else failed++;
        completed++;
        setGeneratingProgress(completed);
      }
    }

    setRunning(false);
    setAllDone(true);
    if (failed === 0) {
      showSuccess(`Done — ${succeeded} image${succeeded !== 1 ? 's' : ''} generated and saved`);
    } else if (succeeded === 0) {
      showError(`All ${failed} image${failed !== 1 ? 's' : ''} failed to generate`);
    } else {
      showSuccess(`Done — ${succeeded} saved, ${failed} failed`);
    }
  }, [variants, selectedSizes, generateOne, overlayEnabled, overlayNicheLine, overlayOfferLine, showSuccess, showError]);

  const handleRetry = useCallback(async (resultKey) => {
    const { variantId, sizeId } = parseResultKey(resultKey);
    const variant = variants.find(v => v.id === variantId);
    const sizeConfig = SIZE_OPTIONS.find(s => s.id === sizeId);
    if (!variant || !sizeConfig) return;
    await generateOne(variant, sizeConfig);
  }, [variants, generateOne]);

  // Generate 3 AI copy variants from Variant 1 using the remix-variations endpoint
  const generateAIVariants = useCallback(async () => {
    const source = variants.find(v => v.headline.trim());
    if (!source) { showError('Add a headline to Variant 1 first'); return; }
    setGeneratingAIVariants(true);
    try {
      const res = await authFetch(`${API_URL}/copy-generation/remix-variations`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          source_headline: source.headline,
          source_body: source.body || '',
          hook: source.headline,
          niche: niche || extractNiche(iterateAdsetName),
          vertical: 'commercial_insurance',
        }),
      });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      const aiVariants = Array.isArray(data?.variations) ? data.variations : Array.isArray(data) ? data : [];
      if (!aiVariants.length) throw new Error('No variations returned');

      // Fill or append up to 3 new variants after the source
      setVariants(prev => {
        const updated = [...prev];
        aiVariants.slice(0, 3).forEach((v, i) => {
          const slotIndex = updated.findIndex((u, idx) => idx > 0 && !u.headline.trim());
          const newVariant = {
            id: Date.now() + i,
            headline: v.headline || '',
            body: v.body || '',
            cta: updated[0]?.cta || 'Get My Quote',
          };
          if (slotIndex !== -1) {
            updated[slotIndex] = newVariant;
          } else {
            updated.push(newVariant);
          }
        });
        return updated;
      });
      showSuccess(`${aiVariants.length} AI copy variants generated`);
    } catch (e) {
      showError(`AI variant generation failed: ${e.message}`);
    } finally {
      setGeneratingAIVariants(false);
    }
  }, [variants, niche, iterateAdsetName, showSuccess, showError]);

  const overlayHasContent = overlayEnabled && (overlayNicheLine.trim() || niche.trim() || overlayOfferLine.trim());
  const filledVariants = variants.filter(v => v.headline.trim() || v.body.trim() || overlayHasContent);
  const totalToGenerate = filledVariants.length * selectedSizes.length;
  const hasResults = Object.keys(results).length > 0;

  return (
    <div className="max-w-6xl mx-auto space-y-8">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-2">
            <Zap size={22} className="text-amber-500" />
            Batch Creative Generator
          </h1>
          <p className="text-gray-500 text-sm mt-0.5">
            Upload a reference image · add your copy variants · generate images in all selected sizes
          </p>
          {/* Iterate banner — shown when arriving from Performance page */}
          {iterateAdName && (
            <div className="mt-3 flex items-center gap-2 px-3 py-2 rounded-lg bg-indigo-50 border border-indigo-100 text-xs text-indigo-700 font-medium w-fit">
              <Repeat2 size={13} />
              Iterating from: <span className="font-semibold truncate max-w-[300px]" title={iterateAdName}>{iterateAdName}</span>
            </div>
          )}
        </div>
        {filledVariants.length > 0 && !running && (
          <button
            onClick={handleGenerate}
            className="flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold text-white shadow-sm hover:opacity-90 transition-opacity"
            style={{ backgroundColor: '#2D2463' }}
          >
            <Zap size={14} />
            Generate {totalToGenerate} Image{totalToGenerate !== 1 ? 's' : ''}
          </button>
        )}
        {running && (
          <div className="flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-medium text-indigo-600 bg-indigo-50 border border-indigo-100">
            <RefreshCw size={14} className="animate-spin" />
            Generating {generatingProgress} of {generatingTotal}…
          </div>
        )}
      </div>

      {/* Two-column setup */}
      <div className="grid grid-cols-1 lg:grid-cols-[320px_1fr] gap-6 items-start">

        {/* Left — Reference image + settings */}
        <div className="space-y-5">

          {/* Reference Image */}
          <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
            <div className="px-4 py-3 border-b border-gray-100">
              <h2 className="text-sm font-semibold text-gray-800 flex items-center gap-1.5">
                <Image size={14} className="text-gray-400" />
                Reference Image
                <span className="ml-1 text-xs font-normal text-gray-400">optional but recommended</span>
              </h2>
            </div>

            <div className="p-4">
              {refImagePreview ? (
                <div className="relative group">
                  <img
                    src={refImagePreview}
                    alt="Reference"
                    className="w-full aspect-square object-cover rounded-lg border border-gray-200"
                  />
                  {uploadingRef && (
                    <div className="absolute inset-0 bg-white/80 rounded-lg flex items-center justify-center">
                      <RefreshCw size={20} className="animate-spin text-indigo-500" />
                    </div>
                  )}
                  {!uploadingRef && (
                    <button
                      onClick={() => { setRefImagePreview(''); setRefImageUrl(''); }}
                      className="absolute top-2 right-2 bg-white rounded-full p-1 shadow-md opacity-0 group-hover:opacity-100 transition-opacity text-gray-500 hover:text-red-500"
                    >
                      <X size={13} />
                    </button>
                  )}
                  {refImageUrl && (
                    <div className="mt-2 flex items-center gap-1.5 text-xs text-green-600">
                      <CheckCircle size={12} /> Ready to use as reference
                    </div>
                  )}
                </div>
              ) : (
                <div
                  onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
                  onDragLeave={() => setDragOver(false)}
                  onDrop={handleFileDrop}
                  onClick={() => fileInputRef.current?.click()}
                  className={`w-full aspect-square rounded-lg border-2 border-dashed flex flex-col items-center justify-center cursor-pointer transition-colors ${
                    dragOver ? 'border-indigo-400 bg-indigo-50' : 'border-gray-200 hover:border-indigo-300 hover:bg-gray-50'
                  }`}
                >
                  <Upload size={24} className="text-gray-300 mb-2" />
                  <span className="text-sm font-medium text-gray-500">Drop image here</span>
                  <span className="text-xs text-gray-400 mt-0.5">or click to browse</span>
                  <span className="text-xs text-gray-300 mt-3">JPG · PNG · WebP</span>
                </div>
              )}
              <input
                ref={fileInputRef}
                type="file"
                accept="image/jpeg,image/png,image/webp"
                className="hidden"
                onChange={(e) => { const f = e.target.files?.[0]; if (f) uploadRefImage(f); }}
              />
            </div>
          </div>

          {/* Image Sizes — multi-select checkboxes */}
          <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
            <div className="px-4 py-3 border-b border-gray-100">
              <h2 className="text-sm font-semibold text-gray-800">
                Image Sizes
                <span className="ml-1 text-xs font-normal text-gray-400">select all that apply</span>
              </h2>
            </div>
            <div className="p-4 space-y-2">
              {SIZE_OPTIONS.map(s => {
                const checked = selectedSizes.includes(s.id);
                return (
                  <label
                    key={s.id}
                    className={`flex items-center gap-3 p-3 rounded-lg border cursor-pointer transition-colors ${
                      checked
                        ? 'border-indigo-300 bg-indigo-50'
                        : 'border-gray-200 hover:border-gray-300 hover:bg-gray-50'
                    }`}
                  >
                    <input
                      type="checkbox"
                      value={s.id}
                      checked={checked}
                      onChange={() => toggleSize(s.id)}
                      className="text-indigo-600 rounded"
                    />
                    <div>
                      <div className="text-sm font-medium text-gray-800">{s.label}</div>
                      <div className="text-xs text-gray-400">{s.sub}</div>
                    </div>
                  </label>
                );
              })}
              {selectedSizes.length > 1 && (
                <p className="text-xs text-indigo-600 pt-1">
                  {selectedSizes.length} sizes selected — {filledVariants.length > 0 ? `${filledVariants.length * selectedSizes.length} images total` : 'fill in variants to see total'}
                </p>
              )}
            </div>
          </div>

          {/* Optional niche context */}
          <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
            <div className="px-4 py-3 border-b border-gray-100">
              <h2 className="text-sm font-semibold text-gray-800">
                Niche / Context
                <span className="ml-1 text-xs font-normal text-gray-400">optional</span>
              </h2>
            </div>
            <div className="p-4">
              <input
                type="text"
                placeholder="e.g. Auto Insurance, Reverse Mortgage, Debt Relief"
                className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-indigo-400"
                value={niche}
                onChange={e => setNiche(e.target.value)}
              />
              <p className="text-xs text-gray-400 mt-1.5">Gives the AI context for the image style and subject matter</p>
            </div>
          </div>

          {/* Text overlay */}
          <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
            <div className="px-4 py-3 border-b border-gray-100 flex items-center justify-between">
              <div>
                <h2 className="text-sm font-semibold text-gray-800">Text Overlay</h2>
                <p className="text-xs text-gray-400 mt-0.5">Bakes headline + offer + CTA button into the image</p>
              </div>
              <button
                type="button"
                onClick={() => setOverlayEnabled(v => !v)}
                className={`relative inline-flex h-5 w-9 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 focus:outline-none ${
                  overlayEnabled ? 'bg-indigo-600' : 'bg-gray-200'
                }`}
                aria-pressed={overlayEnabled}
              >
                <span
                  className={`pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out ${
                    overlayEnabled ? 'translate-x-4' : 'translate-x-0'
                  }`}
                />
              </button>
            </div>
            {overlayEnabled && (
              <div className="p-4 space-y-3">
                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1">
                    Niche Label
                    <span className="ml-1 font-normal text-gray-400">optional</span>
                  </label>
                  <input
                    type="text"
                    placeholder="e.g. Winery Business Insurance"
                    className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-indigo-400"
                    value={overlayNicheLine}
                    onChange={e => setOverlayNicheLine(e.target.value)}
                  />
                  <p className="text-xs text-gray-400 mt-1">Auto-fills from Niche / Context. Edit to override.</p>
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1">Offer Line</label>
                  <input
                    type="text"
                    placeholder="From $24.95/Month"
                    className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-indigo-400"
                    value={overlayOfferLine}
                    onChange={e => setOverlayOfferLine(e.target.value)}
                  />
                  <p className="text-xs text-gray-400 mt-1">Appears below the headline. Leave blank to omit.</p>
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1">
                    Brand Logo
                    <span className="ml-1 font-normal text-gray-400">optional</span>
                  </label>
                  <input
                    type="file"
                    accept="image/*"
                    className="hidden"
                    ref={logoFileInputRef}
                    onChange={e => { const f = e.target.files?.[0]; if (f) uploadLogoImage(f); e.target.value = ''; }}
                  />
                  {overlayLogoPreview ? (
                    <div className="flex items-center gap-3">
                      <img
                        src={overlayLogoPreview}
                        alt="Logo preview"
                        className="h-10 w-auto rounded border border-gray-200 bg-gray-50 object-contain p-1"
                      />
                      <div className="flex flex-col gap-1">
                        <button
                          type="button"
                          onClick={() => logoFileInputRef.current?.click()}
                          disabled={uploadingLogo}
                          className="text-xs text-indigo-600 hover:text-indigo-800 disabled:opacity-40"
                        >
                          {uploadingLogo ? 'Uploading…' : 'Replace'}
                        </button>
                        <button
                          type="button"
                          onClick={() => {
                            setOverlayLogoUrl('');
                            setOverlayLogoPreview('');
                            try { localStorage.removeItem('overlayLogoUrl'); } catch (_) {}
                          }}
                          className="text-xs text-red-400 hover:text-red-600"
                        >
                          Remove
                        </button>
                      </div>
                    </div>
                  ) : (
                    <button
                      type="button"
                      onClick={() => logoFileInputRef.current?.click()}
                      disabled={uploadingLogo}
                      className="flex items-center gap-2 text-sm border border-dashed border-gray-300 rounded-lg px-3 py-2 w-full text-gray-500 hover:border-indigo-400 hover:text-indigo-600 disabled:opacity-40 transition-colors"
                    >
                      <Upload size={13} />
                      {uploadingLogo ? 'Uploading…' : 'Upload logo (PNG recommended)'}
                    </button>
                  )}
                  <p className="text-xs text-gray-400 mt-1">Placed in a white badge top-right. Saved for future sessions.</p>
                </div>
                <div className="rounded-lg bg-amber-50 border border-amber-200 px-3 py-2">
                  <p className="text-xs text-amber-700">
                    <span className="font-semibold">Layout (top to bottom):</span> Niche label → Headline → Offer line → CTA button. Any empty field is skipped — no gap left behind. Logo badge top-right if uploaded.
                  </p>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Right — Copy variants */}
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-gray-800">
              Copy Variants
              <span className="ml-2 text-xs font-normal text-gray-400">
                {variants.length} variant{variants.length !== 1 ? 's' : ''} · {selectedSizes.length} size{selectedSizes.length !== 1 ? 's' : ''} each
              </span>
            </h2>
            <div className="flex items-center gap-3">
              {/* AI variant generation — requires Variant 1 to have a headline */}
              <button
                onClick={generateAIVariants}
                disabled={running || generatingAIVariants || !variants.find(v => v.headline.trim())}
                className="flex items-center gap-1.5 text-xs font-medium text-purple-600 hover:text-purple-800 disabled:opacity-40 transition-colors"
                title="Use AI to generate 3 copy variations from Variant 1"
              >
                {generatingAIVariants
                  ? <><Loader size={12} className="animate-spin" /> Generating...</>
                  : <><Zap size={12} /> AI Generate Variants</>}
              </button>
              <button
                onClick={addVariant}
                disabled={running}
                className="flex items-center gap-1.5 text-xs font-medium text-indigo-600 hover:text-indigo-800 disabled:opacity-40 transition-colors"
              >
                <Plus size={13} /> Add Variant
              </button>
            </div>
          </div>

          <div className="space-y-3">
            {variants.map((variant, idx) => {
              const variantResults = Object.entries(results).filter(([key]) => parseResultKey(key).variantId === variant.id);
              const anyGenerating = variantResults.some(([, r]) => r.status === 'generating');
              const allDoneForVariant = variantResults.length > 0 && variantResults.every(([, r]) => r.status === 'done');
              const anyFailed = variantResults.some(([, r]) => r.status === 'failed');

              return (
                <div
                  key={variant.id}
                  className={`bg-white rounded-xl border shadow-sm overflow-hidden transition-all ${
                    allDoneForVariant ? 'border-green-200' :
                    anyFailed ? 'border-red-200' :
                    anyGenerating ? 'border-indigo-300 ring-1 ring-indigo-100' :
                    'border-gray-200'
                  }`}
                >
                  {/* Card header */}
                  <div className={`px-4 py-2.5 border-b flex items-center justify-between ${
                    allDoneForVariant ? 'bg-green-50 border-green-100' :
                    anyFailed ? 'bg-red-50 border-red-100' :
                    anyGenerating ? 'bg-indigo-50 border-indigo-100' :
                    'bg-gray-50 border-gray-100'
                  }`}>
                    <span className="text-xs font-semibold text-gray-600">Variant {idx + 1}</span>
                    <div className="flex items-center gap-3">
                      {anyGenerating && <StatusBadge status="generating" />}
                      {allDoneForVariant && <StatusBadge status="done" />}
                      {variants.length > 1 && !running && (
                        <button
                          onClick={() => removeVariant(variant.id)}
                          className="text-gray-300 hover:text-red-400 transition-colors"
                        >
                          <X size={13} />
                        </button>
                      )}
                    </div>
                  </div>

                  {/* Fields */}
                  <div className="p-4 space-y-3">
                    <div>
                      <label className="block text-xs font-medium text-gray-500 mb-1">Headline <span className="text-gray-400 font-normal">· under 40 chars</span></label>
                      <input
                        type="text"
                        placeholder="Your rate went up again. You have options."
                        className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-indigo-400 disabled:bg-gray-50 disabled:text-gray-500"
                        value={variant.headline}
                        onChange={e => updateVariant(variant.id, 'headline', e.target.value)}
                        disabled={running}
                      />
                    </div>
                    <div>
                      <label className="block text-xs font-medium text-gray-500 mb-1">Body Copy <span className="text-gray-400 font-normal">· 100–220 chars</span></label>
                      <textarea
                        rows={3}
                        placeholder="Most drivers don't realize they're overpaying until it's too late. Takes 60 seconds. No commitment."
                        className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-indigo-400 resize-none disabled:bg-gray-50 disabled:text-gray-500"
                        value={variant.body}
                        onChange={e => updateVariant(variant.id, 'body', e.target.value)}
                        disabled={running}
                      />
                      <p className="text-xs text-gray-400 mt-1">Used as ad copy and guides the AI image generation</p>
                    </div>
                    <div>
                      <label className="block text-xs font-medium text-gray-500 mb-1">CTA</label>
                      <select
                        className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-indigo-400 disabled:bg-gray-50"
                        value={variant.cta}
                        onChange={e => updateVariant(variant.id, 'cta', e.target.value)}
                        disabled={running}
                      >
                        {CTA_OPTIONS.map(c => <option key={c} value={c}>{c}</option>)}
                      </select>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>

          {/* Generate button */}
          <button
            onClick={handleGenerate}
            disabled={running || filledVariants.length === 0}
            className="w-full flex items-center justify-center gap-2 py-3 rounded-xl text-sm font-semibold text-white shadow-sm hover:opacity-90 transition-opacity disabled:opacity-40"
            style={{ backgroundColor: '#2D2463' }}
          >
            {running ? (
              <><RefreshCw size={15} className="animate-spin" /> Generating {generatingProgress} of {generatingTotal}…</>
            ) : (
              <><Zap size={15} /> Generate {totalToGenerate} Image{totalToGenerate !== 1 ? 's' : ''}</>
            )}
          </button>

          {filledVariants.length === 0 && (
            <p className="text-xs text-center text-gray-400">Add a headline to at least one variant to generate</p>
          )}
        </div>
      </div>

      {/* Results grid */}
      {hasResults && (
        <div className="space-y-5">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-gray-800">
              Results
              <span className="ml-2 text-xs font-normal text-gray-400">
                {Object.values(results).filter(r => r.status === 'done').length} of {Object.values(results).length} complete
              </span>
            </h2>
            {allDone && (
              <Link
                to="/generated-ads"
                className="flex items-center gap-1 text-xs font-medium text-indigo-600 hover:text-indigo-800 transition-colors"
              >
                View in Library <ArrowRight size={11} />
              </Link>
            )}
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-4">
            {Object.entries(results).map(([key, result]) => {
              const { variantId, sizeId } = parseResultKey(key);
              const variant = variants.find(v => v.id === variantId);
              const sizeConfig = SIZE_OPTIONS.find(s => s.id === sizeId);
              if (!variant) return null;
              return (
                <ResultCard
                  key={key}
                  variant={variant}
                  sizeLabel={sizeConfig?.label || ''}
                  result={result}
                  resultKey={key}
                  onRetry={handleRetry}
                />
              );
            })}
          </div>

          {allDone && (() => {
            // Build the items list for BatchPushModal from all successful results
            const pushItems = Object.entries(results)
              .filter(([, r]) => r.status === 'done' && r.imageUrl)
              .map(([key, r]) => {
                const { variantId, sizeId } = parseResultKey(key);
                const variant = variants.find(v => v.id === variantId);
                const sizeConfig = SIZE_OPTIONS.find(s => s.id === sizeId);
                return {
                  key,
                  imageUrl: r.imageUrl,
                  headline: variant?.headline || '',
                  body: variant?.body || '',
                  cta: 'LEARN_MORE', // BatchGenerate CTAs are display labels, not Meta enums — let modal handle
                  variantName: variant?.headline ? variant.headline.slice(0, 30) : `Variant ${variantId}`,
                  sizeLabel: sizeConfig?.label || sizeId,
                };
              });

            return (
              <div className="flex items-center justify-center gap-3 pt-2">
                <Link
                  to="/generated-ads"
                  className="flex items-center gap-2 px-5 py-2.5 rounded-xl border border-gray-200 text-sm font-medium text-gray-600 bg-white hover:bg-gray-50 transition-colors"
                >
                  View in Library <ArrowRight size={14} />
                </Link>
                {pushItems.length > 0 && (
                  <button
                    onClick={() => setBatchPushOpen(true)}
                    className="flex items-center gap-2 px-6 py-2.5 rounded-xl bg-green-600 text-white text-sm font-medium hover:bg-green-700 transition-colors shadow-sm"
                  >
                    <Rocket size={15} />
                    Push {pushItems.length} Ad{pushItems.length !== 1 ? 's' : ''} to Meta
                  </button>
                )}
              </div>
            );
          })()}
        </div>
      )}

      {/* Batch Push Modal */}
      {batchPushOpen && (() => {
        const pushItems = Object.entries(results)
          .filter(([, r]) => r.status === 'done' && r.imageUrl)
          .map(([key, r]) => {
            const { variantId, sizeId } = parseResultKey(key);
            const variant = variants.find(v => v.id === variantId);
            const sizeConfig = SIZE_OPTIONS.find(s => s.id === sizeId);
            return {
              key,
              imageUrl: r.imageUrl,
              headline: variant?.headline || '',
              body: variant?.body || '',
              cta: 'LEARN_MORE', // CTA_OPTIONS are display labels, not Meta enums — always use enum
              variantName: variant?.headline ? variant.headline.slice(0, 30) : `Variant ${variantId}`,
              sizeLabel: sizeConfig?.label || sizeId,
            };
          });
        return (
          <BatchPushModal
            items={pushItems}
            onClose={() => setBatchPushOpen(false)}
            preselectedCampaignId={iterateCampaignId}
            preselectedAdsetId={iterateAdsetId}
            preselectedAdsetName={iterateAdsetName}
            preselectedWebsiteUrl={iterateLinkUrl}
          />
        );
      })()}
    </div>
  );
}
