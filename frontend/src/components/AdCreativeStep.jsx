import { useToast } from '../context/ToastContext';
import { useAuth } from '../context/AuthContext';
import React, { useState, useEffect, useMemo, useRef } from 'react';
import { ChevronRight, Upload, X, Loader, Trash2, Copy, Film, Image, BookOpen, Check, Layers, FolderOpen, Maximize2, Search } from 'lucide-react';
import { useCampaign } from '../context/CampaignContext';
import { getPages } from '../lib/facebookApi';
import { safeLocalStorageGet, safeLocalStorageSet } from '../lib/safeLocalStorage';
import { cropImageToAspect } from '../lib/imageCrop';
import { useBrands } from '../context/BrandContext';
import CreativeEnhancementsPanel from './CreativeEnhancementsPanel';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1';
// Kept solely as an emergency rollback switch while the row-and-rail editor
// proves itself in production. It is off unless explicitly enabled at build time.
const LEGACY_CREATIVE_EDITOR_ENABLED = import.meta.env.VITE_ENABLE_LEGACY_CREATIVE_EDITOR === 'true';

const ALLOWED_IMAGE_TYPES = ['image/jpeg', 'image/jpg', 'image/png', 'image/gif', 'image/webp'];
const ALLOWED_VIDEO_TYPES = ['video/mp4', 'video/quicktime', 'video/x-msvideo', 'video/webm'];

// Meta copy limits
// Headline: 255 hard limit (truncated after ~27 chars in feed)
// Primary text: 2200 hard limit (truncated after ~125 chars in feed)
// Description: 255 hard limit
const HEADLINE_WARN = 40;
export const HEADLINE_LIMIT = 255;
const BODY_WARN = 125;
export const BODY_LIMIT = 2200;
const DESC_LIMIT = 255;

// Commercial launches are always run from the DailyInsurance.news Page. The
// generic "last used Page" fallback is unsafe here because this browser is
// also used for Home Services, where Trusted Home Service is legitimate.
const isCommercialAdAccount = (adAccount) => /commercial/i.test(adAccount?.name || '');
const findCommercialDefaultPage = (pages) => pages.find(
    page => String(page?.name || '').trim().toLowerCase() === 'dailyinsurance.news'
);

const charCountClass = (len, warn, limit) => {
    if (len > limit) return 'text-red-600 font-semibold';
    if (len > warn) return 'text-amber-600';
    return 'text-gray-400';
};

// Facebook CTA types - confirmed working
export const CTA_OPTIONS = [
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
];

const parseDriveTags = (asset) => {
    if (!asset?.soft_tags) return {};
    if (typeof asset.soft_tags === 'object') return asset.soft_tags;
    try {
        return JSON.parse(asset.soft_tags);
    } catch (e) {
        return {};
    }
};

const hasCopyText = (copy = {}) => Boolean(
    copy.headline?.trim() ||
    copy.primary_text?.trim() ||
    copy.description?.trim()
);
// Meta's link-ad description is optional. Strategy documents reliably supply
// the two fields that define an ad's message (headline + primary text), but
// commonly omit a description; treating that optional field as a failed match
// discarded otherwise-valid Drive copy and blocked the row review entirely.
const hasCompleteCopy = (copy = {}) => Boolean(
    copy.headline?.trim() && copy.primary_text?.trim()
);

const normalizeFilenameBase = (fileName = '') => {
    const withoutExt = fileName.replace(/\.[^.]+$/, '');
    const aspectMatch = withoutExt.match(/(?:^|[_\-\s])(1x1|9x16)(?=$|[_\-\s])/i);
    if (!aspectMatch) return null;
    const aspect = aspectMatch[1].toLowerCase();
    const base = withoutExt
        .replace(/(?:^|[_\-\s])(1x1|9x16)(?=$|[_\-\s])/i, ' ')
        .replace(/[_\-\s]+/g, ' ')
        .trim()
        .toLowerCase();
    return { base, aspect };
};

// Drive packages commonly keep the same creative in sibling folders named
// "1x1" and "9x16" while leaving the exported filenames generic. Use the
// folder only as an aspect hint; it is not a pairing identity.
const folderPlacementHint = (asset) => {
    const pathParts = String(asset?.folder_path || '')
        .split(/[\\/]/)
        .map(part => part.trim().toLowerCase())
        .filter(Boolean);
    const aspectFolder = [...pathParts].reverse().find(part => /^(?:1x1|9x16)(?:\s+(?:images?|assets?))?$/.test(part));
    if (aspectFolder?.startsWith('9x16')) return 'stories';
    if (aspectFolder?.startsWith('1x1')) return 'feed';
    return null;
};

const driveAssetPlacement = (asset) => {
    const tags = parseDriveTags(asset);
    if (tags.aspect === '9x16') return 'stories';
    if (tags.aspect === '1x1') return 'feed';
    const folderHint = folderPlacementHint(asset);
    if (folderHint) return folderHint;
    const parsed = normalizeFilenameBase(asset.file_name || '');
    if (parsed) return parsed.aspect === '9x16' ? 'stories' : 'feed';
    return 'feed';
};

const buildDriveAssetGroups = (assets) => {
    const grouped = new Map();
    assets.forEach(asset => {
        const tags = parseDriveTags(asset);
        // Deliberately NOT using folder_path here — verified live 2026-08-21 that a
        // real manifest's 1x1 and 9x16 versions of the SAME copy_id live in
        // different subfolders ("1x1 Images" vs "9x16 Images" siblings under the
        // package folder), so folder_path made every real pair fail to match.
        // But brand_id + copy_id alone isn't safe either (review, same day): a
        // recurring batch for the same brand can plausibly reuse a short prefix
        // like "HST" and restart numbering at F01, silently merging two unrelated
        // packages' assets. package_folder_id (the resolved package folder, stable
        // across the 1x1/9x16 siblings, set by drive_sync_service._find_package_folder)
        // is the real disambiguator — falls back to copy_id-only for any asset
        // synced before this field existed, matching the prior (narrower) behavior
        // rather than refusing to pair at all.
        const manifestKey = tags.copy_id
            ? `manifest:${asset.brand_id}:${tags.package_folder_id || ''}:${String(tags.copy_id).toLowerCase()}`
            : null;
        const key = manifestKey || `single:${asset.id}`;
        // Filename-based cluster key for assets with no copy_id tag — used
        // ONLY to sort same-creative-different-size singles next to each
        // other in the grid (Joel's complaint: without this, Drive's own
        // "1x1 Images"/"9x16 Images" sibling-folder layout means the natural
        // fetch order clusters ALL 1x1s together and ALL 9x16s together,
        // never adjacent). Deliberately NOT folded into `key` above — an
        // untagged filename match is a display hint, not proof these two
        // files are the same creative. Merging them into one group would
        // make them one `isPair` tile that auto dual-places the "stories"
        // file onto the "feed" creative's ad with no review surface (pre-push
        // review, code-auditor: BLOCKING — a generic filename collision
        // across two unrelated packages, e.g. two different clients both
        // naming a file "final_1x1.jpg"/"final_9x16.jpg", would silently
        // launch a mismatched image to Stories). Real pairing — the kind that
        // actually merges into one dual-placement ad — stays gated on the
        // verified copy_id/package_folder_id manifest tags above.
        const filenameParsed = !manifestKey ? normalizeFilenameBase(asset.file_name || '') : null;
        const packageFolderScope = (asset.folder_path || '').split('/').slice(0, -1).join('/');
        const sortClusterKey = filenameParsed
            ? `filename:${asset.brand_id}:${packageFolderScope}:${filenameParsed.base}`
            : null;
        const existing = grouped.get(key) || {
            key,
            assets: [],
            copy: tags.copy || null,
            landingPage: tags.landing_page || null,
            cta: tags.cta || null,
            // Category-copy documents already tag every matched asset with the
            // category heading that supplied its copy. Preserve that semantic
            // label separately from folder_path: the latter often ends in a
            // layout folder such as "1x1 Images", which is useful for pairing
            // but useless for organizing a 50-row launch manifest.
            category: tags.category || null,
            copyPairingAmbiguous: tags.copy_pairing_status === 'ambiguous',
            sortClusterKey,
        };
        existing.assets.push(asset);
        existing.copy = existing.copy || tags.copy || null;
        existing.landingPage = existing.landingPage || tags.landing_page || null;
        existing.cta = existing.cta || tags.cta || null;
        existing.category = existing.category || tags.category || null;
        existing.copyPairingAmbiguous = existing.copyPairingAmbiguous || tags.copy_pairing_status === 'ambiguous';
        grouped.set(key, existing);
    });

    const latestSyncedAt = (group) => group.assets.reduce((max, asset) => {
        const t = asset.synced_at ? new Date(asset.synced_at).getTime() : 0;
        return Number.isFinite(t) && t > max ? t : max;
    }, 0);

    const groups = Array.from(grouped.values()).map(group => {
        const feedAsset = group.assets.find(asset => driveAssetPlacement(asset) === 'feed') || group.assets[0];
        const storiesAsset = group.assets.find(asset => driveAssetPlacement(asset) === 'stories');
        const isPair = Boolean(feedAsset && storiesAsset && feedAsset.id !== storiesAsset.id);
        const pairedAssets = isPair ? [feedAsset, storiesAsset] : [feedAsset];
        const pairedMetadata = pairedAssets.map(asset => {
            const tags = parseDriveTags(asset);
            return {
                copy: tags.copy || {},
                landingPage: tags.landing_page || '',
                cta: tags.cta || '',
                refreshStatus: tags.copy_refresh_status || 'verified',
            };
        });
        // A Meta description is optional. Drive may represent its absence as
        // either an omitted key or an empty string on the companion asset;
        // canonicalize that one optional field before comparing a pair so a
        // valid Feed/Stories pair is not falsely rejected as mismatched.
        const metadataFingerprints = new Set(pairedMetadata.map(metadata => JSON.stringify({
            ...metadata,
            copy: {
                headline: metadata.copy?.headline || '',
                primary_text: metadata.copy?.primary_text || '',
                description: metadata.copy?.description?.trim() || '',
            },
        })));
        // A Feed/Stories pair must carry the exact same source copy and link
        // data on both files. Never let whichever asset happened to arrive
        // first define a launch row for a partially refreshed pair.
        const pairCopyIntegrityOk = !isPair || (
            pairedMetadata.every(metadata => hasCompleteCopy(metadata.copy))
            && pairedMetadata.every(metadata => metadata.refreshStatus !== 'unverified')
            && metadataFingerprints.size === 1
        );
        return {
            ...group,
            id: group.key,
            displayAsset: feedAsset,
            feedAsset,
            storiesAsset,
            isPair,
            copy: pairCopyIntegrityOk ? group.copy : null,
            landingPage: pairCopyIntegrityOk ? group.landingPage : null,
            cta: pairCopyIntegrityOk ? group.cta : null,
            copyIntegrityIssue: isPair && !pairCopyIntegrityOk,
            copyRefreshUnverified: pairedMetadata.some(metadata => metadata.refreshStatus === 'unverified'),
            copyPairingAmbiguous: group.copyPairingAmbiguous,
            syncedAt: latestSyncedAt(group),
        };
    });

    // A cluster (same-named-different-size singles, see sortClusterKey above)
    // sorts as one unit by its most-recently-synced member, so the two tiles
    // land adjacent instead of scattered by their own individual timestamps.
    const clusterRecency = new Map();
    groups.forEach(group => {
        if (!group.sortClusterKey) return;
        clusterRecency.set(group.sortClusterKey, Math.max(clusterRecency.get(group.sortClusterKey) || 0, group.syncedAt));
    });

    // Most-recently-synced first — gives "Select first N" a predictable,
    // Ads-Manager-like "newest first" meaning instead of whatever arbitrary
    // order the backend/Drive folder structure happened to return (pre-push
    // review, joel-perspective: P2 — "first N" was otherwise a black box).
    return groups
        .map((group, index) => ({ group, index }))
        .sort((a, b) => {
            const aRecency = a.group.sortClusterKey ? clusterRecency.get(a.group.sortClusterKey) : a.group.syncedAt;
            const bRecency = b.group.sortClusterKey ? clusterRecency.get(b.group.sortClusterKey) : b.group.syncedAt;
            if (aRecency !== bRecency) return bRecency - aRecency;
            if (a.group.sortClusterKey && a.group.sortClusterKey === b.group.sortClusterKey) {
                // Same cluster, same recency — feed before its stories counterpart.
                return driveAssetPlacement(a.group.displayAsset) === 'stories' ? 1 : -1;
            }
            return a.index - b.index;
        })
        .map(({ group }) => group);
};

const isDriveGroupSelectionBlocked = (group) => Boolean(
    group?.copyPairingAmbiguous || group?.copyRefreshUnverified || group?.copyIntegrityIssue
);

// Live permutation count for the sticky counter below — mirrors BulkAdCreation.jsx's
// own useEffect (media.length × valid-headlines × valid-bodies) exactly, so the number
// shown here never drifts from what Review actually generates. Kept as a pure function
// (not inline in the component) so the two call sites can't quietly diverge.
const countVariations = (creativeData) => {
    const media = creativeData?.creatives?.length || 0;
    const headlines = (creativeData?.headlines || []).filter(h => h && h.trim() !== '').length;
    const bodies = (creativeData?.bodies || []).filter(b => b && b.trim() !== '').length;
    const hasPerCreativeCopy = (creativeData?.creatives || []).some(c => c.source === 'drive' || c.headline || c.body);
    const total = hasPerCreativeCopy
        ? (creativeData.creatives || []).reduce((sum, creative) => {
            const headlineCount = creative.source === 'drive' || creative.headline?.trim() ? 1 : headlines;
            const bodyCount = creative.source === 'drive' || creative.body?.trim() ? 1 : bodies;
            return sum + (headlineCount * bodyCount);
        }, 0)
        : media * headlines * bodies;
    return { media, headlines, bodies, total, hasPerCreativeCopy };
};

