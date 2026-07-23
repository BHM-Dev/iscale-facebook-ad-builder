import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { PauseCircle, PlayCircle, RefreshCw, AlertTriangle, TrendingDown, Target, Zap, ChevronDown, ChevronRight, TrendingUp, X, Repeat2, Sparkles, Tag, ChevronLeft, BarChart2, ShieldAlert, MessageSquare, Send, DollarSign, Check } from 'lucide-react';
import { useToast } from '../context/ToastContext';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { authFetch } from '../lib/facebookApi';
import { useBrands } from '../context/BrandContext';
import { useCampaign } from '../context/CampaignContext';

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1';

const METRIC_LABELS = { cpl: 'Cost Per Lead', cpa: 'Cost Per Action', ctr: 'CTR', roas: 'ROAS' };
const METRIC_UNITS  = { cpl: '$', cpa: '$', ctr: '%', roas: 'x' };
const DATE_PRESETS  = [
  { value: 'today',       label: 'Today' },
  { value: 'yesterday',   label: 'Yesterday' },
  { value: 'last_3d',     label: 'Last 3 Days' },
  { value: 'last_7d',     label: 'Last 7 Days' },
  { value: 'last_14d',    label: 'Last 14 Days' },
  { value: 'last_30d',    label: 'Last 30 Days' },
  { value: 'custom',      label: 'Custom Range' },
];

const INTELLIGENCE_PRESETS = [
  { value: 'yesterday',    label: 'Yesterday' },
  { value: 'last_3d',      label: 'Last 3d' },
  { value: 'last_7d',      label: 'Last 7d' },
  { value: 'last_14d',     label: 'Last 14d' },
  { value: 'last_30d',     label: 'Last 30d' },
  { value: 'weekdays_mtd', label: 'Weekdays MTD' },
  { value: 'weekends_mtd', label: 'Weekends MTD' },
  { value: 'custom',       label: 'Custom' },
];

const normalizeStatus = (status) => (status || '').toString().toUpperCase();

function renderMarkdownInline(text) {
  return text.split(/(\*\*[^*]+\*\*)/g).map((part, i) => {
    const bold = part.match(/^\*\*(.+)\*\*$/);
    if (bold) return <strong key={i} className="font-semibold text-gray-900">{bold[1]}</strong>;
    return part;
  });
}

function MarkdownAnswer({ text }) {
  if (!text) return null;
  return (
    <div className="space-y-1">
      {text.split('\n').map((line, i) => (
        line.trim()
          ? <p key={i} className="text-sm leading-relaxed">{renderMarkdownInline(line)}</p>
          : <div key={i} className="h-1" />
      ))}
    </div>
  );
}

