import { authFetch } from '../lib/facebookApi';

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1';
const API_URL = `${API_BASE}/research`;

// Every research route now requires auth (2026-09-04) — this file used raw
// axios with no bearer token, so every call here 401'd the moment those
// routes were protected. Converted to authFetch, matching the rest of the
// app's convention: fetch-style (not axios), Response.ok checked explicitly,
// query params built into the URL (FastAPI reads these as plain function
// args, not a body model, for the POST-with-query-params endpoints below).

async function unwrap(response, label) {
    if (!response.ok) {
        let detail = `HTTP ${response.status}`;
        try {
            const body = await response.json();
            detail = body.detail || detail;
        } catch {
            // response body wasn't JSON — keep the status-only message
        }
        const error = new Error(detail);
        error.status = response.status;
        console.error(`${label}:`, detail);
        throw error;
    }
    return response.json();
}

export const searchAndSave = async (request) => {
    const response = await authFetch(`${API_URL}/search-and-save`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(request),
    });
    return unwrap(response, 'Error searching and saving');
};

export const getSavedSearches = async () => {
    const response = await authFetch(`${API_URL}/saved-searches`);
    return unwrap(response, 'Error fetching saved searches');
};

export const getSavedSearch = async (searchId) => {
    const response = await authFetch(`${API_URL}/saved-searches/${searchId}`);
    return unwrap(response, 'Error fetching saved search');
};

export const deleteSavedSearch = async (searchId) => {
    const response = await authFetch(`${API_URL}/saved-searches/${searchId}`, { method: 'DELETE' });
    return unwrap(response, 'Error deleting saved search');
};

export const getApiUsage = async () => {
    const response = await authFetch(`${API_URL}/api-usage`);
    return unwrap(response, 'Error fetching API usage');
};

export const getBlacklist = async () => {
    const response = await authFetch(`${API_URL}/blacklist`);
    return unwrap(response, 'Error fetching blacklist');
};

export const addToBlacklist = async (pageName, reason = null) => {
    const params = new URLSearchParams({ page_name: pageName, ...(reason ? { reason } : {}) });
    const response = await authFetch(`${API_URL}/blacklist?${params}`, { method: 'POST' });
    return unwrap(response, 'Error adding to blacklist');
};

export const removeFromBlacklist = async (blacklistId) => {
    const response = await authFetch(`${API_URL}/blacklist/${blacklistId}`, { method: 'DELETE' });
    return unwrap(response, 'Error removing from blacklist');
};

export const getKeywordBlacklist = async () => {
    const response = await authFetch(`${API_URL}/keyword-blacklist`);
    return unwrap(response, 'Error fetching keyword blacklist');
};

export const addToKeywordBlacklist = async (keyword, reason = null) => {
    const params = new URLSearchParams({ keyword, ...(reason ? { reason } : {}) });
    const response = await authFetch(`${API_URL}/keyword-blacklist?${params}`, { method: 'POST' });
    return unwrap(response, 'Error adding to keyword blacklist');
};

export const removeFromKeywordBlacklist = async (blacklistId) => {
    const response = await authFetch(`${API_URL}/keyword-blacklist/${blacklistId}`, { method: 'DELETE' });
    return unwrap(response, 'Error removing from keyword blacklist');
};

export const getRateLimit = async () => {
    const response = await authFetch(`${API_URL}/rate-limit`);
    return unwrap(response, 'Error fetching rate limit');
};

export const getFacebookPages = async (limit = 50, offset = 0, sortBy = 'total_ads') => {
    const params = new URLSearchParams({ limit, offset, sort_by: sortBy });
    const response = await authFetch(`${API_URL}/facebook-pages?${params}`);
    return unwrap(response, 'Error fetching Facebook pages');
};

export const getVerticals = async () => {
    const response = await authFetch(`${API_URL}/verticals`);
    return unwrap(response, 'Error fetching verticals');
};

export const createVertical = async (name, description = null) => {
    const params = new URLSearchParams({ name, ...(description ? { description } : {}) });
    const response = await authFetch(`${API_URL}/verticals?${params}`, { method: 'POST' });
    return unwrap(response, 'Error creating vertical');
};

export const getVerticalAggregatedAds = async (verticalId) => {
    const response = await authFetch(`${API_URL}/verticals/${verticalId}/aggregated-ads`);
    return unwrap(response, 'Error fetching vertical aggregated ads');
};

export const getVerticalPageAds = async (verticalId, pageId) => {
    const response = await authFetch(`${API_URL}/verticals/${verticalId}/pages/${pageId}/ads`);
    return unwrap(response, 'Error fetching vertical page ads');
};

// Brand Scrapes API
export const createBrandScrape = async (brandName, pageUrl) => {
    const response = await authFetch(`${API_URL}/brand-scrapes`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ brand_name: brandName, page_url: pageUrl }),
    });
    return unwrap(response, 'Error creating brand scrape');
};

export const getBrandScrapes = async () => {
    const response = await authFetch(`${API_URL}/brand-scrapes`);
    return unwrap(response, 'Error fetching brand scrapes');
};

export const getBrandScrape = async (scrapeId) => {
    const response = await authFetch(`${API_URL}/brand-scrapes/${scrapeId}`);
    return unwrap(response, 'Error fetching brand scrape');
};

export const deleteBrandScrape = async (scrapeId) => {
    const response = await authFetch(`${API_URL}/brand-scrapes/${scrapeId}`, { method: 'DELETE' });
    return unwrap(response, 'Error deleting brand scrape');
};
