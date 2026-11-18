import React, { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowRight, ExternalLink, Loader2 } from 'lucide-react';
import { authFetch } from '../lib/facebookApi';
import { useToast } from '../context/ToastContext';

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1';

// GetHookd bridge (Steve, 2026-11-18). Joel finds ads in GetHookd; this lists the workspace's saved ads and any ad
// pasted by link, and "Build like this" opens Build New Ad with the ad as a REFERENCE: its copy as a starting point
// to rewrite in our voice and its image as the template our own image is generated from. Never launched as-is, and
// the competitor's landing page never comes across (the backend drops it).
async function readJson(res) {
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body.detail || `Request failed (${res.status})`);
    return body;
}

function AdCard({ ad, onBuild, building }) {
    return (
        <article className="flex flex-col overflow-hidden rounded-lg border border-gray-200 bg-white">
            <div className="aspect-[4/3] bg-gray-100">
                {ad.thumbnail_url
                    ? <img src={ad.thumbnail_url} alt="" loading="lazy" className="h-full w-full object-cover" />
                    : <div className="flex h-full items-center justify-center text-xs text-gray-500">No preview</div>}
            </div>
            <div className="flex flex-1 flex-col gap-1.5 p-3">
                <p className="truncate text-xs text-gray-500">{ad.brand_name || 'Unknown advertiser'}</p>
                <p className="line-clamp-2 text-sm font-semibold text-gray-900">{ad.headline || ad.body?.slice(0, 80) || 'No headline'}</p>
                <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-gray-500">
                    {ad.format && <span className="capitalize">{ad.format}</span>}
                    {ad.days_active != null && <span>{ad.days_active} days{ad.status === 'active' ? ' · running' : ''}</span>}
                    {ad.performance && <span className="rounded-full bg-emerald-50 px-1.5 py-0.5 font-semibold text-emerald-700">{ad.performance}</span>}
                </p>
                <div className="mt-auto flex items-center justify-between gap-2 pt-2">
                    <button
                        type="button"
                        onClick={() => onBuild(ad)}
                        disabled={building}
                        className="inline-flex items-center gap-1.5 rounded-lg bg-gray-900 px-3 py-1.5 text-xs font-semibold text-white hover:bg-black disabled:opacity-50"
                    >
                        {building ? <Loader2 size={13} className="animate-spin" /> : <ArrowRight size={13} />}
                        Build like this
                    </button>
                    {ad.share_url && (
                        <a href={ad.share_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-xs font-semibold text-blue-600 hover:text-blue-700 hover:underline">
                            GetHookd <ExternalLink size={11} />
                        </a>
                    )}
                </div>
            </div>
        </article>
    );
}

export default function GetHookdPanel() {
    const navigate = useNavigate();
    const { showError, showWarning } = useToast();
    const [state, setState] = useState({ loading: true, connected: true, ads: [], error: null });
    const [pasted, setPasted] = useState('');
    const [looking, setLooking] = useState(false);
    const [buildingId, setBuildingId] = useState(null);

    const load = useCallback(async () => {
        try {
            const status = await readJson(await authFetch(`${API_BASE}/gethookd/status`));
            if (!status.connected) {
                setState({ loading: false, connected: false, ads: [], error: null });
                return;
            }
            const saved = await readJson(await authFetch(`${API_BASE}/gethookd/saved`));
            setState({ loading: false, connected: true, ads: saved.ads || [], error: null });
        } catch (error) {
            setState(prev => ({ ...prev, loading: false, error: error.message }));
        }
    }, []);

    useEffect(() => { load(); }, [load]);

    const lookUp = async (event) => {
        event.preventDefault();
        if (!pasted.trim()) return;
        setLooking(true);
        try {
            const ad = await readJson(await authFetch(`${API_BASE}/gethookd/ad?ref=${encodeURIComponent(pasted.trim())}`));
            setState(prev => ({ ...prev, ads: [ad, ...prev.ads.filter(existing => existing.id !== ad.id)] }));
            setPasted('');
        } catch (error) {
            showError(error.message);
        } finally {
            setLooking(false);
        }
    };

    const build = async (ad) => {
        setBuildingId(ad.id);
        try {
            const ref = await readJson(await authFetch(`${API_BASE}/gethookd/reference`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ ad_id: ad.id }),
            }));
            if (!ref.reference_image_url) showWarning("Couldn't copy this ad's image; the remix will start from its copy only.");
            // Same handoff Campaign Performance's Remix drawer uses. No link_url: the destination is always ours,
            // entered at push time (the competitor's landing page never leaves the backend).
            localStorage.setItem('pendingRemixCreative', JSON.stringify({
                ad_name: `GetHookd · ${ref.brand_name || 'reference'}`,
                image_url: ref.reference_image_url || null,
                headline: ref.headline || '',
                body: ref.body || '',
                source: 'gethookd',
                gethookd_share_url: ref.share_url || null,
            }));
            navigate('/ad-remix');
        } catch (error) {
            showError(error.message);
            setBuildingId(null);
        }
    };

    return (
        <section className="rounded-xl border border-gray-200 bg-white p-5" aria-label="From GetHookd">
            <div className="flex flex-wrap items-end justify-between gap-3">
                <div>
                    <h2 className="text-base font-semibold text-gray-900">From GetHookd</h2>
                    <p className="mt-0.5 text-sm text-gray-600">Your saved ads. Build our own version of one, or paste any GetHookd ad link.</p>
                </div>
                {state.connected && (
                    <form onSubmit={lookUp} className="flex w-full max-w-md gap-2">
                        <input
                            value={pasted}
                            onChange={event => setPasted(event.target.value)}
                            placeholder="Paste a GetHookd ad link"
                            className="min-w-0 flex-1 rounded-lg border border-gray-300 px-3 py-1.5 text-sm focus:border-gray-900 focus:outline-none focus:ring-2 focus:ring-gray-200"
                        />
                        <button type="submit" disabled={looking || !pasted.trim()} className="rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-sm font-semibold text-gray-900 hover:bg-gray-50 disabled:opacity-50">
                            {looking ? 'Opening…' : 'Open'}
                        </button>
                    </form>
                )}
            </div>
            <div className="mt-4">
                {state.loading && <p className="text-sm text-gray-500">Loading your GetHookd saves…</p>}
                {!state.loading && !state.connected && (
                    <p className="rounded-lg bg-gray-50 px-3 py-2 text-sm text-gray-600">GetHookd isn&apos;t connected yet. Once its API key is added, your saved ads show up here.</p>
                )}
                {!state.loading && state.error && <p role="alert" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">{state.error}</p>}
                {!state.loading && state.connected && !state.error && state.ads.length === 0 && (
                    <p className="text-sm text-gray-500">Nothing saved yet. Save an ad in GetHookd, or paste its link above.</p>
                )}
                {state.ads.length > 0 && (
                    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
                        {state.ads.map(ad => <AdCard key={ad.id} ad={ad} onBuild={build} building={buildingId === ad.id} />)}
                    </div>
                )}
                <p className="mt-3 text-xs text-gray-500">Used as a reference only: we write our own copy and generate our own image. Their landing page is never used.</p>
            </div>
        </section>
    );
}
