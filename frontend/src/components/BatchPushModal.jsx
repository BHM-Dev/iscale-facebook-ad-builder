import React, { useState, useEffect, useRef } from 'react';
import {
    Rocket, Loader, X, CheckCircle2, AlertCircle, ExternalLink,
    PlusCircle, ListFilter, ChevronDown, ChevronUp
} from 'lucide-react';
import { getCampaigns, getAdSets, getPages, createCompleteAd, createFacebookAdSet, authFetch } from '../lib/facebookApi';
import { useToast } from '../context/ToastContext';
import { safeLocalStorageGet, safeLocalStorageSet } from '../lib/safeLocalStorage';
import CreativeEnhancementsPanel from './CreativeEnhancementsPanel';

const FB_API_BASE = (import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1') + '/facebook';
const GEN_ADS_API_BASE = (import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1') + '/generated-ads';

// Shared CTA options — enum value + human label used in both the shared and per-item dropdowns
const CTA_OPTIONS = [
    ['LEARN_MORE',  'Learn More'],
    ['GET_QUOTE',   'Get Quote'],
    ['SIGN_UP',     'Sign Up'],
    ['CONTACT_US',  'Contact Us'],
    ['SHOP_NOW',    'Shop Now'],
    ['DOWNLOAD',    'Download'],
    ['BOOK_NOW',    'Book Now'],
    ['BUY_TICKETS', 'Buy Tickets'],
    ['DONATE_NOW',  'Donate Now'],
    ['GET_STARTED', 'Get Started'],
    ['APPLY_NOW',   'Apply Now'],
];

const CTA_LABEL_TO_ENUM = Object.fromEntries(CTA_OPTIONS.map(([value, label]) => [label.toLowerCase(), value]));
const KNOWN_CTA_VALUES = new Set(CTA_OPTIONS.map(([value]) => value));
const pageStorageKey = (adAccountId) => adAccountId ? `lastUsedPageId_${adAccountId}` : null;
const PENDING_LINKS_KEY = 'pendingGeneratedAdMetaLinks';
const readPendingLinks = () => {
    try {
        const parsed = JSON.parse(safeLocalStorageGet(PENDING_LINKS_KEY) || '[]');
        return Array.isArray(parsed) ? parsed : [];
    } catch {
        return [];
    }
};
const savePendingLinks = (links) => safeLocalStorageSet(PENDING_LINKS_KEY, JSON.stringify(links));
const rememberPendingLink = (link) => {
    const others = readPendingLinks().filter(existing => existing.generatedAdId !== link.generatedAdId);
    savePendingLinks([...others, link]);
};
const clearPendingLink = (generatedAdId) => {
    savePendingLinks(readPendingLinks().filter(link => link.generatedAdId !== generatedAdId));
};
const normalizeCta = (value) => {
    const key = (value || '').toLowerCase();
    return ({
        'get my quote': 'GET_QUOTE',
        'see my rate': 'GET_QUOTE',
        'compare rates': 'GET_QUOTE',
        'get started': 'GET_STARTED',
    })[key] || CTA_LABEL_TO_ENUM[key] || value || 'LEARN_MORE';
};

/**
 * BatchPushModal — push multiple generated images to Meta in one operation.
 *
 * Props:
 *   items                  {Array}   Each item: { key, imageUrl, headline, body, description, cta, variantName, sizeLabel }
 *   onClose                {function}
 *   preselectedCampaignId  {string}  Meta campaign ID — auto-selects campaign, skips dropdown
 *   preselectedAdsetId     {string}  Meta adset ID — pre-fills "clone from" and defaults to "Create new"
 *   preselectedAdsetName   {string}  Source adset name — used to suggest a new adset name
 */
export default function BatchPushModal({ items, onClose, preselectedCampaignId = '', preselectedAdsetId = '', preselectedAdsetName = '', preselectedWebsiteUrl = '', niche = '' }) {
    const { showError } = useToast();

    // Shared form fields
    const [adAccountId, setAdAccountId] = useState(safeLocalStorageGet('fb_ad_account_id') || '');
    const [campaigns, setCampaigns] = useState([]);
    const [selectedCampaignId, setSelectedCampaignId] = useState('');
    const [selectedCampaign, setSelectedCampaign] = useState(null);
    const [adSets, setAdSets] = useState([]);
    const [pages, setPages] = useState([]);
    const [pageId, setPageId] = useState(() => {
        const key = pageStorageKey(adAccountId);
        return key ? safeLocalStorageGet(key) || '' : '';
    });
    const [websiteUrl, setWebsiteUrl] = useState(preselectedWebsiteUrl || safeLocalStorageGet('lastUsedWebsiteUrl') || '');
    const [fieldErrors, setFieldErrors] = useState({});
    const [sharedCta, setSharedCta] = useState(() => {
        // Default to the most common CTA across items so the dropdown reflects what Joel already chose
        if (!items.length) return 'LEARN_MORE';
        if (items.some(it => !KNOWN_CTA_VALUES.has(it.cta))) return '';
        const counts = {};
        items.forEach(it => { const c = it.cta; counts[c] = (counts[c] || 0) + 1; });
        return Object.entries(counts).sort((a, b) => b[1] - a[1])[0][0];
    });
    const [loading, setLoading] = useState(false);
    const [creativeEnhancements, setCreativeEnhancements] = useState({});

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
        Object.fromEntries(items.map(it => [it.key, {
            headline: it.headline,
            body: it.body,
            description: it.description || '',
            cta: it.cta || ''
        }]))
    );
    const [expandedItem, setExpandedItem] = useState(null);

    // Push state
    const [pushing, setPushing] = useState(false);
    const [pushStatuses, setPushStatuses] = useState({}); // key → 'pending'|'pushing'|'done'|'error'
    const [pushErrors, setPushErrors] = useState({});     // key → error string
    const [isDone, setIsDone] = useState(false);
    // Keep successful Meta results in memory so a failed local attribution
    // write-back can be retried without creating a second ad.
    const [pushedResults, setPushedResults] = useState({}); // key → createCompleteAd result
    const [pushedAdsetId, setPushedAdsetId] = useState(null);
    const [localAdsetId, setLocalAdsetId] = useState(null);
    // Meta and our local mirror are two commits. Keep a failed mirror durable
    // in this modal's retry state and never create another Meta ad set while
    // that first one is awaiting its local record.
    const [pendingAdsetMirror, setPendingAdsetMirror] = useState(null);

    const isCBO = selectedCampaign?.isCBO === true;
    const doneItems = items.filter(it => pushStatuses[it.key] === 'done');
    const errorItems = items.filter(it => ['error', 'reconcile'].includes(pushStatuses[it.key]));
    // A timeout after Meta starts mutating is not safely retryable.  Retrying
    // could create a duplicate paused ad, so force an Ads Manager reconciliation.
    const retryableItems = items.filter(it => !['done', 'reconcile'].includes(pushStatuses[it.key]));

    // Ad Account is a free-text input whose onChange fires on every keystroke —
    // a useEffect keyed on the raw `adAccountId` state (the prior version of
    // this fix) resets on every keystroke too, silently wiping the selection
    // one character at a time while Joel is still typing or correcting a
    // digit. A prior fix attempt just moved this panel below the Ad Account
    // field in the JSX, which has no effect on when a useEffect re-runs —
    // confirmed still broken by re-review (code-auditor, BLOCKING). Reset
    // only on blur, and only if the value actually changed since the last
    // commit, mirroring the existing onBlur-driven loadCampaigns/loadPages
    // pattern on this same field rather than reacting to every keystroke.
    const committedAdAccountRef = useRef(adAccountId);
    const pagesAccountRef = useRef(adAccountId);
    const campaignsRequestRef = useRef(0);
    const pagesRequestRef = useRef(0);
    const resetEnhancementsIfAccountChanged = () => {
        if (committedAdAccountRef.current !== adAccountId) {
            committedAdAccountRef.current = adAccountId;
            setCreativeEnhancements({});
            // Do not let the old account's page list or selected ID appear valid
            // while the new account is loading.
            pagesAccountRef.current = '';
            campaignsRequestRef.current += 1;
            pagesRequestRef.current += 1;
            setPages([]);
            setPageId('');
            return true;
        }
        return false;
    };
    // selectedCampaignId is set via a discrete dropdown/list selection, not
    // free-typed — a plain effect here is safe, no keystroke-wipe risk.
    useEffect(() => {
        setCreativeEnhancements({});
    }, [selectedCampaignId]);

    // Auto-load on mount — fetch ad account ID from backend config so Joel never has to type it
    useEffect(() => {
        setFieldErrors({});
        const bootstrap = async () => {
            let acctId = adAccountId;
            if (!acctId) {
                try {
                    const cfgRes = await authFetch(`${FB_API_BASE}/config`);
                    const cfg = cfgRes?.ok ? await cfgRes.json() : null;
                    if (cfg?.ad_account_id) {
                        acctId = cfg.ad_account_id;
                        setAdAccountId(acctId);
                        // Keep the "committed" ref in sync with THIS auto-fill —
                        // it's the only place adAccountId is set outside the
                        // field's own onBlur, and missing this left the ref
                        // stuck at whatever it was at mount (often '' on a
                        // fresh browser/cleared localStorage). The next blur
                        // for ANY reason — even just tabbing through the form
                        // with no edit — would then see a false "changed"
                        // value and wipe creativeEnhancements with nothing
                        // actually having changed (re-verification review,
                        // HIGH — same silent-wipe class this fix round exists
                        // to close, just relocated to the auto-fill path).
                        committedAdAccountRef.current = acctId;
                        safeLocalStorageSet('fb_ad_account_id', acctId);
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
        const requestId = ++campaignsRequestRef.current;
        setLoading(true);
        try {
            const data = await getCampaigns(acctId);
            const list = Array.isArray(data) ? data : [];
            if (requestId !== campaignsRequestRef.current) return [];
            setCampaigns(list);
            return list;
        } catch {
            if (requestId !== campaignsRequestRef.current) return [];
            showError('Failed to load campaigns');
            return [];
        } finally {
            if (requestId === campaignsRequestRef.current) setLoading(false);
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
                // Only pre-fill budget if source ad set has a real non-zero value.
                // CBO campaigns store budget at campaign level — ad sets return daily_budget=0 or null,
                // which would pre-fill "$0" and silently block the push with a validation error.
                const budgetCents = Number(sourceAdset.daily_budget) || 0;
                const budgetDollars = budgetCents > 0 ? Math.round(budgetCents / 100) : '';
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

    const loadPages = async (acctId, force = false) => {
        if (!acctId || (!force && pages.length > 0 && pagesAccountRef.current === acctId)) return;
        const requestId = ++pagesRequestRef.current;
        try {
            const data = await getPages(acctId);
            const list = Array.isArray(data) ? data : [];
            if (requestId !== pagesRequestRef.current) return;
            const wasSameAccount = pagesAccountRef.current === acctId;
            const savedPageId = safeLocalStorageGet(pageStorageKey(acctId));
            setPages(list);
            setPageId(previousPageId => {
                const candidate = wasSameAccount ? previousPageId : savedPageId;
                return list.some(page => page.id === candidate) ? candidate : '';
            });
            pagesAccountRef.current = acctId;
        } catch {
            if (requestId !== pagesRequestRef.current) return;
            setPages([]);
            setPageId('');
            pagesAccountRef.current = acctId;
        }
    };

    const validate = () => {
        const errors = {};
        if (!adAccountId.trim()) errors.adAccountId = 'Ad Account ID is required';
        if (!selectedCampaignId) errors.campaign = 'Select a campaign';
        if (!pageId) errors.page = 'Select a Facebook page';
        if (!websiteUrl.trim()) errors.websiteUrl = 'Destination URL is required';
        if (Object.values(itemCopy).some(copy => !KNOWN_CTA_VALUES.has(copy.cta))) {
            errors.cta = 'Choose a supported CTA for every ad before pushing';
        }
        if (adsetMode === 'existing' && !sharedAdsetId) errors.adset = 'Select an ad set';
        if (adsetMode === 'new') {
            if (!newAdset.name.trim()) errors.adsetName = 'Ad set name is required';
            if (!isCBO && (!newAdset.dailyBudget || isNaN(newAdset.dailyBudget) || Number(newAdset.dailyBudget) < 1)) {
                errors.dailyBudget = 'Daily budget must be at least $1';
            }
            if (!newAdset.cloneFromId && adSets.length > 0) {
                errors.cloneFrom = 'Select an ad set to clone targeting from';
            }
        }
        setFieldErrors(errors);
        return Object.keys(errors).length === 0;
    };

    const handlePushAll = async () => {
        if (!validate()) return;
        setPushErrors(prev => Object.fromEntries(Object.entries(prev).filter(([key]) =>
            retryableItems.some(item => item.key === key)
        )));
        setPushing(true);
        setIsDone(false);

        // A Meta ad can be created even if its local GeneratedAd write-back
        // times out. Persisted links survive a modal close/reload; resolve
        // them first so a reopened modal never creates a duplicate ad.
        let itemsToPush = [...retryableItems];
        for (const item of retryableItems) {
            const pendingLink = readPendingLinks().find(link => link.generatedAdId === item.generatedAdId);
            if (!pendingLink) continue;
            try {
                const linkRes = await authFetch(`${GEN_ADS_API_BASE}/${item.generatedAdId}/fb-ad-id`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(pendingLink.payload),
                });
                if (!linkRes.ok) throw new Error(`link write-back HTTP ${linkRes.status}`);
                clearPendingLink(item.generatedAdId);
                setPushStatuses(prev => ({ ...prev, [item.key]: 'done' }));
                itemsToPush = itemsToPush.filter(candidate => candidate.key !== item.key);
            } catch (error) {
                setPushStatuses(prev => ({ ...prev, [item.key]: 'error' }));
                setPushErrors(prev => ({ ...prev, [item.key]: `Ad already exists; retry its tracking link: ${error.message}` }));
                itemsToPush = itemsToPush.filter(candidate => candidate.key !== item.key);
            }
        }

        // Keep completed items intact on retry so a transient failure never
        // creates duplicate Meta ads. Only retry items that are not done.
        setPushStatuses(prev => ({
            ...prev,
            ...Object.fromEntries(itemsToPush.map(it => [it.key, 'pending'])),
        }));
        if (itemsToPush.length === 0) {
            setPushing(false);
            setIsDone(true);
            return;
        }

        // Create new ad set once if needed, then reuse the ID for all items
        let targetAdsetId = pushedAdsetId || sharedAdsetId;
        let targetAdsetName = adSets.find(a => a.id === sharedAdsetId)?.name || sharedAdsetId;

        if (adsetMode === 'new' && !pushedAdsetId) {
            const source = adSets.find(a => a.id === newAdset.cloneFromId);
            // Pass special_ad_categories from the parent campaign so the backend
            // can enforce HEC targeting restrictions (age/gender/geo).
            // Without this, Meta returns error 2909035 on insurance campaigns.
            const campaignSpecialCats = selectedCampaign?.specialAdCategories || [];
            const payload = {
                name: newAdset.name.trim(),
                ...(isCBO ? {} : { dailyBudget: Number(newAdset.dailyBudget) }),
                targeting: source?.targeting || {},
                optimizationGoal: source?.optimization_goal || 'LEAD_GENERATION',
                billingEvent: source?.billing_event || 'IMPRESSIONS',
                ...(isCBO ? {} : { bidAmount: source?.bid_amount || null }),
                status: 'PAUSED',
                specialAdCategories: campaignSpecialCats,
            };
            try {
                const pendingMirror = pendingAdsetMirror || (() => {
                    const fbAdsetId = targetAdsetId || null;
                    return {
                        fbAdsetId,
                        mirrorId: localAdsetId || (fbAdsetId ? `batch_adset_${fbAdsetId}` : null),
                        payload,
                    };
                })();
                if (!pendingMirror.fbAdsetId) {
                    pendingMirror.fbAdsetId = await createFacebookAdSet(payload, selectedCampaignId, adAccountId, isCBO ? 'CBO' : 'ABO');
                    pendingMirror.mirrorId = `batch_adset_${pendingMirror.fbAdsetId}`;
                    setPendingAdsetMirror(pendingMirror);
                }
                targetAdsetId = pendingMirror.fbAdsetId;
                setLocalAdsetId(pendingMirror.mirrorId);
                const saveAdsetRes = await authFetch(`${FB_API_BASE}/adsets/save`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        id: pendingMirror.mirrorId,
                        campaignId: selectedCampaignId,
                        name: pendingMirror.payload.name,
                        fbAdsetId: targetAdsetId,
                        optimizationGoal: pendingMirror.payload.optimizationGoal,
                        dailyBudget: pendingMirror.payload.dailyBudget,
                        bidAmount: pendingMirror.payload.bidAmount,
                        targeting: pendingMirror.payload.targeting,
                        status: pendingMirror.payload.status,
                    }),
                });
                if (!saveAdsetRes.ok) {
                    const err = await saveAdsetRes.json().catch(() => ({}));
                    throw new Error(`Meta created ad set ${targetAdsetId}, but its local mirror failed: ${err.detail || saveAdsetRes.status}. Retry to save the mirror; do not create another ad set.`);
                }
                setPushedAdsetId(targetAdsetId);
                setPendingAdsetMirror(null);
                targetAdsetName = pendingMirror.payload.name;
            } catch (e) {
                showError(`Failed to create ad set: ${e.message}`);
                setPushing(false);
                return;
            }
        }

        // Push each item sequentially so Meta doesn't rate-limit
        const adsetObj = adSets.find(a => a.id === targetAdsetId) || {};
        for (const item of itemsToPush) {
            setPushStatuses(prev => ({ ...prev, [item.key]: 'pushing' }));
            const copy = itemCopy[item.key];
            try {
                const pushResult = pushedResults[item.key] || await createCompleteAd(
                    selectedCampaignId,
                    { fbAdsetId: targetAdsetId, ...adsetObj },
                    {
                        mediaType: 'image',
                        imageUrl: item.imageUrl,
                        secondaryImageUrl: item.secondaryImageUrl || null,
                        headlines: [copy.headline || item.headline],
                        bodies: [copy.body || item.body],
                        description: copy.description ?? item.description ?? '',
                        cta: normalizeCta(copy.cta || sharedCta),
                        websiteUrl,
                        creative_enhancements: creativeEnhancements,
                    },
                    { id: `batch_${item.key}_${Date.now()}`, name: copy.headline || item.headline || 'Batch Ad' },
                    pageId,
                    adAccountId,
                    isCBO ? 'CBO' : 'ABO'
                );
                if (!pushedResults[item.key]) {
                    setPushedResults(prev => ({ ...prev, [item.key]: pushResult }));
                }
                // Write back Meta IDs to the local GeneratedAd record. fb_ad_id is the
                // primary RedTrack sub1 join key — a missing link means this creative can
                // never be attributed, so surface (don't swallow) a failed write-back.
                if (pushResult?.adId && item.generatedAdId) {
                    try {
                        const linkRes = await authFetch(`${GEN_ADS_API_BASE}/${item.generatedAdId}/fb-ad-id`, {
                            method: 'PATCH',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({
                                fb_ad_id: pushResult.adId,
                                fb_adset_id: targetAdsetId,
                                fb_campaign_id: selectedCampaignId,
                                fb_creative_id: pushResult.creativeId || null,
                            }),
                        });
                        if (!linkRes.ok) throw new Error(`link write-back HTTP ${linkRes.status}`);
                    } catch {
                        rememberPendingLink({
                            generatedAdId: item.generatedAdId,
                            payload: {
                                fb_ad_id: pushResult.adId,
                                fb_adset_id: targetAdsetId,
                                fb_campaign_id: selectedCampaignId,
                                fb_creative_id: pushResult.creativeId || null,
                            },
                        });
                        // The Meta ad is cached above, so retrying this item will
                        // only retry the bookkeeping link and cannot duplicate the ad.
                        throw new Error(`Ad was pushed, but its tracking link failed for "${copy.headline || item.headline || item.key}". Retry the failed item before closing.`);
                    }
                } else if (!pushResult?.adId) {
                    throw new Error('Meta did not return an ad ID after push. Do not re-push; verify the ad in Ads Manager before retrying.');
                } else if (!item.generatedAdId) {
                    throw new Error('Ad was pushed, but no local generated-ad record exists for attribution. Do not re-push; reconcile this Meta ad first.');
                }
                setPushStatuses(prev => ({ ...prev, [item.key]: 'done' }));
            } catch (e) {
                if (e.metaMutationStarted) {
                    setPushStatuses(prev => ({ ...prev, [item.key]: 'reconcile' }));
                    setPushErrors(prev => ({
                        ...prev,
                        [item.key]: `${e.message}. Meta may have created this ad. Verify it in Ads Manager before retrying.`,
                    }));
                    break;
                }
                setPushStatuses(prev => ({ ...prev, [item.key]: 'error' }));
                setPushErrors(prev => ({ ...prev, [item.key]: e.message }));
            }
        }

        // Persist for next time
        const pageKey = pageStorageKey(adAccountId);
        if (pageId && pageKey) safeLocalStorageSet(pageKey, pageId);
        if (adAccountId) safeLocalStorageSet('fb_ad_account_id', adAccountId);
        if (websiteUrl) safeLocalStorageSet('lastUsedWebsiteUrl', websiteUrl);
        if (selectedCampaignId) sessionStorage.setItem('lastUsedCampaignId', selectedCampaignId);

        setPushing(false);
        setIsDone(true);
    };

    const adsManagerUrl = adAccountId && selectedCampaignId
        ? `https://adsmanager.facebook.com/adsmanager/manage/ads?act=${adAccountId.replace('act_', '')}&selected_campaign_ids=${selectedCampaignId}`
        : 'https://adsmanager.facebook.com';
    const fieldErrorMessages = Object.values(fieldErrors).filter(Boolean);

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
                        {errorItems.some(item => pushedResults[item.key]) && (
                            <button
                                onClick={() => { setIsDone(false); handlePushAll(); }}
                                className="flex-1 px-4 py-3 bg-amber-600 text-white rounded-lg hover:bg-amber-700 font-medium"
                            >
                                Retry Failed Links
                            </button>
                        )}
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
                    {fieldErrorMessages.length > 0 && (
                        <div className="border border-red-200 bg-red-50 rounded-lg px-3 py-2.5">
                            <div className="flex items-start gap-2">
                                <AlertCircle size={15} className="text-red-600 mt-0.5 shrink-0" />
                                <div>
                                    <p className="text-sm font-medium text-red-800">Fix these fields before pushing</p>
                                    <ul className="mt-1 space-y-0.5 text-xs text-red-700 list-disc list-inside">
                                        {fieldErrorMessages.map(error => (
                                            <li key={error}>{error}</li>
                                        ))}
                                    </ul>
                                </div>
                            </div>
                        </div>
                    )}

                    {/* Ad Account */}
                    <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">Ad Account ID *</label>
                        <input
                            type="text"
                            placeholder="act_123456789"
                            value={adAccountId}
                            disabled={pushing}
                            onChange={e => {
                                setAdAccountId(e.target.value);
                                campaignsRequestRef.current += 1;
                                pagesRequestRef.current += 1;
                                setFieldErrors(p => ({ ...p, adAccountId: undefined }));
                                setCampaigns([]);
                                setAdSets([]);
                                setSelectedCampaignId('');
                            }}
                            onBlur={() => {
                                const accountChanged = resetEnhancementsIfAccountChanged();
                                loadCampaigns(adAccountId);
                                loadPages(adAccountId, accountChanged);
                            }}
                            className={`w-full px-3 py-2 border rounded-lg text-sm focus:ring-2 disabled:bg-gray-50 ${
                                fieldErrors.adAccountId ? 'border-red-400 focus:ring-red-500' : 'border-gray-300 focus:ring-green-500'
                            }`}
                        />
                        {fieldErrors.adAccountId && (
                            <p className="text-xs text-red-600 mt-1">{fieldErrors.adAccountId}</p>
                        )}
                    </div>

                    {/* Campaign — locked when iterating from a known campaign */}
                    <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">Campaign *</label>
                        {preselectedCampaignId && selectedCampaignId ? (
                            <div className="flex items-center gap-2 px-3 py-2 bg-indigo-50 border border-indigo-200 rounded-lg text-sm">
                                <span className="text-indigo-700 font-medium flex-1 truncate">
                                    {campaigns.find(c => c.id === selectedCampaignId)?.name || selectedCampaignId}
                                </span>
                                <button
                                    type="button"
                                    onClick={() => setSelectedCampaignId('')}
                                    className="text-xs text-indigo-400 hover:text-indigo-600 underline shrink-0 transition-colors"
                                    title="Pick a different campaign"
                                >
                                    Change
                                </button>
                            </div>
                        ) : (
                            <select
                                value={selectedCampaignId}
                                disabled={pushing || campaigns.length === 0}
                                onChange={e => {
                                    const c = campaigns.find(x => x.id === e.target.value) || null;
                                    setSelectedCampaign(c);
                                    setSelectedCampaignId(e.target.value);
                                    setFieldErrors(p => ({ ...p, campaign: undefined }));
                                    setAdSets([]);
                                    setSharedAdsetId('');
                                    // Keep adsetMode as 'new' — Joel should always explicitly choose to use existing
                                    setNewAdset({ name: suggestedAdsetName, dailyBudget: '', cloneFromId: '' });
                                    loadAdSets(e.target.value);
                                }}
                                className={`w-full px-3 py-2 border rounded-lg text-sm focus:ring-2 disabled:bg-gray-50 ${
                                    fieldErrors.campaign ? 'border-red-400 focus:ring-red-500' : 'border-gray-300 focus:ring-green-500'
                                }`}
                            >
                                <option value="">
                                    {loading ? 'Loading...' : campaigns.length === 0 ? 'Enter Ad Account ID first' : 'Select a campaign...'}
                                </option>
                                {campaigns.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
                            </select>
                        )}
                        {fieldErrors.campaign && (
                            <p className="text-xs text-red-600 mt-1">{fieldErrors.campaign}</p>
                        )}
                    </div>

                    {/* Enhancements reset on blur (Ad Account) or on selection
                        (Campaign) — not on every keystroke. See
                        resetEnhancementsIfAccountChanged above for why a plain
                        effect keyed on adAccountId doesn't work for a
                        free-text field with an onChange-per-keystroke. */}
                    <CreativeEnhancementsPanel value={creativeEnhancements} onChange={setCreativeEnhancements} />

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
                                <>
                                    <select
                                        value={sharedAdsetId}
                                        disabled={pushing || loading || adSets.length === 0}
                                        onChange={e => {
                                            setSharedAdsetId(e.target.value);
                                            setFieldErrors(p => ({ ...p, adset: undefined }));
                                        }}
                                        className={`w-full px-3 py-2 border rounded-lg text-sm focus:ring-2 disabled:bg-gray-50 ${
                                            fieldErrors.adset ? 'border-red-400 focus:ring-red-500' : 'border-gray-300 focus:ring-green-500'
                                        }`}
                                    >
                                        <option value="">
                                            {loading ? 'Loading...' : adSets.length === 0 ? 'No ad sets — create one first' : 'Select an ad set...'}
                                        </option>
                                        {adSets.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
                                    </select>
                                    {fieldErrors.adset && (
                                        <p className="text-xs text-red-600 mt-1">{fieldErrors.adset}</p>
                                    )}
                                </>
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
                                            <span>CBO campaign — budget is managed at campaign level. This new ad set will not send an ad-set budget or bid strategy.</span>
                                        </div>
                                    )}
                                    <div>
                                        <label className="block text-xs font-medium text-gray-600 mb-1">Ad Set Name *</label>
                                        <input
                                            type="text"
                                            placeholder="e.g. Church Insurance — Square — May 12"
                                            value={newAdset.name}
                                            disabled={pushing}
                                            onChange={e => {
                                                setNewAdset(p => ({ ...p, name: e.target.value }));
                                                setFieldErrors(p => ({ ...p, adsetName: undefined }));
                                            }}
                                            className={`w-full px-3 py-2 border rounded-lg text-sm bg-white focus:ring-2 ${
                                                fieldErrors.adsetName ? 'border-red-400 focus:ring-red-500' : 'border-gray-300 focus:ring-green-500'
                                            }`}
                                        />
                                        {fieldErrors.adsetName && (
                                            <p className="text-xs text-red-600 mt-1">{fieldErrors.adsetName}</p>
                                        )}
                                    </div>
                                    {!isCBO && <div>
                                        <label className="block text-xs font-medium text-gray-600 mb-1">Daily Budget (USD) *</label>
                                        <div className="relative">
                                            <span className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 text-sm">$</span>
                                            <input
                                                type="number" min="1" step="1" placeholder="50"
                                                value={newAdset.dailyBudget}
                                                disabled={pushing}
                                                onChange={e => {
                                                    setNewAdset(p => ({ ...p, dailyBudget: e.target.value }));
                                                    setFieldErrors(p => ({ ...p, dailyBudget: undefined }));
                                                }}
                                                className={`w-full pl-7 pr-3 py-2 border rounded-lg text-sm bg-white focus:ring-2 ${
                                                    fieldErrors.dailyBudget ? 'border-red-400 focus:ring-red-500' : 'border-gray-300 focus:ring-green-500'
                                                }`}
                                            />
                                        </div>
                                        {fieldErrors.dailyBudget && (
                                            <p className="text-xs text-red-600 mt-1">{fieldErrors.dailyBudget}</p>
                                        )}
                                    </div>}
                                    <div>
                                        <label className="block text-xs font-medium text-gray-600 mb-1">Clone targeting from *</label>
                                        <select
                                            value={newAdset.cloneFromId}
                                            disabled={pushing || loading || adSets.length === 0}
                                            onChange={e => {
                                                setNewAdset(p => ({ ...p, cloneFromId: e.target.value }));
                                                setFieldErrors(p => ({ ...p, cloneFrom: undefined }));
                                            }}
                                            className={`w-full px-3 py-2 border rounded-lg text-sm bg-white focus:ring-2 ${
                                                fieldErrors.cloneFrom ? 'border-red-400 focus:ring-red-500' : 'border-gray-300 focus:ring-green-500'
                                            }`}
                                        >
                                            <option value="">
                                                {loading ? 'Loading...' : adSets.length === 0 ? 'No ad sets in this campaign' : 'Pick a source ad set...'}
                                            </option>
                                            {adSets.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
                                        </select>
                                        {fieldErrors.cloneFrom && (
                                            <p className="text-xs text-red-600 mt-1">{fieldErrors.cloneFrom}</p>
                                        )}
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
                                    onChange={e => {
                                        setPageId(e.target.value);
                                        pagesAccountRef.current = adAccountId;
                                        setFieldErrors(p => ({ ...p, page: undefined }));
                                    }}
                                    className={`w-full px-3 py-2 border rounded-lg text-sm focus:ring-2 disabled:bg-gray-50 ${
                                        fieldErrors.page ? 'border-red-400 focus:ring-red-500' : 'border-gray-300 focus:ring-green-500'
                                    }`}
                                >
                                    <option value="">Select a page...</option>
                                    {pages.map(pg => <option key={pg.id} value={pg.id}>{pg.name}</option>)}
                                </select>
                            ) : (
                                <input
                                    type="text" placeholder="Page ID"
                                    value={pageId}
                                    disabled={pushing}
                                    onChange={e => {
                                        setPageId(e.target.value);
                                        pagesAccountRef.current = adAccountId;
                                        setFieldErrors(p => ({ ...p, page: undefined }));
                                    }}
                                    className={`w-full px-3 py-2 border rounded-lg text-sm focus:ring-2 disabled:bg-gray-50 ${
                                        fieldErrors.page ? 'border-red-400 focus:ring-red-500' : 'border-gray-300 focus:ring-green-500'
                                    }`}
                                />
                            )}
                            {fieldErrors.page && (
                                <p className="text-xs text-red-600 mt-1">{fieldErrors.page}</p>
                            )}
                        </div>
                        <div>
                            <label className="block text-sm font-medium text-gray-700 mb-1">Destination URL *</label>
                            <input
                                type="url" placeholder="https://..."
                                value={websiteUrl}
                                disabled={pushing}
                                onChange={e => {
                                    setWebsiteUrl(e.target.value);
                                    setFieldErrors(p => ({ ...p, websiteUrl: undefined }));
                                }}
                                className={`w-full px-3 py-2 border rounded-lg text-sm focus:ring-2 disabled:bg-gray-50 ${
                                    fieldErrors.websiteUrl ? 'border-red-400 focus:ring-red-500' : 'border-gray-300 focus:ring-green-500'
                                }`}
                            />
                            {fieldErrors.websiteUrl && (
                                <p className="text-xs text-red-600 mt-1">{fieldErrors.websiteUrl}</p>
                            )}
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
                            <option value="">Choose a CTA...</option>
                            {CTA_OPTIONS.map(([val, label]) => (
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
                                                    <label className="text-xs font-medium text-gray-600">Description</label>
                                                    <input
                                                        type="text"
                                                        value={copy.description || ''}
                                                        onChange={e => setItemCopy(p => ({ ...p, [item.key]: { ...p[item.key], description: e.target.value } }))}
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
                                                        {CTA_OPTIONS.map(([val, label]) => (
                                                            <option key={val} value={val}>{label}</option>
                                                        ))}
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
