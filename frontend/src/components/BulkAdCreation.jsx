import { useToast } from '../context/ToastContext';
import { useAuth } from '../context/AuthContext';
import React, { useState } from 'react';
import { ChevronRight, Loader, Film, Image, X, Pencil } from 'lucide-react';
import { useCampaign } from '../context/CampaignContext';
import { createCompleteAd, createFacebookCampaign, createFacebookAdSet, getRateLimitUsage } from '../lib/facebookApi';
import {
    BULK_LAUNCH_BATCH_COOLDOWN_MS,
    BULK_LAUNCH_BATCH_SIZE,
    INTER_REQUEST_DELAY_MS,
    USAGE_WARN_THRESHOLD,
    delay,
    isRateLimitError,
    peakUsagePercent,
    rateLimitStopMessage,
} from '../lib/metaRateLimit';
import { safeLocalStorageGet, safeLocalStorageSet } from '../lib/safeLocalStorage';
import { resolveNamingTemplate } from '../lib/namingTemplates';
import NamingTemplateField from './NamingTemplateField';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1';

// Best-effort domain for the preview card's link strip — falls back to the raw
// string rather than hiding the field entirely if the URL doesn't parse (e.g.
// still mid-edit in a prior step).
const displayDomain = (url) => {
    if (!url) return '';
    try {
        return new URL(url).hostname.replace(/^www\./, '');
    } catch {
        return url;
    }
};

// The API only accepts absolute http(s) destinations. Validate this in the
// Review step too: a row's URL can be edited after the Creative-step check,
// and image upload must never be the first time an invalid URL is discovered.
const isValidDestinationUrl = (value) => {
    try {
        const parsed = new URL(String(value || '').trim());
        return parsed.protocol === 'http:' || parsed.protocol === 'https:';
    } catch {
        return false;
    }
};

const formatNamingDate = () => new Date().toLocaleDateString('en-US', { month: 'short', day: 'numeric' });

// 'LEARN_MORE' -> 'Learn More' — same values BulkAdCreation already sends to Meta
// (AdCreativeStep.jsx's CTA_OPTIONS), just title-cased for a native-looking button.
const formatCtaLabel = (cta) => (cta || 'LEARN_MORE')
    .split('_')
    .map(word => word.charAt(0) + word.slice(1).toLowerCase())
    .join(' ');

// Keep the final review gate aligned with the Creative step. Drive metadata is
// external input, so a row cannot be "Ready" just because its body/headline/
// URL are present while its CTA would be rejected (or silently defaulted) by
// Meta at creation time.
const META_CTA_OPTIONS = new Set([
    'LEARN_MORE',
    'SHOP_NOW',
    'SIGN_UP',
    'CONTACT_US',
    'DOWNLOAD',
    'BOOK_NOW',
    'BUY_TICKETS',
    'GET_QUOTE',
    'GET_STARTED',
    'APPLY_NOW',
    'DONATE_NOW',
]);

const isValidMetaCta = (value) => META_CTA_OPTIONS.has(String(value || '').trim());

// A dual-placement creative has only two supplied image variants. When it is
// added to an existing ad set, Meta will retain that ad set's targeting; we
// cannot safely assume Stories/Reels are enabled or that unsupported placements
// are excluded. New ad sets are placement-locked at creation time below, while
// existing ad sets must prove the same contract before this launch proceeds.
const existingDualPlacementStatus = (targeting = {}, instagramUserId = null) => {
    const platforms = Array.isArray(targeting.publisher_platforms) ? targeting.publisher_platforms : [];
    const facebookPositions = Array.isArray(targeting.facebook_positions) ? targeting.facebook_positions : [];
    const instagramPositions = Array.isArray(targeting.instagram_positions) ? targeting.instagram_positions : [];
    const hasFacebook = platforms.includes('facebook');
    const hasInstagram = platforms.includes('instagram');
    const facebookOnly = hasFacebook && !hasInstagram && platforms.length === 1;
    const exactFacebook = facebookPositions.length === 2
        && facebookPositions.includes('feed')
        && facebookPositions.includes('story');
    const exactInstagram = instagramPositions.length === 3
        && instagramPositions.includes('stream')
        && instagramPositions.includes('story')
        && instagramPositions.includes('reels');
    if (facebookOnly && exactFacebook && instagramPositions.length === 0) return 'verified-facebook-only';
    if (hasFacebook && hasInstagram && platforms.length === 2 && exactFacebook && exactInstagram && instagramUserId) return 'verified';
    return 'unverified';
};

// Matches the live commercial convention already in Ads Manager:
// `RHO v2 - BARBER SHOPS | FRESH CREATIVE - CAPI`. Keep an existing `- CAPI`
// trailer at the end, and insert the Drive category before the creative label
// so a 100-ad-set batch stays legible in Meta instead of becoming a filename
// dump with no business grouping.
const buildPerMediaAdsetName = (baseName, creative, index) => {
    const base = (baseName || 'Ad Set').trim();
    const capiMatch = base.match(/\s*-\s*CAPI\s*$/i);
    const stem = capiMatch ? base.slice(0, capiMatch.index).trim() : base;
    const suffix = capiMatch ? ' - CAPI' : '';
    const category = creative?.category?.trim();
    const mediaLabel = creative?.name ? `${creative.name} (${index + 1})` : `Creative ${index + 1}`;
    const categoryAlreadyNamed = category && stem.trim().toLowerCase().endsWith(category.toLowerCase());
    const namedStem = category && !categoryAlreadyNamed ? `${stem} - ${category}` : stem;
    return category ? `${namedStem} | ${mediaLabel}${suffix}` : `${namedStem} - ${mediaLabel}${suffix}`;
};