const AdCreativeStep = ({ onNext, onBack, mode = 'combinations' }) => {
    const isMatchImport = mode === 'match-import';
    const { showWarning, showError, showSuccess } = useToast();
    const { authFetch } = useAuth();
    const { creativeData, setCreativeData, selectedAdAccount, adsetData, campaignData, setLaunchSummary } = useCampaign();
    const { brands } = useBrands();
    // Cache keys for creative defaults (URL/headlines/bodies/description/CTA) are scoped
    // by ad account AND campaign — the same ad account can run multiple niches, each with
    // its own destination URL/copy, so account-only scoping would leak the wrong niche's
    // values into a new campaign. campaignData.id is the per-session id CampaignStep
    // generates (`camp_${Date.now()}`) the moment a "Create New Campaign" flow advances
    // past step 1 — it's stable for the life of that flow and unique per flow, so two
    // separate new-campaign sessions on the same ad account never share a cache key the
    // way the literal string 'new' used to. Falls back to 'new' only in the brief window
    // before that id exists. The Facebook Page ID cache is intentionally NOT scoped this
    // way — a brand's Page is stable across its niches on the same account.
    const campaignCacheId = campaignData?.fbCampaignId || campaignData?.id || 'new';
    // Recomputed on every render off creativeData directly (not memoized on a
    // dependency array) — this step's whole job is showing the count change on every
    // keystroke/upload, and the computation itself is three array lengths, not worth
    // the staleness risk of a memo dependency list drifting from the real fields.
    const variationCount = countVariations(creativeData);

    // Feeds the launcher shell's Launch Plan rail — this step owns the creative/
    // headline/body/total-ad counts, so it pushes them up rather than the shell
    // re-deriving them from creativeData and risking a second, drifting formula.
    useEffect(() => {
        setLaunchSummary(prev => ({
            ...prev,
            creativeCount: variationCount.media,
            headlineCount: variationCount.headlines,
            bodyCount: variationCount.bodies,
            totalAds: variationCount.total,
        }));
    }, [variationCount.media, variationCount.headlines, variationCount.bodies, variationCount.total, setLaunchSummary]);

    const [pages, setPages] = useState([]);
    const [loadingPages, setLoadingPages] = useState(false);
    const pageFetchRequestRef = useRef(0);

    const [manualPageEntry, setManualPageEntry] = useState(false);
    const [isDragging, setIsDragging] = useState(false);
    // Defaults ON per Joel's actual ask — he wants Feed (1:1) and Stories (9:16)
    // launched together as the normal case, not something he has to remember to
    // click "Dupe as Stories" for on every single image. Persisted across
    // sessions like the other per-Joel creative preferences (overlayLogoUrl,
    // overlayOfferLine) so it doesn't reset every time he opens the wizard.
    const [autoDupeStories, setAutoDupeStories] = useState(
        () => safeLocalStorageGet('autoDupeStoriesDefault') !== 'false'
    );
    const handleAutoDupeStoriesChange = (checked) => {
        setAutoDupeStories(checked);
        safeLocalStorageSet('autoDupeStoriesDefault', checked ? 'true' : 'false');
    };

    // Generated Ads library modal
    const [showLibraryModal, setShowLibraryModal] = useState(false);
    const [libraryAds, setLibraryAds] = useState([]);
    const [libraryLoading, setLibraryLoading] = useState(false);
    const [selectedLibraryIds, setSelectedLibraryIds] = useState(new Set());

    // Drive Creative Library modal — same pattern as the Generated Ads Library
    // above, sourced from Joel's synced Google Drive folder instead.
    const [showDriveLibraryModal, setShowDriveLibraryModal] = useState(false);
    const [driveAssets, setDriveAssets] = useState([]);
    const [driveLibraryLoading, setDriveLibraryLoading] = useState(false);
    const [driveLibraryError, setDriveLibraryError] = useState(null);
    const [refreshingDriveCopy, setRefreshingDriveCopy] = useState(false);
    const [selectedDriveAssetIds, setSelectedDriveAssetIds] = useState(new Set());
    const [drivePreviewGroup, setDrivePreviewGroup] = useState(null);
    const drivePreviewDialogRef = useRef(null);
    const drivePreviewTriggerRef = useRef(null);
    const driveFetchRequestRef = useRef(0);
    const [driveSearchTerm, setDriveSearchTerm] = useState('');
    const [driveRepairPairId, setDriveRepairPairId] = useState(null);
    const [driveFormatFilter, setDriveFormatFilter] = useState('');
    const [showDriveLibraryHint, setShowDriveLibraryHint] = useState(
        () => safeLocalStorageGet('driveLibraryHintSeen') !== 'true'
    );

    const closeDrivePreview = () => {
        const trigger = drivePreviewTriggerRef.current;
        setDrivePreviewGroup(null);
        window.setTimeout(() => trigger?.focus(), 0);
    };

    useEffect(() => {
        if (!drivePreviewGroup) return undefined;

        const trapFocus = (event) => {
            if (event.key === 'Escape') {
                event.preventDefault();
                closeDrivePreview();
                return;
            }
            if (event.key !== 'Tab') return;

            const focusable = drivePreviewDialogRef.current?.querySelectorAll(
                'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), video[controls], [tabindex]:not([tabindex="-1"])'
            );
            if (!focusable?.length) return;
            const items = Array.from(focusable);
            const first = items[0];
            const last = items[items.length - 1];
            if (event.shiftKey && document.activeElement === first) {
                event.preventDefault();
                last.focus();
            } else if (!event.shiftKey && document.activeElement === last) {
                event.preventDefault();
                first.focus();
            }
        };

        document.addEventListener('keydown', trapFocus);
        const focusTimer = window.setTimeout(() => {
            drivePreviewDialogRef.current?.querySelector('button')?.focus();
        }, 0);
        return () => {
            window.clearTimeout(focusTimer);
            document.removeEventListener('keydown', trapFocus);
        };
    }, [drivePreviewGroup]);

    useEffect(() => {
        if (!showDriveLibraryModal && drivePreviewGroup) setDrivePreviewGroup(null);
    }, [showDriveLibraryModal, drivePreviewGroup]);
    const [copyFieldsTouched, setCopyFieldsTouched] = useState({
        headlines: false,
        bodies: false,
        description: false,
        cta: false,
        websiteUrl: false,
    });
    // A 50-ad Drive import must not become 50 full copy cards. Keep the same
    // selection/inspection pattern as the final Review step: compact rows on
    // the left, with one focused editable record in the rail on the right.
    const [selectedCopyCreativeId, setSelectedCopyCreativeId] = useState(null);
    const copyEditorRef = useRef(null);
    const copyRowRefs = useRef({});
    useEffect(() => {
        const creatives = creativeData.creatives || [];
        if (!creatives.some(creative => creative.id === selectedCopyCreativeId)) {
            setSelectedCopyCreativeId(creatives[0]?.id || null);
        }
    }, [creativeData.creatives, selectedCopyCreativeId]);

    // Validation can identify an individual bad row. Bring that row and the
    // edit rail into view instead of leaving the operator to hunt a 50-row list.
    const focusCopyCreative = (creativeId) => {
        setSelectedCopyCreativeId(creativeId);
        requestAnimationFrame(() => {
            copyEditorRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
            copyRowRefs.current[creativeId]?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        });
    };
    // Wire key must be snake_case (`creative_enhancements`) to match what
    // facebook_service.py reads off the request body — the backend never
    // does camelCase->snake_case conversion, so a mismatch here silently
    // no-ops the whole feature (caught in pre-push review, was `creativeEnhancements`).
    const [creativeEnhancements, setCreativeEnhancements] = useState(
        () => creativeData.creative_enhancements || {}
    );
    const handleCreativeEnhancementsChange = (next) => {
        setCreativeEnhancements(next);
        setCreativeData(current => ({ ...current, creative_enhancements: next }));
    };

    const driveAssetGroups = useMemo(() => {
        if (driveRepairPairId) {
            return buildDriveAssetGroups(driveAssets).filter(group => group.id === driveRepairPairId);
        }
        const query = driveSearchTerm.trim().toLowerCase();
        const visibleAssets = driveAssets.filter(asset => {
            if (driveFormatFilter && asset.format !== driveFormatFilter) return false;
            if (!query) return true;
            const haystack = `${asset.file_name || ''} ${asset.folder_path || ''} ${asset.brand_name || ''}`.toLowerCase();
            return haystack.includes(query);
        });
        return buildDriveAssetGroups(visibleAssets);
    }, [driveAssets, driveSearchTerm, driveFormatFilter, driveRepairPairId]);

    // Keep the full group index separate from the visible filtered list. A
    // buyer can select Feed assets, switch to Stories, and continue selecting;
    // filtering must not erase the earlier choices from the eventual payload.
    const allDriveAssetGroups = useMemo(() => buildDriveAssetGroups(driveAssets), [driveAssets]);
    const driveGroupById = useMemo(() => new Map(allDriveAssetGroups.map(group => [group.id, group])), [allDriveAssetGroups]);
    const mixedDriveCopyMatches = useMemo(() => {
        const matchedPairs = driveAssetGroups.filter(group => group.isPair && hasCompleteCopy(group.copy || {})).length;
        const unmatchedPairs = driveAssetGroups.filter(group => group.isPair && !hasCompleteCopy(group.copy || {})).length;
        return matchedPairs > 0 && unmatchedPairs > 0
            ? { matchedPairs, unmatchedPairs }
            : null;
    }, [driveAssetGroups]);
    // Purely informational — which Drive asset ids are already sitting in
    // creativeData.creatives from an earlier add. Never gates selection or
    // toggling (that stays exactly as it was); it only lets the grid show an
    // "Already added" badge so Joel can tell without opening each card.
    const existingDriveAssetIds = useMemo(() => {
        const ids = new Set();
        (creativeData?.creatives || []).forEach(creative => {
            if (creative.source !== 'drive') return;
            (creative.driveAssetIds || []).forEach(id => ids.add(id));
        });
        return ids;
    }, [creativeData?.creatives]);
    const isDriveGroupAlreadyAdded = (group) => Boolean(
        group && [group.feedAsset?.id, group.storiesAsset?.id, group.displayAsset?.id]
            .some(id => id && existingDriveAssetIds.has(id))
    );

    // Raw file count — "N assets" in the footer label. Distinct from how many
    // CREATIVE entries actually land in creativeData.creatives (a real tagged
    // pair merges 2 assets into 1 creative; an auto-duped single expands 1
    // asset into 2) — that count is driveSelectionMediaCount below.
    const driveSelectionAssetCount = useMemo(
        () => [...selectedDriveAssetIds].reduce((sum, id) => sum + (driveGroupById.get(id)?.isPair ? 2 : 1), 0),
        [selectedDriveAssetIds, driveGroupById]
    );
    // Mirrors addDriveSelectionToCreatives's exact branching so the pre-add
    // "N total ad combinations" preview can't drift from what actually lands
    // in creativeData.creatives — pre-push review (code-auditor: HIGH) found
    // the old shared driveSelectionAssetCount undercounted by up to 2x here
    // once autoDupeStories could expand a single unpaired image into two.
    const driveSelectionMediaCount = useMemo(() => {
        return [...selectedDriveAssetIds].reduce((sum, id) => {
            const group = driveGroupById.get(id);
            if (!group) return sum;
            const canMergeAsPair = group.isPair
                && group.feedAsset?.format !== 'video'
                && group.storiesAsset?.format !== 'video';
            if (canMergeAsPair) return sum + 1; // one dualPlacement creative
            if (group.isPair) return sum + 2; // video-fallback: two real distinct creatives already
            const asset = group.displayAsset;
            if (!asset) return sum;
            const wouldAutoDupe = autoDupeStories && asset.format !== 'video';
            return sum + (wouldAutoDupe ? 2 : 1);
        }, 0);
    }, [selectedDriveAssetIds, driveGroupById, autoDupeStories]);
    const driveSelectionProjectedAdCount = useMemo(() => {
        const selectedGroups = [...selectedDriveAssetIds].map(id => driveGroupById.get(id)).filter(Boolean);
        // Every selected group stays in the editor now, including unmatched
        // groups which become explicit Needs copy cards. Drive assets are one
        // ad per media group; their copy is fixed per card rather than
        // multiplied by the shared variant fields.
        return selectedGroups.reduce((sum, group) => {
            const canMergeAsPair = group.isPair && group.feedAsset?.format !== 'video' && group.storiesAsset?.format !== 'video';
            const mediaCount = canMergeAsPair ? 1 : group.isPair ? 2 : (autoDupeStories && group.displayAsset?.format !== 'video' ? 2 : 1);
            return sum + mediaCount;
        }, 0);
    }, [selectedDriveAssetIds, driveGroupById, autoDupeStories]);

    // Aggregate crop-batch state — drives the "cropping N of M" banner and the
    // failed-crop count/retry-all control on the media grid. `cropping` is set
    // true on a card the instant its placeholder is created (before the
    // client-side concurrency queue in imageCrop.js even starts its network
    // request), so the size of a just-started batch is fully visible in
    // creativeData immediately — no separate bookkeeping needed at the
    // trigger sites (bulk Drive add, auto-dupe on upload, manual duplicate).
    const croppingCreatives = useMemo(
        () => creativeData.creatives.filter(c => c.cropping),
        [creativeData.creatives]
    );
    const cropFailedCreatives = useMemo(
        () => creativeData.creatives.filter(c => c.cropFailed),
        [creativeData.creatives]
    );
    const croppingCount = croppingCreatives.length;
    const cropFailedCount = cropFailedCreatives.length;
    // Tracks "N of M done" for the progress banner via an id-keyed set rather
    // than a raw high-water mark on the in-flight count — a first version
    // used `Math.max(prev, croppingCount)`, which silently broke on two real
    // cases (code-auditor pre-push review, HIGH + MEDIUM): (1) if Joel adds
    // more images while an earlier batch is still draining, the new arrivals
    // got absorbed into the old peak instead of extending the total, so the
    // banner understated both numbers; (2) removing a still-cropping card
    // (the grid's Trash2 button isn't disabled mid-crop) never shrank the
    // total, so M stayed permanently overstated until the whole batch
    // happened to finish. Fixed by tracking the actual set of card ids that
    // have been part of the CURRENT batch: an id joins when it starts
    // cropping, leaves if its card is deleted entirely (shrinking the total),
    // and the whole set clears once nothing is in flight so the next batch
    // starts clean. Computed via useMemo (not useEffect+state) specifically
    // so there's no one-frame render where a fresh batch's total hasn't
    // caught up yet — the auditor also confirmed that lag was independently
    // reachable and could flash a negative "done" count.
    const cropBatchIdsRef = useRef(new Set());
    const cropBatchProgress = useMemo(() => {
        const currentIds = new Set(creativeData.creatives.map(c => c.id));
        const stillCroppingIds = croppingCreatives.map(c => c.id);

        if (stillCroppingIds.length === 0) {
            cropBatchIdsRef.current = new Set();
            return { total: 0, done: 0 };
        }

        const ids = cropBatchIdsRef.current;
        stillCroppingIds.forEach(id => ids.add(id));
        [...ids].forEach(id => {
            if (!currentIds.has(id)) ids.delete(id);
        });

        return { total: ids.size, done: ids.size - stillCroppingIds.length };
    }, [creativeData.creatives, croppingCreatives]);

    // Re-runs every currently-failed crop from its own pristine source in one
    // click, rather than making Joel hunt down and retry each red banner
    // individually across a large bulk grid (joel-perspective follow-up,
    // shipped 2026-09-15 alongside the rest of the smart-crop feature).
    const retryAllFailedCrops = () => {
        cropFailedCreatives.forEach(c => recropCreative(c.id, c.cropAnchor || 'center'));
    };

    // Drops any selected id that narrowing the search/format filter has
    // scrolled out of driveAssetGroups — without this, a tile selected
    // before a filter change stays counted (and stays in the payload) even
    // though it's no longer visible or deselectable by clicking it. Worst
    // case found in review: every selected id goes stale this way and "Add N
    // to Campaign" silently does nothing, with no toast, because the button
    // was enabled off the raw Set size rather than what's actually resolvable.
    useEffect(() => {
        setSelectedDriveAssetIds(prev => {
            const next = new Set([...prev].filter(id => {
                const group = driveGroupById.get(id);
                return group && !isDriveGroupSelectionBlocked(group);
            }));
            return next.size === prev.size ? prev : next;
        });
    }, [driveGroupById]);

    const driveCounts = useMemo(() => {
        return driveAssets.reduce((acc, asset) => {
            acc.total += 1;
            acc[asset.format] = (acc[asset.format] || 0) + 1;
            return acc;
        }, { total: 0, image: 0, video: 0 });
    }, [driveAssets]);

    const defaultUrlForDriveGroup = (group) => {
        const brandId = group?.displayAsset?.brand_id;
        const brand = brands.find(item => item.id === brandId);
        const productsWithUrl = (brand?.products || []).filter(product => product.default_url);
        return productsWithUrl.length === 1 ? productsWithUrl[0].default_url : '';
    };

    const fetchDriveAssets = async ({ throwOnError = false } = {}) => {
        const requestId = ++driveFetchRequestRef.current;
        setDriveLibraryLoading(true);
        setDriveLibraryError(null);
        try {
            const res = await authFetch(`${API_URL}/drive-assets`);
            if (!res.ok) {
                // 503 means the migration hasn't landed yet — surface that plainly
                // rather than a generic failure.
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || `HTTP ${res.status}`);
            }
            const data = await res.json();
            if (!Array.isArray(data)) {
                throw new Error('Drive library returned an invalid response');
            }
            if (requestId !== driveFetchRequestRef.current) return [];
            const assets = data;
            setDriveAssets(assets);
            return assets;
        } catch (err) {
            if (requestId !== driveFetchRequestRef.current) return [];
            setDriveLibraryError(err.message || 'Failed to load Drive Creative Library');
            if (throwOnError) throw err;
            return [];
        } finally {
            if (requestId === driveFetchRequestRef.current) setDriveLibraryLoading(false);
        }
    };

    const refreshDriveCopyMatches = async () => {
        setRefreshingDriveCopy(true);
        try {
            const res = await authFetch(`${API_URL}/drive-assets/refresh-copy-metadata`, { method: 'POST' });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error(data.detail || 'Could not refresh Drive copy');
            const refreshMessage = data.errors
                ? `Copy refresh completed with ${data.errors} source file${data.errors === 1 ? '' : 's'} requiring repair. Those packages are blocked until their current Drive copy refreshes successfully.`
                : `Drive copy refreshed for ${data.updated || 0} asset${data.updated === 1 ? '' : 's'} and synchronized with active Drive rows.`;
            if (data.errors) {
                showWarning(refreshMessage);
            }
            const refreshedAssets = await fetchDriveAssets({ throwOnError: true });
            const refreshedGroups = buildDriveAssetGroups(refreshedAssets || []);
            const refreshedGroupById = new Map(refreshedGroups.map(group => [group.id, group]));
            const refreshedGroupByAssetId = new Map(
                refreshedGroups.flatMap(group => group.assets.map(asset => [asset.id, group]))
            );
            setCreativeData(prev => ({
                ...prev,
                creatives: (prev.creatives || []).map(creative => {
                    if (creative.source !== 'drive') return creative;
                    const group = (creative.drivePairId && refreshedGroupById.get(creative.drivePairId))
                        || (creative.driveAssetIds || []).map(id => refreshedGroupByAssetId.get(id)).find(Boolean);
                    if (!group) return {
                        ...creative,
                        driveCopyIntegrityIssue: true,
                    };
                    const matchedCopy = hasCompleteCopy(group.copy || {}) ? group.copy : {};
                    return {
                        ...creative,
                        driveCopyIntegrityIssue: group.copyIntegrityIssue || group.copyRefreshUnverified || group.copyPairingAmbiguous || false,
                        category: group.category || creative.category,
                        headline: matchedCopy.headline || '',
                        body: matchedCopy.primary_text || '',
                        description: matchedCopy.description || '',
                        cta: group.cta || '',
                        websiteUrl: group.landingPage || '',
                    };
                }),
            }));
            if (!data.errors) showSuccess(refreshMessage);
        } catch (err) {
            showError(err.message || 'Could not refresh Drive copy');
        } finally {
            setRefreshingDriveCopy(false);
        }
    };

    // Load the count as soon as Step 4 is visited, not only after the modal is
    // opened, so the primary action is discoverable and accurately labelled.
    useEffect(() => {
        fetchDriveAssets();
    }, []);

    const dismissDriveLibraryHint = () => {
        setShowDriveLibraryHint(false);
        safeLocalStorageSet('driveLibraryHintSeen', 'true');
    };

    const openDriveLibraryModal = () => {
        setSelectedDriveAssetIds(new Set());
        setDriveSearchTerm('');
        setDriveRepairPairId(null);
        setDriveFormatFilter('');
        // Step-mount supplies the live count, but a transient deploy/network
        // failure must be recoverable by reopening the picker rather than
        // requiring a wizard remount.
        if ((driveAssets.length === 0 || driveLibraryError) && !driveLibraryLoading) fetchDriveAssets();
        setShowDriveLibraryModal(true);
    };

    const toggleDriveAssetSelection = (assetId) => {
        const group = driveGroupById.get(assetId);
        if (isDriveGroupSelectionBlocked(group)) {
            showWarning(group?.copyRefreshUnverified
                ? 'This Drive copy source needs repair. Refresh after fixing the source document before selecting it.'
                : 'This ad number has multiple or incomplete placements in Drive. Rename or resolve the source files, then refresh copy before selecting it.');
            return;
        }
        setSelectedDriveAssetIds(prev => {
            const next = new Set(prev);
            next.has(assetId) ? next.delete(assetId) : next.add(assetId);
            return next;
        });
    };

    // Bulk-select shortcuts — clicking through 50 tiles one at a time was the
    // direct complaint. All three operate on driveAssetGroups in its CURRENT
    // filtered/searched order, so "select first N" means "first N of whatever
    // you're currently looking at," not the full unfiltered library.
    const [driveSelectCount, setDriveSelectCount] = useState('');

    // All three ADD to whatever is already selected rather than replacing it —
    // pre-push review (joel-perspective): a hard replace meant a few manual
    // picks could be silently wiped by a later "Select first N," with no
    // warning. "Clear selection" is the one explicit way to actually reset.
    const selectAllVisibleDriveAssets = () => {
        const blockedCount = driveAssetGroups.filter(isDriveGroupSelectionBlocked).length;
        if (blockedCount) {
            showWarning(String(blockedCount) + ' Drive creative' + (blockedCount !== 1 ? 's were' : ' was') + ' skipped because their pair or copy source needs repair.');
        }
        setSelectedDriveAssetIds(prev => {
            const next = new Set(prev);
            driveAssetGroups.filter(group => !isDriveGroupSelectionBlocked(group)).forEach(group => next.add(group.id));
            return next;
        });
    };

    const clearDriveAssetSelection = () => {
        setSelectedDriveAssetIds(new Set());
    };

    const selectFirstNDriveAssets = () => {
        const n = parseInt(driveSelectCount, 10);
        if (!Number.isFinite(n) || n <= 0) return;
        const blockedCount = driveAssetGroups.filter(isDriveGroupSelectionBlocked).length;
        if (blockedCount) {
            showWarning(String(blockedCount) + ' Drive creative' + (blockedCount !== 1 ? 's were' : ' was') + ' skipped. Resolve the source in Drive, then refresh.');
        }
        setSelectedDriveAssetIds(prev => {
            const next = new Set(prev);
            driveAssetGroups.filter(group => !isDriveGroupSelectionBlocked(group)).slice(0, n).forEach(group => next.add(group.id));
            return next;
        });
    };

    const addDriveSelectionToCreatives = () => {
        const selectedGroups = [...selectedDriveAssetIds]
            .map(id => driveGroupById.get(id))
            .filter(Boolean);
        const blockedGroups = selectedGroups.filter(isDriveGroupSelectionBlocked);
        if (blockedGroups.length > 0) {
            showWarning('Resolve the Drive copy or placement issue before adding these creatives.');
            return;
        }
        const groupsWithCopy = selectedGroups.filter(group => hasCompleteCopy(group.copy || {}) && !group.copyRefreshUnverified);
        // A mixed selection must never let a matched category's global copy
        // fall through onto an unmatched asset. Keep the all-unmatched flow
        // available for Joel's manual copy, but require every group to have a
        // matched copy set when any selected group already has one.
        const unmatchedGroups = selectedGroups.filter(group => !hasCompleteCopy(group.copy || {}) || group.copyRefreshUnverified);
        const clearStaleGlobalCopy = selectedGroups.length > 0
            && groupsWithCopy.length === 0
            && !copyFieldsTouched.headlines
            && !copyFieldsTouched.bodies;
        // Keep unmatched selections in the editor as explicit "Needs copy"
        // cards. Dropping them here made a restaurant/retail selection look
        // successful while silently removing the restaurant ad; the per-card
        // validator now blocks launch until Joel fills the missing card.
        const groupsToAdd = selectedGroups;
        const newCreatives = groupsToAdd.flatMap(group => {
            const matchedCopy = hasCompleteCopy(group.copy || {}) && !group.copyRefreshUnverified ? group.copy : {};
            // Category copy docs often intentionally contain only the message
            // fields. Assign the explicit Creative-step CTA and brand's single
            // default URL to that individual row at add time (never as a hidden
            // Bulk fallback), so it remains visible/editable and can advance.
            const groupCta = group.cta || creativeData.cta || '';
            const groupWebsiteUrl = group.landingPage || defaultUrlForDriveGroup(group) || creativeData.websiteUrl || '';
            // A real pair (both an image feed asset AND an image stories asset —
            // create_creative's dual-placement path is image-only, never video,
            // per its own docstring) becomes ONE creative carrying both URLs, so
            // it flows through BulkAdCreation as a single ad/ad-set entry that
            // Meta shows with the right image per placement — reusing the exact
            // secondary_image_hash mechanism Bulk Match Import already ships and
            // that's already been through Meta-API domain review, not inventing
            // a new one. Falls back to two independent creatives (today's
            // behavior) whenever the pair isn't two real images.
            const canMergeAsPair = group.isPair
                && group.feedAsset?.format !== 'video'
                && group.storiesAsset?.format !== 'video';

            if (canMergeAsPair) {
                return [{
                    id: `drive_${group.feedAsset.id}_${group.storiesAsset.id}`,
                    file: null,
                    previewUrl: group.feedAsset.r2_key,
                    imageUrl: group.feedAsset.r2_key,
                    secondaryImageUrl: group.storiesAsset.r2_key,
                    name: group.feedAsset.file_name,
                    mediaType: 'image',
                    format: 'feed',
                    source: 'drive',
                    dualPlacement: true,
                    drivePairId: group.id,
                    driveAssetIds: [group.feedAsset.id, group.storiesAsset.id],
                    driveCopyIntegrityIssue: group.copyIntegrityIssue || group.copyRefreshUnverified || group.copyPairingAmbiguous || false,
                    category: group.category || group.feedAsset?.brand_name || 'Uncategorized',
                    headline: matchedCopy.headline || '',
                    body: matchedCopy.primary_text || '',
                    description: matchedCopy.description || '',
                    cta: groupCta,
                    ctaSource: group.cta ? 'Drive' : groupCta ? 'Creative default' : '',
                    websiteUrl: groupWebsiteUrl
                }];
            }

            if (!group.isPair) {
                // A truly single, unpaired asset — no real counterpart exists yet,
                // so this is exactly the case applyAutoStoriesDupe is for.
                const asset = group.displayAsset;
                if (!asset) return [];
                return applyAutoStoriesDupe({
                    id: `drive_${asset.id}`,
                    file: null,
                    previewUrl: asset.r2_key,
                    imageUrl: asset.format === 'video' ? undefined : asset.r2_key,
                    videoUrl: asset.format === 'video' ? asset.r2_key : undefined,
                    name: asset.file_name,
                    mediaType: asset.format,
                    format: driveAssetPlacement(asset),
                    source: 'drive',
                    drivePairId: null,
                    driveAssetIds: [asset.id],
                    driveCopyIntegrityIssue: group.copyIntegrityIssue || group.copyRefreshUnverified || group.copyPairingAmbiguous || false,
                    category: group.category || asset.brand_name || 'Uncategorized',
                    headline: matchedCopy.headline || '',
                    body: matchedCopy.primary_text || '',
                    description: matchedCopy.description || '',
                    cta: groupCta,
                    ctaSource: group.cta ? 'Drive' : groupCta ? 'Creative default' : '',
                    websiteUrl: groupWebsiteUrl
                });
            }

            // group.isPair but couldn't merge into one dualPlacement creative above
            // (one side is a video) — both real placements already exist as their
            // own distinct assets here, so never auto-dupe this branch; that would
            // add a redundant third entry rather than filling a real gap.
            return [group.feedAsset, group.storiesAsset].filter(Boolean).map(asset => ({
                id: `drive_${asset.id}`,
                file: null,
                previewUrl: asset.r2_key,
                imageUrl: asset.format === 'video' ? undefined : asset.r2_key,
                videoUrl: asset.format === 'video' ? asset.r2_key : undefined,
                name: asset.file_name,
                mediaType: asset.format,
                format: driveAssetPlacement(asset),
                source: 'drive',
                drivePairId: group.id,
                driveAssetIds: [asset.id],
                driveCopyIntegrityIssue: group.copyIntegrityIssue || group.copyRefreshUnverified || group.copyPairingAmbiguous || false,
                category: group.category || asset.brand_name || 'Uncategorized',
                headline: matchedCopy.headline || '',
                body: matchedCopy.primary_text || '',
                description: matchedCopy.description || '',
                cta: groupCta,
                ctaSource: group.cta ? 'Drive' : groupCta ? 'Creative default' : '',
                websiteUrl: groupWebsiteUrl
            }));
        });
        const firstWithCopy = groupsWithCopy[0] || selectedGroups.find(group => group.landingPage || group.cta);
        const firstCopy = firstWithCopy?.copy || {};
        const firstDefaultUrl = selectedGroups.map(defaultUrlForDriveGroup).find(Boolean) || '';
        setCreativeData(prev => {
            const nextHeadlines = firstCopy.headline && !copyFieldsTouched.headlines
                ? [firstCopy.headline]
                : clearStaleGlobalCopy ? [''] : prev.headlines;
            const nextBodies = firstCopy.primary_text && !copyFieldsTouched.bodies
                ? [firstCopy.primary_text]
                : clearStaleGlobalCopy ? [''] : prev.bodies;
            const nextDescription = firstCopy.description && !copyFieldsTouched.description
                ? firstCopy.description
                : clearStaleGlobalCopy && !copyFieldsTouched.description ? '' : prev.description;
            const nextCta = firstWithCopy?.cta && !copyFieldsTouched.cta
                ? firstWithCopy.cta
                : clearStaleGlobalCopy && !copyFieldsTouched.cta ? 'LEARN_MORE' : (prev.cta || 'LEARN_MORE');
            const nextWebsiteUrl = (firstWithCopy?.landingPage || firstDefaultUrl) && !copyFieldsTouched.websiteUrl
                ? (firstWithCopy?.landingPage || firstDefaultUrl)
                : clearStaleGlobalCopy && !copyFieldsTouched.websiteUrl ? '' : prev.websiteUrl;

            if (selectedAdAccount) {
                safeLocalStorageSet(`defaultHeadlines_${selectedAdAccount.id}_${campaignCacheId}`, JSON.stringify(nextHeadlines || ['']));
                safeLocalStorageSet(`defaultBodies_${selectedAdAccount.id}_${campaignCacheId}`, JSON.stringify(nextBodies || ['']));
                safeLocalStorageSet(`defaultDescription_${selectedAdAccount.id}_${campaignCacheId}`, nextDescription || '');
                safeLocalStorageSet(`defaultCta_${selectedAdAccount.id}_${campaignCacheId}`, nextCta || 'LEARN_MORE');
                safeLocalStorageSet(`defaultUrl_${selectedAdAccount.id}_${campaignCacheId}`, nextWebsiteUrl || '');
            }

            return {
                ...prev,
                creatives: [...(prev.creatives || []), ...newCreatives],
                headlines: nextHeadlines,
                bodies: nextBodies,
                description: nextDescription,
                cta: nextCta,
                websiteUrl: nextWebsiteUrl
            };
        });
        if (unmatchedGroups.length > 0) {
            const pairMismatchCount = unmatchedGroups.filter(group => group.copyIntegrityIssue || group.copyRefreshUnverified).length;
            const missingCopyCount = unmatchedGroups.length - pairMismatchCount;
            const notices = [];
            if (pairMismatchCount > 0) {
                notices.push(`${pairMismatchCount} Feed + Stories pair${pairMismatchCount !== 1 ? 's have' : ' has'} mismatched Drive data. Use Refresh copy from Drive before continuing.`);
            }
            if (missingCopyCount > 0) {
                notices.push(`${missingCopyCount} Drive creative${missingCopyCount !== 1 ? 's are' : ' is'} missing a matched headline or primary text. Fill those cards before launching.`);
            }
            showWarning(notices.join(' '));
        }
        if (newCreatives.length > 0) {
            const pairCount = selectedGroups.filter(group => group.isPair).length;
            const copySource = firstWithCopy?.displayAsset?.folder_path || firstWithCopy?.displayAsset?.file_name;
            const copyNote = hasCopyText(firstCopy)
                ? ` Applied Drive copy${groupsWithCopy.length > 1 ? ` from ${copySource}; ${groupsWithCopy.length - 1} other copy set${groupsWithCopy.length - 1 !== 1 ? 's were' : ' was'} not applied.` : copySource ? ` from ${copySource}.` : '.'}`
                : '';
            showSuccess(`Added ${newCreatives.length} Drive asset${newCreatives.length !== 1 ? 's' : ''}${pairCount ? ` from ${pairCount} Feed + Stories pair${pairCount !== 1 ? 's' : ''}` : ''}.${copyNote}`);
        }
        // Drive selection must not silently change the structure chosen in the
        // Ad Set step. A paired creative can be launched into an existing ad
        // set, one shared new ad set, or one new ad set per pair; the buyer's
        // explicit creationMode remains the source of truth for that choice.
        setShowDriveLibraryModal(false);
    };

    const fetchLibraryAds = async () => {
        setLibraryLoading(true);
        try {
            const res = await authFetch(`${API_URL}/generated-ads`);
            // authFetch resolves with the Response on an auth failure rather than
            // throwing, so without this the modal would just open empty and say
            // nothing about why.
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || `HTTP ${res.status}`);
            }
            const data = await res.json();
            setLibraryAds(Array.isArray(data) ? data.filter(ad => ad.image_url) : []);
        } catch (e) {
            showError(`Failed to load Generated Ads library: ${e.message}`);
        } finally {
            setLibraryLoading(false);
        }
    };

    const openLibraryModal = () => {
        setSelectedLibraryIds(new Set());
        fetchLibraryAds();
        setShowLibraryModal(true);
    };

    const toggleLibrarySelection = (adId) => {
        setSelectedLibraryIds(prev => {
            const next = new Set(prev);
            next.has(adId) ? next.delete(adId) : next.add(adId);
            return next;
        });
    };

    const addLibrarySelectionToCreatives = () => {
        const selected = libraryAds.filter(ad => selectedLibraryIds.has(ad.id));
        const newCreatives = selected.map(ad => ({
            id: `lib_${ad.id}`,
            file: null,
            previewUrl: ad.image_url,
            imageUrl: ad.image_url,
            name: ad.headline || `Library Ad ${ad.id}`,
            mediaType: 'image',
            format: 'feed'
        }));
        setCreativeData(prev => ({
            ...prev,
            creatives: [...(prev.creatives || []), ...newCreatives]
        }));
        setShowLibraryModal(false);
    };

    const handleDragEnter = (e) => {
        e.preventDefault();
        e.stopPropagation();
        setIsDragging(true);
    };

    const handleDragOver = (e) => {
        e.preventDefault();
        e.stopPropagation();
        setIsDragging(true);
    };

    const handleDragLeave = (e) => {
        e.preventDefault();
        e.stopPropagation();
        // Only set dragging to false if leaving the drop zone entirely
        if (e.currentTarget.contains(e.relatedTarget)) return;
        setIsDragging(false);
    };

    const handleDrop = (e) => {
        e.preventDefault();
        e.stopPropagation();
        setIsDragging(false);

        const files = Array.from(e.dataTransfer.files);
        if (files.length === 0) return;

        // Filter for images and videos
        const mediaFiles = files.filter(file =>
            ALLOWED_IMAGE_TYPES.includes(file.type) || ALLOWED_VIDEO_TYPES.includes(file.type)
        );

        if (mediaFiles.length === 0) {
            showWarning('Please drop image or video files only');
            return;
        }

        const newCreatives = mediaFiles.flatMap(file => {
            const isVideo = ALLOWED_VIDEO_TYPES.includes(file.type);
            return applyAutoStoriesDupe({
                id: `creative_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
                file,
                previewUrl: URL.createObjectURL(file),
                name: file.name,
                mediaType: isVideo ? 'video' : 'image',
                format: 'feed'
            });
        });

        setCreativeData(prev => ({
            ...prev,
            creatives: [...(prev.creatives || []), ...newCreatives]
        }));
    };

    // Prepopulate Creative Name with Ad Set Name if empty
    useEffect(() => {
        if (adsetData?.name && !creativeData.creativeName) {
            handleInputChange('creativeName', adsetData.name);
        }
    }, [adsetData?.name]);

    // Clear uploaded Ad Media when this mount belongs to a genuinely different
    // campaign than whatever `creatives` currently sit in shared CampaignContext
    // state (same leak class as the text-field cache effect below, applied to
    // images/videos). Creatives have no localStorage cache to reload from — File/
    // blob objects don't survive JSON serialization — so the only question here is
    // whether to clear or leave alone, not what to reload.
    //
    // AdCreativeStep fully unmounts/remounts on every step-4 exit/re-entry, so a
    // local ref can never hold a "previous" value to diff against. Instead we
    // stash the owning scope (ad account + campaign) directly on `creativeData`,
    // which lives in CampaignContext and stays mounted for the whole session —
    // that lets us tell "same campaign, just navigated back" apart from "picked a
    // different campaign" regardless of this component's own mount lifecycle.
    useEffect(() => {
        if (!selectedAdAccount) return;
        const scopeId = `${selectedAdAccount.id}_${campaignCacheId}`;
        if (creativeData.creativesScopeId === scopeId) return;

        // Revoke any blob object URLs before dropping the references — same
        // revoke-before-drop pattern BulkMatchImport.jsx uses for its image
        // previews — so a campaign switch doesn't leak the discarded blobs.
        (creativeData.creatives || []).forEach(c => {
            if (c.previewUrl && c.previewUrl.startsWith('blob:')) {
                URL.revokeObjectURL(c.previewUrl);
            }
        });

        // Creative Enhancement toggles are session/scope state, not per-ad —
        // clear them alongside `creatives` on a genuine campaign/account
        // switch. Without this, a flag enabled while building one campaign
        // silently carried into the next campaign built in the same tab
        // (joel-perspective pre-push review, P1) — the "N enabled" badge is
        // the only visible trace, easy to miss on a page Joel moves through
        // fast, and by the time an ad's crop/CTA looks unexpectedly
        // different there's no record connecting it back to a stale toggle.
        setCreativeData(prev => ({
            ...prev,
            creatives: [],
            creative_enhancements: {},
            creativesScopeId: scopeId
        }));
        setCreativeEnhancements({});
    }, [selectedAdAccount, campaignCacheId]);

    // Auto-load images queued from the Generated Ads library ("Use in Campaign Builder" flow)
    useEffect(() => {
        try {
            const raw = localStorage.getItem('pendingLibraryImages');
            if (!raw) return;
            const pending = JSON.parse(raw);
            if (!Array.isArray(pending) || pending.length === 0) return;
            localStorage.removeItem('pendingLibraryImages');

            const newCreatives = pending.map(item => ({
                id: `lib_${item.id}`,
                file: null,
                previewUrl: item.imageUrl,
                imageUrl: item.imageUrl,
                name: item.name || `Library Ad`,
                mediaType: 'image',
                format: 'feed'
            }));

            setCreativeData(prev => ({
                ...prev,
                creatives: [...(prev.creatives || []), ...newCreatives],
                // Pre-fill copy fields from the first library ad if not already set
                headlines: prev.headlines[0] ? prev.headlines : (pending[0]?.headline ? [pending[0].headline] : prev.headlines),
                bodies: prev.bodies[0] ? prev.bodies : (pending[0]?.body ? [pending[0].body] : prev.bodies),
                cta: prev.cta || pending[0]?.cta || 'LEARN_MORE'
            }));

            showSuccess(`${newCreatives.length} image${newCreatives.length !== 1 ? 's' : ''} loaded from Generated Ads library`);
        } catch (e) {
            console.error('Failed to load pending library images', e);
        }
    }, []);

    // Load (or clear) campaign-scoped creative defaults — URL, headlines, bodies,
    // description, CTA — whenever the ad account or the effective campaign changes.
    //
    // AdCreativeStep is conditionally rendered by FacebookCampaigns
    // ({currentStep === 4 && <AdCreativeStep .../>}) and fully unmounts/remounts
    // every time the user leaves and re-enters step 4, while creativeData lives in
    // CampaignContext and persists across that. So there is never a meaningful
    // "previous render" inside this component to diff campaignCacheId against —
    // any ref-based change detection re-initializes fresh on every mount and can
    // never see a switch that happened while the component was unmounted.
    //
    // Given that, every mount must resolve fresh from the CURRENT scope rather
    // than trying to diff against history: unconditionally clear the
    // campaign-scoped fields and load strictly from that campaign's own cache (or
    // blank if it has none), in the same setCreativeData call so no stale data
    // from a different campaign can flash on screen first.
    useEffect(() => {
        if (!selectedAdAccount) return;

        const savedUrl = safeLocalStorageGet(`defaultUrl_${selectedAdAccount.id}_${campaignCacheId}`);
        const savedHeadlinesRaw = safeLocalStorageGet(`defaultHeadlines_${selectedAdAccount.id}_${campaignCacheId}`);
        const savedBodiesRaw = safeLocalStorageGet(`defaultBodies_${selectedAdAccount.id}_${campaignCacheId}`);
        const savedDescription = safeLocalStorageGet(`defaultDescription_${selectedAdAccount.id}_${campaignCacheId}`);
        const savedCta = safeLocalStorageGet(`defaultCta_${selectedAdAccount.id}_${campaignCacheId}`);

        let savedHeadlines = null;
        if (savedHeadlinesRaw) {
            try {
                const parsed = JSON.parse(savedHeadlinesRaw);
                if (Array.isArray(parsed) && parsed.length > 0) savedHeadlines = parsed;
            } catch (e) { console.error('Error parsing saved headlines', e); }
        }

        let savedBodies = null;
        if (savedBodiesRaw) {
            try {
                const parsed = JSON.parse(savedBodiesRaw);
                if (Array.isArray(parsed) && parsed.length > 0) savedBodies = parsed;
            } catch (e) { console.error('Error parsing saved bodies', e); }
        }

        // pageId/instagramId are intentionally excluded here — they're
        // account-scoped, not campaign-scoped (see the page-load effect above).
        setCreativeData(prev => ({
            ...prev,
            websiteUrl: savedUrl || '',
            headlines: savedHeadlines || [''],
            bodies: savedBodies || [''],
            description: savedDescription || '',
            cta: savedCta || 'LEARN_MORE'
        }));
        setCopyFieldsTouched({
            headlines: false,
            bodies: false,
            description: false,
            cta: false,
            websiteUrl: false,
        });
    }, [selectedAdAccount, campaignCacheId]);

    // Fetch pages when ad account is selected
    useEffect(() => {
        if (selectedAdAccount) {
            const requestId = ++pageFetchRequestRef.current;
            fetchPages(selectedAdAccount, requestId);
        } else {
            pageFetchRequestRef.current += 1;
            setPages([]);
        }
    }, [selectedAdAccount]);

    const fetchPages = async (account, requestId) => {
        setLoadingPages(true);
        try {
            const fetchedPages = await getPages(account.id);
            if (requestId !== pageFetchRequestRef.current) return;
            setPages(fetchedPages);

            // Page IDs are account-scoped state. A populated ID is not proof it
            // belongs to the account that is active now: CampaignContext survives
            // navigation back to Step 1, while the selected account can change.
            // Treat an unscoped/mismatched page as empty and resolve a fresh
            // account-specific default instead of allowing the old page to pass
            // the truthy-only validation in handleNext.
            const pageBelongsToActiveAccount = creativeData.pageAccountId === account.id;
            const selectedPageIsAvailable = pageBelongsToActiveAccount
                && fetchedPages.some(page => page.id === creativeData.pageId);

            // DailyInsurance.news is the fixed default for Commercial accounts.
            // Resolve it only after Pages load rather than restoring an arbitrary
            // last-used Page ID — the latter allowed a prior Home Services launch
            // to silently select Trusted Home Service for Commercial.
            if (fetchedPages.length > 0 && !selectedPageIsAvailable) {
                const lastUsedPageId = safeLocalStorageGet(`lastUsedPageId_${account.id}`);
                const pageToSelect = (isCommercialAdAccount(account) && findCommercialDefaultPage(fetchedPages))
                    || fetchedPages.find(p => p.id === lastUsedPageId)
                    || fetchedPages[0];
                handlePageSelection(pageToSelect.id, fetchedPages);
            } else if (fetchedPages.length === 0) {
                if (!pageBelongsToActiveAccount) {
                    setCreativeData(prev => ({
                        ...prev,
                        pageId: '',
                        pageName: null,
                        pageAccountId: account.id,
                        instagramId: null,
                    }));
                }
                // If no pages found, default to manual entry so user isn't blocked
                setManualPageEntry(true);
            }
        } catch (error) {
            if (requestId !== pageFetchRequestRef.current) return;
            console.error('Error fetching pages:', error);
            showError('Failed to load Facebook Pages. You can enter Page ID manually.');
            setManualPageEntry(true); // Auto-switch to manual entry
        } finally {
            if (requestId === pageFetchRequestRef.current) setLoadingPages(false);
        }
    };

    const handlePageSelection = (pageId, currentPages = pages) => {
        const selectedPage = currentPages.find(p => p.id === pageId);
        setCreativeData(prev => ({
            ...prev,
            pageId,
            // Real Page name, so the Review screen's ad-preview cards (BulkAdCreation.jsx)
            // can show the actual Page name instead of a generic placeholder — getPages()
            // already fetches this, it just wasn't being persisted onto creativeData before.
            pageName: selectedPage ? selectedPage.name : prev.pageName,
            pageAccountId: selectedAdAccount?.id || null,
            instagramId: selectedPage ? selectedPage.instagramId : null
        }));
        if (selectedAdAccount) {
            safeLocalStorageSet(`lastUsedPageId_${selectedAdAccount.id}`, pageId);
        }
    };

    const handleInputChange = (field, value) => {
        if (['description', 'cta', 'websiteUrl'].includes(field)) {
            setCopyFieldsTouched(prev => ({ ...prev, [field]: true }));
        }
        setCreativeData(prev => ({
            ...prev,
            [field]: value,
            // When manually entering a Page ID, clear instagramId (prevents using Page ID as
            // IG ID) AND pageName — otherwise the Review screen's preview card (BulkAdCreation.jsx)
            // keeps showing the PREVIOUS dropdown-selected page's real name next to a Page ID
            // that no longer matches it. A stale-but-real-looking name is worse than no name:
            // it reads as a confirmed preview when it isn't. Caught in pre-push review.
            ...(field === 'pageId' ? {
                instagramId: null,
                pageName: null,
                pageAccountId: selectedAdAccount?.id || null,
            } : {})
        }));

        // Persist page ID
        if (field === 'pageId' && selectedAdAccount) {
            safeLocalStorageSet(`lastUsedPageId_${selectedAdAccount.id}`, value);
        }

        // Persist description
        if (field === 'description' && selectedAdAccount) {
            safeLocalStorageSet(`defaultDescription_${selectedAdAccount.id}_${campaignCacheId}`, value);
        }

        // Persist CTA
        if (field === 'cta' && selectedAdAccount) {
            safeLocalStorageSet(`defaultCta_${selectedAdAccount.id}_${campaignCacheId}`, value);
        }

        // Persist URL immediately so a Back/remount before Next keeps buyer edits.
        if (field === 'websiteUrl' && selectedAdAccount) {
            safeLocalStorageSet(`defaultUrl_${selectedAdAccount.id}_${campaignCacheId}`, value);
        }
    };

    const handleBodyChange = (index, value) => {
        setCopyFieldsTouched(prev => ({ ...prev, bodies: true }));
        const newBodies = [...creativeData.bodies];
        newBodies[index] = value;
        setCreativeData(prev => ({
            ...prev,
            bodies: newBodies
        }));

        if (selectedAdAccount) {
            safeLocalStorageSet(`defaultBodies_${selectedAdAccount.id}_${campaignCacheId}`, JSON.stringify(newBodies));
        }
    };

    const handleHeadlineChange = (index, value) => {
        setCopyFieldsTouched(prev => ({ ...prev, headlines: true }));
        const newHeadlines = [...creativeData.headlines];
        newHeadlines[index] = value;
        setCreativeData(prev => ({
            ...prev,
            headlines: newHeadlines
        }));

        if (selectedAdAccount) {
            safeLocalStorageSet(`defaultHeadlines_${selectedAdAccount.id}_${campaignCacheId}`, JSON.stringify(newHeadlines));
        }
    };

    const addBodyField = () => {
        if (creativeData.bodies.length < 3) {
            setCreativeData(prev => ({
                ...prev,
                bodies: [...prev.bodies, '']
            }));
        }
    };

    const addHeadlineField = () => {
        if (creativeData.headlines.length < 3) {
            setCreativeData(prev => ({
                ...prev,
                headlines: [...prev.headlines, '']
            }));
        }
    };

    const removeBodyField = (index) => {
        if (creativeData.bodies.length > 1) {
            const newBodies = creativeData.bodies.filter((_, i) => i !== index);
            setCreativeData(prev => ({
                ...prev,
                bodies: newBodies
            }));
            if (selectedAdAccount) {
                safeLocalStorageSet(`defaultBodies_${selectedAdAccount.id}_${campaignCacheId}`, JSON.stringify(newBodies));
            }
        }
    };

    const removeHeadlineField = (index) => {
        if (creativeData.headlines.length > 1) {
            const newHeadlines = creativeData.headlines.filter((_, i) => i !== index);
            setCreativeData(prev => ({
                ...prev,
                headlines: newHeadlines
            }));
            if (selectedAdAccount) {
                safeLocalStorageSet(`defaultHeadlines_${selectedAdAccount.id}_${campaignCacheId}`, JSON.stringify(newHeadlines));
            }
        }
    };

    const handleMediaUpload = (e) => {
        const files = Array.from(e.target.files);
        if (files.length === 0) return;

        const newCreatives = files.flatMap(file => {
            const isVideo = ALLOWED_VIDEO_TYPES.includes(file.type);
            return applyAutoStoriesDupe({
                id: `creative_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
                file,
                previewUrl: URL.createObjectURL(file),
                name: file.name,
                mediaType: isVideo ? 'video' : 'image',
                format: 'feed'
            });
        });

        setCreativeData(prev => ({
            ...prev,
            creatives: [...(prev.creatives || []), ...newCreatives]
        }));
    };

    const removeCreative = (id) => {
        setCreativeData(prev => ({
            ...prev,
            creatives: prev.creatives.filter(c => c.id !== id)
        }));
    };

    // Drive creatives can carry their own matched copy. Keep edits on the
    // creative itself so a restaurant card can never inherit retail's global
    // headline/body when the batch is assembled in BulkAdCreation.
    const updateCreativeCopy = (id, field, value) => {
        setCreativeData(prev => ({
            ...prev,
            creatives: (prev.creatives || []).map(creative => (
                creative.id === id ? { ...creative, [field]: value } : creative
            ))
        }));
    };

    // Recovery path for "I bulk-added a batch with auto-dupe on and actually
    // wanted Feed-only" — unchecking the toggle only stops FUTURE adds, it
    // can't undo what's already in the grid, and removing N duplicates one at
    // a time defeats the whole point of a bulk workflow (pre-push review,
    // joel-perspective: P2). Only strips the auto-created half of each pair —
    // the original upload/selection stays.
    const removeAutoDupedCreatives = () => {
        setCreativeData(prev => ({
            ...prev,
            creatives: prev.creatives.filter(c => !c.id.endsWith('_autodupe'))
        }));
    };

    const toggleCreativeFormat = (id) => {
        setCreativeData(prev => ({
            ...prev,
            creatives: prev.creatives.map(c =>
                c.id === id
                    ? { ...c, format: (c.format || 'feed') === 'stories' ? 'feed' : 'stories' }
                    : c
            )
        }));
    };

    // Shared by applyAutoStoriesDupe and duplicateCreative — strips any
    // existing trailing " (Feed)"/" (Stories)" before appending the new one,
    // so duplicating an already-duplicated card (manually copying an
    // auto-duped half, or re-duplicating a manual duplicate) can't stack into
    // "file.jpg (Stories) (Feed)". Verified reachable via the UI's own Copy
    // button (pre-push review follow-up, code-auditor: LOW) since only the
    // real merged Drive pair is excluded from it, not an auto-duped half.
    const namePlacementSuffix = (name, format) => {
        const base = (name || '').replace(/ \((Feed|Stories)\)$/, '');
        return `${base} (${format === 'stories' ? 'Stories' : 'Feed'})`;
    };

    // Kicks off the real server-side crop (backend/app/services/image_crop_service.py)
    // for a duplicate card and writes the result back onto that exact card by id
    // once it resolves. Runs against the ORIGINAL source's own file/URL (passed in
    // separately, never the duplicate's own in-flight previewUrl) so re-cropping
    // with a different anchor later always starts from the pristine source, not
    // an already-cropped result. On failure, falls back to the uncropped source
    // image (already showing, since the placeholder card was seeded from it) and
    // flags cropFailed so Joel can see it and retry or remove it — never blocks or
    // silently ships a broken card.
    const requestSmartCrop = async (dupeId, source, format, anchor) => {
        const targetRatio = format === 'stories' ? '9:16' : '1:1';
        try {
            const { url, crop_axis: cropAxis } = await cropImageToAspect({
                file: source.file || undefined,
                sourceUrl: source.file ? undefined : source.url,
                targetRatio,
                anchor,
            });
            setCreativeData(prev => ({
                ...prev,
                creatives: prev.creatives.map(c => (
                    c.id === dupeId
                        ? { ...c, previewUrl: url, imageUrl: url, file: null, cropping: false, cropFailed: false, cropAnchor: anchor, cropAxis }
                        : c
                )),
            }));
        } catch (error) {
            console.error('Smart-crop failed:', error);
            setCreativeData(prev => ({
                ...prev,
                creatives: prev.creatives.map(c => (
                    c.id === dupeId ? { ...c, cropping: false, cropFailed: true } : c
                )),
            }));
        }
    };

    // Applied at every point a new SINGLE-placement image creative is added
    // (manual upload, drag-drop, a Drive selection that isn't already a real
    // tagged pair) — when autoDupeStories is on, immediately gives it the
    // opposite-placement duplicate this used to require a manual "Dupe as
    // Stories" click for, one image at a time. Skips videos (dual-placement
    // is image-only, per create_creative's own docstring) and anything
    // already carrying both placements (dualPlacement: true — a real tagged
    // Feed+Stories pair already covers both, duplicating it again would just
    // create a redundant third entry).
    //
    // The duplicate is added immediately with the uncropped source image as a
    // placeholder (cropping: true) so the grid never blocks on the network
    // round-trip — requestSmartCrop swaps in the real cropped result in place
    // moments later. Steve's own call: reusing the same image untouched (the
    // original version of this feature) wasn't good enough — a photo composed
    // for square Feed can look cropped/stretched wrong in a 9:16 frame with no
    // real crop applied, so this always produces an actual correctly-cropped
    // image server-side rather than just relabeling the source.
    const applyAutoStoriesDupe = (creative) => {
        if (!autoDupeStories || creative.mediaType === 'video' || creative.dualPlacement) {
            return [creative];
        }
        const flippedFormat = (creative.format || 'feed') === 'stories' ? 'feed' : 'stories';
        const dupeId = `${creative.id}_autodupe`;
        const duplicate = {
            ...creative,
            id: dupeId,
            format: flippedFormat,
            name: namePlacementSuffix(creative.name, flippedFormat),
            cropping: true,
            cropFailed: false,
            cropAnchor: 'center',
            cropSourceFile: creative.file || null,
            cropSourceUrl: creative.file ? null : (creative.imageUrl || creative.previewUrl),
        };
        requestSmartCrop(dupeId, { file: creative.file, url: duplicate.cropSourceUrl }, flippedFormat, 'center');
        return [creative, duplicate];
    };

    // Duplicate a creative and pre-toggle its format (feed → stories, stories → feed)
    // — the manual "Copy" button, still here for autoDupeStories-off batches or
    // adding an extra placement by hand. Goes through the same real smart-crop as
    // the automatic path (see applyAutoStoriesDupe above) rather than the plain
    // image-reuse this used to do.
    const duplicateCreative = (id) => {
        const original = creativeData.creatives.find(c => c.id === id);
        if (!original) return;
        const flippedFormat = (original.format || 'feed') === 'stories' ? 'feed' : 'stories';
        const dupeId = `creative_${Date.now()}_dup`;
        // Prefer the ORIGINAL's own pristine cropSourceFile/cropSourceUrl (set
        // once when it was itself created) over its current file/imageUrl.
        // Once a card's own smart-crop resolves, requestSmartCrop clears
        // `file` and points imageUrl/previewUrl at the CROPPED result — so
        // duplicating an already-cropped card without this fallback would
        // crop-from-a-crop instead of the true source, silently reintroducing
        // exactly the "badly cropped" problem this feature exists to fix
        // (code-auditor pre-push review, HIGH).
        const cropSourceFile = original.cropSourceFile || original.file || null;
        const cropSourceUrl = cropSourceFile
            ? null
            : (original.cropSourceUrl || original.imageUrl || original.previewUrl);
        const duplicate = {
            ...original,
            id: dupeId,
            format: flippedFormat,
            // Same disambiguation as applyAutoStoriesDupe above — otherwise
            // this manual duplicate is only tellable apart from the original
            // by which ad set it lands in. namePlacementSuffix strips any
            // suffix already there first, so duplicating an auto-duped or
            // already-duplicated card can't stack into "(Stories) (Feed)".
            name: namePlacementSuffix(original.name, flippedFormat),
            cropping: original.mediaType !== 'video',
            cropFailed: false,
            // Only set for images — a video isn't cropped at all (see below),
            // and cropAnchor being present is what the anchor-picker UI keys
            // off to decide whether to render itself on a card.
            cropAnchor: original.mediaType !== 'video' ? 'center' : undefined,
            cropSourceFile,
            cropSourceUrl,
        };
        setCreativeData(prev => ({ ...prev, creatives: [...prev.creatives, duplicate] }));
        if (original.mediaType !== 'video') {
            requestSmartCrop(dupeId, { file: cropSourceFile, url: cropSourceUrl }, flippedFormat, 'center');
        }
    };

    // Re-crops an existing card in place with a different anchor — the small
    // Left/Center/Right (or Top/Center/Bottom) control on any smart-cropped
    // card. Always re-runs from the stable cropSourceFile/cropSourceUrl saved
    // at duplicate-creation time, never from the card's own current (already
    // cropped) previewUrl, so repeated anchor changes don't compound crops.
    const recropCreative = (id, anchor) => {
        const creative = creativeData.creatives.find(c => c.id === id);
        if (!creative) return;
        setCreativeData(prev => ({
            ...prev,
            creatives: prev.creatives.map(c => (c.id === id ? { ...c, cropping: true, cropFailed: false } : c)),
        }));
        requestSmartCrop(id, { file: creative.cropSourceFile, url: creative.cropSourceUrl }, creative.format, anchor);
    };

    const handleNext = () => {
        // Validate required fields
        if (!creativeData.creativeName) {
            showWarning('Please enter a creative name');
            return;
        }

        // Match-import mode gets its copy/media/CTA per-row from the CSV + image
        // folder in the next step — none of that lives on shared creativeData,
        // so skip straight to the fields this mode actually collects.
        if (!isMatchImport) {
            if (!creativeData.creatives || creativeData.creatives.length === 0) {
                showWarning('Please upload at least one image or video');
                return;
            }

            // Crops normally resolve in a second or two, but block proceeding
            // while any is still in flight rather than letting Joel launch
            // whatever the placeholder (uncropped source) image happened to
            // be at that instant.
            if (creativeData.creatives.some(c => c.cropping)) {
                showWarning('Still cropping the Feed/Stories versions — give it a moment and try again.');
                return;
            }

            // A failed crop falls back to showing the uncropped source (never
            // silently ships nothing), but that fallback is exactly the "same
            // image relabeled" problem this feature replaced — block launch
            // until Joel retries or removes it rather than letting a failed
            // card slip through unnoticed (joel-perspective pre-push review, P1).
            // Names a count rather than "one or more" — a follow-up from that
            // same review: on a large bulk grid, a generic warning leaves him
            // guessing how many red banners to go find.
            if (cropFailedCount > 0) {
                showWarning(
                    `${cropFailedCount} Feed/Stories crop${cropFailedCount !== 1 ? 's' : ''} failed — retry or remove ${cropFailedCount !== 1 ? 'them' : 'it'} before continuing.`
                );
                return;
            }

            // Drive selections may carry different copy per image/pair. In that
            // mode validate each card instead of validating only the first
            // global field (which could otherwise apply retail copy to a
            // restaurant ad at launch).
            const perCreativeCopyMode = creativeData.creatives.some(c => c.source === 'drive' || c.headline || c.body);
            if (perCreativeCopyMode) {
                const pairMetadataMismatchIds = new Set(
                    creativeData.creatives
                        .filter(c => c.driveCopyIntegrityIssue)
                        .map(c => c.drivePairId || c.id)
                );
                if (pairMetadataMismatchIds.size > 0) {
                    focusCopyCreative(creativeData.creatives.find(c => c.driveCopyIntegrityIssue)?.id || null);
                    showWarning(`${pairMetadataMismatchIds.size} Feed + Stories pair${pairMetadataMismatchIds.size !== 1 ? 's have' : ' has'} mismatched Drive copy, CTA, or destination data. Return to the Drive picker and refresh the paired source files before continuing.`);
                    return;
                }
                const missingCopy = creativeData.creatives.filter(c => (
                    c.source === 'drive'
                        ? (!c.body?.trim() || !c.headline?.trim())
                        : (!(c.body?.trim() || creativeData.bodies[0]?.trim()) ||
                            !(c.headline?.trim() || creativeData.headlines[0]?.trim()))
                ));
                if (missingCopy.length > 0) {
                    focusCopyCreative(missingCopy[0].id);
                    showWarning(`${missingCopy.length} selected ad${missingCopy.length !== 1 ? 's' : ''} still needs its own Primary Text and Headline. Edit the Ad pairs & copy rows before continuing.`);
                    return;
                }
                const missingDriveCta = creativeData.creatives.find(c => c.source === 'drive' && !c.cta?.trim());
                if (missingDriveCta) {
                    focusCopyCreative(missingDriveCta.id);
                    showWarning(`The Drive CTA for ${missingDriveCta.name || 'one selected ad'} is missing. Refresh its Drive pair before continuing.`);
                    return;
                }
                const invalidDriveCta = creativeData.creatives.find(c => (
                    c.source === 'drive' && c.cta?.trim() && !CTA_OPTIONS.includes(c.cta.trim())
                ));
                if (invalidDriveCta) {
                    focusCopyCreative(invalidDriveCta.id);
                    showWarning(`The Drive CTA for ${invalidDriveCta.name || 'one selected ad'} is not a Meta-supported CTA. Correct it in Drive, then refresh the pair before continuing.`);
                    return;
                }
            } else {
                if (!creativeData.bodies[0] || !creativeData.bodies[0].trim()) {
                    showWarning('Please provide primary text');
                    return;
                }
                if (!creativeData.headlines[0] || !creativeData.headlines[0].trim()) {
                    showWarning('Please provide a headline');
                    return;
                }
            }
        }

        const missingCreativeUrl = creativeData.creatives.find(c => (
            c.source === 'drive' ? !c.websiteUrl?.trim() : !creativeData.websiteUrl?.trim() && !c.websiteUrl?.trim()
        ));
        if (missingCreativeUrl) {
            focusCopyCreative(missingCreativeUrl.id);
            showWarning(`The destination URL for ${missingCreativeUrl.name || 'one selected ad'} is missing. Add it before continuing.`);
            return;
        }

        // Validate the global URL when it is used by any non-Drive creative.
        if (creativeData.websiteUrl) {
            try {
                const url = new URL(creativeData.websiteUrl);
                if (!url.protocol.startsWith('http')) {
                    showWarning('Please enter a valid URL starting with http:// or https://');
                    return;
                }
            } catch (e) {
                showWarning('Please enter a valid URL (e.g., https://example.com)');
                return;
            }
        }

        const invalidCreativeUrl = creativeData.creatives.find(c => c.websiteUrl && (() => {
            try { return !new URL(c.websiteUrl).protocol.startsWith('http'); } catch { return true; }
        })());
        if (invalidCreativeUrl) {
            focusCopyCreative(invalidCreativeUrl.id);
            showWarning(`The destination URL for ${invalidCreativeUrl.name || 'one selected ad'} is invalid. Fix it before continuing.`);
            return;
        }

        if (!creativeData.pageId) {
            showWarning('Please enter a Facebook Page ID');
            return;
        }

        if (!isMatchImport) {
            // Validate Meta copy length hard limits
            const overLimitHeadlines = creativeData.headlines.filter(h => h && h.length > HEADLINE_LIMIT);
            if (overLimitHeadlines.length > 0) {
                showWarning(`Headline exceeds Facebook's ${HEADLINE_LIMIT}-character limit. Please shorten it.`);
                return;
            }
            const overLimitBodies = creativeData.bodies.filter(b => b && b.length > BODY_LIMIT);
            if (overLimitBodies.length > 0) {
                showWarning(`Primary text exceeds Facebook's ${BODY_LIMIT}-character limit. Please shorten it.`);
                return;
            }
            const overLimitCreativeCopy = creativeData.creatives.find(c => (
                (c.headline && c.headline.length > HEADLINE_LIMIT) ||
                (c.body && c.body.length > BODY_LIMIT) ||
                (c.description && c.description.length > DESC_LIMIT)
            ));
            if (overLimitCreativeCopy) {
                focusCopyCreative(overLimitCreativeCopy.id);
                showWarning('One of the selected ad cards exceeds a Meta copy limit. Please shorten it before continuing.');
                return;
            }
            if (creativeData.description && creativeData.description.length > DESC_LIMIT) {
                showWarning(`Description exceeds Facebook's ${DESC_LIMIT}-character limit. Please shorten it.`);
                return;
            }
        }

        // Save URL to local storage for this ad account + campaign
        if (selectedAdAccount && creativeData.websiteUrl) {
            safeLocalStorageSet(`defaultUrl_${selectedAdAccount.id}_${campaignCacheId}`, creativeData.websiteUrl);
        }

        onNext();
    };

    return (
        <>
        <div>
            {isMatchImport ? (
                <>
                    <h2 className="text-2xl font-bold mb-6">Ad Creative - Basic Info</h2>
                    <p className="text-gray-600 mb-6">
                        Match by Naming Convention only needs a creative name, Facebook Page, and destination link here — everything else comes from your CSV and image folder in the next step.
                    </p>
                </>
            ) : (
                <>
                    <h2 className="text-2xl font-bold mb-6">Ad Creative - Standard Ads</h2>
                    <p className="text-gray-600 mb-3">
                        This creates standard (non-Dynamic) ads. Each image you upload becomes one separate ad on Facebook.
                    </p>
                    {/* Live variation counter — updates as media/headlines/bodies are added below,
                        instead of only surfacing this math once the user reaches Review. Mirrors
                        the exact computation BulkAdCreation.jsx's Review screen uses. */}
                    <div className="sticky top-2 z-10 bg-amber-50 border border-amber-200 rounded-lg px-4 py-3 mb-6 text-sm text-amber-900 shadow-sm">
                        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                            <span className="font-mono font-semibold">
                                {variationCount.media} MEDIA × {variationCount.headlines} HEADLINE{variationCount.headlines !== 1 ? 'S' : ''} × {variationCount.bodies} BOD{variationCount.bodies !== 1 ? 'IES' : 'Y'}
                            </span>
                            <span>=</span>
                            <span className="font-mono font-bold text-amber-950">
                                {variationCount.total} ad{variationCount.total !== 1 ? 's' : ''}
                            </span>
                        </div>
                        {variationCount.total === 0 && (() => {
                            // Name the specific missing field(s) rather than a generic
                            // "add all three" line — a headline/body that's whitespace-only
                            // (not literally empty) also filters to 0 here, which a generic
                            // message wouldn't explain to someone who thinks they already
                            // filled it in.
                            const missing = [
                                variationCount.media === 0 && 'an image or video',
                                variationCount.headlines === 0 && 'a headline',
                                variationCount.bodies === 0 && 'body text',
                            ].filter(Boolean);
                            return (
                                <p className="mt-1 text-xs text-amber-700">
                                    Missing: {missing.join(', ')}.
                                </p>
                            );
                        })()}
                    </div>
                </>
            )}

            <div className="space-y-6">
                {/* Creative Name */}
                <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">
                        Creative Name *
                    </label>
                    <input
                        type="text"
                        value={creativeData.creativeName}
                        onChange={(e) => handleInputChange('creativeName', e.target.value)}
                        placeholder="e.g. Summer Sale – June 2025"
                        className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-amber-500 focus:border-transparent"
                    />
                </div>

                {/* Facebook Page Selection */}
                <div>
                    <div className="flex justify-between items-center mb-2">
                        <label className="block text-sm font-medium text-gray-700">
                            Facebook Page *
                        </label>
                        <button
                            onClick={() => setManualPageEntry(!manualPageEntry)}
                            className="text-xs text-amber-600 hover:text-amber-800 underline"
                        >
                            {manualPageEntry ? 'Select from list' : 'Enter Page ID manually'}
                        </button>
                    </div>

                    {manualPageEntry ? (
                        <input
                            type="text"
                            value={creativeData.pageId}
                            onChange={(e) => handleInputChange('pageId', e.target.value)}
                            placeholder="Enter Facebook Page ID (e.g., 933995649786806)"
                            className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-amber-500 focus:border-transparent"
                        />
                    ) : loadingPages ? (
                        <div className="flex items-center gap-2 text-gray-500 py-2">
                            <Loader className="animate-spin" size={20} />
                            <span>Loading pages...</span>
                        </div>
                    ) : (
                        <select
                            value={creativeData.pageId}
                            onChange={(e) => handlePageSelection(e.target.value)}
                            className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-amber-500 focus:border-transparent"
                        >
                            <option value="">Select a Facebook Page...</option>
                            {pages.map(page => (
                                <option key={page.id} value={page.id}>
                                    {page.name}
                                </option>
                            ))}
                        </select>
                    )}

                    {!manualPageEntry && pages.length === 0 && !loadingPages && (
                        <div className="mt-2">
                            <p className="text-xs text-red-500 mb-1">
                                No pages found. Please make sure your ad account has access to at least one Facebook Page.
                            </p>
                            <button
                                onClick={() => setManualPageEntry(true)}
                                className="text-xs text-amber-600 font-medium hover:underline"
                            >
                                Enter Page ID manually instead
                            </button>
                        </div>
                    )}
                </div>

                {/* Media Upload (Images + Videos) — Match Import gets these per-row from the CSV/image folder */}
                {!isMatchImport && (
                <div>
                    {/* Creative source chooser — Drive is the primary bulk-launch workflow so it
                        gets top billing; Generated Ads and Upload/manual stay first-class, not
                        buried. Hierarchy change only: every source below still does exactly what
                        it did before (same modals, same upload input). */}
                    <div className="mb-4">
                        <h3 className="text-base font-semibold text-gray-900">Choose your creative source</h3>
                        <p className="text-sm text-gray-500 mb-3">Select from an existing library, upload new media, or build the combinations manually.</p>
                        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                            <div className="relative">
                                {showDriveLibraryHint && (
                                    <div className="absolute left-0 bottom-full z-10 mb-2 w-64 rounded-lg border border-indigo-200 bg-indigo-50 p-3 text-left text-xs text-indigo-900 shadow-md">
                                        <button
                                            type="button"
                                            onClick={dismissDriveLibraryHint}
                                            className="absolute right-2 top-1 text-indigo-400 hover:text-indigo-700"
                                            aria-label="Dismiss Drive library hint"
                                        >
                                            ×
                                        </button>
                                        <strong className="block pr-3">New: browse your synced Drive assets here</strong>
                                        <span className="block mt-1">Your shared creative library is ready for bulk ad launches.</span>
                                    </div>
                                )}
                                <button
                                    type="button"
                                    onClick={() => { dismissDriveLibraryHint(); openDriveLibraryModal(); }}
                                    className="w-full h-full text-left rounded-xl border-2 border-indigo-200 bg-indigo-50 hover:border-indigo-400 hover:bg-indigo-100 transition-colors p-4"
                                >
                                    <div className="flex items-center gap-2 text-indigo-700 font-semibold">
                                        <FolderOpen size={18} />
                                        Drive Creative Library
                                    </div>
                                    <p className="text-xs text-indigo-600 mt-1 mb-3">Use synced Feed and Stories assets</p>
                                    <span className="inline-flex items-center text-sm font-semibold text-indigo-800 bg-white rounded-md px-2.5 py-1 border border-indigo-200">
                                        Browse Drive Library · {driveAssets.length} asset{driveAssets.length !== 1 ? 's' : ''}
                                    </span>
                                </button>
                            </div>

                            <button
                                type="button"
                                onClick={openLibraryModal}
                                className="text-left rounded-xl border-2 border-gray-200 bg-white hover:border-amber-300 hover:bg-amber-50 transition-colors p-4"
                            >
                                <div className="flex items-center gap-2 text-amber-700 font-semibold">
                                    <BookOpen size={18} />
                                    Generated Ads
                                </div>
                                <p className="text-xs text-gray-500 mt-1 mb-3">Reuse images already generated in Ad Builder</p>
                                <span className="inline-flex items-center text-sm font-semibold text-amber-700 bg-amber-50 rounded-md px-2.5 py-1 border border-amber-200">
                                    Browse Generated Ads
                                </span>
                            </button>

                            <button
                                type="button"
                                onClick={() => document.getElementById('ad-media-upload')?.click()}
                                className="text-left rounded-xl border-2 border-gray-200 bg-white hover:border-amber-300 hover:bg-amber-50 transition-colors p-4"
                            >
                                <div className="flex items-center gap-2 text-gray-700 font-semibold">
                                    <Image size={18} />
                                    Upload or build manually
                                </div>
                                <p className="text-xs text-gray-500 mt-1 mb-3">Add new media and enter copy yourself</p>
                                <span className="inline-flex items-center text-sm font-semibold text-gray-700 bg-gray-50 rounded-md px-2.5 py-1 border border-gray-200">
                                    Upload media
                                </span>
                            </button>
                        </div>
                    </div>

                    <label className="block text-sm font-medium text-gray-700 mb-2">
                        Ad Media (Images or Videos) *
                    </label>

                    {/* Defaults ON — Joel wants Feed + Stories launched together as the
                        normal case, not an extra click per image. Applies to every new
                        single-placement image from here on (upload, drag-drop, and a
                        Drive pick that isn't already a real tagged pair) — including
                        bulk adds, so selecting 50 unpaired Drive images with this on
                        adds 100 media entries, not 50. Never touches images already
                        added, a real Feed+Stories pair, or videos. Persists across
                        sessions (see autoDupeStoriesDefault above) — the OFF-state
                        notice right below exists specifically because of that: a state
                        set once and forgotten needs to be at least as visible as the
                        ON state, or it's a silent "why did Stories placements go quiet"
                        surprise weeks later (pre-push review, joel-perspective: P1). */}
                    <label className="flex items-center gap-2 mb-1 text-sm text-gray-600 cursor-pointer select-none">
                        <input
                            type="checkbox"
                            checked={autoDupeStories}
                            onChange={(e) => handleAutoDupeStoriesChange(e.target.checked)}
                            className="rounded border-gray-300 text-amber-600 focus:ring-amber-500"
                        />
                        Automatically create the matching Stories (9:16) version for each new image
                    </label>
                    {autoDupeStories ? (
                        <p className="mb-3 text-xs text-gray-400">
                            Reuses the same image for both — a photo composed for square Feed may look cropped or
                            stretched in the vertical Stories frame. Check the Stories card before launching, or
                            remove it with its "x" if it doesn't work.
                        </p>
                    ) : (
                        <p className="mb-3 text-xs font-medium text-amber-700 bg-amber-50 border border-amber-200 rounded px-2 py-1 inline-block">
                            Off — new images will be Feed-only. Nothing launches to Instagram/Facebook Stories until you turn this back on or duplicate one by hand.
                        </p>
                    )}

                    {/* Upload Area */}
                    <div
                        className={`border-2 border-dashed rounded-lg p-8 text-center transition-colors mb-4 ${isDragging ? 'border-amber-500 bg-amber-50' : 'border-gray-300 hover:border-amber-500'
                            }`}
                        onDragEnter={handleDragEnter}
                        onDragOver={handleDragOver}
                        onDragLeave={handleDragLeave}
                        onDrop={handleDrop}
                    >
                        <input
                            type="file"
                            accept="image/*,video/*"
                            multiple
                            onChange={handleMediaUpload}
                            className="hidden"
                            id="ad-media-upload"
                        />
                        <label htmlFor="ad-media-upload" className="cursor-pointer flex flex-col items-center">
                            <div className="flex gap-2 mb-2">
                                <Image className={`${isDragging ? 'text-amber-500' : 'text-gray-400'}`} size={28} />
                                <Film className={`${isDragging ? 'text-amber-500' : 'text-gray-400'}`} size={28} />
                            </div>
                            <span className={`font-medium ${isDragging ? 'text-amber-700' : 'text-gray-600'}`}>
                                {isDragging ? 'Drop files here' : 'Click to upload images or videos'}
                            </span>
                            <span className="text-sm text-gray-400 mt-1">or drag and drop</span>
                            <span className="text-xs text-amber-500 mt-2 bg-amber-50 px-2 py-1 rounded">Supports multiple files • Videos up to 500MB</span>
                        </label>
                    </div>

                    {/* Media Grid */}
                    {creativeData.creatives && creativeData.creatives.length > 0 && (
                        <div className="mb-3 px-3 py-2 bg-blue-50 border border-blue-200 rounded-lg text-xs text-blue-800 flex items-center justify-between gap-3 flex-wrap">
                            <span>
                                <strong>Placement tag:</strong> Each image defaults to <span className="font-semibold text-blue-700">Feed (1:1)</span>. Click the pill on any card to switch it to <span className="font-semibold text-purple-700">Stories (9:16)</span>. Use the copy icon to duplicate an image for the opposite placement.
                                {autoDupeStories && ' With auto-duplicate on above, new single images already come in as a Feed + Stories pair — remove either card if you only want one.'}
                            </span>
                            {creativeData.creatives.some(c => c.id.endsWith('_autodupe')) && (
                                <button
                                    type="button"
                                    onClick={removeAutoDupedCreatives}
                                    className="shrink-0 text-xs font-semibold text-blue-700 underline hover:text-blue-900"
                                >
                                    Remove all auto-added Stories/Feed duplicates
                                </button>
                            )}
                        </div>
                    )}
                    {/* Aggregate crop-batch banner — a dense bulk grid (e.g. a
                        50-image Drive add) reads as a wall of per-card spinners
                        with no way to tell "still working" from "stuck" at a
                        glance; this gives the batch a single visible number.
                        Progress-only while in flight; separately, a persistent
                        failure summary + one-click retry-all once anything
                        fails, so Joel isn't hunting red banners card by card
                        (joel-perspective follow-up on the smart-crop feature). */}
                    {croppingCount > 0 && (
                        <div className="mb-3 px-3 py-2 bg-indigo-50 border border-indigo-200 rounded-lg text-xs text-indigo-800 flex items-center gap-2">
                            <Loader className="animate-spin shrink-0" size={14} />
                            Cropping Feed/Stories versions — {cropBatchProgress.done} of {cropBatchProgress.total} done
                        </div>
                    )}
                    {cropFailedCount > 0 && (
                        <div className="mb-3 px-3 py-2 bg-red-50 border border-red-200 rounded-lg text-xs text-red-800 flex items-center justify-between gap-3 flex-wrap">
                            <span>
                                <strong>{cropFailedCount}</strong> Feed/Stories crop{cropFailedCount !== 1 ? 's' : ''} failed — showing the uncropped image on those cards.
                            </span>
                            <button
                                type="button"
                                onClick={retryAllFailedCrops}
                                className="shrink-0 text-xs font-semibold text-red-700 underline hover:text-red-900"
                            >
                                Retry all {cropFailedCount} failed crop{cropFailedCount !== 1 ? 's' : ''}
                            </button>
                        </div>
                    )}
                    {creativeData.creatives && creativeData.creatives.length > 0 && (
                        <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-5 lg:grid-cols-6 gap-3 mb-4">
                            {creativeData.creatives.map((creative) => (
                                <div key={creative.id} className="relative group border rounded-lg overflow-hidden aspect-square bg-gray-100">
                                    {creative.mediaType === 'video' ? (
                                        <video
                                            src={creative.previewUrl}
                                            className="w-full h-full object-cover"
                                            muted
                                            playsInline
                                            onMouseEnter={(e) => e.target.play()}
                                            onMouseLeave={(e) => { e.target.pause(); e.target.currentTime = 0; }}
                                        />
                                    ) : (
                                        <img
                                            src={creative.previewUrl}
                                            alt={creative.name}
                                            className="w-full h-full object-cover"
                                        />
                                    )}
                                    {/* In-flight state for the real server-side crop
                                        (requestSmartCrop) — the card already shows the
                                        uncropped source as a placeholder underneath, this
                                        overlay just makes clear it's not final yet. */}
                                    {creative.cropping && (
                                        <div className="absolute inset-0 bg-black bg-opacity-50 flex flex-col items-center justify-center gap-1.5 text-white text-xs">
                                            <Loader className="animate-spin" size={20} />
                                            Cropping for {(creative.format || 'feed') === 'stories' ? 'Stories' : 'Feed'}...
                                        </div>
                                    )}
                                    {creative.cropFailed && (
                                        <div className="absolute inset-x-0 top-0 bg-red-600 text-white text-[11px] px-2 py-1 flex items-center justify-between gap-2">
                                            <span>Crop failed — showing uncropped image</span>
                                            <button
                                                type="button"
                                                onClick={(e) => { e.stopPropagation(); recropCreative(creative.id, creative.cropAnchor); }}
                                                className="underline font-semibold shrink-0"
                                            >
                                                Retry
                                            </button>
                                        </div>
                                    )}
                                    {/* Media type badge */}
                                    <div className="absolute top-2 left-2">
                                        {creative.mediaType === 'video' ? (
                                            <span className="bg-purple-600 text-white text-xs px-2 py-1 rounded flex items-center gap-1">
                                                <Film size={12} /> Video
                                            </span>
                                        ) : (
                                            <span className="bg-blue-600 text-white text-xs px-2 py-1 rounded flex items-center gap-1">
                                                <Image size={12} /> Image
                                            </span>
                                        )}
                                    </div>
                                    {creative.dualPlacement && (
                                        <div className="absolute top-2 right-2 bg-purple-600 text-white text-[11px] font-semibold px-2 py-1 rounded-full shadow-sm flex items-center gap-1">
                                            <Layers size={12} /> Feed + Stories linked
                                        </div>
                                    )}
                                    <div className="absolute inset-0 bg-black bg-opacity-0 group-hover:bg-opacity-30 transition-all flex items-center justify-center gap-2 opacity-0 group-hover:opacity-100">
                                        {/* Duplicate-as-opposite-placement doesn't apply once a creative
                                            already carries both a feed and a stories image — it's not a
                                            single asset being reused at a second placement, it's already
                                            both. */}
                                        {!creative.dualPlacement && (
                                            <button
                                                onClick={(e) => { e.stopPropagation(); duplicateCreative(creative.id); }}
                                                className="flex items-center gap-1 px-2 py-1.5 bg-blue-500 text-white rounded-lg hover:bg-blue-600 text-xs font-medium transform scale-90 hover:scale-100 transition-all"
                                                title={`Duplicate as ${(creative.format || 'feed') === 'stories' ? 'Feed (1:1)' : 'Stories (9:16)'}`}
                                            >
                                                <Copy size={13} />
                                                {(creative.format || 'feed') === 'stories' ? 'Dupe as Feed' : 'Dupe as Stories'}
                                            </button>
                                        )}
                                        <button
                                            onClick={() => removeCreative(creative.id)}
                                            className="p-2 bg-red-500 text-white rounded-full hover:bg-red-600 transform scale-90 hover:scale-100 transition-all"
                                            title="Remove media"
                                        >
                                            <Trash2 size={16} />
                                        </button>
                                    </div>
                                    {/* Reposition the smart-crop when the default center cut
                                        removes something important — re-crops from the original
                                        source (cropSourceFile/cropSourceUrl), never the current
                                        already-cropped result, so this never compounds. Labels use
                                        cropAxis returned by the backend (which axis it ACTUALLY
                                        trimmed, from the real source dimensions vs. target ratio)
                                        rather than guessing from the Feed/Stories format label — a
                                        landscape photo duped to square Feed still trims WIDTH, so
                                        format alone doesn't reliably predict the axis
                                        (code-auditor pre-push review, MEDIUM). Always visible
                                        (not hover-only) since a bulk grid makes a hover-only
                                        control easy to never discover (joel-perspective, P1). */}
                                    {creative.cropAnchor && creative.cropAxis && creative.cropAxis !== 'none' && !creative.cropping && !creative.cropFailed && (
                                        <div
                                            className="absolute bottom-6 left-0 right-0 flex items-center justify-center gap-1 px-1.5 py-1"
                                            onClick={(e) => e.stopPropagation()}
                                        >
                                            {['start', 'center', 'end'].map(anchor => {
                                                const isVertical = creative.cropAxis === 'height';
                                                const labels = isVertical
                                                    ? { start: 'Top', center: 'Mid', end: 'Bot' }
                                                    : { start: 'Left', center: 'Ctr', end: 'Right' };
                                                return (
                                                    <button
                                                        key={anchor}
                                                        type="button"
                                                        onClick={() => recropCreative(creative.id, anchor)}
                                                        className={`px-1.5 py-0.5 rounded text-[10px] font-semibold shadow-sm ${
                                                            creative.cropAnchor === anchor
                                                                ? 'bg-amber-500 text-white'
                                                                : 'bg-white/70 text-gray-700 hover:bg-white'
                                                        }`}
                                                        title={`Re-crop anchored to ${labels[anchor]}`}
                                                    >
                                                        {labels[anchor]}
                                                    </button>
                                                );
                                            })}
                                        </div>
                                    )}
                                    <div className="absolute bottom-0 left-0 right-0 bg-black bg-opacity-60 text-white text-xs flex items-center gap-1 px-1.5 py-1">
                                        <span className="truncate flex-1 min-w-0">{creative.name}</span>
                                        {creative.dualPlacement ? (
                                            // Not a toggle — this creative already carries both a feed
                                            // and a stories image via secondaryImageUrl, shown together
                                            // in Meta as one ad. Nothing to switch between.
                                            <span
                                                className="flex-shrink-0 px-1.5 py-0.5 rounded text-[10px] font-bold leading-tight bg-purple-500"
                                                title="Feed (1:1) + Stories (9:16) — one ad, Meta shows the right image per placement"
                                            >
                                                1:1 + 9:16
                                            </span>
                                        ) : (
                                            <button
                                                type="button"
                                                onClick={(e) => { e.stopPropagation(); toggleCreativeFormat(creative.id); }}
                                                className={`flex-shrink-0 px-1.5 py-0.5 rounded text-[10px] font-bold leading-tight transition-colors ${
                                                    (creative.format || 'feed') === 'stories'
                                                        ? 'bg-purple-500 hover:bg-purple-400'
                                                        : 'bg-blue-600 hover:bg-blue-500'
                                                }`}
                                                title={(creative.format || 'feed') === 'stories'
                                                    ? 'Stories & Reels (9:16) — click to switch to Feed'
                                                    : 'Feed (1:1) — click to switch to Stories & Reels (9:16)'}
                                            >
                                                {(creative.format || 'feed') === 'stories' ? '9:16' : '1:1'}
                                            </button>
                                        )}
                                    </div>
                                </div>
                            ))}
                        </div>
                )}

                    {!isMatchImport && creativeData.creatives?.length > 0 && (() => {
                        const selectedCreative = creativeData.creatives.find(creative => creative.id === selectedCopyCreativeId)
                            || creativeData.creatives[0];
                        const selectedIndex = creativeData.creatives.findIndex(creative => creative.id === selectedCreative.id);
                        const selectedIsDrive = selectedCreative.source === 'drive';
                        const selectedBody = selectedCreative.body || (!selectedIsDrive ? creativeData.bodies?.[0] || '' : '');
                        const selectedHeadline = selectedCreative.headline || (!selectedIsDrive ? creativeData.headlines?.[0] || '' : '');
                        const selectedDescription = selectedCreative.description || (!selectedIsDrive ? creativeData.description || '' : '');
                        const selectedCta = selectedCreative.cta || (!selectedIsDrive ? creativeData.cta || '' : '');
                        const selectedUrl = selectedCreative.websiteUrl || (!selectedIsDrive ? creativeData.websiteUrl || '' : '');
                        const rowIssues = (creative) => {
                            const isDrive = creative.source === 'drive';
                            const headline = (creative.headline || (!isDrive && creativeData.headlines?.[0]) || '').trim();
                            const body = (creative.body || (!isDrive && creativeData.bodies?.[0]) || '').trim();
                            const cta = (creative.cta || (!isDrive && creativeData.cta) || '').trim();
                            const url = creative.websiteUrl || (!isDrive && creativeData.websiteUrl) || '';
                            const description = creative.description || (!isDrive && creativeData.description) || '';
                            const issues = [];
                            if (!body) issues.push('Primary text');
                            if (!headline) issues.push('Headline');
                            if (!CTA_OPTIONS.includes(cta)) issues.push('CTA');
                            try { if (!new URL(url).protocol.startsWith('http')) issues.push('URL'); } catch { issues.push('URL'); }
                            if (creative.driveCopyIntegrityIssue) issues.push('Drive pair');
                            if (body.length > BODY_LIMIT) issues.push('Primary text length');
                            if (headline.length > HEADLINE_LIMIT) issues.push('Headline length');
                            if (description.length > DESC_LIMIT) issues.push('Description length');
                            return issues;
                        };
                        const selectedIssues = rowIssues(selectedCreative);
                        const selectedCopyReady = selectedIssues.length === 0;
                        return (
                            <section ref={copyEditorRef} className="mt-4 rounded-xl border border-indigo-200 bg-indigo-50/50 p-4">
                                <div className="mb-3 flex items-start justify-between gap-3">
                                    <div>
                                        <h3 className="text-sm font-semibold text-gray-900">Ad pairs &amp; copy</h3>
                                        <p className="mt-0.5 text-xs text-gray-600">Select a row to edit its own copy. The shared fallback fields are minimized below.</p>
                                    </div>
                                    <span className="shrink-0 rounded-full border border-indigo-200 bg-white px-2 py-1 text-[11px] font-semibold text-indigo-700">{creativeData.creatives.length} ads</span>
                                </div>
                                <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
                                    <div className="max-h-[660px] overflow-y-auto rounded-xl border border-gray-200 bg-white">
                                        <div className="hidden grid-cols-[76px_minmax(0,1fr)_110px] gap-3 border-b border-gray-200 bg-gray-50 px-4 py-2 text-[10px] font-semibold uppercase tracking-wide text-gray-500 md:grid">
                                            <span>Creative</span><span>Ad / copy</span><span className="text-right">Status</span>
                                        </div>
                                        {creativeData.creatives.map((creative, index) => {
                                            const selected = creative.id === selectedCreative.id;
                                            const issues = rowIssues(creative);
                                            const copyReady = issues.length === 0;
                                            const displayHeadline = creative.headline || (!creative.source || creative.source !== 'drive' ? creativeData.headlines?.[0] || '' : '');
                                            return (
                                                <button ref={(element) => { copyRowRefs.current[creative.id] = element; }} key={`copy-row-${creative.id}`} type="button" onClick={() => setSelectedCopyCreativeId(creative.id)} className={`grid w-full grid-cols-[62px_minmax(0,1fr)] gap-3 border-b border-gray-100 px-4 py-3 text-left transition-colors md:grid-cols-[76px_minmax(0,1fr)_110px] ${selected ? 'bg-amber-50 shadow-[inset_3px_0_0_0_#d97706]' : 'hover:bg-gray-50'}`}>
                                                    <div className="flex h-14 w-[72px] gap-0.5 overflow-hidden rounded-md border border-gray-200 bg-gray-100 p-0.5">
                                                        {creative.previewUrl && <img src={creative.previewUrl} alt="Feed creative" className={creative.dualPlacement && creative.secondaryImageUrl ? 'w-1/2 object-contain' : 'w-full object-contain'} />}
                                                        {creative.dualPlacement && creative.secondaryImageUrl && <img src={creative.secondaryImageUrl} alt="Stories creative" className="w-1/2 object-contain" />}
                                                    </div>
                                                    <div className="min-w-0">
                                                        <div className="truncate text-sm font-semibold text-gray-900">Ad {index + 1} · {creative.name || 'Untitled creative'}</div>
                                                        <div className="mt-0.5 truncate text-xs text-gray-500">{creative.dualPlacement ? 'Feed + Stories pair' : (creative.format || 'feed') === 'stories' ? 'Stories & Reels' : 'Feed'} · {displayHeadline || 'No headline yet'}</div>
                                                    </div>
                                                    <div className="hidden text-right md:block"><span className={`inline-flex rounded-full px-2 py-1 text-[11px] font-semibold ${copyReady ? 'bg-emerald-100 text-emerald-700' : 'bg-amber-100 text-amber-800'}`}>{copyReady ? 'Ready' : `Needs ${issues[0]}`}</span></div>
                                                </button>
                                            );
                                        })}
                                    </div>
                                    <aside className="sticky top-4 overflow-hidden rounded-xl border border-gray-200 bg-white">
                                        <div className="border-b border-gray-200 px-4 py-3">
                                            <div className="flex items-start justify-between gap-3"><div className="min-w-0"><h4 className="truncate text-sm font-bold text-gray-900">Ad {selectedIndex + 1} · {selectedCreative.name || 'Untitled creative'}</h4><p className="mt-0.5 text-xs text-gray-500">{selectedCreative.dualPlacement ? 'Feed + Stories pair' : 'Single placement'}</p>{!selectedCopyReady && <p className="mt-1 text-xs font-medium text-amber-800">Needs: {selectedIssues.join(', ')}</p>}</div><span className={`shrink-0 rounded-full px-2 py-1 text-[10px] font-semibold ${selectedCopyReady ? 'bg-emerald-100 text-emerald-700' : 'bg-amber-100 text-amber-800'}`}>{selectedCopyReady ? 'Ready' : 'Needs attention'}</span></div>
                                        </div>
                                        <div className="max-h-[610px] space-y-3 overflow-y-auto p-4">
                                            <div className="flex h-52 gap-2 overflow-hidden rounded-lg bg-gray-100 p-2">
                                                {selectedCreative.previewUrl && <img src={selectedCreative.previewUrl} alt="Feed preview" className={selectedCreative.dualPlacement && selectedCreative.secondaryImageUrl ? 'w-1/2 object-contain' : 'w-full object-contain'} />}
                                                {selectedCreative.dualPlacement && selectedCreative.secondaryImageUrl && <img src={selectedCreative.secondaryImageUrl} alt="Stories preview" className="w-1/2 object-contain" />}
                                            </div>
                                            {!selectedIsDrive && (!selectedCreative.body || !selectedCreative.headline || !selectedCreative.description || !selectedCreative.cta || !selectedCreative.websiteUrl) && <p className="rounded-lg bg-blue-50 px-3 py-2 text-xs text-blue-800">Showing shared fallback values for this non-Drive row. Editing any field makes this row independent.</p>}
                                            {selectedCreative.driveCopyIntegrityIssue && <button type="button" onClick={() => { setSelectedDriveAssetIds(new Set()); setDriveSearchTerm(''); setDriveRepairPairId(selectedCreative.drivePairId || null); setDriveFormatFilter(''); setShowDriveLibraryModal(true); }} className="w-full rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-left text-xs font-semibold text-amber-900 hover:bg-amber-100">Open Drive to repair this pair</button>}
                                            <label className="block text-xs font-semibold text-gray-700">Primary text *<textarea rows="5" value={selectedBody} onChange={(event) => updateCreativeCopy(selectedCreative.id, 'body', event.target.value)} className={`mt-1 w-full rounded-lg border px-3 py-2 text-sm font-normal focus:border-amber-500 focus:ring-2 focus:ring-amber-100 ${selectedBody.length > BODY_LIMIT ? 'border-red-400' : 'border-gray-300'}`} /><span className={`mt-1 block text-right text-[11px] ${charCountClass(selectedBody.length, BODY_WARN, BODY_LIMIT)}`}>{selectedBody.length} / {BODY_LIMIT}</span></label>
                                            <label className="block text-xs font-semibold text-gray-700">Headline *<input value={selectedHeadline} onChange={(event) => updateCreativeCopy(selectedCreative.id, 'headline', event.target.value)} className={`mt-1 w-full rounded-lg border px-3 py-2 text-sm font-normal focus:border-amber-500 focus:ring-2 focus:ring-amber-100 ${selectedHeadline.length > HEADLINE_LIMIT ? 'border-red-400' : 'border-gray-300'}`} /><span className={`mt-1 block text-right text-[11px] ${charCountClass(selectedHeadline.length, HEADLINE_WARN, HEADLINE_LIMIT)}`}>{selectedHeadline.length} / {HEADLINE_LIMIT}</span></label>
                                            <label className="block text-xs font-semibold text-gray-700">Description <span className="font-normal text-gray-400">(optional)</span><input value={selectedDescription} onChange={(event) => updateCreativeCopy(selectedCreative.id, 'description', event.target.value)} className={`mt-1 w-full rounded-lg border px-3 py-2 text-sm font-normal focus:border-amber-500 focus:ring-2 focus:ring-amber-100 ${selectedDescription.length > DESC_LIMIT ? 'border-red-400' : 'border-gray-300'}`} /><span className={`mt-1 block text-right text-[11px] ${charCountClass(selectedDescription.length, DESC_LIMIT, DESC_LIMIT)}`}>{selectedDescription.length} / {DESC_LIMIT}</span></label>
                                            <label className="block text-xs font-semibold text-gray-700">Meta CTA *<select value={selectedCta} onChange={(event) => updateCreativeCopy(selectedCreative.id, 'cta', event.target.value)} className="mt-1 w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm font-normal focus:border-amber-500 focus:ring-2 focus:ring-amber-100"><option value="">Select a CTA...</option>{CTA_OPTIONS.map(option => <option key={option} value={option}>{option.replace(/_/g, ' ')}</option>)}</select></label>
                                            <label className="block text-xs font-semibold text-gray-700">Destination URL *<input type="url" value={selectedUrl} onChange={(event) => updateCreativeCopy(selectedCreative.id, 'websiteUrl', event.target.value)} className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm font-normal focus:border-amber-500 focus:ring-2 focus:ring-amber-100" /></label>
                                        </div>
                                    </aside>
                                </div>
                            </section>
                        );
                    })()}

                    {LEGACY_CREATIVE_EDITOR_ENABLED && !isMatchImport && creativeData.creatives?.length > 0 && (
                        <div className="mt-4 rounded-xl border border-indigo-200 bg-indigo-50/50 p-4">
                            <div className="flex items-start justify-between gap-3 mb-3">
                                <div>
                                    <h3 className="text-sm font-semibold text-gray-900">Ad pairs &amp; copy</h3>
                                    <p className="text-xs text-gray-600 mt-0.5">
                                        Copy is attached to each selected image pair. Edit it here before continuing.
                                    </p>
                                </div>
                                <span className="shrink-0 rounded-full bg-white border border-indigo-200 px-2 py-1 text-[11px] font-semibold text-indigo-700">
                                    {creativeData.creatives.length} ad{creativeData.creatives.length !== 1 ? 's' : ''}
                                </span>
                            </div>
                            <div className="grid grid-cols-1 xl:grid-cols-2 gap-3">
                                {creativeData.creatives.map((creative, index) => {
                                    const headline = creative.headline || '';
                                    const body = creative.body || '';
                                    // Meta link-ad descriptions are optional. This badge must use
                                    // the same required fields as the Next-step validator; otherwise
                                    // a fully populated Drive pair is misleadingly labelled "Needs
                                    // copy" solely because its strategy document omitted a description.
                                    // Coerce the editable values to strings here. A legacy Drive
                                    // record can hydrate a textarea with a string-like value while
                                    // still failing the helper's optional-chain check, which made a
                                    // visibly populated pair read "Needs copy" until the next step.
                                    const hasOwnCopy = Boolean(String(headline || '').trim() && String(body || '').trim()) || (
                                        creative.source !== 'drive'
                                        && hasCompleteCopy({
                                            headline: creativeData.headlines?.[0],
                                            primary_text: creativeData.bodies?.[0],
                                        })
                                    );
                                    const missingDriveCta = creative.source === 'drive' && !creative.cta?.trim();
                                    const missingDriveUrl = creative.source === 'drive' && !creative.websiteUrl?.trim();
                                    const missingDriveFields = [
                                        missingDriveCta && 'CTA',
                                        missingDriveUrl && 'URL',
                                    ].filter(Boolean);
                                    const invalidDriveCta = creative.source === 'drive'
                                        && creative.cta?.trim()
                                        && !CTA_OPTIONS.includes(creative.cta.trim());
                                    return (
                                        <div key={`copy-${creative.id}`} className="rounded-lg border border-gray-200 bg-white p-3 shadow-sm">
                                            <div className="flex gap-3">
                                                <div className="flex w-20 h-20 shrink-0 gap-1 overflow-hidden rounded-md bg-gray-100">
                                                    {creative.previewUrl && (
                                                        <div className={`relative h-full ${creative.dualPlacement && creative.secondaryImageUrl ? 'w-1/2' : 'w-full'}`}>
                                                            {creative.mediaType === 'video' ? (
                                                                <video src={creative.previewUrl} className="h-full w-full object-cover" muted playsInline />
                                                            ) : (
                                                                <img src={creative.previewUrl} alt={creative.name} className="h-full w-full object-cover" />
                                                            )}
                                                            {/* Badge is a sibling of the two placement images now, not
                                                                floating in the outer flex row — it was previously
                                                                `absolute` with no positioned ancestor of its own,
                                                                so it could render outside this 20x20 thumbnail
                                                                entirely instead of pinned to the Feed image. */}
                                                            {creative.dualPlacement && (
                                                                <span className="absolute bottom-1 left-1 rounded bg-blue-600 px-1 py-0.5 text-[9px] font-semibold text-white">Feed 1:1</span>
                                                            )}
                                                        </div>
                                                    )}
                                                    {creative.dualPlacement && creative.secondaryImageUrl && (
                                                        <div className="relative h-full w-1/2">
                                                            <img src={creative.secondaryImageUrl} alt={`${creative.name} Stories`} className="h-full w-full object-cover" />
                                                            <span className="absolute bottom-1 left-1 rounded bg-purple-600 px-1 py-0.5 text-[9px] font-semibold text-white">Stories 9:16</span>
                                                        </div>
                                                    )}
                                                </div>
                                                <div className="min-w-0 flex-1">
                                                    <div className="flex items-center gap-2">
                                                        <span className="text-xs font-semibold text-gray-900">Ad {index + 1}</span>
                                                        {creative.dualPlacement && <span className="rounded bg-purple-100 px-1.5 py-0.5 text-[10px] font-semibold text-purple-700">Feed + Stories</span>}
                                                        {creative.driveCopyIntegrityIssue ? (
                                                            <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-semibold text-amber-700">Pair data mismatch</span>
                                                        ) : invalidDriveCta ? (
                                                            <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-semibold text-amber-700">Unsupported CTA</span>
                                                        ) : missingDriveFields.length > 0 ? (
                                                            <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-semibold text-amber-700">Needs {missingDriveFields.join(' + ')}</span>
                                                        ) : hasOwnCopy ? (
                                                            <span className="rounded bg-emerald-100 px-1.5 py-0.5 text-[10px] font-semibold text-emerald-700">Copy matched</span>
                                                        ) : (
                                                            <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-semibold text-amber-700">Needs copy</span>
                                                        )}
                                                    </div>
                                                    <p className="truncate text-[11px] text-gray-500 mt-1" title={creative.name}>{creative.name}</p>
                                                    {(creative.driveCopyIntegrityIssue || invalidDriveCta || missingDriveFields.length > 0) && (
                                                        <button
                                                            type="button"
                                                            onClick={() => {
                                                                setSelectedDriveAssetIds(new Set());
                                                                setDriveSearchTerm('');
                                                                setDriveRepairPairId(creative.drivePairId || null);
                                                                setDriveFormatFilter('');
                                                                setShowDriveLibraryModal(true);
                                                            }}
                                                            className="mt-1 text-[11px] font-semibold text-indigo-700 hover:text-indigo-900"
                                                        >
                                                            {creative.driveCopyIntegrityIssue
                                                                ? 'Open Drive to repair this pair'
                                                                : invalidDriveCta
                                                                    ? `Open Drive to repair unsupported CTA: ${creative.cta}`
                                                                : `Edit the ${missingDriveFields.join(' + ')} below, or refresh from Drive`}
                                                        </button>
                                                    )}
                                                </div>
                                            </div>
                                            <label className="block text-[11px] font-semibold text-gray-600 mt-3 mb-1">Primary Text</label>
                                            <textarea
                                                value={body}
                                                onChange={(e) => updateCreativeCopy(creative.id, 'body', e.target.value)}
                                                rows={3}
                                                placeholder="Primary text for this ad..."
                                                className="w-full rounded-md border border-gray-300 px-2.5 py-2 text-xs focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500"
                                            />
                                            <div className="flex justify-end mt-1">
                                                <span className={`text-[10px] ${charCountClass(body.length, BODY_WARN, BODY_LIMIT)}`}>{body.length} / {BODY_LIMIT}</span>
                                            </div>
                                            <div className="flex items-center justify-between mt-1">
                                                <label className="text-[11px] font-semibold text-gray-600">Headline</label>
                                                <span className={`text-[10px] ${charCountClass(headline.length, HEADLINE_WARN, HEADLINE_LIMIT)}`}>{headline.length} / {HEADLINE_LIMIT}</span>
                                            </div>
                                            <input
                                                type="text"
                                                value={headline}
                                                onChange={(e) => updateCreativeCopy(creative.id, 'headline', e.target.value)}
                                                placeholder="Headline for this ad..."
                                                className="w-full rounded-md border border-gray-300 px-2.5 py-2 text-xs focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500"
                                            />
                                            <label className="block text-[11px] font-semibold text-gray-600 mt-2 mb-1">Description <span className="font-normal text-gray-400">(optional)</span></label>
                                            <input
                                                type="text"
                                                value={creative.description ?? ''}
                                                onChange={(e) => updateCreativeCopy(creative.id, 'description', e.target.value)}
                                                placeholder="Description for this ad..."
                                                className="w-full rounded-md border border-gray-300 px-2.5 py-2 text-xs focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500"
                                            />
                                            <label className="block text-[11px] font-semibold text-gray-600 mt-2 mb-1">Meta CTA *</label>
                                            <select
                                                value={creative.cta || ''}
                                                onChange={(e) => updateCreativeCopy(creative.id, 'cta', e.target.value)}
                                                className="w-full rounded-md border border-gray-300 bg-white px-2.5 py-2 text-xs focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500"
                                            >
                                                <option value="">Select a CTA...</option>
                                                {CTA_OPTIONS.map(option => <option key={option} value={option}>{option.replace(/_/g, ' ')}</option>)}
                                            </select>
                                            <label className="block text-[11px] font-semibold text-gray-600 mt-2 mb-1">Destination URL *</label>
                                            <input
                                                type="url"
                                                value={creative.websiteUrl ?? ''}
                                                onChange={(e) => updateCreativeCopy(creative.id, 'websiteUrl', e.target.value)}
                                                placeholder="https://example.com/landing-page"
                                                className="w-full rounded-md border border-gray-300 px-2.5 py-2 text-xs focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500"
                                            />
                                        </div>
                                    );
                                })}
                            </div>
                        </div>
                    )}

                {/* Meta creative enhancement opt-ins — default-off, and scoped to
                    this Creative-step session (applied identically to every ad
                    built from it), NOT independently settable per individual ad —
                    matches how Joel already thinks about a batch (one Creative
                    step = one set of choices applied across variations). Empty
                    state omits degrees_of_freedom_spec so the existing create
                    behavior remains unchanged. Cleared on a genuine campaign/
                    account switch by the scope-reset effect above, alongside
                    `creatives`. */}
                {!isMatchImport && (
                <CreativeEnhancementsPanel
                    value={creativeEnhancements}
                    onChange={handleCreativeEnhancementsChange}
                    className="mt-4"
                />
                )}

                {/* URL Input (Optional fallback) */}
                    <div className="mt-2">
                        <p className="text-sm text-gray-500 mb-1">Or paste a media URL (image or video):</p>
                        <input
                            type="text"
                            placeholder="https://example.com/image.jpg or https://example.com/video.mp4"
                            className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-amber-500 focus:border-transparent text-sm"
                            onBlur={(e) => {
                                if (e.target.value) {
                                    const url = e.target.value.toLowerCase();
                                    const isVideo = url.endsWith('.mp4') || url.endsWith('.mov') || url.endsWith('.webm') || url.endsWith('.avi');
                                    const newCreative = {
                                        id: `creative_url_${Date.now()}`,
                                        previewUrl: e.target.value,
                                        imageUrl: isVideo ? undefined : e.target.value,
                                        videoUrl: isVideo ? e.target.value : undefined,
                                        name: isVideo ? 'Video from URL' : 'Image from URL',
                                        mediaType: isVideo ? 'video' : 'image',
                                        format: 'feed'
                                    };
                                    setCreativeData(prev => ({
                                        ...prev,
                                        creatives: [...(prev.creatives || []), newCreative]
                                    }));
                                    e.target.value = ''; // Clear input
                                }
                            }}
                        />
                    </div>
                </div>
                )}

                {/* Body Text */}
                {!isMatchImport && (
                <details className="rounded-lg border border-gray-200 bg-gray-50/70 p-3" open={!creativeData.creatives?.some(c => c.source === 'drive' || c.headline || c.body)}>
                    <summary className="cursor-pointer text-sm font-semibold text-gray-700">Shared fallback Primary Text <span className="font-normal text-gray-400">(rarely needed)</span></summary>
                    <p className="mt-1 text-xs text-gray-500">Used only for non-Drive creatives that do not have per-ad copy.</p>
                    <div className="flex items-center justify-between mb-2">
                        <label className="block text-sm font-medium text-gray-700">
                            {creativeData.creatives?.some(c => c.source === 'drive' || c.headline || c.body) ? 'Shared fallback Primary Text' : 'Primary Text *'}
                        </label>
                        {creativeData.bodies.length < 3 && (
                            <button
                                type="button"
                                onClick={addBodyField}
                                className="text-sm text-amber-600 hover:text-amber-700 font-medium flex items-center gap-1"
                            >
                                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                                </svg>
                                Add Body Copy
                            </button>
                        )}
                    </div>
                    <div className="space-y-3">
                        {creativeData.bodies.map((body, index) => (
                            <div key={index} className="relative">
                                <textarea
                                    value={body}
                                    onChange={(e) => handleBodyChange(index, e.target.value)}
                                    placeholder={`Body copy ${index + 1}...`}
                                    rows="3"
                                    className={`w-full px-4 py-2 border rounded-lg focus:ring-2 focus:ring-amber-500 focus:border-transparent ${body && body.length > BODY_LIMIT ? 'border-red-400' : body && body.length > BODY_WARN ? 'border-amber-400' : 'border-gray-300'}`}
                                />
                                <div className="flex justify-between items-center mt-0.5">
                                    <span className="text-xs text-gray-400">
                                        {body && body.length > BODY_WARN ? `Truncated in feed after ${BODY_WARN} chars` : ''}
                                    </span>
                                    <span className={`text-xs ${charCountClass(body ? body.length : 0, BODY_WARN, BODY_LIMIT)}`}>
                                        {body ? body.length : 0} / {BODY_LIMIT}
                                    </span>
                                </div>
                                {index >= 1 && (
                                    <button
                                        type="button"
                                        onClick={() => removeBodyField(index)}
                                        className="absolute top-2 right-2 text-red-500 hover:text-red-700"
                                        title="Remove this body copy"
                                    >
                                        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                                        </svg>
                                    </button>
                                )}
                            </div>
                        ))}
                    </div>
                </details>
                )}

                {/* Headline */}
                {!isMatchImport && (
                <details className="rounded-lg border border-gray-200 bg-gray-50/70 p-3" open={!creativeData.creatives?.some(c => c.source === 'drive' || c.headline || c.body)}>
                    <summary className="cursor-pointer text-sm font-semibold text-gray-700">Shared fallback Headline <span className="font-normal text-gray-400">(rarely needed)</span></summary>
                    <p className="mt-1 text-xs text-gray-500">Used only for non-Drive creatives that do not have per-ad copy.</p>
                    <div className="flex items-center justify-between mb-2">
                        <label className="block text-sm font-medium text-gray-700">
                            {creativeData.creatives?.some(c => c.source === 'drive' || c.headline || c.body) ? 'Shared fallback Headline' : 'Headline *'}
                        </label>
                        {creativeData.headlines.length < 3 && (
                            <button
                                type="button"
                                onClick={addHeadlineField}
                                className="text-sm text-amber-600 hover:text-amber-700 font-medium flex items-center gap-1"
                            >
                                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                                </svg>
                                Add Headline
                            </button>
                        )}
                    </div>
                    <div className="space-y-3">
                        {creativeData.headlines.map((headline, index) => (
                            <div key={index} className="relative">
                                <input
                                    type="text"
                                    value={headline}
                                    onChange={(e) => handleHeadlineChange(index, e.target.value)}
                                    placeholder={`Headline ${index + 1}...`}
                                    className={`w-full px-4 py-2 border rounded-lg focus:ring-2 focus:ring-amber-500 focus:border-transparent ${headline && headline.length > HEADLINE_LIMIT ? 'border-red-400' : headline && headline.length > HEADLINE_WARN ? 'border-amber-400' : 'border-gray-300'}`}
                                />
                                <div className="flex justify-between items-center mt-0.5">
                                    <span className="text-xs text-gray-400">
                                        {headline && headline.length > HEADLINE_WARN ? `May be truncated in feed` : ''}
                                    </span>
                                    <span className={`text-xs ${charCountClass(headline ? headline.length : 0, HEADLINE_WARN, HEADLINE_LIMIT)}`}>
                                        {headline ? headline.length : 0} / {HEADLINE_LIMIT}
                                    </span>
                                </div>
                                {index >= 1 && (
                                    <button
                                        type="button"
                                        onClick={() => removeHeadlineField(index)}
                                        className="absolute top-2 right-2 text-red-500 hover:text-red-700"
                                        title="Remove this headline"
                                    >
                                        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                                        </svg>
                                    </button>
                                )}
                            </div>
                        ))}
                    </div>
                </details>
                )}

                {/* Description */}
                {!isMatchImport && (
                <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">
                        Description
                    </label>
                    <input
                        type="text"
                        value={creativeData.description}
                        onChange={(e) => handleInputChange('description', e.target.value)}
                        placeholder="Shop now and save!"
                        className={`w-full px-4 py-2 border rounded-lg focus:ring-2 focus:ring-amber-500 focus:border-transparent ${creativeData.description && creativeData.description.length > DESC_LIMIT ? 'border-red-400' : 'border-gray-300'}`}
                    />
                    <div className="flex justify-end mt-0.5">
                        <span className={`text-xs ${creativeData.description && creativeData.description.length > DESC_LIMIT ? 'text-red-600 font-semibold' : 'text-gray-400'}`}>
                            {creativeData.description ? creativeData.description.length : 0} / {DESC_LIMIT}
                        </span>
                    </div>
                </div>
                )}

                {/* Ad Permutation Counter */}
                {!isMatchImport && creativeData.creatives && creativeData.creatives.length > 0 && (
                    <div className="bg-amber-50 border border-amber-200 rounded-lg p-4">
                        <div className="flex items-center gap-2 text-amber-800">
                            <svg className="w-5 h-5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                            </svg>
                            <span className="font-medium">
                                {(() => {
                                    const validHeadlines = creativeData.headlines.filter(h => h && h.trim() !== '').length;
                                    const validBodies = creativeData.bodies.filter(b => b && b.trim() !== '').length;
                                    const totalAds = variationCount.total;
                                    const imageCount = creativeData.creatives.filter(c => c.mediaType !== 'video').length;
                                    const videoCount = creativeData.creatives.filter(c => c.mediaType === 'video').length;
                                    const mediaDesc = [];
                                    if (imageCount > 0) mediaDesc.push(`${imageCount} image${imageCount !== 1 ? 's' : ''}`);
                                    if (videoCount > 0) mediaDesc.push(`${videoCount} video${videoCount !== 1 ? 's' : ''}`);
                                    return (
                                        <>
                                            {totalAds} ad{totalAds !== 1 ? 's' : ''} will be created
                                            <span className="text-sm font-normal ml-2">
                                                ({variationCount.hasPerCreativeCopy ? 'per-ad copy' : `${mediaDesc.join(' + ')} × ${validHeadlines} headline${validHeadlines !== 1 ? 's' : ''} × ${validBodies} bod${validBodies !== 1 ? 'ies' : 'y'}`})
                                            </span>
                                        </>
                                    );
                                })()}
                            </span>
                        </div>
                        {(() => {
                            const hasStories = creativeData.creatives.some(c => c.format === 'stories');
                            const hasFeed = creativeData.creatives.some(c => (c.format || 'feed') !== 'stories');
                            if (hasStories && hasFeed) {
                                const feedCount = creativeData.creatives.filter(c => (c.format || 'feed') !== 'stories').length;
                                const storiesCount = creativeData.creatives.filter(c => c.format === 'stories').length;
                                return (
                                    <div className="mt-2 pt-2 border-t border-amber-200 flex items-start gap-1.5 text-sm text-amber-800">
                                        <Layers size={15} className="flex-shrink-0 mt-0.5" />
                                        <span>
                                            <strong>2 ad sets will be created automatically</strong>
                                            {' '}— {feedCount} Feed image{feedCount !== 1 ? 's' : ''} (1:1) + {storiesCount} Stories & Reels image{storiesCount !== 1 ? 's' : ''} (9:16)
                                        </span>
                                    </div>
                                );
                            }
                            return null;
                        })()}
                    </div>
                )}

                {/* Call to Action — Match Import gets CTA per-row from the CSV (defaults to LEARN_MORE) */}
                {!isMatchImport && (
                <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">
                        {creativeData.creatives?.some(c => c.source === 'drive' || c.cta) ? 'Shared fallback Call to Action' : 'Call to Action *'}
                    </label>
                    <select
                        value={creativeData.cta}
                        onChange={(e) => handleInputChange('cta', e.target.value)}
                        className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-amber-500 focus:border-transparent"
                    >
                        {CTA_OPTIONS.map(cta => (
                            <option key={cta} value={cta}>{cta.replace(/_/g, ' ')}</option>
                        ))}
                    </select>
                    {creativeData.creatives?.some(c => c.source === 'drive' || c.cta) && <p className="mt-1 text-xs text-gray-500">Applies only to non-Drive rows without their own CTA.</p>}
                </div>
                )}

                {/* Website URL */}
                <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">
                        {creativeData.creatives?.some(c => c.source === 'drive' || c.websiteUrl) ? 'Shared fallback Website URL' : 'Website URL (Landing Page) *'}
                    </label>
                    <input
                        type="url"
                        value={creativeData.websiteUrl}
                        onChange={(e) => handleInputChange('websiteUrl', e.target.value)}
                        placeholder="https://yourwebsite.com/landing"
                        className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-amber-500 focus:border-transparent"
                    />
                    {creativeData.creatives?.some(c => c.source === 'drive' || c.websiteUrl) && <p className="mt-1 text-xs text-gray-500">Applies only to non-Drive rows without their own destination URL.</p>}
                </div>

                {isMatchImport && (
                    <p className="text-sm text-gray-500 -mt-2">
                        Headlines, body copy, images, and CTA come from your CSV + image folder in the next step.
                    </p>
                )}
            </div>

            {/* Navigation — sticky to the viewport bottom, same reasoning as
                BulkAdCreation's nav bar: this step's form is long, and "Next Step"
                shouldn't require scrolling all the way down to find, especially on
                mobile. -mx-6/px-6 cancels the parent workspace card's own p-6. */}
            <div className="mt-10 flex justify-between items-center sticky bottom-0 -mx-6 bg-white border-t border-gray-200 px-6 py-4 shadow-[0_-4px_12px_-4px_rgba(0,0,0,0.08)]">
                <button
                    onClick={onBack}
                    className="px-6 py-3 text-gray-600 hover:text-gray-800 font-medium"
                >
                    Back
                </button>
                <button
                    onClick={handleNext}
                    className="flex items-center gap-2 px-6 py-3 bg-amber-600 text-white rounded-lg font-medium hover:bg-amber-700"
                >
                    Next Step <ChevronRight size={20} />
                </button>
            </div>
        </div>

        {/* Generated Ads Library Modal */}
        {showLibraryModal && (
            <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
                <div className="bg-white rounded-xl shadow-xl w-full max-w-3xl max-h-[80vh] flex flex-col">
                    <div className="flex items-center justify-between p-4 border-b">
                        <h3 className="text-lg font-semibold">Select from Generated Ads Library</h3>
                        <button onClick={() => setShowLibraryModal(false)} className="text-gray-500 hover:text-gray-700">
                            <X size={20} />
                        </button>
                    </div>
                    <div className="flex-1 overflow-y-auto p-4">
                        {libraryLoading ? (
                            <div className="flex items-center justify-center py-12 gap-2 text-gray-500">
                                <Loader className="animate-spin" size={20} />
                                <span>Loading library...</span>
                            </div>
                        ) : libraryAds.length === 0 ? (
                            <p className="text-center text-gray-500 py-12">No generated ads found. Create some in the Generated Ads section first.</p>
                        ) : (
                            <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
                                {libraryAds.map(ad => {
                                    const isSelected = selectedLibraryIds.has(ad.id);
                                    return (
                                        <div
                                            key={ad.id}
                                            onClick={() => toggleLibrarySelection(ad.id)}
                                            className={`relative cursor-pointer rounded-lg overflow-hidden border-2 transition-all ${isSelected ? 'border-amber-500 ring-2 ring-amber-200' : 'border-gray-200 hover:border-amber-300'}`}
                                        >
                                            <img src={ad.image_url} alt={ad.headline || 'Ad'} className="w-full aspect-square object-cover" />
                                            {isSelected && (
                                                <div className="absolute top-2 right-2 bg-amber-500 rounded-full p-0.5">
                                                    <Check size={14} className="text-white" />
                                                </div>
                                            )}
                                            {ad.headline && (
                                                <div className="p-2 text-xs text-gray-600 truncate bg-white">{ad.headline}</div>
                                            )}
                                        </div>
                                    );
                                })}
                            </div>
                        )}
                    </div>
                    <div className="p-4 border-t flex items-center justify-between">
                        <span className="text-sm text-gray-500">{selectedLibraryIds.size} selected</span>
                        <div className="flex gap-3">
                            <button onClick={() => setShowLibraryModal(false)} className="px-4 py-2 text-gray-600 hover:text-gray-800 font-medium">
                                Cancel
                            </button>
                            <button
                                onClick={addLibrarySelectionToCreatives}
                                disabled={selectedLibraryIds.size === 0}
                                className="px-4 py-2 bg-amber-600 text-white rounded-lg font-medium hover:bg-amber-700 disabled:bg-gray-300 disabled:cursor-not-allowed"
                            >
                                Add {selectedLibraryIds.size > 0 ? selectedLibraryIds.size : ''} to Campaign
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        )}

        {/* Drive Creative Library Modal */}
        {showDriveLibraryModal && (
            <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-2">
                <div className="bg-white rounded-xl shadow-xl w-full max-w-7xl h-[calc(100dvh-1rem)] flex flex-col">
                    <div className="flex items-center justify-between p-2 border-b">
                        <h3 className="text-lg font-semibold">Select from Drive Creative Library</h3>
                        <div className="flex items-center gap-2">
                            <button
                                type="button"
                                onClick={refreshDriveCopyMatches}
                                disabled={refreshingDriveCopy || driveLibraryLoading}
                                className="rounded-lg border border-indigo-200 bg-indigo-50 px-2.5 py-1 text-xs font-semibold text-indigo-700 hover:bg-indigo-100 disabled:cursor-not-allowed disabled:opacity-60"
                            >
                                {refreshingDriveCopy ? 'Refreshing…' : 'Refresh copy'}
                            </button>
                            <button onClick={() => setShowDriveLibraryModal(false)} className="text-gray-500 hover:text-gray-700" aria-label="Close Drive creative library">
                                <X size={20} />
                            </button>
                        </div>
                    </div>
                    <div className="flex flex-col gap-2 border-b p-2 lg:flex-row lg:items-center">
                        <label className="relative block lg:flex-1 lg:min-w-0">
                            <Search className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" size={16} />
                            <input
                                value={driveSearchTerm}
                                onChange={(e) => setDriveSearchTerm(e.target.value)}
                                placeholder="Search filenames, folders, or brands"
                                className="w-full rounded-lg border border-gray-300 bg-white py-1 pl-9 pr-3 text-sm focus:border-amber-500 focus:ring-2 focus:ring-amber-100"
                            />
                        </label>
                        <div className="flex flex-wrap items-center gap-2 lg:flex-nowrap lg:shrink-0">
                            <div className="inline-flex overflow-hidden rounded-lg border border-gray-300 bg-white">
                                {[
                                    { value: '', label: `All ${driveCounts.total}` },
                                    { value: 'image', label: `Images ${driveCounts.image || 0}` },
                                    { value: 'video', label: `Videos ${driveCounts.video || 0}` },
                                ].map(option => (
                                    <button
                                        key={option.value || 'all'}
                                        type="button"
                                        onClick={() => setDriveFormatFilter(option.value)}
                                        className={`px-3 py-1 text-xs font-semibold transition-colors ${
                                            driveFormatFilter === option.value
                                                ? 'bg-gray-900 text-white'
                                                : 'text-gray-600 hover:bg-gray-50'
                                        }`}
                                    >
                                        {option.label}
                                    </button>
                                ))}
                            </div>
                            <button
                                type="button"
                                onClick={selectAllVisibleDriveAssets}
                                disabled={driveAssetGroups.length === 0}
                                className="px-3 py-1 text-xs font-semibold rounded-lg border border-gray-300 text-gray-700 hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed"
                            >
                                Select all {driveAssetGroups.length > 0 ? `(${driveAssetGroups.length})` : ''}
                            </button>
                            <button
                                type="button"
                                onClick={clearDriveAssetSelection}
                                disabled={selectedDriveAssetIds.size === 0}
                                className="px-3 py-1 text-xs font-semibold rounded-lg border border-gray-300 text-gray-700 hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed"
                            >
                                Clear selection
                            </button>
                            <div className="flex flex-col gap-0.5">
                                <div className="flex items-center gap-1.5">
                                    <span className="text-xs text-gray-500">Select first</span>
                                    <input
                                        type="number"
                                        min="1"
                                        value={driveSelectCount}
                                        onChange={(e) => setDriveSelectCount(e.target.value)}
                                        placeholder="e.g. 50"
                                        className="w-16 rounded-lg border border-gray-300 py-1 px-2 text-xs focus:border-amber-500 focus:ring-2 focus:ring-amber-100"
                                    />
                                    <span className="text-xs text-gray-500">matching assets</span>
                                    <button
                                        type="button"
                                        onClick={selectFirstNDriveAssets}
                                        disabled={!driveSelectCount || driveAssetGroups.length === 0}
                                        className="px-3 py-1 text-xs font-semibold rounded-lg border border-gray-300 text-gray-700 hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed"
                                    >
                                        Go
                                    </button>
                                </div>
                                {/* Shows exactly what "Go" will select before Joel commits — the
                                    scope (newest-first, filtered to eligible/matching assets only)
                                    and the exact resulting range, so "first N" is never a black box. */}
                                {driveSelectCount && driveAssetGroups.length > 0 && (() => {
                                    const n = parseInt(driveSelectCount, 10);
                                    if (!Number.isFinite(n) || n <= 0) return null;
                                    const eligible = driveAssetGroups.filter(group => !isDriveGroupSelectionBlocked(group));
                                    const willSelect = eligible.slice(0, n);
                                    return (
                                        <span className="text-[11px] text-gray-500">
                                            Will select the {willSelect.length} newest of {driveAssetGroups.length} matching asset{driveAssetGroups.length !== 1 ? 's' : ''}
                                            {eligible.length !== driveAssetGroups.length ? ` (${driveAssetGroups.length - eligible.length} blocked, skipped)` : ''}.
                                        </span>
                                    );
                                })()}
                            </div>
                        </div>
                    </div>
                    <div className="flex-1 min-h-0 overflow-y-auto p-2">
                        {driveLibraryLoading ? (
                            <div className="flex items-center justify-center py-12 gap-2 text-gray-500">
                                <Loader className="animate-spin" size={20} />
                                <span>Loading Drive library...</span>
                            </div>
                        ) : driveLibraryError ? (
                            <div className="flex flex-col items-center gap-3 py-12 text-center">
                                <p className="text-red-600">{driveLibraryError}</p>
                                <button
                                    type="button"
                                    onClick={() => fetchDriveAssets()}
                                    className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-1.5 text-sm font-semibold text-amber-800 hover:bg-amber-100"
                                >
                                    Retry loading Drive library
                                </button>
                            </div>
                        ) : driveAssets.length === 0 ? (
                            <p className="text-center text-gray-500 py-12">No synced Drive creative yet. It appears here once the Drive sync job (or a manual sync) has run.</p>
                        ) : driveAssetGroups.length === 0 ? (
                            <p className="text-center text-gray-500 py-12">No Drive assets match that search.</p>
                        ) : (
                            <>
                            {mixedDriveCopyMatches && (
                                <div className="mb-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
                                    {mixedDriveCopyMatches.matchedPairs} pair{mixedDriveCopyMatches.matchedPairs !== 1 ? 's' : ''} matched copy from a strategy doc; {mixedDriveCopyMatches.unmatchedPairs} pair{mixedDriveCopyMatches.unmatchedPairs !== 1 ? 's' : ''} did not. Check the source files, then use Refresh copy from Drive.
                                </div>
                            )}
                            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-2">
                                {driveAssetGroups.map(group => {
                                    const asset = group.displayAsset;
                                    const isSelected = selectedDriveAssetIds.has(group.id);
                                    const tags = parseDriveTags(asset);
                                    const copyMatched = hasCompleteCopy(group.copy || {});
                                    const selectionBlocked = isDriveGroupSelectionBlocked(group);
                                    // "Needs repair" (an unverified copy source — a Drive-side fix, not a
                                    // pairing problem) gets its own amber border so it reads as a
                                    // different kind of blocked than an ambiguous/mismatched pairing —
                                    // Joel shouldn't have to read the badge text to tell them apart.
                                    // Mirrors the existing badge-text priority below exactly: ambiguous
                                    // pairing always reads as mismatched/red; otherwise copyRefreshUnverified
                                    // decides "needs repair" vs "mismatch," regardless of copyIntegrityIssue
                                    // (for a pair, an unverified refresh ALSO sets copyIntegrityIssue, so
                                    // excluding that case here would make amber almost never fire).
                                    const needsRepair = selectionBlocked && !group.copyPairingAmbiguous && group.copyRefreshUnverified;
                                    // Suppressed while selected — a card that's both currently chosen and
                                    // already in a prior batch doesn't need a second badge competing with
                                    // the selected ring for attention.
                                    const alreadyAdded = !selectionBlocked && !isSelected && isDriveGroupAlreadyAdded(group);
                                    const borderClass = selectionBlocked
                                        ? (needsRepair ? 'border-amber-400' : 'border-red-300')
                                        : isSelected
                                            ? 'border-amber-500 ring-2 ring-amber-200'
                                            : alreadyAdded
                                                ? 'border-blue-300'
                                                : 'border-gray-200 hover:border-amber-300';
                                    return (
                                        <div
                                            key={group.id}
                                            onClick={() => toggleDriveAssetSelection(group.id)}
                                            aria-disabled={selectionBlocked}
                                            title={selectionBlocked ? (needsRepair ? 'The Drive copy source needs repair. Refresh after fixing it before launch.' : 'Multiple or incomplete placements use this ad number. Resolve them in Drive before launch.') : undefined}
                                            className={`relative rounded-xl overflow-hidden border-2 bg-white transition-all ${selectionBlocked ? 'cursor-not-allowed opacity-70' : 'cursor-pointer'} ${borderClass}`}
                                        >
                                            <div className={`flex h-[96px] gap-1.5 bg-gray-100 p-1 ${group.isPair && group.storiesAsset ? 'items-stretch' : 'items-center justify-center'}`}>
                                                <div className={`relative ${group.isPair && group.storiesAsset ? 'w-1/2 min-w-0' : 'h-full w-full'}`}>
                                                {asset.format === 'video' ? (
                                                    <video src={asset.r2_key} className="h-full w-full object-contain" muted />
                                                ) : (
                                                    <img src={asset.r2_key} alt={asset.file_name} className="h-full w-full object-contain" />
                                                )}
                                                </div>
                                                {group.isPair && <span className="absolute left-1 top-1 rounded bg-black/70 px-1.5 py-0.5 text-[10px] font-semibold text-white">Feed</span>}
                                                {group.isPair && group.storiesAsset && <div className="relative w-1/2 min-w-0">
                                                    {group.storiesAsset.format === 'video' ? (
                                                        <video src={group.storiesAsset.r2_key} className="h-full w-full object-contain" muted />
                                                    ) : (
                                                        <img src={group.storiesAsset.r2_key} alt={group.storiesAsset.file_name} className="h-full w-full object-contain" />
                                                    )}
                                                    <span className="absolute left-1 top-1 rounded bg-black/70 px-1.5 py-0.5 text-[10px] font-semibold text-white">Stories</span>
                                                </div>}
                                            </div>
                                            {alreadyAdded && (
                                                <div className="absolute left-2 top-2 bg-blue-600 text-white text-[10px] font-semibold px-1.5 py-0.5 rounded-full shadow-sm">
                                                    Already added
                                                </div>
                                            )}
                                            <button
                                                type="button"
                                                onClick={(event) => { event.stopPropagation(); drivePreviewTriggerRef.current = event.currentTarget; setDrivePreviewGroup(group); }}
                                                className="absolute right-2 top-2 rounded-md bg-white/95 p-1 text-gray-700 shadow-sm hover:bg-white"
                                                aria-label={`Preview ${asset.file_name}`}
                                                title="Preview full creative"
                                            >
                                                <Maximize2 size={14} />
                                            </button>
                                            {isSelected && (
                                                <div className="absolute top-9 right-2 bg-amber-500 rounded-full p-0.5">
                                                    <Check size={14} className="text-white" />
                                                </div>
                                            )}
                                            {group.copyPairingAmbiguous ? (
                                                <div className="absolute bottom-10 left-2 bg-red-600 text-white text-[11px] font-semibold px-2 py-1 rounded-full shadow-sm">
                                                    {group.category || 'AD'} needs 1 Feed + 1 Stories source
                                                </div>
                                            ) : group.copyIntegrityIssue || group.copyRefreshUnverified ? (
                                                <div className="absolute bottom-10 left-2 bg-red-600 text-white text-[11px] font-semibold px-2 py-1 rounded-full shadow-sm">
                                                    {group.copyRefreshUnverified ? 'Drive source needs repair — refresh Drive' : 'Pair data mismatch — refresh Drive'}
                                                </div>
                                            ) : (copyMatched || group.landingPage || group.cta || tags.copy_id) && (
                                                <div className="absolute bottom-10 left-2 bg-emerald-600 text-white text-[11px] font-semibold px-2 py-1 rounded-full shadow-sm">
                                                    {copyMatched ? 'Copy matched' : 'URL matched'}
                                                </div>
                                            )}
                                            <div className="p-1 text-xs text-gray-600 bg-white" title={group.isPair ? `Feed: ${group.feedAsset?.file_name} · Stories: ${group.storiesAsset?.file_name}` : asset.file_name}>
                                                <div className="truncate font-medium">{copyMatched ? group.copy.headline : asset.file_name}</div>
                                                <div className="truncate text-gray-400">{asset.brand_name || asset.folder_path || 'Uncategorized asset'}</div>
                                            </div>
                                        </div>
                                    );
                                })}
                            </div>
                            </>
                        )}
                    </div>
                    <div className="h-[68px] p-3 border-t flex items-center justify-between gap-3">
                        <div className="min-w-0 text-sm text-gray-600" aria-live="polite">
                            <span className="font-medium">{selectedDriveAssetIds.size} selected</span>
                            {selectedDriveAssetIds.size > 0 ? (
                                <>
                                    <span> · {driveSelectionAssetCount} source asset{driveSelectionAssetCount !== 1 ? 's' : ''}</span>
                                    <span className="font-semibold text-gray-900"> · {driveSelectionProjectedAdCount} creative{driveSelectionProjectedAdCount !== 1 ? 's' : ''} will be added</span>
                                    <span className="block text-[11px] text-gray-500">→ {variationCount.total + driveSelectionProjectedAdCount} ads total after adding{autoDupeStories ? ' · unpaired images may add both Feed and Stories versions' : ''}</span>
                                </>
                            ) : (
                                <span className="text-gray-400"> · Select assets to add</span>
                            )}
                        </div>
                        <div className="flex shrink-0 gap-3">
                            <button onClick={() => setShowDriveLibraryModal(false)} className="px-4 py-2 text-gray-600 hover:text-gray-800 font-medium">
                                Cancel
                            </button>
                            <button
                                onClick={addDriveSelectionToCreatives}
                                disabled={selectedDriveAssetIds.size === 0}
                                className="px-4 py-2 bg-amber-600 text-white rounded-lg font-medium hover:bg-amber-700 disabled:bg-gray-300 disabled:cursor-not-allowed"
                            >
                                Add {driveSelectionProjectedAdCount > 0 ? driveSelectionProjectedAdCount : ''} Creative{driveSelectionProjectedAdCount !== 1 ? 's' : ''}
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        )}
        {drivePreviewGroup && (
            <div className="fixed inset-0 z-[60] overflow-y-auto overscroll-contain bg-black/70 p-2 sm:p-4" onClick={closeDrivePreview}>
                <div
                    ref={drivePreviewDialogRef}
                    role="dialog"
                    aria-modal="true"
                    aria-label="Creative preview"
                    tabIndex={-1}
                    className="my-auto w-full max-w-5xl overflow-y-auto overscroll-contain rounded-xl bg-white p-4 shadow-2xl"
                    style={{ maxHeight: 'calc(100dvh - 1rem)' }}
                    onClick={(event) => event.stopPropagation()}
                >
                    <div className="mb-3 flex items-center justify-between gap-3">
                        <div>
                            <h4 className="font-semibold text-gray-900">Creative preview</h4>
                            <p className="text-xs text-gray-500">Preview only — use the card itself to select this creative.</p>
                        </div>
                        <button type="button" onClick={closeDrivePreview} className="text-gray-500 hover:text-gray-700" aria-label="Close creative preview">
                            <X size={20} />
                        </button>
                    </div>
                    <div className={`grid gap-4 ${drivePreviewGroup.isPair && drivePreviewGroup.storiesAsset ? 'md:grid-cols-2' : 'grid-cols-1'}`}>
                        {[
                            { label: drivePreviewGroup.isPair ? 'Feed (1:1)' : 'Creative', asset: drivePreviewGroup.displayAsset },
                            ...(drivePreviewGroup.isPair && drivePreviewGroup.storiesAsset ? [{ label: 'Stories (9:16)', asset: drivePreviewGroup.storiesAsset }] : []),
                        ].map(({ label, asset: previewAsset }) => (
                            <div key={`${label}-${previewAsset.id}`} className="rounded-lg border border-gray-200 bg-gray-50 p-3">
                                <div className="mb-2 text-sm font-semibold text-gray-800">{label}</div>
                                <div className="flex h-[40vh] items-center justify-center rounded bg-white p-2 md:h-[58vh]">
                                    {previewAsset.format === 'video' ? (
                                        <video src={previewAsset.r2_key} className="h-full w-full object-contain" controls />
                                    ) : (
                                        <img src={previewAsset.r2_key} alt={previewAsset.file_name} className="h-full w-full object-contain" />
                                    )}
                                </div>
                                <p className="mt-2 truncate text-xs text-gray-500" title={previewAsset.file_name}>{previewAsset.file_name}</p>
                            </div>
                        ))}
                    </div>
                </div>
            </div>
        )}
        </>
    );
};

export default AdCreativeStep;
