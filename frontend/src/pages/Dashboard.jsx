import React, { useEffect, useState, useCallback, useRef } from 'react';
import { AlertTriangle, TrendingUp, RefreshCw, ArrowRight, Calendar, ChevronDown, PauseCircle, MessageSquare, Send, Sparkles, DollarSign, Zap } from 'lucide-react';
import { Link, useNavigate } from 'react-router-dom';
import { authFetch } from '../lib/facebookApi';
import { useToast } from '../context/ToastContext';
import { useCampaign } from '../context/CampaignContext';
import { useAuth } from '../context/AuthContext';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1';

function pnlRevenueSourceLabel(source) {
  if (!source || source === 'none') return 'None';
  if (source === 'everflow_unavailable') return 'Switchboard unavailable';
  if (source.startsWith('everflow')) return source === 'everflow_live' ? 'Switchboard' : `Switchboard · ${source.replace('everflow_', '').replaceAll('_', ' ')}`;
  if (source === 'redtrack_unavailable') return 'RedTrack unavailable';
  if (source.startsWith('redtrack')) return source === 'redtrack_live' ? 'RedTrack' : `RedTrack · ${source.replace('redtrack_', '').replaceAll('_', ' ')}`;
  return source.replaceAll('_', ' ');
}

const normalizeStatus = (status) => (status || '').toString().toUpperCase();

