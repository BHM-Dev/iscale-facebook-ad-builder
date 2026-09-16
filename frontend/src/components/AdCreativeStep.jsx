import { useToast } from '../context/ToastContext';
import { useAuth } from '../context/AuthContext';
import React, { useState, useEffect, useMemo, useRef } from 'react';
import { ChevronRight, Upload, X, Loader, Trash2, Copy, Film, Image, BookOpen, Check, Layers, FolderOpen, Search } from 'lucide-react';
import { useCampaign } from '../context/CampaignContext';
import { getPages } from '../lib/facebookApi';
import { safeLocalStorageGet, safeLocalStorageSet } from '../lib/safeLocalStorage';
import { cropImageToAspect } from '../lib/imageCrop';
import { useBrands } from '../context/BrandContext';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1';

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

const CREATIVE_ENHANCEMENT_OPTIONS = [
    { key: 'advantage_plus_creative', label: 'Advantage+ Creative', description: 'Allow Meta to apply its available creative optimizations.' },
    { key: 'enhance_cta', label: 'CTA Enhancement', description: 'Allow Meta to optimize the call-to-action presentation.' },
    { key: 'image_animation', label: 'Image Animation', description: 'Allow Meta to animate eligible image creatives.' },
    { key: 'image_brightness_and_contrast', label: 'Brightness & Contrast', description: 'Allow Meta to adjust image brightness and contrast.' },
    { key: 'image_templates', label: 'Image Templates', description: 'Allow Meta to apply eligible image template treatments.' },
    { key: 'image_touchups', label: 'Image Touchups', description: 'Allow Meta to apply eligible image touchups.' },
    { key: 'image_uncrop', label: 'Image Uncrop', description: 'Allow Meta to expand an image for placement fit.' },
    { key: 'site_extensions', label: 'Site Extensions', description: 'Allow eligible site extension treatments.' },
    { key: 'standard_enhancements', label: 'Standard Enhancements', description: 'Opt into Meta’s standard enhancement bundle.' },
    { key: 'text_generation', label: 'Text Generation', description: 'Allow Meta to generate eligible text variations.' },
    { key: 'text_optimizations', label: 'Text Optimizations', description: 'Allow Meta to optimize eligible text variations.' },
];

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

