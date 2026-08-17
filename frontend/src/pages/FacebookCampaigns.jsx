import React, { useState } from 'react';
import { Check, Target, Users, Image as ImageIcon, Zap, CheckCircle, CreditCard, Megaphone, CheckCircle2, ArrowRight } from 'lucide-react';
import { CampaignProvider, useCampaign } from '../context/CampaignContext';
import AdAccountStep from '../components/AdAccountStep';
import CampaignStep from '../components/CampaignStep';
import AdSetStep from '../components/AdSetStep';
import AdCreativeStep from '../components/AdCreativeStep';
import BulkAdCreation from '../components/BulkAdCreation';
import BulkMatchImport from '../components/BulkMatchImport';

// Shared toggle UI for choosing how Step 5 will build ads. Lives at Step 4 so
// the mode is known before the Creative form renders — Step 5 just reads it.
const BatchModeToggle = ({ batchMode, setBatchMode }) => (
    <div className="flex justify-center mb-6">
        <div className="inline-flex bg-gray-100 rounded-lg p-1">
            <button
                onClick={() => setBatchMode('combinations')}
                className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${batchMode === 'combinations' ? 'bg-white shadow-sm text-amber-600' : 'text-gray-500 hover:text-gray-700'
                    }`}
            >
                Generate All Combinations
            </button>
            <button
                onClick={() => setBatchMode('match-import')}
                className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${batchMode === 'match-import' ? 'bg-white shadow-sm text-amber-600' : 'text-gray-500 hover:text-gray-700'
                    }`}
            >
                Match by Naming Convention
            </button>
        </div>
    </div>
);