function formatMoney(value) {
  return value != null
    ? `$${Number(value).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
    : '—';
}

function CampaignIntelligencePanel({ adAccountId, initialOpen = false, initialPreset = 'last_7d' }) {
  const [open, setOpen] = useState(initialOpen);
  const [preset, setPreset] = useState(initialPreset || 'last_7d');
  const [customFrom, setCustomFrom] = useState('');
  const [customTo, setCustomTo] = useState('');
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const loadedPresetRef = useRef(null);

  const loadIntelligence = useCallback(async (nextPreset = preset, nextFrom = customFrom, nextTo = customTo) => {
    setLoading(true);
    setError(null);
    setData(null);
    try {
      const params = new URLSearchParams({ preset: nextPreset });
      if (adAccountId) params.set('ad_account_id', adAccountId);
      if (nextPreset === 'custom' && nextFrom && nextTo) {
        params.set('date_from', nextFrom);
        params.set('date_to', nextTo);
      }
      const res = await authFetch(`${API_BASE}/intelligence/niche-profitability?${params}`);
      if (!res.ok) {
        const e = await res.json().catch(() => ({}));
        throw new Error(e.detail || `Error ${res.status}`);
      }
      const result = await res.json();
      loadedPresetRef.current = nextPreset === 'custom' ? `custom:${nextFrom}:${nextTo}` : nextPreset;
      setData(result);
    } catch (e) {
      setError(e.message || 'Failed to load intelligence data');
    } finally {
      setLoading(false);
    }
  }, [adAccountId, preset, customFrom, customTo]);

  const toggleOpen = useCallback(() => {
    setOpen(current => {
      const next = !current;
      if (next && loadedPresetRef.current !== preset) {
        loadIntelligence(preset, customFrom, customTo);
      }
      return next;
    });
  }, [preset, customFrom, customTo, loadIntelligence]);

  useEffect(() => {
    if (!initialOpen) return;
    setOpen(true);
    setPreset(initialPreset || 'last_7d');
    if (loadedPresetRef.current !== (initialPreset || 'last_7d')) {
      loadIntelligence(initialPreset || 'last_7d', customFrom, customTo);
    }
  }, [initialOpen, initialPreset, adAccountId]); // eslint-disable-line react-hooks/exhaustive-deps

  const handlePreset = (nextPreset) => {
    setPreset(nextPreset);
    if (nextPreset === 'custom') {
      setCustomFrom('');
      setCustomTo('');
      setData(null);
      setError(null);
      return;
    }
    if (open) loadIntelligence(nextPreset, '', '');
  };

  return (
    <div className="bg-white rounded-xl border border-violet-200 border-l-4 border-l-violet-500 shadow-sm overflow-hidden">
      <div
        className="px-6 py-4 flex items-center justify-between cursor-pointer select-none bg-violet-50/40 hover:bg-violet-50/70 transition-colors"
        onClick={toggleOpen}
      >
        <div>
          <h2 className="font-semibold text-gray-900 flex items-center gap-2">
            <Sparkles size={16} className="text-violet-500" />
            Campaign Intelligence
            <span className="text-xs font-normal text-gray-400">Action queue · tracking checks · niche decisions</span>
          </h2>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={e => { e.stopPropagation(); loadIntelligence(preset, customFrom, customTo); }}
            disabled={loading}
            className="p-1.5 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors disabled:opacity-40"
            title="Refresh intelligence"
          >
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
          </button>
          <ChevronDown size={16} className={`text-gray-400 transition-transform ${open ? '' : '-rotate-90'}`} />
        </div>
      </div>

      {open && (
        <div className="px-6 pb-5">
          <div className="flex flex-wrap gap-1.5 mb-4">
            {INTELLIGENCE_PRESETS.map(p => (
              <button
                key={p.value}
                onClick={() => handlePreset(p.value)}
                className={`px-3 py-1 rounded-full text-xs font-medium transition-colors ${
                  preset === p.value
                    ? 'bg-violet-100 text-violet-700 border border-violet-200'
                    : 'bg-gray-100 text-gray-600 border border-transparent hover:bg-gray-200'
                }`}
              >
                {p.label}
              </button>
            ))}
          </div>

          {preset === 'custom' && (
            <div className="flex items-center gap-2 mb-4">
              <input
                type="date"
                value={customFrom}
                onChange={e => setCustomFrom(e.target.value)}
                className="text-xs border border-gray-200 rounded-lg px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-violet-400"
              />
              <span className="text-xs text-gray-400">to</span>
              <input
                type="date"
                value={customTo}
                onChange={e => setCustomTo(e.target.value)}
                className="text-xs border border-gray-200 rounded-lg px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-violet-400"
              />
              <button
                onClick={() => loadIntelligence('custom', customFrom, customTo)}
                disabled={!customFrom || !customTo}
                className="px-3 py-1.5 bg-violet-600 text-white text-xs font-medium rounded-lg hover:bg-violet-700 disabled:opacity-40 transition-colors"
              >
                Apply
              </button>
            </div>
          )}

          {loading && (
            <div className="space-y-3">
              <div className="h-20 rounded-xl bg-violet-50 animate-pulse" />
              {[0, 1, 2].map(i => <div key={i} className="h-10 rounded bg-gray-100 animate-pulse" />)}
            </div>
          )}

          {!loading && error && (
            <div className="py-6 flex flex-col items-center gap-3">
              <p className="text-sm text-red-500">{error}</p>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => loadIntelligence(preset, customFrom, customTo)}
                  className="px-3 py-1.5 bg-violet-600 text-white text-xs font-medium rounded-lg hover:bg-violet-700 transition-colors"
                >
                  Retry
                </button>
                <button
                  onClick={() => setError(null)}
                  className="px-3 py-1.5 bg-gray-100 text-gray-600 text-xs font-medium rounded-lg hover:bg-gray-200 transition-colors"
                >
                  Dismiss
                </button>
              </div>
            </div>
          )}

          {!loading && !error && data && (
            <>
              <div className="bg-violet-50 border border-violet-100 rounded-xl p-4 mb-4 flex gap-3">
                <Sparkles size={16} className="text-violet-500 flex-shrink-0 mt-0.5" />
                <div className="min-w-0">
                  <p className="text-xs font-semibold text-violet-800 mb-1">
                    {data.preset_label}
                    {data.day_filter !== 'all' && (
                      <span className="ml-2 font-normal text-violet-500">· {data.day_filter} days · {data.date_from} to {data.date_to}</span>
                    )}
                  </p>
                  <div className="text-violet-900">
                    <MarkdownAnswer text={data.summary} />
                  </div>
                </div>
              </div>

              {data.action_queue && (
                <div className="mb-4">
                  <div className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Action Queue</div>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                    {[
                      { key: 'scale', label: 'Scale', hdrBg: 'bg-green-50', border: 'border-green-200', text: 'text-green-800' },
                      { key: 'cut_or_pause', label: 'Cut / Pause', hdrBg: 'bg-red-50', border: 'border-red-200', text: 'text-red-800' },
                      { key: 'watch', label: 'Watch', hdrBg: 'bg-amber-50', border: 'border-amber-200', text: 'text-amber-800' },
                      { key: 'tracking_check', label: 'Tracking', hdrBg: 'bg-yellow-50', border: 'border-yellow-200', text: 'text-yellow-800' },
                    ].map(lane => {
                      const items = data.action_queue[lane.key];
                      if (!items?.length) return null;
                      return (
                        <div key={lane.key} className={`rounded-lg border ${lane.border} overflow-hidden bg-white`}>
                          <div className={`${lane.hdrBg} px-3 py-1.5 text-[10px] font-semibold uppercase tracking-wide ${lane.text}`}>
                            {lane.label}
                          </div>
                          <ul className="px-3 py-2 space-y-1">
                            {items.map(item => (
                              <li key={item} className="text-xs text-gray-700 truncate" title={item}>{item}</li>
                            ))}
                          </ul>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              {data.tracking_warning?.has_warning && (
                <div className="mb-4 rounded-lg border border-yellow-200 bg-yellow-50 px-3 py-2 text-xs text-yellow-800">
                  {data.tracking_warning.message}
                </div>
              )}

              {data.rows.length > 0 && (
                <div className="overflow-x-auto rounded-xl border border-gray-100">
                  <table className="w-full text-sm">
                    <thead className="bg-gray-50 border-b border-gray-100">
                      <tr className="text-left text-xs font-medium text-gray-500 uppercase tracking-wide">
                        <th className="px-4 py-3">Niche</th>
                        <th className="px-4 py-3 text-right">Spend</th>
                        <th className="px-4 py-3 text-right">Revenue</th>
                        <th className="px-4 py-3 text-right">Profit</th>
                        <th className="px-4 py-3 text-right">ROI</th>
                        <th className="px-4 py-3 text-right">CPL</th>
                        <th className="px-4 py-3 text-center">Verdict</th>
                        <th className="px-4 py-3 text-center">Confidence</th>
                        <th className="px-4 py-3 text-center">Action</th>
                        <th className="px-4 py-3 text-center">Join</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-50">
                      {data.rows.map(row => {
                        const roiPct = row.roi != null ? Math.round(row.roi * 100) : null;
                        const profitClass = row.profit > 0 ? 'text-green-600' : row.profit < 0 ? 'text-red-600' : 'text-gray-500';
                        const roiClass = roiPct == null ? 'text-gray-400'
                          : roiPct >= 25 ? 'text-green-600 font-semibold'
                          : roiPct >= 0 ? 'text-gray-700'
                          : roiPct > -25 ? 'text-orange-500 font-semibold'
                          : 'text-red-600 font-semibold';
                        const joinLabels = {
                          matched: { label: 'Matched', cls: 'text-green-600' },
                          matched_rt_approximate: { label: 'Approx RT', cls: 'text-blue-500' },
                          partial_redtrack: { label: 'Partial RT', cls: 'text-orange-500' },
                          missing_redtrack: { label: 'Missing RT', cls: 'text-red-500' },
                        };
                        const joinInfo = joinLabels[row.join_status] || { label: row.join_status, cls: 'text-gray-400' };
                        return (
                          <tr key={row.niche} className="hover:bg-gray-50 transition-colors">
                            <td className="px-4 py-3">
                              <div className="font-medium text-gray-900">{row.niche}</div>
                              {(row.active_adset_count != null || row.current_daily_budget != null) && (
                                <div className="text-xs text-gray-400 mt-0.5">
                                  {row.active_adset_count != null && `${row.active_adset_count} active ad set${row.active_adset_count !== 1 ? 's' : ''}`}
                                  {row.current_daily_budget != null ? ` · $${Math.round(row.current_daily_budget)}/day` : ''}
                                </div>
                              )}
                            </td>
                            <td className="px-4 py-3 text-right text-gray-700">{formatMoney(row.spend)}</td>
                            <td className="px-4 py-3 text-right text-gray-700">{row.revenue > 0 ? formatMoney(row.revenue) : '—'}</td>
                            <td className={`px-4 py-3 text-right ${profitClass}`}>{row.profit > 0 ? '+' : ''}{formatMoney(row.profit)}</td>
                            <td className={`px-4 py-3 text-right ${roiClass}`}>{roiPct != null ? `${roiPct > 0 ? '+' : ''}${roiPct}%` : '—'}</td>
                            <td className="px-4 py-3 text-right text-gray-700">{row.cpl != null ? formatMoney(row.cpl) : '—'}</td>
                            <td className="px-4 py-3 text-center text-xs text-gray-700">{row.verdict}</td>
                            <td className="px-4 py-3 text-center text-xs text-gray-700">{row.confidence || '—'}</td>
                            <td className="px-4 py-3 text-center text-xs text-gray-700">{row.suggested_action_label || '—'}</td>
                            <td className={`px-4 py-3 text-center text-xs font-medium ${joinInfo.cls}`}>{joinInfo.label}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}

              {data.day_filter !== 'all' && (
                <p className="text-xs text-gray-400 mt-2">
                  RedTrack revenue uses full date range (not day-filtered) — ROI is approximate.
                </p>
              )}
            </>
          )}

          {!loading && !error && !data && (
            <p className="text-sm text-gray-400 text-center py-4">Open or select a preset to load intelligence.</p>
          )}
        </div>
      )}
    </div>
  );
}

// ── Creative breakdown table (ad-level) ──────────────────────────────────────
// onRemix: ({ ad_id, ad_name, headline, body, cta_label, image_url, adsetName, campaign_id }) => void
function AdsBreakdown({ fbAdsetId, fbCampaignId, adsetName, campaignId, adsBulk, adsLoading, rtAdsBulk, onAdStatusChange, onRemix }) {
  const { showSuccess, showError } = useToast();
  const navigate = useNavigate();
  const [pausingAds, setPausingAds] = useState(new Set());
  const [adStatuses, setAdStatuses] = useState({}); // local optimistic status overrides
  const [remixingAd, setRemixingAd] = useState(null);
  const [quickAd, setQuickAd] = useState(null);

  const handleRemix = async (ad) => {
    setRemixingAd(ad.ad_id);
    try {
      const res = await authFetch(`${API_BASE}/facebook/ads/${ad.ad_id}/creative`);
      if (!res.ok) { const e = await res.json(); throw new Error(e.detail || 'Failed to fetch creative'); }
      const creative = await res.json();
      onRemix({
        ad_id: ad.ad_id,
        ad_name: creative.ad_name || ad.ad_name,
        headline: creative.headline || '',
        body: creative.body || '',
        cta_label: creative.cta_label || '',
        image_url: creative.image_url || '',
        link_url: creative.link_url || '',
        adsetName,
        campaign_id: campaignId,
        fb_campaign_id: fbCampaignId || '',
        fb_adset_id: fbAdsetId || '',
      });
    } catch (e) {
      showError(`Remix failed: ${e.message}`);
    } finally {
      setRemixingAd(null);
    }
  };

  const handleQuickVariations = async (ad) => {
    setQuickAd(ad.ad_id);
    try {
      const res = await authFetch(`${API_BASE}/facebook/ads/${ad.ad_id}/creative`);
      if (!res.ok) { const e = await res.json(); throw new Error(e.detail || 'Failed to fetch creative'); }
      const creative = await res.json();
      localStorage.setItem('pendingQuickCopy', JSON.stringify({
        headline: creative.headline || '',
        body: creative.body || '',
        cta: creative.cta_label || 'GET MY QUOTE',
        source: 'campaign_performance',
        ad_id: ad.ad_id,
      }));
      navigate('/image-ads');
    } catch (e) {
      showError(`Quick Variations failed: ${e.message}`);
    } finally {
      setQuickAd(null);
    }
  };

  const toggleAdStatus = async (ad) => {
    const currentStatus = adStatuses[ad.ad_id] ?? (ad.status || 'ACTIVE');
    const newStatus = currentStatus === 'ACTIVE' ? 'PAUSED' : 'ACTIVE';
    setPausingAds(prev => new Set(prev).add(ad.ad_id));
    try {
      const res = await authFetch(`${API_BASE}/facebook/ads/${ad.ad_id}/status`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: newStatus }),
      });
      if (!res.ok) { const e = await res.json(); throw new Error(e.detail || 'Failed'); }
      setAdStatuses(prev => ({ ...prev, [ad.ad_id]: newStatus }));
      showSuccess(`Ad "${ad.ad_name}" ${newStatus === 'PAUSED' ? 'paused' : 'resumed'}`);
      onAdStatusChange?.();
    } catch (e) {
      showError(e.message);
    } finally {
      setPausingAds(prev => { const next = new Set(prev); next.delete(ad.ad_id); return next; });
    }
  };

  if (adsLoading) return (
    <div className="mt-3 pl-10 text-xs text-gray-400 animate-pulse">Loading creatives...</div>
  );

  const ads = adsBulk?.[fbAdsetId];
  if (!ads || ads.length === 0) return (
    <div className="mt-3 pl-10 text-xs text-gray-400 italic">No ad-level data for this period.</div>
  );

  const maxSpend = Math.max(...ads.map(a => a.spend), 0.01);
  // Blended avg CPL for this ad set (for relative poor-performer detection)
  const adsWithLeads = ads.filter(a => a.leads > 0);
  const avgCpl = adsWithLeads.length > 0
    ? adsWithLeads.reduce((s, a) => s + a.cpl, 0) / adsWithLeads.length
    : null;
  const hasRoas = ads.some(a => a.roas != null);

  return (
    <div className="mt-3 rounded-lg border border-gray-100 overflow-hidden">
      <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="bg-gray-50 border-b border-gray-100">
            <th className="text-left px-3 py-2 font-medium text-gray-500 w-1/3">Creative</th>
            <th className="text-right px-3 py-2 font-medium text-gray-500">Spend</th>
            <th className="text-right px-3 py-2 font-medium text-gray-500">Leads</th>
            <th className="text-right px-3 py-2 font-medium text-gray-500">CPL</th>
            <th className="text-right px-3 py-2 font-medium text-gray-500">CTR</th>
            <th className="text-right px-3 py-2 font-medium text-gray-500">Impr.</th>
            {hasRoas && (
              <th className="text-right px-3 py-2 font-medium text-gray-500">ROAS</th>
            )}
            {rtAdsBulk && (
              <>
                <th className="text-right px-3 py-2 font-medium text-blue-400">RT Convs</th>
                <th className="text-right px-3 py-2 font-medium text-blue-400">RT CPL</th>
                <th className="text-right px-3 py-2 font-medium text-blue-400">RT ROAS</th>
              </>
            )}
            <th className="px-3 py-2 font-medium text-gray-400 text-center">Actions</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-50">
          {ads.map((ad, i) => {
            const rt = rtAdsBulk?.[ad.ad_id];
            const currentStatus = adStatuses[ad.ad_id] ?? (ad.status || 'ACTIVE');
            const isPaused = currentStatus === 'PAUSED';
            const isPausing = pausingAds.has(ad.ad_id);
            const spendPct = maxSpend > 0 ? (ad.spend / maxSpend) * 100 : 0;

            // Flag signals
            const rtRoas = rt?.roas ?? ad.roas;
            const isPoorRoas = rtRoas != null && rtRoas < 1;
            const isHighCpl = avgCpl != null && ad.cpl != null && ad.cpl > avgCpl * 1.4 && ad.spend > 20;
            const isNoLeads = ad.spend >= 20 && ad.leads === 0;
            const isPoorPerformer = isPoorRoas || isHighCpl || isNoLeads;

            // Winner: most spend, >1 ad in set, has leads
            const isTop = i === 0 && ads.length > 1 && ad.spend > 0 && ad.leads > 0;

            return (
              <tr
                key={ad.ad_id}
                className={`transition-colors ${
                  isPaused ? 'opacity-50' :
                  isPoorPerformer ? 'bg-red-50/30 hover:bg-red-50/50' :
                  isTop ? 'bg-green-50/40 hover:bg-green-50/60' :
                  'hover:bg-gray-50/60'
                }`}
              >
                <td className="px-3 py-2">
                  <div className="flex items-center gap-2">
                    {isTop && <span className="text-green-600 text-xs font-bold" title="Top creative">↑</span>}
                    {isPoorPerformer && !isTop && (
                      <AlertTriangle size={11} className="text-red-400 flex-shrink-0" title={
                        isNoLeads ? 'Spend with 0 leads' : isHighCpl ? 'CPL well above average' : 'ROAS < 1x'
                      } />
                    )}
                    <div>
                      <div className="font-medium text-gray-800 leading-tight truncate max-w-[200px]" title={ad.ad_name}>
                        {ad.ad_name || ad.ad_id}
                      </div>
                      {/* Spend bar */}
                      <div className="mt-1 h-1 bg-gray-100 rounded-full w-24">
                        <div
                          className={`h-1 rounded-full ${isPoorPerformer ? 'bg-red-300' : isTop ? 'bg-green-400' : 'bg-indigo-400'}`}
                          style={{ width: `${spendPct}%` }}
                        />
                      </div>
                    </div>
                  </div>
                </td>
                <td className="px-3 py-2 text-right font-medium text-gray-700">${ad.spend.toFixed(0)}</td>
                <td className="px-3 py-2 text-right text-gray-700">{ad.leads}</td>
                <td className={`px-3 py-2 text-right font-medium ${
                  // Only flag CPL red if it's genuinely unprofitable — skip if ROAS ≥ 1 (ad is covering costs)
                  (isHighCpl || (ad.cpl != null && ad.cpl > 60)) && !(rtRoas != null && rtRoas >= 1)
                    ? 'text-red-600 font-bold'
                    : 'text-gray-700'
                }`}>
                  {ad.cpl != null ? `$${ad.cpl.toFixed(2)}` : '—'}
                </td>
                <td className="px-3 py-2 text-right text-gray-600">{parseFloat(ad.ctr).toFixed(2)}%</td>
                <td className="px-3 py-2 text-right text-gray-500">{ad.impressions.toLocaleString()}</td>
                {hasRoas && (
                  <td className={`px-3 py-2 text-right font-medium ${isPoorRoas ? 'text-red-600 font-bold' : 'text-gray-700'}`}>
                    {ad.roas != null ? `${ad.roas.toFixed(2)}x` : '—'}
                  </td>
                )}
                {rtAdsBulk && (
                  <>
                    <td className="px-3 py-2 text-right text-blue-700">{rt ? rt.conversions : '—'}</td>
                    <td className={`px-3 py-2 text-right font-medium ${rt?.cpl != null && rt.cpl > 60 ? 'text-red-600' : 'text-blue-700'}`}>
                      {rt?.cpl != null ? `$${rt.cpl.toFixed(2)}` : '—'}
                    </td>
                    <td className={`px-3 py-2 text-right font-medium ${rt?.roas != null && rt.roas < 1 ? 'text-red-600' : 'text-blue-700'}`}>
                      {rt?.roas != null ? `${rt.roas.toFixed(2)}x` : '—'}
                    </td>
                  </>
                )}
                <td className="px-3 py-2">
                  <div className="flex items-center justify-center gap-1.5">
                    {/* Remix → opens inline drawer */}
                    <button
                      onClick={() => handleRemix(ad)}
                      disabled={remixingAd === ad.ad_id}
                      className={`flex items-center gap-1 px-2 py-1 rounded transition-colors text-xs font-medium whitespace-nowrap disabled:opacity-50 ${
                        isTop
                          ? 'text-purple-600 bg-purple-50 hover:bg-purple-100'
                          : isPoorPerformer
                          ? 'text-orange-600 bg-orange-50 hover:bg-orange-100'
                          : 'text-indigo-600 bg-indigo-50 hover:bg-indigo-100'
                      }`}
                      title={isTop ? 'Remix this winning creative' : isPoorPerformer ? 'Remix this underperformer with a new angle' : 'Remix this creative'}
                    >
                      {remixingAd === ad.ad_id
                        ? <RefreshCw size={11} className="animate-spin" />
                        : <Sparkles size={11} />
                      }
                      Remix
                    </button>
                    {isTop && (
                      <button
                        onClick={() => handleQuickVariations(ad)}
                        disabled={quickAd === ad.ad_id}
                        className="flex items-center gap-1 px-2 py-1 rounded text-amber-700 bg-amber-50 hover:bg-amber-100 transition-colors text-xs font-medium whitespace-nowrap disabled:opacity-50"
                        title="Open this winner in Quick Generate"
                      >
                        {quickAd === ad.ad_id
                          ? <RefreshCw size={11} className="animate-spin" />
                          : <Zap size={11} />
                        }
                        Quick Variations
                      </button>
                    )}
                    {/* Quick Generate → Batch Generate pre-filled with this ad */}
                    <button
                      onClick={() => navigate(`/batch-generate?adId=${encodeURIComponent(ad.ad_id)}&adName=${encodeURIComponent(ad.ad_name || ad.ad_id)}&adsetName=${encodeURIComponent(adsetName || '')}&campaignId=${encodeURIComponent(fbCampaignId || '')}&adsetId=${encodeURIComponent(fbAdsetId || '')}`)}
                      className="flex items-center gap-1 px-2 py-1 rounded text-indigo-600 bg-indigo-50 hover:bg-indigo-100 transition-colors text-xs font-medium whitespace-nowrap"
                      title="Generate more creative variants from this ad"
                    >
                      <Zap size={11} /> Quick Generate
                    </button>
                    {/* Pause / Resume */}
                    <button
                      onClick={() => toggleAdStatus(ad)}
                      disabled={isPausing}
                      className={`flex items-center gap-1 px-2 py-1 rounded text-xs font-medium transition-colors disabled:opacity-40 ${
                        isPaused
                          ? 'text-green-700 bg-green-50 hover:bg-green-100'
                          : 'text-gray-500 bg-gray-100 hover:bg-red-50 hover:text-red-600'
                      }`}
                      title={isPaused ? 'Resume this ad' : 'Pause this ad'}
                    >
                      {isPausing
                        ? <RefreshCw size={11} className="animate-spin" />
                        : isPaused ? <PlayCircle size={11} /> : <PauseCircle size={11} />
                      }
                      {isPaused ? 'Resume' : 'Pause'}
                    </button>
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      </div>
    </div>
  );
}

// ── Add-rule modal ────────────────────────────────────────────────────────────
function AddRuleModal({ adsets, onClose, onCreated }) {
  const { showSuccess, showError } = useToast();
  const [form, setForm] = useState({
    adset_id: adsets[0]?.id || '',
    metric: 'cpl',
    operator: 'greater_than',
    threshold: 50,
    min_spend: 20,
  });
  const [saving, setSaving] = useState(false);

  const save = async () => {
    setSaving(true);
    try {
      const res = await authFetch(`${API_BASE}/auto-pause/rules`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form),
      });
      if (!res.ok) { const e = await res.json(); throw new Error(e.detail || 'Failed'); }
      showSuccess('Auto-pause rule created');
      onCreated();
      onClose();
    } catch (e) { showError(e.message); }
    finally { setSaving(false); }
  };

  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50">
      <div className="bg-white rounded-2xl shadow-xl p-6 w-full max-w-md">
        <h2 className="text-lg font-bold text-gray-900 mb-4 flex items-center gap-2">
          <PauseCircle size={20} className="text-red-500" /> New Auto-Pause Rule
        </h2>

        <div className="space-y-4">
          <Field label="Ad Set">
            <select className="input-base" value={form.adset_id} onChange={e => setForm({...form, adset_id: e.target.value})}>
              {adsets.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
            </select>
          </Field>

          <Field label="Metric">
            <select className="input-base" value={form.metric} onChange={e => setForm({...form, metric: e.target.value})}>
              <option value="cpl">Cost Per Lead (CPL)</option>
              <option value="cpa">Cost Per Action (CPA)</option>
              <option value="ctr">Click-Through Rate (CTR)</option>
              <option value="roas">ROAS</option>
            </select>
          </Field>

          <Field label="Condition">
            <select className="input-base" value={form.operator} onChange={e => setForm({...form, operator: e.target.value})}>
              <option value="greater_than">Greater than (&gt;)</option>
              <option value="less_than">Less than (&lt;)</option>
            </select>
          </Field>

          <Field label={`Threshold (${METRIC_UNITS[form.metric]})`}>
            <input
              type="number" min="0" step={form.metric === 'roas' ? '0.1' : '1'} className="input-base"
              value={form.threshold}
              onChange={e => setForm({...form, threshold: Number(e.target.value)})}
            />
            <p className="text-xs text-gray-500 mt-1">
              Pause when {METRIC_LABELS[form.metric]} {form.operator === 'greater_than' ? '>' : '<'} {form.metric === 'roas' ? '' : METRIC_UNITS[form.metric]}{form.threshold}{form.metric === 'roas' ? 'x' : ''}
            </p>
          </Field>

          <Field label="Minimum Spend Before Rule Fires ($)">
            <input
              type="number" min="0" className="input-base"
              value={form.min_spend}
              onChange={e => setForm({...form, min_spend: Number(e.target.value)})}
            />
            <p className="text-xs text-gray-500 mt-1">Avoid false positives — wait until this much is spent first</p>
          </Field>
        </div>

        <div className="flex gap-3 mt-6">
          <button onClick={onClose} className="flex-1 btn-secondary">Cancel</button>
          <button onClick={save} disabled={saving} className="flex-1 btn-primary">
            {saving ? 'Saving...' : 'Create Rule'}
          </button>
        </div>
      </div>
    </div>
  );
}

function Field({ label, children }) {
  return (
    <div>
      <label className="block text-sm font-medium text-gray-700 mb-1">{label}</label>
      {children}
    </div>
  );
}

// ── Remix Drawer ─────────────────────────────────────────────────────────────
// Extract the meaningful niche segment from a verbose ad set name.
// Ad set names follow the pattern: "[Date] - [Niche] - [Batch/test info]"
// Returns the second segment (index 1) when the pattern matches, otherwise
// falls back to the full name so no data is silently lost.
function extractNiche(adsetName) {
  if (!adsetName) return '';
  const parts = adsetName.split(' - ');
  return parts.length >= 2 ? parts[1].trim() : adsetName;
}

function RemixDrawer({ creative, brands, onClose, onLaunchWizard }) {
  const { showError } = useToast();
  const [hook, setHook] = useState(creative.headline || '');
  const [niche, setNiche] = useState(extractNiche(creative.adsetName));
  const [selectedBrandId, setSelectedBrandId] = useState(creative.brand_id || '');
  const [generating, setGenerating] = useState(false);
  const [variations, setVariations] = useState([]);
  const [copied, setCopied] = useState(null);

  // Resolve the active brand — fall back to the campaign-assigned brand when
  // selectedBrandId holds the '__change' sentinel (user clicked "change" but
  // hasn't picked a new brand yet).
  const effectiveBrandId = selectedBrandId.startsWith('__change') ? creative.brand_id : selectedBrandId;
  const selectedBrand = brands.find(b => b.id === effectiveBrandId);

  const handleGenerate = async () => {
    if (!hook) return;
    setGenerating(true);
    setVariations([]);
    try {
      const res = await authFetch(`${API_BASE}/copy-generation/remix-variations`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          source_headline: creative.headline,
          source_body: creative.body,
          hook,
          niche,
          brand_name: selectedBrand?.name || '',
          brand_voice: selectedBrand?.voice || '',
          vertical: selectedBrand?.vertical || 'commercial_insurance',
        }),
      });
      if (!res.ok) { const e = await res.json(); throw new Error(e.detail || 'Generation failed'); }
      const data = await res.json();
      setVariations(data.variations || []);
    } catch (e) {
      showError(e.message);
    } finally {
      setGenerating(false);
    }
  };

  const copyVariation = (v, idx) => {
    navigator.clipboard.writeText(`${v.headline}\n\n${v.body}`);
    setCopied(idx);
    setTimeout(() => setCopied(null), 2000);
  };

  return (
    <div className="fixed inset-0 z-50 flex justify-end pointer-events-none">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/30 pointer-events-auto" onClick={onClose} />
      {/* Drawer */}
      <div className="relative w-full max-w-xl bg-white shadow-2xl pointer-events-auto flex flex-col h-full overflow-y-auto">
        {/* Header */}
        <div className="flex items-start justify-between p-5 border-b border-gray-100">
          <div>
            <h2 className="text-lg font-bold text-gray-900 flex items-center gap-2">
              <Sparkles size={18} className="text-purple-600" /> Remix Ad
            </h2>
            <p className="text-xs text-gray-500 mt-0.5">Source: <span className="font-medium text-gray-700">{creative.ad_name}</span></p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 p-1"><X size={20} /></button>
        </div>

        <div className="p-5 space-y-5 flex-1">
          {/* Source ad reference */}
          <div className="bg-gray-50 rounded-lg p-3 border border-gray-100 text-sm">
            <p className="font-medium text-gray-700 mb-1 text-xs uppercase tracking-wide text-gray-400">Source ad copy</p>
            {creative.headline && <p className="font-semibold text-gray-800 mb-1">"{creative.headline}"</p>}
            {creative.body && <p className="text-gray-600 text-xs line-clamp-3">{creative.body}</p>}
          </div>

          {/* Brand — shows as a read-only pill if already assigned to the campaign,
               so Joel doesn't have to touch it. Reveals a selector only when unassigned
               or when he explicitly clicks "change". */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1.5">Brand</label>
            {creative.brand_id && !selectedBrandId.startsWith('__change') ? (
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium text-gray-800 bg-blue-50 border border-blue-200 px-3 py-1.5 rounded-lg">
                  {creative.brand_name}
                </span>
                <button
                  onClick={() => setSelectedBrandId('__change')}
                  className="text-xs text-gray-400 hover:text-gray-600 underline"
                >
                  change
                </button>
              </div>
            ) : (
              <>
                <select
                  value={selectedBrandId.startsWith('__change') ? '' : selectedBrandId}
                  onChange={e => setSelectedBrandId(e.target.value)}
                  className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-purple-500"
                >
                  <option value="">— select brand —</option>
                  {brands.map(b => <option key={b.id} value={b.id}>{b.name}</option>)}
                </select>
                <p className="text-xs text-amber-600 mt-1">Tip: assign a brand to this campaign row to skip this step next time.</p>
              </>
            )}
          </div>

          {/* Hook */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1.5">Hook / Angle <span className="text-gray-400 font-normal">(edit to try a new angle)</span></label>
            <input
              type="text"
              value={hook}
              onChange={e => setHook(e.target.value)}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-purple-500"
              placeholder="e.g. Is your church one repair away from a financial crisis?"
            />
          </div>

          {/* Niche */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1.5">Niche <span className="text-gray-400 font-normal">(from ad set name)</span></label>
            <input
              type="text"
              value={niche}
              onChange={e => setNiche(e.target.value)}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-purple-500"
              placeholder="e.g. Religious Organizations, Welders, Laundromat"
            />
          </div>

          {/* Generate button */}
          <button
            onClick={handleGenerate}
            disabled={generating || !hook}
            className="w-full flex items-center justify-center gap-2 py-3 bg-purple-600 text-white rounded-lg font-medium hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {generating ? <RefreshCw size={16} className="animate-spin" /> : <Sparkles size={16} />}
            {generating ? 'Generating variations…' : 'Generate 3 Variations'}
          </button>

          {/* Variations output */}
          {variations.length > 0 && (
            <div className="space-y-3">
              <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Variations</p>
              {variations.map((v, i) => (
                <div key={i} className="border border-gray-200 rounded-lg p-3 bg-white hover:border-purple-300 transition-colors">
                  <p className="font-semibold text-gray-900 text-sm mb-1">{v.headline}</p>
                  <p className="text-gray-600 text-xs mb-3 line-clamp-4">{v.body}</p>
                  <div className="flex gap-2">
                    <button
                      onClick={() => copyVariation(v, i)}
                      title="Copy headline & body to clipboard"
                      className="flex items-center gap-1 text-xs px-2.5 py-1 rounded bg-gray-100 hover:bg-gray-200 text-gray-700 font-medium"
                    >
                      {copied === i ? '✓ Copied' : 'Copy'}
                    </button>
                    {/* Opens in new tab so Joel keeps his place in the Campaign Performance table */}
                    <button
                      onClick={() => onLaunchWizard({ ...creative, headline: v.headline, body: v.body, niche })}
                      className="flex items-center gap-1 text-xs px-2.5 py-1 rounded bg-purple-50 hover:bg-purple-100 text-purple-700 font-medium"
                    >
                      <Sparkles size={10} /> Build Ad ↗
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────
export default function CampaignPerformance() {
  const navigate = useNavigate();
  const { showSuccess, showError, showInfo } = useToast();
  const { brands } = useBrands();
  const { activeAccountId, activeAccountLoading } = useCampaign();
  const adAccountId = activeAccountId || '';
  const [adsets, setAdsets]     = useState([]);
  const [rules, setRules]       = useState([]); // still needed for isFlagged + rule badges
  // searchParams must be declared before the date useState initialisers that read it
  const [searchParams, setSearchParams] = useSearchParams();
  // Inherit date from Dashboard URL params (preset / date_from / date_to)
  const [datePreset, setDatePreset] = useState(() => {
    if (searchParams.get('date_from') && searchParams.get('date_to')) return 'custom';
    return searchParams.get('preset') || localStorage.getItem('bhm_date_preset') || 'today';
  });
  const [dateFrom, setDateFrom] = useState(() => searchParams.get('date_from') || '');
  const [dateTo, setDateTo] = useState(() => searchParams.get('date_to') || '');
  const [loadingAdsets, setLoadingAdsets] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [statusFilter, setStatusFilter] = useState(() => {
    const view = searchParams.get('view');
    if (view === 'attention') return 'flagged';
    if (view === 'top-performers') return 'has_spend';
    return 'ACTIVE';
  });
  const [sortBy, setSortBy] = useState(() => {
    const view = searchParams.get('view');
    if (view === 'top-performers') return 'roas';
    return 'spend';
  });
  const dashboardView = searchParams.get('view'); // derived live from URL — never stale
  const targetAdsetId = searchParams.get('adsetId');
  const intelligencePanelOpen = searchParams.get('panel') === 'intelligence';
  const intelligenceInitialPreset = searchParams.get('ciPreset') || 'last_7d';

  // Bulk insights state — one API call replaces N per-row calls
  const [bulkInsights, setBulkInsights]       = useState(null);
  const [bulkInsightsLoading, setBulkInsightsLoading] = useState(false);
  const [, setBulkInsightsError]   = useState(null);

  // Ad-level (creative) breakdown state
  const [adsBulk, setAdsBulk]           = useState(null);
  const [adsLoading, setAdsLoading]     = useState(false);
  const [rtAdsBulk, setRtAdsBulk]       = useState(null);  // RT data keyed by ad_id (sub3)
  const [expandedAdsets, setExpandedAdsets] = useState(new Set());
  // Campaign-level collapse — starts with all open; add campaignId to collapse it
  const [collapsedCampaigns, setCollapsedCampaigns] = useState(new Set());
  const toggleCampaign = (key) => setCollapsedCampaigns(prev => {
    const next = new Set(prev);
    next.has(key) ? next.delete(key) : next.add(key);
    return next;
  });

  // Adset-level manual pause state
  const [pausingAdsets, setPausingAdsets] = useState(new Set());
  const [adsetStatusOverrides, setAdsetStatusOverrides] = useState({}); // local optimistic overrides
  const [syncingRT, setSyncingRT] = useState(false);

  // Brand assignment state — maps adset.id → { brand_id, brand_name }
  const [campaignBrands, setCampaignBrands] = useState({});
  const [assigningBrand, setAssigningBrand] = useState(null); // adset.id currently being saved

  // Add-rule modal state
  const [showAddRuleModal, setShowAddRuleModal] = useState(false);

  // Remix drawer state
  const [remixDrawer, setRemixDrawer] = useState(null); // { ad, adsetName, brand_id, brand_name }

  // Floating Ask AI state
  const [askAiOpen, setAskAiOpen] = useState(false);
  const [aiQuery, setAiQuery] = useState('');
  const [aiAnswer, setAiAnswer] = useState('');
  const [aiLoading, setAiLoading] = useState(false);
  const [editingBudget, setEditingBudget] = useState(null);
  const [budgetInput, setBudgetInput] = useState('');
  const [savingBudget, setSavingBudget] = useState(null);
  const [budgetPopover, setBudgetPopover] = useState(null);
  const [campaignBudgetInput, setCampaignBudgetInput] = useState('');
  const [campaignBudgetType, setCampaignBudgetType] = useState('CBO');
  const [savingCampaignBudget, setSavingCampaignBudget] = useState(null);
  const [highlightedAdsetId, setHighlightedAdsetId] = useState(null);
  const rowRefs = useRef({});
  const scrolledToRef = useRef(null); // tracks which adsetId we've already scrolled to

  const loadAdsets = useCallback(async () => {
    setLoadingAdsets(true);
    try {
      const qs = adAccountId ? `?ad_account_id=${encodeURIComponent(adAccountId)}` : '';
      const res = await authFetch(`${API_BASE}/facebook/adsets/saved${qs}`);
      if (!res.ok) throw new Error('Failed to load ad sets');
      const data = await res.json();
      const adsetList = Array.isArray(data) ? data : data.adsets || [];
      setAdsets(adsetList);
      // Seed campaignBrands from adsets that already have a brand assigned (keyed by adset.id)
      const brands = {};
      adsetList.forEach(a => {
        if (a.id && a.brand_id) {
          brands[a.id] = { brand_id: a.brand_id, brand_name: a.brand_name };
        }
      });
      setCampaignBrands(prev => ({ ...prev, ...brands }));
    } catch (e) { showError(e.message); }
    finally { setLoadingAdsets(false); }
  }, [showError, adAccountId]);

  const loadRules = useCallback(async () => {
    try {
      const res = await authFetch(`${API_BASE}/auto-pause/rules`);
      if (!res.ok) throw new Error('Failed to load rules');
      setRules(await res.json());
    } catch (e) { showError(e.message); }
  }, [showError]);

  // authFetch with a hard timeout — prevents any single call from hanging forever
  const timedFetch = useCallback((url, options = {}, ms = 25000) => {
    const ctrl = new AbortController();
    const tid = setTimeout(() => ctrl.abort(), ms);
    return authFetch(url, { ...options, signal: ctrl.signal })
      .finally(() => clearTimeout(tid));
  }, []);

  // Build date params — passes date_from/date_to for custom ranges, date_preset otherwise
  const buildDateParams = useCallback((preset, dateFrom = null, dateTo = null) => {
    const params = new URLSearchParams();
    if (dateFrom && dateTo) {
      params.set('date_from', dateFrom);
      params.set('date_to', dateTo);
    } else {
      params.set('date_preset', preset);
    }
    return params;
  }, []);

  const loadBulkInsights = useCallback(async (accountId, preset, dateFrom = null, dateTo = null) => {
    setBulkInsightsLoading(true);
    setBulkInsightsError(null);
    try {
      const params = buildDateParams(preset, dateFrom, dateTo);
      if (accountId) params.set('ad_account_id', accountId);
      const res = await timedFetch(`${API_BASE}/auto-pause/insights-bulk?${params}`, {}, 25000);
      if (!res.ok) { const e = await res.json(); throw new Error(e.detail || 'Failed to load insights'); }
      setBulkInsights(await res.json());
    } catch (e) {
      setBulkInsightsError(e.name === 'AbortError' ? 'Request timed out — Meta API is slow, try again.' : e.message);
    } finally {
      setBulkInsightsLoading(false);
    }
  }, [buildDateParams, timedFetch]);

  const loadAdsBulk = useCallback(async (accountId, preset, dateFrom = null, dateTo = null) => {
    setAdsLoading(true);
    try {
      const params = buildDateParams(preset, dateFrom, dateTo);
      if (accountId) params.set('ad_account_id', accountId);
      const res = await timedFetch(`${API_BASE}/auto-pause/ads-bulk?${params}`, {}, 20000);
      if (!res.ok) return;
      setAdsBulk(await res.json());
    } catch {
      // silently fail — creative breakdown is supplementary
    } finally {
      setAdsLoading(false);
    }
  }, [buildDateParams, timedFetch]);

  const loadRtAdsBulk = useCallback(async (preset, dateFrom = null, dateTo = null) => {
    setRtAdsBulk(null);
    try {
      const params = buildDateParams(preset, dateFrom, dateTo);
      if (adAccountId) params.set('ad_account_id', adAccountId);
      const res = await timedFetch(`${API_BASE}/redtrack/report/sub1?${params}`, {}, 15000);
      if (!res.ok) return;
      const data = await res.json();
      if (data.configured && data.data) setRtAdsBulk(data.data);
    } catch {
      // silently fail — RT ad-level is supplementary
    }
  }, [adAccountId, buildDateParams, timedFetch]);

  const toggleAdsetStatus = useCallback(async (adset) => {
    const currentStatus = normalizeStatus(adsetStatusOverrides[adset.fb_adset_id] ?? adset.status);
    const newStatus = currentStatus === 'ACTIVE' ? 'PAUSED' : 'ACTIVE';
    setPausingAdsets(prev => new Set(prev).add(adset.fb_adset_id));
    try {
      const res = await timedFetch(`${API_BASE}/facebook/adsets/${adset.fb_adset_id}/status`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: newStatus }),
      }, 15000);
      if (!res.ok) {
        const e = await res.json().catch(() => ({}));
        throw new Error(e.detail || `API error (${res.status})`);
      }
      setAdsetStatusOverrides(prev => ({ ...prev, [adset.fb_adset_id]: newStatus }));
      showSuccess(`"${adset.name}" ${newStatus === 'PAUSED' ? 'paused' : 'resumed'}`);
    } catch (e) {
      showError(e.name === 'AbortError' ? 'Request timed out — try again' : (e.message || 'Failed'));
    } finally {
      setPausingAdsets(prev => { const next = new Set(prev); next.delete(adset.fb_adset_id); return next; });
    }
  }, [adsetStatusOverrides, timedFetch, showSuccess, showError]);

  // Persist non-custom date presets so they survive navigation
  useEffect(() => {
    if (datePreset !== 'custom') localStorage.setItem('bhm_date_preset', datePreset);
  }, [datePreset]);

  // Track whether the initial load has fired — prevents datePreset effect
  // from double-firing before the active account is resolved.
  const initialLoadFired = useRef(false);

  // Fire initial data load once the global active account has resolved; re-fire
  // when the header account switcher changes.
  useEffect(() => {
    if (activeAccountLoading) return;
    initialLoadFired.current = true;
    const initPreset = searchParams.get('preset') || 'today';
    const initFrom   = searchParams.get('date_from') || null;
    const initTo     = searchParams.get('date_to')   || null;
    const resolvedPreset = (initFrom && initTo) ? 'custom' : initPreset;
    setAdsets([]);
    setBulkInsights(null);
    setAdsBulk(null);
    setRtAdsBulk(null);
    loadBulkInsights(adAccountId, resolvedPreset, initFrom, initTo);
    // loadAdsBulk fires after bulkInsights settles (see deferred effect below)
    loadRtAdsBulk(resolvedPreset, initFrom, initTo);
  }, [activeAccountLoading, adAccountId]); // eslint-disable-line react-hooks/exhaustive-deps

  // Re-fetch when user changes the date preset — skip the initial mount render
  // For custom range, wait until both dateFrom and dateTo are set
  useEffect(() => {
    if (!initialLoadFired.current) return;
    if (datePreset === 'custom' && (!dateFrom || !dateTo)) return;
    const from = datePreset === 'custom' ? dateFrom : null;
    const to   = datePreset === 'custom' ? dateTo   : null;
    loadBulkInsights(adAccountId, datePreset, from, to);
    loadRtAdsBulk(datePreset, from, to);
  }, [datePreset, dateFrom, dateTo]); // eslint-disable-line react-hooks/exhaustive-deps

  // Deferred: fire loadAdsBulk after bulk insights finish loading.
  // This avoids two heavy Meta API calls running in parallel on every page load.
  const prevBulkLoadingRef = useRef(false);
  useEffect(() => {
    // Detect the transition: was loading → now done with data
    if (prevBulkLoadingRef.current && !bulkInsightsLoading && bulkInsights !== null) {
      const from = datePreset === 'custom' ? dateFrom : null;
      const to   = datePreset === 'custom' ? dateTo   : null;
      loadAdsBulk(adAccountId, datePreset, from, to);
    }
    prevBulkLoadingRef.current = bulkInsightsLoading;
  }, [bulkInsightsLoading]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (activeAccountLoading) return;
    loadAdsets();
    loadRules();
  }, [activeAccountLoading, adAccountId, loadAdsets, loadRules]);

  useEffect(() => {
    if (!budgetPopover) return;
    const handler = () => setBudgetPopover(null);
    document.addEventListener('click', handler);
    return () => document.removeEventListener('click', handler);
  }, [budgetPopover]);

  // Sync filter/sort state when URL params change (handles component staying mounted across navigations)
  useEffect(() => {
    const view = searchParams.get('view');
    if (view === 'attention') { setStatusFilter('flagged'); setSortBy('spend'); }
    else if (view === 'top-performers') { setStatusFilter('has_spend'); setSortBy('roas'); }
  }, [searchParams]);

  // Sync Dashboard-provided date params when this component stays mounted across navigations.
  useEffect(() => {
    const nextFrom = searchParams.get('date_from') || '';
    const nextTo = searchParams.get('date_to') || '';
    const nextPreset = nextFrom && nextTo
      ? 'custom'
      : searchParams.get('preset') || localStorage.getItem('bhm_date_preset') || 'today';

    setDatePreset(nextPreset);
    setDateFrom(nextFrom);
    setDateTo(nextTo);
  }, [searchParams]);

  useEffect(() => {
    if (!targetAdsetId || targetAdsetId === 'null') {
      setHighlightedAdsetId(null);
      return;
    }
    if (adsets.length === 0) return;

    const target = adsets.find(a => a.fb_adset_id === targetAdsetId);
    if (!target) {
      setHighlightedAdsetId(null);
      return;
    }

    setExpandedAdsets(prev => {
      if (prev.has(targetAdsetId)) return prev;
      const next = new Set(prev);
      next.add(targetAdsetId);
      return next;
    });
    if (target.campaign_id) {
      setCollapsedCampaigns(prev => {
        if (!prev.has(target.campaign_id)) return prev;
        const next = new Set(prev);
        next.delete(target.campaign_id);
        return next;
      });
    }

    setHighlightedAdsetId(targetAdsetId);
    scrolledToRef.current = null; // reset so scroll effect fires for this new target
  }, [adsets, targetAdsetId]);


  const syncAll = async () => {
    setSyncing(true);
    setSyncingRT(true);
    showInfo('Syncing Meta and RedTrack data...');
    try {
      const metaParams = adAccountId ? `?ad_account_id=${adAccountId}` : '';
      const rtParams = datePreset === 'custom' && dateFrom && dateTo
        ? new URLSearchParams({ date_from: dateFrom, date_to: dateTo })
        : new URLSearchParams({ date_preset: datePreset });

      const [metaRes] = await Promise.all([
        authFetch(`${API_BASE}/facebook/sync${metaParams}`, { method: 'POST' }),
        authFetch(`${API_BASE}/redtrack/sync?${rtParams}`, { method: 'POST' }).catch(() => null),
      ]);

      if (!metaRes.ok) {
        const e = await metaRes.json().catch(() => ({}));
        throw new Error(e.detail || 'Meta sync failed');
      }
      const result = await metaRes.json();
      showSuccess(
        `Sync complete — ${result.campaigns.created} campaigns, ${result.adsets.created} ad sets imported. ${result.adsets.updated} ad sets updated.`
      );
      loadAdsets();
      const from = datePreset === 'custom' ? dateFrom : null;
      const to   = datePreset === 'custom' ? dateTo   : null;
      loadBulkInsights(adAccountId, datePreset, from, to);
    } catch (e) { showError(e.message || 'Sync failed'); }
    finally { setSyncing(false); setSyncingRT(false); }
  };

  const assignBrandToAdset = async (adsetId, brandId, brandName) => {
    setAssigningBrand(adsetId);
    try {
      const res = await authFetch(`${API_BASE}/facebook/adsets/${adsetId}/brand`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ brand_id: brandId || null }),
      });
      if (!res.ok) { const e = await res.json(); throw new Error(e.detail || 'Failed'); }
      setCampaignBrands(prev => ({
        ...prev,
        [adsetId]: brandId ? { brand_id: brandId, brand_name: brandName } : null,
      }));
      showSuccess(brandId ? `Brand assigned to ad set` : 'Brand removed from ad set');
    } catch (e) { showError(e.message); }
    finally { setAssigningBrand(null); }
  };

  const saveBudget = async (fbAdsetId) => {
    const dollars = parseFloat(budgetInput);
    if (!dollars || dollars < 1) {
      showError('Enter a valid budget ($1 minimum)');
      return;
    }
    setSavingBudget(fbAdsetId);
    try {
      const dailyBudgetCents = Math.round(dollars * 100);
      const res = await authFetch(`${API_BASE}/facebook/adsets/${fbAdsetId}/budget`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ daily_budget_cents: dailyBudgetCents }),
      });
      if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || 'Failed'); }
      setAdsets(prev => prev.map(a => (
        a.fb_adset_id === fbAdsetId
          ? { ...a, daily_budget: dailyBudgetCents, budget_schedule_type: 'DAILY' }
          : a
      )));
      showSuccess(`Budget updated to $${dollars.toFixed(0)}/day`);
      setEditingBudget(null);
      setBudgetInput('');
    } catch (e) {
      showError(e.message || 'Budget update failed');
    } finally {
      setSavingBudget(null);
    }
  };

  const saveCampaignBudget = async (fbCampaignId) => {
    const isCBO = campaignBudgetType === 'CBO';
    const dollars = parseFloat(campaignBudgetInput);
    if (isCBO && (!dollars || dollars < 1)) {
      showError('Enter a valid budget ($1 minimum)');
      return;
    }

    setSavingCampaignBudget(fbCampaignId);
    try {
      const res = await authFetch(`${API_BASE}/facebook/campaigns/${fbCampaignId}/budget`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          daily_budget_cents: isCBO ? Math.round(dollars * 100) : null,
          budget_optimization: campaignBudgetType,
        }),
      });
      if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || 'Failed'); }
      showSuccess(isCBO
        ? `Campaign budget set to $${dollars.toFixed(0)}/day`
        : 'Campaign switched to ABO — set budgets on each ad set below'
      );
      setBudgetPopover(null);
      loadAdsets();
    } catch (e) {
      showError(e.message || 'Campaign budget update failed');
    } finally {
      setSavingCampaignBudget(null);
    }
  };

  const askAI = async () => {
    if (!aiQuery.trim() || aiLoading) return;
    setAiLoading(true);
    setAiAnswer('');
    try {
      const res = await authFetch(`${API_BASE}/ai-insights/query`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: aiQuery.trim(), ad_account_id: adAccountId || undefined }),
      });
      if (!res.ok) { const e = await res.json(); throw new Error(e.detail || 'Query failed'); }
      const data = await res.json();
      setAiAnswer(data.answer);
    } catch (e) {
      showError(e.message || 'AI query failed — try again');
    } finally {
      setAiLoading(false);
    }
  };

  // Blended CPL across all adsets with data — mirrors Dashboard.jsx logic.
  const blendedCpl = useMemo(() => {
    if (!bulkInsights) return null;
    let totalSpend = 0, totalLeads = 0;
    Object.values(bulkInsights).forEach(ins => {
      totalSpend += ins.spend ?? 0;
      totalLeads += ins.leads ?? 0;
    });
    return totalLeads > 0 ? totalSpend / totalLeads : null;
  }, [bulkInsights]);

  // Helper: is this ad set flagged for attention?
  // Criteria must stay in sync with Dashboard.jsx needsAttention logic.
  const isFlagged = useCallback((a) => {
    const ins = bulkInsights?.[a.fb_adset_id];
    if (!ins) return false;
    if (ins.frequency >= 3) return true;
    if (ins.spend > 50 && ins.leads === 0) return true;
    if (rules.some(r => r.triggered_at && r.adset_id === a.id)) return true;
    if (ins.redtrack?.roas != null && ins.redtrack.roas < 1 && ins.spend > 30) return true;
    // CPL well above blended average (>1.5x) with meaningful spend — mirrors Dashboard
    if (blendedCpl != null && ins.cpl != null && ins.cpl > blendedCpl * 1.5 && ins.spend > 30) return true;
    return false;
  }, [bulkInsights, rules, blendedCpl]);

  const getAdsetStatus = useCallback((adset) => (
    normalizeStatus(adsetStatusOverrides[adset.fb_adset_id] ?? adset.status)
  ), [adsetStatusOverrides]);

  const getCampaignStatus = useCallback((adset) => (
    normalizeStatus(adset.campaign_status)
  ), []);

  const isActiveDelivery = useCallback((adset) => {
    const adsetStatus = getAdsetStatus(adset);
    const campaignStatus = getCampaignStatus(adset);
    return adsetStatus === 'ACTIVE' && (!campaignStatus || campaignStatus === 'ACTIVE');
  }, [getAdsetStatus, getCampaignStatus]);

  const isPausedDelivery = useCallback((adset) => {
    const adsetStatus = getAdsetStatus(adset);
    const campaignStatus = getCampaignStatus(adset);
    return adsetStatus === 'PAUSED' || campaignStatus === 'PAUSED';
  }, [getAdsetStatus, getCampaignStatus]);

  const visibleAdsets = useMemo(() => {
    let list = adsets.filter(a => a.fb_adset_id);

    // Status / spend / flagged filter.
    // "Active only" means active delivery: ad set is active and its parent campaign is not paused.
    if (statusFilter === 'ACTIVE') {
      list = list.filter(isActiveDelivery);
    } else if (statusFilter === 'PAUSED') {
      list = list.filter(isPausedDelivery);
    } else if (statusFilter === 'has_spend') {
      list = list.filter(a => (bulkInsights?.[a.fb_adset_id]?.spend ?? 0) > 0);
    } else if (statusFilter === 'flagged') {
      list = list.filter(a => isActiveDelivery(a) && isFlagged(a));
    }

    // Sort
    list = [...list].sort((a, b) => {
      if (sortBy === 'status') {
        const sa = getAdsetStatus(a), sb = getAdsetStatus(b);
        if (sa === sb) return a.name.localeCompare(b.name);
        return sa === 'ACTIVE' ? -1 : 1;
      }
      if (sortBy === 'name') return a.name.localeCompare(b.name);
      if (sortBy === 'spend') {
        const sa = bulkInsights?.[a.fb_adset_id]?.spend ?? -1;
        const sb = bulkInsights?.[b.fb_adset_id]?.spend ?? -1;
        return sb - sa;
      }
      if (sortBy === 'cpl') {
        const ca = bulkInsights?.[a.fb_adset_id]?.cpl ?? Infinity;
        const cb = bulkInsights?.[b.fb_adset_id]?.cpl ?? Infinity;
        return ca - cb;
      }
      if (sortBy === 'roas') {
        const ra = bulkInsights?.[a.fb_adset_id]?.redtrack?.roas ?? -1;
        const rb = bulkInsights?.[b.fb_adset_id]?.redtrack?.roas ?? -1;
        return rb - ra; // highest RT ROAS first
      }
      return 0;
    });

    return list;
  }, [adsets, statusFilter, sortBy, bulkInsights, isFlagged, getAdsetStatus, isActiveDelivery, isPausedDelivery]);

  useEffect(() => {
    if (!targetAdsetId || targetAdsetId === 'null') return;
    if (!visibleAdsets.some(a => a.fb_adset_id === targetAdsetId)) return;
    if (scrolledToRef.current === targetAdsetId) return; // already scrolled, don't re-fire on filter changes

    window.requestAnimationFrame(() => {
      const row = rowRefs.current[targetAdsetId];
      if (!row) return;
      scrolledToRef.current = targetAdsetId;
      row.scrollIntoView({ behavior: 'smooth', block: 'center' });
    });
  }, [targetAdsetId, visibleAdsets]);

  // Group the sorted adsets by campaign, then sort groups by total spend descending.
  // Orphaned adsets (no campaign_id) fall into a catch-all group at the bottom.
  const groupedCampaigns = useMemo(() => {
    const map = new Map();
    for (const adset of visibleAdsets) {
      const key = adset.campaign_id ?? '__orphaned';
      if (!map.has(key)) {
        map.set(key, {
          key,
          campaignId: adset.campaign_id ?? null,
          campaignName: adset.campaign_name ?? 'Other',
          campaignStatus: adset.campaign_status ?? null,
          adsets: [],
          totalSpend: 0,
          totalLeads: 0,
          totalRevenue: 0,
          rtRoas: null,
          cpl: null,
        });
      }
      const group = map.get(key);
      group.adsets.push(adset);
      const insight = bulkInsights?.[adset.fb_adset_id];
      group.totalSpend += insight?.spend ?? 0;
      group.totalLeads += insight?.leads ?? 0;
      group.totalRevenue += insight?.redtrack?.revenue ?? 0;
    }
    const targetAdsetId = searchParams.get('adsetId');
    return [...map.values()].map(group => ({
      ...group,
      fbCampaignId: group.adsets[0]?.fb_campaign_id ?? null,
      campaignBudgetOptimization: group.adsets[0]?.campaign_budget_optimization || (group.adsets[0]?.campaign_daily_budget ? 'CBO' : null),
      campaignDailyBudget: group.adsets[0]?.campaign_daily_budget ?? null,
      cpl: group.totalSpend > 0 && group.totalLeads > 0 ? group.totalSpend / group.totalLeads : null,
      rtRoas: group.totalSpend > 0 && group.totalRevenue > 0 ? group.totalRevenue / group.totalSpend : null,
      hasTarget: targetAdsetId ? group.adsets.some(a => a.fb_adset_id === targetAdsetId) : false,
    })).sort((a, b) => {
      if (a.hasTarget) return -1;
      if (b.hasTarget) return 1;
      if (a.key === '__orphaned') return 1;
      if (b.key === '__orphaned') return -1;
      return b.totalSpend - a.totalSpend;
    });
  }, [visibleAdsets, bulkInsights, searchParams]);

  const formatMoneyCell = (value, decimals = 0) => (
    value != null ? `$${Number(value).toLocaleString('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals })}` : '--'
  );

  const formatNumberCell = (value) => (
    value != null ? Number(value).toLocaleString('en-US') : '--'
  );

  const formatRoasCell = (value) => (
    value != null ? `${Number(value).toFixed(2)}x` : '--'
  );

  const cplCellClass = (cpl) => (
    cpl != null && (cpl > 60 || (blendedCpl != null && cpl > blendedCpl * 1.5))
      ? 'text-red-600'
      : 'text-gray-800'
  );

  const roasCellClass = (roas) => {
    if (roas == null) return 'text-gray-400';
    if (roas >= 2) return 'text-green-600';
    if (roas < 1) return 'text-red-600';
    return 'text-gray-800';
  };

  const profitCellClass = (profit) => (
    profit == null ? 'text-gray-400' : profit < 0 ? 'text-red-600' : 'text-green-600'
  );

  return (
    <>
    <div className="-m-5 space-y-0">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 px-5 pt-5 pb-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-2">
            <BarChart2 size={26} className="text-indigo-500" />
            Campaign Performance
          </h1>
          <p className="text-gray-500 text-sm mt-1">
            Live Meta insights · RedTrack conversions · Auto-pause rules
          </p>
        </div>
        <div className="flex items-center gap-3 flex-wrap">
          <button
            onClick={() => setShowAddRuleModal(true)}
            className="flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium border border-orange-200 text-orange-600 bg-orange-50 hover:bg-orange-100 transition-colors"
            title="Create an auto-pause rule for any tracked ad set"
          >
            <ShieldAlert size={14} />
            + Add Rule
          </button>
          <button
            onClick={syncAll}
            disabled={syncing || syncingRT}
            className="flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium border border-gray-200 text-gray-600 hover:bg-gray-50 transition-colors disabled:opacity-50"
            title="Import campaign + ad set structure from Meta and refresh RedTrack conversion data"
          >
            <RefreshCw size={14} className={(syncing || syncingRT) ? 'animate-spin' : ''} />
            {(syncing || syncingRT) ? 'Syncing...' : 'Sync'}
          </button>
          <div className="flex flex-col items-end gap-1">
            <div className="flex items-center gap-2">
              <select
                className="border border-gray-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500"
                value={datePreset}
                onChange={e => { setDatePreset(e.target.value); setDateFrom(''); setDateTo(''); }}
              >
                {DATE_PRESETS.map(d => <option key={d.value} value={d.value}>{d.label}</option>)}
              </select>
              {datePreset === 'custom' && (
                <>
                  <input
                    type="date"
                    value={dateFrom}
                    onChange={e => setDateFrom(e.target.value)}
                    className="border border-gray-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500"
                  />
                  <span className="text-gray-400 text-sm">→</span>
                  <input
                    type="date"
                    value={dateTo}
                    onChange={e => setDateTo(e.target.value)}
                    className="border border-gray-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500"
                  />
                </>
              )}
            </div>
            {datePreset === 'today' && [0, 6].includes(new Date().getDay()) && (
              <span className="text-xs text-amber-600 font-medium">
                Weekend — switch to Last 7 Days to see recent ads
              </span>
            )}
          </div>
        </div>
      </div>

      {/* Dashboard deep-link banner */}
      {dashboardView && (
        <div className={`flex items-center justify-between mx-5 mb-2 rounded-xl px-4 py-3 text-sm font-medium border ${
          highlightedAdsetId
            ? 'bg-indigo-50 border-indigo-200 text-indigo-800'
            : dashboardView === 'attention'
              ? 'bg-orange-50 border-orange-200 text-orange-800'
              : 'bg-green-50 border-green-200 text-green-800'
        }`}>
          <div className="flex items-center gap-2">
            {highlightedAdsetId
              ? (() => {
                  const target = adsets.find(a => a.fb_adset_id === highlightedAdsetId);
                  return <><Target size={15} /> Viewing: <span className="font-semibold">{target?.name ?? highlightedAdsetId}</span></>;
                })()
              : dashboardView === 'attention'
                ? <><AlertTriangle size={15} /> Showing flagged ad sets — high frequency, zero-lead spend, or auto-paused</>
                : <><TrendingUp size={15} /> Showing top performers — sorted by RT ROAS, active with spend</>
            }
          </div>
          <button
            onClick={() => { setSearchParams({}); setStatusFilter('ACTIVE'); setSortBy('spend'); setHighlightedAdsetId(null); }}
            className="ml-4 hover:opacity-70 transition-opacity"
          >
            <X size={14} />
          </button>
        </div>
      )}

      <div className="px-5 pb-5 space-y-4 mt-1">
      <CampaignIntelligencePanel
        adAccountId={adAccountId}
        initialOpen={intelligencePanelOpen}
        initialPreset={intelligenceInitialPreset}
      />

      {/* Ad Set Performance Table */}
      <div className="bg-white rounded-xl border border-indigo-100 border-l-4 border-l-indigo-500 shadow-sm overflow-clip">
        <div className="px-6 py-4 border-b border-indigo-100 bg-indigo-50/35 flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <h2 className="font-semibold text-gray-900 flex items-center gap-2">
              <Target size={16} className="text-indigo-600" /> Performance
              <span className="text-xs text-gray-500 font-normal">
                {groupedCampaigns.length} campaign{groupedCampaigns.length !== 1 ? 's' : ''} · {visibleAdsets.length} ad set{visibleAdsets.length !== 1 ? 's' : ''}
              </span>
            </h2>
            <button
              onClick={() => {
                if (collapsedCampaigns.size === groupedCampaigns.length) {
                  setCollapsedCampaigns(new Set());
                } else {
                  setCollapsedCampaigns(new Set(groupedCampaigns.map(g => g.key)));
                }
              }}
              className="text-xs text-gray-500 hover:text-indigo-600 px-2 py-1 rounded-lg border border-gray-200 hover:border-indigo-200 transition-colors"
            >
              {collapsedCampaigns.size === groupedCampaigns.length ? 'Expand all' : 'Collapse all'}
            </button>
          </div>
          <div className="flex items-center gap-2">
            {/* Status filter */}
            <select
              className="border border-gray-200 rounded-lg px-2 py-1.5 text-xs text-gray-600 focus:outline-none focus:ring-2 focus:ring-indigo-500"
              value={statusFilter}
              onChange={e => { setStatusFilter(e.target.value); setSearchParams(p => { const n = new URLSearchParams(p); n.delete('view'); n.delete('adsetId'); return n; }); setHighlightedAdsetId(null); }}
            >
              <option value="all">All ad sets</option>
              <option value="ACTIVE">Active only</option>
              <option value="PAUSED">Paused only</option>
              <option value="has_spend">Has spend</option>
              <option value="flagged">⚠ Needs attention</option>
            </select>
            {/* Sort */}
            <select
              className="border border-gray-200 rounded-lg px-2 py-1.5 text-xs text-gray-600 focus:outline-none focus:ring-2 focus:ring-indigo-500"
              value={sortBy}
              onChange={e => { setSortBy(e.target.value); setSearchParams(p => { const n = new URLSearchParams(p); n.delete('view'); n.delete('adsetId'); return n; }); setHighlightedAdsetId(null); }}
            >
              <option value="status">Sort: Active first</option>
              <option value="spend">Sort: Spend ↓</option>
              <option value="cpl">Sort: CPL ↑</option>
              <option value="roas">Sort: RT ROAS ↓</option>
              <option value="name">Sort: Name A–Z</option>
            </select>
            <button
              onClick={() => { loadAdsets(); loadBulkInsights(adAccountId, datePreset, datePreset === 'custom' ? dateFrom : null, datePreset === 'custom' ? dateTo : null); }}
              className="text-gray-400 hover:text-gray-600 transition-colors"
              title="Refresh"
            >
              <RefreshCw size={14} />
            </button>
          </div>
        </div>

        {/* Show spinner while loading — especially important for insight-dependent filters */}
        {(loadingAdsets || (bulkInsightsLoading && ['flagged', 'has_spend', 'roas'].includes(statusFilter))) ? (
          <div className="p-8 text-center text-gray-400 text-sm flex items-center justify-center gap-2">
            <RefreshCw size={14} className="animate-spin" /> Loading…
          </div>
        ) : visibleAdsets.length === 0 ? (
          <div className="p-8 text-center text-gray-400 text-sm">
            {statusFilter === 'has_spend' ? 'No ad sets with spend in this date range.' :
             statusFilter === 'flagged' ? 'No flagged ad sets — everything looks healthy.' :
             statusFilter !== 'all' ? `No ${statusFilter.toLowerCase()} ad sets found.` :
             'No launched ad sets found. Create and launch a campaign first.'}
          </div>
        ) : (
          <div>
            <div className="grid grid-cols-[minmax(360px,1fr)_96px_84px_96px_96px_124px] px-6 py-1.5 border-b border-slate-200 bg-slate-50 text-[10px] font-semibold uppercase tracking-wide text-gray-400 sticky top-0 z-10">
              <div />
              {['Spend', 'Leads', 'CPL', 'ROAS', 'Budget'].map(col => (
                <div key={col} className="border-l border-slate-200 px-3 text-right">{col}</div>
              ))}
            </div>
            {groupedCampaigns.map(group => {
              const isCampaignOpen = !collapsedCampaigns.has(group.key);
              const activeCount = group.adsets.filter(isActiveDelivery).length;

              return (
                <div key={group.key} className="border-b border-gray-100 last:border-b-0">
                  <div
                    onClick={() => toggleCampaign(group.key)}
                    className="w-full grid grid-cols-[minmax(360px,1fr)_96px_84px_96px_96px_124px] px-6 py-3 bg-slate-100/80 hover:bg-slate-100 transition-colors text-left border-b border-slate-200 border-l-4 border-l-slate-500"
                    role="button"
                    tabIndex={0}
                    onKeyDown={e => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault();
                        toggleCampaign(group.key);
                      }
                    }}
                  >
                    <div className="flex items-center gap-2 min-w-0 pr-4">
                      {isCampaignOpen
                        ? <ChevronDown size={16} className="text-gray-500 flex-shrink-0" />
                        : <ChevronRight size={16} className="text-gray-500 flex-shrink-0" />
                      }
                      <span className="font-semibold text-gray-800 text-sm truncate">{group.campaignName}</span>
                      {group.campaignStatus && (
                        <span aria-hidden="true" className={`flex-shrink-0 text-xs px-2 py-0.5 rounded border font-medium ${
                          group.campaignStatus === 'ACTIVE'
                            ? 'border-green-400 text-green-700 bg-white'
                            : 'border-gray-300 text-gray-500 bg-white'
                        }`}>
                          {group.campaignStatus}
                        </span>
                      )}
                      <span className="flex-shrink-0 text-xs text-gray-400">
                        {activeCount > 0 ? `${activeCount} active` : `${group.adsets.length}`} ad set{group.adsets.length !== 1 ? 's' : ''}
                      </span>
                    </div>
                    {[
                      ['Spend', bulkInsightsLoading ? '--' : formatMoneyCell(group.totalSpend)],
                      ['Leads', bulkInsightsLoading ? '--' : formatNumberCell(group.totalLeads)],
                      ['CPL', bulkInsightsLoading ? '--' : formatMoneyCell(group.cpl, 2)],
                      ['ROAS', bulkInsightsLoading ? '--' : formatRoasCell(group.rtRoas)],
                    ].map(([label, value]) => (
                      <div key={label} className="border-l border-slate-200 px-3 text-right">
                        <span className="text-sm font-semibold text-gray-800">{value}</span>
                      </div>
                    ))}

                    <div className="border-l border-slate-200 pl-3 text-right" onClick={e => e.stopPropagation()}>
                      {group.fbCampaignId && (
                        <div className="relative">
                          <button
                            onClick={() => {
                              if (budgetPopover === group.fbCampaignId) {
                                setBudgetPopover(null);
                              } else {
                                setBudgetPopover(group.fbCampaignId);
                                setCampaignBudgetType(group.campaignBudgetOptimization || 'CBO');
                                setCampaignBudgetInput(
                                  group.campaignDailyBudget
                                    ? (group.campaignDailyBudget / 100).toFixed(0)
                                    : ''
                                );
                              }
                            }}
                            className="ml-auto flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-white border border-gray-200 hover:border-indigo-300 hover:bg-indigo-50 transition-colors text-gray-700 hover:text-indigo-700 text-xs font-medium shadow-sm"
                            title="Edit campaign budget settings"
                          >
                            <DollarSign size={12} />
                            {group.campaignBudgetOptimization === 'CBO' && group.campaignDailyBudget ? (
                              <span className="flex flex-col items-end leading-tight">
                                <span>${(group.campaignDailyBudget / 100).toFixed(0)}/day</span>
                                <span className="text-[9px] text-gray-400 font-normal">campaign</span>
                              </span>
                            ) : group.campaignBudgetOptimization === 'CBO'
                                ? 'CBO'
                                : group.campaignBudgetOptimization === 'ABO'
                                  ? 'ABO'
                                  : 'Budget'
                            }
                          </button>

                          {budgetPopover === group.fbCampaignId && (
                            <div
                              className="absolute right-0 top-10 w-64 bg-white rounded-xl border border-gray-200 shadow-lg p-4 z-50 text-left"
                              onClick={e => e.stopPropagation()}
                            >
                              <div className="text-xs font-semibold text-gray-700 mb-3">Campaign Budget Settings</div>

                              <div className="mb-3">
                                <div className="text-[10px] text-gray-400 uppercase tracking-wide mb-1.5">Budget Type</div>
                                <div className="grid grid-cols-2 gap-1 bg-gray-100 rounded-lg p-0.5">
                                  {['CBO', 'ABO'].map(type => (
                                    <button
                                      key={type}
                                      onClick={() => setCampaignBudgetType(type)}
                                      className={`py-1.5 rounded-md text-xs font-semibold transition-all ${
                                        campaignBudgetType === type
                                          ? 'bg-white text-indigo-700 shadow-sm'
                                          : 'text-gray-500'
                                      }`}
                                    >
                                      {type}
                                      <span className="text-[10px] font-normal text-gray-400 block">
                                        {type === 'CBO' ? 'Campaign level' : 'Ad set level'}
                                      </span>
                                    </button>
                                  ))}
                                </div>
                              </div>

                              {campaignBudgetType === 'CBO' && (
                                <div className="mb-3">
                                  <div className="text-[10px] text-gray-400 uppercase tracking-wide mb-1">Daily Budget</div>
                                  <div className="flex items-center gap-1.5 border border-gray-200 rounded-lg px-2.5 py-1.5 focus-within:ring-1 focus-within:ring-indigo-400 focus-within:border-indigo-300">
                                    <span className="text-gray-400 text-xs">$</span>
                                    <input
                                      type="number"
                                      min="1"
                                      step="1"
                                      value={campaignBudgetInput}
                                      onChange={e => setCampaignBudgetInput(e.target.value)}
                                      onKeyDown={e => {
                                        if (e.key === 'Enter') saveCampaignBudget(group.fbCampaignId);
                                        if (e.key === 'Escape') setBudgetPopover(null);
                                      }}
                                      placeholder="e.g. 500"
                                      className="flex-1 text-sm font-semibold focus:outline-none text-gray-800 w-full"
                                      autoFocus
                                    />
                                    <span className="text-gray-400 text-xs">/day</span>
                                  </div>
                                </div>
                              )}

                              {campaignBudgetType === 'ABO' && (
                                <div className="mb-3 text-xs text-amber-700 bg-amber-50 border border-amber-100 rounded-lg px-2.5 py-2">
                                  Removes campaign budget. Set budgets on each ad set individually using the $ Budget button on each row.
                                </div>
                              )}

                              <div className="flex gap-2">
                                <button
                                  onClick={() => setBudgetPopover(null)}
                                  className="flex-1 py-1.5 text-xs rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50"
                                >
                                  Cancel
                                </button>
                                <button
                                  onClick={() => saveCampaignBudget(group.fbCampaignId)}
                                  disabled={savingCampaignBudget === group.fbCampaignId}
                                  className="flex-1 py-1.5 text-xs rounded-lg bg-indigo-600 text-white font-semibold hover:bg-indigo-700 disabled:opacity-50"
                                >
                                  {savingCampaignBudget === group.fbCampaignId ? 'Saving...' : 'Save'}
                                </button>
                              </div>
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  </div>

                  {isCampaignOpen && (
                    <div className="overflow-x-auto">
                      <table className="w-full text-sm">
                        <thead className="bg-white border-b border-gray-100 sticky top-0 z-10">
                          <tr className="text-left text-[11px] font-semibold uppercase tracking-wide text-gray-400">
                            <th className="px-6 py-2.5 min-w-[200px] max-w-[260px]">Ad Set Name</th>
                            <th className="px-3 py-2.5">Status</th>
                            <th className="px-3 py-2.5">
                              <span className="flex items-center gap-1">
                                Budget
                                <span
                                  className="inline-flex items-center justify-center w-3.5 h-3.5 rounded-full bg-gray-200 text-gray-500 text-[9px] font-bold cursor-help leading-none"
                                  title="CBO (Campaign Budget Optimization): budget is set at the campaign level — use the $ button on the campaign header row. ABO (Ad Set Budget Optimization): each ad set has its own budget — use the $ Set budget button on each row. '$X/day' = live CBO budget. '-- CBO' = this adset's budget is controlled by the campaign."
                                >?</span>
                              </span>
                            </th>
                            <th className="px-3 py-2.5 text-right">Spend</th>
                            <th className="px-3 py-2.5 text-right">Leads</th>
                            <th className="px-3 py-2.5 text-right">CPL</th>
                            <th className="px-3 py-2.5 text-right">ROAS</th>
                            <th className="px-3 py-2.5 text-right">Profit</th>
                            <th className="px-3 py-2.5">Brand</th>
                            <th className="px-6 py-2.5 text-right">Actions</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-gray-50">
                          {group.adsets.map(adset => {
                            const isExpanded = expandedAdsets.has(adset.fb_adset_id);
                            const effectiveStatus = getAdsetStatus(adset);
                            const isPausingAdset = pausingAdsets.has(adset.fb_adset_id);
                            const d = bulkInsights?.[adset.fb_adset_id];
                            const rt = d?.redtrack;
                            const rowRoas = rt?.roas ?? d?.roas ?? null;
                            const rowProfit = rt?.profit ?? null;
                            const adsetAds = adsBulk?.[adset.fb_adset_id] || [];
                            const adsetAvgCpl = adsetAds.filter(a => a.leads > 0).length > 0
                              ? adsetAds.filter(a => a.leads > 0).reduce((s, a) => s + a.cpl, 0) / adsetAds.filter(a => a.leads > 0).length
                              : null;
                            const hasPoorCreatives = adsetAds.some(a => {
                              const adsetProfitableByRt = rt?.roas != null && rt.roas >= 1;
                              const isPoorRoas = (a.roas != null && a.roas < 1) && !adsetProfitableByRt;
                              const isHighCpl = adsetAvgCpl != null && a.cpl != null && a.cpl > adsetAvgCpl * 1.4 && a.spend > 20;
                              const isNoLeads = a.spend >= 20 && a.leads === 0;
                              return isPoorRoas || isHighCpl || isNoLeads;
                            });
                            const adsetRules = rules.filter(r => r.adset_id === adset.id);
                            const triggeredRule = adsetRules.find(r => r.triggered_at);
                            const activeRule = adsetRules.find(r => r.is_active && !r.triggered_at);
                            const cb = campaignBrands[adset.id];
                            const isAssigning = assigningBrand === adset.id;
                            const isHighlighted = highlightedAdsetId === adset.fb_adset_id;

                            const toggleExpand = () => setExpandedAdsets(prev => {
                              const next = new Set(prev);
                              next.has(adset.fb_adset_id) ? next.delete(adset.fb_adset_id) : next.add(adset.fb_adset_id);
                              return next;
                            });

                            return (
                              <React.Fragment key={adset.id}>
                                <tr
                                  ref={node => {
                                    if (node) rowRefs.current[adset.fb_adset_id] = node;
                                  }}
                                  className={`group transition-colors ${effectiveStatus === 'PAUSED' ? 'opacity-60' : ''} ${isHighlighted ? 'bg-indigo-50' : 'hover:bg-gray-50/70'}`}
                                >
                                  <td className={`px-6 py-3 align-middle ${isHighlighted ? 'border-l-4 border-indigo-500' : ''}`}>
                                    <button
                                      onClick={toggleExpand}
                                      className="flex items-center gap-2 min-w-0 text-left"
                                      title="Show creative breakdown"
                                    >
                                      <span className="flex-shrink-0 text-gray-400">
                                        {isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                                      </span>
                                      <span className="font-medium text-gray-900 truncate" title={adset.name}>{adset.name}</span>
                                      {hasPoorCreatives && !isExpanded && (
                                        <span className="flex-shrink-0 text-xs px-1.5 py-0.5 rounded font-medium bg-orange-50 text-orange-600 flex items-center gap-1">
                                          <AlertTriangle size={10} /> Poor creative
                                        </span>
                                      )}
                                      {triggeredRule && (
                                        <span className="flex-shrink-0 text-xs px-1.5 py-0.5 rounded font-medium bg-red-100 text-red-700 flex items-center gap-1">
                                          <PauseCircle size={10} /> Rule triggered
                                        </span>
                                      )}
                                      {!triggeredRule && activeRule && (
                                        <span className="flex-shrink-0 text-xs px-1.5 py-0.5 rounded font-medium bg-indigo-50 text-indigo-600 flex items-center gap-1">
                                          <Zap size={10} /> Rule active
                                        </span>
                                      )}
                                    </button>
                                  </td>
                                  <td className="px-3 py-3 align-middle">
                                    <span className={`text-xs px-1.5 py-0.5 rounded font-medium ${
                                      effectiveStatus === 'ACTIVE' ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'
                                    }`}>{effectiveStatus}</span>
                                  </td>
                                  <td className="px-3 py-3 align-middle">
                                    <div className="flex items-center">
                                      {group.campaignBudgetOptimization === 'CBO' ? (
                                        <span className="text-gray-400 italic text-[11px]">-- CBO</span>
                                      ) : editingBudget === adset.fb_adset_id ? (
                                        <div className="flex items-center gap-1" onClick={e => e.stopPropagation()}>
                                          <span className="text-xs text-gray-400">$</span>
                                          <input
                                            type="number"
                                            min="1"
                                            step="1"
                                            value={budgetInput}
                                            onChange={e => setBudgetInput(e.target.value)}
                                            onKeyDown={e => {
                                              if (e.key === 'Enter') saveBudget(adset.fb_adset_id);
                                              if (e.key === 'Escape') { setEditingBudget(null); setBudgetInput(''); }
                                            }}
                                            className="w-20 text-xs border border-gray-200 rounded px-1.5 py-0.5 focus:outline-none focus:ring-1 focus:ring-indigo-400"
                                            autoFocus
                                          />
                                          <span className="text-xs text-gray-400">/day</span>
                                          <button
                                            onClick={() => saveBudget(adset.fb_adset_id)}
                                            disabled={savingBudget === adset.fb_adset_id}
                                            className="text-green-600 hover:text-green-700 disabled:opacity-40"
                                            title="Save budget"
                                          >
                                            {savingBudget === adset.fb_adset_id ? <RefreshCw size={12} className="animate-spin" /> : <Check size={12} />}
                                          </button>
                                          <button
                                            onClick={() => { setEditingBudget(null); setBudgetInput(''); }}
                                            className="text-gray-400 hover:text-gray-600"
                                            title="Cancel budget edit"
                                          >
                                            <X size={12} />
                                          </button>
                                        </div>
                                      ) : (
                                        <button
                                          onClick={e => {
                                            e.stopPropagation();
                                            setEditingBudget(adset.fb_adset_id);
                                            setBudgetInput(adset.daily_budget ? String(Math.round(adset.daily_budget / 100)) : '');
                                          }}
                                          className="flex items-center gap-1 text-xs px-2 py-1 rounded-lg bg-white border border-gray-200 hover:border-indigo-300 hover:bg-indigo-50 text-gray-600 hover:text-indigo-700 transition-colors shadow-sm font-medium"
                                          title="Edit daily budget"
                                        >
                                          <DollarSign size={11} />
                                          {adset.daily_budget ? `$${Math.round(adset.daily_budget / 100)}/day` : 'Set budget'}
                                        </button>
                                      )}
                                    </div>
                                  </td>
                                  <td className="px-3 py-3 text-right font-medium text-gray-800 align-middle">{bulkInsightsLoading && !d ? '--' : formatMoneyCell(d?.spend)}</td>
                                  <td className="px-3 py-3 text-right text-gray-700 align-middle">{bulkInsightsLoading && !d ? '--' : formatNumberCell(d?.leads)}</td>
                                  <td className={`px-3 py-3 text-right font-semibold align-middle ${cplCellClass(d?.cpl)}`}>{bulkInsightsLoading && !d ? '--' : formatMoneyCell(d?.cpl, 2)}</td>
                                  <td className={`px-3 py-3 text-right font-semibold align-middle ${roasCellClass(rowRoas)}`}>
                                    {bulkInsightsLoading && !d ? '--' : (
                                      <span>
                                        {formatRoasCell(rowRoas)}
                                        {rt?.roas != null && <span className="ml-1 text-[10px] font-medium text-blue-400">RT</span>}
                                      </span>
                                    )}
                                  </td>
                                  <td className={`px-3 py-3 text-right font-semibold align-middle ${profitCellClass(rowProfit)}`}>{bulkInsightsLoading && !d ? '--' : formatMoneyCell(rowProfit)}</td>
                                  <td className="px-3 py-3 align-middle">
                                    <span className="relative inline-block" onClick={e => e.stopPropagation()}>
                                      <select
                                        value={cb?.brand_id || ''}
                                        disabled={isAssigning}
                                        onChange={e => {
                                          const selected = brands.find(b => b.id === e.target.value);
                                          assignBrandToAdset(adset.id, e.target.value || null, selected?.name || null);
                                        }}
                                        className={`text-xs px-2 py-0.5 rounded-full border cursor-pointer appearance-none pr-5 max-w-[160px] ${
                                          cb ? 'bg-blue-50 text-blue-700 border-blue-200' : 'bg-gray-50 text-gray-400 border-gray-200 hover:border-blue-300'
                                        } disabled:opacity-50`}
                                        title="Assign brand to this ad set"
                                      >
                                        <option value="">{isAssigning ? 'Saving...' : '+ Brand'}</option>
                                        {brands.map(b => <option key={b.id} value={b.id}>{b.name}</option>)}
                                      </select>
                                      {cb && <Tag size={9} className="absolute right-1.5 top-1/2 -translate-y-1/2 text-blue-400 pointer-events-none" />}
                                    </span>
                                  </td>
                                  <td className="px-6 py-3 align-middle">
                                    <div className="flex justify-end items-center gap-1.5">
                                      <button
                                        onClick={() => navigate(`/batch-generate?adsetName=${encodeURIComponent(adset.name)}&adsetId=${encodeURIComponent(adset.fb_adset_id || '')}&campaignId=${encodeURIComponent(adset.fb_campaign_id || '')}`)}
                                        className="flex items-center gap-1 px-2 py-1 rounded text-xs font-medium bg-indigo-50 text-indigo-700 hover:bg-indigo-100 transition-colors"
                                        title="Try new creative variants"
                                      >
                                        <Repeat2 size={11} /> Iterate
                                      </button>
                                      {adset.fb_adset_id && (
                                        <button
                                          onClick={() => {
                                            const currentStatus = normalizeStatus(adsetStatusOverrides[adset.fb_adset_id] ?? adset.status);
                                            if (currentStatus === 'ACTIVE' && !window.confirm(`Pause "${adset.name}"?\n\nThis will stop delivery immediately in Meta.`)) return;
                                            toggleAdsetStatus(adset);
                                          }}
                                          disabled={isPausingAdset}
                                          className={`flex items-center gap-1 px-2 py-1 rounded text-xs font-medium transition-colors disabled:opacity-40 ${
                                            effectiveStatus === 'PAUSED'
                                              ? 'bg-green-50 text-green-700 hover:bg-green-100'
                                              : 'bg-gray-100 text-gray-600 hover:bg-red-50 hover:text-red-600'
                                          }`}
                                          title={effectiveStatus === 'PAUSED' ? 'Resume ad set' : 'Pause ad set'}
                                        >
                                          {isPausingAdset
                                            ? <RefreshCw size={11} className="animate-spin" />
                                            : effectiveStatus === 'PAUSED' ? <PlayCircle size={11} /> : <PauseCircle size={11} />
                                          }
                                          {effectiveStatus === 'PAUSED' ? 'Resume' : 'Pause'}
                                        </button>
                                      )}
                                      <button
                                        onClick={async () => {
                                          if (!window.confirm(`Remove "${adset.name}" from this app?\n\nAny auto-pause rules for this ad set will also be deleted. The ad set itself will not be affected in Meta.`)) return;
                                          try {
                                            const res = await authFetch(`${API_BASE}/facebook/adsets/saved/${adset.id}`, { method: 'DELETE' });
                                            if (!res.ok) throw new Error('Failed to remove');
                                            setAdsets(prev => prev.filter(a => a.id !== adset.id));
                                            showSuccess(`"${adset.name}" removed`);
                                          } catch (e) { showError(e.message); }
                                        }}
                                        className="opacity-0 group-hover:opacity-100 text-gray-400 hover:text-red-500 transition-all"
                                        title="Remove from app (does not affect Meta)"
                                      >
                                        <X size={13} />
                                      </button>
                                    </div>
                                  </td>
                                </tr>
                                {isExpanded && (
                                  <tr className="bg-gray-50/40">
                                    <td colSpan={10} className="px-6 pb-4 pt-2 border-t border-gray-100">
                                      {/* Adset-level diagnostic strip */}
                                      {d && (
                                        <div className="mb-3 flex flex-wrap gap-x-5 gap-y-1.5 pb-3 border-b border-gray-100">
                                          <span className="text-[10px] font-semibold text-gray-400 uppercase tracking-wide self-center w-8">Meta</span>
                                          {[
                                            { l: 'Reach', v: d.reach?.toLocaleString() ?? '—' },
                                            { l: 'Impressions', v: d.impressions?.toLocaleString() ?? '—' },
                                            { l: 'Frequency', v: d.frequency != null ? d.frequency.toFixed(2) : '—', bad: d.frequency >= 5, warn: d.frequency >= 3 && d.frequency < 5 },
                                            { l: 'Clicks', v: d.clicks?.toLocaleString() ?? '—' },
                                            { l: 'CTR', v: d.ctr ? `${parseFloat(d.ctr).toFixed(2)}%` : '—' },
                                          ].map(({ l, v, bad, warn }) => (
                                            <div key={l} className="flex flex-col">
                                              <span className="text-[10px] text-gray-400">{l}</span>
                                              <span className={`text-xs font-semibold ${bad ? 'text-red-600' : warn ? 'text-orange-500' : 'text-gray-800'}`}>{v}</span>
                                            </div>
                                          ))}
                                          {rt && (
                                            <>
                                              <span className="text-[10px] font-semibold text-blue-400 uppercase tracking-wide self-center w-8 ml-2">RT</span>
                                              {[
                                                { l: 'Convs', v: rt.conversions ?? '—' },
                                                { l: 'Quality', v: rt.quality_rate != null ? `${(rt.quality_rate * 100).toFixed(0)}%` : d.leads > 0 ? `${((rt.conversions / d.leads) * 100).toFixed(0)}%` : '—', bad: (rt.quality_rate ?? 1) < 0.5 },
                                                { l: 'Revenue', v: rt.revenue != null ? `$${rt.revenue.toFixed(2)}` : '—' },
                                                { l: 'Profit', v: rt.profit != null ? `$${rt.profit.toFixed(2)}` : '—', bad: rt.profit != null && rt.profit < 0 },
                                              ].map(({ l, v, bad }) => (
                                                <div key={l} className="flex flex-col">
                                                  <span className="text-[10px] text-blue-400">{l}</span>
                                                  <span className={`text-xs font-semibold ${bad ? 'text-red-600' : 'text-blue-700'}`}>{v}</span>
                                                </div>
                                              ))}
                                            </>
                                          )}
                                        </div>
                                      )}
                                      <AdsBreakdown
                                        fbAdsetId={adset.fb_adset_id}
                                        fbCampaignId={adset.fb_campaign_id || ''}
                                        adsetName={adset.name}
                                        campaignId={adset.campaign_id}
                                        adsBulk={adsBulk}
                                        adsLoading={adsLoading}
                                        rtAdsBulk={rtAdsBulk}
                                        onAdStatusChange={() => loadAdsBulk(adAccountId, datePreset, datePreset === 'custom' ? dateFrom : null, datePreset === 'custom' ? dateTo : null)}
                                        onRemix={(creative) => {
                                          const brandContext = campaignBrands[adset.id];
                                          setRemixDrawer({ ...creative, brand_id: brandContext?.brand_id || '', brand_name: brandContext?.brand_name || '' });
                                        }}
                                      />
                                    </td>
                                  </tr>
                                )}
                              </React.Fragment>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

      </div>{/* end space-y-4 card wrapper */}
    </div>

    {/* ── Floating Ask AI ─────────────────────────────────────────────────── */}
    {askAiOpen && (
      <div className="fixed inset-x-3 bottom-20 z-[60] sm:inset-x-auto sm:right-6 sm:w-[380px]">
        <div className="bg-white rounded-xl border border-gray-200 shadow-2xl overflow-hidden">
          <div className="flex items-start justify-between px-4 py-3 border-b border-gray-100">
            <div>
              <h2 className="text-sm font-semibold text-gray-900 flex items-center gap-2">
                <Sparkles size={15} className="text-violet-500" />
                Ask AI
              </h2>
              <p className="text-xs text-gray-400 mt-0.5">powered by Claude + live Meta data</p>
            </div>
            <button
              onClick={() => setAskAiOpen(false)}
              className="p-1 text-gray-400 hover:text-gray-600 transition-colors"
              title="Close Ask AI"
            >
              <X size={17} />
            </button>
          </div>
          <div className="p-4">
            <div className="flex gap-2">
              <input
                type="text"
                value={aiQuery}
                onChange={e => setAiQuery(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && askAI()}
                placeholder="Ask about performance..."
                className="min-w-0 flex-1 text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-violet-400 focus:border-transparent"
                disabled={aiLoading}
              />
              <button
                onClick={askAI}
                disabled={aiLoading || !aiQuery.trim()}
                className="flex items-center justify-center w-10 h-10 rounded-lg text-white bg-violet-600 hover:bg-violet-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex-shrink-0"
                title="Ask AI"
              >
                {aiLoading ? <RefreshCw size={14} className="animate-spin" /> : <Send size={14} />}
              </button>
            </div>
            {!aiAnswer && !aiLoading && (
              <div className="mt-3 flex flex-wrap gap-2">
                {[
                  'What are my worst ad sets today?',
                  'Which niches are underperforming this week?',
                  'What should I pause right now?',
                ].map(q => (
                  <button
                    key={q}
                    onClick={() => setAiQuery(q)}
                    className="text-xs px-2.5 py-1 rounded-full border border-gray-200 text-gray-500 hover:border-violet-300 hover:text-violet-600 transition-colors"
                  >
                    {q}
                  </button>
                ))}
              </div>
            )}
            {aiAnswer && (
              <div className="mt-3 p-3 bg-gray-50 rounded-lg border border-gray-100 max-h-72 overflow-y-auto">
                <div className="flex items-start gap-2">
                  <MessageSquare size={14} className="text-violet-400 flex-shrink-0 mt-0.5" />
                  <p className="text-sm text-gray-800 whitespace-pre-wrap leading-relaxed">{aiAnswer}</p>
                </div>
                <button
                  onClick={() => { setAiAnswer(''); setAiQuery(''); }}
                  className="mt-2 text-xs text-gray-400 hover:text-gray-600 transition-colors"
                >
                  Clear
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
    )}
    <button
      onClick={() => setAskAiOpen(open => !open)}
      className="fixed bottom-6 right-6 z-[60] flex items-center gap-2 rounded-full bg-gray-900 px-4 py-3 text-sm font-semibold text-white shadow-lg hover:bg-gray-800 transition-colors"
      title="Ask AI about campaign performance"
    >
      <MessageSquare size={16} />
      Ask AI
    </button>

    {/* ── Add Rule Modal ───────────────────────────────────────────────────── */}
    {showAddRuleModal && (
      <AddRuleModal
        adsets={adsets}
        onClose={() => setShowAddRuleModal(false)}
        onCreated={() => { setShowAddRuleModal(false); }}
      />
    )}

    {/* ── Remix Drawer ─────────────────────────────────────────────────────── */}
    {remixDrawer && (
      <RemixDrawer
        creative={remixDrawer}
        brands={brands}
        onClose={() => setRemixDrawer(null)}
        onLaunchWizard={(data) => {
          localStorage.setItem('pendingRemixCreative', JSON.stringify(data));
          navigate('/ad-remix');
        }}
      />
    )}
    </>
  );
}
