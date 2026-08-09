import React, { useState, useCallback, useMemo, useEffect } from 'react';
import Papa from 'papaparse';
import { useToast } from '../context/ToastContext';
import { useAuth } from '../context/AuthContext';
import { UploadCloud, Loader, FileText, Image as ImageIcon, CheckCircle2, AlertTriangle, XCircle } from 'lucide-react';
import { useCampaign } from '../context/CampaignContext';
import { createCompleteAd, createFacebookCampaign, createFacebookAdSet } from '../lib/facebookApi';
import { CTA_OPTIONS } from './AdCreativeStep';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1';

// Matches ad{N}-{slug}-{aspect}.{ext} e.g. "ad12-hero-shot-1x1.png"
const FILENAME_PATTERN = /^ad(\d+)-.*-(1x1|9x16)\.(png|jpe?g)$/i;

// Meta hard-caps a single ad set at 50 ads. Above that we block submission
// rather than silently chunking — simpler and safer than auto-splitting.
const MAX_ADS_PER_ADSET = 50;

// Small unconditional delay between per-row Meta calls so a 100-row batch
// doesn't hammer the API back-to-back. Not a substitute for real backoff —
// just enough spacing to avoid tripping app-level rate limits on a burst.
const INTER_ROW_DELAY_MS = 350;

// Meta throttle / rate-limit error codes (Application request limit reached,
// Ad account limit, and the 80000-80014 custom-throttle family). If a row
// fails with one of these we stop the batch immediately instead of grinding
// through the rest into a wall of identical errors.
const RATE_LIMIT_ERROR_CODES = new Set([17, 613, 80000, 80001, 80002, 80003, 80004, 80005, 80006, 80007, 80008, 80009, 80010, 80011, 80012, 80013, 80014]);

function delay(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
}

// Extracts the digits from any ad-number format ("12", "AD 12", "ad-12",
// "012") and drops leading zeros, so both sides of the CSV/filename join
// resolve to the same key regardless of how the number was typed/named.
function normalizeAdNumber(raw) {
    if (raw === null || raw === undefined) return '';
    const match = String(raw).match(/\d+/);
    if (!match) return '';
    return String(parseInt(match[0], 10));
}

// Normalizes free-text CSV CTA values ("learn more", "Learn-More") into the
// enum shape Meta expects ("LEARN_MORE") before checking it against the
// whitelist.
function normalizeCta(raw) {
    return String(raw || '').trim().toUpperCase().replace(/[\s-]+/g, '_');
}

/**
 * Uploads a raw File to our own server (same path used internally by
 * uploadImageToFacebook/uploadVideoToFacebook for blob URLs) and returns the
 * persisted URL. Used for the 9x16 secondary asset (never sent to Meta, just
 * needs a durable URL to store) and for the 1x1 primary asset (needs a
 * durable URL both to store AND to feed into ad creation).
 */
async function uploadFileToServer(file, authFetch) {
    const formData = new FormData();
    formData.append('file', file);
    const response = await authFetch(`${API_URL}/uploads/`, {
        method: 'POST',
        body: formData
    });
    if (!response.ok) {
        throw new Error('Failed to upload file to server');
    }
    const result = await response.json();
    return result.url;
}

