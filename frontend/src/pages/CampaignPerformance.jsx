import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { PauseCircle, PlayCircle, Trash2, Plus, RefreshCw, AlertTriangle, CheckCircle, TrendingDown, DollarSign, Target, Zap, ChevronDown, ChevronRight, TrendingUp, X } from 'lucide-react';
import { useToast } from '../context/ToastContext';
import { useSearchParams } from 'react-router-dom';
import { authFetch } from '../lib/facebookApi';

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1';

const METRIC_LABELS = { cpl: 'Cost Per Lead', cpa: 'Cost Per Action', ctr: 'CTR', roas: 'ROAS' };
const METRIC_UNITS  = { cpl: '$', cpa: '$', ctr: '%', roas: 'x' };
const DATE_PRESETS  = [
  { value: 'today',       label: 'Today' },
  { value: 'yesterday',   label: 'Yesterday' },
  { value: 'last_7d',     label: 'Last 7 Days' },
  { value: 'last_14d',    label: 'Last 14 Days' },
  { value: 'last_30d',    label: 'Last 30 Days' },
];

// ── Inline insights card for one ad set ──────────────────────────────────────
// Now receives pre-loaded `data` from the parent's bulk fetch.
// Falls back to an individual fetch only if bulk data is not yet available.
function InsightsCard({ fbAdsetId, adsetName, adAccountId, datePreset, bulkData, bulkLoading, bulkError }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // Individual fetch only fires as fallback if bulk explicitly errored out
  const needsIndividualFetch = !!bulkError && !!fbAdsetId;

  const load = useCallback(async () => {
    if (!needsIndividualFetch) return;
    setLoading(true); setError(null);
    try {
      const params = new URLSearchParams({ date_preset: datePreset });
      if (adAccountId) params.set('ad_account_id', adAccountId);
      const res = await authFetch(`${API_BASE}/auto-pause/insights/${fbAdsetId}?${params}`);
      if (!res.ok) { const e = await res.json(); throw new Error(e.detail || 'Failed'); }
      setData(await res.json());
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  }, [fbAdsetId, datePreset, adAccountId, needsIndividualFetch]);

  useEffect(() => { load(); }, [load]);

  // Prefer bulk data; fall back to individual fetch result
  const resolvedData = (bulkData && fbAdsetId && bulkData[fbAdsetId]) || data;
  const resolvedLoading = needsIndividualFetch ? loading : bulkLoading;
  const resolvedError = needsIndividualFetch ? error : (bulkError && !data ? bulkError : null);

  if (!fbAdsetId) return <span className="text-xs text-gray-400 italic">Not launched yet</span>;
  if (resolvedLoading) return <span className="text-xs text-gray-400 animate-pulse">Loading...</span>;
  if (resolvedError) return <span className="text-xs text-red-500">{resolvedError}</span>;
  if (!resolvedData) return null;

  const d = resolvedData;
  const rt = d.redtrack;

  return (
    <div className="space-y-2 text-sm">
      {/* Meta Insights row */}
      <div className="flex flex-wrap gap-x-5 gap-y-2">
        <span className="text-xs font-semibold text-gray-400 uppercase tracking-wide self-center w-8">Meta</span>
        <Stat label="Spend"       value={`$${d.spend.toFixed(2)}`} />
        <Stat label="Leads"       value={d.leads} />
        <Stat label="CPL"         value={d.cpl != null ? `$${d.cpl.toFixed(2)}` : '—'} highlight={d.cpl > 60} />
        <Stat label="Reach"       value={d.reach.toLocaleString()} />
        <Stat label="Frequency"   value={d.frequency.toFixed(2)} highlight={d.frequency >= 5} warn={d.frequency >= 3 && d.frequency < 5} />
        <Stat label="Impressions" value={d.impressions.toLocaleString()} />
        <Stat label="Clicks"      value={d.clicks.toLocaleString()} />
        <Stat label="CTR"         value={`${parseFloat(d.ctr).toFixed(2)}%`} />
        {d.roas != null && !rt && (
          <Stat label="ROAS" value={`${d.roas.toFixed(2)}x`} highlight={d.roas < 1} />
        )}
      </div>

      {/* RedTrack row — only renders when cache data is available */}
      {rt ? (
        <div className="flex flex-wrap gap-x-5 gap-y-2 bg-blue-50 rounded-lg px-3 py-2">
          <span className="text-xs font-semibold text-blue-500 uppercase tracking-wide self-center w-8">RT</span>
          <RTStat label="Convs"   value={rt.conversions} />
          <RTStat label="Revenue" value={rt.revenue != null ? `$${rt.revenue.toFixed(2)}` : '—'} />
          <RTStat label="ROAS"    value={rt.roas != null ? `${rt.roas.toFixed(2)}x` : '—'} highlight={rt.roas != null && rt.roas < 1} />
          <RTStat label="RT CPL"  value={rt.cpl != null ? `$${rt.cpl.toFixed(2)}` : '—'} highlight={rt.cpl != null && rt.cpl > 60} />
          <RTStat
            label="Quality"
            value={rt.quality_rate != null ? `${(rt.quality_rate * 100).toFixed(0)}%` : d.leads > 0 ? `${((rt.conversions / d.leads) * 100).toFixed(0)}%` : '—'}
            highlight={rt.quality_rate != null && rt.quality_rate < 0.5}
          />
          <RTStat label="Profit"  value={rt.profit != null ? `$${rt.profit.toFixed(2)}` : '—'} highlight={rt.profit != null && rt.profit < 0} />
        </div>
      ) : (
        <div className="flex items-center gap-1.5 text-xs text-gray-400 pl-10">
          <span className="w-2 h-2 rounded-full bg-gray-200 inline-block" />
          RedTrack data syncs every 30 min — check back shortly
        </div>
      )}
    </div>
  );
}

function Stat({ label, value, highlight, warn }) {
  return (
    <div className="flex flex-col">
      <span className="text-xs text-gray-500">{label}</span>
      <span className={`font-semibold ${highlight ? 'text-red-600' : warn ? 'text-orange-500' : 'text-gray-900'}`}>{value}</span>
    </div>
  );
}

function RTStat({ label, value, highlight }) {
  return (
    <div className="flex flex-col">
      <span className="text-xs text-blue-400">{label}</span>
      <span className={`font-semibold ${highlight ? 'text-red-600' : 'text-blue-700'}`}>{value}</span>
    </div>
  );
}

// ── Creative breakdown table (ad-level) ──────────────────────────────────────
function AdsBreakdown({ fbAdsetId, adsBulk, adsLoading, rtAdsBulk }) {
  if (adsLoading) return (
    <div className="mt-3 pl-10 text-xs text-gray-400 animate-pulse">Loading creatives...</div>
  );

  const ads = adsBulk?.[fbAdsetId];
  if (!ads || ads.length === 0) return (
    <div className="mt-3 pl-10 text-xs text-gray-400 italic">No ad-level data for this period.</div>
  );

  const maxSpend = Math.max(...ads.map(a => a.spend), 0.01);

  return (
    <div className="mt-3 rounded-lg border border-gray-100 overflow-hidden">
      <table className="w-full text-xs">
        <thead>
          <tr className="bg-gray-50 border-b border-gray-100">
            <th className="text-left px-3 py-2 font-medium text-gray-500 w-1/3">Creative</th>
            <th className="text-right px-3 py-2 font-medium text-gray-500">Spend</th>
            <th className="text-right px-3 py-2 font-medium text-gray-500">Leads</th>
            <th className="text-right px-3 py-2 font-medium text-gray-500">CPL</th>
            <th className="text-right px-3 py-2 font-medium text-gray-500">CTR</th>
            <th className="text-right px-3 py-2 font-medium text-gray-500">Impr.</th>
            {ads.some(a => a.roas != null) && (
              <th className="text-right px-3 py-2 font-medium text-gray-500">ROAS</th>
            )}
            {rtAdsBulk && (
              <>
                <th className="text-right px-3 py-2 font-medium text-blue-400">RT Convs</th>
                <th className="text-right px-3 py-2 font-medium text-blue-400">RT CPL</th>
                <th className="text-right px-3 py-2 font-medium text-blue-400">RT ROAS</th>
              </>
            )}
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-50">
          {ads.map((ad, i) => {
            const rt = rtAdsBulk?.[ad.ad_id];
            const isTop = i === 0 && ads.length > 1 && ad.spend > 0;
            const isWorse = ad.cpl != null && ads.some(a => a.cpl != null && a.cpl < ad.cpl * 0.7);
            const spendPct = maxSpend > 0 ? (ad.spend / maxSpend) * 100 : 0;

            return (
              <tr key={ad.ad_id} className={`${isTop ? 'bg-green-50/40' : ''} hover:bg-gray-50/60 transition-colors`}>
                <td className="px-3 py-2">
                  <div className="flex items-center gap-2">
                    {isTop && <span className="text-green-600 text-xs font-bold">↑</span>}
                    <div>
                      <div className="font-medium text-gray-800 leading-tight truncate max-w-[200px]" title={ad.ad_name}>
                        {ad.ad_name || ad.ad_id}
                      </div>
                      {/* Spend bar */}
                      <div className="mt-1 h-1 bg-gray-100 rounded-full w-24">
                        <div
                          className="h-1 rounded-full bg-indigo-400"
                          style={{ width: `${spendPct}%` }}
                        />
                      </div>
                    </div>
                  </div>
                </td>
                <td className="px-3 py-2 text-right font-medium text-gray-700">${ad.spend.toFixed(0)}</td>
                <td className="px-3 py-2 text-right text-gray-700">{ad.leads}</td>
                <td className={`px-3 py-2 text-right font-medium ${ad.cpl != null && ad.cpl > 60 ? 'text-red-600' : 'text-gray-700'}`}>
                  {ad.cpl != null ? `$${ad.cpl.toFixed(2)}` : '—'}
                </td>
                <td className="px-3 py-2 text-right text-gray-600">{parseFloat(ad.ctr).toFixed(2)}%</td>
                <td className="px-3 py-2 text-right text-gray-500">{ad.impressions.toLocaleString()}</td>
                {ads.some(a => a.roas != null) && (
                  <td className={`px-3 py-2 text-right font-medium ${ad.roas != null && ad.roas < 1 ? 'text-red-600' : 'text-gray-700'}`}>
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
              </tr>
            );
          })}
        </tbody>
      </table>
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

// ── Main page ─────────────────────────────────────────────────────────────────
export default function CampaignPerformance() {
  const { showSuccess, showError, showInfo } = useToast();
  const [adsets, setAdsets]     = useState([]);
  const [rules, setRules]       = useState([]);
  const [datePreset, setDatePreset] = useState('last_7d');
  const [adAccountId, setAdAccountId] = useState('');
  const [loadingAdsets, setLoadingAdsets] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [checking, setChecking] = useState(false);
  const [showAddRule, setShowAddRule] = useState(false);
  const [lastCheckResult, setLastCheckResult] = useState(null);
  const [searchParams, setSearchParams] = useSearchParams();
  const [statusFilter, setStatusFilter] = useState(() => {
    const view = searchParams.get('view');
    if (view === 'attention') return 'flagged';
    if (view === 'top-performers') return 'has_spend';
    return 'ACTIVE';
  });
  const [sortBy, setSortBy] = useState(() => {
    const view = searchParams.get('view');
    if (view === 'top-performers') return 'roas';
    return 'status';
  });
  const [dashboardView, setDashboardView] = useState(() => searchParams.get('view')); // banner state

  // Bulk insights state — one API call replaces N per-row calls
  const [bulkInsights, setBulkInsights]       = useState(null);
  const [bulkInsightsLoading, setBulkInsightsLoading] = useState(false);
  const [bulkInsightsError, setBulkInsightsError]   = useState(null);

  // Ad-level (creative) breakdown state
  const [adsBulk, setAdsBulk]           = useState(null);
  const [adsLoading, setAdsLoading]     = useState(false);
  const [rtAdsBulk, setRtAdsBulk]       = useState(null);  // RT data keyed by ad_id (sub3)
  const [expandedAdsets, setExpandedAdsets] = useState(new Set());

  const loadAdsets = useCallback(async () => {
    setLoadingAdsets(true);
    try {
      const res = await authFetch(`${API_BASE}/facebook/adsets/saved`);
      if (!res.ok) throw new Error('Failed to load ad sets');
      const data = await res.json();
      setAdsets(Array.isArray(data) ? data : data.adsets || []);
    } catch (e) { showError(e.message); }
    finally { setLoadingAdsets(false); }
  }, []);

  const loadRules = useCallback(async () => {
    try {
      const res = await authFetch(`${API_BASE}/auto-pause/rules`);
      if (!res.ok) throw new Error('Failed to load rules');
      setRules(await res.json());
    } catch (e) { showError(e.message); }
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
      const res = await authFetch(`${API_BASE}/auto-pause/insights-bulk?${params}`);
      if (!res.ok) { const e = await res.json(); throw new Error(e.detail || 'Failed to load insights'); }
      setBulkInsights(await res.json());
    } catch (e) {
      setBulkInsightsError(e.message);
    } finally {
      setBulkInsightsLoading(false);
    }
  }, [buildDateParams]);

  const loadAdsBulk = useCallback(async (accountId, preset, dateFrom = null, dateTo = null) => {
    setAdsLoading(true);
    try {
      const params = buildDateParams(preset, dateFrom, dateTo);
      if (accountId) params.set('ad_account_id', accountId);
      const res = await authFetch(`${API_BASE}/auto-pause/ads-bulk?${params}`);
      if (!res.ok) return; // non-fatal — ad breakdown is supplementary
      setAdsBulk(await res.json());
    } catch (e) {
      // silently fail — creative breakdown is supplementary
    } finally {
      setAdsLoading(false);
    }
  }, [buildDateParams]);

  const loadRtAdsBulk = useCallback(async (preset, dateFrom = null, dateTo = null) => {
    // RT ad-level data keyed by ad_id (sub1) → {conversions, revenue, roas, cpl, ...}
    try {
      const params = buildDateParams(preset, dateFrom, dateTo);
      const res = await authFetch(`${API_BASE}/redtrack/report/sub1?${params}`);
      if (!res.ok) return;
      const data = await res.json();
      if (data.configured && data.data) setRtAdsBulk(data.data);
    } catch (e) {
      // silently fail — RT ad-level is supplementary
    }
  }, [buildDateParams]);

  // On mount: use cached account ID immediately, refresh in background with timeout
  useEffect(() => {
    const cached = localStorage.getItem('fb_ad_account_id') || '';
    if (cached) setAdAccountId(cached);

    const controller = new AbortController();
    const tid = setTimeout(() => controller.abort(), 4000); // 4s hard timeout

    authFetch(`${API_BASE}/facebook/accounts`, { signal: controller.signal })
      .then(res => res.ok ? res.json() : null)
      .then(accounts => {
        clearTimeout(tid);
        const id = Array.isArray(accounts) && accounts.length > 0
          ? (accounts[0].account_id || '') : '';
        if (id) { localStorage.setItem('fb_ad_account_id', id); setAdAccountId(id); }
        const resolvedId = id || cached;
        loadBulkInsights(resolvedId, 'last_7d');
        loadAdsBulk(resolvedId, 'last_7d');
        loadRtAdsBulk('last_7d');
      })
      .catch(() => {
        clearTimeout(tid);
        // Fall back to cached or empty — still fire the data loads
        loadBulkInsights(cached, 'last_7d');
        loadAdsBulk(cached, 'last_7d');
        loadRtAdsBulk('last_7d');
      });
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Re-fetch all bulk data whenever date preset changes
  useEffect(() => {
    loadBulkInsights(adAccountId, datePreset);
    loadAdsBulk(adAccountId, datePreset);
    loadRtAdsBulk(datePreset);
  }, [datePreset]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { loadAdsets(); loadRules(); }, [loadAdsets, loadRules]);

  const deleteRule = async (ruleId) => {
    try {
      const res = await authFetch(`${API_BASE}/auto-pause/rules/${ruleId}`, { method: 'DELETE' });
      if (!res.ok) throw new Error('Failed to delete rule');
      showSuccess('Rule deleted');
      loadRules();
    } catch (e) { showError(e.message); }
  };

  const toggleRule = async (rule) => {
    try {
      const res = await authFetch(`${API_BASE}/auto-pause/rules/${rule.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ is_active: !rule.is_active }),
      });
      if (!res.ok) throw new Error('Failed to update rule');
      showSuccess(rule.is_active ? 'Rule disabled' : 'Rule enabled');
      loadRules();
    } catch (e) { showError(e.message); }
  };

  const syncFromMeta = async () => {
    setSyncing(true);
    showInfo('Importing campaigns and ad sets from Meta...');
    try {
      const params = adAccountId ? `?ad_account_id=${adAccountId}` : '';
      const res = await authFetch(`${API_BASE}/facebook/sync${params}`, { method: 'POST' });
      if (!res.ok) throw new Error('Sync failed');
      const result = await res.json();
      showSuccess(
        `Sync complete — ${result.campaigns.created} campaigns, ${result.adsets.created} ad sets imported. ${result.adsets.updated} ad sets updated.`
      );
      loadAdsets();
    } catch (e) { showError(e.message); }
    finally { setSyncing(false); }
  };

  const [syncingRT, setSyncingRT] = useState(false);
  const syncRedTrack = async () => {
    setSyncingRT(true);
    showInfo('Syncing RedTrack data...');
    try {
      const params = new URLSearchParams({ date_preset: datePreset });
      const res = await authFetch(`${API_BASE}/redtrack/sync?${params}`, { method: 'POST' });
      if (!res.ok) { const e = await res.json(); throw new Error(e.detail || 'Sync failed'); }
      const result = await res.json();
      if (result.synced > 0) {
        showSuccess(`RedTrack synced — ${result.synced} ad sets updated. Refreshing stats...`);
        loadBulkInsights(adAccountId, datePreset);
      } else {
        showInfo(result.message || 'No RedTrack data returned.');
      }
    } catch (e) { showError(e.message); }
    finally { setSyncingRT(false); }
  };

  const runCheck = async () => {
    setChecking(true);
    showInfo('Checking all rules against live Meta data...');
    try {
      const params = adAccountId ? `?ad_account_id=${adAccountId}` : '';
      const res = await authFetch(`${API_BASE}/auto-pause/check${params}`, { method: 'POST' });
      if (!res.ok) throw new Error('Check failed');
      const result = await res.json();
      setLastCheckResult(result);
      if (result.paused.length > 0) {
        showSuccess(`Paused ${result.paused.length} ad set(s)! Check results below.`);
      } else {
        showSuccess(`Check complete — no rules breached. ${result.rules_evaluated} rules evaluated.`);
      }
      loadAdsets(); loadRules();
    } catch (e) { showError(e.message); }
    finally { setChecking(false); }
  };

  // Helper: is this ad set flagged for attention?
  const isFlagged = useCallback((a) => {
    const ins = bulkInsights?.[a.fb_adset_id];
    if (!ins) return false;
    if (ins.frequency >= 3) return true;
    if (ins.spend > 50 && ins.leads === 0) return true;
    if (rules.some(r => r.triggered_at && r.fb_adset_id === a.fb_adset_id)) return true;
    return false;
  }, [bulkInsights, rules]);

  const visibleAdsets = useMemo(() => {
    let list = adsets.filter(a => a.fb_adset_id);

    // Status / spend / flagged filter
    if (statusFilter === 'ACTIVE') {
      list = list.filter(a => a.status === 'ACTIVE');
    } else if (statusFilter === 'PAUSED') {
      list = list.filter(a => a.status === 'PAUSED');
    } else if (statusFilter === 'has_spend') {
      list = list.filter(a => (bulkInsights?.[a.fb_adset_id]?.spend ?? 0) > 0);
    } else if (statusFilter === 'flagged') {
      list = list.filter(a => a.status === 'ACTIVE' && isFlagged(a));
    }

    // Sort
    list = [...list].sort((a, b) => {
      if (sortBy === 'status') {
        if (a.status === b.status) return a.name.localeCompare(b.name);
        return a.status === 'ACTIVE' ? -1 : 1;
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
  }, [adsets, statusFilter, sortBy, bulkInsights, isFlagged]);

  return (
    <div className="max-w-6xl mx-auto space-y-8">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-2">
            <TrendingDown size={26} className="text-red-500" />
            Performance &amp; Auto-Pause
          </h1>
          <p className="text-gray-500 text-sm mt-1">
            Live Meta Insights · Rules checked every 30 minutes automatically
          </p>
        </div>
        <div className="flex items-center gap-3 flex-wrap">
          <button
            onClick={syncFromMeta}
            disabled={syncing}
            className="flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium border border-gray-200 text-gray-600 hover:bg-gray-50 transition-colors disabled:opacity-50"
            title="Import all campaigns and ad sets from Meta into this app"
          >
            <RefreshCw size={14} className={syncing ? 'animate-spin' : ''} />
            {syncing ? 'Syncing...' : 'Sync from Meta'}
          </button>
          <button
            onClick={syncRedTrack}
            disabled={syncingRT}
            className="flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium border border-gray-200 text-blue-600 hover:bg-blue-50 transition-colors disabled:opacity-50"
            title="Pull latest RedTrack conversion data into cache"
          >
            <RefreshCw size={14} className={syncingRT ? 'animate-spin' : ''} />
            {syncingRT ? 'Syncing RT...' : 'Sync RedTrack'}
          </button>
          <select
            className="border border-gray-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500"
            value={datePreset}
            onChange={e => setDatePreset(e.target.value)}
          >
            {DATE_PRESETS.map(d => <option key={d.value} value={d.value}>{d.label}</option>)}
          </select>
          <div className="relative">
            <input
              type="text"
              placeholder="Ad Account ID"
              className="border border-gray-200 rounded-lg pl-3 pr-8 py-2 text-sm w-48 focus:ring-2 focus:ring-indigo-500 focus:outline-none"
              value={adAccountId}
              onChange={e => setAdAccountId(e.target.value)}
            />
            {adAccountId && (
              <span className="absolute right-2 top-1/2 -translate-y-1/2 w-2 h-2 rounded-full bg-green-400" title="Account connected" />
            )}
          </div>
          <button
            onClick={runCheck}
            disabled={checking}
            className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium text-white transition-colors"
            style={{ backgroundColor: checking ? '#9CA3AF' : '#2D2463' }}
          >
            <RefreshCw size={14} className={checking ? 'animate-spin' : ''} />
            {checking ? 'Checking...' : 'Check Now'}
          </button>
        </div>
      </div>

      {/* Dashboard deep-link banner */}
      {dashboardView && (
        <div className={`flex items-center justify-between rounded-xl px-4 py-3 text-sm font-medium border ${
          dashboardView === 'attention'
            ? 'bg-orange-50 border-orange-200 text-orange-800'
            : 'bg-green-50 border-green-200 text-green-800'
        }`}>
          <div className="flex items-center gap-2">
            {dashboardView === 'attention'
              ? <><AlertTriangle size={15} /> Showing flagged ad sets — high frequency, zero-lead spend, or auto-paused</>
              : <><TrendingUp size={15} /> Showing top performers — sorted by RT ROAS, active with spend</>
            }
          </div>
          <button
            onClick={() => { setDashboardView(null); setSearchParams({}); setStatusFilter('ACTIVE'); setSortBy('status'); }}
            className="ml-4 hover:opacity-70 transition-opacity"
          >
            <X size={14} />
          </button>
        </div>
      )}

      {/* Last check results */}
      {lastCheckResult && lastCheckResult.paused.length > 0 && (
        <div className="bg-red-50 border border-red-200 rounded-xl p-4">
          <h3 className="font-semibold text-red-800 flex items-center gap-2 mb-2">
            <PauseCircle size={16} /> Auto-paused {lastCheckResult.paused.length} ad set(s)
          </h3>
          {lastCheckResult.paused.map((p, i) => (
            <div key={i} className="text-sm text-red-700">
              <strong>{p.adset}</strong> — {p.reason}
            </div>
          ))}
        </div>
      )}

      {/* Ad Set Performance Table */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
        <div className="px-6 py-4 border-b border-gray-100 flex flex-wrap items-center justify-between gap-3">
          <h2 className="font-semibold text-gray-900 flex items-center gap-2">
            <Target size={16} className="text-gray-400" /> Ad Set Performance
            <span className="text-xs text-gray-400 font-normal">
              {statusFilter === 'all'
                ? `${adsets.filter(a => a.fb_adset_id).length} total`
                : `${visibleAdsets.length} ${statusFilter.toLowerCase()}`}
            </span>
          </h2>
          <div className="flex items-center gap-2">
            {/* Status filter */}
            <select
              className="border border-gray-200 rounded-lg px-2 py-1.5 text-xs text-gray-600 focus:outline-none focus:ring-2 focus:ring-indigo-500"
              value={statusFilter}
              onChange={e => { setStatusFilter(e.target.value); setDashboardView(null); }}
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
              onChange={e => { setSortBy(e.target.value); setDashboardView(null); }}
            >
              <option value="status">Sort: Active first</option>
              <option value="spend">Sort: Spend ↓</option>
              <option value="cpl">Sort: CPL ↑</option>
              <option value="roas">Sort: RT ROAS ↓</option>
              <option value="name">Sort: Name A–Z</option>
            </select>
            <button
              onClick={() => { loadAdsets(); loadBulkInsights(adAccountId, datePreset); }}
              className="text-gray-400 hover:text-gray-600 transition-colors"
              title="Refresh"
            >
              <RefreshCw size={14} />
            </button>
          </div>
        </div>

        {loadingAdsets ? (
          <div className="p-8 text-center text-gray-400 text-sm">Loading ad sets...</div>
        ) : visibleAdsets.length === 0 ? (
          <div className="p-8 text-center text-gray-400 text-sm">
            {statusFilter === 'has_spend' ? 'No ad sets with spend in this date range.' : statusFilter !== 'all' ? `No ${statusFilter.toLowerCase()} ad sets found.` : 'No launched ad sets found. Create and launch a campaign first.'}
          </div>
        ) : (
          <div className="divide-y divide-gray-50">
            {visibleAdsets.map(adset => {
              const isExpanded = expandedAdsets.has(adset.fb_adset_id);
              const hasAds = adsBulk && adsBulk[adset.fb_adset_id]?.length > 0;
              return (
                <div key={adset.id} className="px-6 py-4">
                  <div className="flex items-center justify-between mb-3">
                    <div className="flex items-center flex-wrap gap-2">
                      {/* Expand / collapse toggle */}
                      <button
                        onClick={() => setExpandedAdsets(prev => {
                          const next = new Set(prev);
                          next.has(adset.fb_adset_id) ? next.delete(adset.fb_adset_id) : next.add(adset.fb_adset_id);
                          return next;
                        })}
                        className="text-gray-400 hover:text-gray-600 transition-colors"
                        title={isExpanded ? 'Hide creative breakdown' : 'Show creative breakdown'}
                      >
                        {isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                      </button>
                      <span className="font-medium text-gray-900 text-sm">{adset.name}</span>
                      <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                        adset.status === 'ACTIVE'
                          ? 'bg-green-100 text-green-700'
                          : 'bg-gray-100 text-gray-500'
                      }`}>
                        {adset.status}
                      </span>
                      {hasAds && (
                        <span className="text-xs text-gray-400">
                          {adsBulk[adset.fb_adset_id].length} creative{adsBulk[adset.fb_adset_id].length !== 1 ? 's' : ''}
                        </span>
                      )}
                      {(() => {
                        const adsetRules = rules.filter(r => r.adset_id === adset.id);
                        const activeRule = adsetRules.find(r => r.is_active && !r.triggered_at);
                        const triggeredRule = adsetRules.find(r => r.triggered_at);
                        if (triggeredRule) return (
                          <span className="text-xs px-2 py-0.5 rounded-full font-medium bg-red-100 text-red-700 flex items-center gap-1">
                            <PauseCircle size={10} /> Rule triggered
                          </span>
                        );
                        if (activeRule) return (
                          <span className="text-xs px-2 py-0.5 rounded-full font-medium bg-indigo-50 text-indigo-600 flex items-center gap-1">
                            <Zap size={10} /> Rule active
                          </span>
                        );
                        return null;
                      })()}
                    </div>
                    <span className="text-xs text-gray-400">{adset.fb_adset_id}</span>
                  </div>
                  <InsightsCard
                    fbAdsetId={adset.fb_adset_id}
                    adsetName={adset.name}
                    adAccountId={adAccountId}
                    datePreset={datePreset}
                    bulkData={bulkInsights}
                    bulkLoading={bulkInsightsLoading}
                    bulkError={bulkInsightsError}
                  />
                  {/* Creative breakdown — only renders when expanded */}
                  {isExpanded && (
                    <AdsBreakdown
                      fbAdsetId={adset.fb_adset_id}
                      adsBulk={adsBulk}
                      adsLoading={adsLoading}
                      rtAdsBulk={rtAdsBulk}
                    />
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Auto-Pause Rules */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
        <div className="px-6 py-4 border-b border-gray-100 flex items-center justify-between">
          <h2 className="font-semibold text-gray-900 flex items-center gap-2">
            <PauseCircle size={16} className="text-red-500" /> Auto-Pause Rules
          </h2>
          <button
            onClick={() => setShowAddRule(true)}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium text-white"
            style={{ backgroundColor: '#2D2463' }}
          >
            <Plus size={14} /> Add Rule
          </button>
        </div>

        {rules.length === 0 ? (
          <div className="p-8 text-center">
            <PauseCircle size={32} className="text-gray-200 mx-auto mb-2" />
            <p className="text-gray-500 text-sm">No rules yet.</p>
            <p className="text-gray-400 text-xs mt-1">Add a rule to automatically pause ad sets when performance drops.</p>
          </div>
        ) : (
          <div className="divide-y divide-gray-50">
            {rules.map(rule => (
              <div key={rule.id} className={`px-6 py-4 flex items-center justify-between gap-4 ${!rule.is_active ? 'opacity-50' : ''}`}>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-medium text-gray-900 text-sm truncate">{rule.adset_name || rule.adset_id}</span>
                    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                      rule.triggered_at ? 'bg-red-100 text-red-700' : rule.is_active ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'
                    }`}>
                      {rule.triggered_at ? 'Triggered' : rule.is_active ? 'Active' : 'Disabled'}
                    </span>
                  </div>
                  <p className="text-xs text-gray-500 mt-0.5">
                    Pause if {METRIC_LABELS[rule.metric]} {rule.operator === 'greater_than' ? '>' : '<'} {METRIC_UNITS[rule.metric]}{rule.threshold}
                    {' '}after {METRIC_UNITS.cpl}{rule.min_spend} spend
                  </p>
                  {rule.trigger_reason && (
                    <p className="text-xs text-red-600 mt-0.5 flex items-center gap-1">
                      <AlertTriangle size={10} /> {rule.trigger_reason}
                    </p>
                  )}
                  {rule.last_checked_at && (
                    <p className="text-xs text-gray-400 mt-0.5">
                      Last checked: {new Date(rule.last_checked_at).toLocaleString()}
                    </p>
                  )}
                </div>
                <div className="flex items-center gap-2 flex-shrink-0">
                  <button
                    onClick={() => toggleRule(rule)}
                    className="p-1.5 rounded-lg hover:bg-gray-100 transition-colors text-gray-400 hover:text-gray-700"
                    title={rule.is_active ? 'Disable rule' : 'Enable rule'}
                  >
                    {rule.is_active ? <PauseCircle size={16} /> : <PlayCircle size={16} />}
                  </button>
                  <button
                    onClick={() => deleteRule(rule.id)}
                    className="p-1.5 rounded-lg hover:bg-red-50 transition-colors text-gray-400 hover:text-red-500"
                    title="Delete rule"
                  >
                    <Trash2 size={16} />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {showAddRule && (
        <AddRuleModal
          adsets={adsets}
          onClose={() => setShowAddRule(false)}
          onCreated={loadRules}
        />
      )}
    </div>
  );
}
