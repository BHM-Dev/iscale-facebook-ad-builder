import React, { useState, useEffect, useRef, useCallback } from 'react';
import { ChevronRight, ChevronLeft, Sparkles, Check, Image, FileText, Briefcase, Package, Users, Zap, Copy, CheckCircle, Upload, RefreshCw, TrendingUp, ExternalLink, X, Globe } from 'lucide-react';
import { useNavigate, Link } from 'react-router-dom';
import { useBrands } from '../context/BrandContext';
import { useToast } from '../context/ToastContext';
import { useAuth } from '../context/AuthContext';
import BrandSelectionStep from '../components/steps/BrandSelectionStep';
import ProductSelectionStep from '../components/steps/ProductSelectionStep';
import ProfileSelectionStep from '../components/steps/ProfileSelectionStep';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1';

export default function AdRemix() {
    const { brands, customerProfiles } = useBrands();
    const { showError, showSuccess } = useToast();
    const { authFetch } = useAuth();
    const navigate = useNavigate();
    const [currentStep, setCurrentStep] = useState(1);
    const [loading, setLoading] = useState(false);
    const [blueprint, setBlueprint] = useState(null);
    const [adConcept, setAdConcept] = useState(null);       // single concept (legacy)
    const [adConcepts, setAdConcepts] = useState([]);        // 3 parallel variations
    const [prefillSource, setPrefillSource] = useState(null); // winning ad data from performance page
    const [pendingBrandId, setPendingBrandId] = useState(null); // brand_id from drawer — resolved once brands load
    const [pendingNiche, setPendingNiche] = useState('');       // niche from ad set name, passed through to Batch Generate
    const [remixFbCampaignId, setRemixFbCampaignId] = useState(''); // Meta campaign ID from source ad — for push modal pre-selection
    const [remixFbAdsetId, setRemixFbAdsetId] = useState('');       // Meta adset ID from source ad
    const [remixLinkUrl, setRemixLinkUrl] = useState('');            // destination URL from source ad — pre-fills push modal
    const [copied, setCopied] = useState(false);
    const [uploadingRef, setUploadingRef] = useState(false);
    const [refPreview, setRefPreview] = useState('');
    const fileInputRef = useRef(null);
    // Push to Meta modal state
    const [pushModal, setPushModal] = useState(null);    // null | concept object
    const [pushForm, setPushForm] = useState({ adset_id: '', page_id: '', website_url: '', lead_form_id: '', image_url: '', status: 'PAUSED' });
    const [pushLoading, setPushLoading] = useState(false);
    const [pushResult, setPushResult] = useState(null);
    const [adSets, setAdSets] = useState([]);
    const [pages, setPages] = useState([]);
    const [adSetsLoading, setAdSetsLoading] = useState(false);
    const [adSetsError, setAdSetsError] = useState('');
    const [imageGenerating, setImageGenerating] = useState(false);
    const [leadForms, setLeadForms] = useState([]);
    const [leadFormsLoading, setLeadFormsLoading] = useState(false);
    // Suppresses auto-advance effects for one render cycle when the user presses Back,
    // preventing the profile/product auto-skip from immediately re-triggering.
    const skipAutoAdvance = useRef(false);

    const [wizardData, setWizardData] = useState({
        template: null,
        brand: null,
        product: null,
        profile: null,
        campaignDetails: {
            offer: '',
            urgency: '',
            messaging: ''
        }
    });

    // On mount: restore result if returning from Batch Generate
    useEffect(() => {
        const saved = localStorage.getItem('remixResult');
        if (saved) {
            try {
                const concepts = JSON.parse(saved);
                setAdConcepts(concepts);
                setAdConcept(concepts[0]);
                setCurrentStep(7);
                localStorage.removeItem('remixResult');
            } catch (e) { /* ignore */ }
        }
    }, []);

    // On mount: check for a winning ad passed in from the performance page
    useEffect(() => {
        const raw = localStorage.getItem('pendingRemixCreative');
        if (!raw) return;
        try {
            const creative = JSON.parse(raw);
            localStorage.removeItem('pendingRemixCreative');
            setPrefillSource(creative);
            // Carry niche through from the ad set name (parsed upstream in RemixDrawer)
            if (creative.niche) setPendingNiche(creative.niche);
            // Carry campaign / adset context and destination URL for the push modal
            if (creative.fb_campaign_id) setRemixFbCampaignId(creative.fb_campaign_id);
            if (creative.fb_adset_id) setRemixFbAdsetId(creative.fb_adset_id);
            if (creative.link_url) setRemixLinkUrl(creative.link_url);
            // Pre-populate wizard: use the winning ad image as the template source
            setWizardData(prev => ({
                ...prev,
                template: {
                    id: null,
                    name: creative.ad_name || 'Winning Ad',
                    image_url: creative.image_url || null,
                    fromMeta: true,
                },
                campaignDetails: {
                    offer: creative.headline || '',
                    urgency: '',
                    messaging: creative.body || '',
                },
            }));
            if (creative.brand_id) {
                // Brand is already known from the drawer — store the ID and resolve
                // it to a full brand object once the brands list loads (see effect below).
                setPendingBrandId(creative.brand_id);
                // Jump to Product step (3); the brand effect below will set the brand object.
                setCurrentStep(3);
            } else {
                // No brand pre-assigned — stop at Brand step so Joel can pick one.
                setCurrentStep(2);
            }
        } catch (e) {
            // malformed localStorage — ignore
        }
    }, []);

    // Resolve pendingBrandId → full brand object once the brands list is available.
    // Also auto-selects the product if the brand only has one, skipping to Profile.
    useEffect(() => {
        if (!pendingBrandId || !brands || brands.length === 0) return;
        const brand = brands.find(b => b.id === pendingBrandId);
        if (!brand) return;
        setPendingBrandId(null);

        const products = brand.products || [];
        if (products.length === 1) {
            // Only one product — auto-select it and jump straight to Profile.
            setWizardData(prev => ({ ...prev, brand, product: products[0] }));
            setCurrentStep(4); // profile auto-skip effect will fire from here
        } else {
            // Multiple products — stop at Product step for Joel to choose.
            setWizardData(prev => ({ ...prev, brand }));
            // currentStep is already 3 (set in mount effect)
        }
    }, [pendingBrandId, brands]);

    // Auto-skip Profile step when the selected brand has exactly one linked profile.
    // Uses brandId (primitive) as dep to avoid re-running on every wizardData change.
    // Guarded by skipAutoAdvance so pressing Back from Campaign doesn't loop back.
    const brandId = wizardData.brand?.id;
    useEffect(() => {
        if (currentStep !== 4 || !brandId || !customerProfiles.length) return;
        if (skipAutoAdvance.current) {
            skipAutoAdvance.current = false; // consume the flag and stay on this step
            return;
        }
        const brand = brands.find(b => b.id === brandId);
        if (!brand) return;
        const brandProfiles = customerProfiles.filter(p =>
            brand.profileIds?.includes(p.id)
        );
        if (brandProfiles.length === 1) {
            // Only one profile for this brand — auto-select and go to Campaign.
            setWizardData(prev => ({ ...prev, profile: brandProfiles[0] }));
            setCurrentStep(5);
        }
    }, [currentStep, brandId, customerProfiles, brands]);

    const steps = [
        { id: 1, name: 'Template', icon: Image },
        { id: 2, name: 'Brand', icon: Briefcase },
        { id: 3, name: 'Product', icon: Package },
        { id: 4, name: 'Profile', icon: Users },
        { id: 5, name: 'Campaign', icon: FileText },
        { id: 6, name: 'Generate', icon: Sparkles },
        { id: 7, name: 'Results', icon: CheckCircle },
    ];

    // Persist push modal form selections (except image_url which expires) across modal opens.
    // page_id also goes to localStorage so it survives across sessions (saves Joel from picking it every time).
    useEffect(() => {
        if (!pushModal) return; // only persist while modal is open
        const { image_url: _ignored, ...toSave } = pushForm;
        try { sessionStorage.setItem('pushModalForm', JSON.stringify(toSave)); } catch (_) {}
        if (pushForm.page_id) {
            try { localStorage.setItem('lastUsedPageId', pushForm.page_id); } catch (_) {}
        }
    }, [pushForm, pushModal]);

    const updateData = (field, value) => {
        setWizardData(prev => ({ ...prev, [field]: value }));
    };

    const updateCampaignDetails = (field, value) => {
        setWizardData(prev => ({
            ...prev,
            campaignDetails: { ...prev.campaignDetails, [field]: value }
        }));
    };

    // Reset all state cleanly (instead of window.location.reload())
    const handleReset = () => {
        resetPushModal();
        setCurrentStep(1);
        setBlueprint(null);
        setAdConcept(null);
        setAdConcepts([]);
        setPrefillSource(null);
        setCopied(false);
        localStorage.removeItem('remixResult');
        setWizardData({
            template: null,
            brand: null,
            product: null,
            profile: null,
            campaignDetails: { offer: '', urgency: '', messaging: '' }
        });
    };

    // Copy all ad copy to clipboard
    const handleCopyAll = () => {
        if (!adConcept) return;
        const text = [
            `Headline: ${adConcept.headline_remix}`,
            '',
            `Body Copy:\n${adConcept.body_copy}`,
            '',
            `CTA: ${adConcept.cta_button}`,
        ].join('\n');
        navigator.clipboard.writeText(text).then(() => {
            setCopied(true);
            showSuccess('Copy pasted to clipboard');
            setTimeout(() => setCopied(false), 2500);
        });
    };

    // Upload a reference image directly on Step 1
    const handleRefUpload = useCallback(async (file) => {
        if (!file || !file.type.startsWith('image/')) {
            showError('Please upload an image file (JPG, PNG, WebP)');
            return;
        }
        setUploadingRef(true);
        setRefPreview(URL.createObjectURL(file));
        try {
            const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1';
            const formData = new FormData();
            formData.append('file', file);
            const res = await authFetch(`${API_URL}/uploads/`, { method: 'POST', body: formData });
            if (!res.ok) throw new Error('Upload failed');
            const data = await res.json();
            const url = data.url || data.file_url || data.path;
            const absUrl = url.startsWith('http') ? url : `${window.location.origin}${url}`;
            updateData('template', {
                id: null,
                name: file.name,
                image_url: absUrl,
                fromMeta: true,
            });
            setCurrentStep(2);
        } catch (e) {
            showError(`Upload failed: ${e.message}`);
            setRefPreview('');
        } finally {
            setUploadingRef(false);
        }
    }, [authFetch, showError, updateData]);

    // Send remix copy to Batch Generate — passes ALL remix variants so each
    // shows up as a separate variant in the Batch Generator.
    const handleGenerateImage = (concept) => {
        const target = concept || adConcept;
        if (!target) return;
        // Save all variations so the user can return to the result screen
        const allConcepts = adConcepts.length ? adConcepts : [target];
        localStorage.setItem('remixResult', JSON.stringify(allConcepts));
        // Pass full array — BatchGenerate will create one variant per concept
        localStorage.setItem('pendingBatchCopy', JSON.stringify(
            allConcepts.map(c => ({
                headline: c.headline_remix || '',
                body: c.body_copy || '',
                cta: c.cta_button || 'Get My Quote',
            }))
        ));
        // Carry niche through so BatchGenerate auto-populates the Niche/Context field
        if (pendingNiche) localStorage.setItem('pendingBatchNiche', pendingNiche);
        navigate('/batch-generate');
    };

    // Shared reset for push modal state — used by Done, Cancel, X, and handleReset
    const resetPushModal = () => {
        setPushModal(null);
        setPushResult(null);
        setPushForm({ adset_id: '', page_id: '', website_url: '', lead_form_id: '', image_url: '', status: 'PAUSED' });
        setAdSets([]);
        setPages([]);
        setLeadForms([]);
        setLeadFormsLoading(false);
        setAdSetsError('');
        setImageGenerating(false);
    };

    // Open the Push to Meta modal for a specific concept
    const openPushModal = async (concept) => {
        setPushModal(concept);
        setPushResult(null);
        setAdSetsError('');
        // Restore persisted selections from previous modal opens (adset, page, form, url, status)
        // Never restore image_url — Meta CDN URLs expire within hours
        let savedForm = {};
        try {
            const saved = sessionStorage.getItem('pushModalForm');
            if (saved) savedForm = JSON.parse(saved);
        } catch (_) {}
        const lastPageId = localStorage.getItem('lastUsedPageId') || '';
        setPushForm({
            adset_id: savedForm.adset_id || '',
            // sessionStorage has same-session preference; fall back to localStorage for cross-session persistence
            page_id: savedForm.page_id || lastPageId,
            // Pre-fill URL from source ad (so Joel doesn't need to type it),
            // falling back to any previously entered URL from this session.
            website_url: savedForm.website_url || remixLinkUrl || '',
            lead_form_id: savedForm.lead_form_id || '',
            image_url: '',
            status: savedForm.status || 'PAUSED',
        });
        setAdSets([]);
        setPages([]);
        setAdSetsLoading(true);
        try {
            const [adSetsRes, pagesRes] = await Promise.all([
                authFetch(`${API_URL}/facebook/adsets`),
                authFetch(`${API_URL}/facebook/pages`),
            ]);
            // Surface HTTP errors explicitly — don't swallow them
            if (!adSetsRes.ok) {
                const err = await adSetsRes.json().catch(() => ({}));
                throw new Error(`Ad sets failed (${adSetsRes.status}): ${err.detail || adSetsRes.statusText}`);
            }
            if (!pagesRes.ok) {
                const err = await pagesRes.json().catch(() => ({}));
                throw new Error(`Pages failed (${pagesRes.status}): ${err.detail || pagesRes.statusText}`);
            }
            const adSetsData = await adSetsRes.json();
            const loadedAdSets = Array.isArray(adSetsData) ? adSetsData : (adSetsData.adsets || []);
            setAdSets(loadedAdSets);
            const pagesData = await pagesRes.json();
            setPages(Array.isArray(pagesData) ? pagesData : []);

            // Auto-select the source adset when coming from Campaign Performance "Remix" flow.
            // If the user already made a selection this session, keep it.
            if (!savedForm.adset_id && remixFbAdsetId && loadedAdSets.length > 0) {
                const byFbId = loadedAdSets.find(a => a.id === remixFbAdsetId || a.fb_adset_id === remixFbAdsetId);
                if (byFbId) {
                    setPushForm(f => ({ ...f, adset_id: byFbId.id }));
                }
            }

            // If the restored adset is a lead gen campaign and we have a page, fetch lead forms
            if (savedForm.adset_id && savedForm.page_id) {
                const restoredAdset = loadedAdSets.find(a => a.id === savedForm.adset_id);
                if (restoredAdset?.campaign?.objective === 'OUTCOME_LEADS') {
                    fetchLeadForms(savedForm.page_id);
                }
            }
        } catch (e) {
            setAdSetsError(e.message || 'Failed to load Meta data — check your access token');
        } finally {
            setAdSetsLoading(false);
        }
    };

    // Generate image inline from the modal using the concept's image_generation_prompt
    const handleGenerateImageInline = async () => {
        if (!pushModal?.image_generation_prompt) return;
        setImageGenerating(true);
        try {
            // Use the winning ad's image as a reference (iterate mode) when available.
            // kie.ai will preserve the scene and adjust lighting/mood only.
            // Falls back to text-to-image if no reference image exists.
            const referenceImageUrl = wizardData.template?.image_url || null;
            const payload = {
                customPrompt: pushModal.image_generation_prompt,
                count: 1,
                imageSizes: [{ width: 1080, height: 1080, name: 'Square' }],
                niche: wizardData.offer?.niche || '',
                imageMode: 'iterate',
                ...(referenceImageUrl && {
                    useProductImage: true,
                    productShots: [referenceImageUrl],
                }),
            };
            const res = await authFetch(`${API_URL}/generated-ads/generate-image`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || 'Image generation failed');
            }
            const data = await res.json();
            const url = data.images?.[0]?.url;
            if (!url) throw new Error('No image URL returned');
            setPushForm(f => ({ ...f, image_url: url }));
        } catch (e) {
            showError(`Image generation failed: ${e.message}`);
        } finally {
            setImageGenerating(false);
        }
    };

    // Submit the Push to Meta form
    const handlePushToMeta = async () => {
        if (!pushModal) return;
        setPushLoading(true);
        try {
            const res = await authFetch(`${API_URL}/facebook/push-to-meta`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    adset_id: pushForm.adset_id,
                    page_id: pushForm.page_id,
                    website_url: pushForm.website_url || '',
                    lead_form_id: pushForm.lead_form_id || '',
                    image_url: pushForm.image_url,
                    headline: pushModal.headline_remix,
                    body_copy: pushModal.body_copy,
                    cta_button: pushModal.cta_button,
                    status: pushForm.status,
                }),
            });
            if (!res.ok) {
                const err = await res.json();
                throw new Error(err.detail || 'Push failed');
            }
            const result = await res.json();
            setPushResult(result);
        } catch (e) {
            showError(`Push to Meta failed: ${e.message}`);
        } finally {
            setPushLoading(false);
        }
    };

    // Fetch lead gen forms for a page — called when an OUTCOME_LEADS ad set is selected
    const fetchLeadForms = async (pageId) => {
        if (!pageId) return;
        setLeadFormsLoading(true);
        setLeadForms([]);
        try {
            const res = await authFetch(`${API_URL}/facebook/lead-forms?page_id=${pageId}`);
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || `${res.status}`);
            }
            const data = await res.json();
            setLeadForms(Array.isArray(data) ? data : []);
        } catch (e) {
            showError(`Failed to load lead forms: ${e.message}`);
        } finally {
            setLeadFormsLoading(false);
        }
    };

    const handleDeconstruct = async () => {
        setLoading(true);
        try {
            const response = await authFetch(`${API_URL}/ad-remix/deconstruct`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ template_id: wizardData.template.id })
            });

            if (!response.ok) throw new Error('Deconstruction failed');

            const data = await response.json();
            setBlueprint(data);
        } catch (error) {
            console.error('Deconstruction error:', error);
            showError('Failed to deconstruct template. Please try again.');
        } finally {
            setLoading(false);
        }
    };

    const handleReconstruct = async () => {
        setLoading(true);
        try {
            const isMetaSource = wizardData.template?.fromMeta;
            const endpoint = isMetaSource
                ? `${API_URL}/ad-remix/reconstruct-from-url`
                : `${API_URL}/ad-remix/reconstruct`;

            const payload = isMetaSource
                ? {
                    source_image_url: wizardData.template.image_url,
                    brand_id: wizardData.brand.id,
                    product_id: wizardData.product.id,
                    profile_id: wizardData.profile.id,
                    campaign_offer: wizardData.campaignDetails.offer,
                    campaign_urgency: wizardData.campaignDetails.urgency,
                    campaign_messaging: wizardData.campaignDetails.messaging,
                    niche: pendingNiche || ""
                }
                : {
                    template_id: wizardData.template.id,
                    brand_id: wizardData.brand.id,
                    product_id: wizardData.product.id,
                    profile_id: wizardData.profile.id,
                    campaign_offer: wizardData.campaignDetails.offer,
                    campaign_urgency: wizardData.campaignDetails.urgency,
                    campaign_messaging: wizardData.campaignDetails.messaging,
                    niche: pendingNiche || ""
                };

            // Advance to step 6 (Generating) before firing requests
            setCurrentStep(6);

            // Fire 3 parallel requests — Gemini returns different variations each time
            const fetchOne = () => authFetch(endpoint, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            }).then(async r => {
                if (!r.ok) {
                    const err = await r.json().catch(() => ({}));
                    throw new Error(err.detail || 'Reconstruction failed');
                }
                return r.json();
            });

            const results = await Promise.allSettled([fetchOne(), fetchOne(), fetchOne()]);
            const successful = results
                .filter(r => r.status === 'fulfilled')
                .map(r => r.value);

            if (successful.length === 0) {
                const firstErr = results.find(r => r.status === 'rejected');
                throw new Error(firstErr?.reason?.message || 'All variations failed');
            }

            setAdConcepts(successful);
            setAdConcept(successful[0]);
            setCurrentStep(7);
        } catch (error) {
            console.error('Reconstruction error:', error);
            showError(error.message || 'Failed to reconstruct ad. Please try again.');
        } finally {
            setLoading(false);
        }
    };

    return (
        <>
        <div className="max-w-5xl mx-auto">
            {/* Header */}
            <div className="mb-8">
                <h1 className="text-3xl font-bold text-gray-900 flex items-center gap-3">
                    <Sparkles size={32} className="text-purple-600" />
                    Ad Remix Engine
                </h1>
                <p className="text-gray-600 mt-1">Deconstruct winning ads and reconstruct them with your brand</p>
            </div>

            {/* Progress Steps */}
            <div className="mb-8 bg-white rounded-xl shadow-sm border border-gray-200 p-6">
                <div className="flex items-center justify-between relative">
                    <div className="absolute left-0 top-1/2 transform -translate-y-1/2 w-full h-1 bg-gray-200 -z-10"></div>
                    {steps.map((step) => {
                        const Icon = step.icon;
                        const isActive = step.id === currentStep;
                        const isCompleted = step.id < currentStep;

                        return (
                            <div
                                key={step.id}
                                className="flex flex-col items-center bg-white px-2"
                            >
                                <div
                                    className={`w-10 h-10 rounded-full flex items-center justify-center mb-2 transition-all ${isActive ? 'bg-purple-600 text-white scale-110 shadow-md' :
                                        isCompleted ? 'bg-green-500 text-white' :
                                            'bg-gray-200 text-gray-500'
                                        }`}
                                >
                                    {isCompleted ? <Check size={20} /> : <Icon size={20} />}
                                </div>
                                <span className={`text-xs font-medium ${isActive ? 'text-purple-600' : 'text-gray-500'}`}>
                                    {step.name}
                                </span>
                            </div>
                        );
                    })}</div>
            </div>

            {/* Prefill banner — shown when launched from a winning ad */}
            {prefillSource && (
                <div className="mb-4 flex items-start gap-3 bg-purple-50 border border-purple-200 rounded-xl px-4 py-3 text-sm">
                    <Zap size={16} className="text-purple-600 mt-0.5 flex-shrink-0" />
                    <div>
                        <span className="font-semibold text-purple-800">Remixing winner: </span>
                        <span className="text-purple-700">{prefillSource.ad_name}</span>
                        <p className="text-purple-600 text-xs mt-0.5">Headline and body pre-filled from the live ad. Select your brand and audience to generate variations.</p>
                    </div>
                </div>
            )}

            {/* Step Content */}
            <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-8 min-h-[500px]">
                {loading && (
                    <div className="absolute inset-0 bg-white/80 backdrop-blur-sm z-50 flex flex-col items-center justify-center rounded-xl">
                        <div className="w-16 h-16 border-4 border-purple-200 border-t-purple-600 rounded-full animate-spin mb-4"></div>
                        <h3 className="text-xl font-bold text-gray-900">
                            {currentStep === 1 ? 'Analyzing Template Structure...' : 'Generating Your Ad Concept...'}
                        </h3>
                    </div>
                )}

                {/* Step 1: Choose starting point */}
                {currentStep === 1 && (
                    <div>
                        <h3 className="text-xl font-bold mb-2">How do you want to start?</h3>
                        <p className="text-gray-500 mb-8">Pick a starting point — Ad Remix will build a new creative concept from it using your brand and audience.</p>

                        <div className="grid grid-cols-1 md:grid-cols-2 gap-5 max-w-2xl">
                            {/* Path A: From a live winning ad */}
                            <Link
                                to="/campaign-performance"
                                className="group flex flex-col gap-4 p-6 rounded-xl border-2 border-gray-200 hover:border-purple-400 hover:bg-purple-50/40 transition-all cursor-pointer"
                            >
                                <div className="w-12 h-12 rounded-xl bg-purple-100 flex items-center justify-center">
                                    <TrendingUp size={22} className="text-purple-600" />
                                </div>
                                <div>
                                    <div className="font-bold text-gray-900 mb-1">Start from a live ad</div>
                                    <p className="text-sm text-gray-500 leading-snug">Go to Campaign Performance, find a winning or underperforming ad, and hit Remix. The creative is pre-loaded automatically.</p>
                                </div>
                                <div className="mt-auto flex items-center gap-1 text-xs font-medium text-purple-600 group-hover:gap-2 transition-all">
                                    Go to Campaign Performance <ChevronRight size={13} />
                                </div>
                            </Link>

                            {/* Path B: Upload reference image */}
                            <div
                                onClick={() => !uploadingRef && fileInputRef.current?.click()}
                                className="group flex flex-col gap-4 p-6 rounded-xl border-2 border-dashed border-gray-200 hover:border-purple-400 hover:bg-purple-50/40 transition-all cursor-pointer"
                            >
                                <div className="w-12 h-12 rounded-xl bg-gray-100 flex items-center justify-center">
                                    {uploadingRef
                                        ? <RefreshCw size={22} className="text-indigo-500 animate-spin" />
                                        : refPreview
                                            ? <img src={refPreview} alt="" className="w-12 h-12 object-cover rounded-xl" />
                                            : <Upload size={22} className="text-gray-400" />
                                    }
                                </div>
                                <div>
                                    <div className="font-bold text-gray-900 mb-1">Upload a reference image</div>
                                    <p className="text-sm text-gray-500 leading-snug">Upload any ad creative — a competitor's ad, a screenshot, a mockup — and remix it with your brand.</p>
                                </div>
                                <div className="mt-auto flex items-center gap-1 text-xs font-medium text-gray-500 group-hover:text-purple-600 transition-colors">
                                    {uploadingRef ? 'Uploading…' : 'Click to upload'} <ChevronRight size={13} />
                                </div>
                                <input
                                    ref={fileInputRef}
                                    type="file"
                                    accept="image/jpeg,image/png,image/webp"
                                    className="hidden"
                                    onChange={(e) => { const f = e.target.files?.[0]; if (f) handleRefUpload(f); }}
                                />
                            </div>
                        </div>
                    </div>
                )}

                {/* Step 2: Brand Selection */}
                {currentStep === 2 && (
                    <BrandSelectionStep
                        brands={brands}
                        selectedBrand={wizardData.brand}
                        onSelect={(brand) => {
                            updateData('brand', brand);
                            setCurrentStep(3);
                        }}
                    />
                )}

                {/* Step 3: Product Selection */}
                {currentStep === 3 && (
                    <ProductSelectionStep
                        products={wizardData.brand?.products || []}
                        selectedProduct={wizardData.product}
                        useProductShots={false}
                        onSelect={(product) => {
                            updateData('product', product);
                            setCurrentStep(4);
                        }}
                        onToggleProductShots={() => { }}
                    />
                )}

                {/* Step 4: Profile Selection */}
                {currentStep === 4 && (
                    <ProfileSelectionStep
                        profiles={customerProfiles.filter(p => wizardData.brand?.profileIds?.includes(p.id))}
                        selectedProfile={wizardData.profile}
                        onSelect={(profile) => {
                            updateData('profile', profile);
                            setCurrentStep(5);
                        }}
                    />
                )}

                {/* Step 5: Campaign Details */}
                {currentStep === 5 && (
                    <div>
                        <h3 className="text-xl font-bold mb-2">Campaign Details</h3>
                        <p className="text-gray-600 mb-4">
                            {prefillSource
                                ? 'Pre-filled from your winning ad — adjust the angle or keep as-is to generate variations.'
                                : 'Provide details to customize your remixed ad'}
                        </p>

                        {prefillSource && (
                            <div className="mb-5 p-3 bg-purple-50 border border-purple-200 rounded-lg text-xs text-purple-700">
                                <span className="font-semibold">Source ad:</span> {prefillSource.ad_name} — edit the fields below to remix with a new angle, or leave them to generate copy variations on the same hook.
                            </div>
                        )}

                        <div className="max-w-2xl space-y-4">
                            <div>
                                <label className="block text-sm font-medium text-gray-700 mb-2">
                                    Offer / Hook *
                                    {prefillSource && wizardData.campaignDetails.offer && (
                                        <span className="ml-2 text-xs font-normal text-purple-500">pre-filled from ad headline</span>
                                    )}
                                </label>
                                <input
                                    type="text"
                                    value={wizardData.campaignDetails.offer}
                                    onChange={(e) => updateCampaignDetails('offer', e.target.value)}
                                    placeholder="e.g., Get a free quote in 60 seconds, See if you qualify for lower rates"
                                    className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-purple-600 focus:border-transparent"
                                />
                            </div>

                            <div>
                                <label className="block text-sm font-medium text-gray-700 mb-2">
                                    Urgency / Timing
                                    <span className="ml-2 text-xs font-normal text-gray-400">optional</span>
                                </label>
                                <input
                                    type="text"
                                    value={wizardData.campaignDetails.urgency}
                                    onChange={(e) => updateCampaignDetails('urgency', e.target.value)}
                                    placeholder="e.g., Rates change daily, Limited spots this week"
                                    className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-purple-600 focus:border-transparent"
                                />
                            </div>

                            <div>
                                <label className="block text-sm font-medium text-gray-700 mb-2">
                                    Key Messaging *
                                    {prefillSource && wizardData.campaignDetails.messaging && (
                                        <span className="ml-2 text-xs font-normal text-purple-500">pre-filled from ad body</span>
                                    )}
                                </label>
                                <textarea
                                    value={wizardData.campaignDetails.messaging}
                                    onChange={(e) => updateCampaignDetails('messaging', e.target.value)}
                                    placeholder="e.g., Compare top carriers in minutes — no obligation, 100% free"
                                    rows={3}
                                    className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-purple-600 focus:border-transparent"
                                />
                            </div>
                        </div>
                    </div>
                )}

                {/* Step 7: Results */}
                {currentStep === 7 && adConcepts.length > 0 && (
                    <div>
                        <div className="text-center mb-8">
                            <div className="w-20 h-20 bg-green-100 text-green-600 rounded-full flex items-center justify-center mx-auto mb-4">
                                <Check size={40} />
                            </div>
                            <h2 className="text-3xl font-bold text-gray-900 mb-2">
                                {adConcepts.length} Remix Variation{adConcepts.length > 1 ? 's' : ''} Generated
                            </h2>
                            <p className="text-gray-600">Pick the concept you want to build into an image</p>
                        </div>

                        <div className="space-y-8">
                            {adConcepts.map((concept, idx) => (
                                <div key={idx} className="border-2 border-gray-200 rounded-xl overflow-hidden">
                                    {/* Variation header */}
                                    <div className="flex items-center justify-between px-6 py-3 bg-gray-50 border-b border-gray-200">
                                        <span className="font-bold text-gray-700">Variation {idx + 1}</span>
                                        <div className="flex gap-2">
                                            <button
                                                onClick={() => {
                                                    const text = [
                                                        `Headline: ${concept.headline_remix}`,
                                                        `Body: ${concept.body_copy}`,
                                                        `CTA: ${concept.cta_button}`,
                                                    ].join('\n\n');
                                                    navigator.clipboard.writeText(text);
                                                }}
                                                className="flex items-center gap-1 px-3 py-1.5 rounded-lg border border-gray-200 text-xs font-medium text-gray-700 bg-white hover:bg-gray-50"
                                            >
                                                <Copy size={13} />
                                                Copy
                                            </button>
                                            <button
                                                onClick={() => handleGenerateImage(concept)}
                                                className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-semibold text-white hover:opacity-90"
                                                style={{ backgroundColor: '#2D2463' }}
                                            >
                                                <Zap size={13} />
                                                Batch Generate
                                            </button>
                                            <button
                                                onClick={() => openPushModal(concept)}
                                                className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-semibold text-white bg-blue-600 hover:bg-blue-700"
                                            >
                                                <ExternalLink size={13} />
                                                Push to Meta
                                            </button>
                                        </div>
                                    </div>

                                    {/* Variation content */}
                                    <div className="p-6 space-y-4">
                                        <div className="bg-purple-50 border border-purple-200 rounded-lg p-4">
                                            <p className="text-xs font-semibold text-purple-700 uppercase tracking-wide mb-1">Headline</p>
                                            <p className="text-lg font-bold text-gray-900">{concept.headline_remix}</p>
                                        </div>
                                        <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
                                            <p className="text-xs font-semibold text-blue-700 uppercase tracking-wide mb-1">Body Copy</p>
                                            <p className="text-gray-700 whitespace-pre-line text-sm">{concept.body_copy}</p>
                                        </div>
                                        <div className="flex gap-4">
                                            <div className="bg-green-50 border border-green-200 rounded-lg p-4 flex-1">
                                                <p className="text-xs font-semibold text-green-700 uppercase tracking-wide mb-2">CTA</p>
                                                <span className="px-4 py-2 bg-green-600 text-white rounded-lg text-sm font-bold">{concept.cta_button}</span>
                                            </div>
                                            <div className="bg-amber-50 border border-amber-200 rounded-lg p-4 flex-[2]">
                                                <p className="text-xs font-semibold text-amber-700 uppercase tracking-wide mb-1">Visual Direction</p>
                                                <p className="text-gray-700 text-sm">{concept.visual_description}</p>
                                            </div>
                                        </div>
                                        <details className="bg-gray-50 border border-gray-200 rounded-lg">
                                            <summary className="px-4 py-2 text-xs font-semibold text-gray-600 cursor-pointer select-none">Image Generation Prompt</summary>
                                            <p className="px-4 pb-4 text-xs text-gray-700 font-mono">{concept.image_generation_prompt}</p>
                                        </details>
                                    </div>
                                </div>
                            ))}
                        </div>
                    </div>
                )}
            </div>

            {/* Navigation */}
            <div className="mt-6 flex items-center justify-between">
                <div></div>
                <div className="flex gap-3">
                    {/* Back button — available on all steps 2–7.
                        Sets skipAutoAdvance before decrementing so profile/product
                        auto-skip effects don't immediately re-trigger. */}
                    {currentStep > 1 && currentStep <= 7 && currentStep !== 6 && (
                        <button
                            onClick={() => {
                                skipAutoAdvance.current = true;
                                // From Results (7), go back to Campaign (5) to re-generate
                                setCurrentStep(currentStep === 7 ? 5 : currentStep - 1);
                            }}
                            className="flex items-center gap-2 px-6 py-3 bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200 font-medium"
                        >
                            <ChevronLeft size={20} />
                            {currentStep === 7 ? 'Edit & Re-generate' : 'Back'}
                        </button>
                    )}

                    {/* Next button — steps 2–4 */}
                    {currentStep >= 2 && currentStep <= 4 && (
                        <button
                            onClick={() => setCurrentStep(currentStep + 1)}
                            disabled={
                                (currentStep === 2 && !wizardData.brand) ||
                                (currentStep === 3 && !wizardData.product) ||
                                (currentStep === 4 && !wizardData.profile)
                            }
                            className="flex items-center gap-2 px-8 py-3 bg-purple-600 text-white rounded-lg hover:bg-purple-700 font-medium disabled:opacity-40 disabled:cursor-not-allowed"
                        >
                            Next
                            <ChevronRight size={20} />
                        </button>
                    )}

                    {/* Step 5 — Generate Remix directly (removed Review step) */}
                    {currentStep === 5 && (
                        <button
                            onClick={handleReconstruct}
                            disabled={!wizardData.brand || !wizardData.product || !wizardData.profile || !wizardData.campaignDetails.offer || !wizardData.campaignDetails.messaging}
                            className="flex items-center gap-2 px-8 py-3 bg-gradient-to-r from-purple-600 to-pink-600 text-white rounded-lg hover:from-purple-700 hover:to-pink-700 font-medium shadow-lg disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                            <Sparkles size={20} />
                            Generate Remix
                        </button>
                    )}

                    {currentStep === 7 && (
                        <button
                            onClick={handleReset}
                            className="px-6 py-3 bg-purple-600 text-white rounded-lg hover:bg-purple-700 font-medium"
                        >
                            Create Another Remix
                        </button>
                    )}
                </div>
            </div>
        </div>

        {/* ── Push to Meta Modal ───────────────────────────────────────── */}
        {pushModal && (
            <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4">
                <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg max-h-[90vh] overflow-y-auto">
                    {pushResult ? (
                        /* Success screen */
                        <div className="p-8 text-center">
                            <div className="w-16 h-16 bg-green-100 text-green-600 rounded-full flex items-center justify-center mx-auto mb-4">
                                <CheckCircle size={32} />
                            </div>
                            <h3 className="text-xl font-bold text-gray-900 mb-2">Ad Created in Meta!</h3>
                            <p className="text-gray-600 text-sm mb-1">
                                Ad ID: <code className="font-mono text-purple-700">{pushResult.ad_id}</code>
                            </p>
                            <p className="text-gray-500 text-sm mb-6">
                                Status:{' '}
                                <span className={`font-semibold ${pushResult.status === 'PAUSED' ? 'text-amber-600' : 'text-green-600'}`}>
                                    {pushResult.status}
                                </span>
                                {pushResult.status === 'PAUSED' && ' — Review in Ads Manager before activating.'}
                            </p>
                            <div className="flex flex-col gap-3">
                                <a
                                    href={pushResult.meta_url}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="flex items-center justify-center gap-2 px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 font-semibold text-sm"
                                >
                                    <ExternalLink size={16} />
                                    Open in Ads Manager
                                </a>
                                <button
                                    onClick={resetPushModal}
                                    className="px-6 py-3 bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200 font-medium text-sm"
                                >
                                    Done
                                </button>
                            </div>
                        </div>
                    ) : (
                        /* Form screen */
                        <>
                            <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
                                <h3 className="text-lg font-bold text-gray-900">Push to Meta</h3>
                                <button
                                    onClick={resetPushModal}
                                    className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-500"
                                >
                                    <X size={18} />
                                </button>
                            </div>

                            <div className="p-6 space-y-5">
                                {/* Ad copy preview */}
                                <div className="bg-purple-50 border border-purple-200 rounded-lg p-4 text-sm">
                                    <p className="font-semibold text-purple-900 mb-1">{pushModal.headline_remix}</p>
                                    <p className="text-gray-700 line-clamp-2 text-xs">{pushModal.body_copy}</p>
                                    <span className="mt-2 inline-block px-2 py-0.5 bg-purple-200 text-purple-800 rounded text-xs font-medium">{pushModal.cta_button}</span>
                                </div>

                                {/* Error banner */}
                                {adSetsError && (
                                    <div className="bg-red-50 border border-red-200 rounded-lg px-4 py-3 text-sm text-red-700">
                                        <strong>Error loading Meta data:</strong> {adSetsError}
                                    </div>
                                )}

                                {/* Ad Set */}
                                <div>
                                    <label className="block text-sm font-semibold text-gray-700 mb-1.5">Ad Set</label>
                                    {adSetsLoading ? (
                                        <div className="flex items-center gap-2 text-sm text-gray-500 py-2">
                                            <RefreshCw size={14} className="animate-spin" />
                                            Loading ad sets…
                                        </div>
                                    ) : (
                                        <>
                                        <select
                                            value={pushForm.adset_id}
                                            onChange={e => {
                                                const newId = e.target.value;
                                                const newAdset = adSets.find(a => a.id === newId);
                                                const newIsLeadGen = newAdset?.campaign?.objective === 'OUTCOME_LEADS';
                                                setPushForm(f => ({ ...f, adset_id: newId, lead_form_id: '', website_url: f.website_url || '' }));
                                                if (newIsLeadGen && pushForm.page_id) fetchLeadForms(pushForm.page_id);
                                                if (!newIsLeadGen) setLeadForms([]);
                                            }}
                                            className="w-full border border-gray-300 rounded-lg px-3 py-2.5 text-sm focus:ring-2 focus:ring-purple-500 focus:border-purple-500"
                                        >
                                            <option value="">Select an ad set…</option>
                                            {(() => {
                                                // Group by campaign name
                                                const groups = {};
                                                adSets.forEach(a => {
                                                    const campName = a.campaign?.name || 'Uncategorized';
                                                    if (!groups[campName]) groups[campName] = [];
                                                    groups[campName].push(a);
                                                });
                                                return Object.entries(groups).map(([campName, sets]) => (
                                                    <optgroup key={campName} label={campName}>
                                                        {sets.map(a => {
                                                            const budget = a.daily_budget
                                                                ? ` · $${(parseInt(a.daily_budget) / 100).toFixed(0)}/day`
                                                                : '';
                                                            const statusTag = a.status && a.status !== 'ACTIVE' ? ` [${a.status}]` : '';
                                                            return (
                                                                <option key={a.id} value={a.id}>
                                                                    {a.name}{budget}{statusTag}
                                                                </option>
                                                            );
                                                        })}
                                                    </optgroup>
                                                ));
                                            })()}
                                        </select>
                                        {/* Lead gen indicator */}
                                        {pushForm.adset_id && adSets.find(a => a.id === pushForm.adset_id)?.campaign?.objective === 'OUTCOME_LEADS' && (
                                            <p className="text-xs text-blue-600 mt-1 font-medium">Lead Generation campaign detected — select a lead form below</p>
                                        )}
                                        </>
                                    )}
                                </div>

                                {/* Facebook Page */}
                                <div>
                                    <label className="block text-sm font-semibold text-gray-700 mb-1.5">Facebook Page</label>
                                    {adSetsLoading ? (
                                        <div className="flex items-center gap-2 text-sm text-gray-500 py-2">
                                            <RefreshCw size={14} className="animate-spin" />
                                            Loading pages…
                                        </div>
                                    ) : (
                                        <select
                                            value={pushForm.page_id}
                                            onChange={e => {
                                                const newPageId = e.target.value;
                                                setPushForm(f => ({ ...f, page_id: newPageId, lead_form_id: '' }));
                                                const selectedAdset = adSets.find(a => a.id === pushForm.adset_id);
                                                if (selectedAdset?.campaign?.objective === 'OUTCOME_LEADS') {
                                                    fetchLeadForms(newPageId);
                                                }
                                            }}
                                            className="w-full border border-gray-300 rounded-lg px-3 py-2.5 text-sm focus:ring-2 focus:ring-purple-500 focus:border-purple-500"
                                        >
                                            <option value="">Select a page…</option>
                                            {pages.map(p => (
                                                <option key={p.id} value={p.id}>{p.name}</option>
                                            ))}
                                        </select>
                                    )}
                                </div>

                                {/* Image — generate inline or paste URL */}
                                <div>
                                    <label className="block text-sm font-semibold text-gray-700 mb-1.5">
                                        <Image size={13} className="inline mr-1" />
                                        Ad Image
                                    </label>
                                    {pushForm.image_url ? (
                                        /* Image preview once URL is set */
                                        <div className="border border-gray-200 rounded-lg overflow-hidden">
                                            <img
                                                src={pushForm.image_url}
                                                alt="Ad preview"
                                                className="w-full h-32 object-cover"
                                                onError={e => { e.target.style.display = 'none'; }}
                                            />
                                            <div className="flex items-center gap-2 px-3 py-2 bg-gray-50 border-t border-gray-200">
                                                <p className="text-xs text-gray-500 flex-1 truncate">{pushForm.image_url}</p>
                                                <button
                                                    type="button"
                                                    onClick={() => setPushForm(f => ({ ...f, image_url: '' }))}
                                                    className="text-xs text-red-500 hover:text-red-700 font-medium shrink-0"
                                                >
                                                    Remove
                                                </button>
                                            </div>
                                        </div>
                                    ) : (
                                        /* No image yet — generate or paste */
                                        <div className="space-y-2">
                                            <button
                                                type="button"
                                                onClick={handleGenerateImageInline}
                                                disabled={imageGenerating}
                                                className="w-full flex items-center justify-center gap-2 px-4 py-3 rounded-lg border-2 border-dashed border-purple-300 text-purple-700 bg-purple-50 hover:bg-purple-100 font-semibold text-sm disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                                            >
                                                {imageGenerating ? (
                                                    <><RefreshCw size={15} className="animate-spin" />Generating image… (30–60s)</>
                                                ) : (
                                                    <><Sparkles size={15} />Generate Image with AI</>
                                                )}
                                            </button>
                                            <div className="flex items-center gap-2 text-xs text-gray-400">
                                                <div className="flex-1 h-px bg-gray-200" />
                                                or paste a URL
                                                <div className="flex-1 h-px bg-gray-200" />
                                            </div>
                                            <input
                                                type="url"
                                                placeholder="https://… (paste any image URL)"
                                                value={pushForm.image_url}
                                                onChange={e => setPushForm(f => ({ ...f, image_url: e.target.value }))}
                                                className="w-full border border-gray-300 rounded-lg px-3 py-2.5 text-sm focus:ring-2 focus:ring-purple-500 focus:border-purple-500"
                                            />
                                        </div>
                                    )}
                                </div>

                                {/* Lead Form (lead gen campaigns) OR Destination URL (traffic/conversion campaigns) */}
                                {(() => {
                                    const selectedAdset = adSets.find(a => a.id === pushForm.adset_id);
                                    const isLeadGen = selectedAdset?.campaign?.objective === 'OUTCOME_LEADS';
                                    if (isLeadGen) {
                                        return (
                                            <div>
                                                <label className="block text-sm font-semibold text-gray-700 mb-1.5">Lead Form</label>
                                                {leadFormsLoading ? (
                                                    <div className="flex items-center gap-2 text-sm text-gray-500 py-2">
                                                        <RefreshCw size={14} className="animate-spin" />
                                                        Loading lead forms…
                                                    </div>
                                                ) : leadForms.length === 0 ? (
                                                    <div className="bg-amber-50 border border-amber-200 rounded-lg px-4 py-3 text-sm text-amber-800">
                                                        No lead forms found for this page. <a href="https://www.facebook.com/ads/leadgen/create" target="_blank" rel="noopener noreferrer" className="underline font-medium">Create one in Meta</a> first.
                                                    </div>
                                                ) : (
                                                    <select
                                                        value={pushForm.lead_form_id}
                                                        onChange={e => setPushForm(f => ({ ...f, lead_form_id: e.target.value }))}
                                                        className="w-full border border-gray-300 rounded-lg px-3 py-2.5 text-sm focus:ring-2 focus:ring-purple-500 focus:border-purple-500"
                                                    >
                                                        <option value="">Select a lead form…</option>
                                                        {leadForms.map(f => (
                                                            <option key={f.id} value={f.id}>{f.name}{f.status && f.status !== 'ACTIVE' ? ` [${f.status}]` : ''}</option>
                                                        ))}
                                                    </select>
                                                )}
                                            </div>
                                        );
                                    }
                                    return (
                                        <div>
                                            <label className="block text-sm font-semibold text-gray-700 mb-1.5">
                                                <Globe size={13} className="inline mr-1" />
                                                Destination URL
                                            </label>
                                            <input
                                                type="url"
                                                placeholder="https://…"
                                                value={pushForm.website_url}
                                                onChange={e => setPushForm(f => ({ ...f, website_url: e.target.value }))}
                                                className="w-full border border-gray-300 rounded-lg px-3 py-2.5 text-sm focus:ring-2 focus:ring-purple-500 focus:border-purple-500"
                                            />
                                        </div>
                                    );
                                })()}

                                {/* Status toggle */}
                                <div>
                                    <label className="block text-sm font-semibold text-gray-700 mb-2">Launch Status</label>
                                    <div className="flex items-center gap-3">
                                        <div className="flex rounded-lg border border-gray-300 overflow-hidden text-sm font-medium">
                                            <button
                                                type="button"
                                                onClick={() => setPushForm(f => ({ ...f, status: 'PAUSED' }))}
                                                className={`px-4 py-2 transition-colors ${pushForm.status === 'PAUSED' ? 'bg-amber-100 text-amber-800' : 'bg-white text-gray-600 hover:bg-gray-50'}`}
                                            >
                                                Paused
                                            </button>
                                            <button
                                                type="button"
                                                onClick={() => setPushForm(f => ({ ...f, status: 'ACTIVE' }))}
                                                className={`px-4 py-2 transition-colors ${pushForm.status === 'ACTIVE' ? 'bg-green-100 text-green-800' : 'bg-white text-gray-600 hover:bg-gray-50'}`}
                                            >
                                                Active
                                            </button>
                                        </div>
                                        {pushForm.status === 'PAUSED' && (
                                            <p className="text-xs text-amber-700">Recommended — review in Meta before going live</p>
                                        )}
                                    </div>
                                </div>
                            </div>

                            <div className="px-6 py-4 border-t border-gray-200 flex gap-3">
                                <button
                                    onClick={resetPushModal}
                                    className="flex-1 px-4 py-2.5 bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200 font-medium text-sm"
                                >
                                    Cancel
                                </button>
                                <button
                                    onClick={handlePushToMeta}
                                    disabled={(() => {
                                        const selectedAdset = adSets.find(a => a.id === pushForm.adset_id);
                                        const isLeadGen = selectedAdset?.campaign?.objective === 'OUTCOME_LEADS';
                                        return (
                                            !pushForm.adset_id ||
                                            !pushForm.page_id ||
                                            !pushForm.image_url ||
                                            (isLeadGen ? !pushForm.lead_form_id : !pushForm.website_url) ||
                                            pushLoading
                                        );
                                    })()}
                                    className="flex-1 flex items-center justify-center gap-2 px-4 py-2.5 text-white rounded-lg font-semibold text-sm disabled:opacity-40 disabled:cursor-not-allowed"
                                    style={{ backgroundColor: '#2D2463' }}
                                >
                                    {pushLoading ? (
                                        <><RefreshCw size={14} className="animate-spin" />Pushing to Meta…</>
                                    ) : (
                                        <>Push to Meta</>
                                    )}
                                </button>
                            </div>
                        </>
                    )}
                </div>
            </div>
        )}
        </>
    );
}
