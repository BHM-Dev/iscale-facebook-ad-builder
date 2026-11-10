import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ChevronDown, ChevronRight, ExternalLink, RefreshCw } from 'lucide-react';
import { authFetch } from '../lib/facebookApi';
import { useToast } from '../context/ToastContext';

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1';
const GROUPS = [['creative', 'Creative'], ['concept', 'Concept'], ['headline', 'Headline']];

const money = value => value == null ? '—' : new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(value);
const preciseMoney = value => value == null ? '—' : new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value);

function cplClass(row) {
  if (!row.leads) {
    return row.max_cpl != null && row.spend >= row.max_cpl ? 'text-red-600' : 'text-gray-400';
  }
  if (row.max_cpl == null) return 'text-gray-700';
  if (row.cpl <= row.max_cpl * 0.85) return 'text-emerald-700';
  if (row.cpl <= row.max_cpl) return 'text-amber-700';
  return 'text-red-600';
}

function NameCell({ row }) {
  if (row.group_by !== 'creative' || !row.concept) return <span className="font-semibold text-gray-900">{row.label}</span>;
  const index = row.label.toLowerCase().indexOf(row.concept.toLowerCase());
  if (index < 0) return <span className="font-semibold text-gray-900">{row.label}</span>;
  return <span className="text-gray-700">{row.label.slice(0, index)}<strong className="text-gray-950">{row.label.slice(index, index + row.concept.length)}</strong>{row.label.slice(index + row.concept.length)}</span>;
}

