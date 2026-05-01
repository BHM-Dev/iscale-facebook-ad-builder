import { useToast } from '../context/ToastContext';
import { useAuth } from '../context/AuthContext';
import React, { useState } from 'react';
import { ChevronRight, Plus, Trash2, Loader, Film, Image } from 'lucide-react';
import { useCampaign } from '../context/CampaignContext';
import { createCompleteAd, createFacebookCampaign, createFacebookAdSet } from '../lib/facebookApi';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1';

const BulkAdCreation = ({ onNext, onBack }) => {
    const { showWarning, showError } = useToast();
    const { authFetch } = useAuth();
    const { campaignData, adsetData, creativeData, adsData, setAdsData, selectedAdAccount } = useCampaign();
    const [loading, setLoading] = useState(false);
    const [progress, setProgress] = useState({ current: 0, total: 0, status: '' });
    const [errors, setErrors] = useState([]);

    // Initialize ads based on creatives - generate all permutations
    React.useEffect(() => {
        if (creativeData.creatives && creativeData.creatives.length > 0) {
            // Filter out empty headlines and bodies
            const validHeadlines = creativeData.headlines.filter(h => h && h.trim() !== '');
            const validBodies = creativeData.bodies.filter(b => b && b.trim() !== '');

            // Generate all permutations: media × headlines × bodies
            const permutations = [];
            creativeData.creatives.forEach((creative, creativeIndex) => {
                validHeadlines.forEach((headline, hIndex) => {
                    validBodies.forEach((body, bIndex) => {
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
                            useDefaultCreative: true
                        });
                    });
                });
            });

            setAdsData(permutations);
            const imageCount = creativeData.creatives.filter(c => c.mediaType !== 'video').length;
            const videoCount = creativeData.creatives.filter(c => c.mediaType === 'video').length;
            console.log(`Generated ${permutations.length} ad permutations (${imageCount} images + ${videoCount} videos × ${validHeadlines.length} headlines × ${validBodies.length} bodies)`);
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

        // Determine format strategy at submission time (not stale closure)
        const feedAdsToCreate    = adsData.filter(ad => (ad.format || 'feed') !== 'stories');
        const storiesAdsToCreate = adsData.filter(ad => ad.format === 'stories');
        const isMixed      = feedAdsToCreate.length > 0 && storiesAdsToCreate.length > 0;
        const isAllStories = feedAdsToCreate.length === 0 && storiesAdsToCreate.length > 0;

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
                    const err = await saveCampRes.json();
                    throw new Error(`Failed to save campaign locally: ${err.detail || err.message}`);
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
                    const err = await saveAdSetRes.json();
                    throw new Error(`Failed to save ad set locally: ${err.detail || err.message}`);
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
            for (let i = 0; i < adsData.length; i++) {
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
                }
            }

            if (failedCount === 0) {
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
                    {/* Ads List */}
                    <div className="space-y-2 mb-4">
                        {adsData.map((ad, index) => {
                            const creative = creativeData.creatives?.find(c => c.id === ad.creativeId);
                            const isVideo = creative?.mediaType === 'video';
                            return (
                                <div key={ad.id} className="flex items-center gap-3 p-4 bg-gray-50 rounded-lg border border-gray-200">
                                    {/* Format badge */}
                                    <span className={`text-xs px-2 py-0.5 rounded-full font-medium flex-shrink-0 ${
                                        ad.format === 'stories'
                                            ? 'bg-purple-100 text-purple-700'
                                            : 'bg-blue-100 text-blue-700'
                                    }`}>
                                        {ad.format === 'stories' ? '9:16' : '1:1'}
                                    </span>
                                    {/* Thumbnail */}
                                    {creative && (
                                        <div className="w-12 h-12 rounded overflow-hidden bg-gray-200 flex-shrink-0 relative">
                                            {isVideo ? (
                                                <>
                                                    <video
                                                        src={creative.previewUrl}
                                                        className="w-full h-full object-cover"
                                                        muted
                                                    />
                                                    <div className="absolute bottom-0 right-0 bg-purple-600 text-white p-0.5 rounded-tl">
                                                        <Film size={10} />
                                                    </div>
                                                </>
                                            ) : (
                                                <>
                                                    <img
                                                        src={creative.previewUrl}
                                                        alt="Thumbnail"
                                                        className="w-full h-full object-cover"
                                                    />
                                                    <div className="absolute bottom-0 right-0 bg-blue-600 text-white p-0.5 rounded-tl">
                                                        <Image size={10} />
                                                    </div>
                                                </>
                                            )}
                                        </div>
                                    )}
                                    <div className="flex-1">
                                        <input
                                            type="text"
                                            value={ad.name}
                                            onChange={(e) => updateAdName(index, e.target.value)}
                                            placeholder={`Ad ${index + 1} name`}
                                            className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                                        />
                                    </div>
                                    <button
                                        onClick={() => removeAd(index)}
                                        className="p-2 text-red-500 hover:text-red-700 hover:bg-red-50 rounded-lg transition-colors"
                                    >
                                        <Trash2 size={20} />
                                    </button>
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
