import React, { useState, useEffect, useRef, useCallback } from 'react';
import { ChevronRight, ChevronLeft, Sparkles, Check, Image, FileText, Briefcase, Package, Users, Zap, Copy, CheckCircle, Upload, RefreshCw, TrendingUp } from 'lucide-react';
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
    const [adConcept, setAdConcept] = useState(null);
    const [prefillSource, setPrefillSource] = useState(null); // winning ad data from performance page
    const [copied, setCopied] = useState(false);
    const [uploadingRef, setUploadingRef] = useState(false);
    const [refPreview, setRefPreview] = useState('');
    const fileInputRef = useRef(null);

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

    // On mount: check for a winning ad passed in from the performance page
    useEffect(() => {
        const raw = localStorage.getItem('pendingRemixCreative');
        if (!raw) return;
        try {
            const creative = JSON.parse(raw);
            localStorage.removeItem('pendingRemixCreative');
            setPrefillSource(creative);
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
            // Skip template picker — jump straight to Brand selection
            setCurrentStep(2);
        } catch (e) {
            // malformed localStorage — ignore
        }
    }, []);

    const steps = [
        { id: 1, name: 'Template', icon: Image },
        { id: 2, name: 'Brand', icon: Briefcase },
        { id: 3, name: 'Product', icon: Package },
        { id: 4, name: 'Profile', icon: Users },
        { id: 5, name: 'Campaign', icon: FileText },
        { id: 6, name: 'Review', icon: Check }
    ];

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
        setCurrentStep(1);
        setBlueprint(null);
        setAdConcept(null);
        setPrefillSource(null);
        setCopied(false);
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

    // Send remix copy to Batch Generate
    const handleGenerateImage = () => {
        if (!adConcept) return;
        localStorage.setItem('pendingBatchCopy', JSON.stringify({
            headline: adConcept.headline_remix || '',
            body: adConcept.body_copy || '',
            cta: adConcept.cta_button || 'Get My Quote',
        }));
        navigate('/batch-generate');
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
                    campaign_messaging: wizardData.campaignDetails.messaging
                }
                : {
                    template_id: wizardData.template.id,
                    brand_id: wizardData.brand.id,
                    product_id: wizardData.product.id,
                    profile_id: wizardData.profile.id,
                    campaign_offer: wizardData.campaignDetails.offer,
                    campaign_urgency: wizardData.campaignDetails.urgency,
                    campaign_messaging: wizardData.campaignDetails.messaging
                };

            const response = await authFetch(endpoint, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });

            if (!response.ok) throw new Error('Reconstruction failed');

            const data = await response.json();
            setAdConcept(data);
            setCurrentStep(7); // Move to results step
        } catch (error) {
            console.error('Reconstruction error:', error);
            showError('Failed to reconstruct ad. Please try again.');
        } finally {
            setLoading(false);
        }
    };

    return (
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

                {/* Step 6: Review & Generate */}
                {currentStep === 6 && (
                    <div>
                        <h3 className="text-xl font-bold mb-4">Review & Generate</h3>
                        <p className="text-gray-600 mb-6">Review your selections and generate the remixed ad concept</p>

                        <div className="space-y-4 max-w-2xl">
                            <div className="bg-gray-50 p-4 rounded-lg">
                                <h4 className="font-bold text-gray-900 mb-2">Template</h4>
                                <p className="text-gray-700">{wizardData.template?.name}</p>
                            </div>

                            <div className="bg-gray-50 p-4 rounded-lg">
                                <h4 className="font-bold text-gray-900 mb-2">Brand</h4>
                                <p className="text-gray-700">{wizardData.brand?.name}</p>
                            </div>

                            <div className="bg-gray-50 p-4 rounded-lg">
                                <h4 className="font-bold text-gray-900 mb-2">Product</h4>
                                <p className="text-gray-700">{wizardData.product?.name}</p>
                            </div>

                            <div className="bg-gray-50 p-4 rounded-lg">
                                <h4 className="font-bold text-gray-900 mb-2">Audience</h4>
                                <p className="text-gray-700">{wizardData.profile?.name}</p>
                            </div>

                            <div className="bg-gray-50 p-4 rounded-lg">
                                <h4 className="font-bold text-gray-900 mb-2">Campaign</h4>
                                <p className="text-gray-700"><strong>Offer:</strong> {wizardData.campaignDetails.offer}</p>
                                {wizardData.campaignDetails.urgency && (
                                    <p className="text-gray-700"><strong>Urgency:</strong> {wizardData.campaignDetails.urgency}</p>
                                )}
                                <p className="text-gray-700"><strong>Messaging:</strong> {wizardData.campaignDetails.messaging}</p>
                            </div>
                        </div>
                    </div>
                )}

                {/* Step 7: Results */}
                {currentStep === 7 && adConcept && (
                    <div>
                        <div className="text-center mb-8">
                            <div className="w-20 h-20 bg-green-100 text-green-600 rounded-full flex items-center justify-center mx-auto mb-4">
                                <Check size={40} />
                            </div>
                            <h2 className="text-3xl font-bold text-gray-900 mb-2">Ad Concept Generated!</h2>
                            <p className="text-gray-600 mb-4">Your remixed ad concept is ready</p>
                            {/* Action buttons */}
                            <div className="flex items-center justify-center gap-3">
                                <button
                                    onClick={handleCopyAll}
                                    className="flex items-center gap-2 px-4 py-2 rounded-lg border border-gray-200 text-sm font-medium text-gray-700 bg-white hover:bg-gray-50 transition-colors"
                                >
                                    {copied ? <CheckCircle size={15} className="text-green-500" /> : <Copy size={15} />}
                                    {copied ? 'Copied!' : 'Copy All Copy'}
                                </button>
                                <button
                                    onClick={handleGenerateImage}
                                    className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold text-white transition-opacity hover:opacity-90"
                                    style={{ backgroundColor: '#2D2463' }}
                                >
                                    <Zap size={15} />
                                    Generate Image
                                </button>
                            </div>
                        </div>

                        <div className="space-y-6 max-w-3xl mx-auto">
                            <div className="bg-purple-50 border-2 border-purple-200 rounded-xl p-6">
                                <h4 className="font-bold text-purple-900 mb-3 flex items-center gap-2">
                                    <FileText size={20} />
                                    Headline
                                </h4>
                                <p className="text-lg font-bold text-gray-900">{adConcept.headline_remix}</p>
                            </div>

                            <div className="bg-blue-50 border-2 border-blue-200 rounded-xl p-6">
                                <h4 className="font-bold text-blue-900 mb-3">Body Copy</h4>
                                <p className="text-gray-700 whitespace-pre-line">{adConcept.body_copy}</p>
                            </div>

                            <div className="bg-green-50 border-2 border-green-200 rounded-xl p-6">
                                <h4 className="font-bold text-green-900 mb-3">Call to Action</h4>
                                <button className="px-6 py-3 bg-green-600 text-white rounded-lg font-bold">
                                    {adConcept.cta_button}
                                </button>
                            </div>

                            <div className="bg-amber-50 border-2 border-amber-200 rounded-xl p-6">
                                <h4 className="font-bold text-amber-900 mb-3 flex items-center gap-2">
                                    <Image size={20} />
                                    Visual Description
                                </h4>
                                <p className="text-gray-700">{adConcept.visual_description}</p>
                            </div>

                            <div className="bg-gray-50 border-2 border-gray-200 rounded-xl p-6">
                                <h4 className="font-bold text-gray-900 mb-3 flex items-center gap-2">
                                    <Sparkles size={20} />
                                    Image Generation Prompt
                                </h4>
                                <p className="text-sm text-gray-700 font-mono bg-white p-4 rounded border border-gray-300">
                                    {adConcept.image_generation_prompt}
                                </p>
                            </div>
                        </div>
                    </div>
                )}
            </div>

            {/* Navigation */}
            <div className="mt-6 flex items-center justify-between">
                <div></div>
                <div className="flex gap-3">
                    {/* Back button — available on all steps 2–7 */}
                    {currentStep > 1 && currentStep < 7 && (
                        <button
                            onClick={() => setCurrentStep(currentStep - 1)}
                            className="flex items-center gap-2 px-6 py-3 bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200 font-medium"
                        >
                            <ChevronLeft size={20} />
                            Back
                        </button>
                    )}

                    {/* Next button — steps 2–5 */}
                    {currentStep >= 2 && currentStep <= 5 && (
                        <button
                            onClick={() => setCurrentStep(currentStep + 1)}
                            disabled={
                                (currentStep === 2 && !wizardData.brand) ||
                                (currentStep === 4 && !wizardData.profile) ||
                                (currentStep === 5 && (!wizardData.campaignDetails.offer || !wizardData.campaignDetails.messaging))
                            }
                            className="flex items-center gap-2 px-8 py-3 bg-purple-600 text-white rounded-lg hover:bg-purple-700 font-medium disabled:opacity-40 disabled:cursor-not-allowed"
                        >
                            Next
                            <ChevronRight size={20} />
                        </button>
                    )}

                    {currentStep === 6 && (
                        <button
                            onClick={handleReconstruct}
                            disabled={!wizardData.campaignDetails.offer || !wizardData.campaignDetails.messaging}
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
    );
}
