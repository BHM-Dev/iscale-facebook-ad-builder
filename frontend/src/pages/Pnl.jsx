import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ChevronDown, ChevronRight, DollarSign, Download, Edit2, ExternalLink, Plus, RefreshCw, Trash2, X } from 'lucide-react';
import { authFetch } from '../lib/facebookApi';
import { useCampaign } from '../context/CampaignContext';
import { useToast } from '../context/ToastContext';

const DETAILED_PNL_SHEET_URL = 'https://docs.google.com/spreadsheets/d/175im8vEPPtDYilFyusBSFoLXOreRfrv-7vfE3jsdPdc/edit?gid=0#gid=0';

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
  if (source === 'not_tracked') return 'Not tracked (Everflow only)';
  if (source === 'everflow_unavailable') return 'Switchboard unavailable';
  if (source === 'bhm_everflow_live') return 'BHM Everflow';
  if (source === 'bhm_everflow_unavailable') return 'BHM Everflow unavailable';
  if (source.startsWith('bhm_everflow')) return 'BHM Everflow';
  if (source === 'mixed') return 'Multiple sources';
  if (source.startsWith('everflow')) return source === 'everflow_live' ? 'Switchboard' : `Switchboard · ${source.replace('everflow_', '').replaceAll('_', ' ')}`;
  return source.replaceAll('_', ' ');
}

// Provider name only, without the live/fallback qualifier — for the page subhead,
// where the qualifier already appears on the Billable Revenue tile.
function revenueSourceName(source) {
  if (!source || source === 'none' || source === 'not_tracked') return 'Switchboard';
  if (source.startsWith('everflow')) return 'Switchboard';
  if (source.startsWith('bhm_everflow')) return 'BHM Everflow';
  if (source === 'mixed') return 'Multiple sources';
  return source.replaceAll('_', ' ');
}

// "not_tracked" isn't a degraded fetch — it's Everflow's intentional answer for
// an account with no offer mapping (billable revenue is Everflow-only, no
// RedTrack fallback). Only flag an actual live-pull failure as "Fallback".
function isRevenueFallback(source) {
  return source === 'everflow_unavailable' || source === 'bhm_everflow_unavailable';
}