// The local-storage upload fallback returns a root-relative path like
// "/uploads/x.png" (StaticFiles is mounted at the API root, not under
// /api/v1) — R2 (when configured) already returns a full https:// URL. Either
// way, resolve to an absolute http(s) URL so what we save to /ads/save is a
// genuinely durable, server-reachable link (never a blob:), and so
// uploadImageToFacebook's `startsWith('blob:')` check cleanly skips its
// internal re-upload path and sends it straight through.
function toAbsoluteUploadUrl(url) {
    if (!url) return url;
    if (/^https?:\/\//i.test(url)) return url;
    const apiOrigin = API_URL.replace(/\/api\/v1\/?$/, '');
    return `${apiOrigin}${url.startsWith('/') ? '' : '/'}${url}`;
}

const BulkMatchImport = ({ onNext, onBack }) => {
    const { showWarning, showError } = useToast();
    const { authFetch } = useAuth();
    const { campaignData, adsetData, creativeData, selectedAdAccount } = useCampaign();

    const [csvRows, setCsvRows] = useState([]); // [{ adNumber, headline, primaryText, cta }]
    const [csvError, setCsvError] = useState('');
    const [imageGroups, setImageGroups] = useState({}); // { [adNumber]: { oneByOne: File, nineBySixteen: File } }
    const [loading, setLoading] = useState(false);
    const [progress, setProgress] = useState({ current: 0, total: 0, status: '' });
    const [errors, setErrors] = useState([]);

    const handleCsvUpload = useCallback((e) => {
        const file = e.target.files?.[0];
        if (!file) return;
        setCsvError('');

        Papa.parse(file, {
            header: true,
            skipEmptyLines: true,
            transformHeader: (h) => h.trim().toLowerCase(),
            complete: (results) => {
                if (results.errors && results.errors.length > 0) {
                    setCsvError(`CSV parse error: ${results.errors[0].message} (row ${results.errors[0].row})`);
                }

                const rows = [];
                const seen = new Set();
                const duplicateAdNumbers = new Set();

                for (const raw of results.data) {
                    const adNumber = normalizeAdNumber(raw.ad_number);
                    if (adNumber === '') continue;

                    if (seen.has(adNumber)) {
                        duplicateAdNumbers.add(adNumber);
                        continue; // first occurrence wins; later duplicates are dropped
                    }
                    seen.add(adNumber);

                    rows.push({
                        adNumber,
                        headline: (raw.headline || '').trim(),
                        primaryText: (raw.primary_text || '').trim(),
                        cta: (raw.cta || '').trim()
                    });
                }

                setCsvRows(rows);

                if (duplicateAdNumbers.size > 0) {
                    const list = Array.from(duplicateAdNumbers).sort((a, b) => Number(a) - Number(b));
                    showWarning(`Duplicate CSV row${list.length !== 1 ? 's' : ''} for AD ${list.join(', AD ')} — only the first row for each was kept.`);
                }
            },
            error: (err) => {
                setCsvError(`Failed to read CSV: ${err.message}`);
            }
        });
        // Allow re-selecting the same file later
        e.target.value = '';
    }, [showWarning]);

    const handleImageUpload = useCallback((e) => {
        const files = Array.from(e.target.files || []);
        if (files.length === 0) return;

        const next = { ...imageGroups };
        const unmatched = [];
        const duplicateAdNumbers = new Set();

        for (const file of files) {
            const match = file.name.match(FILENAME_PATTERN);
            if (!match) {
                unmatched.push(file.name); // surfaced via toast below — nothing silently vanishes
                continue;
            }
            const [, adNumberRaw, aspectRaw] = match;
            const adNumber = normalizeAdNumber(adNumberRaw); // normalize "01" -> "1"
            const aspect = aspectRaw.toLowerCase();
            const group = next[adNumber] ? { ...next[adNumber] } : {};
            if (aspect === '1x1') {
                if (group.oneByOne) duplicateAdNumbers.add(adNumber);
                group.oneByOne = file;
            } else {
                if (group.nineBySixteen) duplicateAdNumbers.add(adNumber);
                group.nineBySixteen = file;
            }
            next[adNumber] = group;
        }

        setImageGroups(next);

        if (unmatched.length > 0) {
            showWarning(`${unmatched.length} file${unmatched.length !== 1 ? 's' : ''} skipped — name didn't match ad{N}-{slug}-{1x1|9x16}.png: ${unmatched.slice(0, 3).join(', ')}${unmatched.length > 3 ? '…' : ''}`);
        }
        if (duplicateAdNumbers.size > 0) {
            const list = Array.from(duplicateAdNumbers).sort((a, b) => Number(a) - Number(b));
            showWarning(`Duplicate image for AD ${list.join(', AD ')} — a matching aspect was uploaded twice; only the last file for each was kept.`);
        }

        e.target.value = '';
    }, [showWarning, imageGroups]);

    // CSV rows are already keyed by normalized ad number at parse time.
    const csvByNumber = useMemo(() => {
        const map = {};
        for (const row of csvRows) {
            map[row.adNumber] = row;
        }
        return map;
    }, [csvRows]);

    // One row per ad_number found in either source. Also mints the review-table
    // thumbnail object URLs here (once per recompute) instead of inline in JSX,
    // so they're memoized and revocable rather than re-created every render.
    const matchedRows = useMemo(() => {
        const allNumbers = new Set([...Object.keys(csvByNumber), ...Object.keys(imageGroups)]);
        const rows = Array.from(allNumbers).map((adNumber) => {
            const copy = csvByNumber[adNumber] || null;
            const images = imageGroups[adNumber] || {};
            const hasCopy = !!(copy && copy.headline && copy.primaryText);
            const hasImage = !!images.oneByOne;

            const ctaRaw = copy?.cta ?? '';
            const normalizedCta = ctaRaw === '' ? 'LEARN_MORE' : normalizeCta(ctaRaw);
            const ctaValid = CTA_OPTIONS.includes(normalizedCta);

            let status;
            if (!hasCopy) status = 'missing_copy'; // has image(s) but no/incomplete CSV row
            else if (!hasImage) status = 'missing_image';
            else if (!ctaValid) status = 'invalid_cta';
            else status = 'ready';

            return {
                adNumber,
                headline: copy?.headline || '',
                primaryText: copy?.primaryText || '',
                cta: normalizedCta,
                oneByOne: images.oneByOne || null,
                nineBySixteen: images.nineBySixteen || null,
                oneByOnePreviewUrl: images.oneByOne ? URL.createObjectURL(images.oneByOne) : null,
                nineBySixteenPreviewUrl: images.nineBySixteen ? URL.createObjectURL(images.nineBySixteen) : null,
                status
            };
        });
        rows.sort((a, b) => Number(a.adNumber) - Number(b.adNumber));
        return rows;
    }, [csvByNumber, imageGroups]);

    // Revoke the object URLs minted above whenever matchedRows is recomputed
    // (or the component unmounts) so review-table thumbnails don't leak blobs.
    useEffect(() => {
        return () => {
            matchedRows.forEach((row) => {
                if (row.oneByOnePreviewUrl) URL.revokeObjectURL(row.oneByOnePreviewUrl);
                if (row.nineBySixteenPreviewUrl) URL.revokeObjectURL(row.nineBySixteenPreviewUrl);
            });
        };
    }, [matchedRows]);

    const readyRows = matchedRows.filter((r) => r.status === 'ready');
    const missingImageRows = matchedRows.filter((r) => r.status === 'missing_image');
    const missingCopyRows = matchedRows.filter((r) => r.status === 'missing_copy');
    const invalidCtaRows = matchedRows.filter((r) => r.status === 'invalid_cta');

    const handleSubmit = async () => {
        if (readyRows.length === 0) {
            showWarning('No rows are ready to create — match at least one CSV row to a 1x1 image');
            return;
        }
        if (readyRows.length > MAX_ADS_PER_ADSET) {
            showError(`This batch has ${readyRows.length} ready ads — Meta limits a single ad set to ${MAX_ADS_PER_ADSET} ads. Split the batch into groups of ${MAX_ADS_PER_ADSET} or fewer (e.g. by AD # range) and run each separately.`);
            return;
        }
        if (!creativeData.websiteUrl) {
            showError('Destination link is missing. Go back and set the destination URL in the Creative step.');
            return;
        }
        if (!creativeData.pageId) {
            showError('Page ID is missing. Go back to the Creative step and select a Facebook Page.');
            return;
        }

        setLoading(true);
        setErrors([]);
        setProgress({ current: 0, total: readyRows.length, status: 'Starting...' });

        try {
            // ── Step 1: Campaign ──────────────────────────────────────────────
            let fbCampaignId = campaignData.fbCampaignId;
            if (!campaignData.isExisting) {
                setProgress((prev) => ({ ...prev, status: 'Creating campaign on Facebook...' }));
                fbCampaignId = await createFacebookCampaign(campaignData, selectedAdAccount.accountId);
            }

            try {
                const saveCampRes = await authFetch(`${API_URL}/facebook/campaigns/save`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        ...campaignData,
                        fbCampaignId,
                        dailyBudget: Number(campaignData.dailyBudget),
                        lifetimeBudget: campaignData.lifetimeBudget ? Number(campaignData.lifetimeBudget) : null,
                        budgetScheduleType: campaignData.budgetScheduleType || 'DAILY',
                        endTime: campaignData.endTime || null
                    })
                });
                if (!saveCampRes.ok) {
                    const err = await saveCampRes.json().catch(() => ({}));
                    throw new Error(
                        `Campaign ${fbCampaignId} was created on Meta but could not be saved locally: `
                        + `${err.detail || err.message || saveCampRes.status}. `
                        + `Do not re-launch — it already exists on the account.`
                    );
                }
            } catch (err) {
                console.error('Error saving campaign locally:', err);
                throw err;
            }

            // ── Step 2: Ad Set — single feed ad set (no placement customization) ──
            let fbAdsetId = adsetData.fbAdsetId;
            if (!adsetData.isExisting) {
                setProgress((prev) => ({ ...prev, status: 'Creating ad set on Facebook...' }));
                const adsetPayload = {
                    ...adsetData,
                    ...(campaignData.budgetType === 'CBO' && {
                        bidStrategy: campaignData.bidStrategy,
                        bidAmount: campaignData.bidAmount
                    }),
                    specialAdCategories: campaignData.specialAdCategories || []
                };
                fbAdsetId = await createFacebookAdSet(adsetPayload, fbCampaignId, selectedAdAccount.accountId, campaignData.budgetType);
            }

            const adsetSaveBody = {
                ...adsetData,
                campaignId: campaignData.id,
                fbAdsetId,
                dailyBudget: adsetData.dailyBudget ? Number(adsetData.dailyBudget) : null,
                lifetimeBudget: adsetData.lifetimeBudget ? Number(adsetData.lifetimeBudget) : null,
                budgetScheduleType: adsetData.budgetScheduleType || 'DAILY',
                endTime: adsetData.endTime || null,
                bidAmount: adsetData.bidAmount ? Number(adsetData.bidAmount) : null
            };
            try {
                const saveAdSetRes = await authFetch(`${API_URL}/facebook/adsets/save`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(adsetSaveBody)
                });
                if (!saveAdSetRes.ok) {
                    const err = await saveAdSetRes.json().catch(() => ({}));
                    throw new Error(
                        `Ad set ${fbAdsetId} was created on Meta but could not be saved locally: `
                        + `${err.detail || err.message || saveAdSetRes.status}. `
                        + `Do not re-launch — it already exists on the account.`
                    );
                }
            } catch (err) {
                console.error('Error saving ad set locally:', err);
                throw err;
            }

            // ── Step 3: Ads — loop only "Ready" rows ────────────────────────────
            const createdAds = [];
            let failedCount = 0;
            let rateLimited = false;
            for (let i = 0; i < readyRows.length; i++) {
                if (i > 0) await delay(INTER_ROW_DELAY_MS); // unconditional spacing between Meta calls

                const row = readyRows[i];
                setProgress({
                    current: i + 1,
                    total: readyRows.length,
                    status: `Creating AD ${row.adNumber} (${i + 1} of ${readyRows.length})...`
                });

                try {
                    // Upload the primary 1x1 to get a durable, server-reachable URL
                    // BEFORE creating the ad — never persist a blob: URL, which dies
                    // the moment this tab closes.
                    const rawImageUrl = await uploadFileToServer(row.oneByOne, authFetch);
                    const imageUrl = toAbsoluteUploadUrl(rawImageUrl);

                    // Upload the 9x16 secondary asset (if present) to get a durable
                    // URL to store — same upload path, used internally for blob URLs.
                    // Not sent to Meta; reserved for a future placement feature.
                    let secondaryImageUrl = null;
                    if (row.nineBySixteen) {
                        try {
                            secondaryImageUrl = await uploadFileToServer(row.nineBySixteen, authFetch);
                        } catch (uploadErr) {
                            console.warn(`Could not upload 9x16 asset for AD ${row.adNumber} — continuing without it:`, uploadErr);
                        }
                    }

                    const rowCreativeData = {
                        ...creativeData,
                        mediaType: 'image',
                        imageUrl,
                        videoUrl: undefined,
                        headlines: [row.headline],
                        bodies: [row.primaryText],
                        cta: row.cta
                    };

                    const adData = {
                        id: `ad_${Date.now()}_${row.adNumber}`,
                        name: `AD ${row.adNumber}`,
                        status: 'PAUSED'
                    };

                    const result = await createCompleteAd(
                        fbCampaignId,
                        { ...adsetData, fbAdsetId },
                        rowCreativeData,
                        adData,
                        creativeData.pageId,
                        selectedAdAccount.accountId,
                        campaignData.budgetType
                    );

                    const saveAdRes = await authFetch(`${API_URL}/facebook/ads/save`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            id: adData.id,
                            adsetId: adsetData.id,
                            name: adData.name,
                            creativeName: creativeData.creativeName,
                            mediaType: 'image',
                            imageUrl,
                            secondaryImageUrl,
                            adNumber: row.adNumber,
                            bodies: [row.primaryText],
                            headlines: [row.headline],
                            description: creativeData.description,
                            cta: row.cta,
                            websiteUrl: creativeData.websiteUrl,
                            status: 'PAUSED',
                            fbAdId: result.adId,
                            fbCreativeId: result.creativeId
                        })
                    });
                    if (!saveAdRes.ok) {
                        const err = await saveAdRes.json();
                        throw new Error(`Failed to save ad locally: ${err.detail || err.message}`);
                    }

                    createdAds.push({ ...row, fbAdId: result.adId, fbCreativeId: result.creativeId });
                } catch (error) {
                    console.error(`Error creating AD ${row.adNumber}:`, error);
                    setErrors((prev) => [...prev, `Failed to create AD ${row.adNumber}: ${error.message}`]);
                    failedCount++;

                    if (RATE_LIMIT_ERROR_CODES.has(error.metaErrorCode)) {
                        rateLimited = true;
                        const remaining = readyRows.length - (i + 1);
                        setErrors((prev) => [...prev, `Meta rate-limited this account — stopping batch. ${createdAds.length} of ${readyRows.length} ads created. ${remaining} row${remaining !== 1 ? 's' : ''} not attempted — wait a few minutes and retry.`]);
                        break;
                    }
                }
            }

            if (failedCount === 0) {
                setProgress({ current: readyRows.length, total: readyRows.length, status: 'Complete!' });
                setTimeout(() => { onNext(); }, 1500);
            } else {
                setProgress({
                    current: readyRows.length,
                    total: readyRows.length,
                    status: rateLimited
                        ? `Stopped — Meta rate-limited this account (${createdAds.length} of ${readyRows.length} created)`
                        : `${createdAds.length} of ${readyRows.length} ads created`
                });
                setLoading(false);
            }
        } catch (error) {
            console.error('Error in bulk match import:', error);
            showError(`Error: ${error.message}`);
            setLoading(false);
        }
    };

    const statusBadge = (status) => {
        if (status === 'ready') {
            return (
                <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full font-medium bg-green-100 text-green-700">
                    <CheckCircle2 size={12} /> Ready
                </span>
            );
        }
        if (status === 'missing_image') {
            return (
                <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full font-medium bg-amber-100 text-amber-700">
                    <AlertTriangle size={12} /> Missing image
                </span>
            );
        }
        if (status === 'invalid_cta') {
            return (
                <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full font-medium bg-red-100 text-red-700">
                    <XCircle size={12} /> Invalid CTA
                </span>
            );
        }
        return (
            <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full font-medium bg-red-100 text-red-700">
                <XCircle size={12} /> Missing copy
            </span>
        );
    };

    return (
        <div>
            <h2 className="text-2xl font-bold mb-2">Match by Naming Convention</h2>
            <p className="text-gray-600 mb-6">
                Upload a copy CSV and an image folder. Rows are matched by ad number (<code className="bg-gray-100 px-1 rounded">AD 1</code> ↔{' '}
                <code className="bg-gray-100 px-1 rounded">ad1-slug-1x1.png</code>). Only <strong>Ready</strong> rows are created.
            </p>

            {!loading ? (
                <>
                    {/* Uploaders */}
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
                        <div className="border-2 border-dashed border-gray-300 rounded-lg p-6 text-center hover:border-blue-400 transition-colors">
                            <FileText className="mx-auto mb-2 text-gray-400" size={28} />
                            <p className="text-sm font-medium text-gray-700 mb-1">Ad Copy CSV</p>
                            <p className="text-xs text-gray-500 mb-3">columns: ad_number, headline, primary_text, cta</p>
                            <p className="text-xs text-gray-400 mb-3">cta must match: {CTA_OPTIONS.join(', ')}</p>
                            <label className="inline-flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium cursor-pointer hover:bg-blue-700">
                                <UploadCloud size={16} /> Choose CSV
                                <input type="file" accept=".csv,text/csv" className="hidden" onChange={handleCsvUpload} />
                            </label>
                            {csvRows.length > 0 && <p className="text-xs text-green-700 mt-2">{csvRows.length} row{csvRows.length !== 1 ? 's' : ''} loaded</p>}
                            {csvError && <p className="text-xs text-red-700 mt-2">{csvError}</p>}
                        </div>

                        <div className="border-2 border-dashed border-gray-300 rounded-lg p-6 text-center hover:border-blue-400 transition-colors">
                            <ImageIcon className="mx-auto mb-2 text-gray-400" size={28} />
                            <p className="text-sm font-medium text-gray-700 mb-1">Image Folder</p>
                            <p className="text-xs text-gray-500 mb-3">ad{'{N}'}-{'{slug}'}-1x1.png / 9x16.png</p>
                            <label className="inline-flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium cursor-pointer hover:bg-blue-700">
                                <UploadCloud size={16} /> Choose Images
                                <input type="file" accept="image/png,image/jpeg" multiple className="hidden" onChange={handleImageUpload} />
                            </label>
                            {Object.keys(imageGroups).length > 0 && (
                                <p className="text-xs text-green-700 mt-2">{Object.keys(imageGroups).length} ad number{Object.keys(imageGroups).length !== 1 ? 's' : ''} matched</p>
                            )}
                        </div>
                    </div>

                    {/* Destination link — shared across the whole batch */}
                    <div className="bg-gray-50 border border-gray-200 rounded-lg p-4 mb-6 text-sm">
                        <strong>Destination link (shared by this batch):</strong>{' '}
                        {creativeData.websiteUrl || <span className="text-red-600">Not set — go back to the Creative step</span>}
                    </div>

                    {/* Review table */}
                    {matchedRows.length > 0 && (
                        <>
                            <div className="overflow-x-auto border border-gray-200 rounded-lg mb-3">
                                <table className="min-w-full text-sm">
                                    <thead className="bg-gray-50">
                                        <tr>
                                            <th className="text-left px-3 py-2 font-semibold text-gray-600">AD #</th>
                                            <th className="text-left px-3 py-2 font-semibold text-gray-600">Headline</th>
                                            <th className="text-left px-3 py-2 font-semibold text-gray-600">1x1</th>
                                            <th className="text-left px-3 py-2 font-semibold text-gray-600">9x16</th>
                                            <th className="text-left px-3 py-2 font-semibold text-gray-600">Status</th>
                                        </tr>
                                    </thead>
                                    <tbody className="divide-y divide-gray-100">
                                        {matchedRows.map((row) => (
                                            <tr key={row.adNumber} className={row.status !== 'ready' ? 'bg-gray-50 opacity-75' : ''}>
                                                <td className="px-3 py-2 font-medium">{row.adNumber}</td>
                                                <td className="px-3 py-2 text-gray-700 max-w-xs truncate">{row.headline || <span className="text-gray-400">—</span>}</td>
                                                <td className="px-3 py-2">
                                                    {row.oneByOnePreviewUrl ? (
                                                        <img src={row.oneByOnePreviewUrl} alt="1x1" className="w-10 h-10 rounded object-cover" />
                                                    ) : (
                                                        <span className="text-gray-400 text-xs">none</span>
                                                    )}
                                                </td>
                                                <td className="px-3 py-2">
                                                    {row.nineBySixteenPreviewUrl ? (
                                                        <img src={row.nineBySixteenPreviewUrl} alt="9x16" className="w-8 h-14 rounded object-cover" />
                                                    ) : (
                                                        <span className="text-gray-400 text-xs">no vertical</span>
                                                    )}
                                                </td>
                                                <td className="px-3 py-2">{statusBadge(row.status)}</td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>

                            <p className="text-sm text-gray-600 mb-2">
                                <strong>{readyRows.length} of {matchedRows.length}</strong> rows ready
                                {missingImageRows.length > 0 && <> — {missingImageRows.length} missing image</>}
                                {missingCopyRows.length > 0 && <> — {missingCopyRows.length} missing copy</>}
                                {invalidCtaRows.length > 0 && <> — {invalidCtaRows.length} invalid CTA</>}
                            </p>

                            {readyRows.length > MAX_ADS_PER_ADSET && (
                                <p className="text-sm text-red-700 mb-6 font-medium">
                                    {readyRows.length} ready ads exceeds Meta's {MAX_ADS_PER_ADSET}-ad-per-ad-set limit — split this batch before submitting.
                                </p>
                            )}
                            {readyRows.length <= MAX_ADS_PER_ADSET && <div className="mb-6" />}
                        </>
                    )}

                    {/* Errors — partial launch failure */}
                    {errors.length > 0 && (
                        <div className="mt-2 space-y-3">
                            <div className="bg-red-50 border border-red-200 rounded-lg p-4">
                                <h3 className="font-semibold text-red-900 mb-2">
                                    {errors.length} ad{errors.length !== 1 ? 's' : ''} failed to create
                                </h3>
                                <ul className="text-sm text-red-800 space-y-1">
                                    {errors.map((error, index) => (
                                        <li key={index}>• {error}</li>
                                    ))}
                                </ul>
                            </div>
                            <div className="bg-amber-50 border border-amber-200 rounded-lg px-4 py-3 text-sm text-amber-800">
                                Any ads that <strong>did</strong> create are live in Meta as <strong>PAUSED</strong> — they won't spend until you activate them in Ads Manager.
                            </div>
                        </div>
                    )}

                    {/* Navigation */}
                    <div className="mt-8 flex justify-between">
                        <button onClick={onBack} className="px-6 py-3 text-gray-600 hover:text-gray-800 font-medium">
                            Back
                        </button>
                        {errors.length > 0 ? (
                            <button
                                onClick={onNext}
                                className="flex items-center gap-2 px-6 py-3 bg-amber-600 text-white rounded-lg font-medium hover:bg-amber-700"
                            >
                                Continue Anyway
                            </button>
                        ) : (
                            <button
                                onClick={handleSubmit}
                                disabled={readyRows.length === 0 || readyRows.length > MAX_ADS_PER_ADSET}
                                className="flex items-center gap-2 px-6 py-3 bg-green-600 text-white rounded-lg font-medium hover:bg-green-700 disabled:bg-gray-300 disabled:cursor-not-allowed"
                            >
                                Create {readyRows.length} Ad{readyRows.length !== 1 ? 's' : ''} on Facebook
                            </button>
                        )}
                    </div>
                </>
            ) : (
                <div className="text-center py-12">
                    {progress.status === 'Complete!' ? (
                        <div className="text-green-500 mx-auto mb-4 text-5xl">✓</div>
                    ) : (
                        <Loader className="animate-spin mx-auto mb-4 text-blue-600" size={48} />
                    )}
                    <h3 className="text-xl font-semibold mb-2">{progress.status}</h3>
                    <div className="w-full max-w-md mx-auto bg-gray-200 rounded-full h-3 mb-2">
                        <div
                            className="bg-blue-600 h-3 rounded-full transition-all duration-300"
                            style={{ width: `${(progress.current / progress.total) * 100}%` }}
                        />
                    </div>
                    <p className="text-gray-600">{progress.current} of {progress.total} ads created</p>
                    {progress.status === 'Complete!' && (
                        <p className="text-sm text-amber-700 mt-3 font-medium">
                            All ads are <strong>PAUSED</strong> in Meta — go to Ads Manager to activate them when ready.
                        </p>
                    )}
                </div>
            )}
        </div>
    );
};

export default BulkMatchImport;
