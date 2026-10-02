import React, { createContext, useCallback, useEffect, useContext, useRef, useState } from 'react';
import { authFetch } from '../lib/facebookApi';
import { useToast } from './ToastContext';
import { LAUNCH_DRAFT_SESSION_KEY, LAUNCH_RECEIPT_SESSION_KEY, clearLaunchDraftSession, draftHasContent } from '../lib/launchDraft';
import { safeLocalStorageGet, safeLocalStorageSet, safeSessionStorageGet, safeSessionStorageRemove, safeSessionStorageSet } from '../lib/safeLocalStorage';

const CampaignContext = createContext();

const restoreLaunchReceipt = () => {
    const stored = safeSessionStorageGet(LAUNCH_RECEIPT_SESSION_KEY);
    if (!stored) return null;
    try {
        return JSON.parse(stored);
    } catch (error) {
        console.warn('Discarding unreadable launch receipt session data', error);
        safeSessionStorageRemove(LAUNCH_RECEIPT_SESSION_KEY);
        return null;
    }
};

// Quick Ad / Launch Pack / Drive Launch write one of these keys before navigating
// to the launcher. They build their own target, so a saved draft or wizard step
// from an earlier visit must be ignored (it would stall their step-1 shortcuts).
export const hasPendingLaunchIntent = () => {
    try {
        return Boolean(
            localStorage.getItem('pendingQuickAd')
            || localStorage.getItem('pendingLaunchPack')
            || localStorage.getItem('pendingDriveLaunch')
        );
    } catch {
        return false;
    }
};

const restoreLaunchDraft = () => {
    if (hasPendingLaunchIntent()) return null;
    const stored = safeSessionStorageGet(LAUNCH_DRAFT_SESSION_KEY);
    if (!stored) return null;
    try {
        const draft = JSON.parse(stored);
        return draft && typeof draft === 'object' ? draft : null;
    } catch (error) {
        console.warn('Discarding unreadable launch draft session data', error);
        safeSessionStorageRemove(LAUNCH_DRAFT_SESSION_KEY);
        return null;
    }
};

export const useCampaign = () => {
    const context = useContext(CampaignContext);
    if (!context) {
        throw new Error('useCampaign must be used within CampaignProvider');
    }
    return context;
};

