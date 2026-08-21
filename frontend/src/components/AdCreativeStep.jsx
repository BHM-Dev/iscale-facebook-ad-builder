import { useToast } from '../context/ToastContext';
import { useAuth } from '../context/AuthContext';
import React, { useState, useEffect, useMemo } from 'react';
import { ChevronRight, Upload, X, Loader, Trash2, Copy, Film, Image, BookOpen, Check, Layers, FolderOpen, Search } from 'lucide-react';
import { useCampaign } from '../context/CampaignContext';
import { getPages } from '../lib/facebookApi';
import { safeLocalStorageGet, safeLocalStorageSet } from '../lib/safeLocalStorage';
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
        const manifestKey = tags.copy_id ? `manifest:${asset.brand_id}:${asset.folder_path || ''}:${String(tags.copy_id).toLowerCase()}` : null;
        const key = manifestKey || `single:${asset.id}`;
        const existing = grouped.get(key) || {
            key,
            assets: [],
            copy: tags.copy || null,
            landingPage: tags.landing_page || null,
            cta: tags.cta || null,
        };
        existing.assets.push(asset);
        existing.copy = existing.copy || tags.copy || null;
        existing.landingPage = existing.landingPage || tags.landing_page || null;
        existing.cta = existing.cta || tags.cta || null;
        grouped.set(key, existing);
    });

    return Array.from(grouped.values()).map(group => {
        const feedAsset = group.assets.find(asset => driveAssetPlacement(asset) === 'feed') || group.assets[0];
        const storiesAsset = group.assets.find(asset => driveAssetPlacement(asset) === 'stories');
        return {
            ...group,
            id: group.key,
            displayAsset: feedAsset,
            feedAsset,
            storiesAsset,
            isPair: Boolean(feedAsset && storiesAsset && feedAsset.id !== storiesAsset.id),
        };
    });
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
    const [pages, setPages] = useState([]);
    const [loadingPages, setLoadingPages] = useState(false);

    const [manualPageEntry, setManualPageEntry] = useState(false);
    const [isDragging, setIsDragging] = useState(false);

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
    const [copyFieldsTouched, setCopyFieldsTouched] = useState({
        headlines: false,
        bodies: false,
        description: false,
        cta: false,
        websiteUrl: false,
    });

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

    const openDriveLibraryModal = () => {
        setSelectedDriveAssetIds(new Set());
        setDriveSearchTerm('');
        setDriveFormatFilter('');
        fetchDriveAssets();
        setShowDriveLibraryModal(true);
    };

    const toggleDriveAssetSelection = (assetId) => {
        setSelectedDriveAssetIds(prev => {
            const next = new Set(prev);
            next.has(assetId) ? next.delete(assetId) : next.add(assetId);
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

            const assets = group.isPair ? [group.feedAsset, group.storiesAsset] : [group.displayAsset];
            return assets.filter(Boolean).map(asset => ({
                id: `drive_${asset.id}`,
                file: null,
                previewUrl: asset.r2_key,
                imageUrl: asset.format === 'video' ? undefined : asset.r2_key,
                videoUrl: asset.format === 'video' ? asset.r2_key : undefined,
                name: asset.file_name,
                mediaType: asset.format,
                format: driveAssetPlacement(asset),
                drivePairId: group.isPair ? group.id : null
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

        const newCreatives = mediaFiles.map(file => {
            const isVideo = ALLOWED_VIDEO_TYPES.includes(file.type);
            return {
                id: `creative_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
                file,
                previewUrl: URL.createObjectURL(file),
                name: file.name,
                mediaType: isVideo ? 'video' : 'image',
                format: 'feed'
            };
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

        setCreativeData(prev => ({
            ...prev,
            creatives: [],
            creativesScopeId: scopeId
        }));
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
            // When manually entering a Page ID, clear the instagramId to prevent using Page ID as IG ID
            ...(field === 'pageId' ? { instagramId: null } : {})
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

        const newCreatives = files.map(file => {
            const isVideo = ALLOWED_VIDEO_TYPES.includes(file.type);
            return {
                id: `creative_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
                file,
                previewUrl: URL.createObjectURL(file),
                name: file.name,
                mediaType: isVideo ? 'video' : 'image',
                format: 'feed'
            };
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

    // Duplicate a creative and pre-toggle its format (feed → stories, stories → feed)
    // so the common workflow of "same image in both placements" is one click
    const duplicateCreative = (id) => {
        setCreativeData(prev => {
            const original = prev.creatives.find(c => c.id === id);
            if (!original) return prev;
            const flippedFormat = (original.format || 'feed') === 'stories' ? 'feed' : 'stories';
            return {
                ...prev,
                creatives: [...prev.creatives, {
                    ...original,
                    id: `creative_${Date.now()}_dup`,
                    format: flippedFormat
                }]
            };
        });
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
                    <div className="bg-amber-50 border border-amber-200 rounded-lg px-4 py-3 mb-6 text-sm text-amber-900">
                        <strong>Want to launch 5 ads?</strong> Upload 5 images below with 1 headline and 1 body — you'll get exactly 5 separate ads. Adding more headlines or body options multiplies the total (e.g. 5 images × 2 headlines = 10 ads).
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
                            <button
                                type="button"
                                onClick={openLibraryModal}
                                className="flex items-center gap-1.5 text-sm text-amber-600 font-medium hover:text-amber-800"
                            >
                                <BookOpen size={16} />
                                Browse Generated Ads Library
                            </button>
                            <button
                                type="button"
                                onClick={openDriveLibraryModal}
                                className="flex items-center gap-1.5 text-sm text-amber-600 font-medium hover:text-amber-800"
                            >
                                <FolderOpen size={16} />
                                Browse Drive Creative Library
                            </button>
                        </div>
                    </div>

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
                        <div className="mb-3 px-3 py-2 bg-blue-50 border border-blue-200 rounded-lg text-xs text-blue-800">
                            <strong>Placement tag:</strong> Each image defaults to <span className="font-semibold text-blue-700">Feed (1:1)</span>. Click the pill on any card to switch it to <span className="font-semibold text-purple-700">Stories (9:16)</span>. Use the copy icon to duplicate an image for the opposite placement.
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
                    <div className="p-4 border-t flex items-center justify-between">
                        <span className="text-sm text-gray-500">
                            {selectedDriveAssetIds.size} selected
                            {selectedDriveAssetIds.size > 0 && `, ${[...selectedDriveAssetIds].reduce((sum, id) => sum + (driveGroupById.get(id)?.isPair ? 2 : 1), 0)} asset${[...selectedDriveAssetIds].reduce((sum, id) => sum + (driveGroupById.get(id)?.isPair ? 2 : 1), 0) !== 1 ? 's' : ''}`}
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
