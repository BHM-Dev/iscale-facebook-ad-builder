import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useCampaign } from '../context/CampaignContext';
import { useToast } from '../context/ToastContext';
import { authFetch } from '../lib/facebookApi';

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1';
const TABS = [
    { key: 'open', label: 'Open' },
    { key: 'history', label: 'History' },
    { key: 'stats', label: 'How each trigger is doing' },
];

const money = (value) => {
    const number = Number(value || 0);
    return `${number < 0 ? '-$' : '$'}${Math.abs(number).toFixed(2)}`;
};

const accountId = (account) => String(account?.id || account?.account_id || account?.accountId || '')
    .replace(/^act_/, '');

const relativeAge = (value) => {
    const timestamp = Date.parse(value || '');
    if (Number.isNaN(timestamp)) return '';
    const minutes = Math.max(0, Math.floor((Date.now() - timestamp) / 60000));
    if (minutes < 1) return 'just now';
    if (minutes < 60) return `${minutes}m ago`;
    const hours = Math.floor(minutes / 60);
    if (hours < 24) return `${hours}h ago`;
    return `${Math.floor(hours / 24)}d ago`;
};

const dayLabel = (day, isLast) => {
    if (isLast) return 'Today';
    const date = new Date(`${day}T12:00:00`);
    return Number.isNaN(date.getTime()) ? day : date.toLocaleDateString(undefined, { weekday: 'short' });
};

const decisionLabel = (proposal) => {
    if (proposal.action === 'pause') return 'Paused';
    const cents = proposal.action_params?.to_cents;
    return cents == null ? 'Budget raised' : `${money(cents / 100)}/day`;
};

function Evidence({ proposal, onExpanded }) {
    const [expanded, setExpanded] = useState(true);
    const evidence = proposal.evidence || {};
    const days = evidence.days || [];
    const totals = evidence.totals_7d || {};
    const toggle = () => {
        const next = !expanded;
        setExpanded(next);
        if (next) onExpanded();
    };

    return (
        <>
            <button type="button" className="mb-1 text-left text-xs text-indigo-600 hover:text-indigo-800" onClick={toggle}>
                {expanded ? 'Hide' : 'Show'} the numbers
            </button>
            {expanded && (
                <div className="overflow-x-auto">
                    <table className="w-full max-w-2xl text-xs tabular-nums">
                        <thead>
                            <tr className="text-right text-gray-400">
                                <th className="py-1 pr-3 text-left font-medium">Day</th>
                                <th className="px-2 py-1 font-medium">Spend</th>
                                <th className="hidden px-2 py-1 font-medium md:table-cell">Leads</th>
                                <th className="px-2 py-1 font-medium">Revenue</th>
                                <th className="py-1 pl-2 font-medium">Profit</th>
                            </tr>
                        </thead>
                        <tbody>
                            {days.map((day, index) => {
                                const profit = Number(day.profit ?? Number(day.revenue || 0) - Number(day.spend || 0));
                                return (
                                    <tr key={`${day.day}-${index}`} className="border-t border-gray-100 text-right">
                                        <td className="py-1 pr-3 text-left text-gray-600">{dayLabel(day.day, index === days.length - 1)}</td>
                                        <td className="px-2 py-1 text-gray-700">{money(day.spend)}</td>
                                        <td className="hidden px-2 py-1 text-gray-700 md:table-cell">{day.leads ?? 0}</td>
                                        <td className="px-2 py-1 text-gray-700">{money(day.revenue)}</td>
                                        <td className={`py-1 pl-2 ${profit < 0 ? 'text-red-600' : 'text-green-700'}`}>{money(profit)}</td>
                                    </tr>
                                );
                            })}
                            <tr className="font-semibold text-right">
                                <td className="py-1 pr-3 text-left">7 days</td>
                                <td className="px-2 py-1">{money(totals.spend)}</td>
                                <td className="hidden px-2 py-1 md:table-cell">{totals.leads ?? 0}</td>
                                <td className="px-2 py-1">{money(totals.revenue)}</td>
                                <td className={`py-1 pl-2 ${Number(totals.profit || 0) < 0 ? 'text-red-600' : 'text-green-700'}`}>{money(totals.profit)}</td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            )}
        </>
    );
}