const FacebookCampaignWizardInner = () => {
    const { creativeData } = useCampaign();
    const [currentStep, setCurrentStep] = useState(1);
    const [batchMode, setBatchMode] = useState('combinations'); // 'combinations' | 'match-import'
    const [formData, setFormData] = useState({
        adAccountId: null,
        campaignId: null,
        adSetId: null,
        creativeId: null,
    });

    const steps = [
        { id: 1, label: 'Ad Account', icon: CreditCard },
        { id: 2, label: 'Campaign', icon: Target },
        { id: 3, label: 'Ad Set', icon: Users },
        { id: 4, label: 'Creative', icon: ImageIcon },
        { id: 5, label: 'Bulk Ads', icon: Megaphone },
        { id: 6, label: 'Review & Launch', icon: CheckCircle2 },
    ];

    const handleNext = () => {
        if (currentStep < steps.length) {
            setCurrentStep(currentStep + 1);
        }
    };

    const handleBack = () => {
        if (currentStep > 1) {
            setCurrentStep(currentStep - 1);
        }
    };

    // Placeholder for validation logic
    const isStepValid = () => {
        switch (currentStep) {
            case 1: return !!formData.adAccountId;
            case 2: return !!formData.campaignId;
            case 3: return !!formData.adSetId;
            case 4:
                // Not mode-aware: the real step-4 gate lives in AdCreativeStep's own
                // handleNext, which already branches on isMatchImport. This is a
                // generic fallback only — see BulkMatchImport.jsx / AdCreativeStep.jsx.
                return !!(
                    creativeData.creativeName &&
                    creativeData.pageId &&
                    creativeData.websiteUrl &&
                    creativeData.creatives && creativeData.creatives.length > 0 &&
                    creativeData.headlines[0] && creativeData.headlines[0].trim() &&
                    creativeData.bodies[0] && creativeData.bodies[0].trim()
                );
            default: return true;
        }
    };

    return (
        <div className="max-w-6xl mx-auto space-y-8">
            {/* Header */}
            <div>
                <h1 className="text-3xl font-bold text-gray-900 mb-2 flex items-center gap-3">
                    <Megaphone size={32} className="text-amber-600" />
                    Facebook Campaigns
                </h1>
                <p className="text-gray-600">Create and manage your Facebook ad campaigns</p>
            </div>

            {/* Wizard Steps */}
            <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
                <div className="flex justify-between items-center mb-8 relative">
                    {/* Progress Bar Background */}
                    <div className="absolute top-1/2 left-0 w-full h-1 bg-gray-100 -z-10 rounded-full" />

                    {/* Progress Bar Fill */}
                    <div
                        className="absolute top-1/2 left-0 h-1 bg-amber-600 -z-10 rounded-full transition-all duration-500 ease-in-out"
                        style={{ width: `${((currentStep - 1) / (steps.length - 1)) * 100}%` }}
                    />

                    {steps.map((step) => {
                        const isCompleted = step.id < currentStep;
                        const isCurrent = step.id === currentStep;

                        return (
                            <div key={step.id} className="flex flex-col items-center gap-2 bg-white px-2">
                                <div
                                    className={`w-10 h-10 rounded-full flex items-center justify-center transition-all duration-300 ${isCompleted || isCurrent
                                        ? 'bg-amber-600 text-white shadow-md scale-110'
                                        : 'bg-gray-100 text-gray-400'
                                        }`}
                                >
                                    {isCompleted ? (
                                        <CheckCircle2 size={20} />
                                    ) : (
                                        <step.icon size={20} />
                                    )}
                                </div>
                                <span
                                    className={`text-sm font-medium transition-colors duration-300 ${isCurrent ? 'text-amber-900' : 'text-gray-500'
                                        }`}
                                >
                                    {step.label}
                                </span>
                            </div>
                        );
                    })}
                </div>

                {/* Step Content */}
                <div className="min-h-[400px]">
                    {currentStep === 1 && (
                        <AdAccountStep
                            selectedAccount={formData.adAccountId}
                            onAccountSelect={(id) => setFormData({ ...formData, adAccountId: id })}
                            onNext={handleNext}
                        />
                    )}
                    {currentStep === 2 && (
                        <CampaignStep
                            adAccountId={formData.adAccountId}
                            selectedCampaign={formData.campaignId}
                            onCampaignSelect={(id) => setFormData({ ...formData, campaignId: id })}
                            onNext={handleNext}
                            onBack={handleBack}
                        />
                    )}
                    {currentStep === 3 && (
                        <AdSetStep
                            adAccountId={formData.adAccountId}
                            campaignId={formData.campaignId}
                            selectedAdSet={formData.adSetId}
                            onAdSetSelect={(id) => setFormData({ ...formData, adSetId: id })}
                            onNext={handleNext}
                            onBack={handleBack}
                        />
                    )}
                    {currentStep === 4 && (
                        <div>
                            <BatchModeToggle batchMode={batchMode} setBatchMode={setBatchMode} />
                            <AdCreativeStep
                                adAccountId={formData.adAccountId}
                                selectedCreative={formData.creativeId}
                                onCreativeSelect={(id) => setFormData({ ...formData, creativeId: id })}
                                onNext={handleNext}
                                onBack={handleBack}
                                mode={batchMode}
                            />
                        </div>
                    )}
                    {currentStep === 5 && (
                        <div>
                            {batchMode === 'combinations' ? (
                                <BulkAdCreation
                                    onNext={handleNext}
                                    onBack={handleBack}
                                />
                            ) : (
                                <BulkMatchImport
                                    onNext={handleNext}
                                    onBack={handleBack}
                                />
                            )}
                        </div>
                    )}
                    {currentStep === 6 && (
                        <div className="text-center py-12">
                            <CheckCircle2 className="mx-auto mb-4 text-amber-500" size={64} />
                            <h2 className="text-3xl font-bold mb-4">Campaign Ready to Launch!</h2>
                            <p className="text-gray-600 mb-8">
                                Review your settings and launch your Facebook ad campaign.
                            </p>
                        </div>
                    )}
                </div>


            </div>
        </div>
    );
};

const FacebookCampaignWizard = () => (
    <CampaignProvider>
        <FacebookCampaignWizardInner />
    </CampaignProvider>
);

export default FacebookCampaignWizard;