const driveAssetPlacement = (asset) => {
    const tags = parseDriveTags(asset);
    if (tags.aspect === '9x16') return 'stories';
    if (tags.aspect === '1x1') return 'feed';
    const parsed = normalizeFilenameBase(asset.file_name || '');
    return parsed?.aspect === '9x16' ? 'stories' : 'feed';
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
            sortClusterKey,
        };
        existing.assets.push(asset);
        existing.copy = existing.copy || tags.copy || null;
        existing.landingPage = existing.landingPage || tags.landing_page || null;
        existing.cta = existing.cta || tags.cta || null;
        grouped.set(key, existing);
    });

    const latestSyncedAt = (group) => group.assets.reduce((max, asset) => {
        const t = asset.synced_at ? new Date(asset.synced_at).getTime() : 0;
        return Number.isFinite(t) && t > max ? t : max;
    }, 0);

    const groups = Array.from(grouped.values()).map(group => {
        const feedAsset = group.assets.find(asset => driveAssetPlacement(asset) === 'feed') || group.assets[0];
        const storiesAsset = group.assets.find(asset => driveAssetPlacement(asset) === 'stories');
        return {
            ...group,
            id: group.key,
            displayAsset: feedAsset,
            feedAsset,
            storiesAsset,
            isPair: Boolean(feedAsset && storiesAsset && feedAsset.id !== storiesAsset.id),
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

// Live permutation count for the sticky counter below — mirrors BulkAdCreation.jsx's
// own useEffect (media.length × valid-headlines × valid-bodies) exactly, so the number
// shown here never drifts from what Review actually generates. Kept as a pure function
// (not inline in the component) so the two call sites can't quietly diverge.
const countVariations = (creativeData) => {
    const media = creativeData?.creatives?.length || 0;
    const headlines = (creativeData?.headlines || []).filter(h => h && h.trim() !== '').length;
    const bodies = (creativeData?.bodies || []).filter(b => b && b.trim() !== '').length;
    return { media, headlines, bodies, total: media * headlines * bodies };
};

const AdCreativeStep = ({ onNext, onBack, mode = 'combinations' }) => {
    const isMatchImport = mode === 'match-import';
    const { showWarning, showError, showSuccess } = useToast();
    const { authFetch } = useAuth();
    const { creativeData, setCreativeData, selectedAdAccount, adsetData, campaignData } = useCampaign();
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
    const [pages, setPages] = useState([]);
    const [loadingPages, setLoadingPages] = useState(false);

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
    const [selectedDriveAssetIds, setSelectedDriveAssetIds] = useState(new Set());
    const [driveSearchTerm, setDriveSearchTerm] = useState('');
    const [driveFormatFilter, setDriveFormatFilter] = useState('');
    const [showDriveLibraryHint, setShowDriveLibraryHint] = useState(
        () => safeLocalStorageGet('driveLibraryHintSeen') !== 'true'
    );
    const [copyFieldsTouched, setCopyFieldsTouched] = useState({
        headlines: false,
        bodies: false,
        description: false,
        cta: false,
        websiteUrl: false,
    });
    // Wire key must be snake_case (`creative_enhancements`) to match what
    // facebook_service.py reads off the request body — the backend never
    // does camelCase->snake_case conversion, so a mismatch here silently
    // no-ops the whole feature (caught in pre-push review, was `creativeEnhancements`).
    const [creativeEnhancements, setCreativeEnhancements] = useState(
        () => creativeData.creative_enhancements || {}
    );
    const [isEnhancementsPanelOpen, setIsEnhancementsPanelOpen] = useState(false);

    const toggleCreativeEnhancement = (key) => {
        setCreativeEnhancements(prev => {
            const next = { ...prev, [key]: !prev[key] };
            setCreativeData(current => ({ ...current, creative_enhancements: next }));
            return next;
        });
    };

    const driveAssetGroups = useMemo(() => {
        const query = driveSearchTerm.trim().toLowerCase();
        const visibleAssets = driveAssets.filter(asset => {
            if (driveFormatFilter && asset.format !== driveFormatFilter) return false;
            if (!query) return true;
            const haystack = `${asset.file_name || ''} ${asset.folder_path || ''} ${asset.brand_name || ''}`.toLowerCase();
            return haystack.includes(query);
        });
        return buildDriveAssetGroups(visibleAssets);
    }, [driveAssets, driveSearchTerm, driveFormatFilter]);

    const driveGroupById = useMemo(() => new Map(driveAssetGroups.map(group => [group.id, group])), [driveAssetGroups]);
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
            const next = new Set([...prev].filter(id => driveGroupById.has(id)));
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

    const fetchDriveAssets = async () => {
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
            setDriveAssets(Array.isArray(data) ? data : []);
        } catch (err) {
            setDriveLibraryError(err.message || 'Failed to load Drive Creative Library');
        } finally {
            setDriveLibraryLoading(false);
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
        setDriveFormatFilter('');
        // Step-mount already fetches this for the button's live count — avoid a
        // second, redundant request (and a loading-state flicker) on every open.
        setShowDriveLibraryModal(true);
    };

    const toggleDriveAssetSelection = (assetId) => {
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
        setSelectedDriveAssetIds(prev => {
            const next = new Set(prev);
            driveAssetGroups.forEach(group => next.add(group.id));
            return next;
        });
    };

    const clearDriveAssetSelection = () => {
        setSelectedDriveAssetIds(new Set());
    };

    const selectFirstNDriveAssets = () => {
        const n = parseInt(driveSelectCount, 10);
        if (!Number.isFinite(n) || n <= 0) return;
        setSelectedDriveAssetIds(prev => {
            const next = new Set(prev);
            driveAssetGroups.slice(0, n).forEach(group => next.add(group.id));
            return next;
        });
    };

    const addDriveSelectionToCreatives = () => {
        const selectedGroups = [...selectedDriveAssetIds]
            .map(id => driveGroupById.get(id))
            .filter(Boolean);
        const newCreatives = selectedGroups.flatMap(group => {
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
                    dualPlacement: true,
                    drivePairId: group.id
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
                    drivePairId: null
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
                drivePairId: group.id
            }));
        });
        const groupsWithCopy = selectedGroups.filter(group => hasCopyText(group.copy || {}));
        const firstWithCopy = groupsWithCopy[0] || selectedGroups.find(group => group.landingPage || group.cta);
        const firstCopy = firstWithCopy?.copy || {};
        const firstDefaultUrl = selectedGroups.map(defaultUrlForDriveGroup).find(Boolean) || '';
        setCreativeData(prev => {
            const nextHeadlines = firstCopy.headline && !copyFieldsTouched.headlines ? [firstCopy.headline] : prev.headlines;
            const nextBodies = firstCopy.primary_text && !copyFieldsTouched.bodies ? [firstCopy.primary_text] : prev.bodies;
            const nextDescription = firstCopy.description && !copyFieldsTouched.description ? firstCopy.description : prev.description;
            const nextCta = firstWithCopy?.cta && !copyFieldsTouched.cta ? firstWithCopy.cta : (prev.cta || 'LEARN_MORE');
            const nextWebsiteUrl = (firstWithCopy?.landingPage || firstDefaultUrl) && !copyFieldsTouched.websiteUrl
                ? (firstWithCopy?.landingPage || firstDefaultUrl)
                : prev.websiteUrl;

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
        if (newCreatives.length > 0) {
            const pairCount = selectedGroups.filter(group => group.isPair).length;
            const copySource = firstWithCopy?.displayAsset?.folder_path || firstWithCopy?.displayAsset?.file_name;
            const copyNote = hasCopyText(firstCopy)
                ? ` Applied Drive copy${groupsWithCopy.length > 1 ? ` from ${copySource}; ${groupsWithCopy.length - 1} other copy set${groupsWithCopy.length - 1 !== 1 ? 's were' : ' was'} not applied.` : copySource ? ` from ${copySource}.` : '.'}`
                : '';
            showSuccess(`Added ${newCreatives.length} Drive asset${newCreatives.length !== 1 ? 's' : ''}${pairCount ? ` from ${pairCount} Feed + Stories pair${pairCount !== 1 ? 's' : ''}` : ''}.${copyNote}`);
        }
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

    // Load last used page ID on mount — scoped per ad account. This used to be
    // a single flat global key, which meant switching ad accounts (different
    // brands) could silently carry over a Page ID that belongs to a different
    // brand entirely. Same leak class as the campaign-scoped caches below.
    // pageId/instagramId are deliberately NOT cleared when the campaign changes
    // (see the campaign-scoped cache effect below) — a brand's Page is stable
    // across its niches/campaigns on the same ad account.
    useEffect(() => {
        if (!selectedAdAccount) return;
        const lastUsedPageId = safeLocalStorageGet(`lastUsedPageId_${selectedAdAccount.id}`);
        if (lastUsedPageId && !creativeData.pageId) {
            handleInputChange('pageId', lastUsedPageId);
        }
    }, [selectedAdAccount]);

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
            fetchPages();
        }
    }, [selectedAdAccount]);

    const fetchPages = async () => {
        setLoadingPages(true);
        try {
            const fetchedPages = await getPages(selectedAdAccount.id);
            setPages(fetchedPages);

            // If no page is selected and we have pages, select the first one (or the last used one if it exists in the list)
            if (fetchedPages.length > 0 && !creativeData.pageId) {
                const lastUsedPageId = safeLocalStorageGet(`lastUsedPageId_${selectedAdAccount.id}`);
                const pageToSelect = fetchedPages.find(p => p.id === lastUsedPageId) || fetchedPages[0];
                handlePageSelection(pageToSelect.id, fetchedPages);
            } else if (fetchedPages.length === 0) {
                // If no pages found, default to manual entry so user isn't blocked
                setManualPageEntry(true);
            }
        } catch (error) {
            console.error('Error fetching pages:', error);
            showError('Failed to load Facebook Pages. You can enter Page ID manually.');
            setManualPageEntry(true); // Auto-switch to manual entry
        } finally {
            setLoadingPages(false);
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
            ...(field === 'pageId' ? { instagramId: null, pageName: null } : {})
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

            // Validate primary text
            if (!creativeData.bodies[0] || !creativeData.bodies[0].trim()) {
                showWarning('Please provide primary text');
                return;
            }

            // Validate headline
            if (!creativeData.headlines[0] || !creativeData.headlines[0].trim()) {
                showWarning('Please provide a headline');
                return;
            }
        }

        if (!creativeData.websiteUrl) {
            showWarning('Please enter a website URL');
            return;
        }

        // Validate URL format
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
                    <div className="flex items-center justify-between mb-2">
                        <label className="block text-sm font-medium text-gray-700">
                            Ad Media (Images or Videos) *
                        </label>
                        <div className="flex items-center gap-4">
                            <div className="relative">
                            {showDriveLibraryHint && (
                                <div className="absolute right-0 bottom-full z-10 mb-2 w-64 rounded-lg border border-indigo-200 bg-indigo-50 p-3 text-left text-xs text-indigo-900 shadow-md">
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
                                className="flex items-center gap-1.5 text-sm text-indigo-700 font-semibold hover:text-indigo-900"
                            >
                                <FolderOpen size={16} />
                                Browse Drive Creative Library ({driveAssets.length})
                            </button>
                            </div>
                            <button
                                type="button"
                                onClick={openLibraryModal}
                                className="flex items-center gap-1.5 text-sm text-amber-600 font-medium hover:text-amber-800"
                            >
                                <BookOpen size={16} />
                                Browse Generated Ads Library
                            </button>
                        </div>
                    </div>

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
                        <div className="grid grid-cols-2 md:grid-cols-3 gap-4 mb-4">
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
                <div className="mt-4 rounded-lg border border-gray-200 bg-gray-50 overflow-hidden">
                    <button
                        type="button"
                        onClick={() => setIsEnhancementsPanelOpen(prev => !prev)}
                        className="w-full flex items-center justify-between px-4 py-3 text-left text-sm font-semibold text-gray-800 hover:bg-gray-100"
                    >
                        <span className="flex items-center gap-2">
                            Creative Enhancements
                            <span className="text-xs font-normal text-gray-500">optional · default off</span>
                            {/* Collapsed-state visibility: Joel-perspective review flagged that
                                once this panel is closed there was no way to tell what's enabled
                                without reopening it. This badge is the fix — visible without
                                expanding, and visible on every ad in a bulk batch. */}
                            {Object.values(creativeEnhancements).some(Boolean) && (
                                <span className="px-2 py-0.5 rounded-full bg-amber-100 text-amber-800 text-xs font-medium">
                                    {Object.values(creativeEnhancements).filter(Boolean).length} enabled
                                </span>
                            )}
                        </span>
                        <span className="text-xs text-gray-500">{isEnhancementsPanelOpen ? 'Hide' : 'Show'}</span>
                    </button>
                    {isEnhancementsPanelOpen && (
                        <div className="border-t border-gray-200 px-4 py-3 space-y-2">
                            <p className="text-xs text-gray-500 mb-3">Opt in per ad request. Nothing is sent to Meta unless you enable a toggle.</p>
                            {CREATIVE_ENHANCEMENT_OPTIONS.map(option => (
                                <label key={option.key} className="flex items-start gap-3 rounded-md px-2 py-2 hover:bg-white cursor-pointer">
                                    <input
                                        type="checkbox"
                                        checked={Boolean(creativeEnhancements[option.key])}
                                        onChange={() => toggleCreativeEnhancement(option.key)}
                                        className="mt-0.5 rounded text-amber-600 focus:ring-amber-500"
                                    />
                                    <span>
                                        <span className="block text-sm font-medium text-gray-700">{option.label}</span>
                                        <span className="block text-xs text-gray-500">{option.description}</span>
                                    </span>
                                </label>
                            ))}
                        </div>
                    )}
                </div>
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
                <div>
                    <div className="flex items-center justify-between mb-2">
                        <label className="block text-sm font-medium text-gray-700">
                            Primary Text *
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
                </div>
                )}

                {/* Headline */}
                {!isMatchImport && (
                <div>
                    <div className="flex items-center justify-between mb-2">
                        <label className="block text-sm font-medium text-gray-700">
                            Headline *
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
                </div>
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
                                    const totalAds = creativeData.creatives.length * validHeadlines * validBodies;
                                    const imageCount = creativeData.creatives.filter(c => c.mediaType !== 'video').length;
                                    const videoCount = creativeData.creatives.filter(c => c.mediaType === 'video').length;
                                    const mediaDesc = [];
                                    if (imageCount > 0) mediaDesc.push(`${imageCount} image${imageCount !== 1 ? 's' : ''}`);
                                    if (videoCount > 0) mediaDesc.push(`${videoCount} video${videoCount !== 1 ? 's' : ''}`);
                                    return (
                                        <>
                                            {totalAds} ad{totalAds !== 1 ? 's' : ''} will be created
                                            <span className="text-sm font-normal ml-2">
                                                ({mediaDesc.join(' + ')} × {validHeadlines} headline{validHeadlines !== 1 ? 's' : ''} × {validBodies} bod{validBodies !== 1 ? 'ies' : 'y'})
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
                        Call to Action *
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
                </div>
                )}

                {/* Website URL */}
                <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">
                        Website URL (Landing Page) *
                    </label>
                    <input
                        type="url"
                        value={creativeData.websiteUrl}
                        onChange={(e) => handleInputChange('websiteUrl', e.target.value)}
                        placeholder="https://yourwebsite.com/landing"
                        className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-amber-500 focus:border-transparent"
                    />
                </div>

                {isMatchImport && (
                    <p className="text-sm text-gray-500 -mt-2">
                        Headlines, body copy, images, and CTA come from your CSV + image folder in the next step.
                    </p>
                )}
            </div>

            {/* Navigation */}
            <div className="mt-8 flex justify-between">
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
            <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
                <div className="bg-white rounded-xl shadow-xl w-full max-w-3xl max-h-[80vh] flex flex-col">
                    <div className="flex items-center justify-between p-4 border-b">
                        <h3 className="text-lg font-semibold">Select from Drive Creative Library</h3>
                        <button onClick={() => setShowDriveLibraryModal(false)} className="text-gray-500 hover:text-gray-700">
                            <X size={20} />
                        </button>
                    </div>
                    <div className="p-4 border-b space-y-3">
                        <label className="relative block">
                            <Search className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" size={16} />
                            <input
                                value={driveSearchTerm}
                                onChange={(e) => setDriveSearchTerm(e.target.value)}
                                placeholder="Search filenames, folders, or brands"
                                className="w-full rounded-lg border border-gray-300 bg-white py-2 pl-9 pr-3 text-sm focus:border-amber-500 focus:ring-2 focus:ring-amber-100"
                            />
                        </label>
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
                                    className={`px-3 py-1.5 text-xs font-semibold transition-colors ${
                                        driveFormatFilter === option.value
                                            ? 'bg-gray-900 text-white'
                                            : 'text-gray-600 hover:bg-gray-50'
                                    }`}
                                >
                                    {option.label}
                                </button>
                            ))}
                        </div>
                        <div className="flex flex-wrap items-center gap-2">
                            <button
                                type="button"
                                onClick={selectAllVisibleDriveAssets}
                                disabled={driveAssetGroups.length === 0}
                                className="px-3 py-1.5 text-xs font-semibold rounded-lg border border-gray-300 text-gray-700 hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed"
                            >
                                Select all {driveAssetGroups.length > 0 ? `(${driveAssetGroups.length})` : ''}
                            </button>
                            <button
                                type="button"
                                onClick={clearDriveAssetSelection}
                                disabled={selectedDriveAssetIds.size === 0}
                                className="px-3 py-1.5 text-xs font-semibold rounded-lg border border-gray-300 text-gray-700 hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed"
                            >
                                Clear selection
                            </button>
                            <div className="flex items-center gap-1.5">
                                <span className="text-xs text-gray-500">Select first (most recent)</span>
                                <input
                                    type="number"
                                    min="1"
                                    value={driveSelectCount}
                                    onChange={(e) => setDriveSelectCount(e.target.value)}
                                    placeholder="e.g. 50"
                                    className="w-20 rounded-lg border border-gray-300 py-1.5 px-2 text-xs focus:border-amber-500 focus:ring-2 focus:ring-amber-100"
                                />
                                <button
                                    type="button"
                                    onClick={selectFirstNDriveAssets}
                                    disabled={!driveSelectCount || driveAssetGroups.length === 0}
                                    className="px-3 py-1.5 text-xs font-semibold rounded-lg border border-gray-300 text-gray-700 hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed"
                                >
                                    Go
                                </button>
                            </div>
                        </div>
                    </div>
                    <div className="flex-1 overflow-y-auto p-4">
                        {driveLibraryLoading ? (
                            <div className="flex items-center justify-center py-12 gap-2 text-gray-500">
                                <Loader className="animate-spin" size={20} />
                                <span>Loading Drive library...</span>
                            </div>
                        ) : driveLibraryError ? (
                            <p className="text-center text-red-600 py-12">{driveLibraryError}</p>
                        ) : driveAssets.length === 0 ? (
                            <p className="text-center text-gray-500 py-12">No synced Drive creative yet. It appears here once the Drive sync job (or a manual sync) has run.</p>
                        ) : driveAssetGroups.length === 0 ? (
                            <p className="text-center text-gray-500 py-12">No Drive assets match that search.</p>
                        ) : (
                            <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
                                {driveAssetGroups.map(group => {
                                    const asset = group.displayAsset;
                                    const isSelected = selectedDriveAssetIds.has(group.id);
                                    const tags = parseDriveTags(asset);
                                    const copyMatched = hasCopyText(group.copy || {});
                                    return (
                                        <div
                                            key={group.id}
                                            onClick={() => toggleDriveAssetSelection(group.id)}
                                            className={`relative cursor-pointer rounded-lg overflow-hidden border-2 transition-all ${isSelected ? 'border-amber-500 ring-2 ring-amber-200' : 'border-gray-200 hover:border-amber-300'}`}
                                        >
                                            {asset.format === 'video' ? (
                                                <video src={asset.r2_key} className="w-full aspect-square object-cover" muted />
                                            ) : (
                                                <img src={asset.r2_key} alt={asset.file_name} className="w-full aspect-square object-cover" />
                                            )}
                                            {isSelected && (
                                                <div className="absolute top-2 right-2 bg-amber-500 rounded-full p-0.5">
                                                    <Check size={14} className="text-white" />
                                                </div>
                                            )}
                                            {group.isPair && (
                                                <div className="absolute top-2 left-2 bg-purple-600 text-white text-[11px] font-semibold px-2 py-1 rounded-full shadow-sm">
                                                    Feed + Stories pair
                                                </div>
                                            )}
                                            {(copyMatched || group.landingPage || group.cta || tags.copy_id) && (
                                                <div className="absolute bottom-[54px] left-2 bg-emerald-600 text-white text-[11px] font-semibold px-2 py-1 rounded-full shadow-sm">
                                                    {copyMatched ? 'Copy matched' : 'URL matched'}
                                                </div>
                                            )}
                                            <div className="p-2 text-xs text-gray-600 bg-white">
                                                <div className="truncate font-medium">{asset.brand_name || 'Unknown brand'}</div>
                                                <div className="truncate text-gray-400">{asset.folder_path || asset.file_name}</div>
                                                {group.isPair && (
                                                    <div className="mt-1 text-[11px] text-purple-700">
                                                        {group.feedAsset?.file_name} + {group.storiesAsset?.file_name}
                                                    </div>
                                                )}
                                            </div>
                                        </div>
                                    );
                                })}
                            </div>
                        )}
                    </div>
                    <div className="p-4 border-t flex items-center justify-between gap-3 flex-wrap">
                        <span className="text-sm text-gray-500">
                            {selectedDriveAssetIds.size} selected
                            {selectedDriveAssetIds.size > 0 && `, ${driveSelectionAssetCount} asset${driveSelectionAssetCount !== 1 ? 's' : ''}`}
                            {/* Surfaces the permutation multiplication BEFORE the click that
                                commits it — bulk-selecting 50 assets against several queued
                                headlines/bodies doesn't create 50 ads, it multiplies (see
                                countVariations above), and that math was previously only
                                visible on the main step after closing this modal (pre-push
                                review, joel-perspective: P1). Uses driveSelectionMediaCount,
                                not driveSelectionAssetCount — a real tagged pair adds ONE
                                creative (merged), while an auto-duped single adds TWO; using
                                the raw asset count here under- or over-counted depending on
                                the mix (pre-push review, code-auditor: HIGH). */}
                            {selectedDriveAssetIds.size > 0 && (variationCount.headlines > 1 || variationCount.bodies > 1) && (
                                <span className="block text-xs text-amber-700 mt-0.5">
                                    → {(variationCount.media + driveSelectionMediaCount) * Math.max(variationCount.headlines, 1) * Math.max(variationCount.bodies, 1)} total ad combinations after adding ({variationCount.media + driveSelectionMediaCount} media × {variationCount.headlines || 1} headline{variationCount.headlines !== 1 ? 's' : ''} × {variationCount.bodies || 1} bod{variationCount.bodies !== 1 ? 'ies' : 'y'})
                                </span>
                            )}
                            {selectedDriveAssetIds.size > 0 && autoDupeStories && (
                                <span className="block text-[11px] text-gray-400 mt-0.5">
                                    Auto-duplicate is on — unpaired single images above will add both a Feed and Stories version.
                                </span>
                            )}
                        </span>
                        <div className="flex gap-3">
                            <button onClick={() => setShowDriveLibraryModal(false)} className="px-4 py-2 text-gray-600 hover:text-gray-800 font-medium">
                                Cancel
                            </button>
                            <button
                                onClick={addDriveSelectionToCreatives}
                                disabled={selectedDriveAssetIds.size === 0}
                                className="px-4 py-2 bg-amber-600 text-white rounded-lg font-medium hover:bg-amber-700 disabled:bg-gray-300 disabled:cursor-not-allowed"
                            >
                                Add {selectedDriveAssetIds.size > 0 ? selectedDriveAssetIds.size : ''} to Campaign
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        )}
        </>
    );
};

export default AdCreativeStep;