function ProposalCard({ proposal, accountName, dismissReasons, onApprove, onDismiss, onEvent, busy, anyBusy }) {
    const [dismissOpen, setDismissOpen] = useState(false);
    const [reason, setReason] = useState('');
    const [note, setNote] = useState('');
    const pause = proposal.action === 'pause';
    const raiseTo = Number(proposal.action_params?.to_cents || 0) / 100;
    const raiseFrom = Number(proposal.action_params?.from_cents || 0) / 100;
    const raisePct = raiseFrom > 0 ? Math.round(((raiseTo - raiseFrom) / raiseFrom) * 100) : null;
    const current = proposal.evidence?.current || {};
    const failedMessage = proposal.status === 'failed' ? proposal.execution_result?.error : null;
    const stale = proposal.status === 'stale';
    const locked = stale || proposal.status === 'executing';
    const dismissDisabled = !reason || (reason === 'Other' && !note.trim()) || busy;
    const adsManagerUrl = `https://adsmanager.facebook.com/adsmanager/manage/adsets?act=${String(proposal.fb_account_id || '').replace(/^act_/, '')}&selected_adset_ids=${encodeURIComponent(proposal.fb_adset_id || '')}`;

    return (
        <article className="border-b border-gray-100 p-4 last:border-b-0" data-testid={`proposal-${proposal.id}`}>
            <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                <span className={`rounded-md px-2 py-0.5 text-[11px] font-bold tracking-wide ${pause ? 'bg-red-50 text-red-700' : 'bg-green-50 text-green-700'}`}>
                    {pause ? 'PAUSE' : 'RAISE BUDGET'}
                </span>
                <span className="font-semibold text-gray-900">{proposal.adset_name}</span>
                <span className="ml-auto text-xs text-gray-400">{accountName || proposal.fb_account_id} · {(proposal.trigger_labels || []).join(' + ')} · {relativeAge(proposal.created_at)}</span>
            </div>
            <p className="mt-1 text-sm text-gray-600">{proposal.evidence?.why}</p>

            <div className="mt-2"><Evidence proposal={proposal} onExpanded={() => onEvent('proposal_evidence_expanded', proposal.id)} /></div>

            <div className="my-3 flex flex-wrap gap-x-6 gap-y-1 text-xs text-gray-600">
                <span>Current: <b className="text-gray-900">{current.status || '—'}{current.daily_budget_cents != null ? ` · ${money(current.daily_budget_cents / 100)}/day` : ''}</b></span>
                <span>Proposed: <b className="text-gray-900">{pause ? 'PAUSE' : `${money(raiseTo)}/day${raisePct != null ? ` (+${raisePct}%)` : ''}`}</b></span>
            </div>

            {stale && <div className="mb-3 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800">{proposal.status_reason || 'This ad set changed since the proposal. Nothing was sent.'}</div>}
            {failedMessage && (
                <div className="mb-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
                    Meta rejected the change: {failedMessage}{' '}
                    <button type="button" className="font-semibold underline" onClick={() => onApprove(proposal)} disabled={anyBusy}>{pause ? 'Retry' : `Retry — raise to ${money(raiseTo)}/day`}</button>
                </div>
            )}
            {(busy || proposal.status === 'executing') && <div className="mb-3 text-xs text-amber-700">Checking the ad set in Meta…</div>}

            <div className="flex flex-wrap items-center gap-2">
                <button type="button" className={`w-full rounded-lg px-3 py-2 text-sm font-semibold text-white sm:w-auto ${pause ? 'bg-red-700 hover:bg-red-800' : 'bg-indigo-600 hover:bg-indigo-700'} disabled:cursor-not-allowed disabled:opacity-50`} onClick={() => onApprove(proposal)} disabled={anyBusy || locked}>
                    {pause ? 'Approve — pause ad set' : `Approve — raise to ${money(raiseTo)}/day`}
                </button>
                <button type="button" className="w-full rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-800 hover:bg-gray-50 disabled:opacity-50 sm:w-auto" onClick={() => setDismissOpen(value => !value)} disabled={busy || locked}>
                    Dismiss ▾
                </button>
                <a className="w-full text-sm text-indigo-600 hover:text-indigo-800 sm:w-auto" href={adsManagerUrl} target="_blank" rel="noreferrer" onClick={() => onEvent('ads_manager_opened', proposal.id)}>
                    Open in Ads Manager ↗
                </a>
            </div>

            {dismissOpen && (
                <div className="mt-3 rounded-lg bg-gray-50 p-3">
                    <div className="flex flex-wrap gap-1.5">
                        {dismissReasons.map(option => (
                            <button key={option} type="button" className={`rounded-full border px-2.5 py-1 text-xs ${reason === option ? 'border-gray-900 bg-gray-900 text-white' : 'border-gray-200 bg-white text-gray-700'}`} onClick={() => setReason(option)}>
                                {option}
                            </button>
                        ))}
                    </div>
                    {reason === 'Other' && <textarea className="mt-2 min-h-14 w-full rounded-lg border border-gray-200 px-2 py-1.5 text-sm" value={note} onChange={event => setNote(event.target.value)} placeholder="What should the rule have known?" />}
                    <button type="button" className="mt-2 rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm font-medium disabled:opacity-50" disabled={dismissDisabled} onClick={() => onDismiss(proposal, reason, note)}>
                        Dismiss proposal
                    </button>
                </div>
            )}
        </article>
    );
}

