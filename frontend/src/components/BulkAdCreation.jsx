import { useToast } from '../context/ToastContext';
import { useAuth } from '../context/AuthContext';
import React, { useState } from 'react';
import { ChevronRight, Plus, Loader, Film, Image, X } from 'lucide-react';
import { useCampaign } from '../context/CampaignContext';
import { createCompleteAd, createFacebookCampaign, createFacebookAdSet, getRateLimitUsage } from '../lib/facebookApi';
import { INTER_REQUEST_DELAY_MS, USAGE_WARN_THRESHOLD, delay, isRateLimitError, peakUsagePercent, rateLimitStopMessage } from '../lib/metaRateLimit';

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

// 'LEARN_MORE' -> 'Learn More' — same values BulkAdCreation already sends to Meta
// (AdCreativeStep.jsx's CTA_OPTIONS), just title-cased for a native-looking button.
const formatCtaLabel = (cta) => (cta || 'LEARN_MORE')
    .split('_')
    .map(word => word.charAt(0) + word.slice(1).toLowerCase())
    .join(' ');

const BulkAdCreation = ({ onNext, onBack }) => {
    const { showWarning, showError } = useToast();
    const { authFetch } = useAuth();
    const { campaignData, adsetData, creativeData, adsData, setAdsData, selectedAdAccount } = useCampaign();
    const [loading, setLoading] = useState(false);
    const [progress, setProgress] = useState({ current: 0, total: 0, status: '' });
    const [errors, setErrors] = useState([]);
    // Last Meta rate-limit reading, shown in the launch panel. null until
    // a launch is attempted; `available: false` means Meta told us nothing.
    const [rateLimitUsage, setRateLimitUsage] = useState(null);
    // Per-row outcome of the last launch: which indexes were created and where a
    // throttle stopped the batch. Without this the review list shows all N ads
    // with no indication of which ones actually made it, leaving the user to
    // reconcile against Ads Manager by hand.
    const [launchOutcome, setLaunchOutcome] = useState(null);

    // Initialize ads based on creatives - generate all permutations
    React.useEffect(() => {
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
                validHeadlines.forEach(({ index: hIndex }) => {
                    validBodies.forEach(({ index: bIndex }) => {
                        const isVideo = creative.mediaType === 'video';
                        const mediaLabel = isVideo ? 'Video' : 'Image';
                        permutations.push({
                            id: `ad_${Date.now()}_${creativeIndex}_${hIndex}_${bIndex}`,
                            name: `${creative.name || `${mediaLabel} ${creativeIndex + 1}`} - H${hIndex + 1}B${bIndex + 1}`,
                            creativeId: creative.id,
                            headlineIndex: hIndex,
                            bodyIndex: bIndex,
                            mediaType: creative.mediaType || 'image',
                            format: creative.format || 'feed',
                            dualPlacement: creative.dualPlacement || false,
                            useDefaultCreative: true
                        });
                    });
                });
            });

            setAdsData(permutations);
        } else {
            // Fallback if no creatives (shouldn't happen due to validation)
            setAdsData([]);
        }
    }, [creativeData.creatives, creativeData.headlines, creativeData.bodies]);

    // Format detection — drives multi-adset launch logic
    const feedAds    = adsData.filter(ad => (ad.format || 'feed') !== 'stories');
    const storiesAds = adsData.filter(ad => ad.format === 'stories');
    const isMixedFormat  = feedAds.length > 0 && storiesAds.length > 0;
    const allStoriesFormat = feedAds.length === 0 && storiesAds.length > 0;

    const addAd = () => {
        setAdsData(prev => [
            ...prev,
            {
                id: `ad_${Date.now()}_${prev.length}`,
                name: `Ad ${prev.length + 1}`,
                useDefaultCreative: true
            }
        ]);
    };

    const removeAd = (index) => {
        setAdsData(prev => prev.filter((_, i) => i !== index));
    };

    const updateAdName = (index, name) => {
        setAdsData(prev => prev.map((ad, i) => i === index ? { ...ad, name } : ad));
    };

    const handleSubmit = async () => {
        if (adsData.length === 0) {
            showWarning('Please add at least one ad');
            return;
        }

        setLoading(true);
        setErrors([]);
        setLaunchOutcome(null);

        // Determine format strategy at submission time (not stale closure)
        const feedAdsToCreate    = adsData.filter(ad => (ad.format || 'feed') !== 'stories');
        const storiesAdsToCreate = adsData.filter(ad => ad.format === 'stories');
        const isMixed      = feedAdsToCreate.length > 0 && storiesAdsToCreate.length > 0;
        const isAllStories = feedAdsToCreate.length === 0 && storiesAdsToCreate.length > 0;

        setProgress({ current: 0, total: adsData.length, status: 'Checking Meta rate limits...' });

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
                        + `Launching ${adsData.length} ad${adsData.length === 1 ? '' : 's'} now may get throttled partway. `
                        + `Safer: launch 5-10 at a time, or wait ~15 minutes for the limit to recover. `
                        + `If it does throttle, the batch stops and marks which ads were created.`
                    );
                }
            }
        } catch (err) {
            // Telemetry must never block a launch.
            console.warn('Rate-limit pre-flight skipped:', err);
        }

        setProgress({ current: 0, total: adsData.length, status: 'Starting...' });

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
                instagram_positions: ['stream', 'story']
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
            let storiesAdsetLocalId = null;

            if (!adsetData.isExisting) {
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
            } else if (hasDualPlacementAds) {
                // Reusing an existing ad set — we can't retroactively confirm or
                // change its own targeting from here, so warn rather than assume
                // it already includes Story placement. If it doesn't, Meta may
                // simply never deliver into Stories for these creatives (safe
                // failure — no wrong-image risk — but worth Abel/Joel knowing).
                showWarning('This ad set was created before dual-placement — confirm its targeting includes Stories/Reels placement, or the linked creative may only ever deliver to Feed.');
            }

            // Save feed (or sole) ad set locally
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
            } catch (err) {
                console.error('Error saving ad set locally:', err);
                throw err;
            }

            // Save stories ad set locally (non-fatal if it fails)
            if (fbStoriesAdsetId && storiesAdsetLocalId) {
                try {
                    await authFetch(`${API_URL}/facebook/adsets/save`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            ...adsetSaveBody,
                            id: storiesAdsetLocalId,
                            name: `${adsetData.name} - Stories & Reels`,
                            fbAdsetId: fbStoriesAdsetId
                        })
                    });
                } catch (err) {
                    console.warn('Could not save stories ad set locally — continuing:', err);
                }
            }

            // ── Step 3: Ads ───────────────────────────────────────────────────────
            const createdAds = [];
            let failedCount = 0;
            let rateLimited = false;
            let attempted = 0;
            const createdIndexes = [];
            for (let i = 0; i < adsData.length; i++) {
                // Space out the per-ad Meta calls. Each iteration below is
                // several writes (image upload + creative + ad), so a 20-ad
                // batch fired back-to-back is a burst big enough to trip the
                // account's limit partway through and leave a half-built
                // campaign. Skipped before the first ad so a single ad is not
                // needlessly delayed.
                if (i > 0) await delay(INTER_REQUEST_DELAY_MS);

                attempted = i + 1;
                const ad = adsData[i];
                const isStoriesAd   = ad.format === 'stories';
                const adFbAdsetId   = isStoriesAd && fbStoriesAdsetId ? fbStoriesAdsetId : fbFeedAdsetId;
                const adLocalAdsetId = isStoriesAd && storiesAdsetLocalId ? storiesAdsetLocalId : adsetData.id;

                setProgress({
                    current: i + 1,
                    total: adsData.length,
                    status: `Creating ${isStoriesAd ? 'Stories' : 'Feed'} ad ${i + 1} of ${adsData.length}...`
                });

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
                        headlines: [creativeData.headlines[ad.headlineIndex]],
                        bodies: [creativeData.bodies[ad.bodyIndex]]
                    };

                    if (!creativeData.pageId) {
                        throw new Error('Page ID is missing. Please go back to the Creative step and select a Facebook Page.');
                    }

                    if (isVideo) {
                        setProgress(prev => ({
                            ...prev,
                            status: `Uploading video ${i + 1} of ${adsData.length}... (this may take a while)`
                        }));
                    }

                    const result = await createCompleteAd(
                        fbCampaignId,
                        { ...adsetData, fbAdsetId: adFbAdsetId },
                        adSpecificCreativeData,
                        ad,
                        creativeData.pageId,
                        selectedAdAccount.accountId,
                        campaignData.budgetType
                    );

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
                            bodies: creativeData.bodies.filter(b => b.trim() !== ''),
                            headlines: creativeData.headlines.filter(h => h.trim() !== ''),
                            description: creativeData.description,
                            cta: creativeData.cta,
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

                    createdIndexes.push(i);
                    createdAds.push({
                        ...ad,
                        fbAdId: result.adId,
                        fbCreativeId: result.creativeId,
                        videoId: result.videoId
                    });
                } catch (error) {
                    console.error(`Error creating ad ${ad.name}:`, error);
                    setErrors(prev => [...prev, `Failed to create ${ad.name}: ${error.message}`]);
                    failedCount++;

                    // Meta throttled the account. Stop now rather than grinding
                    // the remaining ads into a wall of identical errors — every
                    // further attempt is guaranteed to fail and only pushes the
                    // account deeper into the limit.
                    if (isRateLimitError(error)) {
                        rateLimited = true;
                        setLaunchOutcome({ createdIndexes: [...createdIndexes], stoppedAtIndex: i });

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
                            created: createdAds.length,
                            total: adsData.length,
                            attempted,
                            regainSeconds,
                            notAttemptedNames: adsData.slice(i + 1).map(a => a.name).filter(Boolean),
                        })]);
                        break;
                    }
                }
            }

            if (rateLimited) {
                // Don't advance — the batch is incomplete by definition and Joel
                // needs to see how far it got before deciding what to re-run.
                setProgress({ current: attempted, total: adsData.length, status: `Stopped — ${createdAds.length} of ${adsData.length} ads created` });
                setLoading(false);
            } else if (failedCount === 0) {
                // All ads created — auto-advance after brief success display
                setProgress({ current: adsData.length, total: adsData.length, status: 'Complete!' });
                setTimeout(() => { onNext(); }, 1500);
            } else {
                // Partial failure — stay on screen so Joel can see what failed
                setProgress({ current: adsData.length, total: adsData.length, status: `${createdAds.length} of ${adsData.length} ads created` });
                setLoading(false);
            }

        } catch (error) {
            console.error('Error in bulk ad creation:', error);
            showError(`Error: ${error.message}`);
            setLoading(false);
        }
    };

    return (
        <div>
            <h2 className="text-2xl font-bold mb-6">Review & Launch Ads</h2>
            <p className="text-gray-600 mb-2">
                The app has automatically generated one ad for every combination of your images, headlines, and body copy. Each row below is one ad that will be created on Facebook.
            </p>
            <p className="text-gray-600 mb-6">
                You can rename any ad before launching. Remove any combinations you don't want by clicking the trash icon.
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
                    <div><strong>Total Ads to Create:</strong> {adsData.length} ({(() => {
                        const images = creativeData.creatives?.filter(c => c.mediaType !== 'video').length || 0;
                        const videos = creativeData.creatives?.filter(c => c.mediaType === 'video').length || 0;
                        const media = images + videos;
                        const headlines = creativeData.headlines?.filter(h => h && h.trim()).length || 0;
                        const bodies = creativeData.bodies?.filter(b => b && b.trim()).length || 0;
                        return `${media} media × ${headlines} headline${headlines !== 1 ? 's' : ''} × ${bodies} body`;
                    })()})</div>
                    {isMixedFormat && (
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
                    {isMixedFormat && campaignData.budgetType === 'ABO' && (
                        <div className="mt-2 pt-2 border-t border-blue-200 text-sm font-medium text-amber-700">
                            ⚠️ ABO: each ad set gets its own budget —{' '}
                            {adsetData.budgetScheduleType === 'LIFETIME'
                                ? `total lifetime spend will be $${(Number(adsetData.lifetimeBudget || 0) * 2).toFixed(2)}`
                                : `total daily spend will be $${(Number(adsetData.dailyBudget || 0) * 2).toFixed(2)}/day`
                            }.
                        </div>
                    )}
                    {allStoriesFormat && (
                        <div className="mt-1 text-blue-700 font-medium">📱 All creatives are 9:16 — ad set will target Stories & Reels only</div>
                    )}
                </div>
            </div>

            {!loading ? (
                <>
                    {/* Ads Preview Grid — one native-style Facebook feed-preview card per
                        combination, instead of a thumbnail + rename row. Shows the actual
                        headline/body text for that specific combination so a bad pairing is
                        visible before launch, not just trusted from the permutation math. */}
                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4 mb-4">
                        {adsData.map((ad, index) => {
                            const creative = creativeData.creatives?.find(c => c.id === ad.creativeId);
                            const isVideo = creative?.mediaType === 'video';
                            const headline = creativeData.headlines?.[ad.headlineIndex];
                            const body = creativeData.bodies?.[ad.bodyIndex];
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
                                if (launchOutcome.createdIndexes.includes(index)) {
                                    outcome = { label: 'Created', cls: 'bg-emerald-100 text-emerald-700' };
                                } else if (index > launchOutcome.stoppedAtIndex) {
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
                                    <button
                                        onClick={() => removeAd(index)}
                                        title="Exclude this ad from the launch"
                                        className="absolute top-2 right-2 z-10 p-1 rounded-full bg-white/90 text-red-500 hover:text-red-700 hover:bg-white shadow-sm transition-colors"
                                    >
                                        <X size={14} />
                                    </button>

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
                                        <div className={`bg-gray-200 relative ${ad.format === 'stories' ? 'aspect-[9/16]' : 'aspect-square'}`}>
                                            {isVideo ? (
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
                                    {!isEmptyCustomAd && (
                                        <div className="flex items-center justify-between gap-2 px-3 py-2 bg-gray-50 border-t border-gray-200">
                                            <div className="min-w-0">
                                                {creativeData.websiteUrl && (
                                                    <div className="text-[11px] uppercase text-gray-400 truncate">{displayDomain(creativeData.websiteUrl)}</div>
                                                )}
                                                <div className="text-sm font-semibold text-gray-900 truncate">{headline || '—'}</div>
                                            </div>
                                            <span className="flex-shrink-0 text-xs font-medium px-3 py-1.5 rounded bg-gray-200 text-gray-700">
                                                {formatCtaLabel(creativeData.cta)}
                                            </span>
                                        </div>
                                    )}

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

                    {/* Add Ad Button */}
                    <button
                        onClick={addAd}
                        className="w-full p-4 border-2 border-dashed border-gray-300 rounded-lg text-gray-600 hover:border-blue-500 hover:text-blue-600 transition-colors flex items-center justify-center gap-2"
                        title="Adds a blank ad slot — use this only if you want to manually add an ad outside the auto-generated combinations above"
                    >
                        <Plus size={20} />
                        Add a Custom Ad
                    </button>

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
                        <button
                            onClick={onBack}
                            className="px-6 py-3 text-gray-600 hover:text-gray-800 font-medium"
                        >
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
                                disabled={adsData.length === 0}
                                className="flex items-center gap-2 px-6 py-3 bg-green-600 text-white rounded-lg font-medium hover:bg-green-700 disabled:bg-gray-300 disabled:cursor-not-allowed"
                            >
                                Create {adsData.length} Ad{adsData.length !== 1 ? 's' : ''} on Facebook
                            </button>
                        )}
                    </div>
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
                        {progress.status === 'Complete!' && (
                            <p className="text-sm text-amber-700 mt-3 font-medium">
                                All ads are <strong>PAUSED</strong> in Meta — go to Ads Manager to activate them when ready.
                            </p>
                        )}
                    </div>
                </>
            )}
        </div>
    );
};

export default BulkAdCreation;
