import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ChevronDown, ChevronRight, DollarSign, Download, Edit2, Plus, RefreshCw, Trash2, X } from 'lucide-react';
import { authFetch } from '../lib/facebookApi';
import { useCampaign } from '../context/CampaignContext';
import { useToast } from '../context/ToastContext';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1';

const CATEGORIES = ['labor', 'tooling', 'creative', 'data', 'other'];
const COST_TYPES = [
  ['one_off', 'One-off'],
  ['recurring_monthly', 'Recurring monthly'],
  ['pct_of_spend', '% of spend'],
  ['pct_of_revenue', '% of revenue'],
  ['pct_of_gross_profit', '% of gross profit'],
  ['pct_of_profit', '% of net profit'],
];

function money(value, decimals = 0) {
  return value != null ? `$${Number(value).toLocaleString('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals })}` : '--';
}

function pct(value) {
  return value != null ? `${(Number(value) * 100).toFixed(1)}%` : '--';
}

function revenueSourceLabel(source) {
  if (!source || source === 'none') return 'None';
  if (source === 'everflow_unavailable') return 'Switchboard unavailable';
  if (source.startsWith('everflow')) return source === 'everflow_live' ? 'Switchboard' : `Switchboard · ${source.replace('everflow_', '').replaceAll('_', ' ')}`;
  if (source === 'redtrack_unavailable') return 'RedTrack unavailable';
  if (source.startsWith('redtrack')) return source === 'redtrack_live' ? 'RedTrack' : `RedTrack · ${source.replace('redtrack_', '').replaceAll('_', ' ')}`;
  return source.replaceAll('_', ' ');
}

// Provider name only, without the live/fallback qualifier — for the page subhead,
// where the qualifier already appears on the Billable Revenue tile.
function revenueSourceName(source) {
  if (!source || source === 'none') return 'RedTrack';
  if (source.startsWith('everflow')) return 'Switchboard';
  if (source.startsWith('redtrack')) return 'RedTrack';
  return source.replaceAll('_', ' ');
}

function isRevenueFallback(source) {
  return source && !['everflow_live', 'redtrack_live'].includes(source);
}