export default function ProposalsPanel() {
    const { adAccounts = [] } = useCampaign();
    const { showError, showSuccess, showInfo } = useToast();
    const [payload, setPayload] = useState(null);
    const [proposals, setProposals] = useState([]);
    const [tab, setTab] = useState('open');
    const [history, setHistory] = useState(null);
    const [stats, setStats] = useState(null);
    const [loading, setLoading] = useState(true);
    const [busyId, setBusyId] = useState(null);
    const viewed = useRef(new Set());

    const event = useCallback((name, proposalId, props = {}) => {
        authFetch(`${API_BASE}/proposals/events`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ event: name, proposal_id: proposalId, props }) }).catch(() => {});
    }, []);

    const loadOpen = useCallback(async () => {
        try {
            const response = await authFetch(`${API_BASE}/proposals`);
            if (!response.ok) throw new Error('Failed to load proposals');
            const data = await response.json();
            setPayload(data);
            window.dispatchEvent(new Event('proposals:changed'));
            setProposals(data.visible ? (data.proposals || []) : []);
            (data.proposals || []).forEach(proposal => {
                if (!viewed.current.has(proposal.id)) {
                    viewed.current.add(proposal.id);
                    event('proposal_viewed', proposal.id);
                }
            });
        } catch (error) {
            showError(error.message || 'Failed to load proposals');
        } finally {
            setLoading(false);
        }
    }, [event, showError]);

    useEffect(() => { loadOpen(); }, [loadOpen]);

    useEffect(() => {
        if (tab === 'history' && history === null) {
            authFetch(`${API_BASE}/proposals/history?limit=100`).then(async response => {
                if (!response.ok) throw new Error('Failed to load proposal history');
                setHistory(await response.json());
            }).catch(error => showError(error.message));
        }
        if (tab === 'stats' && stats === null) {
            authFetch(`${API_BASE}/proposals/stats`).then(async response => {
                if (!response.ok) throw new Error('Failed to load proposal stats');
                setStats(await response.json());
            }).catch(error => showError(error.message));
        }
    }, [history, showError, stats, tab]);

    useEffect(() => { event('proposal_tab_viewed', null, { tab }); }, [event, tab]);

    const accountNames = useMemo(() => new Map(adAccounts.map(account => [accountId(account), account.name || account.account_name || account.label])), [adAccounts]);
    if (payload?.visible === false) return null;
    if (loading && !payload) return null;
    if (!payload) return null;

    const unavailable = Object.values(payload.accounts || {}).some(account => account.revenue_available === false);
    const approve = async proposal => {
        setBusyId(proposal.id);
        try {
            const response = await authFetch(`${API_BASE}/proposals/${proposal.id}/approve`, { method: 'POST' });
            if (response.status === 409) {
                showInfo('Already handled — see History.');
                await loadOpen();
                return;
            }
            const data = await response.json().catch(() => ({}));
            if (!response.ok) throw new Error(data.detail || 'Approval failed');
            if (data.status === 'stale' || data.status === 'failed') {
                // Keep the card in place so the reason stays readable; the next load drops a stale one.
                setProposals(current => current.map(item => item.id === proposal.id ? data : item));
            } else {
                showSuccess(data.action === 'pause'
                    ? `Paused ${data.adset_name}`
                    : `Raised ${data.adset_name} to ${money(Number(data.action_params?.to_cents || 0) / 100)}/day`);
                await loadOpen();
            }
        } catch (error) {
            showError(error.message || 'Approval failed');
            // The write may have landed even if the response didn't; show the server's state.
            loadOpen();
        } finally {
            setBusyId(null);
        }
    };

    const dismiss = async (proposal, reason, note) => {
        setBusyId(proposal.id);
        try {
            const response = await authFetch(`${API_BASE}/proposals/${proposal.id}/dismiss`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ reason, note: note || '' }) });
            const data = await response.json().catch(() => ({}));
            if (!response.ok) throw new Error(data.detail || 'Dismissal failed');
            await loadOpen();
        } catch (error) {
            showError(error.message || 'Dismissal failed');
        } finally {
            setBusyId(null);
        }
    };

    return (
        <section className="overflow-hidden rounded-xl border border-gray-200 bg-white shadow-sm" data-testid="proposals-panel">
            <div className="flex flex-wrap items-center gap-2 border-b border-gray-200 px-4 py-3">
                <h2 className="text-sm font-semibold text-gray-900">Proposals ({proposals.filter(item => ['open', 'executing', 'failed'].includes(item.status)).length})</h2>
                <div className="ml-auto flex flex-wrap gap-1">
                    {TABS.map(item => <button key={item.key} type="button" className={`rounded-md border px-2.5 py-1 text-xs ${tab === item.key ? 'border-gray-200 bg-gray-100 font-semibold text-gray-900' : 'border-transparent text-gray-500 hover:text-gray-900'}`} onClick={() => setTab(item.key)}>{item.label}</button>)}
                </div>
            </div>
            {payload.shadow && <div className="border-b border-gray-100 px-4 py-2.5 text-xs text-gray-600">Shadow week: only you can see these. Joel and Abel don't see this panel yet.</div>}
            <div className={`border-b border-gray-100 px-4 py-2.5 text-xs ${unavailable ? 'bg-amber-50 text-amber-800' : 'text-gray-600'}`}>
                {unavailable ? 'Revenue source unavailable — no new proposals until revenue data is back. Missing revenue is never treated as $0.' : 'Nothing changes in Meta until someone approves. Existing auto-pause rules are unchanged.'}
            </div>
            {tab === 'open' && (proposals.length === 0 ? <div className="px-4 py-7 text-center text-sm text-gray-400">No proposals right now. The next check runs within the hour.</div> : proposals.map(proposal => (
                <ProposalCard key={proposal.id} proposal={proposal} accountName={accountNames.get(accountId({ id: proposal.fb_account_id })) || accountNames.get(String(proposal.fb_account_id || '').replace(/^act_/, ''))} dismissReasons={payload.dismiss_reasons || []} onApprove={approve} onDismiss={dismiss} onEvent={event} busy={busyId === proposal.id} anyBusy={busyId !== null} />
            )))}
            {tab === 'history' && <HistoryTable rows={history} />}
            {tab === 'stats' && <StatsTable stats={stats} />}
        </section>
    );
}