const BulkAdCreation = ({ onNext, onBack }) => {
    const { showWarning, showError, showSuccess } = useToast();
    const { authFetch } = useAuth();
    const { campaignData, adsetData, creativeData, adsData, setAdsData, selectedAdAccount, setLaunchSummary } = useCampaign();
    const [loading, setLoading] = useState(false);
    const [progress, setProgress] = useState({ current: 0, total: 0, status: '' });
    const [errors, setErrors] = useState([]);
    // Gates the actual launch behind one extra confirm step when per-media mode
    // + ABO means N distinct budgets stack — the Review screen already shows this
    // math in a warning banner, but that's informational only. Flagged in
    // pre-push follow-up: no confirm gate existed before an ABO per-media launch
    // actually created N ad sets, each carrying the full configured budget.
    const [showLaunchConfirm, setShowLaunchConfirm] = useState(false);
    // Last Meta rate-limit reading, shown in the launch panel. null until
    // a launch is attempted; `available: false` means Meta told us nothing.
    const [rateLimitUsage, setRateLimitUsage] = useState(null);
    // Per-row outcome of the last launch: which indexes were created and where a
    // throttle stopped the batch. Without this the review list shows all N ads
    // with no indication of which ones actually made it, leaving the user to
    // reconcile against Ads Manager by hand.
    const [launchOutcome, setLaunchOutcome] = useState(null);
    const reconciliationScope = campaignData?.isExisting ? (campaignData?.fbCampaignId || campaignData?.id) : 'new';
    const reconciliationStorageKey = `bulk-creation-reconciliation:${selectedAdAccount?.accountId || selectedAdAccount?.id || 'none'}:${reconciliationScope}`;
    const [requiresReconciliation, setRequiresReconciliation] = useState(false);
    const persistReconciliationBlock = (message) => {
        setRequiresReconciliation(true);
        try {
            localStorage.setItem(reconciliationStorageKey, JSON.stringify({ message, recordedAt: new Date().toISOString() }));
        } catch (storageError) {
            console.warn('Could not persist reconciliation block:', storageError);
        }
    };
    React.useEffect(() => {
        try {
            setRequiresReconciliation(Boolean(localStorage.getItem(reconciliationStorageKey)));
        } catch (storageError) {
            console.warn('Could not restore reconciliation block:', storageError);
        }
    }, [reconciliationStorageKey]);
    // Recently-excluded ads (most recent last), so the exclude ("✕") button on a
    // dense multi-column grid — a smaller, closer-together target than the old
    // isolated row button — has an undo path. Flagged in pre-push review: no
    // confirm and no undo meant an accidental exclude on a good combination
    // silently dropped it with no recovery short of redoing the whole batch. A
    // STACK, not a single slot — a second exclude within the window used to
    // silently overwrite the first one's undo with no indication anything was
    // lost, the realistic failure mode on a dense grid (rarely just one
    // misclick). Capped so a rapid-fire clearing pass doesn't stack banners
    // indefinitely. A shared-app-wide Toast redesign (action buttons inside a
    // toast) would be a bigger, riskier change for what this needs —
    // self-contained here instead.
    const [removedStack, setRemovedStack] = useState([]);
    // The normal preview grid is useful for a handful of hand-built variants.
    // A Drive launch of 50–100 Feed + Stories pairs needs a manifest instead:
    // one compact row per pair, category filters, and a single focused detail
    // rail. `manifestExcludedAdIds` is deliberately separate from adsData so
    // a buyer can temporarily omit a whole category without destroying its
    // copy assignment or needing to rebuild the Drive selection.
    const [manifestSearch, setManifestSearch] = useState('');
    const [manifestCategory, setManifestCategory] = useState('all');
    const [manifestExcludedAdIds, setManifestExcludedAdIds] = useState(new Set());
    const [selectedManifestAdId, setSelectedManifestAdId] = useState(null);
    // Gates the shared edit drawer's visibility only — selectedManifestAdId/
    // selectedManifestRow keep their existing fallback-to-first-row semantics
    // for the manifest table's own highlighting, untouched by this. The drawer
    // itself is new UI surface over the existing updateManifestField/override
    // fields (already wired end-to-end into the launch payload for every ad,
    // not just Drive-manifest ones) — no new capability, just a way to reach it
    // from the standard preview grid too, and without permanently occupying a
    // column the way the old always-open rail did.
    const [editDrawerOpen, setEditDrawerOpen] = useState(false);
    // Was read-only from localStorage with no in-app control — Joel could only
    // change it by hand-editing browser storage. NamingTemplateField below
    // gives it the same Templates UI Campaign/Ad Set naming already has
    // (2931145), reusing the same resolveNamingTemplate/saveNamingTemplate
    // infra — this field just needed the last bit of UI wiring.
    const [adNamingPattern, setAdNamingPattern] = useState(
        () => safeLocalStorageGet('adNamingPattern') || '{media_name} - H{headline_num}B{body_num}'
    );
    const handleAdNamingPatternChange = (value) => {
        setAdNamingPattern(value);
        safeLocalStorageSet('adNamingPattern', value);
    };
    const adNamingTokens = {
        campaign_name: campaignData.name || '',
        ad_set_name: adsetData.name || '',
        headline_num: 1,
        body_num: 1,
        media_name: creativeData.creatives?.[0]?.name || 'Image 1',
        date: formatNamingDate(),
    };
    const adNamingTokenList = [
        { key: 'campaign_name', label: 'Campaign Name' },
        { key: 'ad_set_name', label: 'Ad Set Name' },
        { key: 'media_name', label: 'Media Name' },
        { key: 'headline_num', label: 'Headline #' },
        { key: 'body_num', label: 'Body #' },
        { key: 'date', label: 'Date' },
    ];
    const MAX_UNDO_STACK = 3;

    // Tracks whichever pattern is actually baked into the CURRENT adsData —
    // vs. adNamingPattern, which tracks whatever's live in the field right now.
    // The two can diverge the instant Joel edits the field without clicking
    // "Rename current ads," and that divergence needs to be visible (pre-push
    // review, joel-perspective: P1 — a silent field with no bound-looking grid
    // reads as either broken or already-applied; either way he could launch on
    // stale names without realizing it).
    const [lastAppliedNamingPattern, setLastAppliedNamingPattern] = useState(adNamingPattern);

    // Shared by initial generation, the explicit re-apply action, and undo —
    // one place computing a pattern-derived ad name so all three can never
    // drift out of sync with each other.
    const computeAdName = (pattern, { headlineIndex, bodyIndex, creativeId, mediaType }) => {
        const creativeIndex = creativeData.creatives.findIndex(c => c.id === creativeId);
        const creative = creativeIndex >= 0 ? creativeData.creatives[creativeIndex] : null;
        const mediaLabel = mediaType === 'video' ? 'Video' : 'Image';
        return resolveNamingTemplate(pattern, {
            campaign_name: campaignData.name || '',
            ad_set_name: adsetData.name || '',
            headline_num: headlineIndex + 1,
            body_num: bodyIndex + 1,
            media_name: creative?.name || `${mediaLabel} ${creativeIndex + 1}`,
            date: formatNamingDate(),
        });
    };

    // Changing a campaign/ad-set name should refresh only generated names, not
    // regenerate the whole manifest. A full regeneration replaces row ids and
    // would silently erase per-pair edits and category exclusions right before
    // a bulk launch. Media/copy inputs still intentionally regenerate the
    // permutations because their actual payloads have changed.
    const permutationInputsRef = React.useRef(null);
    const permutationInputKey = JSON.stringify({
        creatives: creativeData.creatives,
        headlines: creativeData.headlines,
        bodies: creativeData.bodies,
        description: creativeData.description,
        websiteUrl: creativeData.websiteUrl,
    });

    // Initialize ads based on creatives - generate all permutations
    React.useEffect(() => {
        const inputsChanged = permutationInputsRef.current !== permutationInputKey;
        if (!inputsChanged && adsData.length > 0) {
            setAdsData(prev => prev.map(ad => (
                ad.nameManuallyEdited ? ad : { ...ad, name: computeAdName(lastAppliedNamingPattern, ad) }
            )));
            return;
        }
        permutationInputsRef.current = permutationInputKey;
        if (creativeData.creatives && creativeData.creatives.length > 0) {
            // Filter out empty headlines and bodies — keep each one paired with its
            // ORIGINAL position in creativeData.headlines/bodies (not its position in
            // this filtered list). Every consumer of headlineIndex/bodyIndex — the real
            // Meta payload below and the Review screen's preview card — indexes back
            // into the raw, unfiltered creativeData.headlines/bodies. Storing a
            // filtered-list position here silently pulls the wrong headline/body the
            // moment a blank slot sits anywhere but the tail of the list (e.g. slot 2
            // cleared, slots 1 and 3 still filled) — found via pre-push review while
            // building the preview card, real bug independent of that card.
            const validHeadlines = creativeData.headlines
                .map((text, index) => ({ text, index }))
                .filter(h => h.text && h.text.trim() !== '');
            const validBodies = creativeData.bodies
                .map((text, index) => ({ text, index }))
                .filter(b => b.text && b.text.trim() !== '');

            // Generate all permutations: media × headlines × bodies
            const permutations = [];
            creativeData.creatives.forEach((creative, creativeIndex) => {
                const creativeHeadlines = creative.source === 'drive' || creative.headline
                    ? [{ index: null, override: creative.headline }]
                    : validHeadlines.map(({ index }) => ({ index }));
                const creativeBodies = creative.source === 'drive' || creative.body
                    ? [{ index: null, override: creative.body }]
                    : validBodies.map(({ index }) => ({ index }));
                creativeHeadlines.forEach(({ index: hIndex, override: headlineOverride }) => {
                    creativeBodies.forEach(({ index: bIndex, override: bodyOverride }) => {
                        permutations.push({
                            id: `ad_${Date.now()}_${creativeIndex}_${hIndex}_${bIndex}`,
                            name: computeAdName(adNamingPattern, {
                                headlineIndex: hIndex,
                                bodyIndex: bIndex,
                                creativeId: creative.id,
                                mediaType: creative.mediaType,
                            }),
                            nameManuallyEdited: false,
                            creativeId: creative.id,
                            headlineIndex: hIndex,
                            bodyIndex: bIndex,
                            // Store the resolved value on every row. In the
                            // Drive manifest this turns formerly shared form
                            // fields into designated per-ad copy, so a mixed
                            // category launch has no fallback path at submit.
                            headlineOverride: creative.source === 'drive'
                                ? headlineOverride || ''
                                : headlineOverride || creativeData.headlines?.[hIndex] || '',
                            bodyOverride: creative.source === 'drive'
                                ? bodyOverride || ''
                                : bodyOverride || creativeData.bodies?.[bIndex] || '',
                            descriptionOverride: creative.source === 'drive'
                                ? creative.description || ''
                                : creative.description || creativeData.description || '',
                            websiteUrlOverride: creative.source === 'drive'
                                ? creative.websiteUrl || ''
                                : creative.websiteUrl || creativeData.websiteUrl || '',
                            ctaOverride: creative.cta || '',
                            ctaSource: creative.ctaSource || '',
                            mediaType: creative.mediaType || 'image',
                            format: creative.format || 'feed',
                            dualPlacement: creative.dualPlacement || false,
                            useDefaultCreative: true
                        });
                    });
                });
            });

            // A creative with no own headline/body AND no manually-typed
            // headlines/bodies anywhere resolves to zero permutations here —
            // it silently vanishes from adsData with no error, no toast, no
            // trace in the Review grid. This is a realistic outcome for the
            // Drive-copy-autofill path specifically: a strategy-doc block
            // missing its `**Meta headline:**` line leaves creative.headline
            // as '' (falsy, correctly falls through to validHeadlines above),
            // and if Joel is relying entirely on Drive copy with nothing
            // manually typed, validHeadlines is also empty — that creative
            // just disappears from the batch with nothing telling him why
            // (code-auditor pre-push review, MEDIUM — flagged as a real risk
            // for the #1 priority Drive-copy feature specifically).
            const coveredCreativeIds = new Set(permutations.map(p => p.creativeId));
            const droppedCreatives = creativeData.creatives.filter(c => !coveredCreativeIds.has(c.id));
            if (droppedCreatives.length > 0) {
                showWarning(
                    `${droppedCreatives.length} creative${droppedCreatives.length !== 1 ? 's' : ''} `
                    + `(${droppedCreatives.map(c => c.name || c.id).join(', ')}) produced no ads — `
                    + `missing headline/body and no manual headline/body typed as a fallback.`
                );
            }

            setAdsData(permutations);
            setLastAppliedNamingPattern(adNamingPattern);
        } else {
            // Fallback if no creatives (shouldn't happen due to validation)
            setAdsData([]);
        }
    // `adNamingPattern` remains deliberately absent: changing it needs the
    // explicit "Rename current ads" action so manual names are never wiped.
    }, [permutationInputKey, campaignData.name, adsetData.name]);

    // Format detection — drives multi-adset launch logic
    const feedAds    = adsData.filter(ad => (ad.format || 'feed') !== 'stories');
    const storiesAds = adsData.filter(ad => ad.format === 'stories');
    const isMixedFormat  = feedAds.length > 0 && storiesAds.length > 0;
    const allStoriesFormat = feedAds.length === 0 && storiesAds.length > 0;
    // Render-time mirror of handleSubmit's own perMediaMode check — used to gate the
    // feed/stories summary banners below, which describe an ad-set model per-media
    // mode doesn't actually use (and whose ABO ×2 math would be wrong once the real
    // multiplier is however many distinct media files there are).
    const perMediaModeActive = adsetData.creationMode === 'per_media' && !adsetData.isExisting;
    // Drive selections use the compact row/rail review regardless of whether the
    // destination ad set is new or existing. The Drive Launch shortcut deliberately
    // forces "Use Existing" so it never sets perMediaModeActive, which previously
    // made the row view impossible to reach in the exact multi-pair flow it was
    // built for. Review layout and Meta ad-set creation mode are separate concerns.
    const isDriveManifest = creativeData.creatives?.some(creative => creative.source === 'drive');
    const activeAds = adsData.filter(ad => !manifestExcludedAdIds.has(ad.id));
    const driveManifestUsesExistingAdset = Boolean(isDriveManifest && adsetData.isExisting);
    const driveManifestCreatesSeparateAdsets = Boolean(isDriveManifest && perMediaModeActive);
    const driveManifestHasDualPlacement = Boolean(isDriveManifest && activeAds.some(ad => ad.dualPlacement));
    const existingPlacementStatus = driveManifestUsesExistingAdset && driveManifestHasDualPlacement
        ? existingDualPlacementStatus(adsetData.targeting, creativeData.instagramId)
        : null;
    const manifestLaunchOutcome = (ad) => {
        if (!launchOutcome) return null;
        if (launchOutcome.createdAdIds?.includes(ad.id)) return { label: 'Created', cls: 'bg-emerald-100 text-emerald-700' };
        if (launchOutcome.createdButUnmirroredAdIds?.includes(ad.id)) return { label: 'Created in Meta — reconcile', cls: 'bg-amber-100 text-amber-900' };
        if (launchOutcome.uncertainAdIds?.includes(ad.id)) return { label: 'Needs reconciliation', cls: 'bg-amber-100 text-amber-900' };
        if (launchOutcome.attemptedAdIds && !launchOutcome.attemptedAdIds.includes(ad.id)) return { label: 'Not attempted', cls: 'bg-amber-100 text-amber-800' };
        return { label: 'Failed', cls: 'bg-red-100 text-red-700' };
    };
    const manifestRows = adsData.map((ad, index) => {
        const creative = creativeData.creatives?.find(item => item.id === ad.creativeId);
        const creativeIndex = creativeData.creatives?.findIndex(item => item.id === ad.creativeId) ?? index;
        const headline = ad.headlineOverride || creativeData.headlines?.[ad.headlineIndex] || '';
        const body = ad.bodyOverride || creativeData.bodies?.[ad.bodyIndex] || '';
        const description = Object.prototype.hasOwnProperty.call(ad, 'descriptionOverride')
            ? ad.descriptionOverride || ''
            : creative?.description ?? creativeData.description ?? '';
        const websiteUrl = creative?.source === 'drive'
            ? (Object.prototype.hasOwnProperty.call(ad, 'websiteUrlOverride') ? ad.websiteUrlOverride || '' : creative.websiteUrl || '')
            : creative?.websiteUrl || creativeData.websiteUrl || '';
        const cta = creative?.source === 'drive'
            ? (ad.ctaOverride || creative.cta || '')
            : creative?.cta || ad.ctaOverride || creativeData.cta || '';
        const category = creative?.category || creative?.brandName || 'Uncategorized';
        const requiresAssignedCopy = isDriveManifest;
        const copyReady = !requiresAssignedCopy || Boolean(
            headline.trim() && body.trim() && isValidDestinationUrl(websiteUrl) && isValidMetaCta(cta)
        );
        const adsetName = driveManifestCreatesSeparateAdsets
            ? buildPerMediaAdsetName(adsetData.name, creative, creativeIndex >= 0 ? creativeIndex : index)
            : adsetData.name;
        const destinationLabel = driveManifestCreatesSeparateAdsets
            ? '1 new ad set'
            : driveManifestUsesExistingAdset
                ? 'selected existing ad set'
                : '1 shared new ad set';
        return { ad, index, creative, headline, body, description, websiteUrl, cta, ctaSource: ad.ctaSource || creative?.ctaSource || 'Creative card', category, copyReady, adsetName, destinationLabel, outcome: manifestLaunchOutcome(ad) };
    });
    const manifestCategories = [...new Set(manifestRows.map(row => row.category))].sort((a, b) => a.localeCompare(b));
    const visibleManifestRows = manifestRows.filter(row => {
        if (manifestCategory !== 'all' && row.category !== manifestCategory) return false;
        const searchText = `${row.ad.name} ${row.creative?.name || ''} ${row.category} ${row.headline} ${row.body} ${row.description}`.toLowerCase();
        return !manifestSearch.trim() || searchText.includes(manifestSearch.trim().toLowerCase());
    });
    // The rail must honor the active filter. Leaving a previously selected
    // Retail row editable while the table is filtered to Restaurant is exactly
    // how copy gets changed on the wrong pair in a 100-row batch.
    const selectedManifestRow = visibleManifestRows.find(row => row.ad.id === selectedManifestAdId)
        || visibleManifestRows.find(row => !manifestExcludedAdIds.has(row.ad.id))
        || visibleManifestRows[0]
        || null;
    const manifestReadyCount = activeAds.filter(ad => manifestRows.find(row => row.ad.id === ad.id)?.copyReady).length;

    // Feeds the launcher shell's Launch Plan rail — same ready/excluded math this
    // step's own review header already renders, pushed up so the shell never
    // computes a second, potentially-drifting copy of it.
    React.useEffect(() => {
        setLaunchSummary(prev => ({
            ...prev,
            totalAds: activeAds.length,
            readyCount: manifestReadyCount,
            warningCount: Math.max(activeAds.length - manifestReadyCount, 0),
            excludedCount: manifestExcludedAdIds.size,
        }));
    }, [activeAds.length, manifestReadyCount, manifestExcludedAdIds, setLaunchSummary]);

    React.useEffect(() => {
        // Drop exclusions for ads that were permanently removed through the
        // existing exclude/undo flow. This keeps selection state from leaking
        // into a regenerated batch after going Back and changing media.
        const adIds = new Set(adsData.map(ad => ad.id));
        setManifestExcludedAdIds(prev => {
            const next = new Set([...prev].filter(id => adIds.has(id)));
            return next.size === prev.size ? prev : next;
        });
        setSelectedManifestAdId(prev => prev && adIds.has(prev) ? prev : adsData[0]?.id || null);
    }, [adsData]);

    const toggleManifestAd = (adId) => {
        setManifestExcludedAdIds(prev => {
            const next = new Set(prev);
            next.has(adId) ? next.delete(adId) : next.add(adId);
            return next;
        });
    };

    const setVisibleManifestSelection = (selected) => {
        setManifestExcludedAdIds(prev => {
            const next = new Set(prev);
            visibleManifestRows.forEach(row => {
                if (selected) next.delete(row.ad.id);
                else next.add(row.ad.id);
            });
            return next;
        });
    };

    const updateManifestField = (row, field, value) => {
        if (!row) return;
        if (field === 'name') {
            updateAdName(row.index, value);
            return;
        }
        setAdsData(prev => prev.map(ad => {
            if (ad.id !== row.ad.id) return ad;
            if (field === 'headline') return { ...ad, headlineOverride: value };
            if (field === 'body') return { ...ad, bodyOverride: value };
            if (field === 'description') return { ...ad, descriptionOverride: value };
            if (field === 'websiteUrl') return { ...ad, websiteUrlOverride: value };
            if (field === 'cta') return { ...ad, ctaOverride: value, ctaSource: 'Manual row edit' };
            return ad;
        }));
    };

    const removeAd = (index) => {
        // Computed BEFORE the setAdsData updater, not inside it — an updater must
        // be pure (React may invoke it more than once for the same transition,
        // most visibly under StrictMode's double-invoke); calling setRemovedStack
        // from inside setAdsData's callback was exactly that anti-pattern, caught
        // in pre-push review. Reading adsData directly here instead.
        const ad = adsData[index];
        const key = `${ad.id}_${Date.now()}`;
        setRemovedStack(prev => [...prev.slice(-(MAX_UNDO_STACK - 1)), { key, ad, index }]);
        setAdsData(prev => prev.filter((_, i) => i !== index));
        // Each entry expires independently, 8s from when IT was added — not a
        // single shared timer that a later removal would reset for an earlier one.
        setTimeout(() => {
            setRemovedStack(prev => prev.filter(r => r.key !== key));
        }, 8000);
    };

    const undoRemove = (key) => {
        const entry = removedStack.find(r => r.key === key);
        if (!entry) return;
        setAdsData(prev => {
            const next = [...prev];
            // Clamp — the list may have shrunk further (another exclude, or a
            // re-launch that regenerated adsData) since this one was removed.
            const insertAt = Math.min(entry.index, next.length);
            // Re-derive the restored ad's name against whatever pattern is
            // CURRENTLY applied to the rest of the batch (lastAppliedNamingPattern,
            // not necessarily what's live in the field) — otherwise an ad excluded
            // before a "Rename current ads" click comes back on the stale pattern,
            // silently mismatched against every other ad in the grid with no
            // indication anything's off (pre-push review, code-auditor: MEDIUM).
            // Skipped for an ad Joel manually renamed by hand — that's a deliberate
            // choice, not a pattern artifact, and undo should restore exactly what
            // he typed, not overwrite it.
            const restoredAd = entry.ad.nameManuallyEdited
                ? entry.ad
                : { ...entry.ad, name: computeAdName(lastAppliedNamingPattern, entry.ad) };
            next.splice(insertAt, 0, restoredAd);
            return next;
        });
        setRemovedStack(prev => prev.filter(r => r.key !== key));
    };

    const updateAdName = (index, name) => {
        setAdsData(prev => prev.map((ad, i) => i === index ? { ...ad, name, nameManuallyEdited: true } : ad));
    };

    // Explicit, opt-in re-name of the CURRENT batch against whatever pattern is
    // in the field right now — every other field (exclusions already reflected
    // in adsData's length, media, headline/body index) is left untouched, only
    // `name` is recomputed. Deliberately a button click, not a side effect of
    // typing in the field (see the naming-pattern effect-deps comment above).
    // Overwrites even manually-renamed ads — Joel clicked an action explicitly
    // labeled "using this pattern," covering every ad currently in the grid, so
    // this is the one place a manual rename is expected to be replaced; the
    // nameManuallyEdited flag resets since the name is pattern-derived again.
    const applyNamingPatternToCurrentAds = () => {
        setAdsData(prev => prev.map(ad => {
            return {
                ...ad,
                name: computeAdName(adNamingPattern, ad),
                nameManuallyEdited: false,
            };
        }));
        setLastAppliedNamingPattern(adNamingPattern);
        showSuccess(`Renamed ${adsData.length} ad${adsData.length !== 1 ? 's' : ''} using the new pattern.`);
    };

    const handleSubmit = async () => {
        try {
            if (localStorage.getItem(reconciliationStorageKey)) {
                setRequiresReconciliation(true);
                showError('This batch has an unresolved Meta write. Reconcile it in Ads Manager before creating anything else.');
                return;
            }
        } catch (storageError) {
            console.warn('Could not read reconciliation block:', storageError);
        }
        const launchAds = adsData.filter(ad => !manifestExcludedAdIds.has(ad.id));
        if (launchAds.length === 0) {
            showWarning('Select at least one ad pair to launch');
            return;
        }

        // Drive copy is intentionally not allowed to inherit a neighboring
        // pair's shared fields. A category selection can contain Retail and
        // Restaurant in the same launch, so every Drive row must carry its own
        // primary text, headline, and destination at the exact moment we send
        // it to Meta. Meta descriptions are optional for link creatives.
        const incompleteManifestRows = isDriveManifest ? launchAds.filter(ad => {
            const creative = creativeData.creatives?.find(item => item.id === ad.creativeId);
            const headline = (ad.headlineOverride || '').trim();
            const body = (ad.bodyOverride || '').trim();
            const websiteUrl = (Object.prototype.hasOwnProperty.call(ad, 'websiteUrlOverride')
                ? ad.websiteUrlOverride
                : creative?.websiteUrl) || '';
            const cta = ad.ctaOverride || creative?.cta || '';
            return !headline || !body || !isValidDestinationUrl(websiteUrl) || !isValidMetaCta(cta);
        }) : [];
        if (incompleteManifestRows.length > 0) {
            showWarning(`${incompleteManifestRows.length} selected ad pair${incompleteManifestRows.length !== 1 ? 's are' : ' is'} missing a valid Primary Text, Headline, Meta CTA, or http(s) destination URL. Open the affected row and complete it before launch.`);
            return;
        }

        // The existing ad set keeps its own targeting. A post-submit toast is
        // too late: it would warn Joel only after ads had begun creating with
        // unverified Feed/Stories delivery. Require the exact placement contract
        // before any Meta mutation, or have him use a placement-compatible ad set.
        const existingTargetStatus = isDriveManifest && adsetData.isExisting && launchAds.some(ad => ad.dualPlacement)
            ? existingDualPlacementStatus(adsetData.targeting, creativeData.instagramId)
            : null;
        if (existingTargetStatus === 'unverified') {
            showWarning('This existing ad set is not verified for exactly Facebook Feed + Stories (and Instagram Stream, Stories, and Reels when Instagram is enabled). Go back and choose a placement-compatible ad set before launching these paired creatives.');
            return;
        }

        // New paired rows are explicitly targeted to Instagram as well as
        // Facebook below. Do not let Meta create a Facebook-only creative and
        // silently omit the supplied Stories/Reels image when the selected
        // Page has no linked Instagram identity.
        if (isDriveManifest && !adsetData.isExisting && launchAds.some(ad => ad.dualPlacement) && !creativeData.instagramId) {
            showWarning('The selected Facebook Page has no linked Instagram identity available. Choose a Page connected to Instagram before launching Feed + Stories pairs, or use a Facebook-only workflow.');
            return;
        }

        setLoading(true);
        setErrors([]);
        setLaunchOutcome(null);

        // Determine format strategy at submission time (not stale closure)
        const feedAdsToCreate    = launchAds.filter(ad => (ad.format || 'feed') !== 'stories');
        const storiesAdsToCreate = launchAds.filter(ad => ad.format === 'stories');
        const isMixed      = feedAdsToCreate.length > 0 && storiesAdsToCreate.length > 0;
        const isAllStories = feedAdsToCreate.length === 0 && storiesAdsToCreate.length > 0;
        const perMediaMode = adsetData.creationMode === 'per_media' && !adsetData.isExisting;
        const hasLinkedPlacement = launchAds.some(ad => ad.dualPlacement);
        const hasIndependentPlacement = launchAds.some(ad => !ad.dualPlacement);
        if (!perMediaMode && hasLinkedPlacement && hasIndependentPlacement) {
            setLoading(false);
            showWarning('This batch mixes linked Feed + Stories pairs with independent placement ads. Separate them into their own launches until placement routing is configured for this combination.');
            return;
        }

        setProgress({ current: 0, total: launchAds.length, status: 'Checking Meta rate limits...' });

        // Pre-flight: read how much of this account's Meta budget is already
        // spent. Purely informational — a high reading does NOT block the
        // launch, because Meta's percentages are advisory and a buyer may have
        // a good reason to push on. It exists so a batch that is likely to be
        // throttled halfway is a known risk rather than a surprise.
        //
        // `available: false` means Meta sent no usage headers. That is reported
        // as unknown and never as 0% — a fabricated zero would be worse than
        // saying nothing at all.
        try {
            const usage = await getRateLimitUsage(selectedAdAccount?.accountId);
            setRateLimitUsage(usage);
            if (usage?.available) {
                const peak = peakUsagePercent(usage.usage);
                if (peak !== null && peak >= USAGE_WARN_THRESHOLD) {
                    // A warning with no recommended action just trains people
                    // to click past it. Say what to do instead.
                    showWarning(
                        `This account is at ${Math.round(peak)}% of its Meta rate limit. `
                        + `Launching ${launchAds.length} ad${launchAds.length === 1 ? '' : 's'} now may get throttled partway. `
                        + `This launcher will pace the queue and cool down every ${BULK_LAUNCH_BATCH_SIZE} items, but waiting ~15 minutes is safer when usage is already this high. `
                        + `If it does throttle, the batch stops and marks which ads were created.`
                    );
                }
            }
        } catch (err) {
            // Telemetry must never block a launch.
            console.warn('Rate-limit pre-flight skipped:', err);
        }

        setProgress({ current: 0, total: launchAds.length, status: 'Starting...' });

        try {
            // ── Step 1: Campaign ──────────────────────────────────────────────────
            let fbCampaignId = campaignData.fbCampaignId;
            if (!campaignData.isExisting) {
                setProgress(prev => ({ ...prev, status: 'Creating campaign on Facebook...' }));
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
                    // The campaign already exists on Meta at this point — only the
                    // local record failed. Naming the id keeps a retry from quietly
                    // creating a second campaign nothing in the app is tracking.
                    throw new Error(
                        `Campaign ${fbCampaignId} was created on Meta but could not be saved locally: `
                        + `${err.detail || err.message || saveCampRes.status}. `
                        + `Do not re-launch — it already exists on the account.`
                    );
                }
            } catch (err) {
                console.error('Error saving campaign locally:', err);
                err.metaMutationStarted = true;
                throw err;
            }
            // ── Step 2: Ad Set(s) ─────────────────────────────────────────────────
            // Base payload shared between all ad sets
            const baseAdsetPayload = {
                ...adsetData,
                ...(campaignData.budgetType === 'CBO' && {
                    bidStrategy: campaignData.bidStrategy,
                    bidAmount: campaignData.bidAmount
                }),
                specialAdCategories: campaignData.specialAdCategories || []
            };

            // Stories placement targeting overlay — locks to Stories & Reels only
            const storiesTargeting = {
                ...adsetData.targeting,
                publisher_platforms: ['facebook', 'instagram'],
                facebook_positions: ['story'],
                instagram_positions: ['story', 'reels']
            };

            // Feed placement targeting overlay — explicitly excludes Stories/Reels so Meta
            // doesn't default to Advantage+ Placements and serve 1:1 images in Stories
            const feedTargeting = {
                ...adsetData.targeting,
                publisher_platforms: ['facebook', 'instagram'],
                facebook_positions: ['feed'],
                instagram_positions: ['stream']
            };

            // Dual-placement targeting overlay — for an ad set made up entirely of
            // dual-placement creatives (Drive Feed+Stories pairs, each already
            // carrying its own per-placement image via create_creative's
            // asset_customization_rules). Locks to exactly the two placements every
            // creative here customizes for; leaving targeting at its default
            // (broad/Advantage+) would let Meta serve into placements the creative
            // doesn't cover (Marketplace, Explore, Right Hand Column, etc.) — the
            // same "wrong image in wrong placement" failure feedTargeting/
            // storiesTargeting above already exist to prevent, just for a creative
            // that spans both placements instead of only one. Mirrors
            // BulkMatchImport.jsx's dualPlacementTargeting exactly.
            const dualPlacementTargeting = {
                ...adsetData.targeting,
                publisher_platforms: ['facebook', 'instagram'],
                facebook_positions: ['feed', 'story'],
                instagram_positions: ['stream', 'story', 'reels']
            };

            // Only apply when EVERY feed-bucket ad is dual-placement — if a plain
            // single-image feed creative shares this ad set, opening it to Stories
            // too would let Meta serve that creative's square image into Stories,
            // reintroducing the exact bug feedTargeting exists to prevent for it.
            // A genuinely mixed batch (some plain feed, some dual-placement, in the
            // same non-"isMixed" bucket) falls through to today's default behavior
            // unchanged rather than guessing — Abel's actual test case (a single
            // Drive-picked pair, or several pairs together) is the clean case this
            // covers.
            const hasDualPlacementAds = feedAdsToCreate.length > 0 && feedAdsToCreate.every(ad => ad.dualPlacement);

            let fbFeedAdsetId    = adsetData.fbAdsetId; // used for feed ads (or all ads if single-format)
            let fbStoriesAdsetId = null;                // used for stories ads (mixed only)
            let feedAdsetLocalId = adsetData.id;
            let storiesAdsetLocalId = null;
            // creativeId -> { fbAdsetId, localAdsetId } — only populated in per-media mode
            // (Birch Stage's "Duplicate ad set for each media"). Each distinct creative
            // gets its own ad set, so there's no feed/stories "mixed ad set" concern here
            // the way there is for the single-ad-set mode below — a per-media ad set only
            // ever holds ads for one creative, which has exactly one format already.
            const perMediaAdsetMap = new Map();
            if (perMediaMode) {
                const distinctCreativeIds = [...new Set(launchAds.map(ad => ad.creativeId))];
                for (let m = 0; m < distinctCreativeIds.length; m++) {
                    // One browser click may create 50–100 ad sets, but it must not
                    // become a burst of writes to one Meta ad account. Serialize the
                    // queue, then pause at bounded checkpoints. Ads Manager-like
                    // tools can look instantaneous because they accept a queue first;
                    // the safe part happens while it drains.
                    if (m > 0) {
                        if (m % BULK_LAUNCH_BATCH_SIZE === 0) {
                            setProgress(prev => ({
                                ...prev,
                                status: `Cooling down after ${m} of ${distinctCreativeIds.length} ad sets to stay within Meta write limits...`,
                            }));
                            await delay(BULK_LAUNCH_BATCH_COOLDOWN_MS);
                        } else {
                            await delay(INTER_REQUEST_DELAY_MS);
                        }
                    }

                    const creativeId = distinctCreativeIds[m];
                    const creative = creativeData.creatives?.find(c => c.id === creativeId);
                    const creativeIndex = creativeData.creatives?.findIndex(c => c.id === creativeId);
                    const sampleAd = launchAds.find(ad => ad.creativeId === creativeId);
                    // Always number the label, even when the file has a real name —
                    // two separately-uploaded files can share the exact same filename
                    // (e.g. two phone exports both called "image.png"), which would
                    // otherwise produce two identically-named, hard-to-tell-apart ad
                    // sets in Ads Manager with no way to distinguish them after launch.
                    const mediaLabel = creative?.name ? `${creative.name} (${m + 1})` : `Media ${m + 1}`;
                    const targeting = sampleAd?.dualPlacement
                        ? dualPlacementTargeting
                        : sampleAd?.format === 'stories' ? storiesTargeting : feedTargeting;
                    const payload = {
                        ...baseAdsetPayload,
                        name: buildPerMediaAdsetName(adsetData.name, creative, creativeIndex >= 0 ? creativeIndex : m),
                        targeting,
                    };

                    setProgress(prev => ({ ...prev, status: `Creating ad set ${m + 1} of ${distinctCreativeIds.length} (${mediaLabel})...` }));

                    let newFbAdsetId;
                    try {
                        newFbAdsetId = await createFacebookAdSet(payload, fbCampaignId, selectedAdAccount.accountId, campaignData.budgetType);
                    } catch (err) {
                        // No ads have been created yet (Step 3 hasn't started) — the only
                        // state to reconcile is whichever ad sets already succeeded before
                        // this one failed. Abort rather than silently continuing with a
                        // media file that has nowhere for its ads to go.
                        //
                        // Name a rate-limit throttle specifically — this loop can make up
                        // to one Meta call per distinct media file (more than the existing
                        // single/mixed path's max of 2), so it's more likely than before to
                        // actually hit one. Step 3's ad loop gets a richer treatment
                        // (wait-time estimate, launchOutcome state); this is the cheaper
                        // version — naming the cause so the fix ("wait, don't retry
                        // immediately") is obvious from the message alone, since building
                        // the same rich UI for a failure this early (before any ad exists)
                        // is a bigger lift than this fix warrants right now.
                        const rateLimitNote = isRateLimitError(err)
                            ? ' This looks like a Meta rate-limit throttle — wait ~15 minutes before retrying, don\'t immediately re-launch.'
                            : '';
                        const wrapped = new Error(
                            `Failed to create ad set for "${mediaLabel}" (${m + 1} of ${distinctCreativeIds.length}): ${err.message}.`
                            + `${rateLimitNote} `
                            + `${perMediaAdsetMap.size} ad set(s) were already created on Meta before this failure — `
                            + `do not re-launch from scratch, they already exist on the account.`
                        );
                        wrapped.metaErrorCode = err.metaErrorCode;
                        wrapped.metaErrorSubcode = err.metaErrorSubcode;
                        wrapped.metaMutationStarted = Boolean(err.metaMutationStarted || perMediaAdsetMap.size > 0);
                        throw wrapped;
                    }

                    // The local mirror is part of a resumable launch's integrity,
                    // not best-effort. If Meta created the set but this fails,
                    // stop and reconcile rather than treating it as safely
                    // retryable and silently losing app-side management data.
                    const saveAdsetRes = await authFetch(`${API_URL}/facebook/adsets/save`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            ...adsetData,
                            // A per-media launch creates a distinct local row
                            // for each newly-created Meta ad set. Do not carry
                            // the wizard's selected/local id into every save,
                            // or the backend will return the first mirror and
                            // attach all later ads to the wrong ad set.
                            id: undefined,
                            campaignId: campaignData.id,
                            name: payload.name,
                            fbAdsetId: newFbAdsetId,
                            dailyBudget: adsetData.dailyBudget ? Number(adsetData.dailyBudget) : null,
                            lifetimeBudget: adsetData.lifetimeBudget ? Number(adsetData.lifetimeBudget) : null,
                            budgetScheduleType: adsetData.budgetScheduleType || 'DAILY',
                            endTime: adsetData.endTime || null,
                            bidAmount: adsetData.bidAmount ? Number(adsetData.bidAmount) : null
                        })
                    });
                    if (!saveAdsetRes.ok) {
                        const err = await saveAdsetRes.json().catch(() => ({}));
                        const saveError = new Error(`Meta created ad set "${payload.name}" (${newFbAdsetId}) but the local mirror failed: ${err.detail || err.message || saveAdsetRes.status}. Reconcile this ad set in Ads Manager before retrying.`);
                        saveError.metaMutationStarted = true;
                        throw saveError;
                    }
                    const savedAdset = await saveAdsetRes.json().catch(() => ({}));
                    if (!savedAdset.id) {
                        const saveError = new Error(`Meta created ad set "${payload.name}" (${newFbAdsetId}) but the local mirror returned no UUID. Reconcile this ad set in Ads Manager before retrying.`);
                        saveError.metaMutationStarted = true;
                        throw saveError;
                    }
                    perMediaAdsetMap.set(creativeId, { fbAdsetId: newFbAdsetId, localAdsetId: savedAdset.id });
                }
            } else if (!adsetData.isExisting) {
                setProgress(prev => ({ ...prev, status: 'Creating ad set on Facebook...' }));

                if (isMixed) {
                    // Feed ad set — explicit feed placements to prevent Advantage+ bleed into Stories
                    const feedPayload = { ...baseAdsetPayload, name: `${adsetData.name} - Feed`, targeting: feedTargeting };
                    fbFeedAdsetId = await createFacebookAdSet(feedPayload, fbCampaignId, selectedAdAccount.accountId, campaignData.budgetType);
                    // Stories ad set
                    setProgress(prev => ({ ...prev, status: 'Creating Stories & Reels ad set...' }));
                    const storiesPayload = {
                        ...baseAdsetPayload,
                        name: `${adsetData.name} - Stories & Reels`,
                        targeting: storiesTargeting
                    };
                    fbStoriesAdsetId = await createFacebookAdSet(storiesPayload, fbCampaignId, selectedAdAccount.accountId, campaignData.budgetType);
                    storiesAdsetLocalId = `adset_stories_${Date.now()}`;
                } else if (isAllStories) {
                    // Single ad set — stories placements only
                    const storiesPayload = { ...baseAdsetPayload, targeting: storiesTargeting };
                    fbFeedAdsetId = await createFacebookAdSet(storiesPayload, fbCampaignId, selectedAdAccount.accountId, campaignData.budgetType);
                } else if (hasDualPlacementAds) {
                    // Single ad set — placement-locked to Feed + Story so Meta's
                    // asset_customization_rules actually get exercised (see comment
                    // on dualPlacementTargeting above).
                    const dualPayload = { ...baseAdsetPayload, targeting: dualPlacementTargeting };
                    fbFeedAdsetId = await createFacebookAdSet(dualPayload, fbCampaignId, selectedAdAccount.accountId, campaignData.budgetType);
                } else {
                    // Single ad set — feed (default)
                    fbFeedAdsetId = await createFacebookAdSet(baseAdsetPayload, fbCampaignId, selectedAdAccount.accountId, campaignData.budgetType);
                }
            } else if (isMixed) {
                // Existing ad set for feed + new stories ad set
                setProgress(prev => ({ ...prev, status: 'Creating Stories & Reels ad set...' }));
                const storiesPayload = {
                    ...baseAdsetPayload,
                    name: `${adsetData.name} - Stories & Reels`,
                    targeting: storiesTargeting,
                    isExisting: false
                };
                fbStoriesAdsetId = await createFacebookAdSet(storiesPayload, fbCampaignId, selectedAdAccount.accountId, campaignData.budgetType);
                storiesAdsetLocalId = `adset_stories_${Date.now()}`;
            }

            // Save feed (or sole) ad set locally — per-media mode already saved each of
            // its ad sets individually inside the loop above, nothing left to do here.
            if (!perMediaMode) {
                const adsetSaveBody = {
                    ...adsetData,
                    campaignId: campaignData.id,
                    fbAdsetId: fbFeedAdsetId,
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
                        // Same as the campaign save above: the ad set is live on Meta,
                        // only the local row is missing.
                        throw new Error(
                            `Ad set ${fbFeedAdsetId} was created on Meta but could not be saved locally: `
                            + `${err.detail || err.message || saveAdSetRes.status}. `
                            + `Do not re-launch — it already exists on the account.`
                        );
                    }
                    const savedAdset = await saveAdSetRes.json().catch(() => ({}));
                    // Existing selections carry Meta's ID in `adsetData.id`,
                    // but `/ads/save` needs the local FacebookAdSet UUID FK.
                    // The save endpoint resolves/returns that UUID for both
                    // existing and new ad sets; retain it for every ad below.
                    feedAdsetLocalId = savedAdset.id || feedAdsetLocalId;
                } catch (err) {
                    console.error('Error saving ad set locally:', err);
                    err.metaMutationStarted = true;
                    throw err;
                }

                // Save the Stories ad set locally before creating any Stories ads.
                // A live Meta ad set without a local row cannot be used as a valid
                // FacebookAd foreign key, so continuing here would create an
                // unreconcilable partial launch.
                if (fbStoriesAdsetId && storiesAdsetLocalId) {
                    try {
                        const saveStoriesAdSetRes = await authFetch(`${API_URL}/facebook/adsets/save`, {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({
                                ...adsetSaveBody,
                                id: storiesAdsetLocalId,
                                name: `${adsetData.name} - Stories & Reels`,
                                fbAdsetId: fbStoriesAdsetId
                            })
                        });
                        if (!saveStoriesAdSetRes.ok) {
                            const err = await saveStoriesAdSetRes.json().catch(() => ({}));
                            throw new Error(
                                `Stories ad set ${fbStoriesAdsetId} was created on Meta but could not be saved locally: `
                                + `${err.detail || err.message || saveStoriesAdSetRes.status}. `
                                + `Do not re-launch — it already exists on the account.`
                            );
                        }
                        const savedStoriesAdset = await saveStoriesAdSetRes.json().catch(() => ({}));
                        storiesAdsetLocalId = savedStoriesAdset.id || storiesAdsetLocalId;
                    } catch (err) {
                        console.error('Could not save Stories ad set locally:', err);
                        err.metaMutationStarted = true;
                        throw err;
                    }
                }
            }

            // ── Step 3: Ads ───────────────────────────────────────────────────────
            let failedCount = 0;
            let rateLimited = false;
            let ambiguousStop = false;
            let attempted = 0;
            const createdIndexes = [];
            const createdAdIds = [];
            for (let i = 0; i < launchAds.length; i++) {
                // Space out the per-ad Meta calls. Each iteration below is
                // several writes (image upload + creative + ad), so a large
                // launch must be a queue rather than a burst. The checkpoint is
                // visible in the progress label so the short wait does not read
                // like a frozen launch screen.
                if (i > 0) {
                    if (i % BULK_LAUNCH_BATCH_SIZE === 0) {
                        setProgress(prev => ({
                            ...prev,
                            status: `Cooling down after ${i} of ${launchAds.length} ads to stay within Meta write limits...`,
                        }));
                        await delay(BULK_LAUNCH_BATCH_COOLDOWN_MS);
                    } else {
                        await delay(INTER_REQUEST_DELAY_MS);
                    }
                }

                attempted = i + 1;
                const ad = launchAds[i];
                const isStoriesAd   = ad.format === 'stories';
                let adFbAdsetId, adLocalAdsetId;
                if (perMediaMode) {
                    const entry = perMediaAdsetMap.get(ad.creativeId);
                    adFbAdsetId = entry?.fbAdsetId;
                    adLocalAdsetId = entry?.localAdsetId;
                } else {
                    adFbAdsetId = isStoriesAd && fbStoriesAdsetId ? fbStoriesAdsetId : fbFeedAdsetId;
                    adLocalAdsetId = isStoriesAd && storiesAdsetLocalId ? storiesAdsetLocalId : feedAdsetLocalId;
                }

                if (perMediaMode && !adFbAdsetId) {
                    // Defensive only — every creativeId in adsData should have an entry
                    // from the loop above, which aborts the whole launch on any ad-set
                    // creation failure. If this still happens, fail this ad loudly
                    // rather than silently dropping it into an undefined ad set.
                    setErrors(prev => [...prev, `Skipped ${ad.name}: no ad set was created for its media.`]);
                    failedCount++;
                    continue;
                }

                setProgress({
                    current: i + 1,
                    total: launchAds.length,
                    status: `Creating ${isStoriesAd ? 'Stories' : 'Feed'} ad ${i + 1} of ${launchAds.length}...`
                });

                let metaCreatedAdId = null;
                try {
                    const specificCreative = creativeData.creatives?.find(c => c.id === ad.creativeId);
                    const isVideo = specificCreative?.mediaType === 'video';

                    const adSpecificCreativeData = {
                        ...creativeData,
                        mediaType: isVideo ? 'video' : 'image',
                        imageUrl: !isVideo ? (specificCreative?.imageUrl || specificCreative?.previewUrl) : undefined,
                        videoUrl: isVideo ? (specificCreative?.videoUrl || specificCreative?.previewUrl) : undefined,
                        imageFile: !isVideo && specificCreative ? specificCreative.file : null,
                        videoFile: isVideo && specificCreative ? specificCreative.file : null,
                        // Feed+Stories Drive pairs carry a secondaryImageUrl — createCompleteAd
                        // already uploads it and passes secondary_image_hash through to Meta's
                        // asset_feed_spec dual-placement path (same mechanism Bulk Match Import
                        // ships). Never set for video creatives — that path is image-only.
                        secondaryImageUrl: !isVideo ? specificCreative?.secondaryImageUrl : undefined,
                        headlines: [isDriveManifest || specificCreative?.source === 'drive'
                            ? ad.headlineOverride
                            : (ad.headlineOverride || creativeData.headlines[ad.headlineIndex])],
                        bodies: [isDriveManifest || specificCreative?.source === 'drive'
                            ? ad.bodyOverride
                            : (ad.bodyOverride || creativeData.bodies[ad.bodyIndex])],
                        description: (isDriveManifest || Object.prototype.hasOwnProperty.call(ad, 'descriptionOverride'))
                            ? ad.descriptionOverride
                            : specificCreative && Object.prototype.hasOwnProperty.call(specificCreative, 'description')
                                ? specificCreative.description
                            : creativeData.description,
                        cta: ad.ctaOverride || specificCreative?.cta || creativeData.cta,
                        websiteUrl: isDriveManifest || specificCreative?.source === 'drive'
                            ? (Object.prototype.hasOwnProperty.call(ad, 'websiteUrlOverride') ? ad.websiteUrlOverride : specificCreative?.websiteUrl)
                            : (specificCreative?.websiteUrl || creativeData.websiteUrl)
                    };

                    if (!creativeData.pageId) {
                        throw new Error('Page ID is missing. Please go back to the Creative step and select a Facebook Page.');
                    }

                    if (isVideo) {
                        setProgress(prev => ({
                            ...prev,
                            status: `Uploading video ${i + 1} of ${launchAds.length}... (this may take a while)`
                        }));
                    }

                    const result = await createCompleteAd(
                        fbCampaignId,
                        { ...adsetData, fbAdsetId: adFbAdsetId },
                        adSpecificCreativeData,
                        ad,
                        creativeData.pageId,
                        selectedAdAccount.accountId,
                        campaignData.budgetType,
                        // One Drive pair can produce up to four writes: 1:1 image,
                        // 9:16 image, creative, then paused ad. Pace this inner
                        // chain too — outer row pacing alone would still make a
                        // short burst at every ad boundary.
                        { betweenRequestMs: INTER_REQUEST_DELAY_MS }
                    );
                    metaCreatedAdId = result.adId;

                    const saveAdRes = await authFetch(`${API_URL}/facebook/ads/save`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            id: ad.id,
                            adsetId: adLocalAdsetId,
                            name: ad.name,
                            creativeName: creativeData.creativeName,
                            mediaType: isVideo ? 'video' : 'image',
                            imageUrl: adSpecificCreativeData.imageUrl,
                            secondaryImageUrl: adSpecificCreativeData.secondaryImageUrl,
                            videoUrl: adSpecificCreativeData.videoUrl,
                            videoId: result.videoId,
                            thumbnailUrl: result.thumbnailUrl,
                            // Persist the exact per-ad copy used for this creative.
                            // Drive selections can carry different matched copy per
                            // image/pair; saving the global arrays here made later
                            // reads and Iterate show the first category's copy.
                            bodies: adSpecificCreativeData.bodies.filter(b => b && b.trim() !== ''),
                            headlines: adSpecificCreativeData.headlines.filter(h => h && h.trim() !== ''),
                            description: adSpecificCreativeData.description,
                            cta: adSpecificCreativeData.cta,
                            websiteUrl: adSpecificCreativeData.websiteUrl,
                            status: 'PAUSED',
                            fbAdId: result.adId,
                            fbCreativeId: result.creativeId
                        })
                    });
                    if (!saveAdRes.ok) {
                        const err = await saveAdRes.json().catch(() => ({}));
                        throw new Error(
                            `Meta ad ${metaCreatedAdId} was created, but its local record failed to save: `
                            + `${err.detail || err.message || saveAdRes.status}. Do not re-launch this batch.`
                        );
                    }

                    // Only count the ad as fully created after both Meta and the
                    // local mirror have succeeded. This prevents a local-save
                    // failure from looking like a completed row and discourages
                    // blind relaunches that would duplicate the live Meta ad.
                    createdIndexes.push(i);
                    createdAdIds.push(ad.id);

                } catch (error) {
                    console.error(`Error creating ad ${ad.name}:`, error);
                    setErrors(prev => [...prev, `Failed to create ${ad.name}: ${error.message}`]);
                    failedCount++;

                    // A Meta ad exists but the local mirror failed. Stop the
                    // queue and label the row as created-but-unreconciled;
                    // continuing would create more live objects while the first
                    // one is not reconciled, and a blind retry could duplicate it.
                    if (metaCreatedAdId) {
                        persistReconciliationBlock(error.message);
                        setLaunchOutcome({ createdIndexes: [...createdIndexes], createdAdIds: [...createdAdIds], createdButUnmirroredAdIds: [ad.id], attemptedAdIds: launchAds.slice(0, i + 1).map(item => item.id), stoppedAtIndex: i });
                        break;
                    }

                    // Meta throttled the account. Stop now rather than grinding
                    // the remaining ads into a wall of identical errors — every
                    // further attempt is guaranteed to fail and only pushes the
                    // account deeper into the limit.
                    if (isRateLimitError(error)) {
                        rateLimited = true;
                        setLaunchOutcome({ createdIndexes: [...createdIndexes], createdAdIds: [...createdAdIds], attemptedAdIds: launchAds.slice(0, i + 1).map(item => item.id), stoppedAtIndex: i });

                        // Read the wait estimate NOW, not from the pre-flight
                        // check. That reading was taken before the batch started
                        // and describes a different moment — presenting it as the
                        // estimate for the throttle that just happened would be a
                        // number the user plans a retry around. If this read
                        // fails (likely, the account is throttled), it resolves
                        // to unavailable and the message falls back to generic
                        // wording rather than inventing a figure.
                        let regainSeconds = null;
                        try {
                            const fresh = await getRateLimitUsage(selectedAdAccount?.accountId);
                            setRateLimitUsage(fresh);
                            regainSeconds = fresh?.usage?.estimated_time_to_regain_access ?? null;
                        } catch (usageErr) {
                            console.warn('Post-throttle usage read failed:', usageErr);
                        }

                        setErrors(prev => [...prev, rateLimitStopMessage({
                            created: createdIndexes.length,
                            total: launchAds.length,
                            attempted,
                            regainSeconds,
                            notAttemptedNames: launchAds.slice(i + 1).map(a => a.name).filter(Boolean),
                        })]);
                        break;
                    }
                    if (error.metaMutationStarted) {
                        ambiguousStop = true;
                        persistReconciliationBlock(error.message);
                        setLaunchOutcome({ createdIndexes: [...createdIndexes], createdAdIds: [...createdAdIds], uncertainAdIds: [ad.id], attemptedAdIds: launchAds.slice(0, i + 1).map(item => item.id), stoppedAtIndex: i });
                        setErrors(prev => [...prev, `Meta may have created part of this ad. Reconcile ad ${ad.name} in Ads Manager before retrying.`]);
                        break;
                    }
                }
            }

            if (rateLimited || ambiguousStop) {
                if (createdAdIds.length > 0 || !campaignData.isExisting || !adsetData.isExisting) {
                    persistReconciliationBlock('This batch stopped after one or more ads were created. Reconcile the created rows before starting another batch.');
                }
                // Don't advance — the batch is incomplete by definition and Joel
                // needs to see how far it got before deciding what to re-run.
                setProgress({ current: attempted, total: launchAds.length, status: `Stopped — ${createdIndexes.length} of ${launchAds.length} ads created` });
                setLoading(false);
            } else if (failedCount === 0) {
                // All ads created — auto-advance after brief success display
                setProgress({ current: launchAds.length, total: launchAds.length, status: 'Complete!' });
                setTimeout(() => { onNext(); }, 1500);
            } else {
                if (createdAdIds.length > 0 || !campaignData.isExisting || !adsetData.isExisting) {
                    persistReconciliationBlock('This batch partially completed. Reconcile the created rows before starting another batch.');
                }
                // Partial failure — stay on screen so Joel can see what failed
                setProgress({ current: launchAds.length, total: launchAds.length, status: `${createdIndexes.length} of ${launchAds.length} ads created` });
                setLoading(false);
            }

        } catch (error) {
            console.error('Error in bulk ad creation:', error);
            // A toast alone auto-dismisses after a few seconds. For campaign/ad-set
            // creation failures — which can mean "N ad sets already exist on Meta,
            // don't re-launch from scratch" (the per-media loop above especially) —
            // that's the weakest treatment in this file for the message most likely
            // to cause real damage if missed: a buyer multitasking through an 8-20
            // ad batch clicks Create again and duplicates ad sets/spend. Route into
            // the same persistent red panel every other partial-failure path here
            // already uses, not just a toast. Caught in pre-push review.
            showError(`Error: ${error.message}`);
            if (error.metaMutationStarted || !campaignData.isExisting || !adsetData.isExisting) {
                persistReconciliationBlock(error.message);
            }
            setErrors(prev => [...prev, error.message]);
            setLoading(false);
        }
    };

    return (
        <div>
            <h2 className="text-2xl font-bold mb-2">{isDriveManifest ? (driveManifestCreatesSeparateAdsets ? 'Review bulk ad sets' : 'Review bulk ads') : 'Review & Launch Ads'}</h2>
            <p className="text-gray-600 mb-6">
                {isDriveManifest
                    ? driveManifestCreatesSeparateAdsets
                        ? 'Each selected Feed + Stories pair becomes one paused ad in its own new ad set. Use the compact manifest to organize, inspect, and select pairs without reviewing a wall of full-size ad previews.'
                        : driveManifestUsesExistingAdset
                            ? 'Each selected Feed + Stories pair becomes one paused ad in the selected existing ad set. Use the compact manifest to organize, inspect, and select pairs without reviewing a wall of full-size ad previews.'
                            : 'Each selected Feed + Stories pair becomes one paused ad in the new shared ad set. Use the compact manifest to organize, inspect, and select pairs without reviewing a wall of full-size ad previews.'
                    : 'The app has automatically generated one ad for every combination of your images, headlines, and body copy. Each row below is one ad that will be created on Facebook.'}
            </p>

            {/* Summary */}
            <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 mb-6">
                <h3 className="font-semibold text-blue-900 mb-2">Summary</h3>
                <div className="text-sm text-blue-800 space-y-1">
                    <div><strong>Campaign:</strong> {campaignData.name}</div>
                    {campaignData.budgetType === 'CBO' && (
                        <div><strong>Campaign Budget:</strong> {campaignData.budgetScheduleType === 'LIFETIME'
                            ? `$${Number(campaignData.lifetimeBudget).toFixed(2)} total (lifetime)`
                            : `$${Number(campaignData.dailyBudget).toFixed(2)} / day`}
                        </div>
                    )}
                    <div><strong>Ad Set:</strong> {adsetData.name}</div>
                    {campaignData.budgetType === 'ABO' && (
                        <div><strong>Ad Set Budget:</strong> {adsetData.budgetScheduleType === 'LIFETIME'
                            ? `$${Number(adsetData.lifetimeBudget).toFixed(2)} total (lifetime)`
                            : `$${Number(adsetData.dailyBudget).toFixed(2)} / day`}
                        </div>
                    )}
                    <div><strong>Creative Name:</strong> {creativeData.creativeName}</div>
                    <div>
                        <strong>Media:</strong>{' '}
                        {(() => {
                            const images = creativeData.creatives?.filter(c => c.mediaType !== 'video').length || 0;
                            const videos = creativeData.creatives?.filter(c => c.mediaType === 'video').length || 0;
                            const parts = [];
                            if (images > 0) parts.push(`${images} image${images !== 1 ? 's' : ''}`);
                            if (videos > 0) parts.push(`${videos} video${videos !== 1 ? 's' : ''}`);
                            return parts.join(', ') || '0 files';
                        })()}
                    </div>
                    <div><strong>{isDriveManifest ? (driveManifestCreatesSeparateAdsets ? 'Selected pairs / new ad sets' : 'Selected pairs / ads') : 'Total Ads to Create'}:</strong> {isDriveManifest ? `${activeAds.length} / ${adsData.length}` : adsData.length} ({(() => {
                        const hasPerCreativeCopy = creativeData.creatives?.some(c => c.headline || c.body);
                        if (hasPerCreativeCopy) return 'per-ad copy assignments';
                        const images = creativeData.creatives?.filter(c => c.mediaType !== 'video').length || 0;
                        const videos = creativeData.creatives?.filter(c => c.mediaType === 'video').length || 0;
                        const media = images + videos;
                        const headlines = creativeData.headlines?.filter(h => h && h.trim()).length || 0;
                        const bodies = creativeData.bodies?.filter(b => b && b.trim()).length || 0;
                        return `${media} media × ${headlines} headline${headlines !== 1 ? 's' : ''} × ${bodies} body`;
                    })()})</div>
                    {manifestExcludedAdIds.size > 0 && (
                        <div><strong>Excluded:</strong> {manifestExcludedAdIds.size} ad{manifestExcludedAdIds.size !== 1 ? 's' : ''} removed from this batch</div>
                    )}
                    {driveManifestUsesExistingAdset && driveManifestHasDualPlacement && (
                        <div className={`mt-2 rounded px-2 py-1.5 text-xs font-medium ${existingPlacementStatus === 'unverified' ? 'bg-amber-100 text-amber-900' : 'bg-emerald-100 text-emerald-800'}`}>
                            {existingPlacementStatus === 'unverified'
                                ? 'Placement contract not verified — launch is blocked until this existing ad set is limited to the supplied Feed + Stories placements.'
                                : existingPlacementStatus === 'verified-facebook-only'
                                    ? 'Placement verified: Facebook Feed + Stories only. Instagram is not enabled on this existing ad set.'
                                    : 'Placement verified: Facebook Feed + Stories and Instagram Stream, Stories, and Reels.'}
                        </div>
                    )}
                    {/* Per-media mode creates its OWN ad-set breakdown below — the
                        feed/stories "2 ad sets" banner describes a model that isn't
                        actually in use here (per-media can create many more than 2,
                        each already correctly feed/stories/dual-targeted per its own
                        creative), and its ABO "×2" math would be flatly wrong once
                        the real multiplier is N media files, not 2. Gating these away
                        instead of just leaving them to render alongside the per-media
                        banner avoids showing two contradictory ad-set-count stories on
                        the same screen. Caught in pre-push review. */}
                    {isMixedFormat && !perMediaModeActive && (
                        <div className="mt-2 pt-2 border-t border-blue-200 space-y-0.5">
                            <div className="font-semibold text-blue-800">🗂 2 ad sets will be used:</div>
                            {adsetData.isExisting ? (
                                <>
                                    <div className="ml-2">• <strong>{feedAds.length} Feed ad{feedAds.length !== 1 ? 's' : ''}</strong> (1:1) → <em>{adsetData.name}</em> <span className="text-blue-600">(existing)</span></div>
                                    <div className="ml-2">• <strong>{storiesAds.length} Stories & Reels ad{storiesAds.length !== 1 ? 's' : ''}</strong> (9:16) → <em>{adsetData.name} - Stories & Reels</em> <span className="text-blue-600">(new)</span></div>
                                </>
                            ) : (
                                <>
                                    <div className="ml-2">• <strong>{feedAds.length} Feed ad{feedAds.length !== 1 ? 's' : ''}</strong> (1:1) → <em>{adsetData.name} - Feed</em></div>
                                    <div className="ml-2">• <strong>{storiesAds.length} Stories & Reels ad{storiesAds.length !== 1 ? 's' : ''}</strong> (9:16) → <em>{adsetData.name} - Stories & Reels</em></div>
                                </>
                            )}
                        </div>
                    )}
                    {isMixedFormat && !perMediaModeActive && campaignData.budgetType === 'ABO' && (
                        <div className="mt-2 pt-2 border-t border-blue-200 text-sm font-medium text-amber-700">
                            ⚠️ ABO: each ad set gets its own budget —{' '}
                            {adsetData.budgetScheduleType === 'LIFETIME'
                                ? `total lifetime spend will be $${(Number(adsetData.lifetimeBudget || 0) * 2).toFixed(2)}`
                                : `total daily spend will be $${(Number(adsetData.dailyBudget || 0) * 2).toFixed(2)}/day`
                            }.
                        </div>
                    )}
                    {allStoriesFormat && !perMediaModeActive && (
                        <div className="mt-1 text-blue-700 font-medium">📱 All creatives are 9:16 — ad set will target Stories & Reels only</div>
                    )}
                    {perMediaModeActive && (() => {
                        // Same "state the literal computed outcome in one sentence" pattern
                        // as Birch's Stage build card ("Creates N ads in M ad sets") — the
                        // most portable single detail from that competitor capture.
                        const distinctMediaCount = new Set(adsData.map(ad => ad.creativeId)).size;
                        return (
                            <div className="mt-2 pt-2 border-t border-blue-200 text-sm space-y-1">
                                <div className="font-semibold text-blue-800">
                                    🗂 Creates {adsData.length} ad{adsData.length !== 1 ? 's' : ''} in {distinctMediaCount} new ad set{distinctMediaCount !== 1 ? 's' : ''} — one ad set per media file
                                </div>
                                {isMixedFormat && (
                                    <div className="text-blue-700">Each ad set targets Feed (1:1) or Stories & Reels (9:16) based on that file's own format.</div>
                                )}
                                {campaignData.budgetType === 'ABO' && (
                                    <div className="font-medium text-amber-700">
                                        ⚠️ ABO: EVERY one of these {distinctMediaCount} ad sets gets its own full budget —{' '}
                                        {adsetData.budgetScheduleType === 'LIFETIME'
                                            ? `total lifetime spend will be $${(Number(adsetData.lifetimeBudget || 0) * distinctMediaCount).toFixed(2)}`
                                            : `total daily spend will be $${(Number(adsetData.dailyBudget || 0) * distinctMediaCount).toFixed(2)}/day`
                                        } — not $
                                        {adsetData.budgetScheduleType === 'LIFETIME'
                                            ? Number(adsetData.lifetimeBudget || 0).toFixed(2)
                                            : Number(adsetData.dailyBudget || 0).toFixed(2)
                                        }.
                                    </div>
                                )}
                            </div>
                        );
                    })()}
                </div>
            </div>

            {/* Ad naming pattern — previously only settable by hand-editing the
                adNamingPattern localStorage key, no in-app control at all. Changing
                it here does NOT retroactively touch the ads already listed below
                (that would silently wipe manual renames/exclusions) — the button
                applies it to the current batch on purpose. The banner below is what
                makes that two-step model visible instead of silent: without it,
                Joel could edit the field, see no change in the grid, and assume
                either "broken" or "already applied" — and launch on stale names
                either way (pre-push review, joel-perspective: P1). */}
            <div className="bg-gray-50 border border-gray-200 rounded-lg p-4 mb-6">
                <label className="block text-sm font-semibold text-gray-700 mb-2">
                    Ad Naming Pattern
                </label>
                <NamingTemplateField
                    value={adNamingPattern}
                    onChange={handleAdNamingPatternChange}
                    placeholder="{media_name} - H{headline_num}B{body_num}"
                    tokens={adNamingTokens}
                    tokenList={adNamingTokenList}
                    scope="ad"
                />
                {adNamingPattern !== lastAppliedNamingPattern && adsData.length > 0 ? (
                    <div className="mt-3 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2">
                        <span className="text-xs font-medium text-amber-800">
                            Pattern changed — the {adsData.length} ad{adsData.length !== 1 ? 's' : ''} below still use the previous one.
                        </span>
                        <button
                            type="button"
                            onClick={applyNamingPatternToCurrentAds}
                            className="px-3 py-1.5 bg-amber-600 text-white rounded-lg text-xs font-semibold hover:bg-amber-700"
                        >
                            Rename {adsData.length} ad{adsData.length !== 1 ? 's' : ''} now
                        </button>
                    </div>
                ) : (
                    <div className="mt-2 flex items-center gap-3">
                        <button
                            type="button"
                            onClick={applyNamingPatternToCurrentAds}
                            disabled={adsData.length === 0}
                            className="text-xs font-semibold text-amber-700 hover:text-amber-900 disabled:opacity-40 disabled:cursor-not-allowed"
                        >
                            Re-apply this pattern to the current {adsData.length} ad{adsData.length !== 1 ? 's' : ''}
                        </button>
                        <span className="text-xs text-gray-500">New ads generated after a Back/Next use it automatically.</span>
                    </div>
                )}
            </div>

            {!loading ? (
                <>
                    {/* Undo banners — the exclude ("✕") button on this dense grid is a
                        smaller, closer-together target than the old isolated row button
                        it replaced, with no confirm step. This is the safety net for a
                        misclick, not a confirm dialog on every exclude (CLAUDE.md bans
                        native confirm() outright, and a modal on every card-corner click
                        would be worse friction than the problem it solves).
                        `sticky top-2` — flagged in review: at a real 15-20 ad batch, a
                        misclick usually happens scrolled well past the top of the grid,
                        and a banner in normal document flow above it renders off-screen
                        exactly when it's needed. A stack (not one slot) — a second
                        exclude within the window no longer silently overwrites the
                        first one's undo with no indication anything was lost. */}
                    {removedStack.length > 0 && (
                        <div className="sticky top-2 z-20 space-y-2 mb-3">
                            {removedStack.map(entry => (
                                <div key={entry.key} className="flex items-center justify-between gap-3 px-4 py-2.5 bg-gray-800 text-white text-sm rounded-lg shadow-lg">
                                    <span>Removed "{entry.ad.name}"</span>
                                    <div className="flex items-center gap-3 flex-shrink-0">
                                        <button onClick={() => undoRemove(entry.key)} className="font-semibold text-amber-300 hover:text-amber-200">Undo</button>
                                        <button onClick={() => setRemovedStack(prev => prev.filter(r => r.key !== entry.key))} className="text-gray-400 hover:text-gray-200" aria-label="Dismiss">
                                            <X size={14} />
                                        </button>
                                    </div>
                                </div>
                            ))}
                        </div>
                    )}

                    {isDriveManifest ? (
                        <div className="mb-5">
                            <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
                                <div className="rounded-lg border border-gray-200 bg-white px-3 py-2.5">
                                    <div className="text-[11px] font-semibold uppercase tracking-wide text-gray-500">{driveManifestCreatesSeparateAdsets ? 'Selected new ad sets' : 'Selected ads'}</div>
                                    <div className="mt-0.5 text-xl font-bold text-gray-900">{activeAds.length} <span className="text-sm font-medium text-gray-500">/ {adsData.length}</span></div>
                                </div>
                                <div className="rounded-lg border border-gray-200 bg-white px-3 py-2.5">
                                    <div className="text-[11px] font-semibold uppercase tracking-wide text-gray-500">Feed + Stories pairs</div>
                                    <div className="mt-0.5 text-xl font-bold text-gray-900">{activeAds.filter(ad => ad.dualPlacement).length}</div>
                                </div>
                                <div className="rounded-lg border border-gray-200 bg-white px-3 py-2.5">
                                    <div className="text-[11px] font-semibold uppercase tracking-wide text-gray-500">Copy ready</div>
                                    <div className={`mt-0.5 text-xl font-bold ${manifestReadyCount === activeAds.length ? 'text-emerald-700' : 'text-amber-700'}`}>{manifestReadyCount} / {activeAds.length}</div>
                                </div>
                                <div className="rounded-lg border border-gray-200 bg-white px-3 py-2.5">
                                    <div className="text-[11px] font-semibold uppercase tracking-wide text-gray-500">Facebook page</div>
                                    <div className="mt-1 truncate text-sm font-semibold text-gray-900">{creativeData.pageName || 'Page not confirmed'}</div>
                                    <div className={`mt-0.5 truncate text-[11px] ${creativeData.instagramId ? 'text-emerald-700' : 'text-amber-700'}`}>
                                        Instagram: {creativeData.instagramId ? `linked (${creativeData.instagramId})` : 'not linked'}
                                    </div>
                                    <div className="text-[11px] text-gray-500">Feed + Stories/Reels placement</div>
                                </div>
                            </div>

                                <section className="overflow-hidden rounded-xl border border-gray-200 bg-white">
                                    <div className="flex flex-wrap items-center gap-2 border-b border-gray-200 p-3">
                                        <input
                                            value={manifestSearch}
                                            onChange={(event) => setManifestSearch(event.target.value)}
                                            placeholder="Search category, creative, ad set, or copy"
                                            className="min-w-[210px] flex-1 rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-amber-500 focus:ring-2 focus:ring-amber-100"
                                        />
                                        <select
                                            value={manifestCategory}
                                            onChange={(event) => setManifestCategory(event.target.value)}
                                            className="rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm focus:border-amber-500 focus:ring-2 focus:ring-amber-100"
                                        >
                                            <option value="all">All categories</option>
                                            {manifestCategories.map(category => <option key={category} value={category}>{category}</option>)}
                                        </select>
                                        <button type="button" onClick={() => setVisibleManifestSelection(true)} className="rounded-lg border border-gray-300 px-3 py-2 text-xs font-semibold text-gray-700 hover:bg-gray-50">
                                            Select visible
                                        </button>
                                        <button type="button" onClick={() => setVisibleManifestSelection(false)} className="rounded-lg border border-gray-300 px-3 py-2 text-xs font-semibold text-gray-700 hover:bg-gray-50">
                                            Deselect visible
                                        </button>
                                    </div>
                                    <div className="hidden grid-cols-[28px_minmax(220px,1.7fr)_minmax(100px,.8fr)_96px_80px] gap-3 bg-gray-50 px-4 py-2.5 text-[10px] font-semibold uppercase tracking-wide text-gray-500 md:grid">
                                        <span />
                                        <span>Ad set / creative</span>
                                        <span>Category</span>
                                        <span>Copy</span>
                                        <span className="text-right">Details</span>
                                    </div>
                                    <div className="max-h-[680px] overflow-y-auto">
                                        {visibleManifestRows.length === 0 ? (
                                            <p className="px-4 py-10 text-center text-sm text-gray-500">No ad pairs match those filters.</p>
                                        ) : visibleManifestRows.map(row => {
                                            const selected = row.ad.id === selectedManifestRow?.ad.id;
                                            const included = !manifestExcludedAdIds.has(row.ad.id);
                                            return (
                                                <div
                                                    key={row.ad.id}
                                                    role="button"
                                                    tabIndex={0}
                                                    onClick={() => { setSelectedManifestAdId(row.ad.id); setEditDrawerOpen(true); }}
                                                    onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') { setSelectedManifestAdId(row.ad.id); setEditDrawerOpen(true); } }}
                                                    className={`grid cursor-pointer grid-cols-[28px_minmax(0,1fr)_auto] items-center gap-3 border-t border-gray-100 px-4 py-3 transition-colors md:grid-cols-[28px_minmax(220px,1.7fr)_minmax(100px,.8fr)_96px_80px] ${selected ? 'bg-amber-50 shadow-[inset_3px_0_0_0_#d97706]' : included ? 'hover:bg-gray-50' : 'bg-gray-50 opacity-60'}`}
                                                >
                                                    <input
                                                        type="checkbox"
                                                        checked={included}
                                                        onClick={(event) => event.stopPropagation()}
                                                        onChange={() => toggleManifestAd(row.ad.id)}
                                                        aria-label={`Include ${row.ad.name}`}
                                                        className="h-4 w-4 rounded border-gray-300 text-amber-600 focus:ring-amber-500"
                                                    />
                                                    <div className="flex min-w-0 items-center gap-3">
                                                        <div className="flex h-12 w-[58px] shrink-0 gap-0.5 overflow-hidden rounded-md border border-gray-200 bg-gray-100">
                                                            {row.creative?.previewUrl && <img src={row.creative.previewUrl} alt="Feed creative" className="w-1/2 object-cover" />}
                                                            {row.creative?.secondaryImageUrl ? <img src={row.creative.secondaryImageUrl} alt="Stories creative" className="w-1/2 object-cover" /> : row.creative?.previewUrl && <img src={row.creative.previewUrl} alt="Creative" className="w-1/2 object-cover" />}
                                                        </div>
                                                        <div className="min-w-0">
                                                            <div className="truncate text-sm font-semibold text-gray-900">{row.adsetName}</div>
                                                            <div className="truncate text-xs text-gray-500">Ad: {row.ad.name} · {row.ad.dualPlacement ? 'Feed + Stories' : row.ad.format === 'stories' ? 'Stories & Reels' : 'Feed'}</div>
                                                        </div>
                                                    </div>
                                                    <div className="hidden min-w-0 md:block">
                                                        <div className="truncate text-sm text-gray-700">{row.category}</div>
                                                        <div className="text-xs text-gray-400">{row.destinationLabel}</div>
                                                    </div>
                                                    <div className="hidden md:block">
                                                        <span className={`inline-flex rounded-full px-2 py-1 text-[11px] font-semibold ${row.copyReady ? 'bg-emerald-100 text-emerald-700' : 'bg-amber-100 text-amber-800'}`}>{row.copyReady ? 'Ready' : 'Needs copy'}</span>
                                                        {row.outcome && <span className={`mt-1 inline-flex rounded-full px-2 py-1 text-[11px] font-semibold ${row.outcome.cls}`}>{row.outcome.label}</span>}
                                                    </div>
                                                    <button type="button" onClick={(event) => { event.stopPropagation(); setSelectedManifestAdId(row.ad.id); setEditDrawerOpen(true); }} className="text-right text-xs font-semibold text-amber-700 hover:text-amber-900">Open →</button>
                                                </div>
                                            );
                                        })}
                                    </div>
                                </section>
                        </div>
                    ) : (
                    /* Ads Preview Grid — one native-style Facebook feed-preview card per
                        combination, instead of a thumbnail + rename row. Shows the actual
                        headline/body text for that specific combination so a bad pairing is
                        visible before launch, not just trusted from the permutation math. */
                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4 mb-4">
                        {adsData.map((ad, index) => {
                            const creative = creativeData.creatives?.find(c => c.id === ad.creativeId);
                            const isVideo = creative?.mediaType === 'video';
                                    const headline = ad.headlineOverride || creativeData.headlines?.[ad.headlineIndex];
                                    const body = ad.bodyOverride || creativeData.bodies?.[ad.bodyIndex];
                                    const description = creative?.description ?? creativeData.description;
                            // Distinct from a real confirmed name — never render the unconfirmed
                            // placeholder with the same confident styling as a real Page name.
                            // A stale-but-real-looking name (or a generic "Your Page" that reads
                            // as literally correct) is worse than an obvious "unconfirmed" label,
                            // since this card exists specifically to be trusted before launch.
                            const pageConfirmed = Boolean(creativeData.pageName);
                            const pageName = creativeData.pageName || 'Page not confirmed';
                            // "Add a Custom Ad" produces a permutation with no creative/headline/
                            // body attached (no follow-up form exists to fill those in) — it is
                            // guaranteed to fail against Meta. Show that plainly instead of a
                            // normal-looking sparse card.
                            const isEmptyCustomAd = !creative && !headline && !body;
                            // After a throttled launch, say per card what happened.
                            // "Not attempted" is the important one — those are the
                            // ads still missing from Meta.
                            let outcome = null;
                            if (launchOutcome) {
                                if (launchOutcome.createdAdIds?.includes(ad.id) || launchOutcome.createdIndexes?.includes(index)) {
                                    outcome = { label: 'Created', cls: 'bg-emerald-100 text-emerald-700' };
                                } else if (launchOutcome.createdButUnmirroredAdIds?.includes(ad.id)) {
                                    outcome = { label: 'Created in Meta — reconcile', cls: 'bg-amber-100 text-amber-900' };
                                } else if (launchOutcome.uncertainAdIds?.includes(ad.id)) {
                                    outcome = { label: 'Needs reconciliation', cls: 'bg-amber-100 text-amber-900' };
                                } else if (launchOutcome.attemptedAdIds && !launchOutcome.attemptedAdIds.includes(ad.id)) {
                                    outcome = { label: 'Not attempted', cls: 'bg-amber-100 text-amber-800' };
                                } else if (index > launchOutcome.stoppedAtIndex) {
                                    // Backward-compatible fallback for an outcome recorded
                                    // before IDs were tracked.
                                    outcome = { label: 'Not attempted', cls: 'bg-amber-100 text-amber-800' };
                                } else {
                                    outcome = { label: 'Failed', cls: 'bg-red-100 text-red-700' };
                                }
                            }
                            return (
                                <div key={ad.id} className={`relative flex flex-col rounded-lg border overflow-hidden ${
                                    outcome?.label === 'Not attempted'
                                        ? 'bg-amber-50 border-amber-200'
                                        : 'bg-white border-gray-200'
                                }`}>
                                    {/* Exclude-before-launch — same removeAd used by the old row list,
                                        just relocated onto the card corner (AdEspresso's "✕" on its
                                        preview grid). */}
                                    {/* Distinct at-rest colors (blue vs. red), not just hover state,
                                        plus a wider gap than a single icon's width apart — a fast
                                        click-through of a dense grid must not confuse "edit" with
                                        the destructive "exclude" action (joel-perspective review). */}
                                    <div className="absolute top-2 right-2 z-10 flex gap-2">
                                        <button
                                            onClick={() => { setSelectedManifestAdId(ad.id); setEditDrawerOpen(true); }}
                                            title="Edit this ad's copy"
                                            className="p-1 rounded-full bg-blue-50 text-blue-600 hover:text-blue-800 hover:bg-blue-100 shadow-sm transition-colors"
                                        >
                                            <Pencil size={13} />
                                        </button>
                                        <button
                                            onClick={() => removeAd(index)}
                                            title="Exclude this ad from the launch"
                                            className="p-1 rounded-full bg-white/90 text-red-500 hover:text-red-700 hover:bg-white shadow-sm transition-colors"
                                        >
                                            <X size={14} />
                                        </button>
                                    </div>

                                    {/* Status strip: launch outcome + format, top of card */}
                                    <div className="flex items-center gap-2 px-3 pt-3">
                                        {outcome && (
                                            <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${outcome.cls}`}>
                                                {outcome.label}
                                            </span>
                                        )}
                                        <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                                            ad.format === 'stories'
                                                ? 'bg-purple-100 text-purple-700'
                                                : 'bg-blue-100 text-blue-700'
                                        }`}>
                                            {ad.format === 'stories' ? '9:16' : '1:1'}
                                        </span>
                                    </div>

                                    {/* Native-style header: Page name + "Sponsored", like the real
                                        feed unit this ad will render as. Unconfirmed name gets a
                                        visibly different (gray/italic/dashed-avatar) treatment —
                                        never the same confident styling as a real, resolved name. */}
                                    <div className="flex items-center gap-2 px-3 pt-2 pb-2">
                                        <div className={`w-8 h-8 rounded-full flex items-center justify-center text-xs font-semibold flex-shrink-0 ${
                                            pageConfirmed ? 'bg-gray-200 text-gray-500' : 'bg-gray-100 text-gray-400 border border-dashed border-gray-300'
                                        }`}>
                                            {pageConfirmed ? (pageName.trim().charAt(0).toUpperCase() || 'P') : '?'}
                                        </div>
                                        <div className="min-w-0">
                                            <div className={`text-sm truncate ${pageConfirmed ? 'font-semibold text-gray-900' : 'italic text-gray-400'}`}>
                                                {pageName}
                                            </div>
                                            <div className="text-xs text-gray-500">Sponsored</div>
                                        </div>
                                    </div>

                                    {/* Body copy — an explicit placeholder when missing, not a
                                        silently sparse card. A blank paragraph reads as "this
                                        variant just has no caption"; this reads as "check this."
                                        Skipped for an empty custom-ad slot — the red banner below
                                        already covers that case comprehensively. */}
                                    {!isEmptyCustomAd && (body ? (
                                        <p className="px-3 pb-2 text-sm text-gray-800 line-clamp-3">{body}</p>
                                    ) : (
                                        <p className="px-3 pb-2 text-sm italic text-amber-700">No body text — check this combination</p>
                                    ))}

                                    {/* Media — aspect ratio matches this ad's actual placement
                                        format, not a generic feed+story pair like AdEspresso shows
                                        for every combination regardless of relevance. A "Custom Ad"
                                        slot (added via the button below) has no creative attached
                                        and no follow-up form to add one — it is guaranteed to fail
                                        against Meta on launch. Say that plainly instead of rendering
                                        a normal-looking card with a blank media area. */}
                                    {creative ? (
                                        <div className={`bg-gray-200 relative ${ad.dualPlacement && creative.secondaryImageUrl ? 'flex aspect-[16/9]' : ad.format === 'stories' ? 'aspect-[9/16]' : 'aspect-square'}`}>
                                            {ad.dualPlacement && creative.secondaryImageUrl ? (
                                                <>
                                                    <div className="relative w-1/2 border-r-2 border-white">
                                                        <img src={creative.previewUrl} alt="Feed 1:1 preview" className="w-full h-full object-cover" />
                                                        <span className="absolute bottom-2 left-2 rounded bg-blue-600 px-1.5 py-0.5 text-[10px] font-semibold text-white">Feed 1:1</span>
                                                    </div>
                                                    <div className="relative w-1/2">
                                                        <img src={creative.secondaryImageUrl} alt="Stories 9:16 preview" className="w-full h-full object-cover" />
                                                        <span className="absolute bottom-2 left-2 rounded bg-purple-600 px-1.5 py-0.5 text-[10px] font-semibold text-white">Stories 9:16</span>
                                                    </div>
                                                </>
                                            ) : isVideo ? (
                                                <>
                                                    <video src={creative.previewUrl} className="w-full h-full object-cover" muted />
                                                    <div className="absolute bottom-2 right-2 bg-purple-600 text-white p-1 rounded">
                                                        <Film size={12} />
                                                    </div>
                                                </>
                                            ) : (
                                                <>
                                                    <img src={creative.previewUrl} alt="Ad creative" className="w-full h-full object-cover" />
                                                    <div className="absolute bottom-2 right-2 bg-blue-600 text-white p-1 rounded">
                                                        <Image size={12} />
                                                    </div>
                                                </>
                                            )}
                                        </div>
                                    ) : isEmptyCustomAd ? (
                                        <div className="px-3 py-4 bg-red-50 border-y border-red-200 text-sm text-red-800">
                                            <strong>No creative attached.</strong> This ad will fail on launch — remove it or attach media/copy before continuing.
                                        </div>
                                    ) : null}

                                    {/* Link strip — domain + headline + CTA button, exactly the
                                        block that sits under the image on a real Facebook ad.
                                        Skipped for an empty custom-ad slot — a CTA/domain/headline
                                        row would be meaningless chrome around a guaranteed failure. */}
                                    {!isEmptyCustomAd && (() => {
                                        // Mirrors the headline/body pattern above: prefer the
                                        // per-creative override (e.g. a Drive-matched pair's own
                                        // CTA/landing URL from its strategy doc) over the global
                                        // form field. This card exists specifically so a bad
                                        // pairing is visible before launch — it was previously
                                        // always showing the GLOBAL cta/websiteUrl here even when
                                        // Meta would actually receive a different, correct
                                        // per-creative value, which is the opposite of what a
                                        // pre-launch review card is for (joel-perspective pre-push
                                        // review, P1).
                                        // Same three-way fallback the actual submit path uses
                                        // (~line 680) — matching it exactly, not just the
                                        // two-tier headline/body shape, since cta has its own
                                        // separate ad.ctaOverride tier the others don't.
                                        const websiteUrl = creative?.websiteUrl || creativeData.websiteUrl;
                                        const cta = creative?.cta || ad.ctaOverride || creativeData.cta;
                                        return (
                                            <div className="flex items-center justify-between gap-2 px-3 py-2 bg-gray-50 border-t border-gray-200">
                                                <div className="min-w-0">
                                                    {websiteUrl && (
                                                        <div className="text-[11px] uppercase text-gray-400 truncate">{displayDomain(websiteUrl)}</div>
                                                    )}
                                            <div className="text-sm font-semibold text-gray-900 truncate">{headline || '—'}</div>
                                            {description && <div className="text-[11px] text-gray-500 truncate">{description}</div>}
                                                </div>
                                                <span className="flex-shrink-0 text-xs font-medium px-3 py-1.5 rounded bg-gray-200 text-gray-700">
                                                    {formatCtaLabel(cta)}
                                                </span>
                                            </div>
                                        );
                                    })()}

                                    {/* Rename — same input as before, moved into the card footer */}
                                    <div className="px-3 py-2 border-t border-gray-100">
                                        <input
                                            type="text"
                                            value={ad.name}
                                            onChange={(e) => updateAdName(index, e.target.value)}
                                            placeholder={`Ad ${index + 1} name`}
                                            className="w-full px-2 py-1.5 text-sm border border-gray-300 rounded focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                                        />
                                    </div>
                                </div>
                            );
                        })}
                    </div>
                    )}

                    {/* "Add a Custom Ad" removed — it produced a permutation with no
                        creative/headline/body attached and no follow-up form to fill
                        those in, a guaranteed-to-fail dead end (flagged in pre-push
                        review of the preview-grid work, where it got an explicit
                        "will fail" card treatment instead of a real fix). Removing the
                        trap rather than building the missing attach-creative form,
                        which nothing has asked for. */}

                    {/* Meta rate-limit reading from the last launch attempt. Shown
                        only when Meta actually reported usage — when it doesn't,
                        this stays hidden rather than implying 0%. */}
                    {rateLimitUsage?.available && peakUsagePercent(rateLimitUsage.usage) !== null && (
                        <div className="mt-6">
                            {(() => {
                                const peak = Math.round(peakUsagePercent(rateLimitUsage.usage));
                                const hot = peak >= USAGE_WARN_THRESHOLD;
                                // Label the scope honestly. x-business-use-case-usage is
                                // keyed by Business Manager, so with eight ad accounts under
                                // one business its counters are shared across all of them —
                                // calling that "this ad account" would be wrong.
                                const scope = {
                                    ad_account: 'this ad account',
                                    business: 'shared across the business',
                                    app: 'shared app-wide',
                                }[rateLimitUsage.scope] || 'scope unknown';
                                return (
                                    <div className={`rounded-lg border px-4 py-3 text-sm ${hot ? 'bg-amber-50 border-amber-200 text-amber-900' : 'bg-gray-50 border-gray-200 text-gray-700'}`}>
                                        <div className="flex items-center justify-between gap-3">
                                            <span>
                                                Meta rate limit — <strong>{peak}%</strong> used ({scope})
                                            </span>
                                            <div className="h-1.5 w-32 shrink-0 rounded-full bg-gray-200 overflow-hidden">
                                                <div
                                                    className={`h-full rounded-full ${hot ? 'bg-amber-500' : 'bg-emerald-500'}`}
                                                    style={{ width: `${Math.min(100, peak)}%` }}
                                                />
                                            </div>
                                        </div>
                                        {hot && (
                                            <p className="mt-1 text-xs">
                                                Launch 5-10 ads at a time, or wait ~15 minutes. A throttled batch stops and marks which ads were created.
                                            </p>
                                        )}
                                    </div>
                                );
                            })()}
                        </div>
                    )}

                    {/* Errors — partial launch failure */}
                    {errors.length > 0 && (
                        <div className="mt-6 space-y-3">
                            {launchOutcome && (
                                <div className="bg-gray-50 border border-gray-200 rounded-lg px-4 py-3 text-sm text-gray-700">
                                    Launch stopped after {launchOutcome.createdAdIds?.length ?? 0} of {activeAds.length} ads.
                                    {' '}{launchOutcome.createdAdIds?.length ?? 0} ad{(launchOutcome.createdAdIds?.length ?? 0) !== 1 ? 's were' : ' was'} created; the rest failed or were not attempted — see below.
                                </div>
                            )}
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

                    {/* Navigation — sticky to the viewport bottom so the primary action
                        stays reachable while scrolling a long review grid, especially on
                        mobile where "scroll all the way down to launch" was the complaint.
                        -mx-6/px-6 cancels the parent workspace card's own p-6 so this bar
                        bleeds to the card's edges instead of floating with a gap on each side. */}
                    <div className="mt-10 flex justify-between items-center sticky bottom-0 -mx-6 bg-white border-t border-gray-200 px-6 py-4 shadow-[0_-4px_12px_-4px_rgba(0,0,0,0.08)]">
                        <button
                            onClick={onBack}
                            className="px-6 py-3 text-gray-600 hover:text-gray-800 font-medium"
                        >
                            Back
                        </button>
                        {requiresReconciliation ? (
                            <span className="max-w-xl text-right text-sm font-medium text-amber-800">This partial batch is locked after Meta writes. Reconcile it in Ads Manager, then start a fresh batch for any remaining rows.</span>
                        ) : errors.length > 0 ? (
                            <div className="flex items-center gap-3">
                                {isDriveManifest ? (
                                    <span className="max-w-md text-sm text-amber-800">
                                        Launch outcome is not safe to replay automatically. Reconcile the named campaign/ad sets in Ads Manager before starting another launch.
                                    </span>
                                ) : <span className="max-w-md text-sm text-amber-800">Review the failures in Ads Manager before starting another batch. This launcher will not replay a partial batch automatically.</span>}
                            </div>
                        ) : (
                                <button
                                    onClick={() => {
                                    const distinctMediaCount = new Set(activeAds.map(ad => ad.creativeId)).size;
                                    const isRiskyLaunch = perMediaModeActive && campaignData.budgetType === 'ABO' && distinctMediaCount > 1;
                                    if (isRiskyLaunch) {
                                        setShowLaunchConfirm(true);
                                    } else {
                                        handleSubmit();
                                    }
                                }}
                                disabled={activeAds.length === 0}
                                className="flex items-center gap-2 px-6 py-3 bg-green-600 text-white rounded-lg font-medium hover:bg-green-700 disabled:bg-gray-300 disabled:cursor-not-allowed"
                            >
                                {isDriveManifest && driveManifestCreatesSeparateAdsets
                                    ? `Create ${activeAds.length} paused ad${activeAds.length !== 1 ? 's' : ''} in ${activeAds.length} new ad set${activeAds.length !== 1 ? 's' : ''} on Facebook`
                                    : `Create ${activeAds.length} ${isDriveManifest ? 'paused ad' : 'Ad'}${activeAds.length !== 1 ? 's' : ''} on Facebook`}
                            </button>
                        )}
                    </div>

                    {/* Confirm gate — per-media + ABO only. Custom modal, not native
                        confirm() (CLAUDE.md bans that outright), and only inserted for
                        the specific combination that stacks N full budgets, not every
                        launch — the common case stays a single click, unchanged. */}
                    {showLaunchConfirm && (() => {
                        const distinctMediaCount = new Set(activeAds.map(ad => ad.creativeId)).size;
                        const perAdsetBudget = adsetData.budgetScheduleType === 'LIFETIME'
                            ? Number(adsetData.lifetimeBudget || 0)
                            : Number(adsetData.dailyBudget || 0);
                        const totalBudget = perAdsetBudget * distinctMediaCount;
                        const unit = adsetData.budgetScheduleType === 'LIFETIME' ? 'total lifetime' : '/day';
                        return (
                            <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50">
                                <div className="bg-white rounded-2xl shadow-xl p-6 w-full max-w-md">
                                    <h2 className="text-lg font-bold text-gray-900 mb-2">Confirm launch</h2>
                                    <p className="text-sm text-gray-600 mb-4">
                                        This creates <strong>{distinctMediaCount} new ad sets</strong> (one per media file),
                                        each carrying its own <strong>${perAdsetBudget.toFixed(2)}{unit === '/day' ? '/day' : ' lifetime'}</strong> budget —
                                        <strong className="text-amber-700"> ${totalBudget.toFixed(2)}{unit === '/day' ? '/day' : ' total'}</strong> once
                                        every ad set is activated in Ads Manager.
                                    </p>
                                    <div className="flex gap-3">
                                        <button onClick={() => setShowLaunchConfirm(false)} className="flex-1 px-4 py-2.5 rounded-lg border border-gray-200 text-gray-700 font-medium hover:bg-gray-50">
                                            Back
                                        </button>
                                        <button
                                            onClick={() => { setShowLaunchConfirm(false); handleSubmit(); }}
                                            className="flex-1 px-4 py-2.5 rounded-lg bg-green-600 text-white font-medium hover:bg-green-700"
                                        >
                                            Launch anyway
                                        </button>
                                    </div>
                                </div>
                            </div>
                        );
                    })()}

                    {/* Shared edit drawer — replaces the old always-open manifest rail with
                        an on-demand panel, and reuses the exact same updateManifestField
                        writes (already flowing into the real launch payload for every ad,
                        standard or Drive) so a standard-mode "Edit" click and a manifest row
                        click land on identical, already-tested behavior. */}
                    {editDrawerOpen && selectedManifestRow && (
                        <div className="fixed inset-0 z-50 flex justify-end">
                            <div
                                className="absolute inset-0 bg-black/40"
                                onClick={() => setEditDrawerOpen(false)}
                            />
                            <div className="relative h-full w-full max-w-md overflow-hidden bg-white shadow-2xl flex flex-col">
                                <div className="flex items-start justify-between gap-3 border-b border-gray-200 px-4 py-3">
                                    <div className="min-w-0">
                                        <h3 className="truncate text-sm font-bold text-gray-900">{selectedManifestRow.adsetName}</h3>
                                        <p className="mt-0.5 text-xs text-gray-500">Ad: {selectedManifestRow.ad.name} · {selectedManifestRow.category} · {selectedManifestRow.ad.dualPlacement ? 'Feed + Stories pair' : 'Single placement'}</p>
                                        <p className="mt-0.5 truncate text-[11px] text-gray-500">Identity: {creativeData.pageName || creativeData.pageId || 'Page not confirmed'} · Instagram {creativeData.instagramId || 'not linked'} · Feed + Stories/Reels</p>
                                    </div>
                                    <div className="flex shrink-0 items-center gap-2">
                                        <span className={`rounded-full px-2 py-1 text-[10px] font-semibold ${selectedManifestRow.copyReady ? 'bg-emerald-100 text-emerald-700' : 'bg-amber-100 text-amber-800'}`}>{selectedManifestRow.copyReady ? 'Ready' : 'Needs copy'}</span>
                                        {selectedManifestRow.outcome && <span className={`rounded-full px-2 py-1 text-[10px] font-semibold ${selectedManifestRow.outcome.cls}`}>{selectedManifestRow.outcome.label}</span>}
                                        <button type="button" onClick={() => setEditDrawerOpen(false)} className="text-gray-400 hover:text-gray-700" aria-label="Close edit drawer">
                                            <X size={18} />
                                        </button>
                                    </div>
                                </div>
                                {/* key forces a remount + fade on every ad switch — a fast click
                                    from one card's pencil to another's must not let the header
                                    text be the only signal that the drawer's content just swapped
                                    to a different ad (joel-perspective review). */}
                                <div key={selectedManifestRow.ad.id} className="flex-1 space-y-3 overflow-y-auto p-4 animate-fade-in">
                                    <div className="flex h-32 gap-1 overflow-hidden rounded-lg bg-gray-100">
                                        {selectedManifestRow.creative?.previewUrl && <div className="relative w-1/2"><img src={selectedManifestRow.creative.previewUrl} alt="Feed 1:1 preview" className="h-full w-full object-cover" /><span className="absolute bottom-1 left-1 rounded bg-blue-600 px-1 py-0.5 text-[9px] font-semibold text-white">Feed 1:1</span></div>}
                                        {selectedManifestRow.creative?.secondaryImageUrl && <div className="relative w-1/2"><img src={selectedManifestRow.creative.secondaryImageUrl} alt="Stories 9:16 preview" className="h-full w-full object-cover" /><span className="absolute bottom-1 left-1 rounded bg-purple-600 px-1 py-0.5 text-[9px] font-semibold text-white">Stories 9:16</span></div>}
                                    </div>
                                    <p className="rounded-lg bg-blue-50 px-3 py-2 text-xs leading-5 text-blue-800">This copy belongs only to this ad. A Meta description is optional.</p>
                                    <label className="block text-xs font-semibold text-gray-700">Primary text *<textarea rows="4" value={selectedManifestRow.body} onChange={(event) => updateManifestField(selectedManifestRow, 'body', event.target.value)} className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm font-normal focus:border-amber-500 focus:ring-2 focus:ring-amber-100" /></label>
                                    <label className="block text-xs font-semibold text-gray-700">Headline *<input value={selectedManifestRow.headline} onChange={(event) => updateManifestField(selectedManifestRow, 'headline', event.target.value)} className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm font-normal focus:border-amber-500 focus:ring-2 focus:ring-amber-100" /></label>
                                    <label className="block text-xs font-semibold text-gray-700">Description <span className="font-normal text-gray-400">(optional)</span><input value={selectedManifestRow.description} onChange={(event) => updateManifestField(selectedManifestRow, 'description', event.target.value)} className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm font-normal focus:border-amber-500 focus:ring-2 focus:ring-amber-100" /></label>
                                    <label className="block text-xs font-semibold text-gray-700">Destination URL *<input value={selectedManifestRow.websiteUrl} onChange={(event) => updateManifestField(selectedManifestRow, 'websiteUrl', event.target.value)} className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm font-normal focus:border-amber-500 focus:ring-2 focus:ring-amber-100" /></label>
                                    <label className="block text-xs font-semibold text-gray-700">Meta CTA * <span className="font-normal text-gray-400">({selectedManifestRow.ctaSource})</span><select value={selectedManifestRow.cta} onChange={(event) => updateManifestField(selectedManifestRow, 'cta', event.target.value)} className="mt-1 w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm font-normal focus:border-amber-500 focus:ring-2 focus:ring-amber-100"><option value="">Select a CTA...</option>{[...META_CTA_OPTIONS].map(cta => <option key={cta} value={cta}>{formatCtaLabel(cta)}</option>)}</select></label>
                                    <label className="block text-xs font-semibold text-gray-700">Ad name<input value={selectedManifestRow.ad.name} onChange={(event) => updateManifestField(selectedManifestRow, 'name', event.target.value)} className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm font-normal focus:border-amber-500 focus:ring-2 focus:ring-amber-100" /></label>
                                </div>
                                <div className="border-t border-gray-200 p-4">
                                    <p className="mb-2 text-center text-[11px] text-gray-400">Changes save automatically as you type — closing is always safe.</p>
                                    <button
                                        type="button"
                                        onClick={() => setEditDrawerOpen(false)}
                                        className="w-full rounded-lg bg-gray-900 px-4 py-2.5 text-sm font-semibold text-white hover:bg-gray-800"
                                    >
                                        Done
                                    </button>
                                </div>
                            </div>
                        </div>
                    )}
                </>
            ) : (
                <>
                    {/* Progress Indicator */}
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
                        <p className="text-gray-600">
                            {progress.current} of {progress.total} ads created
                        </p>
                        {progress.status === 'Complete!' ? (
                            <p className="text-sm text-amber-700 mt-3 font-medium">
                                All ads are <strong>PAUSED</strong> in Meta — go to Ads Manager to activate them when ready.
                            </p>
                        ) : (
                            <p className="text-sm text-gray-500 mt-3">
                                Meta is processing the remaining creatives. Keep this tab open.
                            </p>
                        )}
                    </div>
                </>
            )}
        </div>
    );
};

export default BulkAdCreation;