export default function WinningAds({ adAccountId, datePreset, dateFrom, dateTo }) {
  const { showSuccess, showError } = useToast();
  const [groupBy, setGroupBy] = useState('creative');
  const [minLeads, setMinLeads] = useState(10);
  const [niche, setNiche] = useState('');
  const [activeOnly, setActiveOnly] = useState(false);
  const [hideUnderFloor, setHideUnderFloor] = useState(false);
  const [expanded, setExpanded] = useState(() => new Set());
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const requestRef = useRef(0);

  const effectiveRange = useMemo(() => {
    if (datePreset === 'today' || datePreset === 'yesterday') return { preset: 'last_14d', defaulted: true };
    return { preset: datePreset || 'last_14d', defaulted: false };
  }, [datePreset]);

  const track = useCallback((event, props) => {
    authFetch(`${API_BASE}/daily-close/event`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ event, props }),
    }).catch(() => {});
  }, []);

  const load = useCallback(async () => {
    if (!adAccountId) return;
    const requestId = ++requestRef.current;
    setLoading(true);
    setError('');
    try {
      const params = new URLSearchParams({ ad_account_id: adAccountId, group_by: groupBy, min_leads: String(minLeads) });
      if (effectiveRange.preset === 'custom' && dateFrom && dateTo) {
        params.set('date_from', dateFrom);
        params.set('date_to', dateTo);
      } else {
        params.set('date_preset', effectiveRange.preset);
      }
      const response = await authFetch(`${API_BASE}/winners?${params}`);
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body.detail || 'Winning ads could not be loaded.');
      if (requestId !== requestRef.current) return;
      setData(body);
      track('winners_viewed', { group_by: groupBy });
    } catch (loadError) {
      if (requestId === requestRef.current) setError(loadError.message || 'Winning ads could not be loaded.');
    } finally {
      if (requestId === requestRef.current) setLoading(false);
    }
  }, [adAccountId, dateFrom, dateTo, effectiveRange.preset, groupBy, minLeads, track]);

  useEffect(() => { load(); }, [load]);

  const niches = useMemo(() => [...new Set((data?.rows || []).flatMap(row => row.niches || []))].sort(), [data]);
  const rows = useMemo(() => (data?.rows || []).filter(row => {
    if (niche && !(row.niches || []).includes(niche)) return false;
    if (activeOnly && !row.active_ad_count) return false;
    if (hideUnderFloor && !row.enough_data) return false;
    return true;
  }), [activeOnly, data, hideUnderFloor, niche]);

  const relaunch = row => {
    if (!row.drive_file_ids?.length) return;
    try {
      localStorage.setItem('pendingDriveRelaunch', JSON.stringify({
        account_id: adAccountId,
        drive_file_ids: row.drive_file_ids,
        drive_file_names: row.drive_file_names || [],
        source: 'winners',
        created_at: Date.now(),
      }));
      track('winners_relaunch', { count: row.drive_file_ids.length, group_by: groupBy });
      window.open('/facebook-campaigns', '_blank', 'noopener,noreferrer');
      showSuccess(`Opening Launch Ads: pick the campaign and ad set, then ${row.drive_file_ids.length === 1 ? 'this creative is' : `these ${row.drive_file_ids.length} creatives are`} preselected.`);
    } catch {
      showError('Could not prepare the Drive relaunch. Check browser storage and try again.');
    }
  };

  const iterate = row => {
    if (!row.top_spend_ad_id) return;
    track('winners_iterate', {});
    window.open(`/batch-generate?adId=${encodeURIComponent(row.top_spend_ad_id)}`, '_blank', 'noopener,noreferrer');
  };

  if (!adAccountId) return <div className="p-8 text-center text-sm text-gray-500">Select an ad account to rank winning ads.</div>;

  return <div className="space-y-3 p-5">
    {effectiveRange.defaulted && <div className="rounded-lg border border-indigo-200 bg-indigo-50 px-3 py-2 text-xs text-indigo-800">Winning ads uses Last 14 days when the page is set to {datePreset === 'today' ? 'Today' : 'Yesterday'} so the 10-lead evidence floor is meaningful.</div>}
    {data?.max_cpl_available === false && <div role="status" className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900"><strong>Estimated profit is unavailable.</strong> {data.max_cpl_reason || 'Max CPL has no revenue-per-lead value for this account.'} Rows are sorted by leads instead.</div>}

    <div className="flex flex-wrap items-end gap-3 rounded-xl border border-gray-200 bg-white p-3 shadow-sm">
      <div><div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-gray-500">Group by</div><div className="inline-flex rounded-lg border border-gray-200 bg-gray-50 p-0.5">{GROUPS.map(([value, label]) => <button key={value} type="button" onClick={() => { setGroupBy(value); setExpanded(new Set()); }} className={`rounded-md px-3 py-1.5 text-xs font-semibold ${groupBy === value ? 'bg-white text-gray-950 shadow-sm' : 'text-gray-500 hover:text-gray-800'}`}>{label}</button>)}</div></div>
      <label className="text-[11px] font-semibold uppercase tracking-wide text-gray-500">Min leads<input type="number" min="1" max="10000" value={minLeads} onChange={event => setMinLeads(Math.max(1, Number(event.target.value) || 1))} className="mt-1 block w-24 rounded-lg border border-gray-200 px-2 py-1.5 text-sm font-normal text-gray-800" /></label>
      <label className="text-[11px] font-semibold uppercase tracking-wide text-gray-500">Niche<select value={niche} onChange={event => setNiche(event.target.value)} className="mt-1 block min-w-40 rounded-lg border border-gray-200 px-2 py-1.5 text-sm font-normal normal-case text-gray-800"><option value="">All niches</option>{niches.map(item => <option key={item}>{item}</option>)}</select></label>
      <label className="flex items-center gap-2 pb-1.5 text-xs font-medium text-gray-700"><input type="checkbox" checked={activeOnly} onChange={event => setActiveOnly(event.target.checked)} className="rounded border-gray-300" />Active only</label>
      <label className="flex items-center gap-2 pb-1.5 text-xs font-medium text-gray-700"><input type="checkbox" checked={hideUnderFloor} onChange={event => setHideUnderFloor(event.target.checked)} className="rounded border-gray-300" />Hide under floor</label>
      <button type="button" onClick={load} className="ml-auto rounded-lg border border-gray-200 p-2 text-gray-500 hover:bg-gray-50" title="Refresh winners"><RefreshCw size={14} className={loading ? 'animate-spin' : ''} /></button>
      {data && <div className="w-full border-t border-gray-100 pt-2 text-xs text-gray-500"><strong className="text-gray-800">{data.ranked_count}</strong> of {data.total_count} {groupBy === 'creative' ? 'creatives' : `${groupBy}s`} cleared the {data.min_leads}-lead floor.</div>}
    </div>

    <div className="overflow-x-auto rounded-xl border border-gray-200 bg-white shadow-sm">
      {error ? <div role="alert" className="p-8 text-center text-sm text-red-700">{error} <button type="button" onClick={load} className="ml-1 font-semibold underline">Retry</button></div> : loading && !data ? <div className="flex items-center justify-center gap-2 p-10 text-sm text-gray-400"><RefreshCw size={15} className="animate-spin" />Loading winning ads…</div> : !rows.length ? <div className="p-10 text-center text-sm text-gray-500">No ads match this account, range, and filter.</div> : <table className="min-w-[1180px] w-full text-left text-xs">
        <thead className="border-b border-gray-200 bg-gray-50 text-[10px] font-semibold uppercase tracking-wide text-gray-500"><tr><th className="w-8 px-2 py-3" /><th className="px-3 py-3">Creative</th><th className="px-3 py-3">Niches</th><th className="px-3 py-3 text-right">Ad sets</th><th className="px-3 py-3 text-right">Spend</th><th className="px-3 py-3 text-right">Leads</th><th className="px-3 py-3 text-right">CPL</th><th className="px-3 py-3 text-right" title="leads × this niche's revenue per lead − spend">Est. profit ⓘ</th><th className="px-3 py-3 text-right">RT revenue</th><th className="px-3 py-3">Status</th><th className="px-3 py-3 text-right">Actions</th></tr></thead>
        <tbody className="divide-y divide-gray-100">{rows.map(row => <React.Fragment key={row.key}>
          <tr className={`${row.enough_data ? '' : 'bg-gray-50 opacity-60'} hover:bg-gray-50/80`}>
            <td className="px-2 py-3">{groupBy === 'concept' && <button type="button" onClick={() => setExpanded(previous => { const next = new Set(previous); next.has(row.key) ? next.delete(row.key) : next.add(row.key); return next; })} className="rounded p-1 text-gray-400 hover:bg-gray-100" aria-label={expanded.has(row.key) ? 'Collapse concept' : 'Expand concept'}>{expanded.has(row.key) ? <ChevronDown size={14} /> : <ChevronRight size={14} />}</button>}</td>
            <td className="max-w-sm px-3 py-3"><div className="flex items-center gap-3">{row.image_url ? <img src={row.image_url} alt="" className="h-12 w-12 shrink-0 rounded-lg border border-gray-200 object-cover" /> : <div className="h-12 w-12 shrink-0 rounded-lg border border-dashed border-gray-300 bg-gray-50" />}<div className="min-w-0"><div className="break-words"><NameCell row={row} /></div>{!row.enough_data && <div className={`mt-1 font-medium ${!row.leads && row.max_cpl != null && row.spend >= row.max_cpl ? 'text-red-600' : 'text-gray-500'}`}>{!row.leads && row.max_cpl != null && row.spend >= row.max_cpl ? 'no leads yet' : `not enough data (${row.leads} leads)`}</div>}</div></div></td>
            <td className="px-3 py-3"><div className="flex max-w-64 flex-wrap gap-1">{(row.niche_codes?.length ? row.niche_codes : row.niches).map(item => <span key={item} className="rounded-full border border-gray-200 bg-white px-2 py-0.5 text-[10px] font-semibold text-gray-600">{item}</span>)}</div></td>
            <td className="px-3 py-3 text-right tabular-nums">{row.adset_count}</td><td className="px-3 py-3 text-right tabular-nums">{money(row.spend)}</td><td className="px-3 py-3 text-right font-semibold tabular-nums">{row.leads}</td>
            <td className={`px-3 py-3 text-right font-semibold tabular-nums ${cplClass(row)}`} title={row.max_cpl == null ? 'Max CPL unavailable' : `Max CPL ${preciseMoney(row.max_cpl)}`}>{row.cpl == null ? '—' : preciseMoney(row.cpl)}</td>
            <td className={`px-3 py-3 text-right font-semibold tabular-nums ${row.est_profit == null ? 'text-gray-400' : row.est_profit >= 0 ? 'text-emerald-700' : 'text-red-600'}`}>{money(row.est_profit)}{row.est_partial && row.est_profit != null && <div className="text-[9px] font-medium uppercase text-amber-700">partial estimate</div>}</td>
            <td className="px-3 py-3 text-right tabular-nums">{money(row.rt_revenue)}{row.rt_revenue != null && row.rt_coverage !== 'full' && <div className="text-[9px] font-medium uppercase text-gray-400">partial</div>}</td>
            <td className="px-3 py-3"><span className={row.active_ad_count ? 'text-emerald-700' : 'text-gray-400'}>{row.active_ad_count} active</span></td>
            <td className="px-3 py-3"><div className="flex justify-end gap-1.5"><button type="button" disabled={!row.drive_file_ids?.length || (row.niches?.length || 0) > 1} onClick={() => relaunch(row)} title={!row.drive_file_ids?.length ? 'Not in the Drive library, so it cannot be relaunched from here' : (row.niches?.length || 0) > 1 ? `Spans ${row.niches.length} niches: switch to Creative view and relaunch one file into its own niche` : 'Open Launch Ads with this Drive creative selected'} className="rounded-lg border border-indigo-200 px-2.5 py-1.5 font-semibold text-indigo-700 hover:bg-indigo-50 disabled:cursor-not-allowed disabled:border-gray-200 disabled:text-gray-300">Relaunch</button><button type="button" disabled={!row.top_spend_ad_id} onClick={() => iterate(row)} className="inline-flex items-center gap-1 rounded-lg border border-gray-200 px-2.5 py-1.5 font-semibold text-gray-700 hover:bg-gray-50 disabled:text-gray-300">Iterate <ExternalLink size={11} /></button></div></td>
          </tr>
          {groupBy === 'concept' && expanded.has(row.key) && <tr className="bg-indigo-50/40"><td /><td colSpan="10" className="px-4 py-3"><div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">{row.details.map(detail => <div key={detail.ad_id} className="rounded-lg border border-indigo-100 bg-white px-3 py-2"><div className="flex items-center justify-between gap-3"><span className="font-semibold text-gray-800">{detail.niche_code || detail.niche || 'Unmapped niche'}</span><span className={`font-semibold ${cplClass(detail)}`}>{detail.cpl == null ? 'No leads' : `${preciseMoney(detail.cpl)} CPL`}</span></div><div className="mt-1 truncate text-[10px] text-gray-500" title={detail.ad_name}>{detail.ad_name}</div><div className="mt-1 text-[10px] text-gray-500">{money(detail.spend)} spend · {detail.leads} leads{detail.max_cpl != null ? ` · ${preciseMoney(detail.max_cpl)} Max CPL` : ''}</div></div>)}</div></td></tr>}
        </React.Fragment>)}</tbody>
      </table>}
    </div>
  </div>;
}
