import React, { useState, useCallback, useMemo, useEffect } from 'react';
import Papa from 'papaparse';
import { useToast } from '../context/ToastContext';
import { useAuth } from '../context/AuthContext';
import { UploadCloud, Loader, FileText, Image as ImageIcon, CheckCircle2, AlertTriangle, XCircle, Pencil } from 'lucide-react';
import { useCampaign } from '../context/CampaignContext';
import { createCompleteAd, createFacebookCampaign, createFacebookAdSet } from '../lib/facebookApi';
import { CTA_OPTIONS, HEADLINE_LIMIT, BODY_LIMIT } from './AdCreativeStep';
import { INTER_REQUEST_DELAY_MS, delay, isRateLimitError } from '../lib/metaRateLimit';
import CreativeEnhancementsPanel from './CreativeEnhancementsPanel';
import {
    buildReconciliationRecord,
    buildReconciliationScope,
    buildReconciliationStorageKey,
    getOrCreateReconciliationLaunchId,
    fingerprintReconciliationPackage,
} from '../lib/reconciliationScope';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1';

// Matches ad{N}-{slug}-{aspect}.{ext} e.g. "ad12-hero-shot-1x1.png"
const FILENAME_PATTERN = /^ad(\d+)-.*-(1x1|9x16)\.(png|jpe?g)$/i;

// Meta hard-caps a single ad set at 50 ads. Above that we block submission
// rather than silently chunking — simpler and safer than auto-splitting.
const MAX_ADS_PER_ADSET = 50;

// Rate-limit spacing, throttle codes and the delay helper are shared with the
// ad-launch loop in BulkAdCreation.jsx — see lib/metaRateLimit.js, so the CODE
// LIST cannot drift between the two paths that write to Meta.
//
// The user-facing throttle message below is still this file's own, not the
// shared rateLimitStopMessage(): that one warns against re-launching because
// BulkAdCreation cannot resume, whereas this importer's rows are driven from a
// CSV the user can trim and re-upload. Different recovery, so different advice
// — deliberate, not drift.
const INTER_ROW_DELAY_MS = INTER_REQUEST_DELAY_MS;

// Match Import also creates dual-placement asset-feed-spec creatives. Reusing
// an existing ad set must meet the same explicit placement contract as the
// Drive manifest path; otherwise Meta can serve the supplied two images into
// placements neither version was made for.
const existingDualPlacementStatus = (targeting = {}, instagramUserId = null) => {
    const platforms = Array.isArray(targeting.publisher_platforms) ? targeting.publisher_platforms : [];
    const facebookPositions = Array.isArray(targeting.facebook_positions) ? targeting.facebook_positions : [];
    const instagramPositions = Array.isArray(targeting.instagram_positions) ? targeting.instagram_positions : [];
    const hasFacebook = platforms.includes('facebook');
    const hasInstagram = platforms.includes('instagram');
    const exactFacebook = facebookPositions.length === 2 && facebookPositions.includes('feed') && facebookPositions.includes('story');
    const exactInstagram = instagramPositions.length === 3 && instagramPositions.includes('stream') && instagramPositions.includes('story') && instagramPositions.includes('reels');
    return (hasFacebook && !hasInstagram && platforms.length === 1 && exactFacebook && instagramPositions.length === 0)
        || (hasFacebook && hasInstagram && platforms.length === 2 && exactFacebook && exactInstagram && instagramUserId)
        ? 'verified'
        : 'unverified';
};

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

