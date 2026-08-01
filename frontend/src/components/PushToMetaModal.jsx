import React, { useState, useEffect } from 'react';
import { Rocket, Loader, X, CheckCircle2, ExternalLink, PlusCircle, ListFilter } from 'lucide-react';
import { getAdAccounts, getCampaigns, getAdSets, getPages, createCompleteAd, createFacebookAdSet, authFetch } from '../lib/facebookApi';
import { useToast } from '../context/ToastContext';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1';

// Meta copy limits (characters before truncation)
const HEADLINE_LIMIT = 40;
const BODY_LIMIT = 125;

// Meta Page/Business asset IDs are always purely numeric. A pasted public
// page-URL slug or username will fail this check, catching the recurring
// "wrong kind of Page ID" mistake before it reaches Meta's API.
function isValidManualPageId(value) {
    return /^\d{5,}$/.test((value || '').trim());
}

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
    generatedAdId = null,
    onClose,
    onSuccess,
}) {
    const { showError, showWarning } = useToast();

    const [pushCampaigns, setPushCampaigns] = useState([]);
    const [pushAdSets, setPushAdSets] = useState([]);
    // Separate from pushAdSets: "Use existing" must only ever list ad sets that belong
    // to the selected campaign. Clone-source can fall back account-wide since it's just
    // a targeting template, not the ad set the ad actually lands in.
    const [cloneSourceAdSets, setCloneSourceAdSets] = useState([]);
    const [adSetsCrossCampaign, setAdSetsCrossCampaign] = useState(false);
    const [pushPages, setPushPages] = useState([]);
    const [pushLoading, setPushLoading] = useState(false);
    const [accounts, setAccounts] = useState([]);
    const [accountsLoading, setAccountsLoading] = useState(false);
    const [accountFetchFailed, setAccountFetchFailed] = useState(false);
    const [pushSubmitting, setPushSubmitting] = useState(false);
    const [successResult, setSuccessResult] = useState(null);
    // Persistent inline error ({message, hint, link}) — survives until the next attempt
    const [pushError, setPushError] = useState(null);
    // Persistent (not toast) HEC-stripped-targeting warning — a toast alone is easy to
    // miss mid-bulk-push, and this silently changes the ad set Joel will later activate.
    const [hecWarning, setHecWarning] = useState(null);

    // Always default to 'new' — Joel always creates a fresh ad set when pushing
    const [adsetMode, setAdsetMode] = useState('new');
    const _today = new Date().toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    const [newAdset, setNewAdset] = useState({
        name: niche ? `${_today} - ${niche} - Testing` : `${_today} - Testing`,
        dailyBudget: '',
        cloneFromId: '',   // ad set ID to copy targeting/optimization from
    });

    const [selectedCampaign, setSelectedCampaign] = useState(null);
    // Account/campaign/page/URL are usually pre-filled from history — collapse them into
    // a summary by default so Joel isn't re-deciding things that already have a good answer.
    // Starts expanded; a completeness effect below collapses it once everything auto-fills.
    const [adminFieldsExpanded, setAdminFieldsExpanded] = useState(true);
    const [adminAutoCollapsed, setAdminAutoCollapsed] = useState(false);

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

    const hydrateAccount = (adAccountId) => {
        if (!adAccountId) return;
        // pageId must reset too — it's scoped to the ad account, and a stale value from
        // a previous account would otherwise silently pass the "all filled" collapse check.
        setPushForm(p => ({ ...p, adAccountId, campaignId: '', adsetId: '', pageId: '' }));
        setPushCampaigns([]);
        setPushAdSets([]);
        setPushPages([]);
        loadPushCampaigns(adAccountId);
        loadPushPages(adAccountId);
    };

    // Auto-load campaigns + pages if ad account ID is already populated.
    // Cold-start users won't have localStorage yet, so fetch accounts and auto-fill
    // the single connected account instead of asking them to know the act_ ID.
    useEffect(() => {
        if (pushForm.adAccountId) {
            loadPushCampaigns(pushForm.adAccountId);
            loadPushPages(pushForm.adAccountId);
            return;
        }

        const loadAccounts = async () => {
            setAccountsLoading(true);
            setAccountFetchFailed(false);
            try {
                const fetched = await getAdAccounts();
                setAccounts(Array.isArray(fetched) ? fetched : []);
                if (Array.isArray(fetched) && fetched.length === 1) {
                    const onlyAccount = fetched[0]?.id || fetched[0]?.accountId || '';
                    hydrateAccount(onlyAccount);
                }
            } catch {
                setAccountFetchFailed(true);
            } finally {
                setAccountsLoading(false);
            }
        };

        loadAccounts();
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

    // Once account, campaign, page, and destination URL have all auto-filled, collapse
    // them into a summary — one time only, so it never fights a user who expanded manually.
    useEffect(() => {
        if (adminAutoCollapsed) return;
        const allFilled = pushForm.adAccountId && pushForm.campaignId && pushForm.pageId && pushForm.websiteUrl;
        if (allFilled) {
            setAdminFieldsExpanded(false);
            setAdminAutoCollapsed(true);
        }
    }, [pushForm.adAccountId, pushForm.campaignId, pushForm.pageId, pushForm.websiteUrl, adminAutoCollapsed]);

    const loadPushCampaigns = async (adAccountId) => {
        if (!adAccountId) return;
        setPushLoading(true);
        try {
            const campaigns = await getCampaigns(adAccountId);
            setPushCampaigns(Array.isArray(campaigns) ? campaigns : []);
        } catch {
            showError('Failed to load campaigns');
        } finally {
            setPushLoading(false);
        }
    };

    const isCBOCampaign = selectedCampaign?.isCBO === true;

    const loadPushAdSets = async (campaignId) => {
        if (!campaignId) return;
        setPushLoading(true);
        setAdSetsCrossCampaign(false);
        try {
            const rawAdsets = await getAdSets(campaignId);
            const adsets = Array.isArray(rawAdsets) ? rawAdsets : [];
            setPushAdSets(adsets);

            let cloneSource = adsets;
            // Brand-new campaigns have no ad sets yet, which used to be a dead end for
            // "Create new" (nothing to clone targeting from). Fall back to the rest of
            // the ad account so Joel can still clone from a proven ad set elsewhere —
            // "Use existing" (pushAdSets) stays campaign-scoped, this is clone-only.
            if (cloneSource.length === 0 && pushForm.adAccountId) {
                const accountWide = await getAdSets(null, pushForm.adAccountId);
                cloneSource = Array.isArray(accountWide) ? accountWide : [];
                if (cloneSource.length > 0) setAdSetsCrossCampaign(true);
            }
            setCloneSourceAdSets(cloneSource);
        } catch {
            showError('Failed to load ad sets');
        } finally {
            setPushLoading(false);
        }
    };

    const loadPushPages = async (adAccountId) => {
        if (!adAccountId) return;
        try {
            const pages = await getPages(adAccountId);
            setPushPages(Array.isArray(pages) ? pages : []);
        } catch { /* non-blocking */ }
    };

    const handlePushToFacebook = async () => {
        // Validate shared fields
        if (!pushForm.campaignId || !pushForm.pageId || !pushForm.websiteUrl) {
            showError('Please fill in all required fields');
            return;
        }
        if (pushPages.length === 0 && !isValidManualPageId(pushForm.pageId)) {
            showError('The Page ID must be all digits (the Business Manager asset ID) — not the page\'s public username or URL.');
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
                if (cloneSourceAdSets.length === 0) {
                    showError('This ad account has no ad sets anywhere to clone targeting from. Create one in Ads Manager first, then retry.');
                } else {
                    showError('Select an ad set to clone targeting from');
                }
                return;
            }
        }

        setPushSubmitting(true);
        setPushError(null);
        setHecWarning(null);
        let createdAdsetId = null;
        let createdAdsetName = null;
        let hecStrippedFields = null;
        try {
            let targetAdsetId = pushForm.adsetId;
            let targetAdsetName = pushAdSets.find(a => a.id === pushForm.adsetId)?.name || pushForm.adsetId;

            if (adsetMode === 'new') {
                // Clone targeting + settings from the chosen source ad set
                const source = cloneSourceAdSets.find(a => a.id === newAdset.cloneFromId);
                const adsetPayload = {
                    name: newAdset.name.trim(),
                    dailyBudget: Number(newAdset.dailyBudget), // backend handles cents conversion
                    targeting: source?.targeting || {},
                    optimizationGoal: source?.optimization_goal || 'LEAD_GENERATION',
                    billingEvent: source?.billing_event || 'IMPRESSIONS',
                    bidAmount: source?.bid_amount || null,
                    status: 'PAUSED',
                    // Without this, the backend's HEC check is always false — targeting
                    // that should be stripped for Housing/Employment/Credit campaigns
                    // would go to Meta unstripped and hard-error instead.
                    specialAdCategories: selectedCampaign?.specialAdCategories || [],
                };
                const created = await createFacebookAdSet(
                    adsetPayload,
                    pushForm.campaignId,
                    pushForm.adAccountId,
                    'ABO',
                    { returnMeta: true }
                );
                targetAdsetId = created.id;
                if (created.hecStripped?.length) {
                    showWarning('This campaign is flagged Housing/Employment/Credit, so Meta stripped some targeting — see details below.', 10000);
                    hecStrippedFields = created.hecStripped;
                    setHecWarning(hecStrippedFields);
                }
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

            // Write back Meta IDs to the local GeneratedAd so this creative can be attributed.
            // fb_ad_id is the primary RedTrack sub1 join key — if Meta returned an ad ID we must
            // not leave the record unlinked. Surface (don't swallow) a failed write-back — a toast
            // alone auto-dismisses and this is a revenue-attribution gap, so it also gets a
            // persistent flag on the success screen below.
            let linkWriteBackFailed = false;
            if (result?.adId && generatedAdId) {
                try {
                    const linkRes = await authFetch(`${API_URL}/generated-ads/${generatedAdId}/fb-ad-id`, {
                        method: 'PATCH',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            fb_ad_id: result.adId,
                            fb_adset_id: targetAdsetId,
                            fb_campaign_id: pushForm.campaignId,
                            fb_creative_id: result.creativeId || null,
                        }),
                    });
                    if (!linkRes.ok) throw new Error(`link write-back HTTP ${linkRes.status}`);
                } catch {
                    linkWriteBackFailed = true;
                    showError('Ad pushed, but the tracking link failed to save. Revenue attribution for this creative may be missing.');
                }
            }

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
                linkWriteBackFailed,
                hecStrippedFields,
            });
            if (onSuccess) onSuccess();
        } catch (e) {
            // Persistent inline error — toasts auto-dismiss and a failed push with no
            // visible trace looks like a silent no-op. This banner stays until retry.
            if (createdAdsetId) {
                const adsManagerUrl = pushForm.adAccountId && pushForm.campaignId
                    ? `https://adsmanager.facebook.com/adsmanager/manage/adsets?act=${pushForm.adAccountId.replace('act_', '')}&selected_campaign_ids=${pushForm.campaignId}`
                    : 'https://adsmanager.facebook.com';
                setPushError({
                    message: `Ad set "${createdAdsetName}" was created, but the ad failed to push: ${e.message}`,
                    hint: 'Open Ads Manager to delete the empty ad set, then try again.',
                    link: adsManagerUrl,
                });
            } else {
                setPushError({
                    message: e.message || 'Failed to push ad.',
                    hint: /page/i.test(e.message || '')
                        ? 'Tip: the Page ID must be the page\'s asset ID from Business Manager — the public profile ID from the page URL will be rejected by Meta.'
                        : null,
                    link: null,
                });
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
                    {successResult.linkWriteBackFailed && (
                        <div className="flex items-start gap-2 p-3 mb-4 bg-red-50 border border-red-200 rounded-lg text-left text-xs text-red-800">
                            <span className="mt-0.5 shrink-0">⚠️</span>
                            <span>The tracking link failed to save locally. This ad's spend/revenue will not attribute back to this creative in RedTrack/Everflow reporting until it's manually linked. Flag this to Steven if it keeps happening.</span>
                        </div>
                    )}
                    {successResult.hecStrippedFields?.length > 0 && (
                        <div className="flex items-start gap-2 p-3 mb-4 bg-amber-50 border border-amber-200 rounded-lg text-left text-xs text-amber-800">
                            <span className="mt-0.5 shrink-0">⚠️</span>
                            <span>This campaign is flagged Housing/Employment/Credit, so Meta removed: <strong>{successResult.hecStrippedFields.join('; ')}</strong>. Double-check targeting in Ads Manager before activating.</span>
                        </div>
                    )}
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
                    <div>
                        <h3 className="text-xl font-bold text-gray-900">Push Ad to Facebook Campaign</h3>
                        <p className="text-xs text-gray-500 mt-0.5">Creates one standalone ad, PAUSED — activate it in Ads Manager after review.</p>
                    </div>
                    <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
                        <X size={20} />
                    </button>
                </div>

                <div className="space-y-4">
                    {/* Account / Campaign / Page / URL — collapsed into a summary once all four
                        have auto-filled from history, so Joel isn't re-deciding settled things. */}
                    {!adminFieldsExpanded ? (
                        <div className="flex items-start justify-between gap-3 rounded-lg border border-gray-200 bg-gray-50 px-4 py-3">
                            <div className="text-sm text-gray-700 space-y-0.5 min-w-0">
                                <div className="truncate"><span className="text-gray-400">Account:</span> {accounts.find(a => (a.id || a.accountId) === pushForm.adAccountId)?.name || pushForm.adAccountId}</div>
                                <div className="truncate"><span className="text-gray-400">Campaign:</span> {pushCampaigns.find(c => c.id === pushForm.campaignId)?.name || pushForm.campaignId}</div>
                                <div className="truncate"><span className="text-gray-400">Page:</span> {pushPages.find(pg => pg.id === pushForm.pageId)?.name || pushForm.pageId}</div>
                                <div className="truncate"><span className="text-gray-400">URL:</span> {pushForm.websiteUrl}</div>
                            </div>
                            <button
                                type="button"
                                onClick={() => setAdminFieldsExpanded(true)}
                                className="shrink-0 text-xs font-medium text-green-700 hover:text-green-800 underline"
                            >
                                Change
                            </button>
                        </div>
                    ) : (
                        <>
                    {/* Ad Account ID */}
                    <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">Ad Account ID *</label>
                        {accountsLoading && !pushForm.adAccountId ? (
                            <div className="h-10 rounded-lg bg-gray-100 border border-gray-200 animate-pulse flex items-center px-3 text-sm text-gray-400">
                                Loading ad account...
                            </div>
                        ) : accounts.length > 1 ? (
                            <select
                                value={pushForm.adAccountId}
                                onChange={(e) => hydrateAccount(e.target.value)}
                                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-green-500"
                            >
                                <option value="">Select ad account...</option>
                                {accounts.map(account => {
                                    const acctValue = account.id || account.accountId || '';
                                    return (
                                        <option key={acctValue} value={acctValue}>
                                            {account.name ? `${account.name} (${acctValue})` : acctValue}
                                        </option>
                                    );
                                })}
                            </select>
                        ) : (
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
                        )}
                        {accountFetchFailed && !pushForm.adAccountId && (
                            <p className="text-xs text-amber-600 mt-1">Could not auto-load accounts. Enter the ad account ID manually.</p>
                        )}
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
                                {pushLoading && pushForm.adAccountId ? 'Loading campaigns...' : pushCampaigns.length === 0 ? 'Ad account required first' : 'Select a campaign...'}
                            </option>
                            {pushCampaigns.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
                        </select>
                    </div>

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
                            <>
                                <input
                                    type="text"
                                    placeholder="e.g. 123456789"
                                    value={pushForm.pageId}
                                    onChange={(e) => setPushForm(p => ({ ...p, pageId: e.target.value }))}
                                    className={`w-full px-3 py-2 border rounded-lg text-sm focus:ring-2 focus:ring-green-500 ${
                                        pushForm.pageId && !isValidManualPageId(pushForm.pageId) ? 'border-red-400' : 'border-gray-300'
                                    }`}
                                />
                                <p className={`mt-1 text-xs ${pushForm.pageId && !isValidManualPageId(pushForm.pageId) ? 'text-red-600' : 'text-gray-500'}`}>
                                    {pushForm.pageId && !isValidManualPageId(pushForm.pageId)
                                        ? "That doesn't look like a Page ID — it must be all digits (the page's Business Manager asset ID), not the page's public username or URL."
                                        : "Use the Business Manager asset ID, not the ID from the page's public URL — those are different numbers."}
                                </p>
                            </>
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
                        </>
                    )}

                    {/* Ad Set — mode toggle + fields. Always visible (never collapsed) —
                        Joel makes a fresh ad set decision on every push. */}
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
                                                ? 'No ad sets in this campaign yet — create one in Ads Manager first'
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
                                            disabled={pushLoading || cloneSourceAdSets.length === 0}
                                        >
                                            <option value="">
                                                {pushLoading
                                                    ? 'Loading ad sets...'
                                                    : cloneSourceAdSets.length === 0
                                                        ? 'No ad sets anywhere in this ad account — create one in Ads Manager first'
                                                        : 'Pick a source ad set...'}
                                            </option>
                                            {cloneSourceAdSets.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
                                        </select>
                                        <p className="text-xs text-gray-500 mt-1">
                                            {adSetsCrossCampaign
                                                ? "This campaign has no ad sets yet, so these are pulled from elsewhere in the ad account — double-check geo/age AND placements (Feed vs. Stories/Reels) still fit before pushing."
                                                : 'Copies geo, age, placements, and optimization goal. Custom audiences are not copied.'}
                                        </p>
                                    </div>
                                    {/* PAUSED notice */}
                                    <p className="text-xs text-amber-700">New ad sets are created as Paused — activate in Ads Manager after reviewing.</p>
                                </div>
                            )}
                        </div>
                    )}

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

                {pushError && (
                    <div className="mt-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm">
                        <p className="font-semibold text-red-800">Push failed</p>
                        <p className="mt-1 text-red-700">{pushError.message}</p>
                        {pushError.hint && <p className="mt-1 text-red-600 text-xs">{pushError.hint}</p>}
                        {pushError.link && (
                            <a href={pushError.link} target="_blank" rel="noreferrer" className="mt-1 inline-block text-xs font-medium text-red-700 underline">
                                Open Ads Manager
                            </a>
                        )}
                    </div>
                )}

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
                            : <><Rocket size={18} /> {adsetMode === 'new' ? 'Create Ad Set & Push (Paused)' : 'Push to Meta (Paused)'}</>
                        }
                    </button>
                </div>
            </div>
        </div>
    );
}
