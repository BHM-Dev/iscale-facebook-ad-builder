import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { PauseCircle, PlayCircle, RefreshCw, AlertTriangle, TrendingDown, Target, Zap, ChevronDown, ChevronRight, TrendingUp, X, Repeat2, Sparkles, Tag, ChevronLeft, BarChart2, ShieldAlert, DollarSign, Check, Search, Rocket, MapPin } from 'lucide-react';
import { useToast } from '../context/ToastContext';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { authFetch } from '../lib/facebookApi';
import { useBrands } from '../context/BrandContext';
import { useCampaign } from '../context/CampaignContext';
import { safeLocalStorageSet } from '../lib/safeLocalStorage';

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
  { value: 'today',         label: 'Today' },
  { value: 'yesterday',    label: 'Yesterday' },
  { value: 'last_3d',      label: 'Last 3d' },
  { value: 'last_7d',      label: 'Last 7d' },
  { value: 'last_14d',     label: 'Last 14d' },
  { value: 'last_30d',     label: 'Last 30d' },
  { value: 'weekdays_mtd', label: 'Weekdays MTD' },
  { value: 'weekends_mtd', label: 'Weekends MTD' },
  { value: 'custom',       label: 'Custom' },
];
const INTELLIGENCE_PRESET_VALUES = new Set(INTELLIGENCE_PRESETS.map(p => p.value));

// Geography clamps Weekdays/Weekends MTD to a rolling window (currently 14
// days — see _clamp_geography_day_filter_window in intelligence.py) because
// the full month-to-date, account-wide, per-day, per-state query times out on
// large accounts. The clamp window is a backend constant, not something this
// file should re-guess: once the real result for a preset has loaded, use its
// own preset_label (the actual resolved window) instead of a static string
// that would silently drift if the backend's cap ever changes. Before data
// loads, "~14d" is an approximation, not a promise.
function intelligencePresetLabel(presetOption, intelligenceView, geographyData) {
  if (intelligenceView !== 'geography') return presetOption.label;
  if (presetOption.value !== 'weekdays_mtd' && presetOption.value !== 'weekends_mtd') return presetOption.label;
  if (geographyData?.preset === presetOption.value && geographyData?.preset_label) {
    return geographyData.preset_label;
  }
  return presetOption.value === 'weekdays_mtd' ? 'Weekdays (~14d)' : 'Weekends (~14d)';
}

function resolveIntelligencePreset(pageDatePreset, explicitPreset) {
  if (explicitPreset && INTELLIGENCE_PRESET_VALUES.has(explicitPreset)) return explicitPreset;
  if (pageDatePreset && INTELLIGENCE_PRESET_VALUES.has(pageDatePreset)) return pageDatePreset;
  return 'last_7d';
}

const normalizeStatus = (status) => (status || '').toString().toUpperCase();

function formatMoney(value) {
  return value != null
    ? `$${Number(value).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
    : '—';
}

function formatDateShort(value) {
  if (!value) return '—';
  const parsed = new Date(`${value}T12:00:00`);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

const BEST_TIMES_DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

function BestTimesGrid({ data }) {
  const attributionIncomplete = Boolean(data.attribution_complete === false);
  const [expandedContext, setExpandedContext] = useState(attributionIncomplete);
  const summarizeEntity = (item, key, label, level) => {
    const spend = (item.cells || []).reduce((sum, cell) => sum + Number(cell.spend || 0), 0);
    const revenue = item.revenue_source === 'not_tracked' ? null : (item.cells || []).reduce((sum, cell) => sum + Number(cell.revenue || 0), 0);
    return { ...item, key, label, level, totalSpend: spend, totalRevenue: revenue, totalRoi: revenue != null && spend > 0 ? (revenue - spend) / spend : null };
  };
  const campaignGroups = useMemo(() => {
    const campaigns = data.campaigns || [];
    if (campaigns.length) return campaigns.map(campaign => ({
      campaign: summarizeEntity(campaign, `campaign:${campaign.campaign_id || campaign.campaign_name}`, campaign.campaign_name, 'Campaign'),
      adsets: (campaign.adsets || []).map(adset => summarizeEntity(adset, `adset:${adset.adset_id}`, adset.adset_name, 'Ad set')),
    })).sort((a, b) => b.campaign.totalSpend - a.campaign.totalSpend);
    return [{ campaign: null, adsets: (data.niches || []).map(item => summarizeEntity(item, `legacy:${item.niche}`, item.niche, 'Timing group')) }];
  }, [data]);
  const selectionOptions = useMemo(() => campaignGroups.flatMap(group => [group.campaign, ...group.adsets].filter(Boolean)), [campaignGroups]);
  const [selectedEntityKey, setSelectedEntityKey] = useState(() => selectionOptions[0]?.key || '');
  const [search, setSearch] = useState('');
  const niche = selectionOptions.find(item => item.key === selectedEntityKey) || selectionOptions[0];
  const recommendation = niche?.recommendation;
  const timingBlocks = useMemo(() => niche?.timing_blocks || [], [niche]);
  const allocated = Boolean(data.attribution_allocated);
  const untracked = niche?.revenue_source === 'not_tracked';
  const groups = ['Mon–Fri', 'Sat–Sun'];
  const confidenceStyle = { high: 'bg-green-100 text-green-800', medium: 'bg-amber-100 text-amber-800', low: 'bg-gray-100 text-gray-600' };
  const roiHeatRange = useMemo(() => {
    const rois = timingBlocks.map(block => Number(block.roi)).filter(Number.isFinite);
    return {
      positive: Math.max(...rois.filter(roi => roi > 0), 0),
      negative: Math.abs(Math.min(...rois.filter(roi => roi < 0), 0)),
    };
  }, [timingBlocks]);
  const roiHeatStyle = block => {
    const roi = Number(block.roi);
    if (!Number.isFinite(roi) || roi === 0) return {};
    const range = roi > 0 ? roiHeatRange.positive : roiHeatRange.negative;
    if (!range) return {};
    const intensity = Math.min(Math.abs(roi) / range, 1);
    const alpha = 0.08 + (intensity * 0.22);
    return { backgroundColor: roi > 0 ? `rgba(34, 197, 94, ${alpha})` : `rgba(239, 68, 68, ${alpha})` };
  };
  const watchBlocks = useMemo(() => timingBlocks
    .filter(block => Number(block.roi) > 0 && block.status !== 'run' && block.evidence_bucket_count)
    .sort((a, b) => Number(b.roi) - Number(a.roi))
    .slice(0, 2), [timingBlocks]);
  const formatHour = hour => `${hour % 12 || 12} ${hour < 12 ? 'AM' : 'PM'}`;
  const scheduleLine = windows => windows?.length
    ? windows.map(window => `${window.group} · ${formatHour(window.start_hour)}–${formatHour(window.end_hour % 24)} PT`).join(' · ')
    : 'None identified';

  return (
    <div className="space-y-3">
      <div className="rounded-xl border border-gray-200 bg-gray-50 px-3 py-3">
        <label className="sr-only" htmlFor="best-times-search">Search campaigns or ad sets</label>
        <input id="best-times-search" value={search} onChange={e => setSearch(e.target.value)} placeholder="Search campaigns or ad sets" className="mb-2 w-full text-sm border border-gray-200 rounded-lg px-3 py-2 bg-white" />
        <select value={niche?.key || ''} onChange={e => setSelectedEntityKey(e.target.value)} disabled={!selectionOptions.length} className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 bg-white disabled:bg-gray-50">
          {campaignGroups.map(group => {
            const query = search.trim().toLowerCase();
            const matchingAdsets = group.adsets.filter(item => !query || item.label.toLowerCase().includes(query));
            const campaignMatches = !query || group.campaign?.label.toLowerCase().includes(query);
            if (!group.campaign) return matchingAdsets.map(item => <option key={item.key} value={item.key}>{item.label} · timing group</option>);
            if (!campaignMatches && !matchingAdsets.length) return null;
            return <optgroup key={group.campaign.key} label="Campaign">
              {campaignMatches && <option value={group.campaign.key}>{group.campaign.label} · Campaign total · ${Math.round(group.campaign.totalSpend).toLocaleString()} spend</option>}
              {matchingAdsets.map(item => <option key={item.key} value={item.key}>↳ Ad set · {item.label} · ${Math.round(item.totalSpend).toLocaleString()} spend</option>)}
            </optgroup>;
          })}
        </select>
        <p className="mt-1 text-[11px] text-gray-500">Campaign total combines its ad sets. Choose an indented ad set for its own timing view.</p>
      </div>

      {!niche && <p className="text-sm text-gray-400 py-6 text-center">No hourly data returned for this account and period.</p>}
      {niche && recommendation && (() => {
        const isRun = recommendation.status === 'run';
        // A "high" confidence Run is the only case that should read as a
        // settled recommendation. Medium/low still surface the same windows
        // (Joel asked to see them) but the framing must not imply Meta-ready
        // certainty it doesn't have — a Medium/Low "Run" got copied into
        // Ads Manager dayparting in review as if it were High (Joel-perspective P0).
        const confident = isRun && recommendation.confidence === 'high';
        const hasRunWindows = recommendation.run_windows?.length > 0;
        const hasAvoidWindows = recommendation.avoid_windows?.length > 0;
        const avoidSummary = hasAvoidWindows ? scheduleLine(recommendation.avoid_windows) : 'No repeatable avoid window yet';
        return <section className={`rounded-xl p-4 ${confident ? 'border-2 border-green-200 bg-green-50/60' : recommendation.status === 'none' ? 'border border-amber-200 bg-amber-50/60' : 'border border-gray-200 bg-gray-50'}`}>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="text-[10px] font-bold uppercase tracking-wider text-gray-500">{confident ? 'Recommended Meta Schedule' : isRun ? 'Directional Schedule — Not Yet Confident' : 'Meta Schedule'}</p>
            <h4 className={`mt-1 font-bold text-gray-900 ${confident ? 'text-lg' : 'text-base'}`}>{isRun ? recommendation.label : recommendation.status === 'none' ? 'No repeatable schedule yet' : 'Timing recommendation unavailable'}</h4>
          </div>
          <span className={`rounded-full px-2.5 py-1 text-[11px] font-bold uppercase ${confidenceStyle[recommendation.confidence] || confidenceStyle.low}`}>{recommendation.confidence || 'low'} confidence</span>
        </div>
        {allocated && isRun && <p className="mt-2 text-[11px] font-semibold text-amber-800">Directional: RedTrack-shaped timing on allocated Everflow billing — treat as a scheduling test, not confirmed exact attribution.</p>}
        {!confident && isRun && <p className="mt-2 text-[11px] text-gray-500">{recommendation.confidence === 'medium' ? 'Medium' : 'Low'} confidence — do not apply this schedule in Meta yet; keep watching for more evidence.</p>}
        {(hasRunWindows || isRun || recommendation.status === 'none') && <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2">{hasRunWindows && <div className="rounded-lg bg-white/80 p-3"><p className="text-[10px] font-bold uppercase text-green-700">Test first</p><p className="mt-1 text-sm font-semibold text-gray-900">{scheduleLine(recommendation.run_windows)}</p></div>}{(isRun || recommendation.status === 'none') && <div className="rounded-lg bg-white/80 p-3"><p className="text-[10px] font-bold uppercase text-red-700">When to avoid</p><p className={`mt-1 text-sm font-semibold ${hasAvoidWindows ? 'text-gray-900' : 'text-gray-600'}`}>{avoidSummary}</p>{!hasAvoidWindows && <p className="mt-1 text-[10px] leading-snug text-gray-500">Negative ROI blocks exist, but none has enough repeatable evidence to change the schedule.</p>}</div>}</div>}
        {watchBlocks.length > 0 && <p className="mt-3 text-[11px] leading-snug text-amber-800"><span className="font-semibold">Also watch:</span> {watchBlocks.map(block => `${block.label} (${block.roi >= 0 ? '+' : ''}${Math.round(block.roi * 100)}% ROI)`).join(' · ')} — profitable overall, but not repeatable enough to schedule yet.</p>}
        {recommendation.profit != null && <p className="mt-3 text-xs font-medium text-gray-700">{allocated ? '≈' : ''}{formatMoney(recommendation.profit)} profit · {recommendation.roi != null ? `${recommendation.roi >= 0 ? '+' : ''}${Math.round(recommendation.roi * 100)}% ROI` : 'ROI unavailable'} · {recommendation.positive_bucket_count || 0} of {recommendation.evidence_bucket_count || 0} evidence buckets positive</p>}
        <p className="mt-2 text-xs leading-relaxed text-gray-600">{recommendation.reason}</p>
        {niche.level === 'Ad set' && <p className="mt-2 text-[11px] text-gray-500">Ad-set view is investigative; a well-supported campaign schedule should take priority.</p>}
      </section>;
      })()}

      {attributionIncomplete && <div role="alert" className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-3 text-xs text-amber-900"><span className="font-semibold">Timing recommendation unavailable.</span> {data.attribution_warning || 'Some revenue is not tied to a Meta ad set.'} Keep current schedules unchanged.</div>}
      {niche && untracked && <div role="alert" className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-3 text-xs text-amber-900"><span className="font-semibold">Revenue tracking unavailable.</span> Spend and leads are available, but timing cannot be ranked until this account has an exact offer mapping.</div>}

      {niche && !untracked && !attributionIncomplete && <div className="rounded-lg border border-gray-200 bg-white">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-gray-100 px-3 py-3"><div><h4 className="text-sm font-semibold text-gray-900">Timing by 2-hour block</h4><p className="mt-0.5 text-[11px] text-gray-500">Profitability is pooled by weekday group; recommendations require repeatable evidence.</p></div><div className="flex items-center gap-2 text-[10px] text-gray-500" aria-label="ROI color legend"><span className="rounded bg-green-100 px-1.5 py-0.5 text-green-800">Positive ROI</span><span className="rounded bg-red-100 px-1.5 py-0.5 text-red-800">Negative ROI</span></div></div>
        {groups.map(group => <div key={group} className="border-b border-gray-100 last:border-b-0"><div className="flex items-center justify-between bg-gray-50 px-3 py-2"><span className="text-xs font-semibold text-gray-800">{group}</span><span className="text-[11px] text-gray-500">PT</span></div><div className="grid grid-cols-1 gap-px bg-gray-200 sm:grid-cols-2 xl:grid-cols-3">{timingBlocks.filter(block => block.group === group).map(block => <div key={block.key} style={roiHeatStyle(block)} title={block.roi != null ? `${Math.round(block.roi * 100)}% ROI` : 'ROI unavailable'} className={`bg-white p-3 ${block.status === 'run' ? 'border-l-2 border-l-green-400' : block.status === 'avoid' ? 'border-l-2 border-l-red-400' : block.status === 'inconsistent' ? 'border-l-2 border-l-amber-300' : ''}`}><div className="flex items-center justify-between gap-2"><span className="text-sm font-semibold text-gray-900">{block.label}</span><span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${confidenceStyle[block.confidence] || confidenceStyle.low}`}>{block.confidence}</span></div><p className={`mt-1 text-xs font-semibold ${block.status === 'run' ? 'text-green-700' : block.status === 'avoid' ? 'text-red-700' : block.status === 'inconsistent' ? 'text-amber-700' : 'text-gray-500'}`}>{allocated && (block.status === 'run' || block.status === 'avoid') ? 'Directional test' : block.status === 'unavailable' ? 'Insufficient evidence' : block.status}</p>{block.revenue != null && <p className="mt-1 text-[11px] text-gray-600">{formatMoney(block.revenue)} revenue · {formatMoney(block.spend)} spend · <span className={block.profit >= 0 ? 'text-green-700' : 'text-red-700'}>{block.profit >= 0 ? '+' : ''}{formatMoney(block.profit)} profit</span> · {block.roi != null ? `${block.roi >= 0 ? '+' : ''}${Math.round(block.roi * 100)}% ROI` : '—'}</p>}<p className="mt-1 text-[10px] leading-snug text-gray-500">{block.reason} {block.evidence_bucket_count ? `(${block.positive_bucket_count}/${block.evidence_bucket_count} positive buckets)` : ''}</p></div>)}</div></div>)}
      </div>}

      {niche && <details open={expandedContext} onToggle={event => setExpandedContext(event.currentTarget.open)} className="rounded-lg border border-amber-200 bg-amber-50"><summary className="flex cursor-pointer list-none items-center justify-between px-3 py-2 text-xs font-semibold text-amber-900"><span>Timing context & coverage</span><ChevronDown size={14} /></summary><div className="border-t border-amber-200 px-3 py-3 text-[11px] leading-relaxed text-amber-900"><p>{allocated ? 'Directional: Everflow billing is allocated using RedTrack timing. Treat Run or Avoid as a controlled scheduling test.' : 'Timing is based on matched Everflow ad-set revenue.'}</p>{data.attribution_warning && <p className="mt-1"><span className="font-semibold">Coverage:</span> {data.attribution_warning}</p>}{(data.dropped_conversion_count || data.dropped_revenue) ? <p className="mt-1">{data.dropped_conversion_count || 0} attribution records · {formatMoney(data.dropped_revenue || 0)} unmatched value.</p> : null}</div></details>}
      {niche && <p className="text-[11px] text-gray-500">Sampling: {data.preset_label || 'Selected period'} · {data.date_from}–{data.date_to} · {data.timezone || 'PT'}.</p>}
    </div>
  );
}

