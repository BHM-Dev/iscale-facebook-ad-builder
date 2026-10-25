import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AlertTriangle, ArrowLeft, ArrowRight, BarChart3, RefreshCw, ShieldCheck } from 'lucide-react';
import { Link, useLocation } from 'react-router-dom';
import { authFetch } from '../lib/facebookApi';
import { useCampaign } from '../context/CampaignContext';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1';
const money = (value, digits = 0) => value == null ? '—' : `$${Number(value).toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
const percent = (current, previous, goodWhen = 'up') => {
  if (current == null || previous == null || previous === 0) return null;
  const value = ((current - previous) / Math.abs(previous)) * 100;
  const good = goodWhen === 'up' ? value > 0 : value < 0;
  return <span className={`text-[11px] font-semibold ${value === 0 ? 'text-gray-400' : good ? 'text-green-600' : 'text-red-600'}`}>{value > 0 ? '↑' : '↓'} {Math.abs(value).toFixed(0)}% vs prior</span>;
};

function isoDaysBefore(days) {
  const date = new Date();
  date.setHours(12, 0, 0, 0);
  date.setDate(date.getDate() - days);
  return date.toISOString().slice(0, 10);
}

function Metric({ label, value, comparison, goodWhen }) {
  return <div className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
    <div className="text-[11px] font-semibold uppercase tracking-wide text-gray-500">{label}</div>
    <div className="mt-1 text-2xl font-bold text-gray-900">{value}</div>
    <div className="mt-1 min-h-4">{comparison && percent(comparison.current, comparison.previous, goodWhen)}</div>
  </div>;
}

export default function PerformanceBrief() {
  const location = useLocation();
  const { activeAccountId } = useCampaign();
  const query = useMemo(() => new URLSearchParams(location.search), [location.search]);
  const [range, setRange] = useState(() => ({
    from: query.get('date_from') || isoDaysBefore(7),
    to: query.get('date_to') || isoDaysBefore(1),
  }));
  const [brief, setBrief] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const requestRef = useRef(0);

  const load = useCallback(async (refresh = false) => {
    const requestId = ++requestRef.current;
    setLoading(true); setError(null); setBrief(null);
    const params = new URLSearchParams({ date_from: range.from, date_to: range.to });
    const accountId = query.get('ad_account_id') || activeAccountId;
    if (accountId) params.set('ad_account_id', accountId);
    if (refresh) params.set('refresh', 'true');
    try {
      const response = await authFetch(`${API_URL}/dashboard/performance-brief?${params}`);
      if (!response.ok) throw new Error('The performance brief is temporarily unavailable.');
      const payload = await response.json();
      if (requestId === requestRef.current) setBrief(payload);
    } catch (requestError) {
      if (requestId === requestRef.current) setError(requestError.message || 'The performance brief is temporarily unavailable.');
    } finally { if (requestId === requestRef.current) setLoading(false); }
  }, [activeAccountId, query, range]);

  useEffect(() => { load(); }, [load]);

  const totals = brief?.totals || {};
  const previous = brief?.previous_totals || {};
  const revenueAvailable = brief?.data_quality?.revenue_status === 'exact_adset_attributed';
  const accountRoas = totals.roas;
  const headline = !brief ? 'Loading completed-day review…'
    : !revenueAvailable ? 'Delivery review only — exact billable revenue is unavailable for this account.'
    : `Conversion-date billable revenue / delivery-date spend was ${accountRoas?.toFixed(2) || '—'}× in this completed window.`;
  const applyRange = (event) => { event.preventDefault(); if (range.from <= range.to) load(true); };
  const campaignLink = (adsetId, from = range.from, to = range.to) => `/campaign-performance?${new URLSearchParams({ view: 'all', adsetId, date_from: from, date_to: to, ...(brief?.ad_account_id ? { accountId: brief.ad_account_id } : {}) })}`;

  return <div className="mx-auto max-w-7xl space-y-6">
    <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
      <div>
        <Link to="/" className="inline-flex items-center gap-1 text-xs font-medium text-gray-500 hover:text-indigo-700"><ArrowLeft size={13} /> Dashboard</Link>
        <h1 className="mt-2 text-2xl font-bold text-gray-900">Performance Brief</h1>
        <p className="mt-1 max-w-3xl text-sm text-gray-500">A quiet completed-day review for decisions, not another alert stream. It identifies material delivery exceptions and directs Joel to the existing campaign workflow.</p>
      </div>
      <form onSubmit={applyRange} className="flex flex-wrap items-end gap-2 rounded-xl border border-gray-200 bg-white p-3 shadow-sm">
        <label className="text-[11px] font-medium text-gray-500">From<input type="date" value={range.from} onChange={event => setRange(value => ({ ...value, from: event.target.value }))} className="mt-1 block rounded border border-gray-200 px-2 py-1.5 text-sm text-gray-700" /></label>
        <label className="text-[11px] font-medium text-gray-500">To<input type="date" value={range.to} max={isoDaysBefore(1)} onChange={event => setRange(value => ({ ...value, to: event.target.value }))} className="mt-1 block rounded border border-gray-200 px-2 py-1.5 text-sm text-gray-700" /></label>
        <button type="submit" className="rounded-lg bg-indigo-600 px-3 py-2 text-xs font-semibold text-white hover:bg-indigo-700">Review</button>
        <button type="button" onClick={() => load(true)} disabled={loading} className="rounded-lg border border-gray-200 p-2 text-gray-500 hover:bg-gray-50 disabled:opacity-40" title="Refresh sources"><RefreshCw size={14} className={loading ? 'animate-spin' : ''} /></button>
      </form>
    </div>

    {error && <div className="flex items-center gap-2 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"><AlertTriangle size={15} />{error}</div>}

    <div className="rounded-xl border border-indigo-200 bg-indigo-50 p-5">
      <div className="flex items-center gap-2 text-sm font-semibold text-indigo-950"><BarChart3 size={16} className="text-indigo-600" />{headline}</div>
      <p className="mt-2 text-xs text-indigo-900/70">{brief ? `${brief.date_from}–${brief.date_to} compared with ${brief.previous_date_from}–${brief.previous_date_to}. Today is excluded. Conversion-date revenue can lag delivery-date spend (Pacific reporting time).` : 'Only closed reporting days are considered.'}</p>
    </div>

    <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
      <Metric label="Meta spend" value={money(totals.spend)} comparison={{ current: totals.spend, previous: previous.spend }} />
      <Metric label="Meta leads" value={totals.leads == null ? '—' : Number(totals.leads).toLocaleString()} comparison={{ current: totals.leads, previous: previous.leads }} />
      <Metric label="CPL" value={money(totals.cpl, 2)} comparison={{ current: totals.cpl, previous: previous.cpl }} goodWhen="down" />
      <Metric label="Billable revenue" value={money(totals.revenue)} comparison={{ current: totals.revenue, previous: previous.revenue }} />
      <Metric label="Revenue / lead" value={money(totals.revenue_per_lead, 2)} comparison={{ current: totals.revenue_per_lead, previous: previous.revenue_per_lead }} />
    </div>

    <div className="grid gap-4 xl:grid-cols-2">
      <section className="overflow-hidden rounded-xl border border-gray-200 bg-white shadow-sm">
        <div className="border-b border-gray-100 px-5 py-4"><h2 className="text-sm font-semibold text-gray-900">Problem days worth inspecting</h2><p className="mt-1 text-xs text-gray-500">Only days with at least 10% of period spend qualify. There is no fixed CPL target.</p></div>
        {loading ? <div className="p-6 text-sm text-gray-400">Loading completed days…</div> : brief?.day_flags?.length ? <div className="divide-y divide-gray-100">{brief.day_flags.map(flag => <div key={`${flag.date}-${flag.kind}`} className="flex gap-3 px-5 py-4"><AlertTriangle size={15} className="mt-0.5 shrink-0 text-orange-500" /><div className="min-w-0 flex-1"><Link to={campaignLink('', flag.date, flag.date)} className="text-sm font-semibold text-indigo-800 hover:underline">{flag.date}</Link><p className="mt-1 text-xs text-gray-600">{flag.detail}</p><div className="mt-2 flex flex-wrap gap-x-3 text-xs text-gray-500"><span>Spend {money(flag.spend)}</span><span>Leads {flag.leads}</span><span>CPL {money(flag.cpl, 2)}</span>{flag.revenue_per_lead != null && <span>RPL {money(flag.revenue_per_lead, 2)}</span>}</div></div></div>)}</div> : <div className="p-6 text-sm text-gray-500">No material completed-day exception met the review threshold.</div>}
      </section>
      <section className="overflow-hidden rounded-xl border border-gray-200 bg-white shadow-sm">
        <div className="border-b border-gray-100 px-5 py-4"><h2 className="text-sm font-semibold text-gray-900">Ad sets to inspect</h2><p className="mt-1 text-xs text-gray-500">Meta delivery only. Exact billable revenue is intentionally not allocated to an ad set here.</p></div>
        {loading ? <div className="p-6 text-sm text-gray-400">Loading delivery contributors…</div> : brief?.watch_adsets?.length ? <div className="divide-y divide-gray-100">{brief.watch_adsets.map(row => <div key={row.fb_adset_id} className="flex items-start justify-between gap-3 px-5 py-4"><div className="min-w-0"><div className="truncate text-sm font-semibold text-gray-900" title={row.adset_name}>{row.adset_name} <span className="text-[10px] font-medium text-gray-500">{row.status}</span></div>{row.campaign_name && <div className="truncate text-xs text-gray-500">{row.campaign_name}</div>}<div className="mt-2 flex flex-wrap gap-x-3 text-xs text-gray-500"><span>Spend {money(row.spend)}</span><span>Leads {row.leads}</span><span>CPL {money(row.cpl, 2)}</span>{row.daily_budget != null && <span>{row.budget_type || 'ABO'} budget {money(Number(row.daily_budget) / 100)}</span>}{row.spend_change_pct != null && <span>Spend {row.spend_change_pct > 0 ? '+' : ''}{row.spend_change_pct}%</span>}</div></div><Link to={campaignLink(row.fb_adset_id)} className="inline-flex shrink-0 items-center gap-1 text-xs font-semibold text-indigo-700 hover:underline">Inspect <ArrowRight size={12} /></Link></div>)}</div> : <div className="p-6 text-sm text-gray-500">No materially scaled CPL deterioration or spend-without-leads ad set in this window.</div>}
      </section>
    </div>

    <section className="overflow-hidden rounded-xl border border-gray-200 bg-white shadow-sm">
      <div className="border-b border-gray-100 px-5 py-4"><h2 className="text-sm font-semibold text-gray-900">Highest-spend delivery context</h2><p className="mt-1 text-xs text-gray-500">Use this to decide what to open next; it does not recommend automatic changes.</p></div>
      <div className="overflow-x-auto"><table className="w-full text-sm"><thead className="border-b border-gray-100 text-left text-[11px] uppercase tracking-wide text-gray-400"><tr><th className="px-5 py-3">Ad set</th><th className="px-3 py-3 text-right">Spend</th><th className="px-3 py-3 text-right">Leads</th><th className="px-3 py-3 text-right">CPL</th><th className="px-5 py-3 text-right">Prior spend</th></tr></thead><tbody className="divide-y divide-gray-50">{(brief?.adsets || []).slice(0, 10).map(row => <tr key={row.fb_adset_id} className="hover:bg-gray-50"><td className="px-5 py-3"><Link to={campaignLink(row.fb_adset_id)} className="font-medium text-gray-900 hover:text-indigo-700">{row.adset_name}</Link><div className="text-xs text-gray-500">{row.campaign_name || 'Campaign name unavailable'}</div></td><td className="px-3 py-3 text-right">{money(row.spend)}</td><td className="px-3 py-3 text-right">{row.leads}</td><td className="px-3 py-3 text-right">{money(row.cpl, 2)}</td><td className="px-5 py-3 text-right text-gray-500">{money(row.previous_spend)}</td></tr>)}</tbody></table></div>
    </section>

    <div className="flex gap-2 rounded-xl border border-gray-200 bg-white px-4 py-3 text-xs text-gray-500"><ShieldCheck size={15} className="mt-0.5 shrink-0 text-green-600" /><p><strong className="text-gray-700">Source discipline:</strong> {brief?.data_quality?.account_economics_source || 'Account economics load only when their exact source is available.'} Revenue status: <strong className="text-gray-700">{brief?.data_quality?.revenue_status || 'checking'}</strong>. {brief?.data_quality?.revenue_rule}</p></div>
  </div>;
}
