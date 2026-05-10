import React, { useState, useRef, useCallback, useEffect } from 'react';
import { Plus, X, Zap, CheckCircle, AlertCircle, Clock, Upload, Image, ArrowRight, RefreshCw, Repeat2 } from 'lucide-react';
import { Link, useSearchParams } from 'react-router-dom';
import { useToast } from '../context/ToastContext';
import { authFetch } from '../lib/facebookApi';

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
  const iterateAdId      = searchParams.get('adId')     || '';
  const iterateAdName    = searchParams.get('adName')   || '';

  // Reference image
  const [refImageUrl, setRefImageUrl] = useState('');
  const [refImagePreview, setRefImagePreview] = useState('');
  const [uploadingRef, setUploadingRef] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef(null);

  // Settings — multi-size (array, min 1 selected)
  const [selectedSizes, setSelectedSizes] = useState(['square']);
  const [niche, setNiche] = useState('');

  const toggleSize = useCallback((sizeId) => {
    setSelectedSizes(prev => {
      if (prev.includes(sizeId)) {
        if (prev.length === 1) return prev; // must keep at least one
        return prev.filter(s => s !== sizeId);
      }
      return [...prev, sizeId];
    });
  }, []);

  // Variants
  const [variants, setVariants] = useState([newVariant(0), newVariant(1)]);

  // Pre-fill Variant 1 if arriving from Ad Remix "Generate Image" button
  useEffect(() => {
    const raw = localStorage.getItem('pendingBatchCopy');
    if (!raw) return;
    try {
      const copy = JSON.parse(raw);
      localStorage.removeItem('pendingBatchCopy');
      setVariants(prev => prev.map((v, i) =>
        i === 0
          ? { ...v, headline: copy.headline || '', body: copy.body || '', cta: copy.cta || v.cta }
          : v
      ));
    } catch (e) { /* malformed — ignore */ }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Fetch creative data if arriving from Performance page (no niche auto-fill from adset name)
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
      })
      .catch(() => {});
  }, [iterateAdId]); // eslint-disable-line react-hooks/exhaustive-deps

  // Generation state
  const [running, setRunning] = useState(false);
  const [results, setResults] = useState({});  // `${variantId}-${sizeId}` → { status, imageUrl, error }
  const [allDone, setAllDone] = useState(false);
  const [generatingProgress, setGeneratingProgress] = useState(0);
  const [generatingTotal, setGeneratingTotal] = useState(0);

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

  // ── Variant management ──────────────────────────────────────────────────────
  const addVariant = () => setVariants(prev => [...prev, newVariant(prev.length)]);
  const removeVariant = (id) => setVariants(prev => prev.filter(v => v.id !== id));
  const updateVariant = (id, field, value) =>
    setVariants(prev => prev.map(v => v.id === id ? { ...v, [field]: value } : v));

  // ── Generation ──────────────────────────────────────────────────────────────
  const generateOne = useCallback(async (variant, sizeConfig) => {
    const key = `${variant.id}-${sizeConfig.id}`;
    setResults(prev => ({ ...prev, [key]: { status: 'generating', imageUrl: null, error: null } }));

    const contextLine = niche ? ` Professional Facebook advertisement for ${niche}.` : ' Professional Facebook advertisement.';
    const prompt = refImageUrl
      ? `Maintain the exact visual composition, style, lighting, and aesthetic of the reference image.${contextLine} Keep the same background setting, subject positioning, and overall mood. The ad headline is: "${variant.headline}". High quality photorealistic advertising photography.`
      : `Professional Facebook advertisement.${contextLine} Headline: "${variant.headline}". ${variant.body}. Clean, high-quality photorealistic ad creative.`;

    const payload = {
      customPrompt: prompt,
      count: 1,
      imageSizes: [{ width: sizeConfig.width, height: sizeConfig.height, name: sizeConfig.label }],
      copy: { headline: variant.headline, body: variant.body, cta: variant.cta },
      ...(refImageUrl ? { productShots: [refImageUrl], useProductImage: true } : {}),
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
    } catch (e) {
      const msg = e.message === 'Failed to fetch' ? 'Network timeout — try again' : e.message;
      setResults(prev => ({ ...prev, [key]: { status: 'failed', imageUrl: null, error: msg } }));
    }
  }, [niche, refImageUrl]);

  const handleGenerate = useCallback(async () => {
    const valid = variants.filter(v => v.headline.trim());
    if (valid.length === 0) {
      showError('Add at least one headline before generating');
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
    for (const variant of valid) {
      for (const size of sizes) {
        await generateOne(variant, size);
        completed++;
        setGeneratingProgress(completed);
      }
    }

    setRunning(false);
    setAllDone(true);
    showSuccess(`Done — ${total} image${total !== 1 ? 's' : ''} generated and saved`);
  }, [variants, selectedSizes, generateOne, showSuccess, showError]);

  const handleRetry = useCallback(async (resultKey) => {
    const { variantId, sizeId } = parseResultKey(resultKey);
    const variant = variants.find(v => v.id === variantId);
    const sizeConfig = SIZE_OPTIONS.find(s => s.id === sizeId);
    if (!variant || !sizeConfig) return;
    await generateOne(variant, sizeConfig);
  }, [variants, generateOne]);

  const filledVariants = variants.filter(v => v.headline.trim());
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
            <button
              onClick={addVariant}
              disabled={running}
              className="flex items-center gap-1.5 text-xs font-medium text-indigo-600 hover:text-indigo-800 disabled:opacity-40 transition-colors"
            >
              <Plus size={13} /> Add Variant
            </button>
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
                View in Generated Ads Library <ArrowRight size={11} />
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

          {allDone && (
            <div className="flex justify-center pt-2">
              <Link
                to="/generated-ads"
                className="flex items-center gap-2 px-6 py-2.5 rounded-xl border border-indigo-200 text-sm font-medium text-indigo-700 bg-indigo-50 hover:bg-indigo-100 transition-colors"
              >
                View all generated ads <ArrowRight size={14} />
              </Link>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
