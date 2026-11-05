import React, { useEffect, useState } from 'react';
import { useToast } from '../context/ToastContext';
import { authFetch } from '../lib/facebookApi';

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1';
const money = (value, decimals = 0) => value == null ? '—' : `$${Number(value).toLocaleString('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals })}`;
const signed = value => value == null ? '—' : `${Number(value) >= 0 ? '+' : '−'}${money(Math.abs(Number(value)))}`;

export function formatCloseForSlack(close) {
  const day = new Date(`${close.day}T12:00:00Z`).toLocaleDateString('en-US', { weekday: 'long', timeZone: 'UTC' });
  const up = (close.movers?.up || []).slice(0, 2).map(row => `${row.name} ${signed(row.profit)}`).join(', ') || '—';
  const down = close.movers?.down?.[0] ? `${close.movers.down[0].name} ${signed(close.movers.down[0].profit)}` : '—';
  return `*${day} closed at ${signed(close.profit)}:* ${money(close.spend)} Meta spend, ${money(close.revenue)} Everflow revenue (${Number(close.roas || 0).toFixed(2)}x)\nMTD ${signed(close.mtd?.profit)} · Up: ${up} · Down: ${down}`;
}

export default function DailyCloseCard({ accountNames = {} }) {
  const { showSuccess } = useToast();
  const [data, setData] = useState(null);
  const [error, setError] = useState(false);
  useEffect(() => {
    let alive = true;
    authFetch(`${API_BASE}/daily-close/latest`).then(async response => {
      if (!response.ok) throw new Error('close unavailable');
      const next = await response.json();
      if (alive) setData(next);
    }).catch(() => alive && setError(true));
    authFetch(`${API_BASE}/daily-close/event`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ event: 'close_card_viewed', props: {} }) }).catch(() => {});
    return () => { alive = false; };
  }, []);
  const close = data?.combined;
  const label = close?.day ? new Date(`${close.day}T12:00:00Z`).toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric', timeZone: 'UTC' }) : '';
  const asOf = close?.revenue_as_of ? new Date(close.revenue_as_of).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', timeZone: 'America/New_York' }) : null;
  const copy = async () => {
    await navigator.clipboard.writeText(formatCloseForSlack(close));
    showSuccess('Close copied');
    authFetch(`${API_BASE}/daily-close/event`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ event: 'close_copied', props: { day: close.day } }) }).catch(() => {});
  };
  if (error) return <p className="px-1 text-xs text-gray-400">Yesterday’s close is unavailable right now.</p>;
  if (!close) return null;
  if (!close.available) return <section className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">Revenue not in yet (Everflow unavailable)</section>;
  const since = (close.first_read?.revenue != null && close.revenue != null) ? close.revenue - close.first_read.revenue : null;
  return <section className="rounded-xl border border-gray-200 bg-white px-4 py-4 shadow-sm" data-testid="daily-close-card">
    <div className="flex flex-wrap items-center justify-between gap-2"><div><h2 className="text-sm font-semibold text-gray-900">Yesterday’s close · {label} (PT)</h2><p className="text-xs text-gray-500">Revenue as of {asOf || '—'} ET{since != null && ` · ${signed(since)} since first read`}</p></div><button type="button" onClick={copy} title="Copy close for Slack" className="rounded-lg border border-gray-200 px-3 py-1.5 text-xs font-semibold text-gray-700 hover:bg-gray-50">Copy for Slack</button></div>
    <div className="mt-4 flex flex-wrap gap-x-7 gap-y-3 text-sm"><div><div className="text-xs text-gray-500">Spend</div><strong>{money(close.spend, 2)}</strong></div><div><div className="text-xs text-gray-500">Revenue</div><strong>{money(close.revenue, 2)}</strong></div><div><div className="text-xs text-gray-500">Profit</div><strong className={close.profit >= 0 ? 'text-emerald-700' : 'text-red-600'}>{signed(close.profit)}</strong></div><div><div className="text-xs text-gray-500">ROAS</div><strong>{close.roas == null ? '—' : `${Number(close.roas).toFixed(2)}x`}</strong></div><div><div className="text-xs text-gray-500">Leads</div><strong>{Number(close.leads || 0).toLocaleString()}</strong></div></div>
    <div className="mt-3 border-t border-gray-100 pt-3 text-xs text-gray-600">{(data.accounts || []).map(row => <span key={row.account_id} className="mr-4">{accountNames[row.account_id] || row.account_id} {row.available ? `${signed(row.profit)} (${Number(row.roas || 0).toFixed(2)}x)` : '—'}</span>)}</div>
    <p className="mt-3 text-xs text-gray-600">Month to date {signed(close.mtd?.profit)} · {close.mtd?.days_elapsed} days · pacing {signed(close.mtd?.pace)} vs last month {money(close.mtd?.last_month_profit)}</p>
    <div className="mt-3 grid gap-2 text-xs sm:grid-cols-2"><div><span className="font-semibold text-emerald-700">Up</span> {(close.movers?.up || []).map(row => <span key={row.adset_id} className="ml-2 inline-block max-w-[180px] truncate align-bottom" title={row.name}>{row.name} {signed(row.profit)}</span>)}</div><div><span className="font-semibold text-red-600">Down</span> {(close.movers?.down || []).map(row => <span key={row.adset_id} className="ml-2 inline-block max-w-[180px] truncate align-bottom" title={row.name}>{row.name} {signed(row.profit)}</span>)}</div></div>
  </section>;
}
