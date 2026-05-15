import React, { useState, useEffect } from 'react';
import {
    Rocket, Loader, X, CheckCircle2, AlertCircle, ExternalLink,
    PlusCircle, ListFilter, ChevronDown, ChevronUp
} from 'lucide-react';
import { getCampaigns, getAdSets, getPages, createCompleteAd, createFacebookAdSet, authFetch } from '../lib/facebookApi';
import { useToast } from '../context/ToastContext';

const FB_API_BASE = (import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1') + '/facebook';

/**
 * BatchPushModal — push multiple generated images to Meta in one operation.
 *
 * Props:
 *   items                  {Array}   Each item: { key, imageUrl, headline, body, cta, variantName, sizeLabel }
 *   onClose                {function}
 *   preselectedCampaignId  {string}  Meta campaign ID — auto-selects campaign, skips dropdown
 *   preselectedAdsetId     {string}  Meta adset ID — pre-fills "clone from" and defaults to "Create new"
 *   preselectedAdsetName   {string}  Source adset name — used to suggest a new adset name
 */
export default function BatchPushModal({ items, onClose, preselectedCampaignId = '', preselectedAdsetId = '', preselectedAdsetName = '', preselectedWebsiteUrl = '', niche = '' }) {
    const { showError } = useToast();

    // Shared form fields
    const [adAccountId, setAdAccountId] = useState(localStorage.getItem('fb_ad_account_id') || '');
    const [campaigns, setCampaigns] = useState([]);
    const [selectedCampaignId, setSelectedCampaignId] = useState('');
    const [selectedCampaign, setSelectedCampaign] = useState(null);
    const [adSets, setAdSets] = useState([]);
    const [pages, setPages] = useState([]);
    const [pageId, setPageId] = useState(localStorage.getItem('lastUsedPageId') || '');
    const [websiteUrl, setWebsiteUrl] = useState(preselectedWebsiteUrl || localStorage.getItem('lastUsedWebsiteUrl') || '');
    const [sharedCta, setSharedCta] = useState(() => {
        // Default to the most common CTA across items so the dropdown reflects what Joel already chose
        if (!items.length) return 'LEARN_MORE';
        const counts = {};
        items.forEach(it => { const c = it.cta || 'LEARN_MORE'; counts[c] = (counts[c] || 0) + 1; });
        return Object.entries(counts).sort((a, b) => b[1] - a[1])[0][0];
    });
    const [loading, setLoading] = useState(false);

    // Ad set mode — always default to 'new' so Joel creates a fresh ad set each push
    const [adsetMode, setAdsetMode] = useState('new');
    const [sharedAdsetId, setSharedAdsetId] = useState('');
    const today = new Date().toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    const suggestedAdsetName = niche
        ? `${today} - ${niche} - Testing`
        : preselectedAdsetName
        ? `${preselectedAdsetName} - New Creative - ${today}`
        : `${today} - Testing`;
    const [newAdset, setNewAdset] = useState({ name: suggestedAdsetName, dailyBudget: '', cloneFromId: preselectedAdsetId });

    // Per-item copy overrides (editable inline)
    const [itemCopy, setItemCopy] = useState(() =>
        Object.fromEntries(items.map(it => [it.key, { headline: it.headline, body: it.body, cta: it.cta || 'LEARN_MORE' }]))
    );
    const [expandedItem, setExpandedItem] = useState(null);

    // Push state
    const [pushing, setPushing] = useState(false);
    const [pushStatuses, setPushStatuses] = useState({}); // key → 'pending'|'pushing'|'done'|'error'
    const [pushErrors, setPushErrors] = useState({});     // key → error string
    const [isDone, setIsDone] = useState(false);

    const isCBO = selectedCampaign?.isCBO === true;
    const doneItems = items.filter(it => pushStatuses[it.key] === 'done');
    const errorItems = items.filter(it => pushStatuses[it.key] === 'error');

    // Auto-load on mount — fetch ad account ID from backend config so Joel never has to type it
    useEffect(() => {
        const bootstrap = async () => {
            let acctId = adAccountId;
            if (!acctId) {
                try {
                    const cfgRes = await authFetch(`${FB_API_BASE}/config`);
                    const cfg = cfgRes?.ok ? await cfgRes.json() : null;
                    if (cfg?.ad_account_id) {
                        acctId = cfg.ad_account_id;
                        setAdAccountId(acctId);
                        localStorage.setItem('fb_ad_account_id', acctId);
                    }
                } catch (_) { /* fall through — user can type it */ }
            }
            if (acctId) {
                loadPages(acctId);
                loadCampaigns(acctId);
            }
        };
        bootstrap();
    }, []); // eslint-disable-line react-hooks/exhaustive-deps

    // Once campaigns are available (either on mount or after user enters account ID),
    // auto-select the preselected campaign and load its ad sets.
    // This handles the race condition where fb_ad_account_id isn't in localStorage on first open.
    useEffect(() => {
        if (preselectedCampaignId && campaigns.length > 0 && !selectedCampaignId) {
            const match = campaigns.find(c => c.id === preselectedCampaignId);
            if (match) {
                setSelectedCampaignId(match.id);
                setSelectedCampaign(match);
                loadAdSets(match.id);
            }
        }
    }, [campaigns]); // eslint-disable-line react-hooks/exhaustive-deps

    const loadCampaigns = async (acctId) => {
        if (!acctId) return [];
        setLoading(true);
        try {
            const data = await getCampaigns(acctId);
            const list = Array.isArray(data) ? data : [];
            setCampaigns(list);
            return list;
        } catch {
            showError('Failed to load campaigns');
            return [];
        } finally {
            setLoading(false);
        }
    };

    const loadAdSets = async (campaignId) => {
        if (!campaignId) return;
        setLoading(true);
        try {
            const data = await getAdSets(campaignId);
            const list = Array.isArray(data) ? data : [];
            setAdSets(list);
            // When iterating from a known adset, pre-confirm clone source and pre-fill budget.
            // Meta SDK returns adsets where a.id is the Meta adset ID, so match directly first.
            // daily_budget from Meta is in cents — divide by 100 for dollars in the UI.
            let sourceAdset = null;
            if (preselectedAdsetId) {
                sourceAdset = list.find(a => a.id === preselectedAdsetId)
                    || list.find(a => a.fb_adset_id === preselectedAdsetId)
                    || (list.length > 0 ? list[0] : null);
            }
            if (sourceAdset) {
                const budgetDollars = sourceAdset.daily_budget
                    ? Math.round(Number(sourceAdset.daily_budget) / 100)
                    : '';
                setNewAdset(prev => ({
                    ...prev,
                    cloneFromId: sourceAdset.id,
                    dailyBudget: prev.dailyBudget || budgetDollars, // don't overwrite if Joel already typed one
                }));
            }
        } catch {
            showError('Failed to load ad sets');
        } finally {
            setLoading(false);
        }
    };

    const loadPages = async (acctId) => {
        if (!acctId || pages.length > 0) return;
        try {
            const data = await getPages(acctId);
            setPages(Array.isArray(data) ? data : []);
        } catch { /* non-blocking */ }
    };

    const validate = () => {
        if (!adAccountId.trim()) { showError('Ad Account ID is required'); return false; }
        if (!selectedCampaignId) { showError('Select a campaign'); return false; }
        if (!pageId) { showError('Select a Facebook Page'); return false; }
        if (!websiteUrl.trim()) { showError('Destination URL is required'); return false; }
        if (adsetMode === 'existing' && !sharedAdsetId) { showError('Select an ad set'); return false; }
        if (adsetMode === 'new') {
            if (!newAdset.name.trim()) { showError('Ad set name is required'); return false; }
            if (!newAdset.dailyBudget || isNaN(newAdset.dailyBudget) || Number(newAdset.dailyBudget) < 1) {
                showError('Daily budget must be at least $1'); return false;
            }
            if (!newAdset.cloneFromId && adSets.length > 0) {
                showError('Select an ad set to clone targeting from'); return false;
            }
        }
        return true;
    };

    const handlePushAll = async () => {
        if (!validate()) return;
        const campaignLabel = campaigns.find(c => c.id === selectedCampaignId)?.name || selectedCampaignId;
        const adsetLabel = adsetMode === 'existing'
            ? (adSets.find(a => a.id === sharedAdsetId)?.name || sharedAdsetId)
            : `New ad set: "${newAdset.name}"`;
        if (!window.confirm(`Push ${items.length} ad${items.length !== 1 ? 's' : ''} to Meta?\n\nCampaign: ${campaignLabel}\nAd Set: ${adsetLabel}\nDestination: ${websiteUrl}\n\nAds will be created as PAUSED.`)) return;
        setPushStatuses({});
        setPushErrors({});
        setPushing(true);
        setIsDone(false);

        // Initialise all items as pending
        setPushStatuses(Object.fromEntries(items.map(it => [it.key, 'pending'])));

        // Create new ad set once if needed, then reuse the ID for all items
        let targetAdsetId = sharedAdsetId;
        let targetAdsetName = adSets.find(a => a.id === sharedAdsetId)?.name || sharedAdsetId;

        if (adsetMode === 'new') {
            const source = adSets.find(a => a.id === newAdset.cloneFromId);
            // Pass special_ad_categories from the parent campaign so the backend
            // can enforce HEC targeting restrictions (age/gender/geo).
            // Without this, Meta returns error 2909035 on insurance campaigns.
            const campaignSpecialCats = selectedCampaign?.specialAdCategories || [];
            const payload = {
                name: newAdset.name.trim(),
                dailyBudget: Number(newAdset.dailyBudget),
                targeting: source?.targeting || {},
                optimizationGoal: source?.optimization_goal || 'LEAD_GENERATION',
                billingEvent: source?.billing_event || 'IMPRESSIONS',
                bidAmount: source?.bid_amount || null,
                status: 'PAUSED',
                specialAdCategories: campaignSpecialCats,
            };
            try {
                targetAdsetId = await createFacebookAdSet(payload, selectedCampaignId, adAccountId, 'ABO');
                targetAdsetName = newAdset.name.trim();
            } catch (e) {
                showError(`Failed to create ad set: ${e.message}`);
                setPushing(false);
                return;
            }
        }

        // Push each item sequentially so Meta doesn't rate-limit
        const adsetObj = adSets.find(a => a.id === targetAdsetId) || {};
        for (const item of items) {
            setPushStatuses(prev => ({ ...prev, [item.key]: 'pushing' }));
            const copy = itemCopy[item.key];
            try {
                await createCompleteAd(
                    selectedCampaignId,
                    { fbAdsetId: targetAdsetId, ...adsetObj },
                    {
                        mediaType: 'image',
                        imageUrl: item.imageUrl,
                        headlines: [copy.headline || item.headline],
                        bodies: [copy.body || item.body],
                        cta: copy.cta || sharedCta,
                        websiteUrl,
                    },
                    { id: `batch_${item.key}_${Date.now()}`, name: copy.headline || item.headline || 'Batch Ad' },
                    pageId,
                    adAccountId,
                    'ABO'
                );
                setPushStatuses(prev => ({ ...prev, [item.key]: 'done' }));
            } catch (e) {
                setPushStatuses(prev => ({ ...prev, [item.key]: 'error' }));
                setPushErrors(prev => ({ ...prev, [item.key]: e.message }));
            }
        }

        // Persist for next time
        if (pageId) localStorage.setItem('lastUsedPageId', pageId);
        if (adAccountId) localStorage.setItem('fb_ad_account_id', adAccountId);
        if (websiteUrl) localStorage.setItem('lastUsedWebsiteUrl', websiteUrl);
        if (selectedCampaignId) sessionStorage.setItem('lastUsedCampaignId', selectedCampaignId);

        setPushing(false);
        setIsDone(true);
    };

    const adsManagerUrl = adAccountId && selectedCampaignId
        ? `https://adsmanager.facebook.com/adsmanager/manage/ads?act=${adAccountId.replace('act_', '')}&selected_campaign_ids=${selectedCampaignId}`
        : 'https://adsmanager.facebook.com';

    // ── Done screen ───────────────────────────────────────────────────────────
    if (isDone) {
        return (
            <div className="fixed inset-0 bg-black/50 backdrop-blur-sm z-[60] flex items-center justify-center p-4">
                <div className="bg-white rounded-2xl shadow-2xl max-w-lg w-full p-8 text-center" onClick={e => e.stopPropagation()}>
                    <div className={`w-16 h-16 ${errorItems.length === 0 ? 'bg-green-100' : 'bg-amber-100'} rounded-full flex items-center justify-center mx-auto mb-4`}>
                        {errorItems.length === 0
                            ? <CheckCircle2 size={36} className="text-green-600" />
                            : <AlertCircle size={36} className="text-amber-600" />}
                    </div>
                    <h3 className="text-xl font-bold text-gray-900 mb-1">
                        {errorItems.length === 0 ? 'All Ads Pushed!' : `${doneItems.length} of ${items.length} Pushed`}
                    </h3>
                    <p className="text-gray-500 text-sm mb-6">
                        {doneItems.length} succeeded{errorItems.length > 0 ? `, ${errorItems.length} failed` : ''}.
                    </p>

                    {/* Per-item summary */}
                    <div className="space-y-1.5 mb-6 max-h-48 overflow-y-auto text-left">
                        {items.map(item => (
                            <div key={item.key} className="flex items-center gap-2 text-sm">
                                {pushStatuses[item.key] === 'done'
                                    ? <CheckCircle2 size={14} className="text-green-500 shrink-0" />
                                    : <AlertCircle size={14} className="text-red-500 shrink-0" />}
                                <span className="text-gray-700 truncate flex-1">{item.variantName} · {item.sizeLabel}</span>
                                {pushErrors[item.key] && (
                                    <span className="text-red-500 text-xs truncate max-w-[160px]" title={pushErrors[item.key]}>
                                        {pushErrors[item.key]}
                                    </span>
                                )}
                            </div>
                        ))}
                    </div>

                    <div className="flex gap-3">
                        <button onClick={onClose} className="flex-1 px-4 py-3 bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200 font-medium">
                            Close
                        </button>
                        <a
                            href={adsManagerUrl}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="flex-1 px-4 py-3 bg-green-600 text-white rounded-lg hover:bg-green-700 font-medium flex items-center justify-center gap-2"
                        >
                            <ExternalLink size={16} /> View in Ads Manager
                        </a>
                    </div>
                </div>
            </div>
        );
    }

    // ── Main form ─────────────────────────────────────────────────────────────
    return (
        <div className="fixed inset-0 bg-black/50 backdrop-blur-sm z-[60] flex items-center justify-center p-4" onClick={!pushing ? onClose : undefined}>
            <div
                className="bg-white rounded-2xl shadow-2xl max-w-2xl w-full max-h-[92vh] flex flex-col"
                onClick={e => e.stopPropagation()}
            >
                {/* Header */}
                <div className="flex items-center justify-between px-6 pt-5 pb-4 border-b border-gray-100 shrink-0">
                    <div>
                        <h3 className="text-lg font-bold text-gray-900">Push {items.length} Ad{items.length !== 1 ? 's' : ''} to Meta</h3>
                        <p className="text-xs text-gray-500 mt-0.5">All images push to the same ad set. Review copy per image below.</p>
                    </div>
                    {!pushing && (
                        <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
                            <X size={20} />
                        </button>
                    )}
                </div>

                <div className="overflow-y-auto flex-1 px-6 py-4 space-y-5">

                    {/* Ad Account */}
                    <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">Ad Account ID *</label>
                        <input
                            type="text"
                            placeholder="act_123456789"
                            value={adAccountId}
                            disabled={pushing}
                            onChange={e => { setAdAccountId(e.target.value); setCampaigns([]); setAdSets([]); setSelectedCampaignId(''); }}
                            onBlur={() => { loadCampaigns(adAccountId); loadPages(adAccountId); }}
                            className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-green-500 disabled:bg-gray-50"
                        />
                    </div>

                    {/* Campaign — locked when iterating from a known campaign */}
                    <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">Campaign *</label>
                        {preselectedCampaignId && selectedCampaignId ? (
                            <div className="flex items-center gap-2 px-3 py-2 bg-indigo-50 border border-indigo-200 rounded-lg text-sm">
                                <span className="text-indigo-700 font-medium flex-1 truncate">
                                    {campaigns.find(c => c.id === selectedCampaignId)?.name || selectedCampaignId}
                                </span>
                                <span className="text-xs text-indigo-400 shrink-0">From your campaign</span>
                            </div>
                        ) : (
                            <select
                                value={selectedCampaignId}
                                disabled={pushing || campaigns.length === 0}
                                onChange={e => {
                                    const c = campaigns.find(x => x.id === e.target.value) || null;
                                    setSelectedCampaign(c);
                                    setSelectedCampaignId(e.target.value);
                                    setAdSets([]);
                                    setSharedAdsetId('');
                                    // Keep adsetMode as 'new' — Joel should always explicitly choose to use existing
                                    setNewAdset({ name: suggestedAdsetName, dailyBudget: '', cloneFromId: '' });
                                    loadAdSets(e.target.value);
                                }}
                                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-green-500 disabled:bg-gray-50"
                            >
                                <option value="">
                                    {loading ? 'Loading...' : campaigns.length === 0 ? 'Enter Ad Account ID first' : 'Select a campaign...'}
                                </option>
                                {campaigns.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
                            </select>
                        )}
                    </div>

                    {/* Ad Set */}
                    {selectedCampaignId && (
                        <div>
                            <label className="block text-sm font-medium text-gray-700 mb-2">Ad Set *</label>
                            <div className="flex gap-2 mb-3">
                                <button
                                    type="button"
                                    disabled={pushing}
                                    onClick={() => setAdsetMode('existing')}
                                    className={`flex-1 flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg text-sm font-medium border transition-colors ${
                                        adsetMode === 'existing' ? 'bg-green-50 border-green-500 text-green-700' : 'bg-white border-gray-300 text-gray-600 hover:bg-gray-50'
                                    }`}
                                >
                                    <ListFilter size={14} /> Use existing
                                </button>
                                <button
                                    type="button"
                                    disabled={pushing}
                                    onClick={() => setAdsetMode('new')}
                                    className={`flex-1 flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg text-sm font-medium border transition-colors ${
                                        adsetMode === 'new' ? 'bg-green-50 border-green-500 text-green-700' : 'bg-white border-gray-300 text-gray-600 hover:bg-gray-50'
                                    }`}
                                >
                                    <PlusCircle size={14} /> Create new
                                </button>
                            </div>

                            {adsetMode === 'existing' ? (
                                <select
                                    value={sharedAdsetId}
                                    disabled={pushing || loading || adSets.length === 0}
                                    onChange={e => setSharedAdsetId(e.target.value)}
                                    className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-green-500 disabled:bg-gray-50"
                                >
                                    <option value="">
                                        {loading ? 'Loading...' : adSets.length === 0 ? 'No ad sets — create one first' : 'Select an ad set...'}
                                    </option>
                                    {adSets.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
                                </select>
                            ) : (
                                <div className="space-y-3 p-3 bg-green-50 border border-green-200 rounded-lg">
                                    {/* Empty targeting warning */}
                                    {adSets.length === 0 && (
                                        <div className="flex items-start gap-2 p-2 bg-red-50 border border-red-200 rounded-lg text-xs text-red-800">
                                            <span className="mt-0.5 shrink-0">⚠️</span>
                                            <span>No existing ad sets to clone from. New ad set will have <strong>empty targeting</strong> — set geo, age, and audience manually in Ads Manager before activating.</span>
                                        </div>
                                    )}
                                    {/* Custom audience warning */}
                                    <div className="flex items-start gap-2 p-2 bg-amber-50 border border-amber-200 rounded-lg text-xs text-amber-800">
                                        <span className="mt-0.5 shrink-0">⚠️</span>
                                        <span>Custom audiences (lookalikes, customer lists) are <strong>not copied</strong> when cloning — add them manually in Ads Manager.</span>
                                    </div>
                                    {/* CBO warning */}
                                    {isCBO && (
                                        <div className="flex items-start gap-2 p-2 bg-amber-50 border border-amber-200 rounded-lg text-xs text-amber-800">
                                            <span className="mt-0.5 shrink-0">⚠️</span>
                                            <span>CBO campaign — budget is managed at campaign level. Daily budget below may be ignored by Meta.</span>
                                        </div>
                                    )}
                                    <div>
                                        <label className="block text-xs font-medium text-gray-600 mb-1">Ad Set Name *</label>
                                        <input
                                            type="text"
                                            placeholder="e.g. Church Insurance — Square — May 12"
                                            value={newAdset.name}
                                            disabled={pushing}
                                            onChange={e => setNewAdset(p => ({ ...p, name: e.target.value }))}
                                            className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm bg-white focus:ring-2 focus:ring-green-500"
                                        />
                                    </div>
                                    <div>
                                        <label className="block text-xs font-medium text-gray-600 mb-1">Daily Budget (USD) *</label>
                                        <div className="relative">
                                            <span className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 text-sm">$</span>
                                            <input
                                                type="number" min="1" step="1" placeholder="50"
                                                value={newAdset.dailyBudget}
                                                disabled={pushing}
                                                onChange={e => setNewAdset(p => ({ ...p, dailyBudget: e.target.value }))}
                                                className="w-full pl-7 pr-3 py-2 border border-gray-300 rounded-lg text-sm bg-white focus:ring-2 focus:ring-green-500"
                                            />
                                        </div>
                                    </div>
                                    <div>
                                        <label className="block text-xs font-medium text-gray-600 mb-1">Clone targeting from *</label>
                                        <select
                                            value={newAdset.cloneFromId}
                                            disabled={pushing || loading || adSets.length === 0}
                                            onChange={e => setNewAdset(p => ({ ...p, cloneFromId: e.target.value }))}
                                            className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm bg-white focus:ring-2 focus:ring-green-500"
                                        >
                                            <option value="">
                                                {loading ? 'Loading...' : adSets.length === 0 ? 'No ad sets in this campaign' : 'Pick a source ad set...'}
                                            </option>
                                            {adSets.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
                                        </select>
                                        <p className="text-xs text-gray-500 mt-1">Copies geo, age, placements & optimization. Custom audiences not copied.</p>
                                    </div>
                                    <p className="text-xs text-amber-700">New ad set is created as Paused — activate in Ads Manager after reviewing.</p>
                                </div>
                            )}
                        </div>
                    )}

                    {/* Page + URL row */}
                    <div className="grid grid-cols-2 gap-4">
                        <div>
                            <label className="block text-sm font-medium text-gray-700 mb-1">Facebook Page *</label>
                            {pages.length > 0 ? (
                                <select
                                    value={pageId}
                                    disabled={pushing}
                                    onChange={e => setPageId(e.target.value)}
                                    className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-green-500 disabled:bg-gray-50"
                                >
                                    <option value="">Select a page...</option>
                                    {pages.map(pg => <option key={pg.id} value={pg.id}>{pg.name}</option>)}
                                </select>
                            ) : (
                                <input
                                    type="text" placeholder="Page ID"
                                    value={pageId}
                                    disabled={pushing}
                                    onChange={e => setPageId(e.target.value)}
                                    className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-green-500 disabled:bg-gray-50"
                                />
                            )}
                        </div>
                        <div>
                            <label className="block text-sm font-medium text-gray-700 mb-1">Destination URL *</label>
                            <input
                                type="url" placeholder="https://..."
                                value={websiteUrl}
                                disabled={pushing}
                                onChange={e => setWebsiteUrl(e.target.value)}
                                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-green-500 disabled:bg-gray-50"
                            />
                        </div>
                    </div>

                    {/* Default CTA — applies to all ads unless overridden per-item */}
                    <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">
                            Default CTA
                            <span className="ml-1 text-xs font-normal text-gray-400">— applies to all ads (override per-item below)</span>
                        </label>
                        <select
                            value={sharedCta}
                            disabled={pushing}
                            onChange={e => {
                                setSharedCta(e.target.value);
                                // Apply to all items that haven't been individually overridden
                                setItemCopy(prev => Object.fromEntries(
                                    Object.entries(prev).map(([k, v]) => [k, { ...v, cta: e.target.value }])
                                ));
                            }}
                            className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-green-500 disabled:bg-gray-50"
                        >
                            {[
                                ['LEARN_MORE', 'Learn More'],
                                ['GET_QUOTE', 'Get Quote'],
                                ['SIGN_UP', 'Sign Up'],
                                ['CONTACT_US', 'Contact Us'],
                                ['SHOP_NOW', 'Shop Now'],
                                ['DOWNLOAD', 'Download'],
                                ['BOOK_NOW', 'Book Now'],
                            ].map(([val, label]) => (
                                <option key={val} value={val}>{label}</option>
                            ))}
                        </select>
                    </div>

                    {/* Ad items — expandable copy overrides */}
                    <div>
                        <label className="block text-sm font-medium text-gray-700 mb-2">
                            Ads to push
                            <span className="ml-1 text-xs font-normal text-gray-400">— click any row to edit copy</span>
                        </label>
                        <div className="space-y-2">
                            {items.map(item => {
                                const status = pushStatuses[item.key];
                                const copy = itemCopy[item.key];
                                const isExpanded = expandedItem === item.key;

                                return (
                                    <div key={item.key} className="border border-gray-200 rounded-xl overflow-hidden">
                                        {/* Row header */}
                                        <div
                                            className="flex items-center gap-3 px-3 py-2.5 cursor-pointer hover:bg-gray-50"
                                            onClick={() => !pushing && setExpandedItem(isExpanded ? null : item.key)}
                                        >
                                            {/* Thumbnail */}
                                            <img
                                                src={item.imageUrl}
                                                alt=""
                                                className="w-10 h-10 object-cover rounded-lg shrink-0 bg-gray-100"
                                            />
                                            {/* Labels */}
                                            <div className="flex-1 min-w-0">
                                                <p className="text-sm font-medium text-gray-800 truncate">{copy.headline || item.headline || '—'}</p>
                                                <p className="text-xs text-gray-400">{item.variantName} · {item.sizeLabel}</p>
                                            </div>
                                            {/* Status badge */}
                                            <div className="shrink-0">
                                                {!status && (
                                                    isExpanded
                                                        ? <ChevronUp size={14} className="text-gray-400" />
                                                        : <ChevronDown size={14} className="text-gray-400" />
                                                )}
                                                {status === 'pending' && <span className="text-xs text-gray-400">Queued</span>}
                                                {status === 'pushing' && <Loader size={14} className="animate-spin text-blue-500" />}
                                                {status === 'done' && <CheckCircle2 size={16} className="text-green-500" />}
                                                {status === 'error' && (
                                                    <span className="text-xs text-red-500" title={pushErrors[item.key]}>Failed</span>
                                                )}
                                            </div>
                                        </div>

                                        {/* Expandable copy editor */}
                                        {isExpanded && !pushing && (
                                            <div className="px-3 pb-3 pt-1 border-t border-gray-100 bg-gray-50 space-y-2">
                                                <div>
                                                    <label className="text-xs font-medium text-gray-600">Headline</label>
                                                    <input
                                                        type="text"
                                                        value={copy.headline}
                                                        onChange={e => setItemCopy(p => ({ ...p, [item.key]: { ...p[item.key], headline: e.target.value } }))}
                                                        className="w-full mt-1 px-2 py-1.5 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-green-500 bg-white"
                                                    />
                                                </div>
                                                <div>
                                                    <label className="text-xs font-medium text-gray-600">Body</label>
                                                    <textarea
                                                        rows={2}
                                                        value={copy.body}
                                                        onChange={e => setItemCopy(p => ({ ...p, [item.key]: { ...p[item.key], body: e.target.value } }))}
                                                        className="w-full mt-1 px-2 py-1.5 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-green-500 bg-white"
                                                    />
                                                </div>
                                                <div>
                                                    <label className="text-xs font-medium text-gray-600">CTA</label>
                                                    <select
                                                        value={copy.cta}
                                                        onChange={e => setItemCopy(p => ({ ...p, [item.key]: { ...p[item.key], cta: e.target.value } }))}
                                                        className="w-full mt-1 px-2 py-1.5 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-green-500 bg-white"
                                                    >
                                                        {['LEARN_MORE','SHOP_NOW','SIGN_UP','CONTACT_US','DOWNLOAD','BOOK_NOW','GET_QUOTE'].map(c =>
                                                            <option key={c} value={c}>{c.replace(/_/g,' ')}</option>
                                                        )}
                                                    </select>
                                                </div>
                                            </div>
                                        )}
                                    </div>
                                );
                            })}
                        </div>
                    </div>
                </div>

                {/* Footer */}
                <div className="px-6 py-4 border-t border-gray-100 shrink-0">
                    {/* Progress bar during push */}
                    {pushing && (
                        <div className="mb-3">
                            <div className="flex justify-between text-xs text-gray-500 mb-1">
                                <span>Pushing ads to Meta...</span>
                                <span>{doneItems.length + errorItems.length} / {items.length}</span>
                            </div>
                            <div className="w-full bg-gray-200 rounded-full h-1.5">
                                <div
                                    className="bg-green-500 h-1.5 rounded-full transition-all"
                                    style={{ width: `${((doneItems.length + errorItems.length) / items.length) * 100}%` }}
                                />
                            </div>
                        </div>
                    )}
                    <div className="flex gap-3">
                        <button
                            onClick={onClose}
                            disabled={pushing}
                            className="flex-1 px-4 py-3 bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200 font-medium disabled:opacity-50"
                        >
                            Cancel
                        </button>
                        <button
                            onClick={handlePushAll}
                            disabled={pushing}
                            className="flex-1 px-4 py-3 bg-green-600 text-white rounded-lg hover:bg-green-700 font-medium flex items-center justify-center gap-2 disabled:bg-gray-300 disabled:cursor-not-allowed"
                        >
                            {pushing
                                ? <><Loader className="animate-spin" size={18} /> Pushing {items.length} ads...</>
                                : <><Rocket size={18} /> Push {items.length} Ad{items.length !== 1 ? 's' : ''} to Meta</>
                            }
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
}
