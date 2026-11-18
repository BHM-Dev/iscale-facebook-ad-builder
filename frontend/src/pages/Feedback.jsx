import React, { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { authFetch } from '../lib/facebookApi';
import { useToast } from '../context/ToastContext';

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1';
const STATUS_LABELS = { new: 'New', in_progress: 'In progress', done: 'Done', wont_fix: "Won't fix" };
const FILTERS = [['open', 'Open'], ['done', 'Done'], ['wont_fix', "Won't fix"], ['all', 'All']];
const EMPTY_MESSAGES = {
    open: 'No open feedback.',
    done: 'No done feedback.',
    wont_fix: "No won't-fix feedback.",
    all: 'No feedback yet.',
};

// Which pages people actually open (2026-11-18), from /usage/summary. Collapsed by default.
function UsagePanel() {
    const [open, setOpen] = useState(false);
    const [data, setData] = useState(null);
    const [error, setError] = useState(null);
    useEffect(() => {
        if (!open || data) return;
        authFetch(`${API_BASE}/usage/summary?days=14`)
            .then(res => (res.ok ? res.json() : Promise.reject(new Error('Usage could not be loaded.'))))
            .then(setData)
            .catch(err => setError(err instanceof TypeError ? "Couldn't reach the Ad Builder." : err.message));
    }, [open, data]);
    return (
        <div className="mb-6 rounded-xl border border-gray-200 bg-white">
            <button type="button" onClick={() => setOpen(v => !v)} aria-expanded={open} className="flex w-full items-center justify-between px-4 py-3 text-left text-sm font-semibold text-gray-900">
                Page usage, last 14 days <span className="text-xs font-normal text-gray-500">{open ? 'Hide' : 'Show'}</span>
            </button>
            {open && (
                <div className="border-t border-gray-100 px-4 py-3 text-sm">
                    {error ? <p className="text-red-700">{error}</p> : !data ? <p className="text-gray-500">Loading…</p> : data.pages.length === 0 ? (
                        <p className="text-gray-500">No page views recorded yet. Tracking started 2026-11-18.</p>
                    ) : (
                        <div className="grid gap-4 md:grid-cols-2">
                            <table className="w-full text-left text-xs">
                                <thead className="text-gray-500"><tr><th className="py-1">Page</th><th className="py-1 text-right">Views</th><th className="py-1 text-right">People</th><th className="py-1 text-right">Minutes</th></tr></thead>
                                <tbody>{data.pages.slice(0, 20).map(row => (
                                    <tr key={row.path} className="border-t border-gray-100"><td className="py-1 font-mono">{row.path}</td><td className="py-1 text-right tabular-nums">{row.views}</td><td className="py-1 text-right tabular-nums">{row.people}</td><td className="py-1 text-right tabular-nums">{row.minutes}</td></tr>
                                ))}</tbody>
                            </table>
                            <div className="space-y-3 text-xs">
                                {Object.entries(data.people).map(([email, pages]) => (
                                    <div key={email}><div className="font-semibold text-gray-800">{email}</div><div className="text-gray-600">{pages.map(p => `${p.path} (${p.views})`).join(' · ')}</div></div>
                                ))}
                            </div>
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}

// Admin list of in-app feedback (2026-11-17). Items are worked in Claude Code sessions and marked Done here.
export default function Feedback() {
    const { showError } = useToast();
    const [rows, setRows] = useState(null);
    const [filter, setFilter] = useState('open');
    const [loadError, setLoadError] = useState(null);

    const load = useCallback(async () => {
        setLoadError(null);
        try {
            const res = await authFetch(`${API_BASE}/feedback?limit=500`);
            if (!res.ok) throw new Error(res.status === 403 ? 'Only admins can see feedback.' : 'Feedback could not be loaded.');
            setRows(await res.json());
        } catch (error) {
            setLoadError(error instanceof TypeError ? "Couldn't reach the Ad Builder." : error.message);
            setRows([]);
        }
    }, []);

    useEffect(() => { load(); }, [load]);

    const update = async (id, patch) => {
        try {
            const res = await authFetch(`${API_BASE}/feedback/${id}`, {
                method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(patch),
            });
            if (!res.ok) throw new Error('Could not update this feedback.');
            const updated = await res.json();
            setRows(current => current.map(row => (row.id === id ? updated : row)));
        } catch (error) {
            showError(error.message);
        }
    };

    const visible = (rows || []).filter(row => (
        filter === 'all' ? true : filter === 'open' ? ['new', 'in_progress'].includes(row.status) : row.status === filter
    ));

    return (
        <div className="p-6 max-w-6xl mx-auto">
            <div className="flex items-end justify-between mb-4">
                <div>
                    <h1 className="text-2xl font-bold text-gray-900">Feedback</h1>
                    <p className="text-sm text-gray-500 mt-1">Sent from the “Send feedback” link on any page.</p>
                </div>
                <div className="flex items-center gap-2">
                <button onClick={load} className="rounded-lg border border-gray-200 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50">Refresh</button>
                <div className="flex rounded-lg border border-gray-200 overflow-hidden text-sm">
                    {FILTERS.map(([key, label]) => (
                        <button key={key} onClick={() => setFilter(key)}
                            className={`px-3 py-1.5 ${filter === key ? 'bg-gray-900 text-white' : 'bg-white text-gray-700 hover:bg-gray-50'}`}>
                            {label}
                        </button>
                    ))}
                </div>
                </div>
            </div>

            <UsagePanel />

            {loadError ? (
                <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">{loadError} <button onClick={load} className="underline">Try again</button></div>
            ) : rows === null ? (
                <div className="text-sm text-gray-500">Loading…</div>
            ) : visible.length === 0 ? (
                <div className="rounded-xl border border-dashed border-gray-300 p-10 text-center text-sm text-gray-500">{EMPTY_MESSAGES[filter] || 'No feedback yet.'}</div>
            ) : (
                <div className="space-y-3">
                    {visible.map(row => (
                        <div key={row.id} className="rounded-xl border border-gray-200 bg-white p-4">
                            <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-gray-500">
                                <span>
                                    {row.created_at ? new Date(row.created_at).toLocaleString() : ''} · {row.user_email || 'unknown user'} ·{' '}
                                    <Link to={row.page_path} className="font-mono text-blue-600 hover:underline">{row.page_path}</Link>
                                    {row.context?.ad_account_id ? ` · ${row.context.ad_account_id}` : ''}
                                </span>
                                <select value={row.status} onChange={e => update(row.id, { status: e.target.value })}
                                    aria-label="Status" className="rounded-md border border-gray-300 px-2 py-1 text-xs text-gray-800">
                                    {Object.entries(STATUS_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                                </select>
                            </div>
                            <p className="mt-2 whitespace-pre-wrap text-sm text-gray-900">{row.message}</p>
                            {/^https:\/\//i.test(row.screenshot_url || '') && (
                                <a href={row.screenshot_url} target="_blank" rel="noreferrer" className="mt-2 inline-block text-xs text-blue-600 hover:underline">View screenshot</a>
                            )}
                            <input
                                defaultValue={row.resolution_note || ''}
                                onBlur={e => { if ((e.target.value || '') !== (row.resolution_note || '')) update(row.id, { resolution_note: e.target.value }); }}
                                placeholder="Note (e.g. fixed in abc1234)"
                                aria-label="Resolution note"
                                className="mt-2 w-full rounded-md border border-gray-200 px-2 py-1 text-xs text-gray-700 placeholder:text-gray-400"
                            />
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
}