function MarkdownAnswer({ text }) {
  const lines = text.split('\n');
  const elements = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    // Horizontal rule
    if (/^---+$/.test(line.trim())) {
      elements.push(<hr key={i} className="my-3 border-gray-200" />);
      i++; continue;
    }

    // Table: detect header row followed by separator
    if (i + 1 < lines.length && /^\|.*\|$/.test(line) && /^\|[-| :]+\|$/.test(lines[i + 1])) {
      const headers = line.split('|').filter((_, idx, arr) => idx > 0 && idx < arr.length - 1).map(h => h.trim());
      i += 2; // skip header + separator
      const rows = [];
      while (i < lines.length && /^\|.*\|$/.test(lines[i])) {
        const cells = lines[i].split('|').filter((_, idx, arr) => idx > 0 && idx < arr.length - 1).map(c => c.trim());
        rows.push(cells);
        i++;
      }
      elements.push(
        <div key={`table-${i}`} className="overflow-x-auto my-2">
          <table className="text-xs w-full border-collapse">
            <thead>
              <tr className="bg-gray-100">
                {headers.map((h, hi) => (
                  <th key={hi} className="px-2 py-1.5 text-left font-semibold text-gray-700 border border-gray-200">{renderInline(h)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, ri) => (
                <tr key={ri} className={ri % 2 === 0 ? 'bg-white' : 'bg-gray-50'}>
                  {row.map((cell, ci) => (
                    <td key={ci} className="px-2 py-1.5 border border-gray-200 text-gray-700">{renderInline(cell)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
      continue;
    }

    // Heading ##
    const h2 = line.match(/^##\s+(.+)/);
    if (h2) {
      elements.push(<p key={i} className="font-semibold text-gray-900 text-sm mt-3 mb-1">{renderInline(h2[1])}</p>);
      i++; continue;
    }

    // Heading ###
    const h3 = line.match(/^###\s+(.+)/);
    if (h3) {
      elements.push(<p key={i} className="font-medium text-gray-800 text-sm mt-2 mb-0.5">{renderInline(h3[1])}</p>);
      i++; continue;
    }

    // Blank line
    if (line.trim() === '') {
      elements.push(<div key={i} className="h-1.5" />);
      i++; continue;
    }

    // Regular paragraph
    elements.push(<p key={i} className="text-sm text-gray-800 leading-relaxed">{renderInline(line)}</p>);
    i++;
  }

  return <div className="space-y-0.5">{elements}</div>;
}

function renderInline(text) {
  // Split on **bold** markers
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return parts.map((part, i) => {
    const bold = part.match(/^\*\*(.+)\*\*$/);
    if (bold) return <strong key={i} className="font-semibold text-gray-900">{bold[1]}</strong>;
    return part;
  });
}

const PRESETS = [
  { value: 'today',    label: 'Today' },
  { value: 'yesterday', label: 'Yesterday' },
  { value: 'last_7d',  label: 'Last 7 Days' },
  { value: 'last_14d', label: 'Last 14 Days' },
  { value: 'last_30d', label: 'Last 30 Days' },
];

function KpiCard({ label, value, sub, highlight, warn }) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-5">
      <div className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-1">{label}</div>
      <div className={`text-2xl font-bold ${highlight ? 'text-red-600' : warn ? 'text-orange-500' : 'text-gray-900'}`}>
        {value}
      </div>
      {sub && <div className="text-xs text-gray-400 mt-0.5">{sub}</div>}
    </div>
  );
}

function DateFilter({ preset, setPreset, dateFrom, setDateFrom, dateTo, setDateTo, onApply }) {
  const [open, setOpen] = useState(false);
  const [showCustom, setShowCustom] = useState(false);
  const ref = useRef(null);

  // Close dropdown on outside click
  useEffect(() => {
    function handleClick(e) {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    }
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, []);

  const activeLabel = showCustom && dateFrom && dateTo
    ? `${dateFrom} – ${dateTo}`
    : (PRESETS.find(p => p.value === preset)?.label ?? 'Last 7 Days');

  function selectPreset(val) {
    setPreset(val);
    setShowCustom(false);
    setOpen(false);
    onApply({ preset: val, dateFrom: null, dateTo: null });
  }

  function applyCustom() {
    if (!dateFrom || !dateTo) return;
    setShowCustom(true);
    setOpen(false);
    onApply({ preset: null, dateFrom, dateTo });
  }

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen(o => !o)}
        className="flex items-center gap-2 px-3 py-2 rounded-lg text-sm text-gray-600 border border-gray-200 bg-white hover:bg-gray-50 transition-colors"
      >
        <Calendar size={13} className="text-gray-400" />
        {activeLabel}
        <ChevronDown size={12} className="text-gray-400" />
      </button>

      {open && (
        <div className="absolute right-0 mt-1 w-64 bg-white border border-gray-200 rounded-xl shadow-lg z-50 py-1 overflow-hidden">
          {PRESETS.map(p => (
            <button
              key={p.value}
              onClick={() => selectPreset(p.value)}
              className={`w-full text-left px-4 py-2 text-sm transition-colors ${
                preset === p.value && !showCustom
                  ? 'bg-indigo-50 text-indigo-700 font-medium'
                  : 'text-gray-700 hover:bg-gray-50'
              }`}
            >
              {p.label}
            </button>
          ))}
          <div className="border-t border-gray-100 mt-1 pt-1 px-3 pb-3">
            <div className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-2 pt-1">Custom range</div>
            <div className="flex flex-col gap-1.5">
              <input
                type="date"
                value={dateFrom}
                onChange={e => setDateFrom(e.target.value)}
                className="w-full text-xs border border-gray-200 rounded-lg px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-indigo-400"
              />
              <input
                type="date"
                value={dateTo}
                onChange={e => setDateTo(e.target.value)}
                className="w-full text-xs border border-gray-200 rounded-lg px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-indigo-400"
              />
            </div>
            <button
              onClick={applyCustom}
              disabled={!dateFrom || !dateTo}
              className="mt-2 w-full bg-indigo-600 text-white text-xs font-medium py-1.5 rounded-lg hover:bg-indigo-700 disabled:opacity-40 transition-colors"
            >
              Apply
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export default function Dashboard() {
  const navigate = useNavigate();
  const { showSuccess, showError } = useToast();
  const { hasPermission } = useAuth();
  const { activeAccountId, activeAccountLoading, adAccounts } = useCampaign();
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [syncingRT, setSyncingRT] = useState(false);
  const [pausingAdsets, setPausingAdsets] = useState(new Set());
  const [pausedOverrides, setPausedOverrides] = useState(new Set()); // fb_adset_ids paused this session
  const [insightsError, setInsightsError] = useState(null);
  const [adsets, setAdsets] = useState([]);
  const [bulkInsights, setBulkInsights] = useState({});
  const [nicheSummary, setNicheSummary] = useState([]);
  const [rules, setRules] = useState([]);

  // AI Insights panel state
  const [aiQuery, setAiQuery] = useState('');
  const [aiAnswer, setAiAnswer] = useState('');
  const [aiLoading, setAiLoading] = useState(false);
  const [aiDatePreset, setAiDatePreset] = useState('last_7d');
  const [showAiExamples, setShowAiExamples] = useState(false);
  const [budgetPopover, setBudgetPopover] = useState(null);
  const [campaignBudgetInput, setCampaignBudgetInput] = useState('');
  const [campaignBudgetType, setCampaignBudgetType] = useState('CBO');
  const [savingCampaignBudget, setSavingCampaignBudget] = useState(null);
  const [editingBudget, setEditingBudget] = useState(null);
  const [budgetInput, setBudgetInput] = useState('');
  const [savingBudget, setSavingBudget] = useState(null);
  const [scalingAdset, setScalingAdset] = useState(new Set());
  const [quickGeneratingAdsets, setQuickGeneratingAdsets] = useState(new Set());
  const [collapsedSections, setCollapsedSections] = useState({});
  const [expandedSections, setExpandedSections] = useState({});
  const [pnlSummary, setPnlSummary] = useState(null);
  const [pnlLoading, setPnlLoading] = useState(false);

  // Date filter state
  const [preset, setPreset] = useState(() => localStorage.getItem('bhm_date_preset') || 'today');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [activeRange, setActiveRange] = useState(() => ({ preset: localStorage.getItem('bhm_date_preset') || 'today', dateFrom: null, dateTo: null }));

  const toggleSection = (section) => {
    setCollapsedSections(prev => ({ ...prev, [section]: !prev[section] }));
  };

  const toggleExpandedSection = (section) => {
    setExpandedSections(prev => ({ ...prev, [section]: !prev[section] }));
  };

  const load = useCallback(async (range) => {
    const { preset: p, dateFrom: df, dateTo: dt } = range || { preset: 'today', dateFrom: null, dateTo: null };
    if (activeAccountLoading) return;
    if (!activeAccountId && adAccounts.length > 0) return;
    setLoading(true);
    setInsightsError(null);
    setBulkInsights({}); // clear stale data so KPIs show — while loading
    setNicheSummary([]);
    try {
      const insightsParams = new URLSearchParams();
      if (activeAccountId) insightsParams.set('ad_account_id', activeAccountId);
      if (df && dt) {
        insightsParams.set('date_from', df);
        insightsParams.set('date_to', dt);
      } else {
        insightsParams.set('date_preset', p || 'today');
      }

      const timedFetch = (url, ms = 25000) => {
        const ctrl = new AbortController();
        const tid = setTimeout(() => ctrl.abort(), ms);
        return authFetch(url, { signal: ctrl.signal }).finally(() => clearTimeout(tid));
      };

      const [adsetsRes, insightsRes, nicheRes, rulesRes] = await Promise.all([
        timedFetch(`${API_URL}/facebook/adsets/saved?${insightsParams}`, 10000),
        timedFetch(`${API_URL}/auto-pause/insights-bulk?${insightsParams}`, 25000),
        timedFetch(`${API_URL}/dashboard/niche-summary?${insightsParams}`, 25000),
        timedFetch(`${API_URL}/auto-pause/rules`, 10000),
      ]);
      if (adsetsRes.ok)   setAdsets(await adsetsRes.json());
      if (insightsRes.ok) {
        setBulkInsights(await insightsRes.json());
      } else {
        const err = await insightsRes.json().catch(() => ({}));
        setInsightsError(err.detail || `Meta API error (${insightsRes.status}) — try a different date range`);
      }
      if (nicheRes.ok) {
        setNicheSummary(await nicheRes.json());
      } else {
        showError(`Niche summary unavailable (${nicheRes.status})`);
      }
      if (rulesRes.ok)    setRules(await rulesRes.json());
    } catch (e) {
      if (e.name !== 'AbortError') setInsightsError('Request timed out — check your connection and try again');
    } finally {
      setLoading(false);
    }
  }, [activeAccountId, activeAccountLoading, adAccounts.length, showError]);


  const syncAll = useCallback(async () => {
    if (activeAccountLoading || (!activeAccountId && adAccounts.length > 0)) return;
    setSyncing(true);
    setSyncingRT(true);
    try {
      const { preset: p, dateFrom: df, dateTo: dt } = activeRange;
      const params = new URLSearchParams();
      if (activeAccountId) params.set('ad_account_id', activeAccountId);
      if (df && dt) { params.set('date_from', df); params.set('date_to', dt); }
      else { params.set('date_preset', p || 'today'); }

      const [metaRes] = await Promise.all([
        authFetch(`${API_URL}/facebook/sync${activeAccountId ? `?ad_account_id=${encodeURIComponent(activeAccountId)}` : ''}`, { method: 'POST' }),
        authFetch(`${API_URL}/redtrack/sync?${params}`, { method: 'POST' }).catch(() => null),
      ]);

      if (!metaRes.ok) { const e = await metaRes.json(); throw new Error(e.detail || 'Meta sync failed'); }
      showSuccess('Sync complete');
      load(activeRange);
    } catch (e) { showError(e.message || 'Sync failed'); }
    finally { setSyncing(false); setSyncingRT(false); }
  }, [activeAccountId, activeAccountLoading, activeRange, adAccounts.length, load, showSuccess, showError]);

  const buildPerformanceParams = useCallback(() => {
    const { preset: p, dateFrom: df, dateTo: dt } = activeRange;
    const params = new URLSearchParams();
    if (activeAccountId) params.set('ad_account_id', activeAccountId);
    if (df && dt) {
      params.set('date_from', df);
      params.set('date_to', dt);
    } else {
      params.set('date_preset', p || 'today');
    }
    return params;
  }, [activeAccountId, activeRange]);

  const buildBatchGenerateUrl = useCallback((adset, topAd = null) => {
    const params = new URLSearchParams();
    if (topAd?.ad_id) {
      params.set('adId', topAd.ad_id);
      params.set('adName', topAd.ad_name || '');
    }
    params.set('adsetName', adset.name || '');
    params.set('adsetId', adset.fb_adset_id || '');
    params.set('campaignId', adset.fb_campaign_id || '');
    return `/batch-generate?${params.toString()}`;
  }, []);

  const handleQuickGenerate = useCallback(async (adset) => {
    const rowKey = adset.fb_adset_id || adset.id;
    setQuickGeneratingAdsets(prev => new Set(prev).add(rowKey));

    try {
      const params = buildPerformanceParams();
      const res = await authFetch(`${API_URL}/auto-pause/ads-bulk?${params}`);
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'Unable to load winning ad');
      }

      const adsBulk = await res.json();
      const topAd = adsBulk?.[adset.fb_adset_id]?.[0];
      navigate(buildBatchGenerateUrl(adset, topAd?.ad_id ? topAd : null));
    } catch (e) {
      showError(`${e.message || 'Quick Generate lookup failed'} - opening ad set fallback`);
      navigate(buildBatchGenerateUrl(adset));
    } finally {
      setQuickGeneratingAdsets(prev => {
        const next = new Set(prev);
        next.delete(rowKey);
        return next;
      });
    }
  }, [buildBatchGenerateUrl, buildPerformanceParams, navigate, showError]);

  const pauseAdset = useCallback(async (fb_adset_id) => {
    setPausingAdsets(prev => new Set(prev).add(fb_adset_id));
    try {
      const res = await authFetch(`${API_URL}/facebook/adsets/${fb_adset_id}/status`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: 'PAUSED' }),
      });
      if (!res.ok) { const e = await res.json(); throw new Error(e.detail || 'Failed'); }
      setPausedOverrides(prev => new Set(prev).add(fb_adset_id));
    } catch (e) {
      showError(e.message || 'Failed to pause ad set. Check your Meta connection and try again in Performance.');
    } finally {
      setPausingAdsets(prev => { const next = new Set(prev); next.delete(fb_adset_id); return next; });
    }
  }, [showError]);

  useEffect(() => {
    if (!budgetPopover) return;
    const handler = () => setBudgetPopover(null);
    document.addEventListener('click', handler);
    return () => document.removeEventListener('click', handler);
  }, [budgetPopover]);

  const saveCampaignBudget = async (fbCampaignId) => {
    const isCBO = campaignBudgetType === 'CBO';
    const dollars = parseFloat(campaignBudgetInput);
    if (isCBO && (!dollars || dollars < 1)) {
      showError('Enter a valid budget ($1 minimum)');
      return;
    }
    setSavingCampaignBudget(fbCampaignId);
    try {
      const res = await authFetch(`${API_URL}/facebook/campaigns/${fbCampaignId}/budget`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          daily_budget_cents: isCBO ? Math.round(dollars * 100) : null,
          budget_optimization: campaignBudgetType,
        }),
      });
      if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || 'Failed'); }
      showSuccess(isCBO ? `Campaign budget set to $${dollars.toFixed(0)}/day` : 'Switched to ABO');
      setBudgetPopover(null);
      load(activeRange);
    } catch (e) {
      showError(e.message || 'Failed');
    } finally {
      setSavingCampaignBudget(null);
    }
  };

  const saveAdsetBudget = async (fbAdsetId) => {
    const dollars = parseFloat(budgetInput);
    if (!dollars || dollars < 1) {
      showError('Enter a valid budget');
      return;
    }
    setSavingBudget(fbAdsetId);
    try {
      const res = await authFetch(`${API_URL}/facebook/adsets/${fbAdsetId}/budget`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ daily_budget_cents: Math.round(dollars * 100) }),
      });
      if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || 'Failed'); }
      showSuccess(`Budget set to $${dollars.toFixed(0)}/day`);
      setEditingBudget(null);
      setBudgetInput('');
      load(activeRange);
    } catch (e) {
      showError(e.message || 'Failed');
    } finally {
      setSavingBudget(null);
    }
  };

  const scaleAdset = async (a) => {
    const isCBO = a.adset.campaign_budget_optimization === 'CBO' || !!a.adset.campaign_daily_budget;
    const currentCents = isCBO
      ? a.adset.campaign_daily_budget
      : a.adset.daily_budget;

    if (!currentCents || currentCents <= 0) {
      showError('Set a budget first before scaling');
      return;
    }

    const newCents = Math.round(currentCents * 1.2);
    const scaleKey = isCBO ? `cbo-${a.fb_campaign_id}` : a.fb_adset_id;
    setScalingAdset(prev => new Set(prev).add(scaleKey));

    try {
      if (isCBO) {
        const res = await authFetch(`${API_URL}/facebook/campaigns/${a.fb_campaign_id}/budget`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ daily_budget_cents: newCents, budget_optimization: 'CBO' }),
        });
        if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || 'Failed'); }
        showSuccess(`Campaign budget scaled to $${(newCents / 100).toFixed(0)}/day (+20%)`);
      } else {
        const res = await authFetch(`${API_URL}/facebook/adsets/${a.fb_adset_id}/budget`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ daily_budget_cents: newCents }),
        });
        if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || 'Failed'); }
        showSuccess(`Ad set budget scaled to $${(newCents / 100).toFixed(0)}/day (+20%)`);
      }
      load(activeRange);
    } catch (e) {
      showError(e.message || 'Scale failed');
    } finally {
      setScalingAdset(prev => {
        const next = new Set(prev);
        next.delete(scaleKey);
        return next;
      });
    }
  };

  const askAI = async () => {
    if (!aiQuery.trim() || aiLoading) return;
    setAiLoading(true);
    setAiAnswer('');
    try {
      const res = await authFetch(`${API_URL}/ai-insights/query`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: aiQuery.trim(), ad_account_id: activeAccountId || undefined, date_preset: aiDatePreset }),
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

  // Initial load + account switcher reload
  useEffect(() => { load(activeRange); }, [load, activeRange]);

  useEffect(() => {
    if (!hasPermission('pnl:read')) {
      setPnlSummary(null);
      return;
    }
    if (activeAccountLoading || !activeAccountId) return;
    let cancelled = false;
    const loadPnl = async () => {
      setPnlLoading(true);
      try {
        const params = new URLSearchParams({
          ad_account_id: activeAccountId,
          period: 'mtd',
        });
        const res = await authFetch(`${API_URL}/pnl/summary?${params}`);
        if (!res.ok) throw new Error('Profit/Loss unavailable');
        const data = await res.json();
        if (!cancelled) setPnlSummary(data);
      } catch {
        if (!cancelled) setPnlSummary(null);
      } finally {
        if (!cancelled) setPnlLoading(false);
      }
    };
    loadPnl();
    return () => { cancelled = true; };
  }, [activeAccountId, activeAccountLoading, hasPermission]);

  function handleApply(range) {
    setActiveRange(range);
    if (range.preset) localStorage.setItem('bhm_date_preset', range.preset);
  }

  // ── Aggregate KPIs ──────────────────────────────────────────────────────────
  const rows = Object.values(bulkInsights);
  const totalSpend   = rows.reduce((s, r) => s + (r.spend || 0), 0);
  const totalLeads   = rows.reduce((s, r) => s + (r.leads || 0), 0);
  const blendedCpl   = totalLeads > 0 ? totalSpend / totalLeads : null;
  const rtRevenue    = rows.reduce((s, r) => s + (r.redtrack?.revenue || 0), 0);
  const rtConvs      = rows.reduce((s, r) => s + (r.redtrack?.conversions || 0), 0);
  const rtRoas       = totalSpend > 0 && rtRevenue > 0 ? rtRevenue / totalSpend : null;
  const isActiveDelivery = (adset) => {
    const adsetStatus = normalizeStatus(adset.status);
    const campaignStatus = normalizeStatus(adset.campaign_status);
    return adsetStatus === 'ACTIVE' && (!campaignStatus || campaignStatus === 'ACTIVE');
  };
  const activeCount  = adsets.filter(isActiveDelivery).length;
  const cplRanks = nicheSummary
    .filter(row => row.avg_cpl != null)
    .map(row => row.avg_cpl)
    .sort((a, b) => a - b);

  function formatMoney(value) {
    return value != null
      ? `$${Number(value).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
      : '—';
  }

  function formatPercent(value) {
    return value != null ? `${(Number(value) * 100).toFixed(1)}%` : '—';
  }

  function cplClass(avgCpl) {
    if (avgCpl == null || cplRanks.length < 5) return 'text-gray-500';
    const rank = cplRanks.findIndex(value => value === avgCpl);
    if (rank < Math.ceil(cplRanks.length / 3)) return 'text-green-600';
    if (rank >= Math.floor((cplRanks.length * 2) / 3)) return 'text-red-600';
    return 'text-gray-700';
  }

  // Human-readable subtitle for selected range
  const rangeLabel = activeRange.dateFrom && activeRange.dateTo
    ? `${activeRange.dateFrom} – ${activeRange.dateTo}`
    : (PRESETS.find(p => p.value === activeRange.preset)?.label ?? 'Last 7 Days');

  // ── Needs Attention ─────────────────────────────────────────────────────────
  const triggeredRules = rules.filter(r => r.triggered_at);
  const attentionMap = new Map();

  triggeredRules.forEach(r => {
    const key = `rule-${r.id}`;
    attentionMap.set(key, {
      id: key,
      label: r.adset_name || 'Ad set',
      campaignName: '',
      fb_adset_id: null,
      adset: null,
      severity: 'red',
      reasons: [{ severity: 'red', text: `Auto-paused: ${r.trigger_reason}` }],
    });
  });

  adsets
    .filter(a => isActiveDelivery(a) && a.fb_adset_id && !pausedOverrides.has(a.fb_adset_id))
    .forEach(a => {
      const ins = bulkInsights[a.fb_adset_id];
      if (!ins) return;
      const rt = ins.redtrack;
      const issues = [];

      // Ad fatigue
      if (ins.frequency >= 5) {
        issues.push({ severity: 'red', text: `Freq ${ins.frequency.toFixed(1)} — fatigue risk` });
      } else if (ins.frequency >= 3) {
        issues.push({ severity: 'orange', text: `Freq ${ins.frequency.toFixed(1)} — monitor` });
      }

      // Spend with no leads
      if (ins.spend > 50 && ins.leads === 0) {
        issues.push({ severity: 'red', text: `$${ins.spend.toFixed(0)} spent, 0 leads` });
      }

      // RT ROAS below 1x (actively losing money)
      if (rt?.roas != null && rt.roas < 1 && ins.spend > 30) {
        issues.push({ severity: 'red', text: `RT ROAS ${rt.roas.toFixed(2)}x — losing money` });
      }

      // CPL well above blended average (>1.5x) with meaningful spend
      // Skip if RT ROAS ≥ 1 — high CPL but still profitable means it doesn't need attention
      if (blendedCpl != null && ins.cpl != null && ins.cpl > blendedCpl * 1.5 && ins.spend > 30) {
        const rtRoas = rt?.roas;
        if (rtRoas == null || rtRoas < 1) {
          issues.push({ severity: 'orange', text: `CPL $${ins.cpl.toFixed(0)} — ${Math.round(ins.cpl / blendedCpl)}x avg` });
        }
      }

      if (issues.length === 0) return;

      attentionMap.set(a.fb_adset_id, {
        id: `adset-${a.id}`,
        adset: a,
        label: a.name,
        campaignName: a.campaign_name || '',
        severity: issues.some(i => i.severity === 'red') ? 'red' : 'orange',
        reasons: issues,
        fb_adset_id: a.fb_adset_id,
        fb_campaign_id: a.fb_campaign_id || '',
      });
    });

  const attentionList = Array.from(attentionMap.values()).slice(0, 8);

  // Build a Campaign Performance URL that carries the active date so the page
  // loads with the same date range the Dashboard is currently showing.
  const perfLink = (view, adsetId = '') => {
    const params = new URLSearchParams({ view });
    if (adsetId) params.set('adsetId', adsetId);
    if (dateFrom && dateTo) {
      params.set('date_from', dateFrom);
      params.set('date_to', dateTo);
    } else {
      params.set('preset', preset);
    }
    return `/campaign-performance?${params.toString()}`;
  };

  // ── Top Performers (by RT ROAS, min spend $50) ──────────────────────────────
  const topPerformers = adsets
    .filter(a => a.fb_adset_id && bulkInsights[a.fb_adset_id])
    .map(a => {
      const ins = bulkInsights[a.fb_adset_id];
      const rt  = ins?.redtrack;
      return {
        adset: a,
        id: a.id,
        name: a.name,
        campaignName: a.campaign_name || '',
        fb_adset_id: a.fb_adset_id || '',
        fb_campaign_id: a.fb_campaign_id || '',
        status: a.status,
        spend: ins?.spend || 0,
        leads: ins?.leads || 0,
        cpl: ins?.cpl,
        rtRoas: rt?.roas,
        rtCpl: rt?.cpl,
        rtConvs: rt?.conversions || 0,
        frequency: ins?.frequency ?? null,
      };
    })
    .filter(a => a.spend >= 50 && a.rtRoas != null && a.rtRoas > 0)
    .sort((a, b) => b.rtRoas - a.rtRoas)
    .slice(0, 8);

  const BudgetButton = ({ adset }) => {
    const isCBO = adset.campaign_budget_optimization === 'CBO' || !!adset.campaign_daily_budget;
    const fbCampaignId = adset.fb_campaign_id;

    if (isCBO) {
      return (
        <div className="relative" onClick={e => e.stopPropagation()}>
          <button
            onClick={() => {
              if (budgetPopover === fbCampaignId) {
                setBudgetPopover(null);
              } else {
                setBudgetPopover(fbCampaignId);
                setCampaignBudgetType('CBO');
                setCampaignBudgetInput(adset.campaign_daily_budget ? (adset.campaign_daily_budget / 100).toFixed(0) : '');
              }
            }}
            className="flex items-center gap-1 text-xs px-2 py-1 rounded-lg bg-white border border-gray-200 hover:border-indigo-300 hover:bg-indigo-50 text-gray-600 hover:text-indigo-700 transition-colors shadow-sm font-medium"
          >
            <DollarSign size={11} />
            {adset.campaign_daily_budget ? (
              <span className="flex flex-col items-end leading-tight">
                <span>${(adset.campaign_daily_budget / 100).toFixed(0)}/day</span>
                <span className="text-[9px] font-semibold text-blue-500 bg-blue-50 px-1 rounded">campaign</span>
              </span>
            ) : 'CBO'}
          </button>

          {budgetPopover === fbCampaignId && (
            <div
              className="absolute right-0 top-9 w-64 bg-white rounded-xl border border-gray-200 shadow-lg p-4 z-50 text-left"
              onClick={e => e.stopPropagation()}
            >
              <div className="text-xs font-semibold text-gray-700 mb-3">Campaign Budget Settings</div>
              <div className="mb-3">
                <div className="text-[10px] text-gray-400 uppercase tracking-wide mb-1">Daily Budget</div>
                <div className="flex items-center gap-1.5 border border-gray-200 rounded-lg px-2.5 py-1.5 focus-within:ring-1 focus-within:ring-indigo-400">
                  <span className="text-gray-400 text-xs">$</span>
                  <input
                    type="number"
                    min="1"
                    step="1"
                    value={campaignBudgetInput}
                    onChange={e => setCampaignBudgetInput(e.target.value)}
                    onKeyDown={e => {
                      if (e.key === 'Enter') saveCampaignBudget(fbCampaignId);
                      if (e.key === 'Escape') setBudgetPopover(null);
                    }}
                    placeholder="e.g. 500"
                    className="flex-1 text-sm font-semibold focus:outline-none text-gray-800 w-full"
                    autoFocus
                  />
                  <span className="text-gray-400 text-xs">/day</span>
                </div>
              </div>
              <div className="flex gap-2">
                <button
                  onClick={() => setBudgetPopover(null)}
                  className="flex-1 py-1.5 text-xs rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50"
                >
                  Cancel
                </button>
                <button
                  onClick={() => saveCampaignBudget(fbCampaignId)}
                  disabled={savingCampaignBudget === fbCampaignId}
                  className="flex-1 py-1.5 text-xs rounded-lg bg-indigo-600 text-white font-semibold hover:bg-indigo-700 disabled:opacity-50"
                >
                  {savingCampaignBudget === fbCampaignId ? 'Saving...' : 'Save'}
                </button>
              </div>
            </div>
          )}
        </div>
      );
    }

    if (editingBudget === adset.fb_adset_id) {
      return (
        <div className="flex items-center gap-1" onClick={e => e.stopPropagation()}>
          <span className="text-xs text-gray-400">$</span>
          <input
            type="number"
            min="1"
            step="1"
            value={budgetInput}
            onChange={e => setBudgetInput(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter') saveAdsetBudget(adset.fb_adset_id);
              if (e.key === 'Escape') { setEditingBudget(null); setBudgetInput(''); }
            }}
            className="w-20 text-xs border border-gray-200 rounded px-1.5 py-0.5 focus:outline-none focus:ring-1 focus:ring-indigo-400"
            autoFocus
          />
          <span className="text-xs text-gray-400">/day</span>
          <button
            onClick={() => saveAdsetBudget(adset.fb_adset_id)}
            disabled={savingBudget === adset.fb_adset_id}
            className="text-green-600 hover:text-green-700 disabled:opacity-40 text-xs"
          >
            ✓
          </button>
          <button
            onClick={() => { setEditingBudget(null); setBudgetInput(''); }}
            className="text-gray-400 hover:text-gray-600 text-xs"
          >
            ×
          </button>
        </div>
      );
    }

    return (
      <button
        onClick={e => {
          e.stopPropagation();
          setEditingBudget(adset.fb_adset_id);
          setBudgetInput(adset.daily_budget ? String(Math.round(adset.daily_budget / 100)) : '');
        }}
        className="flex items-center gap-1 text-xs px-2 py-1 rounded-lg bg-white border border-gray-200 hover:border-indigo-300 hover:bg-indigo-50 text-gray-600 hover:text-indigo-700 transition-colors shadow-sm font-medium"
      >
        <DollarSign size={11} />
        {adset.daily_budget ? `$${Math.round(adset.daily_budget / 100)}/day` : 'Set budget'}
      </button>
    );
  };

  const visibleTopPerformers = expandedSections.topPerformers ? topPerformers : topPerformers.slice(0, 10);
  const visibleAttentionList = expandedSections.needsAttention ? attentionList : attentionList.slice(0, 10);
  const visibleNicheSummary = expandedSections.nicheSummary ? nicheSummary : nicheSummary.slice(0, 10);

  return (
    <div className="max-w-7xl mx-auto space-y-8">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Dashboard</h1>
          <p className="text-gray-500 text-sm mt-0.5">{rangeLabel} · {activeCount} active ad sets</p>
        </div>
        <div className="flex items-center gap-2">
          <DateFilter
            preset={preset}
            setPreset={setPreset}
            dateFrom={dateFrom}
            setDateFrom={setDateFrom}
            dateTo={dateTo}
            setDateTo={setDateTo}
            onApply={handleApply}
          />
          <button
            onClick={syncAll}
            disabled={syncing || syncingRT || loading}
            className="flex items-center gap-2 px-3 py-2 rounded-lg text-sm text-gray-600 border border-gray-200 hover:bg-gray-50 transition-colors disabled:opacity-40"
            title="Pull latest campaign data from Meta and revenue data from RedTrack"
          >
            <RefreshCw size={13} className={(syncing || syncingRT) ? 'animate-spin' : ''} />
            Sync
          </button>
          <button
            onClick={() => load(activeRange)}
            disabled={loading}
            className="flex items-center gap-2 px-3 py-2 rounded-lg text-sm text-gray-500 border border-gray-200 hover:bg-gray-50 transition-colors disabled:opacity-40"
          >
            <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
            Refresh
          </button>
        </div>
      </div>

      {hasPermission('pnl:read') && (pnlSummary || pnlLoading) && (
        <Link
          to="/pnl"
          className="block rounded-xl border border-green-100 bg-white p-4 shadow-sm transition-colors hover:border-green-200 hover:bg-green-50/30"
        >
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <div>
              <div className="flex items-center gap-2 text-sm font-semibold text-gray-900">
                <DollarSign size={15} className="text-green-600" />
                Running Profit/Loss
              </div>
              <div className="mt-0.5 text-xs text-gray-400">
                {pnlSummary ? `MTD · ${pnlSummary.date_from} – ${pnlSummary.date_to}` : 'Loading month-to-date profit view'}
              </div>
            </div>
            <div className="flex items-center gap-1 text-xs font-medium text-green-700">
              View full Profit/Loss <ArrowRight size={12} />
            </div>
          </div>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
            {[
              ['Ad Spend', pnlLoading ? '—' : formatMoney(pnlSummary?.spend), 'Meta'],
              ['Billable Revenue', pnlLoading ? '—' : formatMoney(pnlSummary?.revenue), pnlRevenueSourceLabel(pnlSummary?.revenue_source)],
              ['Other Costs', pnlLoading ? '—' : formatMoney(pnlSummary?.other_costs), pnlSummary?.has_costs ? `${pnlSummary.costs?.length || 0} entries` : 'Gross'],
              ['Net Profit', pnlLoading ? '—' : formatMoney(pnlSummary?.net_profit), pnlSummary?.data_incomplete ? 'Incomplete' : pnlSummary?.has_costs ? 'Net' : 'Gross'],
              ['Margin', pnlLoading ? '—' : formatPercent(pnlSummary?.margin), 'net ÷ revenue'],
            ].map(([label, value, caption]) => {
              const isNet = label === 'Net Profit';
              const tone = isNet && !pnlSummary?.data_incomplete && pnlSummary?.has_costs && pnlSummary?.net_profit > 0
                ? 'text-green-600'
                : isNet && !pnlSummary?.data_incomplete && pnlSummary?.has_costs && pnlSummary?.net_profit < 0
                  ? 'text-red-600'
                  : 'text-gray-900';
              return (
                <div key={label} className="rounded-lg border border-gray-100 bg-gray-50 px-3 py-3">
                  <div className="text-[10px] font-semibold uppercase tracking-wide text-gray-500">{label}</div>
                  <div className={`mt-1 text-lg font-bold ${tone}`}>{value}</div>
                  <div className="mt-0.5 text-[11px] text-gray-400">{caption}</div>
                </div>
              );
            })}
          </div>
        </Link>
      )}

      {/* Insights error banner */}
      {insightsError && !loading && (
        <div className="flex items-center gap-2 px-4 py-3 rounded-xl bg-red-50 border border-red-200 text-sm text-red-700">
          <AlertTriangle size={14} className="flex-shrink-0" />
          {insightsError}
        </div>
      )}

      {/* Ask AI */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
        <div className="flex items-center gap-2 px-5 pt-4 pb-3 border-b border-gray-100">
          <Sparkles size={15} className="text-violet-500" />
          <span className="text-sm font-semibold text-gray-900">Ask AI</span>
          <span className="hidden sm:inline text-xs font-normal text-gray-400">powered by Claude + live Meta data</span>
        </div>
        <div className="px-5 pb-5 pt-3">
            <div className="flex gap-2 mb-2">
              {[
                { value: 'yesterday', label: 'Yesterday' },
                { value: 'last_3d',   label: 'Last 3 Days' },
                { value: 'last_7d',   label: 'Last 7 Days' },
                { value: 'last_30d',  label: 'Last 30 Days' },
                { value: 'this_month', label: 'MTD' },
              ].map(p => (
                <button
                  key={p.value}
                  onClick={() => setAiDatePreset(p.value)}
                  className={`text-xs px-2.5 py-1 rounded-full border transition-colors ${
                    aiDatePreset === p.value
                      ? 'border-violet-400 bg-violet-50 text-violet-700 font-medium'
                      : 'border-gray-200 text-gray-500 hover:border-violet-300 hover:text-violet-600'
                  }`}
                >
                  {p.label}
                </button>
              ))}
            </div>
            <div className="flex gap-2">
              <input
                type="text"
                value={aiQuery}
                onChange={e => setAiQuery(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && askAI()}
                placeholder="e.g. What are my worst performing ad sets this week?"
                className="flex-1 text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-violet-400 focus:border-transparent"
                disabled={aiLoading}
              />
              <button
                onClick={askAI}
                disabled={aiLoading || !aiQuery.trim()}
                className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium text-white bg-violet-600 hover:bg-violet-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex-shrink-0"
              >
                {aiLoading
                  ? <><RefreshCw size={13} className="animate-spin" /> Thinking...</>
                  : <><Send size={13} /> Ask</>
                }
              </button>
            </div>
            {!aiAnswer && !aiLoading && (
              <div className="mt-2">
                <button
                  onClick={() => setShowAiExamples(v => !v)}
                  className="text-xs text-gray-400 hover:text-violet-600 transition-colors flex items-center gap-1"
                >
                  Examples {showAiExamples ? '▴' : '▾'}
                </button>
                {showAiExamples && (
                  <div className="mt-2 flex flex-wrap gap-2">
                    {[
                      'What are my worst ad sets today?',
                      'Which creatives have the highest CPL?',
                      'Show me frequency issues across all campaigns',
                      'Any pixel or tracking problems I should know about?',
                    ].map(q => (
                      <button
                        key={q}
                        onClick={() => { setAiQuery(q); setShowAiExamples(false); }}
                        className="text-xs px-2.5 py-1 rounded-full border border-gray-200 text-gray-500 hover:border-violet-300 hover:text-violet-600 transition-colors"
                      >
                        {q}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}
            {aiAnswer && (
              <div className="mt-3 p-4 bg-gray-50 rounded-lg border border-gray-100">
                <div className="flex items-start gap-2">
                  <MessageSquare size={14} className="text-violet-400 flex-shrink-0 mt-0.5" />
                  <MarkdownAnswer text={aiAnswer} />
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

      {/* KPI Row */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4">
        <KpiCard
          label="Total Spend"
          value={loading ? '—' : `$${totalSpend.toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`}
          sub="Meta · ad spend"
        />
        <KpiCard
          label="Total Leads"
          value={loading ? '—' : totalLeads.toLocaleString()}
          sub="Meta attribution"
        />
        <KpiCard
          label="Blended CPL"
          value={loading ? '—' : blendedCpl != null ? `$${blendedCpl.toFixed(2)}` : '—'}
          sub="spend ÷ leads"
          highlight={blendedCpl != null && blendedCpl > 60}
          warn={blendedCpl != null && blendedCpl > 40 && blendedCpl <= 60}
        />
        <KpiCard
          label="RT Revenue"
          value={loading ? '—' : rtRevenue > 0 ? `$${rtRevenue.toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}` : '—'}
          sub={rtConvs > 0 ? `RT · ${rtConvs} conversions` : 'RedTrack · awaiting sync'}
        />
        <KpiCard
          label="RT ROAS"
          value={loading ? '—' : rtRoas != null ? `${rtRoas.toFixed(2)}x` : '—'}
          sub="revenue ÷ spend"
          highlight={rtRoas != null && rtRoas < 1}
          warn={rtRoas != null && rtRoas >= 1 && rtRoas < 1.5}
        />
      </div>

      <div className="space-y-4">
        {/* Top Performers */}
        <div className="bg-white rounded-xl border border-green-100 border-l-4 border-l-green-500 shadow-sm overflow-hidden">
          <div className="px-5 py-3 border-b border-green-100 bg-green-50/40 flex items-center justify-between gap-3">
            <button
              type="button"
              onClick={() => toggleSection('topPerformers')}
              className="min-w-0 font-semibold text-gray-900 flex items-center gap-2 text-sm text-left"
            >
              <ChevronDown size={15} className={`text-green-600 transition-transform ${collapsedSections.topPerformers ? '-rotate-90' : ''}`} />
              <TrendingUp size={15} className="text-green-600" />
              <span>Top Performers</span>
              <span className="text-xs text-gray-500 font-normal">by RT ROAS · has spend</span>
            </button>
            <Link to={perfLink('top-performers')} className="text-xs text-green-700 hover:underline flex items-center gap-1 flex-shrink-0">
              View all in Performance <ArrowRight size={11} />
            </Link>
          </div>
          {!collapsedSections.topPerformers && (loading ? (
            <div className="px-5 py-6 text-center text-sm text-gray-400">Loading...</div>
          ) : topPerformers.length === 0 ? (
            <div className="px-5 py-6 text-center text-sm text-gray-400">
              No RT data yet — sync RedTrack from the Performance page.
            </div>
          ) : (
            <div className="overflow-x-auto">
              {topPerformers.some(a => a.adset.campaign_budget_optimization === 'CBO' || !!a.adset.campaign_daily_budget) && (
                <div className="px-5 py-2 bg-blue-50 border-b border-blue-100 text-[11px] text-blue-600">
                  All budgets are campaign-level (CBO) &mdash; +20% scales the full campaign, not just this ad set.
                </div>
              )}
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-[11px] font-semibold uppercase tracking-wide text-gray-400 border-b border-gray-100">
                    <th className="px-5 py-2 text-left">Ad Set</th>
                    <th className="px-3 py-2 text-right">Spend</th>
                    <th className="px-3 py-2 text-right">CPL</th>
                    <th className="px-3 py-2 text-right">RT ROAS</th>
                    <th className="px-3 py-2 text-right">Freq</th>
                    <th className="px-3 py-2 text-left">Budget</th>
                    <th className="px-3 py-2 text-left">Action</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-50">
                  {visibleTopPerformers.map(a => (
                    <tr key={a.id} className="hover:bg-gray-50 transition-colors">
                      <td className="px-5 py-3">
                        <Link to={perfLink('top-performers', a.fb_adset_id)} className="block">
                          <div className="font-medium text-gray-900 truncate max-w-[280px]" title={a.name}>
                            {a.name}
                          </div>
                          {a.campaignName && (
                            <div className="text-xs text-gray-400 truncate max-w-[280px]">{a.campaignName}</div>
                          )}
                        </Link>
                      </td>
                      <td className="px-3 py-3 text-right font-medium text-gray-800">${a.spend.toFixed(0)}</td>
                      <td className="px-3 py-3 text-right text-gray-600">{a.rtCpl != null ? `$${a.rtCpl.toFixed(2)}` : '—'}</td>
                      <td className="px-3 py-3 text-right font-bold text-green-600">{a.rtRoas.toFixed(2)}x</td>
                      <td className="px-3 py-3 text-right text-xs font-medium">
                        {a.frequency != null ? (
                          <span className={
                            a.frequency >= 4 ? 'text-red-600'
                              : a.frequency >= 2.5 ? 'text-orange-500'
                                : 'text-gray-400'
                          }>
                            {a.frequency.toFixed(1)}
                          </span>
                        ) : <span className="text-gray-300">—</span>}
                      </td>
                      <td className="px-3 py-3"><BudgetButton adset={a.adset} /></td>
                      <td className="px-3 py-3">
                        <div className="flex items-center gap-1.5">
                          {(() => {
                            const isCBO = a.adset.campaign_budget_optimization === 'CBO' || !!a.adset.campaign_daily_budget;
                            const hasBudget = isCBO ? !!a.adset.campaign_daily_budget : !!a.adset.daily_budget;
                            const scaleKey = isCBO ? `cbo-${a.fb_campaign_id}` : a.fb_adset_id;
                            const isScaling = scalingAdset.has(scaleKey);
                            return (
                              <button
                                onClick={() => scaleAdset(a)}
                                disabled={isScaling || !hasBudget}
                                title={hasBudget ? (isCBO ? '+20% campaign budget - affects all ad sets in this campaign' : '+20% ad set budget') : 'Set budget first'}
                                className="flex items-center gap-1 px-2 py-1 rounded-lg text-xs font-medium text-green-700 border border-green-200 bg-green-50 hover:bg-green-100 transition-colors disabled:opacity-40"
                              >
                                {isScaling ? <RefreshCw size={11} className="animate-spin" /> : '+20%'}
                              </button>
                            );
                          })()}
                          <button
                            onClick={() => handleQuickGenerate(a)}
                            disabled={quickGeneratingAdsets.has(a.fb_adset_id || a.id)}
                            className="flex items-center gap-1 px-2 py-1 rounded-lg text-xs font-medium text-indigo-600 border border-indigo-100 bg-indigo-50 hover:bg-indigo-100 transition-colors disabled:opacity-40"
                          >
                            {quickGeneratingAdsets.has(a.fb_adset_id || a.id)
                              ? <RefreshCw size={11} className="animate-spin" />
                              : <Zap size={11} />
                            }
                            Quick Generate
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {topPerformers.length > 10 && (
                <div className="px-5 py-3 border-t border-gray-100 bg-white">
                  <button
                    type="button"
                    onClick={() => toggleExpandedSection('topPerformers')}
                    className="text-xs font-semibold text-green-700 hover:text-green-800"
                  >
                    {expandedSections.topPerformers ? 'Show top 10' : `See all ${topPerformers.length}`}
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>

        {/* Needs Attention */}
        <div className="bg-white rounded-xl border border-orange-100 border-l-4 border-l-orange-500 shadow-sm overflow-hidden">
          <div className="px-5 py-3 border-b border-orange-100 bg-orange-50/50 flex items-center justify-between gap-3">
            <button
              type="button"
              onClick={() => toggleSection('needsAttention')}
              className="min-w-0 font-semibold text-gray-900 flex items-center gap-2 text-sm text-left"
            >
              <ChevronDown size={15} className={`text-orange-600 transition-transform ${collapsedSections.needsAttention ? '-rotate-90' : ''}`} />
              <AlertTriangle size={15} className="text-orange-600" />
              <span>Needs Attention</span>
            </button>
            <Link to={perfLink('attention')} className="text-xs text-orange-700 hover:underline flex items-center gap-1 flex-shrink-0">
              View all in Performance <ArrowRight size={11} />
            </Link>
          </div>
          {!collapsedSections.needsAttention && (loading ? (
            <div className="px-5 py-6 text-center text-sm text-gray-400">Loading...</div>
          ) : attentionList.length === 0 ? (
            <div className="px-5 py-6 text-center text-sm text-gray-400">
              <span className="text-green-500 font-medium">All clear</span> — no issues flagged.
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-[11px] font-semibold uppercase tracking-wide text-gray-400 border-b border-gray-100">
                    <th className="px-5 py-2 text-left">Ad Set</th>
                    <th className="px-3 py-2 text-left">Issue</th>
                    <th className="px-3 py-2 text-right">Spend</th>
                    <th className="px-3 py-2 text-right">CPL</th>
                    <th className="px-3 py-2 text-left">Budget</th>
                    <th className="px-3 py-2 text-left">Action</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-50">
                  {visibleAttentionList.map(item => {
                    const isPausing = item.fb_adset_id && pausingAdsets.has(item.fb_adset_id);
                    const ins = bulkInsights[item.fb_adset_id] || {};
                    return (
                      <tr key={item.id} className="hover:bg-gray-50 transition-colors">
                        <td className="px-5 py-3">
                          <Link to={perfLink('attention', item.fb_adset_id)} className="block">
                            <div className="flex items-center gap-2">
                              <div className={`w-2 h-2 rounded-full flex-shrink-0 ${item.severity === 'red' ? 'bg-red-500' : 'bg-orange-400'}`} />
                              <div className="font-medium text-gray-900 truncate max-w-[260px]" title={item.label}>{item.label}</div>
                            </div>
                            {item.campaignName && (
                              <div className="text-xs text-gray-400 truncate max-w-[260px] pl-4">{item.campaignName}</div>
                            )}
                          </Link>
                        </td>
                        <td className="px-3 py-3">
                          <div className="flex flex-col gap-0.5">
                            {item.reasons.map((r, i) => (
                              <span key={i} className={`text-xs ${r.severity === 'red' ? 'text-red-600' : 'text-orange-500'}`}>
                                {r.text}
                              </span>
                            ))}
                          </div>
                        </td>
                        <td className="px-3 py-3 text-right font-medium text-gray-800">{ins.spend != null ? `$${ins.spend.toFixed(0)}` : '—'}</td>
                        <td className="px-3 py-3 text-right text-red-600 font-semibold">{ins.cpl != null ? `$${ins.cpl.toFixed(2)}` : '—'}</td>
                        <td className="px-3 py-3">{item.adset && <BudgetButton adset={item.adset} />}</td>
                        <td className="px-3 py-3">
                          {item.fb_adset_id && (
                            <button
                              onClick={() => pauseAdset(item.fb_adset_id)}
                              disabled={isPausing}
                              className="flex items-center gap-1 px-2 py-1 rounded-lg text-xs font-medium text-gray-500 border border-gray-200 hover:bg-red-50 hover:text-red-600 hover:border-red-200 transition-colors disabled:opacity-40"
                            >
                              {isPausing ? <RefreshCw size={11} className="animate-spin" /> : <PauseCircle size={11} />}
                              Pause
                            </button>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              {attentionList.length > 10 && (
                <div className="px-5 py-3 border-t border-gray-100 bg-white">
                  <button
                    type="button"
                    onClick={() => toggleExpandedSection('needsAttention')}
                    className="text-xs font-semibold text-orange-700 hover:text-orange-800"
                  >
                    {expandedSections.needsAttention ? 'Show top 10' : `See all ${attentionList.length}`}
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Performance by Niche */}
      <div className="bg-white rounded-xl border border-blue-100 border-l-4 border-l-blue-500 shadow-sm overflow-hidden">
        <div className="px-5 py-4 border-b border-blue-100 bg-blue-50/40 flex items-center justify-between gap-3">
          <button
            type="button"
            onClick={() => toggleSection('nicheSummary')}
            className="min-w-0 font-semibold text-gray-900 flex items-center gap-2 text-sm text-left"
          >
            <ChevronDown size={15} className={`text-blue-600 transition-transform ${collapsedSections.nicheSummary ? '-rotate-90' : ''}`} />
            <TrendingUp size={15} className="text-blue-600" />
            <span>Performance by Niche</span>
          </button>
          <span className="text-xs text-gray-500 flex-shrink-0">{rangeLabel}</span>
        </div>
        {!collapsedSections.nicheSummary && (loading ? (
          <div className="p-5 space-y-3">
            {[0, 1, 2].map(row => (
              <div key={row} className="grid grid-cols-8 gap-4 items-center">
                <div className="col-span-2 h-4 rounded bg-gray-100 animate-pulse" />
                <div className="h-4 rounded bg-gray-100 animate-pulse" />
                <div className="h-4 rounded bg-gray-100 animate-pulse" />
                <div className="h-4 rounded bg-gray-100 animate-pulse" />
                <div className="h-4 rounded bg-gray-100 animate-pulse" />
                <div className="h-4 rounded bg-gray-100 animate-pulse" />
                <div className="h-4 rounded bg-gray-100 animate-pulse" />
              </div>
            ))}
          </div>
        ) : nicheSummary.length === 0 ? (
          <div className="px-5 py-8 text-center text-sm text-gray-400">
            No niche data available for this period.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 border-b border-gray-100">
                <tr className="text-left text-xs font-medium text-gray-500 uppercase tracking-wide">
                  <th className="px-5 py-3">Niche</th>
                  <th className="px-5 py-3 text-right">Ad Sets</th>
                  <th className="px-5 py-3 text-right">Spend</th>
                  <th className="px-5 py-3 text-right">Revenue</th>
                  <th className="px-5 py-3 text-right">Profit</th>
                  <th className="px-5 py-3 text-right">ROAS</th>
                  <th className="px-5 py-3 text-right">CPL</th>
                  <th className="px-5 py-3 text-right">Leads</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {visibleNicheSummary.map(row => (
                  <tr key={row.niche} className="hover:bg-gray-50 transition-colors">
                    <td className="px-5 py-3 font-medium text-gray-900">{row.niche}</td>
                    <td className="px-5 py-3 text-right text-gray-500">{row.adset_count}</td>
                    <td className="px-5 py-3 text-right text-gray-700">{formatMoney(row.total_spend)}</td>
                    <td className="px-5 py-3 text-right text-gray-700">
                      {row.total_revenue > 0 ? formatMoney(row.total_revenue) : '—'}
                    </td>
                    <td className={`px-5 py-3 text-right font-semibold ${
                      row.total_revenue === 0 ? 'text-gray-400'
                      : (row.total_revenue - row.total_spend) >= 0 ? 'text-green-600'
                      : 'text-red-600'
                    }`}>
                      {row.total_revenue > 0
                        ? formatMoney(row.total_revenue - row.total_spend)
                        : '—'}
                    </td>
                    <td className={`px-5 py-3 text-right font-semibold ${
                      row.avg_roas == null ? 'text-gray-400'
                      : row.avg_roas >= 2 ? 'text-green-600'
                      : row.avg_roas >= 1 ? 'text-gray-700'
                      : 'text-red-600'
                    }`}>
                      {row.avg_roas != null ? `${row.avg_roas.toFixed(1)}x` : '—'}
                    </td>
                    <td className={`px-5 py-3 text-right font-semibold ${cplClass(row.avg_cpl)}`}>
                      {formatMoney(row.avg_cpl)}
                    </td>
                    <td className="px-5 py-3 text-right text-gray-700">
                      {row.total_leads != null ? row.total_leads : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {nicheSummary.length > 10 && (
              <div className="px-5 py-3 border-t border-gray-100 bg-white">
                <button
                  type="button"
                  onClick={() => toggleExpandedSection('nicheSummary')}
                  className="text-xs font-semibold text-blue-700 hover:text-blue-800"
                >
                  {expandedSections.nicheSummary ? 'Show top 10' : `See all ${nicheSummary.length}`}
                </button>
              </div>
            )}
          </div>
        ))}
      </div>

    </div>
  );
}
