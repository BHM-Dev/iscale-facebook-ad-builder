import React, { createContext, useCallback, useEffect, useContext, useState } from 'react';
import { authFetch } from '../lib/facebookApi';

const CampaignContext = createContext();

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

// Helper: default start time = tomorrow at 1:00 AM
const defaultStartTime = () => {
    const tomorrow = new Date();
    tomorrow.setDate(tomorrow.getDate() + 1);
    tomorrow.setHours(1, 0, 0, 0);
    const year = tomorrow.getFullYear();
    const month = String(tomorrow.getMonth() + 1).padStart(2, '0');
    const day = String(tomorrow.getDate()).padStart(2, '0');
    const hours = String(tomorrow.getHours()).padStart(2, '0');
    const minutes = String(tomorrow.getMinutes()).padStart(2, '0');
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
    conversionEvent: 'PURCHASE',
    attributionSetting: '7d_click',
    status: 'PAUSED',
    fbAdsetId: null,
    isExisting: false,
    adScheduleEnabled: false,
    adSchedule: [] // Array of { days: [0-6], startMinute: number, endMinute: number }
});

export const CampaignProvider = ({ children }) => {
    const [activeAccountId, setActiveAccountIdState] = useState(() => localStorage.getItem('fb_ad_account_id') || '');
    const [adAccounts, setAdAccounts] = useState([]);
    const [activeAccountLoading, setActiveAccountLoading] = useState(true);

    const [campaignData, setCampaignData] = useState(createDefaultCampaignData);

    const [adsetData, setAdsetData] = useState(createDefaultAdsetData);

    const [creativeData, setCreativeData] = useState({
        creativeName: '',
        creatives: [], // Array of { id, file, previewUrl, name }
        creativesScopeId: null, // ad-account + campaign key the current `creatives` belong to — see AdCreativeStep's clear-on-campaign-switch effect
        bodies: [''], // Start with 1 field
        headlines: [''], // Start with 1 field
        description: '',
        cta: 'LEARN_MORE',
        websiteUrl: '',
        pageId: '',
        instagramId: null
    });

    const [adsData, setAdsData] = useState([]);

    const [selectedAdAccount, setSelectedAdAccount] = useState(null);

    const normalizeAccountId = useCallback((rawId) => {
        if (!rawId) return '';
        const id = String(rawId);
        return id.startsWith('act_') ? id : `act_${id}`;
    }, []);

    const setActiveAccountId = useCallback((accountId) => {
        const normalized = normalizeAccountId(accountId);
        setActiveAccountIdState(normalized);
        if (normalized) {
            localStorage.setItem('fb_ad_account_id', normalized);
        } else {
            localStorage.removeItem('fb_ad_account_id');
        }
    }, [normalizeAccountId]);

    useEffect(() => {
        let cancelled = false;

        const resolveActiveAccount = async () => {
            setActiveAccountLoading(true);
            const cached = normalizeAccountId(localStorage.getItem('fb_ad_account_id') || '');

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

    const resetWizard = () => {
        setCampaignData({
            id: null,
            name: '',
            objective: 'OUTCOME_SALES',
            budgetType: 'ABO',
            budgetScheduleType: 'DAILY',
            dailyBudget: 0,
            lifetimeBudget: 0,
            endTime: defaultEndTime(),
            bidStrategy: '',
            specialAdCategories: [],
            status: 'PAUSED',
            fbCampaignId: null,
            isExisting: false
        });
        setAdsetData({
            id: null,
            name: '',
            optimizationGoal: 'OFFSITE_CONVERSIONS',
            budgetScheduleType: 'DAILY',
            dailyBudget: 0,
            lifetimeBudget: 0,
            endTime: defaultEndTime(),
            bidStrategy: 'LOWEST_COST_WITHOUT_CAP',
            bidAmount: 0,
            targeting: {
                genders: [],
                publisher_platforms: ['facebook', 'instagram'],
                countries: ['US'],
                ageMin: 18,
                ageMax: 65
            },
            advantageAudience: 0,
            startTime: defaultStartTime(),
            pixelId: '',
            conversionEvent: 'PURCHASE',
            status: 'PAUSED',
            fbAdsetId: null,
            isExisting: false,
            adScheduleEnabled: false,
            adSchedule: []
        });
        setCreativeData({
            creativeName: '',
            creatives: [],
            creativesScopeId: null,
            bodies: ['', '', ''],
            headlines: ['', '', ''],
            description: '',
            cta: 'LEARN_MORE',
            websiteUrl: '',
            pageId: ''
        });
        setAdsData([]);
        setSelectedAdAccount(null);
    };

    const value = {
        campaignData,
        setCampaignData,
        adsetData,
        setAdsetData,
        creativeData,
        setCreativeData,
        adsData,
        setAdsData,
        selectedAdAccount,
        setSelectedAdAccount,
        activeAccountId,
        setActiveAccountId,
        adAccounts,
        activeAccountLoading,
        resetWizard
    };

    return (
        <CampaignContext.Provider value={value}>
            {children}
        </CampaignContext.Provider>
    );
};