// Helper: default end time = 30 days from now at 11:59 PM
const defaultEndTime = () => {
    const d = new Date();
    d.setDate(d.getDate() + 30);
    d.setHours(23, 59, 0, 0);
    const year = d.getFullYear();
    const month = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}T23:59`;
};

// Match Meta's launch behavior: a new ad set starts now unless the buyer
// deliberately schedules it. Round up a minute so the datetime-local control
// never renders a time that has already passed by the time it is submitted.
const defaultStartTime = () => {
    const now = new Date();
    now.setSeconds(0, 0);
    now.setMinutes(now.getMinutes() + 1);
    const year = now.getFullYear();
    const month = String(now.getMonth() + 1).padStart(2, '0');
    const day = String(now.getDate()).padStart(2, '0');
    const hours = String(now.getHours()).padStart(2, '0');
    const minutes = String(now.getMinutes()).padStart(2, '0');
    return `${year}-${month}-${day}T${hours}:${minutes}`;
};

// Default shape for a brand-new campaign — exported so any "Create New Campaign"
// handler (CampaignStep) can reset back to a genuinely blank form instead of
// hand-listing fields, and so it can never drift out of sync with initial state.
export const createDefaultCampaignData = () => ({
    id: null,
    name: '',
    objective: 'OUTCOME_SALES',
    budgetType: 'ABO',
    budgetScheduleType: 'DAILY', // 'DAILY' or 'LIFETIME'
    dailyBudget: 0,
    lifetimeBudget: 0,
    endTime: defaultEndTime(), // required when budgetScheduleType === 'LIFETIME'
    bidStrategy: '',
    bidAmount: 0,
    specialAdCategories: [], // e.g. ['HOUSING'] — Facebook requires this at campaign level
    status: 'PAUSED',
    fbCampaignId: null,
    isExisting: false
});

// Default shape for a brand-new ad set — see createDefaultCampaignData above.
export const createDefaultAdsetData = () => ({
    id: null,
    name: '',
    optimizationGoal: 'OFFSITE_CONVERSIONS',
    budgetScheduleType: 'DAILY', // 'DAILY' or 'LIFETIME'
    dailyBudget: 0,
    lifetimeBudget: 0,
    endTime: defaultEndTime(), // required when budgetScheduleType === 'LIFETIME'
    bidStrategy: 'LOWEST_COST_WITHOUT_CAP',
    bidAmount: 0,
    targeting: {
        genders: [], // [] = All, [1] = Male, [2] = Female
        publisher_platforms: ['facebook', 'instagram'],
        geo_locations: {
            countries: ['US'],
            excluded_countries: [],
            regions: [],
            excluded_regions: [],
            cities: [],
            excluded_cities: [],
            geo_markets: [],
            excluded_geo_markets: []
        },
        ageMin: 18,
        ageMax: 65
    },
    advantageAudience: 0, // 0 = Off, 1 = On
    startTime: defaultStartTime(),
    pixelId: '',
    // This is a lead-generation launcher. A buyer can still deliberately pick
    // another pixel event, but a fresh ad set must not quietly optimize for a
    // retail purchase event.
    conversionEvent: 'LEAD',
    attributionSetting: '7d_click',
    status: 'PAUSED',
    fbAdsetId: null,
    isExisting: false,
    adScheduleEnabled: false,
    adSchedule: [], // Array of { days: [0-6], startMinute: number, endMinute: number }
    // 'single' — one new ad set holds every generated ad (today's only behavior).
    // 'per_media' — one new ad set per distinct media file, each holding just the
    // ads generated from that file (Birch Stage's "Duplicate ad set for each
    // media" mode). Only meaningful when isExisting is false — "Use Existing Ad
    // Set" is already Birch's third mode ("Add to ad set") with no change needed.
    creationMode: 'single'
});

export const createDefaultCreativeData = () => ({
    creativeName: '',
    creatives: [],
    creativesScopeId: null,
    bodies: [''],
    headlines: [''],
    description: '',
    cta: 'GET_QUOTE',
    websiteUrl: '',
    pageId: '',
    pageAccountId: null,
    instagramId: null,
});

export const CampaignProvider = ({ children }) => {
    const [restoredDraft] = useState(restoreLaunchDraft);
    const { showWarning } = useToast();
    const draftQuotaWarnedRef = useRef(false);
    const [activeAccountId, setActiveAccountIdState] = useState(() => safeLocalStorageGet('fb_ad_account_id') || '');
    const [adAccounts, setAdAccounts] = useState([]);
    const [activeAccountLoading, setActiveAccountLoading] = useState(true);

    const [campaignData, setCampaignData] = useState(() => restoredDraft?.campaignData || createDefaultCampaignData());

    const [adsetData, setAdsetData] = useState(() => restoredDraft?.adsetData || createDefaultAdsetData());

    const [creativeData, setCreativeData] = useState(() => restoredDraft?.creativeData || createDefaultCreativeData());

    const [adsData, setAdsData] = useState(() => restoredDraft?.adsData || []);

    // Read-only snapshot the launcher shell's summary rail renders from — each step
    // that already computes these numbers for its own UI (AdCreativeStep's variation
    // counter, BulkAdCreation's review header) pushes its own values here rather than
    // the shell re-deriving them, so the two can never drift apart. Cleared on step
    // change isn't needed: each producer overwrites the fields it owns every render.
    const [launchSummary, setLaunchSummary] = useState({
        creativeCount: null,
        headlineCount: null,
        bodyCount: null,
        totalAds: null,
        warningCount: null,
        readyCount: null,
        excludedCount: null,
    });

    // The Review step owns the actual Meta write. Keep its successful outcome
    // alongside the rest of the wizard context so the completion screen can be
    // a real receipt instead of a generic success message. Keep it only in the
    // current browser tab session so a refresh cannot erase a successful Meta
    // write, while Ads Manager remains the durable delivery authority.
    const [launchReceipt, setLaunchReceiptState] = useState(restoreLaunchReceipt);
    const setLaunchReceipt = useCallback((receipt) => {
        setLaunchReceiptState(receipt);
        if (receipt) {
            safeSessionStorageSet(LAUNCH_RECEIPT_SESSION_KEY, JSON.stringify(receipt));
            safeSessionStorageRemove(LAUNCH_DRAFT_SESSION_KEY);
        }
        else safeSessionStorageRemove(LAUNCH_RECEIPT_SESSION_KEY);
    }, []);

    const [selectedAdAccount, setSelectedAdAccount] = useState(() => restoredDraft?.selectedAdAccount || null);

    // Shown once when a launch was restored after a refresh or a return visit, so
    // a buyer never mistakes a saved draft for a fresh launcher and spends on a
    // stale account / campaign / ad set.
    const [restoredDraftNotice, setRestoredDraftNotice] = useState(() => {
        if (!draftHasContent(restoredDraft)) return null;
        const creatives = restoredDraft.creativeData?.creatives || [];
        return {
            savedAt: restoredDraft.savedAt || null,
            accountName: restoredDraft.selectedAdAccount?.name || null,
            campaignName: restoredDraft.campaignData?.name || null,
            adsetName: restoredDraft.adsetData?.name || null,
            adCount: restoredDraft.adsData?.length || 0,
            creativeCount: creatives.length,
            localFileCount: creatives.filter(creative => creative.needsReupload).length,
        };
    });
    const dismissRestoredDraft = useCallback(() => setRestoredDraftNotice(null), []);
    const discardLaunchDraft = useCallback(() => {
        clearLaunchDraftSession();
        setCampaignData(createDefaultCampaignData());
        setAdsetData(createDefaultAdsetData());
        setCreativeData(createDefaultCreativeData());
        setAdsData([]);
        setLaunchSummary({ creativeCount: null, headlineCount: null, bodyCount: null, totalAds: null, warningCount: null, readyCount: null, excludedCount: null });
        setSelectedAdAccount(null);
        setRestoredDraftNotice(null);
    }, []);

    // Keep an in-progress launch available after a browser refresh. File objects
    // cannot survive sessionStorage, but Drive creatives use durable R2 URLs and
    // are restored with file=null. Ordinary local-file rows cannot be rebuilt:
    // they are flagged needsReupload (and their dead blob: preview dropped) so the
    // banner can name them; the review asset validator still blocks launch on them.
    useEffect(() => {
        if (launchReceipt) return undefined;
        // Debounced: the whole draft (every Drive creative) is serialized, and
        // campaign/ad set names change on every keystroke.
        const timer = setTimeout(() => {
            const serializableCreativeData = {
                ...creativeData,
                creatives: (creativeData.creatives || []).map(creative => {
                    if (creative.source === 'drive') return { ...creative, file: null };
                    const previewUrl = typeof creative.previewUrl === 'string' && creative.previewUrl.startsWith('blob:')
                        ? null
                        : creative.previewUrl;
                    return { ...creative, file: null, previewUrl, needsReupload: true };
                }),
            };
            const draft = {
                savedAt: new Date().toISOString(),
                campaignData,
                adsetData,
                creativeData: serializableCreativeData,
                adsData,
                selectedAdAccount,
            };
            // Never persist an empty launcher: it would leave a "draft" that
            // restores nothing but still carries a stale wizard step, and a
            // second provider instance could resurrect a discarded draft.
            if (!draftHasContent(draft)) {
                safeSessionStorageRemove(LAUNCH_DRAFT_SESSION_KEY);
                return;
            }
            if (!safeSessionStorageSet(LAUNCH_DRAFT_SESSION_KEY, JSON.stringify(draft))) {
                // Quota exceeded: a stale draft left behind is worse than none, because
                // it would restore an older state as if it were current.
                safeSessionStorageRemove(LAUNCH_DRAFT_SESSION_KEY);
                console.warn('Launch draft is too large to keep across a refresh; it was not saved.');
                if (!draftQuotaWarnedRef.current) {
                    draftQuotaWarnedRef.current = true;
                    showWarning('This launch is too large to keep across a page refresh. Avoid refreshing until it is launched.');
                }
            }
        }, 400);
        return () => clearTimeout(timer);
    }, [campaignData, adsetData, creativeData, adsData, selectedAdAccount, launchReceipt, showWarning]);

    const normalizeAccountId = useCallback((rawId) => {
        if (!rawId) return '';
        const id = String(rawId);
        return id.startsWith('act_') ? id : `act_${id}`;
    }, []);

    const setActiveAccountId = useCallback((accountId) => {
        const normalized = normalizeAccountId(accountId);
        setActiveAccountIdState(normalized);
        if (normalized) {
            safeLocalStorageSet('fb_ad_account_id', normalized);
        } else {
            localStorage.removeItem('fb_ad_account_id');
        }
    }, [normalizeAccountId]);

    useEffect(() => {
        let cancelled = false;

        const resolveActiveAccount = async () => {
            setActiveAccountLoading(true);
            const cached = normalizeAccountId(safeLocalStorageGet('fb_ad_account_id') || '');

            try {
                const accountsResponse = await authFetch(`${import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1'}/facebook/accounts`);
                if (accountsResponse.ok) {
                    const accountsData = await accountsResponse.json();
                    if (cancelled) return;

                    setAdAccounts(accountsData);
                    const accountIds = accountsData
                        .map(account => normalizeAccountId(account.id || account.account_id || account.accountId))
                        .filter(Boolean);

                    if (cached && accountIds.includes(cached)) {
                        setActiveAccountId(cached);
                    } else if (accountIds.length > 0) {
                        setActiveAccountId(accountIds[0]);
                    } else {
                        setActiveAccountId('');
                    }
                    return;
                }
            } catch (err) {
                console.error('Failed to load Meta ad accounts:', err);
            }

            try {
                const configResponse = await authFetch(`${import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1'}/facebook/config`);
                if (!cancelled && configResponse.ok) {
                    const config = await configResponse.json();
                    setActiveAccountId(config.ad_account_id || cached || '');
                } else if (!cancelled) {
                    setActiveAccountId(cached);
                }
            } catch (err) {
                if (!cancelled) setActiveAccountId(cached);
            } finally {
                if (!cancelled) setActiveAccountLoading(false);
            }
        };

        resolveActiveAccount().finally(() => {
            if (!cancelled) setActiveAccountLoading(false);
        });

        return () => { cancelled = true; };
    }, [normalizeAccountId, setActiveAccountId]);

    const value = {
        campaignData,
        setCampaignData,
        adsetData,
        setAdsetData,
        creativeData,
        setCreativeData,
        adsData,
        setAdsData,
        launchSummary,
        setLaunchSummary,
        launchReceipt,
        setLaunchReceipt,
        selectedAdAccount,
        setSelectedAdAccount,
        restoredDraftNotice,
        dismissRestoredDraft,
        discardLaunchDraft,
        activeAccountId,
        setActiveAccountId,
        adAccounts,
        activeAccountLoading
    };

    return (
        <CampaignContext.Provider value={value}>
            {children}
        </CampaignContext.Provider>
    );
};