function CreativeCompass({ buckets, onOpenAdset, dateRangeLabel }) {
  return (
    <section className="bg-white rounded-xl border border-indigo-100 border-l-4 border-l-indigo-500 shadow-sm overflow-hidden">
      <div className="px-5 py-4 border-b border-indigo-100 bg-indigo-50/35">
        <h2 className="font-semibold text-gray-900 flex items-center gap-2"><Target size={16} className="text-indigo-600" /> Creative Compass</h2>
        <p className="text-xs text-gray-500 mt-1">Rule-based starting points from the ad-set metrics already loaded below · {dateRangeLabel} · grain: ad sets. Nothing here is an opaque score.</p>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-5 divide-y sm:divide-y-0 sm:divide-x divide-gray-100">
        {buckets.map(bucket => (
          <div key={bucket.key} className="p-4 min-w-0">
            <div className="flex items-center justify-between gap-2 mb-1">
              <h3 className={`text-sm font-semibold ${bucket.color}`}>{bucket.label}</h3>
              <span className="text-lg font-bold text-gray-900">{bucket.items.length}</span>
            </div>
            <p className="text-[11px] leading-snug text-gray-500 min-h-[32px]">{bucket.rule}</p>
            {bucket.items.length === 0 ? (
              <p className="text-xs text-gray-400 mt-3">{bucket.empty || 'Nothing here right now'}</p>
            ) : (
              <div className="mt-3 space-y-2">
                {bucket.items.slice(0, 3).map(item => (
                  <button key={item.id} type="button" onClick={() => onOpenAdset(item.adset)} className="block w-full text-left rounded-lg border border-gray-100 px-2.5 py-2 hover:border-indigo-200 hover:bg-indigo-50/40 transition-colors">
                    <span className="block text-xs font-medium text-gray-800 truncate">{item.adset.name}</span>
                    <span className="block text-[11px] text-gray-500 truncate">{item.detail}</span>
                  </button>
                ))}
                {bucket.items.length > 3 && <p className="text-[11px] text-gray-400">+{bucket.items.length - 3} more below</p>}
              </div>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}

function GeographyWatchlist({ data, loading, error, onRefresh }) {
  const [expandedCampaignId, setExpandedCampaignId] = useState(null);
  if (loading && !data) return <div className="h-48 rounded-xl bg-gray-50 animate-pulse" />;
  if (error) return <div role="alert" className="rounded-xl border border-red-200 bg-red-50 px-4 py-4 text-sm text-red-700"><p className="font-semibold">Geography diagnostics unavailable</p><p className="mt-1">{error}</p><button type="button" onClick={onRefresh} className="mt-3 rounded-lg bg-white px-3 py-1.5 text-xs font-semibold text-red-700 ring-1 ring-red-200 hover:bg-red-100">Retry</button></div>;
  if (!data) return null;
  const platformMode = data.source_mode === 'platform';
  if (!data.campaigns?.length) return <div className="rounded-xl border border-gray-200 bg-gray-50 px-4 py-8 text-center"><p className="text-sm font-semibold text-gray-700">{platformMode ? 'No matched state conversion data' : 'No state delivery signals need review'}</p><p className="mt-1 text-xs text-gray-500">{platformMode ? 'RedTrack/Everflow returned no geo rows that matched a Meta ad set in this period.' : 'A signal needs $50+ spend, 2+ leads, and a CPL at least 1.5× its campaign’s blended CPL.'}</p></div>;
  return <div className="space-y-3">
    <div className="rounded-xl border border-violet-100 bg-violet-50 px-4 py-3 text-xs text-violet-900"><span className="font-semibold">{data.flagged_state_count} state{data.flagged_state_count !== 1 ? 's' : ''} across {data.flagged_campaign_count} campaign{data.flagged_campaign_count !== 1 ? 's' : ''} matched.</span> {platformMode ? (data.source_rows?.meta_spend ? "Spend is Meta's own per-state delivery data. Revenue is RedTrack/Everflow — Meta doesn't see post-click conversions. ROAS divides that revenue by Meta's spend." : "Meta's spend data didn't load this time (revenue below is still real) — Refresh to retry.") : 'These are CPL signals from Meta, not state-level revenue or an instruction to exclude anyone.'}</div>
    {data.campaigns.map(campaign => {
      const expanded = expandedCampaignId === campaign.campaign_id;
      const statesLabel = campaign.flagged_states.map(state => state.state).join(', ');
      return <section key={campaign.campaign_id} className="rounded-xl border border-gray-200 bg-white overflow-hidden">
        <div className="flex flex-wrap items-start justify-between gap-3 px-4 py-4"><div className="min-w-0"><p className="font-semibold text-sm text-gray-900 break-words">{campaign.campaign_name || campaign.campaign_id}</p><p className="mt-1 text-xs text-gray-500">{platformMode ? `${campaign.total_conversions.toLocaleString()} conversions · ${formatMoney(campaign.total_revenue)} revenue · ${formatMoney(campaign.total_spend)} spend · ${campaign.total_roas != null ? `${campaign.total_roas.toFixed(2)}x ROAS` : 'ROAS —'}` : `Campaign CPL ${formatMoney(campaign.blended_cpl)} · ${formatMoney(campaign.total_spend)} spend · ${campaign.total_leads.toLocaleString()} leads`}</p>{!platformMode && <p className="mt-2 text-xs text-red-700"><span className="font-semibold">Review:</span> {statesLabel}</p>}</div><button type="button" onClick={() => setExpandedCampaignId(expanded ? null : campaign.campaign_id)} className="shrink-0 inline-flex items-center gap-1.5 rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-xs font-semibold text-gray-700 hover:border-violet-300 hover:bg-violet-50 hover:text-violet-700" aria-expanded={expanded}>{expanded ? 'Hide states' : 'Inspect states'} <ChevronDown size={14} className={expanded ? 'rotate-180' : ''} /></button></div>
        {expanded && <div className="border-t border-gray-100 px-4 py-3"><p className="mb-2 text-[11px] text-gray-500">{platformMode ? "Spend is Meta's own account-wide region breakdown — real per-state delivery cost, not an estimate. Revenue uses Everflow when matched, otherwise RedTrack; Meta doesn't see revenue at all. State ROAS is revenue ÷ spend. Ad-set rows below break out revenue only — Meta's spend breakdown doesn't go deeper than campaign × state." : 'Compare delivery first, then make any targeting change in Meta deliberately. “Estimated excess” is only the CPL gap versus this campaign’s blended CPL—not profit.'}</p><div className="overflow-x-auto rounded-lg border border-gray-100"><table className="w-full min-w-[700px] text-xs"><thead className="bg-gray-50 text-gray-500"><tr><th className="px-3 py-2 text-left font-medium">State / ad set</th>{platformMode ? <><th className="px-3 py-2 text-right font-medium">Spend</th><th className="px-3 py-2 text-right font-medium">Conversions</th><th className="px-3 py-2 text-right font-medium">Revenue</th><th className="px-3 py-2 text-right font-medium">ROAS (Rev ÷ Spend)</th></> : <><th className="px-3 py-2 text-right font-medium">Spend</th><th className="px-3 py-2 text-right font-medium">Leads</th><th className="px-3 py-2 text-right font-medium">CPL</th><th className="px-3 py-2 text-right font-medium">Estimated excess</th><th className="px-3 py-2 text-right font-medium">Status</th></>}</tr></thead><tbody>{campaign.states.flatMap(state => {
          const stateRoas = state.roas ?? (Number(state.spend) > 0 ? Number(state.revenue || 0) / Number(state.spend) : null);
          if (!platformMode) return [<tr key={state.state} className={`border-t border-gray-100 ${state.is_dragging ? 'bg-red-50/60' : ''}`}><td className="px-3 py-2 font-medium text-gray-800">{state.state}</td><td className="px-3 py-2 text-right text-gray-700">{formatMoney(state.spend)}</td><td className="px-3 py-2 text-right text-gray-700">{state.leads}</td><td className={`px-3 py-2 text-right font-semibold ${state.is_dragging ? 'text-red-700' : 'text-gray-800'}`}>{formatMoney(state.cpl)}</td><td className="px-3 py-2 text-right text-gray-700">{state.is_dragging ? formatMoney(state.excess_cost) : '—'}</td><td className="px-3 py-2 text-right">{state.is_dragging ? <span className="rounded-full bg-red-100 px-2 py-0.5 font-semibold text-red-700">Review targeting</span> : <span className="text-gray-400">No signal</span>}</td></tr>];
          return [<tr key={`${state.state}-summary`} className="border-t border-gray-100 bg-violet-50/40"><td className="px-3 py-2 font-semibold text-gray-800">{state.state} <span className="font-normal text-gray-500">({state.adset_count} ad set{state.adset_count !== 1 ? 's' : ''})</span></td><td className="px-3 py-2 text-right font-semibold text-gray-800">{formatMoney(state.spend)}</td><td className="px-3 py-2 text-right text-gray-700">{state.conversions}</td><td className="px-3 py-2 text-right font-semibold text-gray-800">{formatMoney(state.revenue)}</td><td className={`px-3 py-2 text-right text-base font-bold ${stateRoas != null && stateRoas < 1 ? 'text-red-700' : 'text-emerald-700'}`}>{stateRoas != null ? `${Number(stateRoas).toFixed(2)}x` : '—'}</td></tr>, ...(state.adsets || []).map(adset => <tr key={`${state.state}-${adset.adset_id}`} className="border-t border-gray-100"><td className="px-3 py-2 pl-7 text-gray-600">↳ {adset.adset_name}</td><td className="px-3 py-2 text-right text-gray-400">—</td><td className="px-3 py-2 text-right text-gray-700">{adset.conversions}</td><td className="px-3 py-2 text-right text-gray-700">{formatMoney(adset.revenue)}</td><td className="px-3 py-2 text-right text-gray-400">—</td></tr>)];
        })}</tbody></table></div></div>}
      </section>;
    })}
  </div>;
}

function CampaignIntelligencePanel({ adAccountId, pageDatePreset, pageDateFrom, pageDateTo, initialOpen = false, initialPreset = null }) {
  const resolvedInitialPreset = resolveIntelligencePreset(pageDatePreset, initialPreset);
  const [open, setOpen] = useState(initialOpen);
  const [preset, setPreset] = useState(resolvedInitialPreset);
  const [customFrom, setCustomFrom] = useState(resolvedInitialPreset === 'custom' ? (pageDateFrom || '') : '');
  const [customTo, setCustomTo] = useState(resolvedInitialPreset === 'custom' ? (pageDateTo || '') : '');
  const [data, setData] = useState(null);
  const [intelligenceView, setIntelligenceView] = useState('niche');
  const [bestTimesData, setBestTimesData] = useState(null);
  const [bestTimesLoading, setBestTimesLoading] = useState(false);
  const [bestTimesError, setBestTimesError] = useState(null);
  const [geographyData, setGeographyData] = useState(null);
  const [geographyLoading, setGeographyLoading] = useState(false);
  const [geographyError, setGeographyError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const loadedPresetRef = useRef(null);
  const userSelectedPresetRef = useRef(false);
  const intelligenceRequestRef = useRef(0);
  const bestTimesRequestRef = useRef(0);
  const geographyRequestRef = useRef(0);

  const actionCounts = data?.action_queue?.counts || {};
  const findingCount = (actionCounts.scale || 0) + (actionCounts.cut_or_pause || 0) + (actionCounts.tracking_check || 0);
  const hasFindings = findingCount > 0 || data?.tracking_warning?.has_warning;
  const findingBadge = findingCount > 9 ? '9+' : findingCount;

  const loadIntelligence = useCallback(async (nextPreset = preset, nextFrom = customFrom, nextTo = customTo) => {
    const requestId = ++intelligenceRequestRef.current;
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
      if (requestId === intelligenceRequestRef.current) {
        loadedPresetRef.current = nextPreset === 'custom' ? `custom:${nextFrom}:${nextTo}` : nextPreset;
        setData(result);
      }
    } catch (e) {
      if (requestId === intelligenceRequestRef.current) {
        setError(e.message || 'Failed to load intelligence data');
        // This fetch now also fires in the background while the panel is
        // closed (findings badge prefetch) — without this log a failure
        // here (e.g. a Meta rate limit) would be completely invisible,
        // since setError only renders inside the open panel body.
        console.error('Campaign Intelligence fetch failed:', e);
      }
    } finally {
      if (requestId === intelligenceRequestRef.current) setLoading(false);
    }
  }, [adAccountId, preset, customFrom, customTo]);

  const loadGeography = useCallback(async (nextPreset = preset, nextFrom = customFrom, nextTo = customTo, refresh = false) => {
    const requestId = ++geographyRequestRef.current;
    setGeographyLoading(true);
    setGeographyError(null);
    try {
      const params = new URLSearchParams({ preset: nextPreset });
      if (adAccountId) params.set('ad_account_id', adAccountId);
      if (nextPreset === 'custom') {
        params.set('date_from', nextFrom);
        params.set('date_to', nextTo);
      }
      if (refresh) params.set('refresh', 'true');
      const res = await authFetch(`${API_BASE}/intelligence/geography-watchlist?${params}`);
      if (!res.ok) {
        const e = await res.json().catch(() => ({}));
        throw new Error(e.detail || `Error ${res.status}`);
      }
      const result = await res.json();
      if (requestId === geographyRequestRef.current) setGeographyData(result);
    } catch (e) {
      if (requestId === geographyRequestRef.current) setGeographyError(e.message || 'Failed to load geography diagnostics');
    } finally {
      if (requestId === geographyRequestRef.current) setGeographyLoading(false);
    }
  }, [adAccountId, preset, customFrom, customTo]);

  const loadBestTimes = useCallback(async (nextPreset = preset, nextFrom = customFrom, nextTo = customTo, forceRefresh = false) => {
    const requestId = ++bestTimesRequestRef.current;
    setBestTimesLoading(true);
    setBestTimesError(null);
    try {
      const params = new URLSearchParams({ preset: nextPreset });
      if (adAccountId) params.set('ad_account_id', adAccountId);
      if (forceRefresh) params.set('refresh', 'true');
      if (nextPreset === 'custom' && nextFrom && nextTo) {
        params.set('date_from', nextFrom);
        params.set('date_to', nextTo);
      }
      const res = await authFetch(`${API_BASE}/intelligence/best-times?${params}`);
      if (!res.ok) {
        const e = await res.json().catch(() => ({}));
        throw new Error(e.detail || `Error ${res.status}`);
      }
      const result = await res.json();
      if (requestId === bestTimesRequestRef.current) setBestTimesData(result);
    } catch (e) {
      if (requestId === bestTimesRequestRef.current) setBestTimesError(e.message || 'Failed to load Best Times data');
    } finally {
      if (requestId === bestTimesRequestRef.current) setBestTimesLoading(false);
    }
  }, [adAccountId, preset, customFrom, customTo]);

  const toggleOpen = useCallback(() => {
    setOpen(current => {
      const next = !current;
      if (next && loadedPresetRef.current !== preset && !loading) {
        loadIntelligence(preset, customFrom, customTo);
      }
      if (next && intelligenceView === 'best-times' && !bestTimesData) {
        loadBestTimes(preset, customFrom, customTo);
      }
      if (next && intelligenceView === 'geography' && !geographyData) {
        loadGeography(preset, customFrom, customTo);
      }
      return next;
    });
  }, [preset, customFrom, customTo, intelligenceView, bestTimesData, geographyData, loading, loadIntelligence, loadBestTimes, loadGeography]);

  useEffect(() => {
    if (!initialOpen) return;
    setOpen(true);
  }, [initialOpen]);

  useEffect(() => {
    intelligenceRequestRef.current += 1;
    bestTimesRequestRef.current += 1;
    geographyRequestRef.current += 1;
    loadedPresetRef.current = null;
    setData(null);
    setError(null);
    setBestTimesData(null);
    setBestTimesError(null);
    setBestTimesLoading(false);
    setGeographyData(null);
    setGeographyError(null);
    setGeographyLoading(false);
    if (open) {
      loadIntelligence(preset, customFrom, customTo);
      if (intelligenceView === 'best-times') loadBestTimes(preset, customFrom, customTo);
      if (intelligenceView === 'geography') loadGeography(preset, customFrom, customTo);
    } else if (!userSelectedPresetRef.current) {
      const nextPreset = resolveIntelligencePreset(pageDatePreset, initialPreset);
      const nextFrom = nextPreset === 'custom' ? (pageDateFrom || '') : '';
      const nextTo = nextPreset === 'custom' ? (pageDateTo || '') : '';
      loadIntelligence(nextPreset, nextFrom, nextTo);
    }
  }, [adAccountId, pageDatePreset, pageDateFrom, pageDateTo]); // eslint-disable-line react-hooks/exhaustive-deps

  // Single source of truth for syncing Intelligence's preset to the page's own
  // date range. Always respects an explicit manual pick (userSelectedPresetRef),
  // whether the sync was triggered by a deep link or by the page's own date
  // dropdown changing — and always reloads when it's visible (or about to
  // become visible via a deep link) so the displayed data never goes stale
  // against the preset pill. Two separate effects with inconsistent guards
  // previously let a manual pick get silently overridden, and let the pill
  // update without the underlying data refreshing.
  useEffect(() => {
    if (userSelectedPresetRef.current) return;
    const nextPreset = resolveIntelligencePreset(pageDatePreset, initialPreset);
    const nextFrom = nextPreset === 'custom' ? (customFrom || pageDateFrom || '') : '';
    const nextTo = nextPreset === 'custom' ? (customTo || pageDateTo || '') : '';
    setPreset(nextPreset);
    if (nextPreset === 'custom') {
      setCustomFrom(nextFrom);
      setCustomTo(nextTo);
    }
    const key = nextPreset === 'custom' ? `custom:${nextFrom}:${nextTo}` : nextPreset;
    if ((open || initialOpen) && loadedPresetRef.current !== key) {
      loadIntelligence(nextPreset, nextFrom, nextTo);
      if (intelligenceView === 'best-times') loadBestTimes(nextPreset, nextFrom, nextTo);
      if (intelligenceView === 'geography') loadGeography(nextPreset, nextFrom, nextTo);
    }
  }, [pageDatePreset, pageDateFrom, pageDateTo, initialPreset, open, initialOpen]); // eslint-disable-line react-hooks/exhaustive-deps

  const handlePreset = (nextPreset) => {
    userSelectedPresetRef.current = true;
    setPreset(nextPreset);
    if (nextPreset === 'custom') {
      setCustomFrom('');
      setCustomTo('');
      setData(null);
      setError(null);
      intelligenceRequestRef.current += 1;
      bestTimesRequestRef.current += 1;
      geographyRequestRef.current += 1;
      setLoading(false);
      setBestTimesLoading(false);
      setBestTimesData(null);
      setBestTimesError(null);
      setGeographyData(null);
      setGeographyError(null);
      setGeographyLoading(false);
      setBestTimesLoading(false);
      return;
    }
    if (open) loadIntelligence(nextPreset, '', '');
    // Keep Best Times in sync with the preset even while the niche tab is
    // active — otherwise switching back to Best Times later shows data for
    // the previous preset with no visual indication it's stale.
    if (open && intelligenceView === 'best-times') loadBestTimes(nextPreset, '', '');
    else {
      bestTimesRequestRef.current += 1;
      setBestTimesData(null);
      setBestTimesError(null);
      setBestTimesLoading(false);
    }
    if (open && intelligenceView === 'geography') loadGeography(nextPreset, '', '');
    else {
      geographyRequestRef.current += 1;
      setGeographyData(null);
      setGeographyError(null);
      setGeographyLoading(false);
    }
  };

  // Best Times owns its own date window (it defaults to 30 days for a
  // meaningful hourly sample). Do not keep showing the niche view's old
  // seven-day label above an already-loaded timing result.
  const panelData = (intelligenceView === 'best-times' && bestTimesData) || (intelligenceView === 'geography' && geographyData) || data || {
    preset_label: preset,
    date_from: customFrom || '—',
    date_to: customTo || '—',
    day_filter: 'all',
    summary: '',
    action_queue: null,
    tracking_warning: null,
    rows: [],
  };

  return (
    <>
      <button type="button" onClick={toggleOpen} className={`inline-flex items-center gap-2 px-3 py-2 rounded-lg border text-xs font-semibold transition-colors ${hasFindings ? 'border-amber-300 bg-amber-50 text-amber-800 hover:bg-amber-100' : 'border-violet-200 bg-violet-50 text-violet-700 hover:bg-violet-100'}`} title={hasFindings ? `${findingBadge} intelligence finding${findingCount === 1 ? '' : 's'} to review` : 'Review campaign intelligence'}>
        <Sparkles size={14} /> Campaign Intelligence
        {hasFindings && <span className="inline-flex min-w-5 items-center justify-center rounded-full bg-amber-500 px-1.5 py-0.5 text-[10px] font-bold leading-none text-white">{findingBadge}</span>}
      </button>

      {open && (
        // z-40, one below the Remix drawer's z-50 — if both are ever open at once,
        // stacking is deterministic instead of relying on DOM insertion order.
        <div className="fixed inset-0 z-40 flex justify-end pointer-events-none">
          {/* Backdrop */}
          <div className="absolute inset-0 bg-black/30 pointer-events-auto" onClick={toggleOpen} />
          {/* Drawer */}
          <div className="relative w-full max-w-3xl bg-white shadow-2xl pointer-events-auto flex flex-col h-full overflow-y-auto">
            <div className="px-6 py-4 flex items-center justify-between bg-violet-50/40 border-b border-violet-100">
              <h2 className="font-semibold text-gray-900 flex items-center gap-2">
                <Sparkles size={16} className="text-violet-500" />
                Campaign Intelligence
                <span className="text-xs font-normal text-gray-400">{intelligenceView === 'best-times' ? 'hourly timing by niche' : intelligenceView === 'geography' ? 'state delivery diagnostics by campaign' : 'Action queue · tracking checks · niche decisions'}</span>
              </h2>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => { if (intelligenceView === 'geography') loadGeography(preset, customFrom, customTo, true); else { loadIntelligence(preset, customFrom, customTo); if (intelligenceView === 'best-times' && (preset !== 'custom' || (customFrom && customTo))) loadBestTimes(preset, customFrom, customTo, true); } }}
                  disabled={loading || bestTimesLoading || geographyLoading || (preset === 'custom' && (!customFrom || !customTo))}
                  className="p-1.5 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors disabled:opacity-40"
                  title="Refresh intelligence"
                >
                  <RefreshCw size={14} className={(loading || bestTimesLoading || geographyLoading) ? 'animate-spin' : ''} />
                </button>
                <button onClick={toggleOpen} className="text-gray-400 hover:text-gray-600 p-1">
                  <X size={18} />
                </button>
              </div>
            </div>

            <div className="px-6 py-5">
          <div className="flex flex-wrap gap-1.5 mb-4">
            {INTELLIGENCE_PRESETS.map(p => (
              <button
                key={p.value}
                onClick={() => handlePreset(p.value)}
                title={intelligenceView === 'geography' && (p.value === 'weekdays_mtd' || p.value === 'weekends_mtd')
                  ? 'Capped to a rolling window (not full month-to-date) — a month-wide, per-day, per-state Meta query is too large to complete reliably. Best Times and Niche use true MTD.'
                  : undefined}
                className={`px-3 py-1 rounded-full text-xs font-medium transition-colors ${
                  preset === p.value
                    ? 'bg-violet-100 text-violet-700 border border-violet-200'
                    : 'bg-gray-100 text-gray-600 border border-transparent hover:bg-gray-200'
                }`}
              >
                {intelligencePresetLabel(p, intelligenceView, geographyData)}
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
                onClick={() => {
                  loadIntelligence('custom', customFrom, customTo);
                  if (intelligenceView === 'best-times') loadBestTimes('custom', customFrom, customTo);
                  else {
                    bestTimesRequestRef.current += 1;
                    setBestTimesData(null);
                    setBestTimesError(null);
                    setBestTimesLoading(false);
                  }
                  if (intelligenceView === 'geography') loadGeography('custom', customFrom, customTo);
                  else {
                    geographyRequestRef.current += 1;
                    setGeographyData(null);
                    setGeographyError(null);
                    setGeographyLoading(false);
                  }
                }}
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

          {!loading && error && intelligenceView === 'niche' && (
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

          {/* Best Times intentionally clears the niche payload while it fetches
              its 30-day sample. Keep its own loading/error surface mounted
              during that request instead of replacing the panel with a blank
              empty state. */}
          {!loading && (data || intelligenceView === 'best-times' || intelligenceView === 'geography' || bestTimesData || bestTimesError || geographyData || geographyError) && ( !error || intelligenceView !== 'niche') && (
            <>
              <div className="bg-violet-50 border border-violet-100 rounded-xl p-4 mb-4 flex gap-3">
                <Sparkles size={16} className="text-violet-500 flex-shrink-0 mt-0.5" />
                <div className="min-w-0">
                  <p className="text-xs font-semibold text-violet-800 mb-1">
                    {panelData.preset_label}
                    <span className="ml-2 font-normal text-violet-500">· {formatDateShort(panelData.date_from)}–{formatDateShort(panelData.date_to)}{intelligenceView === 'best-times' ? ` · ${panelData.timezone || 'PT'}` : intelligenceView === 'geography' ? ' · grain: campaign × state' : ' · grain: niches'}</span>
                    {panelData.day_filter !== 'all' && (
                      <span className="ml-2 font-normal text-violet-500">· {panelData.day_filter} days only</span>
                    )}
                  </p>
                  <div className="text-violet-900">
                    {intelligenceView === 'niche' && panelData.action_queue ? (
                      (() => {
                        const LANES = [
                          { key: 'scale', label: 'Scale', dot: 'bg-green-500', pill: 'bg-green-100 text-green-800' },
                          { key: 'cut_or_pause', label: 'Cut / Pause', dot: 'bg-red-500', pill: 'bg-red-100 text-red-800' },
                          { key: 'watch', label: 'Watch', dot: 'bg-amber-500', pill: 'bg-amber-100 text-amber-800' },
                          { key: 'tracking_check', label: 'Tracking', dot: 'bg-yellow-500', pill: 'bg-yellow-100 text-yellow-800' },
                        ];
                        const counts = panelData.action_queue.counts || {};
                        const topLane = LANES.find(lane => panelData.action_queue[lane.key]?.length);
                        const topItem = topLane ? panelData.action_queue[topLane.key][0] : null;
                        return (
                          <>
                            {topItem && (
                              <p className="text-sm font-semibold leading-relaxed">
                                <span className="text-violet-500 font-normal">Start here → </span>
                                {topItem.niche}
                                {topItem.action_label ? <span className="text-violet-700"> · {topItem.action_label}</span> : null}
                              </p>
                            )}
                            <div className="mt-2 flex flex-wrap gap-1.5">
                              {LANES.map(lane => {
                                const count = counts[lane.key] ?? panelData.action_queue[lane.key]?.length ?? 0;
                                if (!count) return null;
                                return (
                                  <span key={lane.key} className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold ${lane.pill}`}>
                                    <span className={`h-1.5 w-1.5 rounded-full ${lane.dot}`} />
                                    {count} {lane.label}
                                  </span>
                                );
                              })}
                            </div>
                          </>
                        );
                      })()
                    ) : (
                      <p className="text-sm font-semibold leading-relaxed">{intelligenceView === 'best-times' ? 'When should I run this campaign? Review the recommended Meta schedule below.' : intelligenceView === 'geography' ? 'Where is delivery dragging? Start with the few campaign-state signals that clear the evidence threshold.' : panelData.summary}</p>
                    )}
                  </div>
                </div>
              </div>

              <div className="flex gap-1 p-1 mb-4 rounded-lg bg-gray-100 w-fit">
                <button type="button" onClick={() => setIntelligenceView('niche')} className={`px-3 py-1.5 rounded-md text-xs font-semibold ${intelligenceView === 'niche' ? 'bg-white text-violet-700 shadow-sm' : 'text-gray-500'}`}>Niche profitability</button>
                <button type="button" onClick={() => {
                  setIntelligenceView('best-times');
                  // Best Times follows the date range the buyer selected in
                  // Campaign Intelligence. Never silently widen Last 7d to
                  // Last 30d; a short window is still useful for a current
                  // scheduling check, even if it yields a lower-confidence result.
                  if (!bestTimesData && (preset !== 'custom' || (customFrom && customTo))) {
                    loadBestTimes(preset, customFrom, customTo);
                  }
                }} className={`px-3 py-1.5 rounded-md text-xs font-semibold ${intelligenceView === 'best-times' ? 'bg-white text-violet-700 shadow-sm' : 'text-gray-500'}`}>Best Times</button>
                <button type="button" onClick={() => {
                  setIntelligenceView('geography');
                  if (!geographyData && (preset !== 'custom' || (customFrom && customTo))) loadGeography(preset, customFrom, customTo);
                }} className={`px-3 py-1.5 rounded-md text-xs font-semibold ${intelligenceView === 'geography' ? 'bg-white text-violet-700 shadow-sm' : 'text-gray-500'}`}>Geography</button>
              </div>

              {intelligenceView === 'best-times' && (
                <div className="mb-5 rounded-xl border border-violet-100 bg-white p-3">
                  <div className="flex items-center justify-between mb-3"><div><h3 className="text-sm font-semibold text-gray-900">Best Times</h3><p className="text-[11px] text-gray-500 mt-0.5">{!bestTimesData ? 'Loading attribution…' : bestTimesData.attribution_complete === false ? 'Attribution incomplete · timing recommendations unavailable' : bestTimesData.attribution_method === 'everflow_adset_id_redtrack_unavailable' ? 'Exact Everflow ad-set attribution' : bestTimesData.attribution_allocated ? 'Directional revenue allocation · RedTrack shape + Everflow billing' : bestTimesData.niches?.some(item => item.revenue_source === 'not_tracked') ? 'Revenue unavailable · no Everflow offer mapping' : 'Exact Everflow ad-set attribution'} · {bestTimesData?.timezone || '—'}</p></div><button type="button" onClick={() => loadBestTimes(preset, customFrom, customTo, true)} disabled={bestTimesLoading || (preset === 'custom' && (!customFrom || !customTo))} className="text-xs text-violet-600 hover:text-violet-800 disabled:opacity-40">{bestTimesLoading ? 'Loading…' : 'Refresh'}</button></div>
                  {bestTimesLoading && !bestTimesData && <div className="h-48 rounded-lg bg-gray-50 animate-pulse" />}
                  {!bestTimesLoading && bestTimesError && <div role="alert" className="rounded-lg border border-red-200 bg-red-50 px-3 py-3 text-sm text-red-700"><div className="font-semibold">Timing recommendations unavailable</div><div className="mt-1">We couldn’t load the timing data for this account and period.</div><div className="mt-1 text-xs">Keep current budgets and schedules unchanged, then use Refresh to retry.</div></div>}
                  {!bestTimesError && bestTimesData && <BestTimesGrid data={bestTimesData} />}
                </div>
              )}

              {intelligenceView === 'geography' && (
                <div className="mb-5 rounded-xl border border-violet-100 bg-white p-3">
                  <div className="mb-3 flex flex-wrap items-center justify-between gap-2"><div><h3 className="text-sm font-semibold text-gray-900">Geography</h3><p className="mt-0.5 text-[11px] text-gray-500">Campaign × state · spend from Meta, revenue from RedTrack/Everflow.</p></div><button type="button" onClick={() => loadGeography(preset, customFrom, customTo, true)} disabled={geographyLoading || (preset === 'custom' && (!customFrom || !customTo))} className="text-xs text-violet-600 hover:text-violet-800 disabled:opacity-40">{geographyLoading ? 'Loading…' : 'Refresh'}</button></div>
                  <GeographyWatchlist data={geographyData} loading={geographyLoading} error={geographyError} onRefresh={() => loadGeography(preset, customFrom, customTo, true)} />
                </div>
              )}

              {panelData.action_queue && intelligenceView === 'niche' && (
                <div className="mb-4">
                  <div className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Action Queue</div>
                  <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-4">
                    {[
                      { key: 'scale', label: 'Scale', hdrBg: 'bg-green-50', border: 'border-green-200', text: 'text-green-800' },
                      { key: 'cut_or_pause', label: 'Cut / Pause', hdrBg: 'bg-red-50', border: 'border-red-200', text: 'text-red-800' },
                      { key: 'watch', label: 'Watch', hdrBg: 'bg-amber-50', border: 'border-amber-200', text: 'text-amber-800' },
                      { key: 'tracking_check', label: 'Tracking', hdrBg: 'bg-yellow-50', border: 'border-yellow-200', text: 'text-yellow-800' },
                    ].map(lane => {
                      const items = panelData.action_queue[lane.key];
                      if (!items?.length) return null;
                      return (
                        <div key={lane.key} className={`rounded-lg border ${lane.border} overflow-hidden bg-white ${lane.key === 'tracking_check' ? 'sm:col-span-2 md:col-span-3' : ''}`}>
                          <div className={`${lane.hdrBg} px-3 py-1.5 text-[10px] font-semibold uppercase tracking-wide ${lane.text}`}>
                            {lane.label}
                          </div>
                          <ul className="px-3 py-2 space-y-1">
                            {items.map(item => {
                              const niche = typeof item === 'string' ? item : item.niche;
                              const actionLabel = typeof item === 'string' ? '' : item.action_label;
                              const reason = typeof item === 'string' ? '' : item.reason;
                              return (
                              <li key={`${niche}-${actionLabel}`} className="min-w-0" title={reason || `${niche}${actionLabel ? ` (${actionLabel})` : ''}`}>
                                <div className="text-xs font-semibold text-gray-800 truncate">{niche}{actionLabel ? ` · ${actionLabel}` : ''}</div>
                                {reason && <div className="text-[11px] text-gray-500 truncate">{reason}</div>}
                              </li>
                              );
                            })}
                          </ul>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              {panelData.tracking_warning?.has_warning && intelligenceView === 'niche' && (
                <div className="mb-4 rounded-lg border border-yellow-200 bg-yellow-50 px-3 py-2 text-xs text-yellow-800">
                  {data.tracking_warning.message}
                </div>
              )}

              {/* Best Times has a different response shape (campaigns/adsets,
                  not niche-profitability rows). Check the active view first so
                  a successful timing response can never dereference rows. */}
              {intelligenceView === 'niche' && panelData.rows?.length > 0 && (
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
                  {panelData.rows.map(row => {
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

              {panelData.day_filter !== 'all' && intelligenceView === 'niche' && (
                <p className="text-xs text-gray-400 mt-2">
                  RedTrack revenue uses full date range (not day-filtered) — ROI is approximate.
                </p>
              )}
            </>
          )}

          {!loading && !error && !data && intelligenceView === 'niche' && (
            <p className="text-sm text-gray-400 text-center py-4">Open or select a preset to load intelligence.</p>
          )}
            </div>
          </div>
        </div>
      )}
    </>
  );
}

// ── Creative breakdown table (ad-level) ──────────────────────────────────────
// onRemix: ({ ad_id, ad_name, headline, body, cta_label, image_url, adsetName, campaign_id }) => void
function AdsBreakdown({ fbAdsetId, fbCampaignId, adsetName, campaignId, adAccountId, adsBulk, adsLoading, adsError, rtAdsBulk, onAdStatusChange, onRemix }) {
  const { showSuccess, showError } = useToast();
  const navigate = useNavigate();
  const [pausingAds, setPausingAds] = useState(new Set());
  const [adStatuses, setAdStatuses] = useState({}); // local optimistic status overrides
  const [remixingAd, setRemixingAd] = useState(null);
  const [quickAd, setQuickAd] = useState(null);

  // "Quick Ad" — the template-free launch path (AdBuilder-QuickAd-Feature-Brief.md).
  // Unlike Remix/Quick Variations/Quick Generate above (all AI-copy-assist tools that
  // still route through /ad-remix's template-deconstruction step), this is for when
  // Joel already has his own creative + copy ready and just wants to launch it —
  // seeds the exact localStorage cache keys AdAccountStep/CampaignStep/AdSetStep
  // already read for their own "auto-select from last used" behavior, so the wizard
  // on /facebook-campaigns arrives pre-aimed at this ad's account/campaign/ad set
  // without Joel having to search for any of them.
  const handleQuickAd = () => {
    if (!adAccountId || !fbCampaignId || !fbAdsetId) {
      showError('Missing account/campaign/ad set context for this row — cannot Quick Ad from here.');
      return;
    }
    safeLocalStorageSet('lastSelectedAdAccountId', adAccountId);
    safeLocalStorageSet('lastSelectedCampaignId_' + adAccountId, fbCampaignId);
    safeLocalStorageSet('lastSelectedAdSetId_' + fbCampaignId, fbAdsetId);
    safeLocalStorageSet('pendingQuickAd', JSON.stringify({
      ad_account_id: adAccountId,
      fb_campaign_id: fbCampaignId,
      fb_adset_id: fbAdsetId,
      adset_name: adsetName || '',
    }));
    navigate('/facebook-campaigns');
  };

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

  if (adsError) return <div className="mt-3 pl-10 text-xs text-amber-700">Creative breakdown unavailable: {adsError}</div>;

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
                    {/* Quick Ad → skips /ad-remix's template step entirely. For when
                        Joel already has his own creative + copy ready to launch, not
                        looking for AI remix/variation assistance. Labeled "Launch Own
                        Ad" rather than another "Quick *" name — three other buttons on
                        this row already share that prefix (Quick Variations, Quick
                        Generate), and this is the only one of the four that skips AI
                        copy assistance entirely; a tooltip alone wasn't going to carry
                        that distinction (joel-perspective P1). */}
                    <button
                      onClick={handleQuickAd}
                      className="flex items-center gap-1 px-2 py-1 rounded text-teal-700 bg-teal-50 hover:bg-teal-100 transition-colors text-xs font-medium whitespace-nowrap"
                      title="Launch with your own creative — skips the AI remix template, straight to Bulk Ad Creation for this account/campaign/ad set"
                    >
                      <Rocket size={11} /> Launch Own Ad
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
function extractNiche(adsetName) {
  if (!adsetName) return 'Unknown';
  const nonNiche = /^(batch\s*\d+|v\d+|scale|retarget|broad|phase\s*\d+|test|duplicate|copy)$/i;
  const parts = adsetName.split(' - ').map(part => part.trim());
  const dateLike = /^(?:\d{1,2}\/\d{1,2}(?:\/\d{2,4})?|\d{4}-\d{1,2}-\d{1,2}|\d{1,2}-\d{1,2}-\d{4})/;
  for (const part of parts.slice(1)) {
    if (part && !nonNiche.test(part) && !dateLike.test(part)) return part;
  }
  return parts[0] && !dateLike.test(parts[0]) ? parts[0] : 'General';
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

// ── State delivery diagnostic ──────────────────────────────────────────────────
// Meta can report delivery by state, but our RedTrack/Everflow joins are not
// state-granular. Keep this visually and semantically separate from ROAS/profit.
function StatePerformancePanel({ campaignId, campaignName, adAccountId, datePreset, dateFrom, dateTo, timedFetch, buildDateParams }) {
  const [open, setOpen] = useState(false);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const requestRef = useRef(0);

  const load = useCallback(async () => {
    if (!campaignId) return;
    const requestId = ++requestRef.current;
    setLoading(true);
    setError(null);
    try {
      const params = buildDateParams(datePreset, dateFrom, dateTo);
      params.set('campaign_id', campaignId);
      if (adAccountId) params.set('ad_account_id', adAccountId);
      const res = await timedFetch(`${API_BASE}/auto-pause/state-performance?${params}`, {}, 25000);
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `Unable to load state performance (${res.status})`);
      }
      const result = await res.json();
      if (requestId === requestRef.current) setData(result);
    } catch (err) {
      if (requestId === requestRef.current) setError(err.name === 'AbortError' ? 'Request timed out — Meta is slow. Try again.' : err.message);
    } finally {
      if (requestId === requestRef.current) setLoading(false);
    }
  }, [adAccountId, buildDateParams, campaignId, dateFrom, datePreset, dateTo, timedFetch]);

  const toggle = () => {
    const next = !open;
    setOpen(next);
    if (next && !data && !loading) load();
  };

  return (
    <div className="relative border-l border-slate-200 pl-3 text-right" onClick={e => e.stopPropagation()}>
      <button type="button" onClick={toggle} disabled={!campaignId} className="ml-auto flex items-center gap-1.5 rounded-lg border border-gray-200 bg-white px-2.5 py-1.5 text-xs font-medium text-gray-700 shadow-sm transition-colors hover:border-indigo-300 hover:bg-indigo-50 hover:text-indigo-700 disabled:cursor-not-allowed disabled:opacity-40" title={campaignId ? 'Inspect Meta delivery by state' : 'Campaign ID unavailable — sync this account first'}>
        <MapPin size={12} /> States
      </button>
      {open && (
        <div className="absolute right-6 mt-2 z-50 w-[min(700px,calc(100vw-3rem))] rounded-xl border border-gray-200 bg-white p-4 text-left shadow-xl" role="dialog" aria-label={`State performance for ${campaignName}`}>
          <div className="mb-3 flex items-start justify-between gap-3">
            <div>
              <h3 className="text-sm font-semibold text-gray-900">State performance</h3>
              <p className="mt-0.5 text-xs text-gray-500">{campaignName} · Meta delivery only. Revenue and ROAS are not available by state.</p>
            </div>
            <button type="button" onClick={load} disabled={loading} className="text-xs font-semibold text-indigo-600 hover:text-indigo-800 disabled:opacity-50">{loading ? 'Loading…' : 'Refresh'}</button>
          </div>
          {error && <div role="alert" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">{error}</div>}
          {loading && !data && <div className="py-8 text-center text-sm text-gray-400"><RefreshCw size={14} className="mr-1 inline animate-spin" />Loading state delivery…</div>}
          {data && (
            <>
              <div className="mb-3 rounded-lg border border-indigo-100 bg-indigo-50 px-3 py-2 text-xs text-indigo-900">
                Blended CPL: <strong>{data.blended_cpl != null ? formatMoney(data.blended_cpl) : '—'}</strong> · {formatMoney(data.total_spend)} spend · {data.total_leads.toLocaleString()} leads. A state is flagged only at $50+ spend, 2+ leads, and ≥1.5× the campaign CPL.
              </div>
              {data.states?.length ? <div className="max-h-80 overflow-y-auto rounded-lg border border-gray-100">
                <table className="w-full text-xs">
                  <thead className="sticky top-0 bg-gray-50 text-gray-500"><tr><th className="px-3 py-2 text-left font-medium">State</th><th className="px-3 py-2 text-right font-medium">Spend</th><th className="px-3 py-2 text-right font-medium">Leads</th><th className="px-3 py-2 text-right font-medium">CPL</th><th className="px-3 py-2 text-right font-medium">CTR</th><th className="px-3 py-2 text-right font-medium">Signal</th></tr></thead>
                  <tbody>{data.states.map(row => <tr key={row.state} className={row.is_dragging ? 'bg-red-50' : 'border-t border-gray-100'}><td className="px-3 py-2 font-medium text-gray-800">{row.state}</td><td className="px-3 py-2 text-right">{formatMoney(row.spend)}</td><td className="px-3 py-2 text-right">{row.leads}</td><td className={`px-3 py-2 text-right font-semibold ${row.is_dragging ? 'text-red-700' : 'text-gray-800'}`}>{formatMoney(row.cpl)}</td><td className="px-3 py-2 text-right">{row.ctr != null ? `${Number(row.ctr).toFixed(2)}%` : '—'}</td><td className="px-3 py-2 text-right">{row.is_dragging ? <span className="rounded-full bg-red-100 px-2 py-0.5 font-semibold text-red-700">Review targeting</span> : <span className="text-gray-400">—</span>}</td></tr>)}</tbody>
                </table>
              </div> : <p className="py-5 text-center text-sm text-gray-400">No state-level delivery returned for this period.</p>}
            </>
          )}
        </div>
      )}
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────
export default function CampaignPerformance() {
  const navigate = useNavigate();
  const { showSuccess, showError, showInfo, showWarning } = useToast();
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
  const dateRangeLabel = useMemo(() => {
    if (datePreset === 'custom') {
      return dateFrom && dateTo ? `${dateFrom} to ${dateTo}` : 'Custom range';
    }
    return DATE_PRESETS.find(p => p.value === datePreset)?.label || datePreset;
  }, [datePreset, dateFrom, dateTo]);
  const [loadingAdsets, setLoadingAdsets] = useState(false);
  const [adsetsError, setAdsetsError] = useState(null);
  const [syncing, setSyncing] = useState(false);
  const [statusFilter, setStatusFilter] = useState(() => {
    const view = searchParams.get('view');
    if (view === 'attention') return 'flagged';
    if (view === 'top-performers') return 'top_performers';
    if (searchParams.get('niche')) return 'all';
    return 'all';
  });
  const [sortBy, setSortBy] = useState(() => {
    const view = searchParams.get('view');
    if (view === 'top-performers') return 'roas';
    return 'spend';
  });
  // Name search — the one filter primitive AdEspresso's campaign-list view has that
  // this page didn't, per the competitor synthesis brief (§3.4). Local-only, not
  // synced to the URL — a transient narrowing while scanning, not a saved view.
  const [nameSearch, setNameSearch] = useState(() => searchParams.get('search') || '');
  const [nicheFilter, setNicheFilter] = useState(() => searchParams.get('niche') || '');
  // Metric-threshold filter — AdEspresso's "Filter by CPL < = > value" (§4 of that
  // capture), the other filter-surface gap logged in the same brief section.
  // `value === ''` means inactive; a real value narrows visibleAdsets by the
  // already-loaded bulkInsights numbers, same data source status/search use —
  // no new API call.
  const [metricFilter, setMetricFilter] = useState({ metric: 'cpl', operator: 'lt', value: '' });
  const dashboardView = searchParams.get('view'); // derived live from URL — never stale
  const targetAdsetId = searchParams.get('adsetId');

  // Bulk insights state — one API call replaces N per-row calls
  const [bulkInsights, setBulkInsights]       = useState(null);
  const [bulkInsightsLoading, setBulkInsightsLoading] = useState(false);
  const [bulkInsightsError, setBulkInsightsError]   = useState(null);

  // Ad-level (creative) breakdown state
  const [adsBulk, setAdsBulk]           = useState(null);
  const [adsLoading, setAdsLoading]     = useState(false);
  const [adsError, setAdsError]         = useState(null);
  const [rtAdsBulk, setRtAdsBulk]       = useState(null);  // RT data keyed by ad_id (sub3)
  const [rtAdsError, setRtAdsError]     = useState(null);
  const insightsRequestRef = useRef(0);
  const adsRequestRef = useRef(0);
  const rtAdsRequestRef = useRef(0);
  // Ad-level detail is intentionally lazy. The campaign scan only needs
  // ad-set metrics; loading every creative and every RedTrack sub1 row before
  // Joel expands one is the largest avoidable request on this page.
  const creativeDetailsKeyRef = useRef(null);
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
  const adsetsRequestRef = useRef(0);

  const loadAdsets = useCallback(async () => {
    const requestId = ++adsetsRequestRef.current;
    const isCurrent = () => adsetsRequestRef.current === requestId;
    setLoadingAdsets(true);
    setAdsetsError(null);
    try {
      const qs = adAccountId ? `?ad_account_id=${encodeURIComponent(adAccountId)}` : '';
      const res = await authFetch(`${API_BASE}/facebook/adsets/saved${qs}`);
      if (!res.ok) throw new Error('Failed to load ad sets');
      const data = await res.json();
      const adsetList = Array.isArray(data) ? data : data.adsets || [];
      if (!isCurrent()) return;
      setAdsets(adsetList);
      // Seed campaignBrands from adsets that already have a brand assigned (keyed by adset.id)
      const brands = {};
      adsetList.forEach(a => {
        if (a.id && a.brand_id) {
          brands[a.id] = { brand_id: a.brand_id, brand_name: a.brand_name };
        }
      });
      setCampaignBrands(prev => ({ ...prev, ...brands }));
    } catch (e) { if (isCurrent()) setAdsetsError(e.message || 'Failed to load ad sets'); }
    finally { if (isCurrent()) setLoadingAdsets(false); }
  }, [adAccountId]);

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
    const requestId = ++insightsRequestRef.current;
    const isCurrent = () => insightsRequestRef.current === requestId;
    setBulkInsightsLoading(true);
    setBulkInsightsError(null);
    try {
      const params = buildDateParams(preset, dateFrom, dateTo);
      if (accountId) params.set('ad_account_id', accountId);
      const res = await timedFetch(`${API_BASE}/auto-pause/insights-bulk?${params}`, {}, 25000);
      if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || `Failed to load insights (${res.status})`); }
      const data = await res.json();
      if (isCurrent()) setBulkInsights(data);
    } catch (e) {
      if (isCurrent()) {
        setBulkInsights(null);
        setBulkInsightsError(e.name === 'AbortError' ? 'Request timed out — Meta API is slow, try again.' : e.message);
      }
    } finally {
      if (isCurrent()) setBulkInsightsLoading(false);
    }
  }, [buildDateParams, timedFetch]);

  const loadAdsBulk = useCallback(async (accountId, preset, dateFrom = null, dateTo = null) => {
    const requestId = ++adsRequestRef.current;
    const isCurrent = () => adsRequestRef.current === requestId;
    setAdsError(null);
    setAdsLoading(true);
    try {
      const params = buildDateParams(preset, dateFrom, dateTo);
      if (accountId) params.set('ad_account_id', accountId);
      const res = await timedFetch(`${API_BASE}/auto-pause/ads-bulk?${params}`, {}, 20000);
      if (!res.ok) throw new Error(`Creative breakdown unavailable (${res.status})`);
      const data = await res.json();
      if (isCurrent()) setAdsBulk(data);
      return true;
    } catch (e) {
      if (isCurrent()) setAdsError(e.name === 'AbortError' ? 'Request timed out — try again.' : e.message);
      return false;
    } finally {
      if (isCurrent()) setAdsLoading(false);
    }
  }, [buildDateParams, timedFetch]);

  const loadRtAdsBulk = useCallback(async (preset, dateFrom = null, dateTo = null) => {
    const requestId = ++rtAdsRequestRef.current;
    const isCurrent = () => rtAdsRequestRef.current === requestId;
    setRtAdsBulk(null);
    setRtAdsError(null);
    try {
      const params = buildDateParams(preset, dateFrom, dateTo);
      if (adAccountId) params.set('ad_account_id', adAccountId);
      const res = await timedFetch(`${API_BASE}/redtrack/report/sub1?${params}`, {}, 15000);
      if (!res.ok) throw new Error(`RedTrack creative data unavailable (${res.status})`);
      const data = await res.json();
      if (isCurrent() && data.configured && data.data) setRtAdsBulk(data.data);
      return true;
    } catch (e) {
      if (isCurrent()) setRtAdsError(e.name === 'AbortError' ? 'Request timed out — try again.' : e.message);
      return false;
    }
  }, [adAccountId, buildDateParams, timedFetch]);

  const loadCreativeDetails = useCallback(async (accountId, preset, dateFrom = null, dateTo = null, force = false) => {
    if (preset === 'custom' && (!dateFrom || !dateTo)) return;
    const rangeKey = [accountId || '', preset, dateFrom || '', dateTo || ''].join(':');
    if (!force && creativeDetailsKeyRef.current === rangeKey) return;
    creativeDetailsKeyRef.current = rangeKey;
    const loaded = await Promise.all([
      loadAdsBulk(accountId, preset, dateFrom, dateTo),
      loadRtAdsBulk(preset, dateFrom, dateTo),
    ]);
    if (loaded.some(result => result === false)) creativeDetailsKeyRef.current = null;
  }, [loadAdsBulk, loadRtAdsBulk]);

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
  const skipNextDateReload = useRef(true);

  // Fire initial data load once the global active account has resolved; re-fire
  // when the header account switcher changes.
  useEffect(() => {
    if (activeAccountLoading) {
      insightsRequestRef.current += 1;
      adsRequestRef.current += 1;
      rtAdsRequestRef.current += 1;
      setAdsets([]); setExpandedAdsets(new Set()); setBulkInsights(null); setAdsBulk(null); setRtAdsBulk(null);
      setBulkInsightsError(null); setAdsError(null); setRtAdsError(null);
      adsetsRequestRef.current += 1;
      setLoadingAdsets(false);
      return;
    }
    initialLoadFired.current = true;
    const initPreset = searchParams.get('preset') || 'today';
    const initFrom   = searchParams.get('date_from') || null;
    const initTo     = searchParams.get('date_to')   || null;
    const resolvedPreset = (initFrom && initTo) ? 'custom' : initPreset;
    setAdsets([]);
    setExpandedAdsets(new Set());
    setBulkInsights(null);
    setAdsBulk(null);
    setAdsError(null);
    setBulkInsights(null);
    setBulkInsightsError(null);
    setRtAdsBulk(null);
    setRtAdsError(null);
    creativeDetailsKeyRef.current = null;
    loadBulkInsights(adAccountId, resolvedPreset, initFrom, initTo);
  }, [activeAccountLoading, adAccountId]); // eslint-disable-line react-hooks/exhaustive-deps

  // Re-fetch when user changes the date preset — skip the initial mount render
  // For custom range, wait until both dateFrom and dateTo are set
  useEffect(() => {
    if (!initialLoadFired.current) return;
    if (skipNextDateReload.current) {
      skipNextDateReload.current = false;
      return;
    }
    if (datePreset === 'custom' && (!dateFrom || !dateTo)) return;
    const from = datePreset === 'custom' ? dateFrom : null;
    const to   = datePreset === 'custom' ? dateTo   : null;
    setBulkInsights(null);
    setBulkInsightsError(null);
    setAdsBulk(null);
    setAdsError(null);
    setRtAdsBulk(null);
    setRtAdsError(null);
    creativeDetailsKeyRef.current = null;
    loadBulkInsights(adAccountId, datePreset, from, to);
  }, [datePreset, dateFrom, dateTo]); // eslint-disable-line react-hooks/exhaustive-deps

  // Deep links can expand an ad set without a click. Fetch creative detail at
  // that point too, but never while the normal campaign scan is collapsed.
  useEffect(() => {
    if (activeAccountLoading || !expandedAdsets.size) return;
    const from = datePreset === 'custom' ? dateFrom : null;
    const to = datePreset === 'custom' ? dateTo : null;
    const rangeKey = [adAccountId || '', datePreset, from || '', to || ''].join(':');
    if (creativeDetailsKeyRef.current === rangeKey) return;
    loadCreativeDetails(adAccountId, datePreset, from, to);
  }, [activeAccountLoading, adAccountId, datePreset, dateFrom, dateTo, expandedAdsets, loadCreativeDetails]);

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
    setNameSearch(searchParams.get('search') || '');
    setNicheFilter(searchParams.get('niche') || '');
    if (view === 'attention') { setStatusFilter('flagged'); setSortBy('spend'); }
    else if (view === 'top-performers') { setStatusFilter('top_performers'); setSortBy('roas'); }
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

      const [metaRes, rtRes] = await Promise.all([
        authFetch(`${API_BASE}/facebook/sync${metaParams}`, { method: 'POST' }),
        authFetch(`${API_BASE}/redtrack/sync?${rtParams}`, { method: 'POST' }).catch(() => null),
      ]);

      if (!metaRes.ok) {
        const e = await metaRes.json().catch(() => ({}));
        throw new Error(e.detail || 'Meta sync failed');
      }
      const result = await metaRes.json();
      const redTrackFailed = !rtRes || !rtRes.ok;
      // RedTrack failure must never be silently absorbed — a buyer refreshing
      // this page needs to know revenue/CPL may be stale even though the ad
      // structure just synced clean (audit finding 2026-08-21: this used to
      // be .catch(() => null) with the response discarded entirely).
      if (redTrackFailed) {
        const rtErr = rtRes ? await rtRes.json().catch(() => ({})) : {};
        showWarning(
          `Meta synced, but RedTrack revenue refresh failed${rtErr.detail ? `: ${rtErr.detail}` : ''} — revenue/CPL numbers may be stale.`
        );
      }
      // A truncated Meta sync must never read as a clean one. When Meta
      // throttles the ad set fetch the backend returns complete:false with the
      // failing pass in `errors` — surfacing that is the whole point, because a
      // partial sync silently under-attributes Everflow revenue in P&L rather
      // than failing visibly (RHO, ~$8.8k/month, 2026-09).
      const detail = `${result.campaigns.created} campaigns, ${result.adsets.created} ad sets imported. ${result.adsets.updated} ad sets updated.`;
      if (result.complete === false) {
        showWarning(
          `Meta sync INCOMPLETE — ${detail} Some ad sets could not be fetched${result.errors?.length ? `: ${result.errors.join('; ')}` : ''}. Revenue attribution may be understated until this is re-run.`
        );
      } else if (!redTrackFailed) {
        showSuccess(`Sync complete — ${detail}`);
      }
      loadAdsets();
      const from = datePreset === 'custom' ? dateFrom : null;
      const to   = datePreset === 'custom' ? dateTo   : null;
      loadBulkInsights(adAccountId, datePreset, from, to);
      setAdsBulk(null);
      setRtAdsBulk(null);
      setAdsError(null);
      setRtAdsError(null);
      creativeDetailsKeyRef.current = null;
      if (expandedAdsets.size) loadCreativeDetails(adAccountId, datePreset, from, to);
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

  // Keep these reasons aligned with Dashboard.jsx's Needs Attention rules.
  const getAttentionReasons = useCallback((a) => {
    const ins = bulkInsights?.[a.fb_adset_id];
    if (!ins) return [];
    const reasons = [];
    if (ins.frequency >= 5) reasons.push(`Frequency ${ins.frequency.toFixed(1)} — fatigue risk`);
    else if (ins.frequency >= 3) reasons.push(`Frequency ${ins.frequency.toFixed(1)} — monitor`);
    if (ins.spend > 50 && ins.leads === 0) reasons.push(`${formatMoney(ins.spend)} spent, 0 leads`);
    if (ins.redtrack?.roas != null && ins.redtrack.roas < 1 && ins.spend > 30) reasons.push(`RT ROAS ${ins.redtrack.roas.toFixed(2)}x — losing money`);
    if (blendedCpl != null && ins.cpl != null && ins.cpl > blendedCpl * 1.5 && ins.spend > 30 && (ins.redtrack?.roas == null || ins.redtrack.roas < 1)) {
      reasons.push(`CPL ${formatMoney(ins.cpl)} — above 1.5x blended average`);
    }
    if (rules.some(r => r.triggered_at && r.adset_id === a.id)) reasons.push('Auto-pause rule triggered');
    return reasons;
  }, [bulkInsights, rules, blendedCpl]);

  const isFlagged = useCallback((a) => getAttentionReasons(a).length > 0, [getAttentionReasons]);

  const compassBuckets = useMemo(() => {
    const active = adsets.filter(a => a.fb_adset_id && normalizeStatus(adsetStatusOverrides[a.fb_adset_id] ?? a.status) === 'ACTIVE' && (!a.campaign_status || normalizeStatus(a.campaign_status) === 'ACTIVE'));
    const attention = active.map(adset => ({ adset, reasons: getAttentionReasons(adset) })).filter(item => item.reasons.length).map(item => ({ ...item, id: `attention-${item.adset.id}`, detail: item.reasons[0] }));
    const winners = active.filter(a => bulkInsights?.[a.fb_adset_id]).map(adset => ({ adset, ins: bulkInsights[adset.fb_adset_id] })).filter(({ ins }) => (ins.spend ?? 0) >= 50 && ins.redtrack?.roas > 0).sort((a, b) => b.ins.redtrack.roas - a.ins.redtrack.roas).map(({ adset, ins }) => ({ id: `winner-${adset.id}`, adset, detail: `RT ROAS ${ins.redtrack.roas.toFixed(2)}x · ${formatMoney(ins.spend)} spend` }));
    const cutoff = Date.now() - 14 * 24 * 60 * 60 * 1000;
    const recent = active.filter(adset => adset.start_time && !Number.isNaN(Date.parse(adset.start_time)) && Date.parse(adset.start_time) >= cutoff).map(adset => ({ id: `recent-${adset.id}`, adset, detail: `Started ${new Date(adset.start_time).toLocaleDateString()}` }));
    const potential = active.map(adset => ({ adset, ins: bulkInsights?.[adset.fb_adset_id] })).filter(({ ins }) => ins?.ctr != null && ins.ctr > 2 && (ins.spend ?? 0) < 75).map(({ adset, ins }) => ({ id: `potential-${adset.id}`, adset, detail: `CTR ${Number(ins.ctr).toFixed(2)}% · ${formatMoney(ins.spend)} spend` }));
    return [
      { key: 'attention', label: 'Ad sets that need attention', color: 'text-orange-700', rule: 'Frequency ≥3, zero leads after $50, RT ROAS <1, CPL >1.5x blended average, or an auto-pause rule triggered.', items: attention },
      { key: 'winners', label: 'Winners', color: 'text-green-700', rule: 'Active ad sets with RT ROAS >0 and at least $50 spend, sorted highest first.', items: winners },
      { key: 'recent', label: 'Launched recently', color: 'text-blue-700', rule: 'Active ad sets with Meta start_time inside the last 14 days.', items: recent },
      { key: 'potential', label: 'High potential', color: 'text-violet-700', rule: 'Active ad sets with CTR >2.0% and less than $75 spend — early signal, not a winner yet.', items: potential },
      { key: 'scaling', label: 'Scaling', color: 'text-emerald-700', rule: 'Needs a clean prior-period spend comparison; no misleading day-over-day proxy is used.', items: [], empty: 'Needs prior-period data before this bucket can make a claim.' },
    ];
  }, [adsets, bulkInsights, getAttentionReasons, adsetStatusOverrides]);
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
    } else if (statusFilter === 'top_performers' && (bulkInsightsError || (bulkInsights && Object.keys(bulkInsights).length > 0 && Object.values(bulkInsights).every(insight => insight?.redtrack == null)))) {
      list = [];
    } else if (statusFilter === 'top_performers') {
      list = list.filter(a => {
        const insight = bulkInsights?.[a.fb_adset_id];
        return (insight?.spend ?? 0) >= 50 && (insight?.redtrack?.roas ?? 0) > 0;
      });
    } else if (statusFilter === 'has_spend' && !bulkInsightsError) {
      list = list.filter(a => (bulkInsights?.[a.fb_adset_id]?.spend ?? 0) > 0);
    } else if (statusFilter === 'flagged') {
      list = list.filter(a => isActiveDelivery(a) && isFlagged(a));
    }

    // Name search
    const q = nameSearch.trim().toLowerCase();
    if (q) {
      list = list.filter(a => a.name?.toLowerCase().includes(q));
    }

    if (nicheFilter) {
      list = list.filter(a => extractNiche(a.name) === nicheFilter);
    }

    // Metric-threshold filter (AdEspresso's "Filter by CPL < = > value")
    if (metricFilter.value !== '' && !Number.isNaN(Number(metricFilter.value)) && !bulkInsightsError) {
      const threshold = Number(metricFilter.value);
      list = list.filter(a => {
        const insight = bulkInsights?.[a.fb_adset_id];
        const metricValue = metricFilter.metric === 'cpl' ? insight?.cpl
          : metricFilter.metric === 'spend' ? insight?.spend
          : metricFilter.metric === 'roas' ? insight?.redtrack?.roas
          : null;
        // No data for this ad set on the current metric — exclude rather than
        // include-by-default, since "does CPL < $50" can't be answered true for
        // an ad set with no CPL reading at all.
        if (metricValue == null) return false;
        return metricFilter.operator === 'lt' ? metricValue < threshold : metricValue > threshold;
      });
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
  }, [adsets, statusFilter, sortBy, nameSearch, nicheFilter, metricFilter, bulkInsights, bulkInsightsError, isFlagged, getAdsetStatus, isActiveDelivery, isPausedDelivery]);

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

  const visibleSummary = useMemo(() => {
    const countedCboCampaigns = new Set();
    const totals = visibleAdsets.reduce((acc, adset) => {
      const insight = bulkInsights?.[adset.fb_adset_id];
      acc.spend += insight?.spend ?? 0;
      acc.leads += insight?.leads ?? 0;
      acc.revenue += insight?.redtrack?.revenue ?? 0;
      if (adset.campaign_budget_optimization === 'CBO' || adset.campaign_daily_budget) {
        const campaignKey = adset.fb_campaign_id || adset.campaign_id || `adset-${adset.id}`;
        if (!countedCboCampaigns.has(campaignKey)) {
          countedCboCampaigns.add(campaignKey);
          acc.dailyBudget += adset.campaign_daily_budget ?? 0;
        }
      } else {
        acc.dailyBudget += adset.daily_budget ?? 0;
      }
      return acc;
    }, {
      spend: 0,
      leads: 0,
      revenue: 0,
      dailyBudget: 0,
    });

    return {
      campaignCount: groupedCampaigns.length,
      adsetCount: visibleAdsets.length,
      activeAdsetCount: visibleAdsets.filter(isActiveDelivery).length,
      totalSpend: totals.spend,
      totalLeads: totals.leads,
      cpl: totals.spend > 0 && totals.leads > 0 ? totals.spend / totals.leads : null,
      rtRoas: totals.spend > 0 && totals.revenue > 0 ? totals.revenue / totals.spend : null,
      dailyBudget: totals.dailyBudget > 0 ? totals.dailyBudget / 100 : null,
    };
  }, [visibleAdsets, bulkInsights, groupedCampaigns.length, isActiveDelivery]);

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

  const openCompassAdset = useCallback((adset) => {
    // Compass buckets only surface active-delivery ad sets (Winners included, after the
    // active-status fix below) — force the table filters back to a state where the target
    // is guaranteed visible, rather than risk a silent no-op if the buyer had a different
    // status/search/metric filter active when they clicked.
    setStatusFilter('ACTIVE');
    setNameSearch('');
    setMetricFilter({ metric: 'cpl', operator: 'lt', value: '' });
    setHighlightedAdsetId(adset.fb_adset_id);
    setSearchParams(prev => {
      const next = new URLSearchParams(prev);
      next.set('adsetId', adset.fb_adset_id);
      next.set('view', 'compass');
      return next;
    });
  }, [setSearchParams]);

  return (
    <>
    <div className="-m-5 mx-auto max-w-[1800px] space-y-0">
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
          <CampaignIntelligencePanel
            adAccountId={adAccountId}
            pageDatePreset={datePreset}
            pageDateFrom={dateFrom}
            pageDateTo={dateTo}
          />
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
              : nicheFilter
                ? <><Target size={15} /> Showing all ad sets in niche <span className="font-semibold">{nicheFilter}</span></>
                : dashboardView === 'top-performers'
                  ? <><TrendingUp size={15} /> Showing top performers — at least $50 spend and positive RT ROAS</>
                  : <><TrendingUp size={15} /> Showing all ad sets</>
            }
          </div>
          <button
            onClick={() => { setSearchParams({}); setStatusFilter('all'); setNameSearch(''); setNicheFilter(''); setSortBy('spend'); setHighlightedAdsetId(null); }}
            className="ml-4 hover:opacity-70 transition-opacity"
          >
            <X size={14} />
          </button>
        </div>
      )}

      <div className="px-5 pb-5 space-y-4 mt-1">
      <CreativeCompass buckets={compassBuckets} onOpenAdset={openCompassAdset} dateRangeLabel={dateRangeLabel} />

      {/* Ad Set Performance Table */}
      <div className="bg-white rounded-xl border border-indigo-100 border-l-4 border-l-indigo-500 shadow-sm overflow-clip">
        <div className="px-6 py-4 border-b border-indigo-100 bg-indigo-50/35 flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <h2 className="font-semibold text-gray-900 flex items-center gap-2">
              <Target size={16} className="text-indigo-600" /> Performance
              {nicheFilter && <span className="text-xs text-indigo-600 font-normal">· {nicheFilter}</span>}
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
            {/* Name search — real gap flagged in the competitor synthesis brief
                (AdEspresso's campaign-list view has this, this page didn't). */}
            <div className="relative">
              <Search size={12} className="absolute left-2 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none" />
              <input
                type="text"
                placeholder="Search ad sets..."
                value={nameSearch}
                onChange={e => setNameSearch(e.target.value)}
                className="border border-gray-200 rounded-lg pl-6 pr-6 py-1.5 text-xs text-gray-600 w-36 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:w-48 transition-all"
              />
              {nameSearch && (
                <button
                  onClick={() => setNameSearch('')}
                  className="absolute right-1.5 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
                  title="Clear search"
                >
                  <X size={12} />
                </button>
              )}
            </div>
            {/* Metric-threshold filter — the other filter-surface gap from the same
                brief section (AdEspresso's "Filter by CPL < = > value"). Reads
                already-loaded bulkInsights, no new API call. */}
            <div className="flex items-center gap-1 border border-gray-200 rounded-lg px-1.5 py-1">
              <select
                className="text-xs text-gray-600 bg-transparent focus:outline-none"
                value={metricFilter.metric}
                disabled={bulkInsightsLoading || !!bulkInsightsError}
                onChange={e => setMetricFilter(prev => ({ ...prev, metric: e.target.value }))}
              >
                <option value="cpl">CPL</option>
                <option value="spend">Spend</option>
                <option value="roas">RT ROAS</option>
              </select>
              <select
                className="text-xs text-gray-600 bg-transparent focus:outline-none"
                value={metricFilter.operator}
                disabled={bulkInsightsLoading || !!bulkInsightsError}
                onChange={e => setMetricFilter(prev => ({ ...prev, operator: e.target.value }))}
              >
                <option value="lt">&lt;</option>
                <option value="gt">&gt;</option>
              </select>
              <input
                type="number"
                placeholder="value"
                value={metricFilter.value}
                disabled={bulkInsightsLoading || !!bulkInsightsError}
                onChange={e => setMetricFilter(prev => ({ ...prev, value: e.target.value }))}
                className="w-14 text-xs text-gray-600 bg-transparent focus:outline-none"
              />
              {metricFilter.value !== '' && (
                <button
                  onClick={() => setMetricFilter(prev => ({ ...prev, value: '' }))}
                  className="text-gray-400 hover:text-gray-600"
                  title="Clear metric filter"
                >
                  <X size={12} />
                </button>
              )}
            </div>
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
              <option value="top_performers">Top performers</option>
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
              onClick={() => {
                const from = datePreset === 'custom' ? dateFrom : null;
                const to = datePreset === 'custom' ? dateTo : null;
                loadAdsets();
                loadBulkInsights(adAccountId, datePreset, from, to);
                setAdsBulk(null);
                setRtAdsBulk(null);
                setAdsError(null);
                setRtAdsError(null);
                creativeDetailsKeyRef.current = null;
                if (expandedAdsets.size) loadCreativeDetails(adAccountId, datePreset, from, to);
              }}
              className="text-gray-400 hover:text-gray-600 transition-colors"
              title="Refresh"
            >
              <RefreshCw size={14} />
            </button>
          </div>
        </div>

        {/* Show spinner while loading — especially important for insight-dependent filters */}
        {bulkInsightsError && statusFilter === 'top_performers' && (
          <div role="alert" className="mx-5 mb-4 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
            Top-performer metrics are unavailable: {bulkInsightsError}. <button type="button" className="font-semibold underline" onClick={() => { const from = datePreset === 'custom' ? dateFrom : null; const to = datePreset === 'custom' ? dateTo : null; loadBulkInsights(adAccountId, datePreset, from, to); }}>Retry metrics</button>
          </div>
        )}
        {bulkInsightsError && statusFilter !== 'top_performers' && (
          <div role="alert" className="mx-5 mb-4 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
            Performance metrics are unavailable: {bulkInsightsError}. Showing campaigns without spend filtering so Meta/API failures do not look like zero activity.
          </div>
        )}
        {statusFilter === 'top_performers' && bulkInsights && Object.keys(bulkInsights).length > 0 && Object.values(bulkInsights).some(insight => insight?.redtrack == null) && (
          <div role="alert" className="mx-5 mb-4 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">RedTrack metrics are incomplete, so only ad sets with confirmed ROAS can appear here. Retry or sync RedTrack before acting on this view.</div>
        )}
        {rtAdsError && <div role="status" className="mx-5 mb-4 rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-xs text-gray-600">RedTrack creative-level data is unavailable: {rtAdsError}. Meta creative metrics remain available.</div>}
        {adsetsError && <div role="alert" className="mx-5 mb-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">{adsetsError}. <button type="button" className="font-semibold underline" onClick={loadAdsets}>Retry ad sets</button></div>}
        {(loadingAdsets || (bulkInsightsLoading && (['flagged', 'has_spend', 'top_performers', 'roas'].includes(statusFilter) || sortBy === 'cpl' || sortBy === 'roas' || metricFilter.value !== ''))) ? (
          <div className="p-8 text-center text-gray-400 text-sm flex items-center justify-center gap-2">
            <RefreshCw size={14} className="animate-spin" /> Loading…
          </div>
        ) : adsetsError ? null : visibleAdsets.length === 0 ? (
          <div className="p-8 text-center text-gray-400 text-sm">
            {nameSearch ? `No ad sets matching "${nameSearch}".` :
             metricFilter.value !== '' ? `No ad sets with ${metricFilter.metric.toUpperCase()} ${metricFilter.operator === 'lt' ? '<' : '>'} ${metricFilter.value}.` :
             statusFilter === 'has_spend' ? 'No ad sets with spend in this date range.' :
             statusFilter === 'top_performers' ? 'No ad sets with at least $50 spend and positive ROAS in this date range.' :
             statusFilter === 'flagged' ? 'No flagged ad sets — everything looks healthy.' :
             statusFilter !== 'all' ? `No ${statusFilter.toLowerCase()} ad sets found.` :
             'No launched ad sets found. Create and launch a campaign first.'}
          </div>
        ) : (
          <div>
            <div className="grid grid-cols-[minmax(300px,1fr)_96px_84px_96px_96px_86px_124px] px-6 py-1.5 border-b border-slate-200 bg-slate-50 text-[10px] font-semibold uppercase tracking-wide text-gray-400 sticky top-0 z-10">
              <div />
              {['Spend', 'Leads', 'CPL', 'ROAS'].map(col => (
                <div key={col} className="border-l border-slate-200 px-3 text-right">{col}</div>
              ))}
              <div />
              <div className="border-l border-slate-200 px-3 text-right">Budget</div>
            </div>
            <div className="grid grid-cols-[minmax(300px,1fr)_96px_84px_96px_96px_86px_124px] px-6 py-3 border-b border-indigo-100 bg-indigo-50/60 text-left">
              <div className="flex items-center gap-2 min-w-0 pr-4">
                <span className="font-semibold text-gray-900 text-sm">Visible total</span>
                <span className="text-xs text-gray-500">
                  {visibleSummary.campaignCount} campaign{visibleSummary.campaignCount !== 1 ? 's' : ''} · {visibleSummary.adsetCount} ad set{visibleSummary.adsetCount !== 1 ? 's' : ''} · {visibleSummary.activeAdsetCount} active
                </span>
              </div>
              {[
                ['Spend', bulkInsightsLoading ? '--' : formatMoneyCell(visibleSummary.totalSpend)],
                ['Leads', bulkInsightsLoading ? '--' : formatNumberCell(visibleSummary.totalLeads)],
                ['CPL', bulkInsightsLoading ? '--' : formatMoneyCell(visibleSummary.cpl, 2)],
                ['ROAS', bulkInsightsLoading ? '--' : formatRoasCell(visibleSummary.rtRoas)],
              ].map(([label, value]) => (
                <div key={label} className="border-l border-indigo-100 px-3 text-right">
                  <span className="text-sm font-bold text-gray-900">{value}</span>
                </div>
              ))}
              <div />
              <div className="border-l border-indigo-100 px-3 text-right">
                <span className="text-sm font-bold text-gray-900">
                  {bulkInsightsLoading ? '--' : formatMoneyCell(visibleSummary.dailyBudget)}
                </span>
                <div className="text-[10px] text-gray-400 uppercase tracking-wide">Daily</div>
              </div>
            </div>
            {groupedCampaigns.map(group => {
              const isCampaignOpen = !collapsedCampaigns.has(group.key);
              const activeCount = group.adsets.filter(isActiveDelivery).length;

              return (
                <div key={group.key} className="border-b border-gray-100 last:border-b-0">
                  <div
                    onClick={() => toggleCampaign(group.key)}
                    className="w-full grid grid-cols-[minmax(300px,1fr)_96px_84px_96px_96px_86px_124px] px-6 py-3 bg-slate-100/80 hover:bg-slate-100 transition-colors text-left border-b border-slate-200 border-l-4 border-l-slate-500"
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

                    <StatePerformancePanel
                      campaignId={group.fbCampaignId}
                      campaignName={group.campaignName}
                      adAccountId={adAccountId}
                      datePreset={datePreset}
                      dateFrom={datePreset === 'custom' ? dateFrom : null}
                      dateTo={datePreset === 'custom' ? dateTo : null}
                      timedFetch={timedFetch}
                      buildDateParams={buildDateParams}
                    />

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
                            const adsetRules = rules.filter(r => r.adset_id === adset.id);
                            const triggeredRule = adsetRules.find(r => r.triggered_at);
                            const activeRule = adsetRules.find(r => r.is_active && !r.triggered_at);
                            const cb = campaignBrands[adset.id];
                            const isAssigning = assigningBrand === adset.id;
                            const isHighlighted = highlightedAdsetId === adset.fb_adset_id;

                            const toggleExpand = () => {
                              if (!isExpanded) {
                                const from = datePreset === 'custom' ? dateFrom : null;
                                const to = datePreset === 'custom' ? dateTo : null;
                                loadCreativeDetails(adAccountId, datePreset, from, to);
                              }
                              setExpandedAdsets(prev => {
                                const next = new Set(prev);
                                next.has(adset.fb_adset_id) ? next.delete(adset.fb_adset_id) : next.add(adset.fb_adset_id);
                                return next;
                              });
                            };

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
                                      title="Show creative breakdown (loaded on demand)"
                                    >
                                      <span className="flex-shrink-0 text-gray-400">
                                        {isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                                      </span>
                                      <span className="font-medium text-gray-900 truncate" title={adset.name}>{adset.name}</span>
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
                                        adAccountId={adAccountId}
                                        adsBulk={adsBulk}
                                        adsLoading={adsLoading}
                                        adsError={adsError}
                                        rtAdsBulk={rtAdsBulk}
                                        onAdStatusChange={() => loadCreativeDetails(adAccountId, datePreset, datePreset === 'custom' ? dateFrom : null, datePreset === 'custom' ? dateTo : null, true)}
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