function monthValue(date = new Date()) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`;
}

function firstOfMonth(month) {
  return `${month}-01`;
}

function AccountLabel({ account }) {
  if (!account) return null;
  const rawId = account.id || account.account_id || '';
  const id = rawId.startsWith('act_') ? rawId : `act_${rawId}`;
  return (
    <div className="text-sm text-gray-500">
      {account.name || 'Meta account'} · <span className="font-mono text-xs">{id}</span>
    </div>
  );
}

function KpiTile({ label, value, caption, tone = 'neutral', badge }) {
  const toneClass = tone === 'good' ? 'text-green-600' : tone === 'bad' ? 'text-red-600' : 'text-gray-900';
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
      <div className="flex items-center justify-between gap-2">
        <div className="text-xs font-semibold uppercase tracking-wide text-gray-500">{label}</div>
        {badge && <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-amber-700">{badge}</span>}
      </div>
      <div className={`mt-2 text-2xl font-bold ${toneClass}`}>{value}</div>
      <div className="mt-1 text-xs text-gray-400">{caption}</div>
    </div>
  );
}

function CostModal({ entry, summary, activeAccountId, onClose, onSaved }) {
  const { showError, showSuccess } = useToast();
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState(() => ({
    ad_account_id: entry ? (entry.ad_account_id || '') : activeAccountId,
    label: entry?.label ?? '',
    category: entry?.category ?? 'other',
    cost_type: entry?.cost_type ?? 'one_off',
    amount: entry?.amount ?? '',
    allocation_method: entry?.allocation_method ?? 'by_spend',
    effective_from: entry?.effective_from ?? firstOfMonth(monthValue()),
    effective_to: entry?.effective_to ?? '',
    notes: entry?.notes ?? '',
  }));

  const isAllAccounts = form.ad_account_id === '';
  const isPercent = form.cost_type.startsWith('pct_');
  const previewBase = useMemo(() => {
    if (!summary) return 0;
    if (form.cost_type === 'pct_of_spend') return summary.spend || 0;
    if (form.cost_type === 'pct_of_revenue') return summary.revenue || 0;
    if (form.cost_type === 'pct_of_gross_profit') return Math.max((summary.revenue || 0) - (summary.spend || 0), 0);
    if (form.cost_type === 'pct_of_profit') {
      const existingProfitCost = summary.costs?.find(cost => cost.cost_type === 'pct_of_profit' && cost.profit_base != null);
      return Math.max(existingProfitCost?.profit_base ?? ((summary.revenue || 0) - (summary.spend || 0) - (summary.other_costs || 0)), 0);
    }
    return 0;
  }, [form.cost_type, summary]);
  const previewAmount = isPercent ? previewBase * (Number(form.amount || 0) / 100) : Number(form.amount || 0);

  const save = async () => {
    if (!form.label.trim()) {
      showError('Cost label is required');
      return;
    }
    setSaving(true);
    try {
      const payload = {
        ...form,
        ad_account_id: isAllAccounts ? null : form.ad_account_id,
        amount: Number(form.amount || 0),
        effective_to: form.effective_to || null,
      };
      const url = entry ? `${API_URL}/pnl/costs/${entry.id}` : `${API_URL}/pnl/costs`;
      const res = await authFetch(url, {
        method: entry ? 'PATCH' : 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || 'Failed to save cost');
      }
      showSuccess(entry ? 'Cost updated' : 'Cost added');
      onSaved();
    } catch (err) {
      showError(err.message || 'Failed to save cost');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4 backdrop-blur-sm">
      <div className="w-full max-w-2xl rounded-xl bg-white shadow-xl">
        <div className="flex items-center justify-between border-b border-gray-100 px-5 py-4">
          <h2 className="text-lg font-semibold text-gray-900">{entry ? 'Edit cost' : 'Add cost'}</h2>
          <button onClick={onClose} className="rounded-lg p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600"><X size={18} /></button>
        </div>
        <div className="grid gap-4 p-5 sm:grid-cols-2">
          <label className="sm:col-span-2">
            <span className="text-xs font-semibold uppercase tracking-wide text-gray-500">Label</span>
            <input value={form.label} onChange={e => setForm({ ...form, label: e.target.value })} className="mt-1 w-full rounded-lg border border-gray-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500" />
          </label>
          <label>
            <span className="text-xs font-semibold uppercase tracking-wide text-gray-500">Category</span>
            <select value={form.category} onChange={e => setForm({ ...form, category: e.target.value })} className="mt-1 w-full rounded-lg border border-gray-200 px-3 py-2 text-sm">
              {CATEGORIES.map(c => <option key={c} value={c}>{c}</option>)}
            </select>
          </label>
          <label>
            <span className="text-xs font-semibold uppercase tracking-wide text-gray-500">Cost type</span>
            <select value={form.cost_type} onChange={e => setForm({ ...form, cost_type: e.target.value })} className="mt-1 w-full rounded-lg border border-gray-200 px-3 py-2 text-sm">
              {COST_TYPES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          </label>
          <label>
            <span className="text-xs font-semibold uppercase tracking-wide text-gray-500">{isPercent ? 'Percent' : 'Amount'}</span>
            <input type="number" min="0" max={isPercent ? 100 : undefined} step="0.01" value={form.amount} onChange={e => setForm({ ...form, amount: e.target.value })} className="mt-1 w-full rounded-lg border border-gray-200 px-3 py-2 text-sm" />
          </label>
          <label>
            <span className="text-xs font-semibold uppercase tracking-wide text-gray-500">Applies to</span>
            <select value={form.ad_account_id || ''} onChange={e => setForm({ ...form, ad_account_id: e.target.value })} className="mt-1 w-full rounded-lg border border-gray-200 px-3 py-2 text-sm">
              <option value={activeAccountId}>This account only</option>
              <option value="">All ad accounts</option>
            </select>
          </label>
          {isAllAccounts && (
            <label>
              <span className="text-xs font-semibold uppercase tracking-wide text-gray-500">Allocation</span>
              <select value={form.allocation_method} onChange={e => setForm({ ...form, allocation_method: e.target.value })} className="mt-1 w-full rounded-lg border border-gray-200 px-3 py-2 text-sm">
                <option value="by_spend">By spend</option>
                <option value="even">Even</option>
              </select>
            </label>
          )}
          <label>
            <span className="text-xs font-semibold uppercase tracking-wide text-gray-500">Effective from</span>
            <input type="date" value={form.effective_from} onChange={e => setForm({ ...form, effective_from: e.target.value })} className="mt-1 w-full rounded-lg border border-gray-200 px-3 py-2 text-sm" />
          </label>
          <label>
            <span className="text-xs font-semibold uppercase tracking-wide text-gray-500">Effective to</span>
            <input type="date" value={form.effective_to} onChange={e => setForm({ ...form, effective_to: e.target.value })} className="mt-1 w-full rounded-lg border border-gray-200 px-3 py-2 text-sm" />
          </label>
          <label className="sm:col-span-2">
            <span className="text-xs font-semibold uppercase tracking-wide text-gray-500">Notes</span>
            <textarea value={form.notes} onChange={e => setForm({ ...form, notes: e.target.value })} rows={3} className="mt-1 w-full rounded-lg border border-gray-200 px-3 py-2 text-sm" />
          </label>
          <div className="sm:col-span-2 rounded-lg border border-indigo-100 bg-indigo-50 px-3 py-2 text-sm text-indigo-800">
            {/* Never show "5% of $0.00" while the period data is still loading —
                a confident $0 preview is worse than admitting we don't know yet. */}
            {isPercent && !summary
              ? 'Waiting for this period\'s figures before previewing the resolved cost…'
              : isPercent
                ? `${Number(form.amount || 0)}% of ${money(previewBase, 2)} = ${money(previewAmount, 2)}`
                : `Resolved cost preview: ${money(previewAmount, 2)}`
            }
          </div>
        </div>
        <div className="flex justify-end gap-2 border-t border-gray-100 px-5 py-4">
          <button onClick={onClose} className="rounded-lg border border-gray-200 px-4 py-2 text-sm text-gray-600 hover:bg-gray-50">Cancel</button>
          <button onClick={save} disabled={saving} className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50">
            {saving ? 'Saving...' : 'Save cost'}
          </button>
        </div>
      </div>
    </div>
  );
}

export default function Pnl() {
  const { showError, showSuccess } = useToast();
  const { activeAccountId, adAccounts, activeAccountLoading } = useCampaign();
  const [month, setMonth] = useState(monthValue());
  const [period, setPeriod] = useState('mtd');
  const [customFrom, setCustomFrom] = useState('');
  const [customTo, setCustomTo] = useState('');
  const [summary, setSummary] = useState(null);
  const [months, setMonths] = useState([]);
  const [loading, setLoading] = useState(true);
  const [monthsLoading, setMonthsLoading] = useState(true);
  const [monthsError, setMonthsError] = useState('');
  // Remembers whether the event breakdown was left open, per Joel's request.
  const [showEvents, setShowEvents] = useState(() => localStorage.getItem('pnlShowEvents') === '1');
  // Bumped on every load. Each chain checks it still owns the latest request
  // before writing state, so switching account or period mid-flight can't have
  // the slower, older response land last and overwrite the newer numbers.
  const loadToken = useRef(0);
  const [loadError, setLoadError] = useState('');
  const [modalEntry, setModalEntry] = useState(null);
  const [showModal, setShowModal] = useState(false);
  const [deleteEntry, setDeleteEntry] = useState(null);

  const activeAccount = adAccounts.find(account => {
    const raw = account.id || account.account_id || '';
    return (raw.startsWith('act_') ? raw : `act_${raw}`) === activeAccountId;
  });

  // The two fetches are deliberately NOT awaited together. /pnl/months walks six
  // months of Meta + revenue calls and took 12-24s in production; sharing one
  // loading flag with the summary meant the whole page sat blank behind it. They
  // now render independently, each with its own loading and error state.
  const load = useCallback(() => {
    if (activeAccountLoading || !activeAccountId) {
      // Without this the flags stay true forever when there is no account to
      // load — e.g. account resolution failed — and the page reads as loading.
      setLoading(false);
      setMonthsLoading(false);
      return;
    }
    const token = ++loadToken.current;
    const current = () => loadToken.current === token;
    setLoadError('');

    const params = new URLSearchParams({ ad_account_id: activeAccountId, period });
    if (period === 'custom') {
      if (!customFrom || !customTo) {
        setSummary(null);
        setMonths([]);
        setLoading(false);
        setMonthsLoading(false);
        setLoadError('Choose a start and end date to load a custom Profit/Loss range');
        return;
      }
      params.set('date_from', customFrom);
      params.set('date_to', customTo);
    } else {
      params.set('month', month);
    }

    setLoading(true);
    setSummary(null);
    authFetch(`${API_URL}/pnl/summary?${params}`)
      .then(res => {
        if (!res.ok) throw new Error('Profit/Loss summary unavailable');
        return res.json();
      })
      .then(data => { if (current()) setSummary(data); })
      .catch(err => {
        if (!current()) return;
        setSummary(null);
        setLoadError(err.message || 'Failed to load Profit/Loss');
        showError(err.message || 'Failed to load Profit/Loss');
      })
      .finally(() => { if (current()) setLoading(false); });

    setMonthsLoading(true);
    setMonths([]);
    setMonthsError('');
    authFetch(`${API_URL}/pnl/months?ad_account_id=${encodeURIComponent(activeAccountId)}&limit=6`)
      .then(res => {
        if (!res.ok) throw new Error('Profit/Loss month history unavailable');
        return res.json();
      })
      .then(data => { if (current()) setMonths(data); })
      .catch(() => {
        if (!current()) return;
        setMonths([]);
        setMonthsError('Month history unavailable. The figures above are unaffected.');
      })
      .finally(() => { if (current()) setMonthsLoading(false); });
  }, [activeAccountId, activeAccountLoading, customFrom, customTo, month, period, showError]);

  useEffect(() => { load(); }, [load]);

  const deleteCost = async (entry) => {
    try {
      const res = await authFetch(`${API_URL}/pnl/costs/${entry.id}`, { method: 'DELETE' });
      if (!res.ok) throw new Error('Failed to delete cost');
      showSuccess('Cost deleted');
      load();
    } catch (err) {
      showError(err.message || 'Failed to delete cost');
    }
  };

  const exportCsv = () => {
    const rowsToExport = period === 'custom' && summary ? [summary] : months;
    const header = ['Period', 'Date From', 'Date To', 'Spend', 'Billable Revenue', 'Costs', 'Net Profit', 'Margin', 'ROAS', 'Data Incomplete'];
    const rows = rowsToExport.map(row => [
      row.period_label,
      row.date_from,
      row.date_to,
      row.spend,
      row.revenue,
      row.other_costs,
      row.net_profit,
      row.margin ?? '',
      row.roas ?? '',
      row.data_incomplete ? 'yes' : 'no',
    ]);
    const csv = [header, ...rows].map(row => row.map(cell => `"${String(cell).replace(/"/g, '""')}"`).join(',')).join('\n');
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }));
    const a = document.createElement('a');
    a.href = url;
    a.download = `pnl-${activeAccountId}-${month}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const isGross = summary && !summary.has_costs;
  const isIncomplete = summary?.data_incomplete;
  const netTone = isGross || isIncomplete ? 'neutral' : summary?.net_profit > 0 ? 'good' : summary?.net_profit < 0 ? 'bad' : 'neutral';

  return (
    <div className="mx-auto max-w-7xl space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <h1 className="flex items-center gap-2 text-2xl font-bold text-gray-900">
            <DollarSign size={26} className="text-green-600" />
            Profit/Loss
          </h1>
          {/* One meta line instead of a stacked subhead + account label — three
              stacked lines against the period controls read as clutter. Source
              names are derived so they stay right when the provider changes. */}
          <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-sm text-gray-500">
            <AccountLabel account={activeAccount} />
            {activeAccount && <span className="text-gray-300">|</span>}
            <span>
              Spend from Meta · Revenue from {revenueSourceName(summary?.revenue_source)} · Net of your costs
            </span>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {period !== 'custom' ? (
            <input type="month" value={month} onChange={e => setMonth(e.target.value)} className="rounded-lg border border-gray-200 px-3 py-2 text-sm" />
          ) : (
            <>
              <input type="date" value={customFrom} onChange={e => setCustomFrom(e.target.value)} className="rounded-lg border border-gray-200 px-3 py-2 text-sm" />
              <input type="date" value={customTo} onChange={e => setCustomTo(e.target.value)} className="rounded-lg border border-gray-200 px-3 py-2 text-sm" />
            </>
          )}
          <select value={period} onChange={e => setPeriod(e.target.value)} className="rounded-lg border border-gray-200 px-3 py-2 text-sm">
            <option value="mtd">MTD</option>
            <option value="month">Month</option>
            <option value="custom">Custom range</option>
          </select>
          <button onClick={load} disabled={loading} className="flex items-center gap-2 rounded-lg border border-gray-200 px-3 py-2 text-sm text-gray-600 hover:bg-gray-50 disabled:opacity-50">
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
            Refresh
          </button>
        </div>
      </div>

      {loadError && !loading && (
        <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {loadError}. The previous Profit/Loss figures were cleared so stale account data is not shown.
        </div>
      )}

      {summary?.data_incomplete && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          Data incomplete: {summary.errors?.join(', ') || 'one or more sources are unavailable'}. Treat this period as unavailable until the source recovers.
        </div>
      )}

      {isGross && !isIncomplete && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm font-medium text-amber-800">
          Gross view only: no cost ledger entries are applied yet, so profit excludes retainers, commissions, tooling, and creative costs.
        </div>
      )}

      {/* Stepped breakpoints: the old md:grid-cols-5 jumped straight from one
          column to five, which squeezed the tiles unreadably once the fixed
          sidebar took its 16rem. */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
        <KpiTile label="Ad Spend" value={loading ? '--' : money(summary?.spend)} caption="Meta" badge={summary?.spend == null && !loading ? 'Unavailable' : null} />
        <KpiTile label="Billable Revenue" value={loading ? '--' : money(summary?.revenue)} caption={revenueSourceLabel(summary?.revenue_source)} badge={isRevenueFallback(summary?.revenue_source) ? 'Fallback' : null} />
        <KpiTile label="Other Costs" value={loading ? '--' : money(summary?.other_costs)} caption={summary?.has_costs ? `${summary.costs.length} entries` : 'Gross until costs logged'} badge={isGross ? 'Gross' : null} />
        <KpiTile label="Net Profit" value={loading ? '--' : money(summary?.net_profit)} caption={summary?.has_costs ? 'Net' : 'Gross'} tone={netTone} badge={isIncomplete ? 'Incomplete' : isGross ? 'Gross' : null} />
        <KpiTile label="Margin" value={loading ? '--' : pct(summary?.margin)} caption="net ÷ revenue" tone={netTone} badge={isIncomplete ? 'Incomplete' : null} />
      </div>

      {summary?.unattributed_revenue > 0 && (
        <div className="rounded-xl border border-gray-200 bg-gray-50 px-4 py-3 text-sm text-gray-600">
          Billable Revenue above <span className="font-medium">includes</span> {money(summary.unattributed_revenue, 2)} that Switchboard could not tie to a specific ad set. It counts toward this account, so the total matches the Switchboard portal — it just can&apos;t be traced to a single ad set.
        </div>
      )}

      {summary?.unmapped_adsets > 0 && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          {summary.unmapped_adsets} ad set{summary.unmapped_adsets !== 1 ? 's' : ''} have no revenue rows for this period. Revenue may be incomplete.
        </div>
      )}

      <div className="rounded-xl border border-gray-200 bg-white shadow-sm">
        <div className="flex items-center justify-between border-b border-gray-100 px-5 py-4">
          <div>
            <h2 className="font-semibold text-gray-900">Other Costs</h2>
            <p className="text-xs text-gray-400">Retainers, commissions, tooling, creative credits, and platform costs.</p>
          </div>
          <button onClick={() => { setModalEntry(null); setShowModal(true); }} className="flex items-center gap-2 rounded-lg bg-indigo-600 px-3 py-2 text-sm font-medium text-white hover:bg-indigo-700">
            <Plus size={14} />
            Add cost
          </button>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="border-b border-gray-100 bg-gray-50 text-xs font-semibold uppercase tracking-wide text-gray-500">
              <tr>
                <th className="px-5 py-3 text-left">Label</th>
                <th className="px-3 py-3 text-left">Category</th>
                <th className="px-3 py-3 text-left">Type</th>
                <th className="px-3 py-3 text-right">Amount</th>
                <th className="px-3 py-3 text-right">This Account</th>
                <th className="px-5 py-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {loading ? (
                <tr><td colSpan={6} className="px-5 py-8 text-center text-sm text-gray-400">Loading costs...</td></tr>
              ) : summary?.costs?.length ? summary.costs.map(entry => (
                <tr key={entry.id} className="hover:bg-gray-50">
                  <td className="px-5 py-3">
                    <div className="font-medium text-gray-900">{entry.label}</div>
                    {entry.ad_account_id == null && <div className="mt-1 inline-flex rounded-full bg-blue-50 px-2 py-0.5 text-[11px] font-medium text-blue-600">All accounts</div>}
                  </td>
                  <td className="px-3 py-3 text-gray-600">{entry.category}</td>
                  <td className="px-3 py-3 text-gray-600">{entry.cost_type.replaceAll('_', ' ')}</td>
                  <td className="px-3 py-3 text-right text-gray-700">{entry.cost_type.startsWith('pct_') ? `${entry.amount}%` : money(entry.amount, 2)}</td>
                  <td className="px-3 py-3 text-right font-semibold text-gray-900">{money(entry.resolved_amount, 2)}</td>
                  <td className="px-5 py-3">
                    <div className="flex justify-end gap-2">
                      <button onClick={() => { setModalEntry(entry); setShowModal(true); }} className="rounded-lg p-1.5 text-gray-400 hover:bg-gray-100 hover:text-gray-700" title="Edit"><Edit2 size={14} /></button>
                      <button onClick={() => setDeleteEntry(entry)} className="rounded-lg p-1.5 text-gray-400 hover:bg-red-50 hover:text-red-600" title="Delete"><Trash2 size={14} /></button>
                    </div>
                  </td>
                </tr>
              )) : (
                <tr>
                  <td colSpan={6} className="px-5 py-8 text-center text-sm text-gray-400">
                    No costs logged for {summary?.period_label || 'this period'}. Net profit above is gross of retainers, tooling, and creative spend.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Collapsed by default and hidden entirely when there's nothing to show, so
          the main view is untouched unless Joel goes looking. Approved by Joel
          2026-07-29 on the condition it doesn't clutter. RedTrack accounts return
          no split, so this only appears for Switchboard-backed accounts. */}
      {summary?.event_breakdown?.length > 0 && (
        <div className="rounded-xl border border-gray-200 bg-white shadow-sm">
          <button
            onClick={() => setShowEvents(v => { localStorage.setItem('pnlShowEvents', v ? '0' : '1'); return !v; })}
            className="flex w-full items-center justify-between px-5 py-4 text-left hover:bg-gray-50"
          >
            <div>
              <h2 className="flex items-center gap-1.5 font-semibold text-gray-900">
                {showEvents ? <ChevronDown size={16} className="text-gray-400" /> : <ChevronRight size={16} className="text-gray-400" />}
                Revenue by event type
              </h2>
              <p className="ml-[22px] text-xs text-gray-400">
                How the billable revenue above splits across the payable events Switchboard reports.
              </p>
            </div>
            <span className="text-xs text-gray-400">{summary.event_breakdown.length} types</span>
          </button>
          {showEvents && (
            <div className="overflow-x-auto border-t border-gray-100">
              <table className="w-full text-sm">
                <thead className="border-b border-gray-100 bg-gray-50 text-xs font-semibold uppercase tracking-wide text-gray-500">
                  <tr>
                    <th className="px-5 py-3 text-left">Event</th>
                    <th className="px-5 py-3 text-right">Count</th>
                    <th className="px-5 py-3 text-right">Revenue</th>
                    <th className="px-5 py-3 text-right">Share</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-50">
                  {summary.event_breakdown.map(row => (
                    <tr key={row.event} className="hover:bg-gray-50">
                      <td className="px-5 py-3 font-medium text-gray-900">{row.event}</td>
                      <td className="px-5 py-3 text-right text-gray-600">{row.events.toLocaleString('en-US')}</td>
                      <td className="px-5 py-3 text-right font-semibold text-gray-900">{money(row.revenue, 2)}</td>
                      <td className="px-5 py-3 text-right text-gray-500">
                        {summary.revenue > 0 ? `${((row.revenue / summary.revenue) * 100).toFixed(1)}%` : '--'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      <div className="rounded-xl border border-gray-200 bg-white shadow-sm">
        <div className="flex items-center justify-between border-b border-gray-100 px-5 py-4">
          <h2 className="font-semibold text-gray-900">Month Over Month</h2>
          <button onClick={exportCsv} className="flex items-center gap-2 rounded-lg border border-gray-200 px-3 py-2 text-sm text-gray-600 hover:bg-gray-50">
            <Download size={14} />
            Export CSV
          </button>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="border-b border-gray-100 bg-gray-50 text-xs font-semibold uppercase tracking-wide text-gray-500">
              <tr>
                {['Month', 'Spend', 'Billable Revenue', 'Costs', 'Net', 'Margin', 'ROAS'].map((col, idx) => (
                  <th key={col} className={`px-5 py-3 ${idx === 0 ? 'text-left' : 'text-right'}`}>{col}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {monthsLoading ? (
                <tr><td colSpan={7} className="px-5 py-8 text-center text-sm text-gray-400">Loading month history — this walks six months of Meta and revenue data and can take a while.</td></tr>
              ) : monthsError ? (
                <tr><td colSpan={7} className="px-5 py-8 text-center text-sm text-amber-700">{monthsError}</td></tr>
              ) : !months.length ? (
                <tr><td colSpan={7} className="px-5 py-8 text-center text-sm text-gray-400">No month history available.</td></tr>
              ) : months.map(row => {
                const positive = row.net_profit > 0;
                return (
                  <tr key={`${row.date_from}-${row.date_to}`} className="hover:bg-gray-50">
                    <td className="px-5 py-3 font-medium text-gray-900">{row.period_label}</td>
                    <td className="px-5 py-3 text-right">{money(row.spend)}</td>
                    <td className="px-5 py-3 text-right">{money(row.revenue)}</td>
                    <td className="px-5 py-3 text-right">{money(row.other_costs)}</td>
                    <td className={`px-5 py-3 text-right font-semibold ${positive ? 'text-green-600' : 'text-red-600'}`}>{money(row.net_profit)}</td>
                    <td className="px-5 py-3 text-right">{pct(row.margin)}</td>
                    <td className="px-5 py-3 text-right">{row.roas != null ? `${Number(row.roas).toFixed(2)}x` : '--'}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {showModal && (
        <CostModal
          entry={modalEntry}
          summary={summary}
          activeAccountId={activeAccountId}
          onClose={() => setShowModal(false)}
          onSaved={() => { setShowModal(false); load(); }}
        />
      )}

      {deleteEntry && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4 backdrop-blur-sm">
          <div className="w-full max-w-md rounded-xl bg-white p-5 shadow-xl">
            <h2 className="text-lg font-semibold text-gray-900">Delete cost?</h2>
            <p className="mt-2 text-sm text-gray-500">
              {deleteEntry.ad_account_id == null
                ? `This removes "${deleteEntry.label}" from every account's Profit/Loss ledger. The underlying Meta and revenue data will not be affected.`
                : `This removes "${deleteEntry.label}" from this account's Profit/Loss ledger. The underlying Meta and revenue data will not be affected.`
              }
            </p>
            <div className="mt-5 flex justify-end gap-2">
              <button onClick={() => setDeleteEntry(null)} className="rounded-lg border border-gray-200 px-4 py-2 text-sm text-gray-600 hover:bg-gray-50">
                Cancel
              </button>
              <button
                onClick={() => {
                  const target = deleteEntry;
                  setDeleteEntry(null);
                  deleteCost(target);
                }}
                className="rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700"
              >
                Delete
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