function monthValue(date = new Date()) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`;
}

function dateValue(date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
}

const RANGE_PERIODS = new Set(['today', 'yesterday', 'last_7d', 'last_30d', 'last_month']);

function presetRange(period, now = new Date()) {
  const end = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  if (period === 'today') return { from: dateValue(end), to: dateValue(end) };
  if (period === 'yesterday') {
    end.setDate(end.getDate() - 1);
    return { from: dateValue(end), to: dateValue(end) };
  }
  if (period === 'last_month') {
    const lastDay = new Date(end.getFullYear(), end.getMonth(), 0);
    return { from: dateValue(new Date(lastDay.getFullYear(), lastDay.getMonth(), 1)), to: dateValue(lastDay) };
  }
  const days = period === 'last_30d' ? 29 : 6;
  const start = new Date(end);
  start.setDate(start.getDate() - days);
  return { from: dateValue(start), to: dateValue(end) };
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

function profitClass(value) {
  if (value == null) return 'text-gray-400';
  return value >= 0 ? 'text-emerald-700' : 'text-red-600';
}

// All accounts view: one line per advertiser campaign, with the Meta accounts that run it. Gross only — monthly
// costs are business-wide and stay in Net Profit above. Lines add up to the tiles.
function CampaignBreakdown({ campaigns, adAccounts = [] }) {
  const [open, setOpen] = useState({});
  const toggle = key => setOpen(prev => ({ ...prev, [key]: !prev[key] }));
  const nameFor = (id) => {
    const match = adAccounts.find(account => {
      const raw = String(account.id || account.account_id || '');
      return (raw.startsWith('act_') ? raw : `act_${raw}`) === id;
    });
    return match?.name || id;
  };
  return (
    <div className="rounded-xl border border-gray-200 bg-white shadow-sm" data-testid="pnl-campaigns">
      <div className="border-b border-gray-100 px-5 py-4">
        <h2 className="font-semibold text-gray-900">By campaign</h2>
        <p className="text-xs text-gray-400">Gross profit per advertiser campaign. Monthly costs come off once, in Net Profit above.</p>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] text-sm">
          <thead className="border-b border-gray-100 bg-gray-50 text-xs font-semibold uppercase tracking-wide text-gray-500">
            <tr>
              <th className="px-5 py-2.5 text-left">Campaign</th>
              <th className="px-3 py-2.5 text-right">Spend</th>
              <th className="px-3 py-2.5 text-right">Revenue</th>
              <th className="px-3 py-2.5 text-right">Gross profit</th>
              <th className="px-5 py-2.5 text-right">ROAS</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {campaigns.map(campaign => {
              const active = campaign.accounts.filter(a => (a.spend || 0) > 0 || (a.revenue || 0) > 0);
              const shown = active.length ? active : campaign.accounts;
              const idle = campaign.accounts.length - shown.length;
              const expandable = campaign.accounts.length > 1 || campaign.unplaced_revenue > 0;
              const isOpen = !!open[campaign.key];
              return (
                <React.Fragment key={campaign.key}>
                  <tr
                    className={expandable ? 'cursor-pointer hover:bg-gray-50' : ''}
                    onClick={expandable ? () => toggle(campaign.key) : undefined}
                    onKeyDown={expandable ? (event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); toggle(campaign.key); } } : undefined}
                    tabIndex={expandable ? 0 : undefined}
                    aria-expanded={expandable ? isOpen : undefined}
                  >
                    <td className="px-5 py-3">
                      <div className="flex items-start gap-1.5">
                        {expandable ? (isOpen ? <ChevronDown size={14} className="mt-0.5 shrink-0 text-gray-400" /> : <ChevronRight size={14} className="mt-0.5 shrink-0 text-gray-400" />) : <span className="w-3.5 shrink-0" />}
                        <div>
                          <div className="font-medium text-gray-900">{campaign.vertical} <span className="font-normal text-gray-500">· {campaign.name}</span></div>
                          {shown.length > 0 && (
                            <div className="mt-0.5 text-xs text-gray-400">
                              {shown.map(a => nameFor(a.ad_account_id)).join(', ')}{idle > 0 ? ` (+${idle} idle)` : ''}
                            </div>
                          )}
                          {campaign.key === 'unplaced' && (
                            <div className="mt-0.5 text-xs text-gray-400">Counted in the totals above; this period was closed before the campaign split existed.</div>
                          )}
                        </div>
                      </div>
                    </td>
                    <td className="px-3 py-3 text-right tabular-nums">{money(campaign.spend)}</td>
                    <td className="px-3 py-3 text-right tabular-nums">
                      {campaign.revenue_tracked ? money(campaign.revenue) : <span className="text-xs text-amber-700" title="No revenue source is connected for this campaign yet, so profit can't be calculated.">Not connected</span>}
                    </td>
                    <td className={`px-3 py-3 text-right font-medium tabular-nums ${profitClass(campaign.gross_profit)}`}>{money(campaign.gross_profit)}</td>
                    <td className="px-5 py-3 text-right tabular-nums text-gray-600">
                      {campaign.roas != null ? `${campaign.roas.toFixed(2)}x` : '--'}
                      {campaign.data_incomplete && <span className="ml-1.5 rounded bg-amber-50 px-1.5 py-0.5 text-[10px] font-semibold text-amber-700" title="Meta spend or revenue for one of these accounts didn't load, so this line is missing part of its numbers.">Incomplete</span>}
                    </td>
                  </tr>
                  {isOpen && campaign.accounts.map(account => (
                    <tr key={account.ad_account_id} className="bg-gray-50/60 text-xs text-gray-600">
                      <td className="py-2 pl-11 pr-5">{nameFor(account.ad_account_id)} <span className="font-mono text-[11px] text-gray-400">{account.ad_account_id}</span></td>
                      <td className="px-3 py-2 text-right tabular-nums">{money(account.spend)}</td>
                      <td className="px-3 py-2 text-right tabular-nums">{money(account.revenue)}</td>
                      <td className={`px-3 py-2 text-right tabular-nums ${profitClass(account.gross_profit)}`}>{money(account.gross_profit)}</td>
                      <td className="px-5 py-2" />
                    </tr>
                  ))}
                  {isOpen && campaign.unplaced_revenue > 0 && (
                    <tr className="bg-gray-50/60 text-xs text-gray-500">
                      <td className="py-2 pl-11 pr-5">Revenue we couldn&apos;t match to an ad set</td>
                      <td className="px-3 py-2" />
                      <td className="px-3 py-2 text-right tabular-nums">{money(campaign.unplaced_revenue)}</td>
                      <td className="px-3 py-2" colSpan={2} />
                    </tr>
                  )}
                </React.Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// The P&L read left to right as an equation that ends on the answer: Revenue − Spend = Gross (− Costs = Net).
// The last cell is the one number the page exists for, so it is the only one that is large and tinted.
function ProfitStatement({ cells, loading }) {
  return (
    <div className="overflow-hidden rounded-xl border border-gray-200 bg-white shadow-sm" data-testid="pnl-statement">
      <div className={`grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)] ${cells.length === 5 ? 'lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,1fr)_minmax(0,1fr)_minmax(0,1.35fr)]' : 'lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,1.35fr)]'}`}>
        {cells.map((cell, idx) => {
          const last = idx === cells.length - 1;
          const toneClass = cell.tone === 'good' ? 'text-emerald-700' : cell.tone === 'bad' ? 'text-red-600' : 'text-gray-900';
          const tint = last ? (cell.tone === 'good' ? 'bg-emerald-50/70' : cell.tone === 'bad' ? 'bg-red-50/70' : 'bg-gray-50') : '';
          return (
            <div
              key={cell.label}
              className={`relative px-5 py-4 ${tint} ${last ? 'col-span-2 border-t lg:col-span-1 lg:border-t-0' : ''} ${idx > 0 ? 'lg:border-l' : ''} ${idx % 2 === 1 && !last ? 'border-l' : ''} ${idx >= 2 && !last ? 'border-t lg:border-t-0' : ''} border-gray-100`}
            >
              {idx > 0 && (
                <span aria-hidden="true" className="absolute -left-3 top-1/2 z-10 hidden h-6 w-6 -translate-y-1/2 items-center justify-center rounded-full border border-gray-200 bg-white text-xs font-semibold text-gray-400 lg:flex">
                  {cell.op}
                </span>
              )}
              <div className="flex items-center gap-2">
                <span className={`text-[11px] font-semibold uppercase tracking-wide ${last ? 'text-gray-700' : 'text-gray-500'}`}>{cell.label}</span>
                {cell.badge && <span className="rounded-full bg-amber-100 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide text-amber-700">{cell.badge}</span>}
              </div>
              <div className={`mt-1.5 font-bold tabular-nums ${last ? 'text-3xl' : 'text-xl'} ${toneClass}`}>{loading ? '--' : cell.value}</div>
              <div className="mt-1 truncate text-xs text-gray-400" title={loading ? undefined : cell.caption}>{loading ? '\u00a0' : cell.caption}</div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// Footnotes belong to the statement, so they sit tight under it as small text instead of full-width banners
// competing with the numbers. Real data problems still get a banner (see data_incomplete in the page).
function StatementNotes({ notes }) {
  const shown = notes.filter(Boolean);
  if (!shown.length) return null;
  return (
    <ul className="mt-2 space-y-1 px-1 text-xs leading-5 text-gray-500" data-testid="pnl-notes">
      {shown.map((note, idx) => (
        <li key={idx} className={`flex gap-1.5 ${note.tone === 'warn' ? 'text-amber-700' : ''}`}>
          <span aria-hidden="true" className="text-gray-300">•</span>
          <span>{note.text}</span>
        </li>
      ))}
    </ul>
  );
}

const COST_TYPE_LABEL = Object.fromEntries(COST_TYPES);

// The ledger behind the Costs cell in the statement. A list, not a 6-column table: in the side column the
// only things that matter are what it is and what it cost this period.
function CostsLedger({ costs, total, loading, periodLabel, onAdd, onEdit, onDelete }) {
  return (
    <section className="rounded-xl border border-gray-200 bg-white shadow-sm" data-testid="pnl-costs">
      <div className="flex items-center justify-between gap-3 border-b border-gray-100 px-4 py-3.5">
        <div>
          <h2 className="font-semibold text-gray-900">Monthly costs</h2>
          <p className="text-xs text-gray-400">Retainers, commissions, tooling, creative.</p>
        </div>
        <button onClick={onAdd} className="flex shrink-0 items-center gap-1.5 rounded-lg border border-indigo-200 bg-indigo-50 px-2.5 py-1.5 text-xs font-semibold text-indigo-700 hover:bg-indigo-100">
          <Plus size={13} />
          Add cost
        </button>
      </div>
      {loading ? (
        <div className="px-4 py-8 text-center text-sm text-gray-400">Loading costs...</div>
      ) : costs?.length ? (
        <>
          <ul className="divide-y divide-gray-100">
            {costs.map(entry => (
              <li key={entry.id} className="group flex items-start gap-3 px-4 py-3">
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium text-gray-900" title={entry.label}>{entry.label}</div>
                  <div className="mt-0.5 text-xs text-gray-400">
                    <span className="capitalize">{entry.category}</span>
                    {' · '}
                    {entry.cost_type.startsWith('pct_') ? `${entry.amount}% ${(COST_TYPE_LABEL[entry.cost_type] || '').replace('% ', '')}` : COST_TYPE_LABEL[entry.cost_type] || entry.cost_type.replaceAll('_', ' ')}
                    {entry.ad_account_id == null && ' · All accounts'}
                  </div>
                  {entry.cost_type === 'pct_of_profit' && entry.profit_threshold > 0 && (
                    <div className="mt-0.5 text-[11px] text-gray-400">
                      Above {money(entry.profit_threshold, 0)} net per period
                      {entry.profit_base != null && ` · this period ${money(entry.profit_base, 2)}`}
                    </div>
                  )}
                </div>
                <div className="flex shrink-0 flex-col items-end">
                  {entry.withheld ? (
                    <span className="text-xs font-medium text-amber-700" title="Spend or revenue didn't load for this period, so the profit this is a share of isn't known yet">Withheld: data incomplete</span>
                  ) : (
                    <span className="text-sm font-semibold tabular-nums text-gray-900">{money(entry.resolved_amount, 2)}</span>
                  )}
                  <div className="mt-1 flex gap-1 opacity-60 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100">
                    <button onClick={() => onEdit(entry)} className="rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-700" title="Edit" aria-label={`Edit ${entry.label}`}><Edit2 size={13} /></button>
                    <button onClick={() => onDelete(entry)} className="rounded p-1 text-gray-400 hover:bg-red-50 hover:text-red-600" title="Delete" aria-label={`Delete ${entry.label}`}><Trash2 size={13} /></button>
                  </div>
                </div>
              </li>
            ))}
          </ul>
          <div className="flex items-center justify-between border-t border-gray-100 bg-gray-50/60 px-4 py-2.5 text-sm">
            <span className="text-gray-500">Total this period</span>
            <span className="font-semibold tabular-nums text-gray-900">{money(total, 2)}</span>
          </div>
        </>
      ) : (
        <div className="px-4 py-8 text-center text-sm text-gray-400">
          No costs logged for {periodLabel || 'this period'}. Net profit is gross of retainers, tooling, and creative spend.
        </div>
      )}
    </section>
  );
}

// Collapsed by default and hidden entirely when there's nothing to show (Joel, 2026-07-29: only if it doesn't
// clutter). RedTrack accounts return no split, so this only appears for Switchboard-backed accounts.
function EventBreakdown({ rows, revenue, open, onToggle }) {
  return (
    <section className="rounded-xl border border-gray-200 bg-white shadow-sm">
      <button onClick={onToggle} aria-expanded={open} className="flex w-full items-center justify-between gap-3 rounded-xl px-4 py-3.5 text-left hover:bg-gray-50">
        <div>
          <h2 className="flex items-center gap-1.5 font-semibold text-gray-900">
            {open ? <ChevronDown size={16} className="text-gray-400" /> : <ChevronRight size={16} className="text-gray-400" />}
            Revenue by event type
          </h2>
          <p className="ml-[22px] text-xs text-gray-400">How revenue splits across Switchboard's payable events.</p>
        </div>
        <span className="shrink-0 text-xs text-gray-400">{rows.length} types</span>
      </button>
      {open && (
        <ul className="divide-y divide-gray-100 border-t border-gray-100">
          {rows.map(row => {
            const share = revenue > 0 ? (row.revenue / revenue) * 100 : null;
            return (
              <li key={row.event} className="px-4 py-2.5">
                <div className="flex items-baseline justify-between gap-3 text-sm">
                  <span className="truncate font-medium text-gray-900" title={row.event}>{row.event}</span>
                  <span className="shrink-0 font-semibold tabular-nums text-gray-900">{money(row.revenue, 2)}</span>
                </div>
                <div className="mt-1.5 flex items-center gap-2">
                  <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-gray-100">
                    <div className="h-full rounded-full bg-indigo-400" style={{ width: `${Math.max(0, Math.min(100, share || 0))}%` }} />
                  </div>
                  <span className="w-24 shrink-0 text-right text-[11px] tabular-nums text-gray-400">
                    {row.events.toLocaleString('en-US')} · {share != null ? `${share.toFixed(1)}%` : '--'}
                  </span>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

function CostModal({ entry, summary, activeAccountId, onClose, onSaved }) {
  const { showError, showSuccess } = useToast();
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState(() => ({
    ad_account_id: entry ? (entry.ad_account_id || '') : '',
    label: entry?.label ?? '',
    category: entry?.category ?? 'other',
    cost_type: entry?.cost_type ?? 'one_off',
    amount: entry?.amount ?? '',
    allocation_method: entry?.allocation_method ?? 'full',
    effective_from: entry?.effective_from ?? firstOfMonth(monthValue()),
    effective_to: entry?.effective_to ?? '',
    notes: entry?.notes ?? '',
    profit_threshold: entry?.profit_threshold ?? '',
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
  const isProfitShare = form.cost_type === 'pct_of_profit';
  const threshold = isProfitShare ? Number(form.profit_threshold || 0) : 0;
    const previewShareBase = isProfitShare ? Math.max(previewBase - threshold, 0) : previewBase;
  const previewAmount = isPercent ? previewShareBase * (Number(form.amount || 0) / 100) : Number(form.amount || 0);

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
        effective_to: form.cost_type === 'one_off' ? form.effective_from : (form.effective_to || null),
        profit_threshold: isProfitShare && form.profit_threshold !== '' ? Number(form.profit_threshold) : null,
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
              <option value="">All ad accounts</option>
              {activeAccountId && <option value={activeAccountId}>Active account only</option>}
            </select>
          </label>
          {isAllAccounts && (
            <label>
              <span className="text-xs font-semibold uppercase tracking-wide text-gray-500">Allocation</span>
              <select value={form.allocation_method} onChange={e => setForm({ ...form, allocation_method: e.target.value })} className="mt-1 w-full rounded-lg border border-gray-200 px-3 py-2 text-sm">
                <option value="full">Full amount (don&apos;t split)</option>
                <option value="by_spend">Split by spend share</option>
                <option value="even">Split evenly</option>
              </select>
              <span className="mt-1 block text-[11px] text-gray-400">
                {form.allocation_method === 'full'
                  ? 'The whole cost is charged to the month.'
                  : 'The cost is divided across accounts, so this account carries only part of it.'}
              </span>
            </label>
          )}
          <label>
            <span className="text-xs font-semibold uppercase tracking-wide text-gray-500">{form.cost_type === 'one_off' ? 'Date' : 'Effective from'}</span>
            <input type="date" value={form.effective_from} onChange={e => setForm({ ...form, effective_from: e.target.value })} className="mt-1 w-full rounded-lg border border-gray-200 px-3 py-2 text-sm" />
          </label>
          {form.cost_type !== 'one_off' && <label>
            <span className="text-xs font-semibold uppercase tracking-wide text-gray-500">Effective to</span>
            <input type="date" value={form.effective_to} onChange={e => setForm({ ...form, effective_to: e.target.value })} className="mt-1 w-full rounded-lg border border-gray-200 px-3 py-2 text-sm" />
          </label>}
          {isProfitShare && (
            <label className="sm:col-span-2">
              <span className="text-xs font-semibold uppercase tracking-wide text-gray-500">Net profit threshold (commission applies above this)</span>
              <input type="number" min="0" step="0.01" placeholder="0 = always pays" value={form.profit_threshold} onChange={e => setForm({ ...form, profit_threshold: e.target.value })} className="mt-1 w-full rounded-lg border border-gray-200 px-3 py-2 text-sm" />
              <span className="mt-1 block text-[11px] text-gray-400">
                Each period, the percent applies only to net profit (after retainer and all other costs) above this amount. At or below it the cost is $0.
              </span>
            </label>
          )}
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
                ? `${Number(form.amount || 0)}% of ${money(previewShareBase, 2)}${threshold > 0 ? ` (net profit ${money(previewBase, 2)} above the ${money(threshold, 0)} threshold)` : ''} = ${money(previewAmount, 2)}`
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
  const [scope, setScope] = useState('all');
  const [month, setMonth] = useState(monthValue());
  const [period, setPeriod] = useState('mtd');
  const [customFrom, setCustomFrom] = useState('');
  const [customTo, setCustomTo] = useState('');
  const [summary, setSummary] = useState(null);
  const [months, setMonths] = useState([]);
  const [loading, setLoading] = useState(true);
  const [monthsLoading, setMonthsLoading] = useState(true);
  const [monthsError, setMonthsError] = useState('');
  const [loadingSlow, setLoadingSlow] = useState(false);
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
  const isAllScope = scope === 'all';
  const requestAccountId = isAllScope ? 'all' : activeAccountId;
  const isDateRangePeriod = period === 'custom' || RANGE_PERIODS.has(period);

  // The two fetches are deliberately NOT awaited together. /pnl/months walks six
  // months of Meta + revenue calls and took 12-24s in production; sharing one
  // loading flag with the summary meant the whole page sat blank behind it. They
  // now render independently, each with its own loading and error state.
  const load = useCallback(() => {
    const token = ++loadToken.current;
    if (activeAccountLoading || (!isAllScope && !activeAccountId)) {
      // Without this the flags stay true forever when there is no account to
      // load — e.g. account resolution failed — and the page reads as loading.
      setLoading(false);
      setMonthsLoading(false);
      setSummary(null);
      setMonths([]);
      setMonthsError('');
      setLoadError(activeAccountLoading ? '' : 'No active ad account is available');
      return;
    }
    const current = () => loadToken.current === token;
    setLoadError('');

    const params = new URLSearchParams({ ad_account_id: requestAccountId, period: isDateRangePeriod ? 'custom' : period });
    if (isDateRangePeriod) {
      if (!customFrom || !customTo) {
        setSummary(null);
        setMonths([]);
        setMonthsError('');
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
    authFetch(`${API_URL}/pnl/months?ad_account_id=${encodeURIComponent(requestAccountId)}&limit=6`)
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
  }, [activeAccountId, activeAccountLoading, customFrom, customTo, isAllScope, month, period, requestAccountId, showError]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    if (!loading && !monthsLoading) {
      setLoadingSlow(false);
      return undefined;
    }
    const timer = setTimeout(() => setLoadingSlow(true), 4000);
    return () => clearTimeout(timer);
  }, [loading, monthsLoading]);

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

  const [resyncing, setResyncing] = useState(null);

  const resyncMonth = async (row) => {
    // Closed months are frozen after the first clean fetch; this re-pulls one.
    const monthKey = (row.date_from || '').slice(0, 7);
    if (!monthKey) return;
    setResyncing(monthKey);
    try {
      const res = await authFetch(
        `${API_URL}/pnl/months/${monthKey}/resync?ad_account_id=${encodeURIComponent(requestAccountId)}`,
        { method: 'POST' },
      );
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || 'Re-sync failed');
      }
      showSuccess(`${row.period_label} re-synced`);
      load();
    } catch (err) {
      showError(err.message || 'Re-sync failed');
    } finally {
      setResyncing(null);
    }
  };

  const exportCsv = () => {
    const rowsToExport = period === 'custom' && summary ? [summary] : months;
    const header = isAllScope
      ? ['Period', 'Date From', 'Date To', 'Spend', 'Billable Revenue', 'Gross Profit', 'Costs', 'Net Profit', 'Net Margin', 'ROAS', 'Data Incomplete']
      : ['Period', 'Date From', 'Date To', 'Spend', 'Billable Revenue', 'Gross Profit', 'Gross Margin', 'ROAS', 'Data Incomplete'];
    const rows = rowsToExport.map(row => [
      row.period_label,
      row.date_from,
      row.date_to,
      row.spend,
      row.revenue,
      row.gross_profit,
      ...(isAllScope ? [row.other_costs, row.net_profit] : []),
      row.margin ?? '',
      row.roas ?? '',
      row.data_incomplete ? 'yes' : 'no',
    ]);
    const csv = [header, ...rows].map(row => row.map(cell => `"${String(cell).replace(/"/g, '""')}"`).join(',')).join('\n');
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }));
    const a = document.createElement('a');
    a.href = url;
    a.download = `pnl-${requestAccountId}-${month}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const toggleEvents = () => setShowEvents(v => { try { localStorage.setItem('pnlShowEvents', v ? '0' : '1'); } catch { /* storage blocked */ } return !v; });
  const isIncomplete = summary?.data_incomplete;
  const grossTone = isIncomplete ? 'neutral' : summary?.gross_profit > 0 ? 'good' : summary?.gross_profit < 0 ? 'bad' : 'neutral';
  const netTone = isIncomplete ? 'neutral' : summary?.net_profit > 0 ? 'good' : summary?.net_profit < 0 ? 'bad' : 'neutral';
  const changePeriod = (nextPeriod) => {
    setPeriod(nextPeriod);
    if (RANGE_PERIODS.has(nextPeriod)) {
      const range = presetRange(nextPeriod);
      setCustomFrom(range.from);
      setCustomTo(range.to);
    }
  };

  const monthsSection = (
  <div className="rounded-xl border border-gray-200 bg-white shadow-sm">
    <div className="flex items-center justify-between gap-3 border-b border-gray-100 px-5 py-4">
      <div>
        <h2 className="font-semibold text-gray-900">Month over month</h2>
        <p className="text-xs text-gray-400">
          {isAllScope
            ? 'Closed months store spend and revenue once. Costs stay live, so adding or backdating a cost entry still moves past months\' Net.'
            : 'Closed months store spend and revenue once. Account rows show gross performance only.'}
        </p>
      </div>
      <button onClick={exportCsv} className="flex shrink-0 items-center gap-2 rounded-lg border border-gray-200 px-3 py-2 text-sm text-gray-600 hover:bg-gray-50">
        <Download size={14} />
        Export CSV
      </button>
    </div>
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="border-b border-gray-100 bg-gray-50 text-xs font-semibold uppercase tracking-wide text-gray-500">
          <tr>
            {(isAllScope
              ? ['Month', 'Spend', 'Billable Revenue', 'Gross', 'Costs', 'Net', 'Net Margin', 'ROAS']
              : ['Month', 'Spend', 'Billable Revenue', 'Gross', 'Gross Margin', 'ROAS']
            ).map((col, idx) => (
              <th key={col} className={`${idx === 0 ? 'pl-4 pr-3' : 'px-3'} py-3 ${idx === 0 ? 'text-left' : 'text-right'}`}>{col}</th>
            ))}
            <th className="w-12 px-3 py-3"><span className="sr-only">Actions</span></th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-50">
          {monthsLoading ? (
            <tr><td colSpan={isAllScope ? 9 : 7} className="px-5 py-8 text-center text-sm text-gray-400">Loading month history — this walks six months of Meta and revenue data and can take a while.</td></tr>
          ) : monthsError ? (
            <tr><td colSpan={isAllScope ? 9 : 7} className="px-5 py-8 text-center text-sm text-amber-700"><div>{monthsError}</div><button type="button" onClick={load} className="mt-3 rounded-lg border border-amber-200 px-3 py-1.5 text-xs font-medium hover:bg-amber-50">Retry month history</button></td></tr>
          ) : !months.length ? (
            <tr><td colSpan={isAllScope ? 9 : 7} className="px-5 py-8 text-center text-sm text-gray-400">No month history available.</td></tr>
          ) : months.map(row => {
            // Gross and net are coloured on their own sign: a profitable-gross month whose costs
            // pushed net negative (Jul 2026) must not show its gross in red.
            const tone = value => (value > 0 ? 'text-green-600' : value < 0 ? 'text-red-600' : 'text-gray-900');
            return (
              <tr key={`${row.date_from}-${row.date_to}`} className="hover:bg-gray-50">
                <td className="whitespace-nowrap py-3 pl-4 pr-3 font-medium text-gray-900">
                  {row.period_label}
                  {row.from_snapshot ? (
                    <span className="ml-2 rounded-full bg-gray-100 px-2 py-0.5 text-[10px] font-medium text-gray-500">
                      stored{row.synced_at ? ` ${new Date(row.synced_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}` : ''}
                    </span>
                  ) : (
                    <span className="ml-2 rounded-full bg-green-50 px-2 py-0.5 text-[10px] font-medium text-green-700">live</span>
                  )}
                </td>
                <td className="px-3 py-3 text-right tabular-nums">{money(row.spend)}</td>
                <td className="px-3 py-3 text-right tabular-nums">{money(row.revenue)}</td>
                <td className={`px-3 py-3 text-right tabular-nums font-semibold ${tone(row.gross_profit)}`}>{money(row.gross_profit)}</td>
                {isAllScope && (
                  <>
                    <td className="px-3 py-3 text-right tabular-nums">{money(row.other_costs)}</td>
                    <td className={`px-3 py-3 text-right tabular-nums font-semibold ${tone(row.net_profit)}`}>{money(row.net_profit)}</td>
                  </>
                )}
                <td className="px-3 py-3 text-right tabular-nums">{pct(row.margin)}</td>
                <td className="px-3 py-3 text-right tabular-nums">{row.roas != null ? `${Number(row.roas).toFixed(2)}x` : '--'}</td>
                <td className="px-3 py-3 text-right tabular-nums">
                  {row.from_snapshot && (
                    <button
                      onClick={() => resyncMonth(row)}
                      disabled={resyncing === (row.date_from || '').slice(0, 7)}
                      aria-label={`Re-fetch ${row.period_label}`}
                      className="inline-flex items-center rounded-lg border border-gray-200 p-1.5 text-xs text-gray-500 hover:bg-gray-50 hover:text-gray-700 disabled:opacity-40"
                      title={`Re-fetch ${row.period_label} from Meta and the revenue source. Only this month.`}
                    >
                      <RefreshCw size={12} className={resyncing === (row.date_from || '').slice(0, 7) ? 'animate-spin' : ''} />
                    </button>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  </div>
  );

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
            {isAllScope ? (
              <span>All accounts</span>
            ) : (
              <AccountLabel account={activeAccount} />
            )}
            {(isAllScope || activeAccount) && <span className="text-gray-300">|</span>}
            <span>
              {isAllScope
                ? `Spend from Meta · Revenue from ${revenueSourceName(summary?.revenue_source)} · Net of business costs`
                : `Spend from Meta · Revenue from ${revenueSourceName(summary?.revenue_source)} · Gross account performance`}
            </span>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="inline-flex rounded-lg border border-gray-200 bg-white p-1 text-sm">
            <button
              onClick={() => setScope('all')}
              className={`rounded-md px-3 py-1.5 font-medium ${isAllScope ? 'bg-gray-900 text-white' : 'text-gray-600 hover:bg-gray-50'}`}
            >
              All accounts
            </button>
            <button
              onClick={() => setScope('account')}
              disabled={!activeAccountId}
              className={`rounded-md px-3 py-1.5 font-medium ${!isAllScope ? 'bg-gray-900 text-white' : 'text-gray-600 hover:bg-gray-50'} disabled:opacity-40`}
            >
              Active account
            </button>
          </div>
          {period === 'custom' ? (
            <>
              <input type="date" value={customFrom} onChange={e => setCustomFrom(e.target.value)} className="rounded-lg border border-gray-200 px-3 py-2 text-sm" />
              <input type="date" value={customTo} onChange={e => setCustomTo(e.target.value)} className="rounded-lg border border-gray-200 px-3 py-2 text-sm" />
            </>
          ) : RANGE_PERIODS.has(period) ? (
            <span className="rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-sm text-gray-600">
              {customFrom} – {customTo}
            </span>
          ) : (
            <input type="month" value={month} onChange={e => setMonth(e.target.value)} className="rounded-lg border border-gray-200 px-3 py-2 text-sm" />
          )}
          <select value={period} onChange={e => changePeriod(e.target.value)} className="rounded-lg border border-gray-200 px-3 py-2 text-sm">
            <option value="mtd">MTD</option>
            <option value="month">Month</option>
            <option value="today">Today</option>
            <option value="yesterday">Yesterday</option>
            <option value="last_7d">Last 7 days</option>
            <option value="last_30d">Last 30 days</option>
            <option value="last_month">Last month</option>
            <option value="custom">Custom range</option>
          </select>
          <button onClick={load} disabled={loading} className="flex items-center gap-2 rounded-lg border border-gray-200 px-3 py-2 text-sm text-gray-600 hover:bg-gray-50 disabled:opacity-50">
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
            Refresh
          </button>
          <a
            href={DETAILED_PNL_SHEET_URL}
            target="_blank"
            rel="noreferrer"
            className="flex items-center gap-2 rounded-lg border border-indigo-200 bg-indigo-50 px-3 py-2 text-sm font-medium text-indigo-700 hover:bg-indigo-100"
            title="Open Joel's detailed P&L Google Sheet"
          >
            <ExternalLink size={14} />
            Detailed P&L
          </a>
        </div>
      </div>

      {loadError && !loading && (
        <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          <div>{loadError}. The previous Profit/Loss figures were cleared so stale account data is not shown.</div>
          <button type="button" onClick={load} className="mt-2 rounded-lg border border-red-200 px-3 py-1.5 text-xs font-medium hover:bg-red-100">Retry summary</button>
        </div>
      )}

      {(loading || monthsLoading) && loadingSlow && (
        <div className="rounded-xl border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-800">
          Profit/Loss is still loading live Meta and revenue data. The summary and six-month history use separate requests and may finish at different times.
        </div>
      )}

      {summary?.data_incomplete && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          Data incomplete: {summary.errors?.join(', ') || 'one or more sources are unavailable'}. Treat this period as unavailable until the source recovers.
        </div>
      )}

      <div>
        <ProfitStatement
          loading={loading}
          cells={[
            {
              label: 'Revenue',
              value: money(summary?.revenue),
              caption: summary?.revenue_source === 'bhm_everflow_live' && !summary?.conversions ? 'BHM Everflow · no conversions yet' : revenueSourceLabel(summary?.revenue_source),
              badge: isRevenueFallback(summary?.revenue_source) ? 'Fallback' : null,
            },
            {
              label: 'Ad spend', op: '−',
              value: money(summary?.spend),
              caption: summary?.spend > 0 && summary?.revenue != null ? `Meta · ${(summary.revenue / summary.spend).toFixed(2)}x ROAS` : 'Meta',
              badge: summary?.spend == null && !loading ? 'Unavailable' : null,
            },
            {
              label: 'Gross profit', op: '=',
              value: money(summary?.gross_profit),
              caption: summary?.revenue > 0 && summary?.gross_profit != null ? `${((summary.gross_profit / summary.revenue) * 100).toFixed(1)}% of revenue` : 'revenue − spend',
              tone: grossTone,
              badge: isIncomplete ? 'Incomplete' : null,
            },
            ...(isAllScope ? [
              {
                label: 'Monthly costs', op: '−',
                value: money(summary?.other_costs),
                caption: summary?.has_costs ? `${summary.costs.length} entries · listed below` : 'No costs logged',
              },
              {
                label: 'Net profit', op: '=',
                value: money(summary?.net_profit),
                caption: summary?.revenue > 0 && summary?.net_profit != null ? `${((summary.net_profit / summary.revenue) * 100).toFixed(1)}% of revenue · after costs` : 'gross − costs',
                tone: netTone,
                badge: isIncomplete ? 'Incomplete' : null,
              },
            ] : []),
          ]}
        />
        <StatementNotes
          notes={[
            !isAllScope && { text: <>Monthly costs and net profit are business-wide, so they&apos;re on the <button type="button" onClick={() => setScope('all')} className="font-medium text-indigo-600 hover:underline">All accounts</button> view.</> },
            summary?.unattributed_revenue > 0 && { text: <>Revenue includes {money(summary.unattributed_revenue, 2)} Switchboard couldn&apos;t tie to a specific ad set. It still counts, so the total matches the Switchboard portal.</> },
            isAllScope && (summary?.network_revenue > 0 || summary?.foreign_revenue > 0) && {
              text: (
                <span data-testid="pnl-excluded-revenue">
                  Not counted:{' '}
                  {summary.network_revenue > 0 && <>{money(summary.network_revenue, 2)} of network revenue (third-party traffic through BHM&apos;s network)</>}
                  {summary.network_revenue > 0 && summary.foreign_revenue > 0 && ' and '}
                  {summary.foreign_revenue > 0 && <>{money(summary.foreign_revenue, 2)} from Meta ad sets outside these accounts</>}
                  . The Switchboard portal total runs higher by about this much.
                </span>
              ),
            },
            // unmapped_adsets is not shown: it counts every ad set ever saved for the account (paused, years old,
            // no spend) that had no revenue, so it fired on every healthy month and said nothing actionable.
          ]}
        />
      </div>

      {/* Two independent columns: campaigns then month history on the left, costs + event split on the right.
          Month history lives in the left column so it never waits below the taller column (no dead gap). On
          the single-account view there are no campaigns or costs, so month history renders full width below. */}
      {isAllScope ? (
        <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_340px]">
          <div className="min-w-0 space-y-6">
            {loading ? (
              <div className="rounded-xl border border-gray-200 bg-white px-5 py-10 text-center text-sm text-gray-400 shadow-sm">Loading campaigns...</div>
            ) : summary?.campaigns?.length > 0 ? (
              <CampaignBreakdown campaigns={summary.campaigns} adAccounts={adAccounts} />
            ) : (
              <div className="rounded-xl border border-gray-200 bg-white px-5 py-10 text-center text-sm text-gray-400 shadow-sm">No campaign activity for this period.</div>
            )}
            {monthsSection}
          </div>
          <div className="space-y-6">
            <CostsLedger
              costs={summary?.costs}
              total={summary?.other_costs}
              loading={loading}
              periodLabel={summary?.period_label}
              onAdd={() => { setModalEntry(null); setShowModal(true); }}
              onEdit={entry => { setModalEntry(entry); setShowModal(true); }}
              onDelete={entry => setDeleteEntry(entry)}
            />
            {summary?.event_breakdown?.length > 0 && (
              <EventBreakdown rows={summary.event_breakdown} revenue={summary.revenue} open={showEvents} onToggle={toggleEvents} />
            )}
          </div>
        </div>
      ) : summary?.event_breakdown?.length > 0 && (
        <div className="max-w-xl">
          <EventBreakdown rows={summary.event_breakdown} revenue={summary.revenue} open={showEvents} onToggle={toggleEvents} />
        </div>
      )}

      {!isAllScope && monthsSection}

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