function HistoryTable({ rows }) {
    if (!rows) return <div className="px-4 py-7 text-center text-sm text-gray-400">Loading history…</div>;
    if (!rows.length) return <div className="px-4 py-7 text-center text-sm text-gray-400">No decisions yet.</div>;
    return <div className="overflow-x-auto"><table className="w-full min-w-[680px] text-left text-xs"><thead className="text-gray-400"><tr>{['When', 'Ad set', 'Trigger', 'Decision', 'By', 'Result'].map(header => <th key={header} className="px-4 py-2 font-medium">{header}</th>)}</tr></thead><tbody className="divide-y divide-gray-100">{rows.map(row => <tr key={row.id}><td className="whitespace-nowrap px-4 py-2">{relativeAge(row.decided_at || row.updated_at || row.created_at)}</td><td className="px-4 py-2 font-medium text-gray-800">{row.adset_name}</td><td className="px-4 py-2">{(row.trigger_labels || [row.trigger_key]).join(' + ')}</td><td className="px-4 py-2">{row.status === 'dismissed' ? 'Dismissed' : decisionLabel(row)}</td><td className="px-4 py-2">{row.decided_by || '—'}</td><td className="px-4 py-2">{row.status_reason || row.dismiss_reason || row.status}</td></tr>)}</tbody></table></div>;
}

function StatsTable({ stats }) {
    if (!stats) return <div className="px-4 py-7 text-center text-sm text-gray-400">Loading stats…</div>;
    const rows = Object.entries(stats);
    if (!rows.length) return <div className="px-4 py-7 text-center text-sm text-gray-400">No trigger data yet.</div>;
    return <div><div className="border-b border-gray-100 px-4 py-2.5 text-xs text-gray-600">How each trigger is doing</div><div className="overflow-x-auto"><table className="w-full min-w-[680px] text-left text-xs"><thead className="text-gray-400"><tr><th className="px-4 py-2 font-medium">Trigger</th><th className="px-4 py-2 text-right font-medium">Proposed</th><th className="px-4 py-2 text-right font-medium">Approved</th><th className="px-4 py-2 text-right font-medium">Dismissed</th><th className="px-4 py-2 text-right font-medium">Expired</th><th className="px-4 py-2 text-right font-medium">Approval rate</th></tr></thead><tbody className="divide-y divide-gray-100">{rows.map(([key, row]) => { const denominator = Number(row.approved || 0) + Number(row.dismissed || 0); return <tr key={key}><td className="px-4 py-2 font-medium text-gray-800">{row.label || key}</td><td className="px-4 py-2 text-right">{row.proposed || 0}</td><td className="px-4 py-2 text-right">{row.approved || 0}</td><td className="px-4 py-2 text-right">{row.dismissed || 0}</td><td className="px-4 py-2 text-right">{row.expired || 0}</td><td className="px-4 py-2 text-right">{denominator ? `${Math.round((Number(row.approved || 0) / denominator) * 100)}%` : '—'}</td></tr>; })}</tbody></table></div></div>;
}
