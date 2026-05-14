import React, { useState, useEffect } from 'react';
import { Rocket, Loader, X, CheckCircle2, ExternalLink, PlusCircle, ListFilter } from 'lucide-react';
import { getCampaigns, getAdSets, getPages, createCompleteAd, createFacebookAdSet } from '../lib/facebookApi';
import { useToast } from '../context/ToastContext';

// Meta copy limits (characters before truncation)
const HEADLINE_LIMIT = 40;
const BODY_LIMIT = 125;

/**
 * Shared Push to Meta modal.
 * Works from both GeneratedAds library and ImageAds results page.
 *
 * Props:
 *   imageUrl          {string}   URL of the image to push to Meta
 *   initialHeadline   {string}   Pre-fill headline from the ad copy
 *   initialBody       {string}   Pre-fill body copy
 *   initialCta        {string}   Pre-fill CTA (defaults to LEARN_MORE)
 *   initialWebsiteUrl {string}   Pre-fill destination URL
 *   initialCampaignId {string}   Pre-select campaign in dropdown
 *   onClose           {function} Called when the modal should close
 *   onSuccess         {function} Optional — called after a successful push
 */
export default function PushToMetaModal({
    imageUrl,
    initialHeadline = '',
    initialBody = '',
    initialCta = 'LEARN_MORE',
    initialWebsiteUrl = '',
    initialCampaignId = '',
    niche = '',
    onClose,
    onSuccess,
}) {
    const { showError } = useToast();

    const [pushCampaigns, setPushCampaigns] = useState([]);
    const [pushAdSets, setPushAdSets] = useState([]);
    const [pushPages, setPushPages] = useState([]);
    const [pushLoading, setPushLoading] = useState(false);
    const [pushSubmitting, setPushSubmitting] = useState(false);
    const [successResult, setSuccessResult] = useState(null);

    // Always default to 'new' — Joel always creates a fresh ad set when pushing
    const [adsetMode, setAdsetMode] = useState('new');
    const _today = new Date().toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    const [newAdset, setNewAdset] = useState({
        name: niche ? `${_today} - ${niche} - Testing` : `${_today} - Testing`,
        dailyBudget: '',
        cloneFromId: '',   // ad set ID to copy targeting/optimization from
    });

    const [selectedCampaign, setSelectedCampaign] = useState(null);

    const [pushForm, setPushForm] = useState({
        adAccountId: localStorage.getItem('fb_ad_account_id') || '',
        campaignId: '',
        adsetId: '',
        pageId: localStorage.getItem('lastUsedPageId') || '',
        websiteUrl: initialWebsiteUrl || localStorage.getItem('lastUsedWebsiteUrl') || '',
        headline: initialHeadline,
        body: initialBody,
        cta: initialCta || 'LEARN_MORE',
    });

    // Auto-load campaigns + pages if ad account ID is already populated on mount
    useEffect(() => {
        if (pushForm.adAccountId) {
            loadPushCampaigns(pushForm.adAccountId);
            loadPushPages(pushForm.adAccountId);
        }
    }, []); // eslint-disable-line react-hooks/exhaustive-deps

    // Auto-select campaign once the list loads (from initialCampaignId or last used)
    useEffect(() => {
        const targetId = initialCampaignId || localStorage.getItem('lastUsedCampaignId') || '';
        if (targetId && pushCampaigns.length > 0 && !pushForm.campaignId) {
            const match = pushCampaigns.find(c => c.id === targetId);
            if (match) {
                setSelectedCampaign(match);
                setPushForm(p => ({ ...p, campaignId: match.id, adsetId: '' }));
                setPushAdSets([]);
                // Do NOT override adsetMode — keep the 'new' default
                loadPushAdSets(match.id);
            }
        }
    }, [pushCampaigns]); // eslint-disable-line react-hooks/exhaustive-deps

    const loadPushCampaigns = async (adAccountId) => {
        if (!adAccountId) return;
        setPushLoading(true);
        try {
            const campaigns = await getCampaigns(adAccountId);
            setPushCampaigns(Array.isArray(campaigns) ? campaigns : []);
        } catch (e) {
            showError('Failed to load campaigns');
        } finally {
            setPushLoading(false);
        }
    };

    const isCBOCampaign = selectedCampaign?.isCBO === true;

    const loadPushAdSets = async (campaignId) => {
        if (!campaignId) return;
        setPushLoading(true);
        try {
            const adsets = await getAdSets(campaignId);
            setPushAdSets(Array.isArray(adsets) ? adsets : []);
        } catch (e) {
            showError('Failed to load ad sets');
        } finally {
            setPushLoading(false);
        }
    };

    const loadPushPages = async (adAccountId) => {
        if (!adAccountId || pushPages.length > 0) return;
        try {
            const pages = await getPages(adAccountId);
            setPushPages(Array.isArray(pages) ? pages : []);
        } catch (e) { /* non-blocking */ }
    };

    const handlePushToFacebook = async () => {
        // Validate shared fields
        if (!pushForm.campaignId || !pushForm.pageId || !pushForm.websiteUrl) {
            showError('Please fill in all required fields');
            return;
        }

        // Validate ad set section
        if (adsetMode === 'existing' && !pushForm.adsetId) {
            showError('Please select an ad set');
            return;
        }
        if (adsetMode === 'new') {
            if (!newAdset.name.trim()) { showError('Ad set name is required'); return; }
            if (!newAdset.dailyBudget || isNaN(newAdset.dailyBudget) || Number(newAdset.dailyBudget) < 1) {
                showError('Daily budget must be at least $1'); return;
            }
            if (!newAdset.cloneFromId) {
                if (pushAdSets.length === 0) {
                    showError('This campaign has no ad sets to clone targeting from. Create one in Ads Manager first, then retry.');
                } else {
                    showError('Select an ad set to clone targeting from');
                }
                return;
            }
        }

        setPushSubmitting(true);
        let createdAdsetId = null;
        let createdAdsetName = null;
        try {
            let targetAdsetId = pushForm.adsetId;
            let targetAdsetName = pushAdSets.find(a => a.id === pushForm.adsetId)?.name || pushForm.adsetId;

            if (adsetMode === 'new') {
                // Clone targeting + settings from the chosen source ad set
                const source = pushAdSets.find(a => a.id === newAdset.cloneFromId);
                const adsetPayload = {
                    name: newAdset.name.trim(),
                    dailyBudget: Number(newAdset.dailyBudget), // backend handles cents conversion
                    targeting: source?.targeting || {},
                    optimizationGoal: source?.optimization_goal || 'LEAD_GENERATION',
                    billingEvent: source?.billing_event || 'IMPRESSIONS',
                    bidAmount: source?.bid_amount || null,
                    status: 'PAUSED',
                };
                targetAdsetId = await createFacebookAdSet(
                    adsetPayload,
                    pushForm.campaignId,
                    pushForm.adAccountId,
                    'ABO'
                );
                targetAdsetName = newAdset.name.trim();
                // Track so we can report partial failure if ad push fails
                createdAdsetId = targetAdsetId;
                createdAdsetName = targetAdsetName;
            }

            const adsetObj = pushAdSets.find(a => a.id === targetAdsetId) || {};
            const result = await createCompleteAd(
                pushForm.campaignId,
                { fbAdsetId: targetAdsetId, ...adsetObj },
                {
                    mediaType: 'image',
                    imageUrl,
                    headlines: [pushForm.headline],
                    bodies: [pushForm.body],
                    cta: pushForm.cta,
                    websiteUrl: pushForm.websiteUrl,
                },
                { id: `pushed_img_${Date.now()}`, name: pushForm.headline || 'Ad from Image Builder' },
                pushForm.pageId,
                pushForm.adAccountId,
                'ABO'
            );

            // Persist selections for next use
            if (pushForm.pageId) localStorage.setItem('lastUsedPageId', pushForm.pageId);
            if (pushForm.adAccountId) localStorage.setItem('fb_ad_account_id', pushForm.adAccountId);
            if (pushForm.websiteUrl) localStorage.setItem('lastUsedWebsiteUrl', pushForm.websiteUrl);
            if (pushForm.campaignId) localStorage.setItem('lastUsedCampaignId', pushForm.campaignId);

            setSuccessResult({
                adId: result?.adId,
                adsetName: targetAdsetName,
                isNewAdset: adsetMode === 'new',
                campaignId: pushForm.campaignId,
                adAccountId: pushForm.adAccountId,
            });
            if (onSuccess) onSuccess();
        } catch (e) {
            if (createdAdsetId) {
                // Ad set was created successfully but ad push failed — give a direct link
                const adsManagerUrl = pushForm.adAccountId && pushForm.campaignId
                    ? `https://adsmanager.facebook.com/adsmanager/manage/adsets?act=${pushForm.adAccountId.replace('act_', '')}&selected_campaign_ids=${pushForm.campaignId}`
                    : 'https://adsmanager.facebook.com';
                showError(
                    `Ad set "${createdAdsetName}" was created, but the ad failed to push. Open Ads Manager to delete the empty ad set and try again: ${adsManagerUrl}`
                );
            } else {
                showError(`Failed to push ad: ${e.message}`);
            }
        } finally {
            setPushSubmitting(false);
        }
    };

    // Character count colour helper
    const countColor = (len, limit) =>
        len > limit ? 'text-red-600 font-semibold' : len > limit * 0.85 ? 'text-amber-600' : 'text-gray-400';

    // ── Success screen ────────────────────────────────────────────────────────
    if (successResult) {
        const adsManagerUrl = successResult.adAccountId && successResult.campaignId
            ? `https://adsmanager.facebook.com/adsmanager/manage/ads?act=${successResult.adAccountId.replace('act_', '')}&selected_campaign_ids=${successResult.campaignId}`
            : 'https://adsmanager.facebook.com';

        return (
            <div
                className="fixed inset-0 bg-black/50 backdrop-blur-sm z-[60] flex items-center justify-center p-4"
                onClick={onClose}
            >
                <div
                    className="bg-white rounded-2xl shadow-2xl max-w-lg w-full p-8 text-center"
                    onClick={(e) => e.stopPropagation()}
                >
                    <div className="w-16 h-16 bg-green-100 rounded-full flex items-center justify-center mx-auto mb-4">
                        <CheckCircle2 size={36} className="text-green-600" />
                    </div>
                    <h3 className="text-xl font-bold text-gray-900 mb-2">Ad Pushed to Meta!</h3>
                    <p className="text-gray-500 text-sm mb-6">Your ad is now in Ads Manager.</p>
                    <div className="bg-gray-50 rounded-xl p-4 text-left space-y-2 mb-6 text-sm">
                        {successResult.adId && (
                            <div className="flex justify-between">
                                <span className="text-gray-500">Ad ID</span>
                                <span className="font-mono text-gray-800">{successResult.adId}</span>
                            </div>
                        )}
                        <div className="flex justify-between">
                            <span className="text-gray-500">Ad Set</span>
                            <span className="font-medium text-gray-800 truncate max-w-[200px]">
                                {successResult.isNewAdset && <span className="text-green-600 mr-1">New</span>}
                                {successResult.adsetName}
                            </span>
                        </div>
                        <div className="flex justify-between">
                            <span className="text-gray-500">Status</span>
                            <span className="text-amber-700 font-medium">Paused — review in Ads Manager</span>
                        </div>
                    </div>
                    <div className="flex gap-3">
                        <button
                            onClick={onClose}
                            className="flex-1 px-4 py-3 bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200 font-medium"
                        >
                            Close
                        </button>
                        <a
                            href={adsManagerUrl}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="flex-1 px-4 py-3 bg-green-600 text-white rounded-lg hover:bg-green-700 font-medium flex items-center justify-center gap-2"
                        >
                            <ExternalLink size={16} />
                            View in Ads Manager
                        </a>
                    </div>
                </div>
            </div>
        );
    }

    // ── Main form ─────────────────────────────────────────────────────────────
    return (
        <div
            className="fixed inset-0 bg-black/50 backdrop-blur-sm z-[60] flex items-center justify-center p-4"
            onClick={onClose}
        >
            <div
                className="bg-white rounded-2xl shadow-2xl max-w-lg w-full p-6 max-h-[90vh] overflow-y-auto"
                onClick={(e) => e.stopPropagation()}
            >
                <div className="flex items-center justify-between mb-4">
                    <h3 className="text-xl font-bold text-gray-900">Push Ad to Facebook Campaign</h3>
                    <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
                        <X size={20} />
                    </button>
                </div>

                <div className="space-y-4">
                    {/* Ad Account ID */}
                    <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">Ad Account ID *</label>
                        <input
                            type="text"
                            placeholder="act_123456789"
                            value={pushForm.adAccountId}
                            onChange={(e) => {
                                setPushForm(p => ({ ...p, adAccountId: e.target.value, campaignId: '', adsetId: '' }));
                                setPushCampaigns([]);
                                setPushAdSets([]);
                            }}
                            onBlur={() => {
                                loadPushCampaigns(pushForm.adAccountId);
                                loadPushPages(pushForm.adAccountId);
                            }}
                            className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-green-500"
                        />
                    </div>

                    {/* Campaign */}
                    <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">Campaign *</label>
                        <select
                            value={pushForm.campaignId}
                            onChange={(e) => {
                                const campaign = pushCampaigns.find(c => c.id === e.target.value) || null;
                                setSelectedCampaign(campaign);
                                setPushForm(p => ({ ...p, campaignId: e.target.value, adsetId: '' }));
                                setPushAdSets([]);
                                // Keep adsetMode as 'new' (user can switch to existing if needed)
                                // Preserve the niche-derived name; clear only targeting clone
                                setNewAdset(p => ({ ...p, cloneFromId: '' }));
                                loadPushAdSets(e.target.value);
                            }}
                            className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-green-500"
                            disabled={pushCampaigns.length === 0}
                        >
                            <option value="">
                                {pushLoading ? 'Loading...' : pushCampaigns.length === 0 ? 'Enter Ad Account ID first' : 'Select a campaign...'}
                            </option>
                            {pushCampaigns.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
                        </select>
                    </div>

                    {/* Ad Set — mode toggle + fields */}
                    {pushForm.campaignId && (
                        <div>
                            <label className="block text-sm font-medium text-gray-700 mb-2">Ad Set *</label>

                            {/* Toggle */}
                            <div className="flex gap-2 mb-3">
                                <button
                                    type="button"
                                    onClick={() => setAdsetMode('existing')}
                                    className={`flex-1 flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg text-sm font-medium border transition-colors ${
                                        adsetMode === 'existing'
                                            ? 'bg-green-50 border-green-500 text-green-700'
                                            : 'bg-white border-gray-300 text-gray-600 hover:bg-gray-50'
                                    }`}
                                >
                                    <ListFilter size={14} />
                                    Use existing
                                </button>
                                <button
                                    type="button"
                                    onClick={() => setAdsetMode('new')}
                                    className={`flex-1 flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg text-sm font-medium border transition-colors ${
                                        adsetMode === 'new'
                                            ? 'bg-green-50 border-green-500 text-green-700'
                                            : 'bg-white border-gray-300 text-gray-600 hover:bg-gray-50'
                                    }`}
                                >
                                    <PlusCircle size={14} />
                                    Create new
                                </button>
                            </div>

                            {adsetMode === 'existing' ? (
                                <select
                                    value={pushForm.adsetId}
                                    onChange={(e) => setPushForm(p => ({ ...p, adsetId: e.target.value }))}
                                    className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-green-500"
                                    disabled={pushLoading || pushAdSets.length === 0}
                                >
                                    <option value="">
                                        {pushLoading
                                            ? 'Loading...'
                                            : pushAdSets.length === 0
                                                ? 'No ad sets found — create one in Ads Manager first'
                                                : 'Select an ad set...'}
                                    </option>
                                    {pushAdSets.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
                                </select>
                            ) : (
                                <div className="space-y-3 p-3 bg-green-50 border border-green-200 rounded-lg">
                                    {/* CBO warning */}
                                    {isCBOCampaign && (
                                        <div className="flex items-start gap-2 p-2 bg-amber-50 border border-amber-200 rounded-lg text-xs text-amber-800">
                                            <span className="mt-0.5 shrink-0">⚠️</span>
                                            <span>This is a CBO campaign — budget is managed at the campaign level. The daily budget entered below may be ignored by Meta.</span>
                                        </div>
                                    )}
                                    {/* Name */}
                                    <div>
                                        <label className="block text-xs font-medium text-gray-600 mb-1">Ad Set Name *</label>
                                        <input
                                            type="text"
                                            placeholder="e.g. Church Insurance — Square — May 12"
                                            value={newAdset.name}
                                            onChange={(e) => setNewAdset(p => ({ ...p, name: e.target.value }))}
                                            className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-green-500 bg-white"
                                        />
                                    </div>
                                    {/* Daily budget */}
                                    <div>
                                        <label className="block text-xs font-medium text-gray-600 mb-1">Daily Budget (USD) *</label>
                                        <div className="relative">
                                            <span className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 text-sm">$</span>
                                            <input
                                                type="number"
                                                min="1"
                                                step="1"
                                                placeholder="50"
                                                value={newAdset.dailyBudget}
                                                onChange={(e) => setNewAdset(p => ({ ...p, dailyBudget: e.target.value }))}
                                                className="w-full pl-7 pr-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-green-500 bg-white"
                                            />
                                        </div>
                                    </div>
                                    {/* Clone targeting from */}
                                    <div>
                                        <label className="block text-xs font-medium text-gray-600 mb-1">Clone targeting from *</label>
                                        <select
                                            value={newAdset.cloneFromId}
                                            onChange={(e) => setNewAdset(p => ({ ...p, cloneFromId: e.target.value }))}
                                            className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-green-500 bg-white"
                                            disabled={pushLoading || pushAdSets.length === 0}
                                        >
                                            <option value="">
                                                {pushLoading
                                                    ? 'Loading ad sets...'
                                                    : pushAdSets.length === 0
                                                        ? 'No ad sets in this campaign — pick a different campaign'
                                                        : 'Pick a source ad set...'}
                                            </option>
                                            {pushAdSets.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
                                        </select>
                                        <p className="text-xs text-gray-500 mt-1">Copies geo, age, placements, and optimization goal. Custom audiences are not copied.</p>
                                    </div>
                                    {/* PAUSED notice */}
                                    <p className="text-xs text-amber-700">New ad sets are created as Paused — activate in Ads Manager after reviewing.</p>
                                </div>
                            )}
                        </div>
                    )}

                    {/* Facebook Page */}
                    <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">Facebook Page *</label>
                        {pushPages.length > 0 ? (
                            <select
                                value={pushForm.pageId}
                                onChange={(e) => setPushForm(p => ({ ...p, pageId: e.target.value }))}
                                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-green-500"
                            >
                                <option value="">Select a page...</option>
                                {pushPages.map(pg => <option key={pg.id} value={pg.id}>{pg.name}</option>)}
                            </select>
                        ) : (
                            <input
                                type="text"
                                placeholder="e.g. 123456789"
                                value={pushForm.pageId}
                                onChange={(e) => setPushForm(p => ({ ...p, pageId: e.target.value }))}
                                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-green-500"
                            />
                        )}
                    </div>

                    {/* Website URL */}
                    <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">Destination URL *</label>
                        <input
                            type="url"
                            placeholder="https://yoursite.com/landing-page"
                            value={pushForm.websiteUrl}
                            onChange={(e) => setPushForm(p => ({ ...p, websiteUrl: e.target.value }))}
                            className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-green-500"
                        />
                    </div>

                    {/* Headline */}
                    <div>
                        <div className="flex items-center justify-between mb-1">
                            <label className="block text-sm font-medium text-gray-700">Headline</label>
                            <span className={`text-xs ${countColor(pushForm.headline.length, HEADLINE_LIMIT)}`}>
                                {pushForm.headline.length}/{HEADLINE_LIMIT}
                            </span>
                        </div>
                        <input
                            type="text"
                            value={pushForm.headline}
                            onChange={(e) => setPushForm(p => ({ ...p, headline: e.target.value }))}
                            className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-green-500"
                        />
                        {pushForm.headline.length > HEADLINE_LIMIT && (
                            <p className="text-xs text-red-600 mt-1">Meta truncates headlines after {HEADLINE_LIMIT} characters</p>
                        )}
                    </div>

                    {/* Body */}
                    <div>
                        <div className="flex items-center justify-between mb-1">
                            <label className="block text-sm font-medium text-gray-700">Body Copy</label>
                            <span className={`text-xs ${countColor(pushForm.body.length, BODY_LIMIT)}`}>
                                {pushForm.body.length}/{BODY_LIMIT}
                            </span>
                        </div>
                        <textarea
                            rows={3}
                            value={pushForm.body}
                            onChange={(e) => setPushForm(p => ({ ...p, body: e.target.value }))}
                            className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-green-500"
                        />
                        {pushForm.body.length > BODY_LIMIT && (
                            <p className="text-xs text-amber-600 mt-1">Body over {BODY_LIMIT} chars will show a "See More" link on mobile</p>
                        )}
                    </div>

                    {/* CTA */}
                    <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">Call to Action</label>
                        <select
                            value={pushForm.cta}
                            onChange={(e) => setPushForm(p => ({ ...p, cta: e.target.value }))}
                            className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-green-500"
                        >
                            {['LEARN_MORE', 'SHOP_NOW', 'SIGN_UP', 'CONTACT_US', 'DOWNLOAD', 'BOOK_NOW', 'GET_QUOTE'].map(c =>
                                <option key={c} value={c}>{c.replace(/_/g, ' ')}</option>
                            )}
                        </select>
                    </div>
                </div>

                <div className="flex gap-3 mt-6">
                    <button
                        onClick={onClose}
                        className="flex-1 px-4 py-3 bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200 font-medium"
                    >
                        Cancel
                    </button>
                    <button
                        onClick={handlePushToFacebook}
                        disabled={pushSubmitting}
                        className="flex-1 px-4 py-3 bg-green-600 text-white rounded-lg hover:bg-green-700 font-medium flex items-center justify-center gap-2 disabled:bg-gray-300 disabled:cursor-not-allowed"
                    >
                        {pushSubmitting
                            ? <><Loader className="animate-spin" size={18} /> {adsetMode === 'new' ? 'Creating & Pushing...' : 'Pushing...'}</>
                            : <><Rocket size={18} /> {adsetMode === 'new' ? 'Create Ad Set & Push' : 'Push Live'}</>
                        }
                    </button>
                </div>
            </div>
        </div>
    );
}
