import React, { useEffect, useState, useCallback, useRef } from 'react';
import { TrendingDown, Wand2, Star, ShoppingBag, AlertTriangle, TrendingUp, RefreshCw, ArrowRight, Calendar, ChevronDown } from 'lucide-react';
import { Link } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { authFetch } from '../lib/facebookApi';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1';

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
            <div className="flex gap-2 items-center">
              <input
                type="date"
                value={dateFrom}
                onChange={e => setDateFrom(e.target.value)}
                className="flex-1 text-xs border border-gray-200 rounded-lg px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-indigo-400"
              />
              <span className="text-gray-400 text-xs">–</span>
              <input
                type="date"
                value={dateTo}
                onChange={e => setDateTo(e.target.value)}
                className="flex-1 text-xs border border-gray-200 rounded-lg px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-indigo-400"
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
  const { authFetch: authFetchCtx } = useAuth();
  const [loading, setLoading] = useState(true);
  const [adsets, setAdsets] = useState([]);
  const [bulkInsights, setBulkInsights] = useState({});
  const [rules, setRules] = useState([]);

  // Date filter state
  const [preset, setPreset] = useState('last_7d');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [activeRange, setActiveRange] = useState({ preset: 'last_7d', dateFrom: null, dateTo: null });

  const load = useCallback(async (range) => {
    const { preset: p, dateFrom: df, dateTo: dt } = range || { preset: 'last_7d', dateFrom: null, dateTo: null };
    setLoading(true);
    try {
      // Resolve ad account ID first (same pattern as CampaignPerformance)
      let adAccountId = '';
      try {
        const acctRes = await authFetch(`${API_URL}/facebook/accounts`);
        if (acctRes.ok) {
          const accounts = await acctRes.json();
          adAccountId = (Array.isArray(accounts) && accounts.length > 0)
            ? (accounts[0].account_id || '')
            : '';
        }
      } catch (_) { /* fall through with empty account */ }

      const insightsParams = new URLSearchParams();
      if (adAccountId) insightsParams.set('ad_account_id', adAccountId);
      if (df && dt) {
        insightsParams.set('date_from', df);
        insightsParams.set('date_to', dt);
      } else {
        insightsParams.set('date_preset', p || 'last_7d');
      }

      const [adsetsRes, insightsRes, rulesRes] = await Promise.all([
        authFetch(`${API_URL}/facebook/adsets/saved`),
        authFetch(`${API_URL}/auto-pause/insights-bulk?${insightsParams}`),
        authFetch(`${API_URL}/auto-pause/rules`),
      ]);
      if (adsetsRes.ok)   setAdsets(await adsetsRes.json());
      if (insightsRes.ok) setBulkInsights(await insightsRes.json());
      if (rulesRes.ok)    setRules(await rulesRes.json());
    } catch (e) {
      // silently degrade
    } finally {
      setLoading(false);
    }
  }, []);

  // Initial load
  useEffect(() => { load(activeRange); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  function handleApply(range) {
    setActiveRange(range);
    load(range);
  }

  // ── Aggregate KPIs ──────────────────────────────────────────────────────────
  const rows = Object.values(bulkInsights);
  const totalSpend   = rows.reduce((s, r) => s + (r.spend || 0), 0);
  const totalLeads   = rows.reduce((s, r) => s + (r.leads || 0), 0);
  const blendedCpl   = totalLeads > 0 ? totalSpend / totalLeads : null;
  const rtRevenue    = rows.reduce((s, r) => s + (r.redtrack?.revenue || 0), 0);
  const rtConvs      = rows.reduce((s, r) => s + (r.redtrack?.conversions || 0), 0);
  const rtRoas       = totalSpend > 0 && rtRevenue > 0 ? rtRevenue / totalSpend : null;
  const activeCount  = adsets.filter(a => a.status === 'ACTIVE').length;

  // Human-readable subtitle for selected range
  const rangeLabel = activeRange.dateFrom && activeRange.dateTo
    ? `${activeRange.dateFrom} – ${activeRange.dateTo}`
    : (PRESETS.find(p => p.value === activeRange.preset)?.label ?? 'Last 7 Days');

  // ── Needs Attention ─────────────────────────────────────────────────────────
  const triggeredRules = rules.filter(r => r.triggered_at);
  const needsAttention = [];

  triggeredRules.forEach(r => {
    needsAttention.push({
      id: `rule-${r.id}`,
      label: r.adset_name || 'Ad set',
      reason: `Auto-paused: ${r.trigger_reason}`,
      severity: 'red',
      link: '/performance',
    });
  });

  adsets
    .filter(a => a.status === 'ACTIVE' && a.fb_adset_id)
    .forEach(a => {
      const ins = bulkInsights[a.fb_adset_id];
      if (!ins) return;
      if (ins.frequency >= 5) {
        needsAttention.push({
          id: `freq-${a.id}`,
          label: a.name,
          reason: `Frequency ${ins.frequency.toFixed(1)} — ad fatigue risk`,
          severity: 'red',
          link: '/performance',
        });
      } else if (ins.frequency >= 3) {
        needsAttention.push({
          id: `freq-warn-${a.id}`,
          label: a.name,
          reason: `Frequency ${ins.frequency.toFixed(1)} — monitor closely`,
          severity: 'orange',
          link: '/performance',
        });
      }
      if (ins.spend > 50 && ins.leads === 0) {
        needsAttention.push({
          id: `noleads-${a.id}`,
          label: a.name,
          reason: `$${ins.spend.toFixed(0)} spent, 0 leads`,
          severity: 'red',
          link: '/performance',
        });
      }
    });

  const seen = new Set();
  const attentionList = needsAttention.filter(item => {
    if (seen.has(item.id)) return false;
    seen.add(item.id);
    return true;
  }).slice(0, 5);

  // ── Top Performers (by RT ROAS, min spend $50) ──────────────────────────────
  const topPerformers = adsets
    .filter(a => a.fb_adset_id && bulkInsights[a.fb_adset_id])
    .map(a => {
      const ins = bulkInsights[a.fb_adset_id];
      const rt  = ins?.redtrack;
      return {
        id: a.id,
        name: a.name,
        status: a.status,
        spend: ins?.spend || 0,
        leads: ins?.leads || 0,
        cpl: ins?.cpl,
        rtRoas: rt?.roas,
        rtCpl: rt?.cpl,
        rtConvs: rt?.conversions || 0,
      };
    })
    .filter(a => a.spend >= 50 && a.rtRoas != null && a.rtRoas > 0)
    .sort((a, b) => b.rtRoas - a.rtRoas)
    .slice(0, 4);

  const quickActions = [
    { label: 'Performance', description: 'Live ad set & creative stats', icon: TrendingDown, path: '/performance', color: 'from-indigo-600 to-indigo-500', primary: true },
    { label: 'Build Creatives', description: 'Create new image or video ads', icon: Wand2, path: '/build-creatives', color: 'from-amber-500 to-orange-500' },
    { label: 'Manage Brands', description: 'Update brand assets and profiles', icon: ShoppingBag, path: '/brands', color: 'from-orange-500 to-red-500' },
    { label: 'Browse Templates', description: 'Explore winning ad templates', icon: Star, path: '/winning-ads', color: 'from-amber-600 to-yellow-600' },
  ];

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
            onClick={() => load(activeRange)}
            disabled={loading}
            className="flex items-center gap-2 px-3 py-2 rounded-lg text-sm text-gray-500 border border-gray-200 hover:bg-gray-50 transition-colors disabled:opacity-40"
          >
            <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
            Refresh
          </button>
        </div>
      </div>

      {/* KPI Row */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4">
        <KpiCard
          label="Total Spend"
          value={loading ? '—' : `$${totalSpend.toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`}
          sub={rangeLabel}
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
          sub={rtConvs > 0 ? `${rtConvs} conversions` : 'RedTrack'}
        />
        <KpiCard
          label="RT ROAS"
          value={loading ? '—' : rtRoas != null ? `${rtRoas.toFixed(2)}x` : '—'}
          sub="revenue ÷ spend"
          highlight={rtRoas != null && rtRoas < 1}
          warn={rtRoas != null && rtRoas >= 1 && rtRoas < 1.5}
        />
      </div>

      {/* Needs Attention + Top Performers */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">

        {/* Needs Attention */}
        <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
          <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between">
            <h2 className="font-semibold text-gray-900 flex items-center gap-2 text-sm">
              <AlertTriangle size={15} className="text-orange-500" />
              Needs Attention
            </h2>
            <Link to="/performance" className="text-xs text-indigo-600 hover:underline flex items-center gap-1">
              View all <ArrowRight size={11} />
            </Link>
          </div>
          {loading ? (
            <div className="px-5 py-8 text-center text-sm text-gray-400">Loading...</div>
          ) : attentionList.length === 0 ? (
            <div className="px-5 py-8 text-center text-sm text-gray-400">
              <div className="text-green-500 font-medium mb-1">All clear</div>
              No issues flagged for this period.
            </div>
          ) : (
            <div className="divide-y divide-gray-50">
              {attentionList.map(item => (
                <Link key={item.id} to={item.link} className="flex items-start gap-3 px-5 py-3 hover:bg-gray-50 transition-colors">
                  <div className={`mt-0.5 w-2 h-2 rounded-full flex-shrink-0 ${item.severity === 'red' ? 'bg-red-500' : 'bg-orange-400'}`} />
                  <div className="min-w-0">
                    <div className="text-sm font-medium text-gray-800 truncate">{item.label}</div>
                    <div className={`text-xs mt-0.5 ${item.severity === 'red' ? 'text-red-600' : 'text-orange-500'}`}>{item.reason}</div>
                  </div>
                </Link>
              ))}
            </div>
          )}
        </div>

        {/* Top Performers */}
        <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
          <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between">
            <h2 className="font-semibold text-gray-900 flex items-center gap-2 text-sm">
              <TrendingUp size={15} className="text-green-500" />
              Top Performers
              <span className="text-xs text-gray-400 font-normal">by RT ROAS</span>
            </h2>
            <Link to="/performance" className="text-xs text-indigo-600 hover:underline flex items-center gap-1">
              View all <ArrowRight size={11} />
            </Link>
          </div>
          {loading ? (
            <div className="px-5 py-8 text-center text-sm text-gray-400">Loading...</div>
          ) : topPerformers.length === 0 ? (
            <div className="px-5 py-8 text-center text-sm text-gray-400">
              No RT data yet — sync RedTrack from the Performance page.
            </div>
          ) : (
            <div className="divide-y divide-gray-50">
              {topPerformers.map((a, i) => (
                <Link key={a.id} to="/performance" className="flex items-center gap-3 px-5 py-3 hover:bg-gray-50 transition-colors">
                  <span className="text-xs font-bold text-gray-300 w-4">{i + 1}</span>
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium text-gray-800 truncate">{a.name}</div>
                    <div className="text-xs text-gray-400 mt-0.5">
                      ${a.spend.toFixed(0)} spend · {a.leads} leads · {a.rtConvs} RT convs
                    </div>
                  </div>
                  <div className="text-right flex-shrink-0">
                    <div className="text-sm font-bold text-green-600">{a.rtRoas.toFixed(2)}x</div>
                    {a.rtCpl != null && (
                      <div className="text-xs text-gray-400">${a.rtCpl.toFixed(2)} CPL</div>
                    )}
                  </div>
                </Link>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Quick Actions */}
      <div>
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-3">Quick Actions</h2>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {quickActions.map((action) => {
            const Icon = action.icon;
            return (
              <Link
                key={action.path}
                to={action.path}
                className={`group bg-white rounded-xl border shadow-sm p-5 hover:shadow-md transition-all ${action.primary ? 'border-indigo-200 bg-indigo-50/40' : 'border-gray-200'}`}
              >
                <div className={`bg-gradient-to-r ${action.color} w-10 h-10 rounded-lg flex items-center justify-center mb-3 group-hover:scale-105 transition-transform`}>
                  <Icon className="text-white" size={20} />
                </div>
                <div className={`text-sm font-semibold mb-0.5 ${action.primary ? 'text-indigo-700' : 'text-gray-900'}`}>{action.label}</div>
                <div className="text-xs text-gray-500">{action.description}</div>
              </Link>
            );
          })}
        </div>
      </div>
    </div>
  );
}