function downloadCsvTemplate() {
    const csv = [
        'ad_number,headline,primary_text,cta',
        '1,"Your headline here","Your primary text here",LEARN_MORE',
        '2,"Another headline","Another primary text",GET_QUOTE'
    ].join('\n');
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = 'ad-package-copy-template.csv';
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
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
    const { campaignData, adsetData, creativeData, selectedAdAccount, setLaunchSummary } = useCampaign();

    const [csvRows, setCsvRows] = useState([]); // [{ adNumber, headline, primaryText, cta }]
    const [csvError, setCsvError] = useState('');
    const [imageGroups, setImageGroups] = useState({}); // { [adNumber]: { oneByOne: File, nineBySixteen: File } }
    const [loading, setLoading] = useState(false);
    const [progress, setProgress] = useState({ current: 0, total: 0, status: '' });
    const [errors, setErrors] = useState([]);
    const [requiresReconciliation, setRequiresReconciliation] = useState(false);
    const [reconciliationRecord, setReconciliationRecord] = useState(null);
    const [reconciliationExcludedAdNumbers, setReconciliationExcludedAdNumbers] = useState(() => new Set());
    const [showReconciliationConfirm, setShowReconciliationConfirm] = useState(false);
    const [reconciliationStorageUnavailable, setReconciliationStorageUnavailable] = useState(false);
    const [reconciliationPendingRecords, setReconciliationPendingRecords] = useState([]);
    const [reconciliationAmbiguousRecords, setReconciliationAmbiguousRecords] = useState([]);
    const [creativeEnhancements, setCreativeEnhancements] = useState({});
    // Match Import reads selectedAdAccount/campaignData from shared wizard
    // context rather than owning its own switcher — but the wizard can still
    // navigate back and change either, and without this the enhancement
    // selection from a stale account/campaign would silently carry into a
    // new one with no on-screen indication either way (joel-perspective
    // pre-push review, P2). Same reset precedent, and same cache-key
    // derivation (prefers fbCampaignId, falls back to id then 'new'), that
    // AdCreativeStep.jsx already applies for its own scope changes.
    const campaignCacheId = campaignData?.fbCampaignId || campaignData?.id || 'new';
    useEffect(() => {
        setCreativeEnhancements({});
    }, [selectedAdAccount, campaignCacheId]);

    // Inline edits made in the review table, keyed by adNumber. Kept separate
    // from csvRows so a typo fix never requires re-uploading the CSV — these
    // overrides are layered on top of the parsed row in matchedRows below.
    const [rowEdits, setRowEdits] = useState({}); // { [adNumber]: { headline?, primaryText?, cta? } }
    const [editingCell, setEditingCell] = useState(null); // { adNumber, field } | null
    const [draftValue, setDraftValue] = useState('');

    const startEditingCell = (adNumber, field, currentValue) => {
        setEditingCell({ adNumber, field });
        setDraftValue(currentValue || '');
    };

    const commitEditingCell = () => {
        if (!editingCell) return;
        const { adNumber, field } = editingCell;
        setRowEdits((prev) => ({
            ...prev,
            [adNumber]: { ...prev[adNumber], [field]: draftValue }
        }));
        setEditingCell(null);
        setDraftValue('');
    };

    const cancelEditingCell = () => {
        setEditingCell(null);
        setDraftValue('');
    };

    // CTA select commits immediately on change rather than waiting for blur.
    const commitCtaEdit = (adNumber, value) => {
        setRowEdits((prev) => ({
            ...prev,
            [adNumber]: { ...prev[adNumber], cta: value }
        }));
        setEditingCell(null);
    };

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

                const fields = results.meta?.fields || [];
                if (!fields.includes('ad_number')) {
                    setCsvRows([]);
                    setRowEdits({});
                    setCsvError('CSV must include an ad_number column. Download the template to see the required headers.');
                    return;
                }

                const rows = [];
                const seen = new Set();
                const duplicateAdNumbers = new Set();
                let droppedRows = 0;

                for (const raw of results.data) {
                    const adNumber = normalizeAdNumber(raw.ad_number);
                    if (adNumber === '') {
                        droppedRows++;
                        continue;
                    }

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
                // A fresh CSV load starts with zero inline overrides — otherwise a
                // stale edit either silently masks the new CSV's value for the same
                // AD #, or resurrects as a ghost row (via the rowEdits union in
                // matchedRows) for an AD # that isn't even in the new file.
                setRowEdits({});

                if (duplicateAdNumbers.size > 0) {
                    const list = Array.from(duplicateAdNumbers).sort((a, b) => Number(a) - Number(b));
                    showWarning(`Duplicate CSV row${list.length !== 1 ? 's' : ''} for AD ${list.join(', AD ')} — only the first row for each was kept.`);
                }
                if (droppedRows > 0) {
                    showWarning(`${droppedRows} CSV row${droppedRows !== 1 ? 's' : ''} skipped because ad_number was blank or invalid.`);
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
        const allNumbers = new Set([...Object.keys(csvByNumber), ...Object.keys(imageGroups), ...Object.keys(rowEdits)]);
        const rows = Array.from(allNumbers).map((adNumber) => {
            const copy = csvByNumber[adNumber] || null;
            const images = imageGroups[adNumber] || {};
            const edits = rowEdits[adNumber] || {};

            // Inline edits win over the parsed CSV value for that field.
            const headline = edits.headline !== undefined ? edits.headline : (copy?.headline || '');
            const primaryText = edits.primaryText !== undefined ? edits.primaryText : (copy?.primaryText || '');
            const hasCopy = !!(headline && headline.trim() && primaryText && primaryText.trim());
            const hasOneByOne = !!images.oneByOne;
            const hasNineBySixteen = !!images.nineBySixteen;
            // Same caps AdCreativeStep enforces before allowing Next — applies
            // equally to CSV-sourced copy and inline edits made in this table.
            const overLimit = headline.length > HEADLINE_LIMIT || primaryText.length > BODY_LIMIT;

            const ctaRaw = edits.cta !== undefined ? edits.cta : (copy?.cta ?? '');
            const normalizedCta = normalizeCta(ctaRaw);
            const ctaMissing = normalizedCta === '';
            const ctaValid = CTA_OPTIONS.includes(normalizedCta);

            // Both placements (Feed 1x1 + Stories/Reels 9x16) are required
            // together — a row missing either is NOT ready. Distinguish which
            // is missing so Abel/Joel know exactly what to add per row.
            let status;
            if (!hasCopy) status = 'missing_copy'; // has image(s) but no/incomplete CSV row
            else if (overLimit) status = 'over_limit';
            else if (ctaMissing) status = 'missing_cta';
            else if (!hasOneByOne && !hasNineBySixteen) status = 'missing_both_images';
            else if (!hasOneByOne) status = 'missing_1x1';
            else if (!hasNineBySixteen) status = 'missing_9x16';
            else if (!ctaValid) status = 'invalid_cta';
            else status = 'ready';

            return {
                adNumber,
                headline,
                primaryText,
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
    }, [csvByNumber, imageGroups, rowEdits]);

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
    const reconciliationDraftFingerprint = fingerprintReconciliationPackage({
        campaign: campaignData,
        adset: adsetData,
        package: { readyRows: readyRows.map(row => row.adNumber), destination: creativeData.websiteUrl },
    });
    const reconciliationLaunchId = useMemo(() => getOrCreateReconciliationLaunchId(
        selectedAdAccount?.accountId || selectedAdAccount?.id,
        reconciliationDraftFingerprint,
    ), [selectedAdAccount?.accountId, selectedAdAccount?.id, reconciliationDraftFingerprint]);
    const reconciliationPackageFingerprint = fingerprintReconciliationPackage({
        readyRows: readyRows.map(row => ({
            adNumber: row.adNumber,
            headline: row.headline,
            primaryText: row.primaryText,
            cta: row.cta,
            oneByOne: row.oneByOne ? { name: row.oneByOne.name, size: row.oneByOne.size, lastModified: row.oneByOne.lastModified } : null,
            nineBySixteen: row.nineBySixteen ? { name: row.nineBySixteen.name, size: row.nineBySixteen.size, lastModified: row.nineBySixteen.lastModified } : null,
        })),
        destination: creativeData.websiteUrl,
        pageId: creativeData.pageId,
        instagramId: creativeData.instagramId,
        enhancements: creativeEnhancements,
    });
    const reconciliationScope = buildReconciliationScope({
        campaignData,
        adsetData,
        launchId: reconciliationLaunchId,
    });
    const reconciliationStorageKey = buildReconciliationStorageKey('match', selectedAdAccount?.accountId || selectedAdAccount?.id, reconciliationScope);
    const reconciliationAccountKey = `bulk-match-reconciliation-active:${selectedAdAccount?.accountId || selectedAdAccount?.id || 'none'}`;
    const launchReadyRows = readyRows.filter(row => !reconciliationExcludedAdNumbers.has(row.adNumber));
    const setPersistentReconciliationBlock = (message, createdMetaIds = [], affectedAdNumbers = readyRows.map(row => row.adNumber)) => {
        const record = buildReconciliationRecord({
            scope: reconciliationScope,
            packageFingerprint: reconciliationPackageFingerprint,
            readyAdNumbers: affectedAdNumbers,
            createdMetaIds,
            message,
            campaignId: campaignData?.fbCampaignId || campaignData?.id || null,
            adsetId: adsetData?.fbAdsetId || adsetData?.id || null,
            campaignWasExisting: Boolean(campaignData?.isExisting),
            adsetWasExisting: Boolean(adsetData?.isExisting),
        });
        setRequiresReconciliation(true);
        setReconciliationRecord(record);
        setReconciliationPendingRecords([record]);
        setReconciliationAmbiguousRecords([]);
        try {
            localStorage.setItem(reconciliationStorageKey, JSON.stringify(record));
            const activeRaw = localStorage.getItem(reconciliationAccountKey);
            const active = activeRaw ? JSON.parse(activeRaw) : [];
            const activeRecords = Array.isArray(active) ? active : active?.scope ? [active] : [];
            localStorage.setItem(reconciliationAccountKey, JSON.stringify([
                ...activeRecords.filter(item => item.scope !== reconciliationScope && item.blocked !== false),
                record,
            ]));
        } catch (storageError) {
            console.warn('Could not persist reconciliation block:', storageError);
            setReconciliationStorageUnavailable(true);
        }
    };
    const persistLaunchIntent = () => {
        const record = buildReconciliationRecord({
            scope: reconciliationScope,
            packageFingerprint: reconciliationPackageFingerprint,
            readyAdNumbers: launchReadyRows.map(row => row.adNumber),
            message: 'Launch interrupted before completion. Reconcile this batch before retrying.',
            campaignId: campaignData?.fbCampaignId || campaignData?.id || null,
            adsetId: adsetData?.fbAdsetId || adsetData?.id || null,
            campaignWasExisting: Boolean(campaignData?.isExisting),
            adsetWasExisting: Boolean(adsetData?.isExisting),
            phase: 'in_progress',
        });
        localStorage.setItem(reconciliationStorageKey, JSON.stringify(record));
        const activeRaw = localStorage.getItem(reconciliationAccountKey);
        const active = activeRaw ? JSON.parse(activeRaw) : [];
        const activeRecords = Array.isArray(active) ? active : active?.scope ? [active] : [];
        localStorage.setItem(reconciliationAccountKey, JSON.stringify([
            ...activeRecords.filter(item => item.scope !== reconciliationScope && item.blocked !== false),
            record,
        ]));
    };
    const clearSuccessfulLaunchIntent = () => {
        localStorage.removeItem(reconciliationStorageKey);
        const activeRaw = localStorage.getItem(reconciliationAccountKey);
        const active = activeRaw ? JSON.parse(activeRaw) : [];
        const activeRecords = Array.isArray(active) ? active : active?.scope ? [active] : [];
        const remaining = activeRecords.filter(item => item.blocked !== false && item.scope !== reconciliationScope);
        if (remaining.length > 0) localStorage.setItem(reconciliationAccountKey, JSON.stringify(remaining));
        else localStorage.removeItem(reconciliationAccountKey);
    };
    useEffect(() => {
        try {
            const stored = localStorage.getItem(reconciliationStorageKey);
            const activeRaw = localStorage.getItem(reconciliationAccountKey);
            const active = activeRaw ? JSON.parse(activeRaw) : [];
            const activeRecords = Array.isArray(active) ? active : active?.scope ? [active] : [];
            const parsedStored = stored ? JSON.parse(stored) : null;
            const candidates = [...activeRecords, ...(parsedStored ? [parsedStored] : [])]
                .filter(item => item && item.blocked !== false);
            const pendingRecords = [...new Map(candidates.map(item => [item.scope, item])).values()];
            const parsed = pendingRecords.length === 1 ? pendingRecords[0] : null;
            setReconciliationRecord(parsed);
            setReconciliationPendingRecords(pendingRecords);
            setReconciliationAmbiguousRecords(pendingRecords.length > 1 ? pendingRecords : []);
            setReconciliationStorageUnavailable(false);
            setRequiresReconciliation(Boolean(parsed && parsed.blocked !== false));
            setReconciliationExcludedAdNumbers(new Set());
        } catch (storageError) {
            console.warn('Could not restore reconciliation block:', storageError);
            setRequiresReconciliation(true);
            setReconciliationStorageUnavailable(true);
            setReconciliationPendingRecords([]);
            setReconciliationAmbiguousRecords([]);
        }
    }, [reconciliationAccountKey, reconciliationStorageKey]);

    const clearReconciliationBlock = () => {
        if (reconciliationAmbiguousRecords.length > 0 || !reconciliationRecord) {
            showError('Multiple unresolved batches are locked for this ad account. Resolve each batch from the tab that created it; this screen will not guess which one to clear.');
            setShowReconciliationConfirm(false);
            return;
        }
        const protectedAdNumbers = reconciliationRecord?.readyAdNumbers || [];
        const targetScope = reconciliationRecord?.scope || reconciliationScope;
        const targetStorageKey = buildReconciliationStorageKey('match', selectedAdAccount?.accountId || selectedAdAccount?.id, targetScope);
        const targetCampaignIsExisting = reconciliationRecord.campaignWasExisting ?? campaignData?.isExisting;
        const targetAdsetIsExisting = reconciliationRecord.adsetWasExisting ?? adsetData?.isExisting;
        if (!targetCampaignIsExisting || !targetAdsetIsExisting) {
            setShowReconciliationConfirm(false);
            showError('This partial launch created a new campaign or ad set. Reconcile it in Ads Manager, then start a fresh batch from the previous step.');
            return;
        }
        if (protectedAdNumbers.length === 0) {
            setShowReconciliationConfirm(false);
            showError('No affected AD numbers were recorded. Reconcile this launch in Ads Manager, then start a fresh batch.');
            return;
        }
        try {
            const activeRaw = localStorage.getItem(reconciliationAccountKey);
            const active = activeRaw ? JSON.parse(activeRaw) : [];
            const activeRecords = Array.isArray(active) ? active : active?.scope ? [active] : [];
            const cleared = { blocked: false, scope: targetScope, protectedAdNumbers, clearedAt: new Date().toISOString() };
            localStorage.setItem(targetStorageKey, JSON.stringify(cleared));
            const remaining = activeRecords.filter(item => item.blocked !== false && item.scope !== targetScope);
            if (remaining.length > 0) localStorage.setItem(reconciliationAccountKey, JSON.stringify(remaining));
            else localStorage.removeItem(reconciliationAccountKey);
            setReconciliationExcludedAdNumbers(new Set(protectedAdNumbers));
            setReconciliationRecord(cleared);
            setReconciliationPendingRecords([]);
            setReconciliationAmbiguousRecords([]);
            setRequiresReconciliation(false);
            setShowReconciliationConfirm(false);
            setErrors([]);
            showWarning(`Excluded ADs ${protectedAdNumbers.join(', ')} after reconciliation. The remaining rows are available to launch.`);
        } catch (storageError) {
            console.warn('Could not clear reconciliation block:', storageError);
            setReconciliationStorageUnavailable(true);
            setShowReconciliationConfirm(false);
            showError('The reconciliation lock could not be cleared because browser storage is unavailable.');
        }
    };
    const abandonReconciledFreshBatch = () => {
        try {
            if (reconciliationAmbiguousRecords.length > 0 || !reconciliationRecord) {
                showError('Multiple unresolved batches are locked for this ad account. Resolve each batch from the tab that created it; this screen will not guess which one to clear.');
                return;
            }
            const targetScope = reconciliationRecord?.scope || reconciliationScope;
            const targetStorageKey = buildReconciliationStorageKey('match', selectedAdAccount?.accountId || selectedAdAccount?.id, targetScope);
            localStorage.removeItem(targetStorageKey);
            const activeRaw = localStorage.getItem(reconciliationAccountKey);
            const active = activeRaw ? JSON.parse(activeRaw) : [];
            const activeRecords = Array.isArray(active) ? active : active?.scope ? [active] : [];
            const remaining = activeRecords.filter(item => item.blocked !== false && item.scope !== targetScope);
            if (remaining.length > 0) localStorage.setItem(reconciliationAccountKey, JSON.stringify(remaining));
            else localStorage.removeItem(reconciliationAccountKey);
            setRequiresReconciliation(false);
            setReconciliationRecord(null);
            setReconciliationPendingRecords([]);
            setReconciliationAmbiguousRecords([]);
            setShowReconciliationConfirm(false);
            onBack();
        } catch (storageError) {
            console.warn('Could not clear fresh-batch reconciliation lock:', storageError);
            showError('The reconciliation lock could not be cleared because browser storage is unavailable.');
        }
    };
    const missing1x1Rows = matchedRows.filter((r) => r.status === 'missing_1x1');
    const missing9x16Rows = matchedRows.filter((r) => r.status === 'missing_9x16');
    const missingBothImagesRows = matchedRows.filter((r) => r.status === 'missing_both_images');
    const missingCopyRows = matchedRows.filter((r) => r.status === 'missing_copy');
    const invalidCtaRows = matchedRows.filter((r) => r.status === 'invalid_cta');
    const missingCtaRows = matchedRows.filter((r) => r.status === 'missing_cta');
    const overLimitRows = matchedRows.filter((r) => r.status === 'over_limit');

    // Match Import owns a different set of counts from standard combinations:
    // image/copy readiness comes from the CSV + filename join, not the shared
    // creative arrays used by AdCreativeStep. Publish those counts to the
    // persistent rail so it cannot retain standard-mode values after switching
    // modes or navigating Back/Next.
    useEffect(() => {
        // Combos mode uses "Warnings" for ads that still launch with a caveat,
        // and "Excluded" for ads that won't be submitted. Non-ready rows here
        // never reach handleSubmit (only readyRows do), so by that same
        // vocabulary they're excluded, not warned — labeling them as warnings
        // would read to Joel as "still launches" when it won't.
        const excludedCount = matchedRows.filter(row => row.status !== 'ready').length;
        setLaunchSummary(prev => ({
            ...prev,
            creativeCount: Object.keys(imageGroups).length,
            headlineCount: matchedRows.filter(row => row.headline.trim()).length,
            bodyCount: matchedRows.filter(row => row.primaryText.trim()).length,
            totalAds: readyRows.length,
            warningCount: 0,
            readyCount: readyRows.length,
            excludedCount,
        }));
    }, [imageGroups, matchedRows, readyRows.length, setLaunchSummary]);

    const handleSubmit = async () => {
        try {
            const stored = localStorage.getItem(reconciliationStorageKey);
            const activeRaw = localStorage.getItem(reconciliationAccountKey);
            const active = activeRaw ? JSON.parse(activeRaw) : [];
            const activeRecords = Array.isArray(active) ? active : active?.scope ? [active] : [];
            const parsedStored = stored ? JSON.parse(stored) : null;
            if ((parsedStored && parsedStored.blocked !== false) || activeRecords.some(item => item.blocked !== false)) {
                setRequiresReconciliation(true);
                showError('This ad account has an unresolved Meta write. Reconcile that account-wide lock in Ads Manager before creating anything else.');
                return;
            }
        } catch (storageError) {
            console.warn('Could not read reconciliation block:', storageError);
        }
        if (launchReadyRows.length === 0) {
            showWarning('No rows are ready to create — match each CSV row to BOTH a 1x1 and a 9x16 image (both placements are required)');
            return;
        }
        if (launchReadyRows.length > MAX_ADS_PER_ADSET) {
            showError(`This batch has ${launchReadyRows.length} launchable ads — Meta limits a single ad set to ${MAX_ADS_PER_ADSET} ads. Split the batch into groups of ${MAX_ADS_PER_ADSET} or fewer (e.g. by AD # range) and run each separately.`);
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
        // This importer always creates Feed + Stories/Instagram placement
        // targeting. Stop before the first Meta write if the Page cannot
        // supply the Instagram identity required by object_story_spec.
        if (!creativeData.instagramId) {
            showError('The selected Facebook Page has no linked Instagram identity available. Choose a Page connected to Instagram before launching paired creatives.');
            return;
        }
        if (adsetData.isExisting && existingDualPlacementStatus(adsetData.targeting, creativeData.instagramId) === 'unverified') {
            showError('This existing ad set is not verified for exactly Facebook Feed + Stories (and Instagram Stream, Stories, and Reels when Instagram is enabled). Go back and choose a placement-compatible ad set before launching paired creatives.');
            return;
        }

        try {
            // Persist before the first Meta mutation. If the tab dies between
            // the mutation and the error handler, the account fallback still
            // blocks a blind replay after reload.
            persistLaunchIntent();
        } catch (storageError) {
            console.warn('Could not persist launch intent:', storageError);
            setReconciliationStorageUnavailable(true);
            showError('Browser storage is unavailable, so this launch is locked for safety. Re-enable storage before continuing.');
            return;
        }
        setLoading(true);
        setErrors([]);
        setRequiresReconciliation(false);
        setProgress({ current: 0, total: launchReadyRows.length, status: 'Starting...' });

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
                // A failed local mirror makes the launch state incomplete even
                // when the campaign was selected rather than newly created.
                // Stop for reconciliation; never expose a blind retry.
                err.metaMutationStarted = true;
                throw err;
            }

            // ── Step 2: Ad Set — single ad set, placement-locked to exactly the two
            // placements every creative in this batch customizes (Feed + Story).
            // Every ad here uses the dual-placement asset_feed_spec creative (see
            // create_creative's asset_customization_rules), so leaving targeting at
            // its default (broad publisher_platforms / Advantage+ placements) would
            // let Meta serve these into placements the creative doesn't cover
            // (Marketplace, Explore, Right Hand Column, etc.) — the exact "wrong
            // image in wrong placement" failure this feature exists to prevent.
            // Mirrors the feedTargeting/storiesTargeting overlay pattern in
            // BulkAdCreation.jsx, collapsed to one ad set since both placements
            // ship together on every ad here (not split feed-only/stories-only).
            const dualPlacementTargeting = {
                ...adsetData.targeting,
                publisher_platforms: ['facebook', 'instagram'],
                facebook_positions: ['feed', 'story'],
                instagram_positions: ['stream', 'story', 'reels']
            };

            let fbAdsetId = adsetData.fbAdsetId;
            let localAdsetId = adsetData.id;
            if (!adsetData.isExisting) {
                setProgress((prev) => ({ ...prev, status: 'Creating ad set on Facebook...' }));
                const adsetPayload = {
                    ...adsetData,
                    ...(campaignData.budgetType === 'CBO' && {
                        bidStrategy: campaignData.bidStrategy,
                        bidAmount: campaignData.bidAmount
                    }),
                    specialAdCategories: campaignData.specialAdCategories || [],
                    targeting: dualPlacementTargeting
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
                const savedAdset = await saveAdSetRes.json().catch(() => ({}));
                // Existing selections use the Meta ID in wizard state, while
                // the local ad mirror requires the FacebookAdSet UUID FK.
                localAdsetId = savedAdset.id || localAdsetId;
            } catch (err) {
                console.error('Error saving ad set locally:', err);
                err.metaMutationStarted = true;
                throw err;
            }

            // ── Step 3: Ads — loop only "Ready" rows ────────────────────────────
            const createdAds = [];
            let failedCount = 0;
            let rateLimited = false;
            let reconciliationStop = false;
            const reconciledAdNumbers = [];
            for (let i = 0; i < launchReadyRows.length; i++) {
                if (i > 0) await delay(INTER_ROW_DELAY_MS); // unconditional spacing between Meta calls

                const row = launchReadyRows[i];
                setProgress({
                    current: i + 1,
                    total: launchReadyRows.length,
                    status: `Creating AD ${row.adNumber} (${i + 1} of ${launchReadyRows.length})...`
                });

                let metaCreatedAdId = null;
                try {
                    // Upload the primary 1x1 to get a durable, server-reachable URL
                    // BEFORE creating the ad — never persist a blob: URL, which dies
                    // the moment this tab closes.
                    const rawImageUrl = await uploadFileToServer(row.oneByOne, authFetch);
                    const imageUrl = toAbsoluteUploadUrl(rawImageUrl);

                    // Upload the 9x16 secondary asset to get a durable, server-reachable
                    // URL — same treatment as the 1x1 above. Required (readyRows only
                    // contains rows with both images matched), and this same URL is
                    // what createCompleteAd uploads to Meta for the Stories/Reels
                    // placement, so the DB-persisted value below always matches what
                    // Meta actually received.
                    const rawSecondaryImageUrl = await uploadFileToServer(row.nineBySixteen, authFetch);
                    const secondaryImageUrl = toAbsoluteUploadUrl(rawSecondaryImageUrl);

                    const rowCreativeData = {
                        ...creativeData,
                        mediaType: 'image',
                        imageUrl,
                        secondaryImageUrl,
                        videoUrl: undefined,
                        headlines: [row.headline],
                        bodies: [row.primaryText],
                        cta: row.cta,
                        creative_enhancements: creativeEnhancements
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
                    metaCreatedAdId = result.adId;

                    const saveAdRes = await authFetch(`${API_URL}/facebook/ads/save`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            id: adData.id,
                            adsetId: localAdsetId,
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
                    failedCount++;

                    if (metaCreatedAdId) {
                        reconciliationStop = true;
                        reconciledAdNumbers.push(row.adNumber);
                        setPersistentReconciliationBlock(error.message, [metaCreatedAdId], [row.adNumber]);
                        setErrors((prev) => [...prev, `AD ${row.adNumber} was created in Meta as ${metaCreatedAdId}, but its local record failed to save: ${error.message}. Do not retry this batch; reconcile the ad in Ads Manager first.`]);
                        break;
                    }

                    // The client marks errors after a Meta mutation (for
                    // example a timeout after create-ad) so this row may
                    // already exist even without an ID response. Continuing
                    // would make a retryable-looking partial batch that can
                    // duplicate an ad. Stop and require reconciliation.
                    if (error.metaMutationStarted) {
                        reconciliationStop = true;
                        reconciledAdNumbers.push(row.adNumber);
                        setPersistentReconciliationBlock(error.message, [], [row.adNumber]);
                        setErrors((prev) => [...prev, `Meta may have created AD ${row.adNumber}, but its result could not be confirmed: ${error.message}. Do not retry this batch; reconcile in Ads Manager first.`]);
                        break;
                    }

                    setErrors((prev) => [...prev, `Failed to create AD ${row.adNumber}: ${error.message}`]);

                    if (isRateLimitError(error)) {
                        rateLimited = true;
                        const remaining = launchReadyRows.length - (i + 1);
                        setErrors((prev) => [...prev, `Meta rate-limited this account — stopping batch. ${createdAds.length} of ${launchReadyRows.length} ads created. ${remaining} row${remaining !== 1 ? 's' : ''} not attempted — wait a few minutes and retry.`]);
                        break;
                    }
                }
            }

            if (failedCount === 0) {
                clearSuccessfulLaunchIntent();
                setProgress({ current: launchReadyRows.length, total: launchReadyRows.length, status: 'Complete!' });
                setTimeout(() => { onNext(); }, 1500);
            } else {
                if (createdAds.length > 0 || !campaignData.isExisting || !adsetData.isExisting) {
                    setPersistentReconciliationBlock(
                        'This batch partially completed. Reconcile the created rows before starting another batch.',
                        createdAds.map(ad => ad.fbAdId),
                        [...new Set([...createdAds.map(ad => ad.adNumber), ...reconciledAdNumbers])],
                    );
                }
                setProgress({
                    current: launchReadyRows.length,
                    total: launchReadyRows.length,
                    status: rateLimited
                        ? `Stopped — Meta rate-limited this account (${createdAds.length} of ${launchReadyRows.length} created)`
                        : reconciliationStop
                            ? `Stopped — ${createdAds.length} fully saved; one Meta ad needs local reconciliation`
                        : `${createdAds.length} of ${launchReadyRows.length} ads created`
                });
                setLoading(false);
            }
        } catch (error) {
            console.error('Error in bulk match import:', error);
            if (error.metaMutationStarted || !campaignData.isExisting || !adsetData.isExisting) {
                setPersistentReconciliationBlock(error.message, [], readyRows.map(row => row.adNumber));
                setErrors((prev) => [...prev, `Meta may have created a campaign or ad set, but its result could not be confirmed: ${error.message}. Do not retry this batch; reconcile in Ads Manager first.`]);
                setProgress((prev) => ({ ...prev, status: 'Stopped — Meta objects need reconciliation' }));
                setLoading(false);
                return;
            }
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
        if (status === 'missing_1x1') {
            return (
                <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full font-medium bg-amber-100 text-amber-700">
                    <AlertTriangle size={12} /> Missing 1x1
                </span>
            );
        }
        if (status === 'missing_9x16') {
            return (
                <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full font-medium bg-amber-100 text-amber-700">
                    <AlertTriangle size={12} /> Missing 9x16
                </span>
            );
        }
        if (status === 'missing_both_images') {
            return (
                <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full font-medium bg-amber-100 text-amber-700">
                    <AlertTriangle size={12} /> Missing 1x1 &amp; 9x16
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
        if (status === 'missing_cta') {
            return (
                <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full font-medium bg-amber-100 text-amber-700">
                    <AlertTriangle size={12} /> CTA required
                </span>
            );
        }
        if (status === 'over_limit') {
            return (
                <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full font-medium bg-red-100 text-red-700">
                    <XCircle size={12} /> Over character limit
                </span>
            );
        }
        return (
            <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full font-medium bg-red-100 text-red-700">
                <XCircle size={12} /> Missing copy
            </span>
        );
    };

    const reconciliationPendingSummary = reconciliationPendingRecords.map(record => {
        const ads = (record.readyAdNumbers || []).join(', ') || 'unknown ADs';
        const meta = (record.createdMetaIds || []).join(', ') || 'Meta ID pending';
        const scope = `${record.campaignId || 'campaign unknown'} / ${record.adsetId || 'ad set unknown'}`;
        const when = record.recordedAt ? new Date(record.recordedAt).toLocaleString() : 'time unknown';
        return `${ads} (Meta: ${meta}; ${scope}; ${when})`;
    }).join(' • ');
    const canResetReconciliation = reconciliationPendingRecords.length === 1
        && reconciliationRecord
        && (reconciliationRecord.campaignWasExisting ?? campaignData?.isExisting)
        && (reconciliationRecord.adsetWasExisting ?? adsetData?.isExisting);

    return (
        <div>
            <h2 className="text-2xl font-bold mb-2">Match by Naming Convention</h2>
            {reconciliationPendingRecords.length > 0 && (
                <div className="mb-5 rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900">
                    <strong>This ad account has an unresolved launch.</strong> Reconcile it before creating new ads.
                    <div className="mt-1 text-xs">Affected rows: {reconciliationPendingSummary}</div>
                    {reconciliationAmbiguousRecords.length > 1 && <div className="mt-1 text-xs font-semibold">Multiple pending batches are present. Resolve each from the tab that created it; this screen will not guess.</div>}
                </div>
            )}
            <p className="text-gray-600 mb-6">
                Upload a copy CSV and an image folder. Rows are matched by ad number (<code className="bg-gray-100 px-1 rounded">AD 1</code> ↔{' '}
                <code className="bg-gray-100 px-1 rounded">ad1-slug-1x1.png</code>). Both a <strong>1x1</strong> (Feed) and a <strong>9x16</strong> (Story)
                image are required per ad — Meta publishes both placements together with the same copy. Only <strong>Ready</strong> rows are created.
            </p>
            <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2 mb-6">
                <strong>9x16 is now required for every ad</strong> (previously optional) — both images must be present for a row to be Ready.
                Re-running a batch that only had 1x1 images before will show new "Missing 9x16" rows; that's expected, not a bug.
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
                            <div className="flex flex-wrap items-center justify-center gap-2">
                                <label className="inline-flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium cursor-pointer hover:bg-blue-700">
                                    <UploadCloud size={16} /> Choose CSV
                                    <input type="file" accept=".csv,text/csv" className="hidden" onChange={handleCsvUpload} />
                                </label>
                                <button
                                    type="button"
                                    onClick={downloadCsvTemplate}
                                    className="inline-flex items-center gap-2 px-3 py-2 border border-gray-300 text-gray-700 rounded-lg text-sm font-medium hover:bg-gray-50"
                                >
                                    <FileText size={16} /> Download template
                                </button>
                            </div>
                            <p className="text-xs text-amber-700 mt-3">Maximum {MAX_ADS_PER_ADSET} ready ads per ad set.</p>
                            {csvRows.length > 0 && <p className="text-xs text-green-700 mt-2">{csvRows.length} row{csvRows.length !== 1 ? 's' : ''} loaded</p>}
                            {csvError && <p className="text-xs text-red-700 mt-2">{csvError}</p>}
                        </div>

                        <div className="border-2 border-dashed border-gray-300 rounded-lg p-6 text-center hover:border-blue-400 transition-colors">
                            <ImageIcon className="mx-auto mb-2 text-gray-400" size={28} />
                            <p className="text-sm font-medium text-gray-700 mb-1">Image Folder</p>
                            <p className="text-xs text-gray-500 mb-3">ad{'{N}'}-{'{slug}'}-1x1.png / 9x16.png — both required per ad</p>
                            <label className="inline-flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium cursor-pointer hover:bg-blue-700">
                                <UploadCloud size={16} /> Choose Images
                                <input type="file" accept="image/png,image/jpeg" multiple className="hidden" onChange={handleImageUpload} />
                            </label>
                            {Object.keys(imageGroups).length > 0 && (
                                <div className="mt-2 flex items-center justify-center gap-2">
                                    <p className="text-xs text-green-700">{Object.keys(imageGroups).length} ad number{Object.keys(imageGroups).length !== 1 ? 's' : ''} matched</p>
                                    <button
                                        type="button"
                                        onClick={() => {
                                            setImageGroups({});
                                            showWarning('Matched images cleared. Upload the intended image set before continuing.');
                                        }}
                                        className="text-xs text-gray-600 underline hover:text-gray-900"
                                    >
                                        Clear matches
                                    </button>
                                </div>
                            )}
                        </div>
                    </div>

                    {/* Destination link — shared across the whole batch */}
                    <div className="bg-gray-50 border border-gray-200 rounded-lg p-4 mb-6 text-sm">
                        <strong>Destination link (shared by this batch):</strong>{' '}
                        {creativeData.websiteUrl || <span className="text-red-600">Not set — go back to the Creative step</span>}
                    </div>

                    <CreativeEnhancementsPanel value={creativeEnhancements} onChange={setCreativeEnhancements} />

                    {/* Review table */}
                    {matchedRows.length > 0 && (
                        <>
                            <p className="text-xs text-gray-500 mb-2 flex items-center gap-1">
                                <Pencil size={12} className="text-gray-400" />
                                Click any headline, primary text, or CTA below to fix it directly — no need to re-upload the CSV.
                            </p>
                            <div className="overflow-x-auto border border-gray-200 rounded-lg mb-3">
                                <table className="min-w-full text-sm">
                                    <thead className="bg-gray-50">
                                        <tr>
                                            <th className="text-left px-3 py-2 font-semibold text-gray-600">AD #</th>
                                            <th className="text-left px-3 py-2 font-semibold text-gray-600">Headline</th>
                                            <th className="text-left px-3 py-2 font-semibold text-gray-600">Primary Text</th>
                                            <th className="text-left px-3 py-2 font-semibold text-gray-600">CTA</th>
                                            <th className="text-left px-3 py-2 font-semibold text-gray-600">1x1</th>
                                            <th className="text-left px-3 py-2 font-semibold text-gray-600">9x16</th>
                                            <th className="text-left px-3 py-2 font-semibold text-gray-600">Status</th>
                                        </tr>
                                    </thead>
                                    <tbody className="divide-y divide-gray-100">
                                        {matchedRows.map((row) => {
                                            const isEditingHeadline = editingCell?.adNumber === row.adNumber && editingCell.field === 'headline';
                                            const isEditingPrimaryText = editingCell?.adNumber === row.adNumber && editingCell.field === 'primaryText';
                                            const isEditingCta = editingCell?.adNumber === row.adNumber && editingCell.field === 'cta';
                                            const primaryTextPreview = row.primaryText
                                                ? (row.primaryText.length > 60 ? `${row.primaryText.slice(0, 60)}…` : row.primaryText)
                                                : '';

                                            return (
                                                <tr key={row.adNumber} className={row.status !== 'ready' ? 'bg-gray-50 opacity-75' : ''}>
                                                    <td className="px-3 py-2 font-medium">{row.adNumber}</td>
                                                    <td className="px-3 py-2 text-gray-700 max-w-xs">
                                                        {isEditingHeadline ? (
                                                            <div>
                                                                <input
                                                                    type="text"
                                                                    autoFocus
                                                                    value={draftValue}
                                                                    onChange={(e) => setDraftValue(e.target.value)}
                                                                    onBlur={commitEditingCell}
                                                                    onKeyDown={(e) => {
                                                                        if (e.key === 'Enter') commitEditingCell();
                                                                        if (e.key === 'Escape') cancelEditingCell();
                                                                    }}
                                                                    className="w-full px-2 py-1 border border-blue-400 rounded focus:outline-none focus:ring-1 focus:ring-blue-400"
                                                                />
                                                                <span className={`text-xs ${draftValue.length > HEADLINE_LIMIT ? 'text-red-600 font-semibold' : 'text-gray-400'}`}>
                                                                    {draftValue.length} / {HEADLINE_LIMIT}
                                                                </span>
                                                            </div>
                                                        ) : (
                                                            <button
                                                                type="button"
                                                                onClick={() => startEditingCell(row.adNumber, 'headline', row.headline)}
                                                                className="w-full flex items-center gap-1 text-left truncate hover:bg-blue-50 rounded px-1 -mx-1 border-b border-dotted border-gray-300"
                                                                title="Click to edit headline"
                                                            >
                                                                <span className="truncate">{row.headline || <span className="text-gray-400">—</span>}</span>
                                                                <Pencil size={11} className="text-gray-400 shrink-0" />
                                                            </button>
                                                        )}
                                                    </td>
                                                    <td className="px-3 py-2 text-gray-700 max-w-sm">
                                                        {isEditingPrimaryText ? (
                                                            <div>
                                                                <textarea
                                                                    autoFocus
                                                                    rows={3}
                                                                    value={draftValue}
                                                                    onChange={(e) => setDraftValue(e.target.value)}
                                                                    onBlur={commitEditingCell}
                                                                    onKeyDown={(e) => {
                                                                        // Enter alone still adds a newline in a textarea — only commit on Cmd/Ctrl+Enter, mirroring the "Enter to commit" shortcut without blocking multi-line input.
                                                                        if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) commitEditingCell();
                                                                        if (e.key === 'Escape') cancelEditingCell();
                                                                    }}
                                                                    className="w-full px-2 py-1 border border-blue-400 rounded focus:outline-none focus:ring-1 focus:ring-blue-400"
                                                                />
                                                                <span className={`text-xs ${draftValue.length > BODY_LIMIT ? 'text-red-600 font-semibold' : 'text-gray-400'}`}>
                                                                    {draftValue.length} / {BODY_LIMIT}
                                                                </span>
                                                            </div>
                                                        ) : (
                                                            <button
                                                                type="button"
                                                                onClick={() => startEditingCell(row.adNumber, 'primaryText', row.primaryText)}
                                                                className="w-full flex items-center gap-1 text-left truncate hover:bg-blue-50 rounded px-1 -mx-1 border-b border-dotted border-gray-300"
                                                                title={row.primaryText || 'Click to edit primary text'}
                                                            >
                                                                <span className="truncate">{primaryTextPreview || <span className="text-gray-400">—</span>}</span>
                                                                <Pencil size={11} className="text-gray-400 shrink-0" />
                                                            </button>
                                                        )}
                                                    </td>
                                                    <td className="px-3 py-2">
                                                        {isEditingCta ? (
                                                            <select
                                                                autoFocus
                                                                value={row.cta}
                                                                onChange={(e) => commitCtaEdit(row.adNumber, e.target.value)}
                                                                onBlur={cancelEditingCell}
                                                                className="px-2 py-1 border border-blue-400 rounded focus:outline-none focus:ring-1 focus:ring-blue-400"
                                                            >
                                                                <option value="">Select CTA</option>
                                                                {CTA_OPTIONS.map((cta) => (
                                                                    <option key={cta} value={cta}>{cta.replace(/_/g, ' ')}</option>
                                                                ))}
                                                            </select>
                                                        ) : (
                                                            <button
                                                                type="button"
                                                                onClick={() => setEditingCell({ adNumber: row.adNumber, field: 'cta' })}
                                                                className="flex items-center gap-1 hover:bg-blue-50 rounded px-1 -mx-1 border-b border-dotted border-gray-300"
                                                                title="Click to change CTA"
                                                            >
                                                                {row.cta ? row.cta.replace(/_/g, ' ') : 'Select CTA'}
                                                                <Pencil size={11} className="text-gray-400 shrink-0" />
                                                            </button>
                                                        )}
                                                    </td>
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
                                            );
                                        })}
                                    </tbody>
                                </table>
                            </div>

                            <p className="text-sm text-gray-600 mb-2">
                                <strong>{readyRows.length} of {matchedRows.length}</strong> rows ready
                                {missing1x1Rows.length > 0 && <> — {missing1x1Rows.length} missing 1x1</>}
                                {missing9x16Rows.length > 0 && <> — {missing9x16Rows.length} missing 9x16</>}
                                {missingBothImagesRows.length > 0 && <> — {missingBothImagesRows.length} missing both images</>}
                                {missingCopyRows.length > 0 && <> — {missingCopyRows.length} missing copy</>}
                                {missingCtaRows.length > 0 && <> — {missingCtaRows.length} missing CTA</>}
                                {invalidCtaRows.length > 0 && <> — {invalidCtaRows.length} invalid CTA</>}
                                {overLimitRows.length > 0 && <> — {overLimitRows.length} over character limit</>}
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
                        {requiresReconciliation ? (
                            <div className="flex flex-wrap items-center justify-end gap-3 text-right">
                                <span className="max-w-md text-sm font-medium text-amber-800">
                                    {reconciliationAmbiguousRecords.length > 1
                                        ? 'Multiple unresolved batches are locked for this ad account. Resolve each from the tab that created it.'
                                        : `This partial batch is locked after Meta writes. Reconcile ${reconciliationPendingSummary || 'the affected rows'} in Ads Manager.`}
                                </span>
                                {canResetReconciliation ? (
                                    <button type="button" onClick={() => setShowReconciliationConfirm(true)} className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-xs font-semibold text-amber-900 hover:bg-amber-100">
                                        Reset and exclude affected ADs
                                    </button>
                                ) : reconciliationAmbiguousRecords.length === 0 && reconciliationRecord ? (
                                    <button type="button" onClick={abandonReconciledFreshBatch} className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-xs font-semibold text-amber-900 hover:bg-amber-100">
                                        Reconciled — start fresh batch
                                    </button>
                                ) : null}
                            </div>
                        ) : errors.length > 0 ? (
                            <span className="max-w-md text-right text-sm font-medium text-amber-800">Review the failed rows in Ads Manager before starting another batch. This importer will not advance a partial batch to the success screen.</span>
                        ) : (
                            <button
                                onClick={handleSubmit}
                                disabled={launchReadyRows.length === 0 || launchReadyRows.length > MAX_ADS_PER_ADSET}
                                className="flex items-center gap-2 px-6 py-3 bg-green-600 text-white rounded-lg font-medium hover:bg-green-700 disabled:bg-gray-300 disabled:cursor-not-allowed"
                            >
                                Create {launchReadyRows.length} Ad{launchReadyRows.length !== 1 ? 's' : ''} on Facebook
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
            {showReconciliationConfirm && (
                <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/40 px-4 backdrop-blur-sm" role="dialog" aria-modal="true" aria-labelledby="match-reconciliation-confirm-title">
                    <div className="w-full max-w-md rounded-2xl bg-white p-6 shadow-xl">
                        <h2 id="match-reconciliation-confirm-title" className="text-lg font-bold text-gray-900">Reset and exclude affected ADs?</h2>
                        <p className="mt-2 text-sm leading-6 text-gray-600">Confirm that you checked Ads Manager. ADs {reconciliationRecord?.readyAdNumbers?.join(', ') || 'in this batch'} with Meta IDs {reconciliationRecord?.createdMetaIds?.join(', ') || 'not captured'} may already exist in Meta and will be excluded from the next launch. Double-check the campaign and ad set before excluding.</p>
                        {reconciliationRecord?.scope !== reconciliationScope && (
                            <p className="mt-2 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-xs font-semibold text-amber-900">We could not confirm this is the batch currently on screen after the refresh. Double-check the campaign, ad set, AD numbers, and Meta IDs in Ads Manager before excluding.</p>
                        )}
                        <div className="mt-5 flex gap-3">
                            <button type="button" onClick={() => setShowReconciliationConfirm(false)} className="flex-1 rounded-lg border border-gray-200 px-4 py-2.5 font-medium text-gray-700 hover:bg-gray-50">Cancel</button>
                            <button type="button" onClick={clearReconciliationBlock} className="flex-1 rounded-lg bg-amber-600 px-4 py-2.5 font-semibold text-white hover:bg-amber-700">Reset and exclude</button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
};

export default BulkMatchImport;
