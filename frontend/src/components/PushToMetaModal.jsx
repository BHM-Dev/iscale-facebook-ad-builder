import React, { useState } from 'react';
import { Rocket, Loader, X, CheckCircle2, ExternalLink } from 'lucide-react';
import { getCampaigns, getAdSets, getPages, createCompleteAd } from '../lib/facebookApi';
import { useToast } from '../context/ToastContext';

// Meta copy limits (characters before truncation)
const HEADLINE_LIMIT = 40;
const BODY_LIMIT = 125;

/**
 * Shared Push to Meta modal.
 * Works from both GeneratedAds library and ImageAds results page.
 *
 * Props:
 *   imageUrl        {string}   URL of the image to push to Meta
 *   initialHeadline {string}   Pre-fill headline from the ad copy
 *   initialBody     {string}   Pre-fill body copy
 *   initialCta      {string}   Pre-fill CTA (defaults to LEARN_MORE)
 *   onClose         {function} Called when the modal should close
 *   onSuccess       {function} Optional — called after a successful push
 */
export default function PushToMetaModal({
    imageUrl,
    initialHeadline = '',
    initialBody = '',
    initialCta = 'LEARN_MORE',
    onClose,
    onSuccess,
}) {
    const { showError } = useToast();

    const [pushCampaigns, setPushCampaigns] = useState([]);
    const [pushAdSets, setPushAdSets] = useState([]);
    const [pushPages, setPushPages] = useState([]);
    const [pushLoading, setPushLoading] = useState(false);
    const [pushSubmitting, setPushSubmitting] = useState(false);
    const [successResult, setSuccessResult] = useState(null); // { adId, adsetName }

    const [pushForm, setPushForm] = useState({
        adAccountId: localStorage.getItem('lastUsedAdAccountId') || '',
        campaignId: '',
        adsetId: '',
        pageId: localStorage.getItem('lastUsedPageId') || '',
        websiteUrl: '',
        headline: initialHeadline,
        body: initialBody,
        cta: initialCta || 'LEARN_MORE',
    });

    const loadPushCampaigns = async (adAccountId) => {
        if (!adAccountId) return;
        setPushLoading(true);
        try {
            const campaigns = await getCampaigns(adAccountId);
            setPushCampaigns(Array.isArray(campaigns) ? campaigns : []);
        } catch (e) {
            showError('Failed to load campaigns');
        } finally {
            setPushLoading(false);
        }
    };

    const loadPushAdSets = async (campaignId) => {
        if (!campaignId) return;
        setPushLoading(true);
        try {
            const adsets = await getAdSets(campaignId);
            setPushAdSets(Array.isArray(adsets) ? adsets : []);
        } catch (e) {
            showError('Failed to load ad sets');
        } finally {
            setPushLoading(false);
        }
    };

    const loadPushPages = async (adAccountId) => {
        if (!adAccountId || pushPages.length > 0) return;
        try {
            const pages = await getPages(adAccountId);
            setPushPages(Array.isArray(pages) ? pages : []);
        } catch (e) { /* non-blocking */ }
    };

    const handlePushToFacebook = async () => {
        if (!pushForm.campaignId || !pushForm.adsetId || !pushForm.pageId || !pushForm.websiteUrl) {
            showError('Please fill in all required fields');
            return;
        }
        setPushSubmitting(true);
        try {
            const adsetObj = pushAdSets.find(a => a.id === pushForm.adsetId);
            const result = await createCompleteAd(
                pushForm.campaignId,
                { fbAdsetId: pushForm.adsetId, ...adsetObj },
                {
                    mediaType: 'image',
                    imageUrl,
                    headlines: [pushForm.headline],
                    bodies: [pushForm.body],
                    cta: pushForm.cta,
                    websiteUrl: pushForm.websiteUrl,
                },
                { id: `pushed_img_${Date.now()}`, name: pushForm.headline || 'Ad from Image Builder' },
                pushForm.pageId,
                pushForm.adAccountId,
                'ABO'
            );
            // Persist selections for next use
            if (pushForm.pageId) localStorage.setItem('lastUsedPageId', pushForm.pageId);
            if (pushForm.adAccountId) localStorage.setItem('lastUsedAdAccountId', pushForm.adAccountId);

            setSuccessResult({
                adId: result?.adId,
                adsetName: adsetObj?.name || pushForm.adsetId,
                campaignId: pushForm.campaignId,
                adAccountId: pushForm.adAccountId,
            });
            if (onSuccess) onSuccess();
        } catch (e) {
            showError(`Failed to push ad: ${e.message}`);
        } finally {
            setPushSubmitting(false);
        }
    };

    // Character count colour helper
    const countColor = (len, limit) =>
        len > limit ? 'text-red-600 font-semibold' : len > limit * 0.85 ? 'text-amber-600' : 'text-gray-400';

    // Success screen
    if (successResult) {
        const adsManagerUrl = successResult.adAccountId && successResult.campaignId
            ? `https://adsmanager.facebook.com/adsmanager/manage/ads?act=${successResult.adAccountId.replace('act_', '')}&selected_campaign_ids=${successResult.campaignId}`
            : 'https://adsmanager.facebook.com';

        return (
            <div
                className="fixed inset-0 bg-black/50 backdrop-blur-sm z-[60] flex items-center justify-center p-4"
                onClick={onClose}
            >
                <div
                    className="bg-white rounded-2xl shadow-2xl max-w-lg w-full p-8 text-center"
                    onClick={(e) => e.stopPropagation()}
                >
                    <div className="w-16 h-16 bg-green-100 rounded-full flex items-center justify-center mx-auto mb-4">
                        <CheckCircle2 size={36} className="text-green-600" />
                    </div>
                    <h3 className="text-xl font-bold text-gray-900 mb-2">Ad Pushed to Meta!</h3>
                    <p className="text-gray-500 text-sm mb-6">Your ad is now in Ads Manager.</p>
                    <div className="bg-gray-50 rounded-xl p-4 text-left space-y-2 mb-6 text-sm">
                        {successResult.adId && (
                            <div className="flex justify-between">
                                <span className="text-gray-500">Ad ID</span>
                                <span className="font-mono text-gray-800">{successResult.adId}</span>
                            </div>
                        )}
                        <div className="flex justify-between">
                            <span className="text-gray-500">Ad Set</span>
                            <span className="font-medium text-gray-800 truncate max-w-[200px]">{successResult.adsetName}</span>
                        </div>
                        <div className="flex justify-between">
                            <span className="text-gray-500">Status</span>
                            <span className="text-amber-700 font-medium">Paused (review in Ads Manager)</span>
                        </div>
                    </div>
                    <div className="flex gap-3">
                        <button
                            onClick={onClose}
                            className="flex-1 px-4 py-3 bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200 font-medium"
                        >
                            Close
                        </button>
                        <a
                            href={adsManagerUrl}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="flex-1 px-4 py-3 bg-green-600 text-white rounded-lg hover:bg-green-700 font-medium flex items-center justify-center gap-2"
                        >
                            <ExternalLink size={16} />
                            View in Ads Manager
                        </a>
                    </div>
                </div>
            </div>
        );
    }

    return (
        <div
            className="fixed inset-0 bg-black/50 backdrop-blur-sm z-[60] flex items-center justify-center p-4"
            onClick={onClose}
        >
            <div
                className="bg-white rounded-2xl shadow-2xl max-w-lg w-full p-6 max-h-[90vh] overflow-y-auto"
                onClick={(e) => e.stopPropagation()}
            >
                <div className="flex items-center justify-between mb-4">
                    <h3 className="text-xl font-bold text-gray-900">Push Ad to Facebook Campaign</h3>
                    <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
                        <X size={20} />
                    </button>
                </div>

                <div className="space-y-4">
                    {/* Ad Account ID */}
                    <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">Ad Account ID *</label>
                        <input
                            type="text"
                            placeholder="act_123456789"
                            value={pushForm.adAccountId}
                            onChange={(e) => {
                                setPushForm(p => ({ ...p, adAccountId: e.target.value, campaignId: '', adsetId: '' }));
                                setPushCampaigns([]);
                                setPushAdSets([]);
                            }}
                            onBlur={() => {
                                loadPushCampaigns(pushForm.adAccountId);
                                loadPushPages(pushForm.adAccountId);
                            }}
                            className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-green-500"
                        />
                    </div>

                    {/* Campaign */}
                    <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">Campaign *</label>
                        <select
                            value={pushForm.campaignId}
                            onChange={(e) => {
                                setPushForm(p => ({ ...p, campaignId: e.target.value, adsetId: '' }));
                                loadPushAdSets(e.target.value);
                            }}
                            className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-green-500"
                            disabled={pushCampaigns.length === 0}
                        >
                            <option value="">
                                {pushLoading ? 'Loading...' : pushCampaigns.length === 0 ? 'Enter Ad Account ID first' : 'Select a campaign...'}
                            </option>
                            {pushCampaigns.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
                        </select>
                    </div>

                    {/* Ad Set */}
                    <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">Ad Set *</label>
                        <select
                            value={pushForm.adsetId}
                            onChange={(e) => setPushForm(p => ({ ...p, adsetId: e.target.value }))}
                            className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-green-500"
                            disabled={pushAdSets.length === 0}
                        >
                            <option value="">{pushAdSets.length === 0 ? 'Select a campaign first' : 'Select an ad set...'}</option>
                            {pushAdSets.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
                        </select>
                    </div>

                    {/* Facebook Page */}
                    <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">Facebook Page *</label>
                        {pushPages.length > 0 ? (
                            <select
                                value={pushForm.pageId}
                                onChange={(e) => setPushForm(p => ({ ...p, pageId: e.target.value }))}
                                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-green-500"
                            >
                                <option value="">Select a page...</option>
                                {pushPages.map(pg => <option key={pg.id} value={pg.id}>{pg.name}</option>)}
                            </select>
                        ) : (
                            <input
                                type="text"
                                placeholder="e.g. 123456789"
                                value={pushForm.pageId}
                                onChange={(e) => setPushForm(p => ({ ...p, pageId: e.target.value }))}
                                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-green-500"
                            />
                        )}
                    </div>

                    {/* Website URL */}
                    <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">Destination URL *</label>
                        <input
                            type="url"
                            placeholder="https://yoursite.com/landing-page"
                            value={pushForm.websiteUrl}
                            onChange={(e) => setPushForm(p => ({ ...p, websiteUrl: e.target.value }))}
                            className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-green-500"
                        />
                    </div>

                    {/* Headline */}
                    <div>
                        <div className="flex items-center justify-between mb-1">
                            <label className="block text-sm font-medium text-gray-700">Headline</label>
                            <span className={`text-xs ${countColor(pushForm.headline.length, HEADLINE_LIMIT)}`}>
                                {pushForm.headline.length}/{HEADLINE_LIMIT}
                            </span>
                        </div>
                        <input
                            type="text"
                            value={pushForm.headline}
                            onChange={(e) => setPushForm(p => ({ ...p, headline: e.target.value }))}
                            className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-green-500"
                        />
                        {pushForm.headline.length > HEADLINE_LIMIT && (
                            <p className="text-xs text-red-600 mt-1">Meta truncates headlines after {HEADLINE_LIMIT} characters</p>
                        )}
                    </div>

                    {/* Body */}
                    <div>
                        <div className="flex items-center justify-between mb-1">
                            <label className="block text-sm font-medium text-gray-700">Body Copy</label>
                            <span className={`text-xs ${countColor(pushForm.body.length, BODY_LIMIT)}`}>
                                {pushForm.body.length}/{BODY_LIMIT}
                            </span>
                        </div>
                        <textarea
                            rows={3}
                            value={pushForm.body}
                            onChange={(e) => setPushForm(p => ({ ...p, body: e.target.value }))}
                            className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-green-500"
                        />
                        {pushForm.body.length > BODY_LIMIT && (
                            <p className="text-xs text-amber-600 mt-1">Body over {BODY_LIMIT} chars will show a "See More" link on mobile</p>
                        )}
                    </div>

                    {/* CTA */}
                    <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">Call to Action</label>
                        <select
                            value={pushForm.cta}
                            onChange={(e) => setPushForm(p => ({ ...p, cta: e.target.value }))}
                            className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-green-500"
                        >
                            {['LEARN_MORE', 'SHOP_NOW', 'SIGN_UP', 'CONTACT_US', 'DOWNLOAD', 'BOOK_NOW', 'GET_QUOTE'].map(c =>
                                <option key={c} value={c}>{c.replace(/_/g, ' ')}</option>
                            )}
                        </select>
                    </div>
                </div>

                <div className="flex gap-3 mt-6">
                    <button
                        onClick={onClose}
                        className="flex-1 px-4 py-3 bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200 font-medium"
                    >
                        Cancel
                    </button>
                    <button
                        onClick={handlePushToFacebook}
                        disabled={pushSubmitting}
                        className="flex-1 px-4 py-3 bg-green-600 text-white rounded-lg hover:bg-green-700 font-medium flex items-center justify-center gap-2 disabled:bg-gray-300 disabled:cursor-not-allowed"
                    >
                        {pushSubmitting
                            ? <><Loader className="animate-spin" size={18} /> Pushing...</>
                            : <><Rocket size={18} /> Push Live</>
                        }
                    </button>
                </div>
            </div>
        </div>
    );
}
