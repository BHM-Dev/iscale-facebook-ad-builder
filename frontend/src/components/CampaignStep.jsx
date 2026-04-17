import React, { useState, useEffect } from 'react';
import { ChevronRight, ChevronLeft, Check, Loader, Plus } from 'lucide-react';
import { useCampaign } from '../context/CampaignContext';
import { useToast } from '../context/ToastContext';
import { getCampaigns, createFacebookCampaign } from '../lib/facebookApi';

const CAMPAIGN_OBJECTIVES = [
    { value: 'OUTCOME_SALES', label: 'Sales - Drive purchases and conversions' },
    { value: 'OUTCOME_TRAFFIC', label: 'Traffic - Send people to your website' },
    { value: 'OUTCOME_LEADS', label: 'Leads - Collect leads for your business' },
    { value: 'OUTCOME_ENGAGEMENT', label: 'Engagement - Get more messages, video views, etc.' },
    { value: 'OUTCOME_AWARENESS', label: 'Awareness - Reach people near your business' },
    { value: 'OUTCOME_APP_PROMOTION', label: 'App Promotion - Get more app installs' }
];

const BID_STRATEGIES = [
    { value: 'LOWEST_COST_WITHOUT_CAP', label: 'Lowest Cost (Highest Volume or Value, No Cap)' },
    { value: 'LOWEST_COST_WITH_BID_CAP', label: 'Lowest Cost with Bid Cap' },
    { value: 'COST_CAP', label: 'Cost Cap (Cost Per Result Goal)' }
];

const CampaignStep = ({ onNext, onBack }) => {
    const { campaignData, setCampaignData, selectedAdAccount, setSelectedAdAccount } = useCampaign();
    const { showError, showWarning } = useToast();
    const [mode, setMode] = useState('new'); // 'new' or 'existing'
    const [existingCampaigns, setExistingCampaigns] = useState([]);
    const [selectedCampaign, setSelectedCampaign] = useState(null);
    const [loading, setLoading] = useState(false);
    const [loadingCampaigns, setLoadingCampaigns] = useState(false);

    useEffect(() => {
        // Fetch campaigns when switching to existing mode
        if (mode === 'existing' && selectedAdAccount) {
            fetchExistingCampaigns();
        }
    }, [mode, selectedAdAccount]);

    const fetchExistingCampaigns = async () => {
        if (!selectedAdAccount) return;

        setLoadingCampaigns(true);
        try {
            const campaigns = await getCampaigns(selectedAdAccount.id);
            setExistingCampaigns(campaigns);
        } catch (error) {
            console.error('Error fetching campaigns:', error);
            showError(`Error fetching campaigns: ${error.message}`);
        } finally {
            setLoadingCampaigns(false);
        }
    };

    const handleSelectExisting = (campaign) => {
        setSelectedCampaign(campaign);

        const dailyBudget = campaign.dailyBudget ? parseInt(campaign.dailyBudget) / 100 : 0;
        const lifetimeBudget = campaign.lifetimeBudget ? parseInt(campaign.lifetimeBudget) / 100 : 0;

        const isCBO = dailyBudget > 0 || lifetimeBudget > 0;
        const isLifetime = lifetimeBudget > 0 && dailyBudget === 0;

        setCampaignData({
            ...campaign,
            budgetType: isCBO ? 'CBO' : 'ABO',
            budgetScheduleType: isLifetime ? 'LIFETIME' : 'DAILY',
            dailyBudget: dailyBudget,
            lifetimeBudget: lifetimeBudget,
            bidStrategy: campaign.bid_strategy || '',
            fbCampaignId: campaign.id,
            isExisting: true
        });
    };

    const handleInputChange = (field, value) => {
        setCampaignData(prev => ({
            ...prev,
            [field]: value,
            isExisting: false
        }));
    };

    const handleNext = async () => {
        if (mode === 'existing' && !selectedCampaign) {
            showWarning('Please select a campaign');
            return;
        }

        if (mode === 'existing') {
            // For existing campaigns, we just use the selected data
            // No need to call API or create anything new
            // The data is already set in handleSelectExisting
        }

        if (mode === 'new') {
            if (!campaignData.name || !campaignData.objective) {
                showWarning('Please fill in all required fields');
                return;
            }

            if (campaignData.budgetType === 'CBO') {
                const isLifetime = campaignData.budgetScheduleType === 'LIFETIME';
                const budget = isLifetime ? campaignData.lifetimeBudget : campaignData.dailyBudget;
                if (!budget || budget <= 0) {
                    showWarning(`Please enter a valid ${isLifetime ? 'Lifetime' : 'Daily'} Budget for CBO campaign`);
                    return;
                }
                if (isLifetime) {
                    if (!campaignData.endTime) {
                        showWarning('Lifetime budget requires an end date');
                        return;
                    }
                    if (new Date(campaignData.endTime) <= new Date()) {
                        showWarning('End date must be in the future');
                        return;
                    }
                }
            }

            // Validate Bid Amount if strategy requires it (for CBO campaigns)
            if (campaignData.budgetType === 'CBO' &&
                (campaignData.bidStrategy === 'LOWEST_COST_WITH_BID_CAP' || campaignData.bidStrategy === 'COST_CAP') &&
                (!campaignData.bidAmount || campaignData.bidAmount <= 0)) {
                showWarning('Please enter a valid Bid Amount for the selected bid strategy');
                return;
            }

            // For new campaigns, we just prepare the data
            // The actual creation happens in the final step (BulkAdCreation)
            const id = `camp_${Date.now()}`;
            setCampaignData(prev => ({ ...prev, id }));
        }

        onNext();
    };

    return (
        <div>
            <h2 className="text-2xl font-bold mb-6">Campaign Setup</h2>

            {/* Mode Toggle */}
            <div className="flex gap-4 mb-6">
                <button
                    onClick={() => {
                        setMode('new');
                        setCampaignData(prev => ({
                            ...prev,
                            isExisting: false,
                            fbCampaignId: null
                        }));
                    }}
                    className={`flex-1 p-4 rounded-xl border-2 transition-all ${mode === 'new'
                        ? 'border-amber-600 bg-amber-50'
                        : 'border-gray-200 hover:border-amber-300'
                        }`}
                >
                    <Plus className="mx-auto mb-2" size={24} />
                    <div className="font-semibold">Create New Campaign</div>
                </button>
                <button
                    onClick={() => setMode('existing')}
                    className={`flex-1 p-4 rounded-xl border-2 transition-all ${mode === 'existing'
                        ? 'border-amber-600 bg-amber-50'
                        : 'border-gray-200 hover:border-amber-300'
                        }`}
                >
                    <Check className="mx-auto mb-2" size={24} />
                    <div className="font-semibold">Use Existing Campaign</div>
                </button>
            </div>

            {/* Existing Campaigns List */}
            {mode === 'existing' && (
                <div className="space-y-4 mb-6">
                    {/* Existing Campaigns */}
                    <div>
                        <h3 className="font-semibold text-gray-700 mb-3">Select a Campaign</h3>
                        {loadingCampaigns ? (
                            <div className="flex items-center justify-center gap-2 text-gray-500 py-8">
                                <Loader className="animate-spin" size={20} />
                                <span>Loading campaigns from Facebook...</span>
                            </div>
                        ) : existingCampaigns.length === 0 ? (
                            <p className="text-gray-500 text-center py-8">No campaigns found in this ad account.</p>
                        ) : (
                            existingCampaigns.map(campaign => (
                                <div
                                    key={campaign.id}
                                    onClick={() => handleSelectExisting(campaign)}
                                    className={`p-4 rounded-xl border-2 cursor-pointer transition-all mb-2 ${selectedCampaign?.id === campaign.id
                                        ? 'border-amber-600 bg-amber-50'
                                        : 'border-gray-200 hover:border-amber-300'
                                        }`}
                                >
                                    <div className="flex justify-between items-start">
                                        <div className="flex-1">
                                            <div className="flex items-center gap-2">
                                                <div className="font-bold text-gray-900">{campaign.name}</div>
                                                <span className={`px-2 py-0.5 rounded text-xs font-medium ${campaign.status === 'ACTIVE' ? 'bg-green-100 text-green-700' :
                                                    campaign.status === 'PAUSED' ? 'bg-yellow-100 text-yellow-700' :
                                                        'bg-gray-100 text-gray-700'
                                                    }`}>
                                                    {campaign.status}
                                                </span>
                                            </div>
                                            <div className="text-sm text-gray-500 mt-1">
                                                <span className="font-medium text-gray-700">
                                                    {(campaign.dailyBudget || campaign.lifetimeBudget) ? 'CBO' : 'ABO'}
                                                </span>
                                                {' • '}{campaign.objective}
                                                {campaign.dailyBudget && ` • Daily: $${(parseInt(campaign.dailyBudget) / 100).toFixed(2)}`}
                                                {campaign.lifetimeBudget && ` • Lifetime: $${(parseInt(campaign.lifetimeBudget) / 100).toFixed(2)}`}
                                            </div>
                                        </div>
                                        {selectedCampaign?.id === campaign.id && (
                                            <Check className="text-amber-600" size={20} />
                                        )}
                                    </div>
                                </div>
                            ))
                        )}
                    </div>
                </div>
            )}

            {/* New Campaign Form */}
            {mode === 'new' && (
                <div className="space-y-4">
                    <div>
                        <label className="block text-sm font-medium text-gray-700 mb-2">
                            Campaign Name *
                        </label>
                        <input
                            type="text"
                            value={campaignData.name}
                            onChange={(e) => handleInputChange('name', e.target.value)}
                            placeholder="Summer Sale Campaign"
                            className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-amber-500 focus:border-transparent"
                        />
                    </div>

                    <div>
                        <label className="block text-sm font-medium text-gray-700 mb-2">
                            Campaign Objective *
                        </label>
                        <select
                            value={campaignData.objective}
                            onChange={(e) => handleInputChange('objective', e.target.value)}
                            className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-amber-500 focus:border-transparent"
                        >
                            <option value="">Select objective...</option>
                            {CAMPAIGN_OBJECTIVES.map(obj => (
                                <option key={obj.value} value={obj.value}>{obj.label}</option>
                            ))}
                        </select>
                    </div>

                    {/* Special Ad Categories */}
                    <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">
                            Special Ad Category
                        </label>
                        <p className="text-xs text-gray-500 mb-3">
                            Required by Facebook for ads in regulated industries. Select if applicable — leave blank for most campaigns. Note: Housing, Credit, and Employment categories restrict age, gender, and detailed targeting.
                        </p>
                        <div className="grid grid-cols-2 gap-2">
                            {[
                                { value: 'HOUSING', label: 'Housing', desc: 'Real estate, rentals, mortgage' },
                                { value: 'FINANCIAL_PRODUCTS_SERVICES', label: 'Financial Products & Services', desc: 'Insurance, loans, credit cards, investments' },
                                { value: 'EMPLOYMENT', label: 'Employment', desc: 'Job listings, hiring, staffing' },
                                { value: 'ISSUES_ELECTIONS_POLITICS', label: 'Political / Issues', desc: 'Political ads, social issues' },
                                { value: 'ONLINE_GAMBLING_AND_GAMING', label: 'Online Gambling & Gaming', desc: 'Gambling, sports betting, iGaming' }
                            ].map(cat => {
                                const selected = (campaignData.specialAdCategories || []).includes(cat.value);
                                return (
                                    <button
                                        key={cat.value}
                                        type="button"
                                        onClick={() => {
                                            const current = campaignData.specialAdCategories || [];
                                            const updated = selected
                                                ? current.filter(v => v !== cat.value)
                                                : [...current, cat.value];
                                            handleInputChange('specialAdCategories', updated);
                                        }}
                                        className={`p-3 rounded-lg border-2 text-left transition-all ${selected
                                            ? 'border-amber-600 bg-amber-50'
                                            : 'border-gray-200 hover:border-amber-300'
                                        }`}
                                    >
                                        <div className="flex items-center gap-2">
                                            <div className={`w-4 h-4 rounded border-2 flex items-center justify-center flex-shrink-0 ${selected ? 'border-amber-600 bg-amber-600' : 'border-gray-300'}`}>
                                                {selected && <Check size={10} className="text-white" />}
                                            </div>
                                            <div>
                                                <div className="font-semibold text-sm text-gray-900">{cat.label}</div>
                                                <div className="text-xs text-gray-500">{cat.desc}</div>
                                            </div>
                                        </div>
                                    </button>
                                );
                            })}
                        </div>
                        {(campaignData.specialAdCategories || []).length > 0 && (
                            <div className="mt-2 p-3 bg-amber-50 border border-amber-200 rounded-lg text-xs text-amber-800">
                                <strong>Targeting restrictions apply.</strong> Facebook will limit age, gender, and zip-code targeting for this campaign. Make sure your ad set targeting complies.
                            </div>
                        )}
                    </div>

                    <div>
                        <label className="block text-sm font-medium text-gray-700 mb-2">
                            Budget Type *
                        </label>
                        <div className="grid grid-cols-2 gap-4">
                            <button
                                type="button"
                                onClick={() => handleInputChange('budgetType', 'ABO')}
                                className={`p-3 rounded-lg border-2 transition-all ${campaignData.budgetType === 'ABO'
                                    ? 'border-amber-600 bg-amber-50'
                                    : 'border-gray-200 hover:border-amber-300'
                                    }`}
                            >
                                <div className="font-semibold">ABO</div>
                                <div className="text-xs text-gray-500">Ad Set Budget</div>
                            </button>
                            <button
                                type="button"
                                onClick={() => handleInputChange('budgetType', 'CBO')}
                                className={`p-3 rounded-lg border-2 transition-all ${campaignData.budgetType === 'CBO'
                                    ? 'border-amber-600 bg-amber-50'
                                    : 'border-gray-200 hover:border-amber-300'
                                    }`}
                            >
                                <div className="font-semibold">CBO</div>
                                <div className="text-xs text-gray-500">Campaign Budget</div>
                            </button>
                        </div>
                    </div>

                    {campaignData.budgetType === 'CBO' && (
                        <>
                            {/* Daily vs Lifetime toggle */}
                            <div>
                                <label className="block text-sm font-medium text-gray-700 mb-2">
                                    Budget Schedule
                                </label>
                                <div className="grid grid-cols-2 gap-3">
                                    <button
                                        type="button"
                                        onClick={() => handleInputChange('budgetScheduleType', 'DAILY')}
                                        className={`p-3 rounded-lg border-2 transition-all text-left ${campaignData.budgetScheduleType !== 'LIFETIME' ? 'border-amber-600 bg-amber-50' : 'border-gray-200 hover:border-amber-300'}`}
                                    >
                                        <div className="font-semibold text-sm">Daily Budget</div>
                                        <div className="text-xs text-gray-500">Spend up to X per day</div>
                                    </button>
                                    <button
                                        type="button"
                                        onClick={() => handleInputChange('budgetScheduleType', 'LIFETIME')}
                                        className={`p-3 rounded-lg border-2 transition-all text-left ${campaignData.budgetScheduleType === 'LIFETIME' ? 'border-amber-600 bg-amber-50' : 'border-gray-200 hover:border-amber-300'}`}
                                    >
                                        <div className="font-semibold text-sm">Lifetime Budget</div>
                                        <div className="text-xs text-gray-500">Fixed total for entire flight</div>
                                    </button>
                                </div>
                            </div>

                            <div>
                                <label className="block text-sm font-medium text-gray-700 mb-2">
                                    {campaignData.budgetScheduleType === 'LIFETIME'
                                        ? 'Lifetime Budget (USD) — Total for entire flight'
                                        : 'Daily Budget (USD)'}
                                </label>
                                <div className="relative">
                                    <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                                        <span className="text-gray-500">$</span>
                                    </div>
                                    <input
                                        type="number"
                                        value={campaignData.budgetScheduleType === 'LIFETIME'
                                            ? (campaignData.lifetimeBudget || '')
                                            : (campaignData.dailyBudget || '')}
                                        onChange={(e) => {
                                            const val = parseInt(e.target.value) || 0;
                                            if (campaignData.budgetScheduleType === 'LIFETIME') {
                                                handleInputChange('lifetimeBudget', val);
                                            } else {
                                                handleInputChange('dailyBudget', val);
                                            }
                                        }}
                                        placeholder={campaignData.budgetScheduleType === 'LIFETIME' ? '3000' : '100'}
                                        min="1"
                                        step="1"
                                        className="w-full pl-7 pr-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-amber-500 focus:border-transparent"
                                    />
                                </div>
                                {/* Implied daily spend helper for lifetime */}
                                {campaignData.budgetScheduleType === 'LIFETIME' && campaignData.lifetimeBudget > 0 && campaignData.endTime && (() => {
                                    const days = Math.max(1, Math.round((new Date(campaignData.endTime) - new Date()) / 86400000));
                                    const implied = (campaignData.lifetimeBudget / days).toFixed(2);
                                    return (
                                        <p className="text-xs text-gray-500 mt-1">
                                            ≈ ${implied}/day over ~{days} days. Facebook paces across all calendar days including unscheduled ones.
                                        </p>
                                    );
                                })()}
                            </div>

                            {/* End Date — required for lifetime budget */}
                            {campaignData.budgetScheduleType === 'LIFETIME' && (
                                <div>
                                    <label className="block text-sm font-medium text-gray-700 mb-2">
                                        Campaign End Date & Time *
                                    </label>
                                    <input
                                        type="datetime-local"
                                        value={campaignData.endTime || ''}
                                        onChange={(e) => handleInputChange('endTime', e.target.value)}
                                        className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-amber-500 focus:border-transparent"
                                    />
                                    <p className="text-xs text-gray-500 mt-1">Required for lifetime budget. Must be a future date.</p>
                                </div>
                            )}

                            <div>
                                <label className="block text-sm font-medium text-gray-700 mb-2">
                                    Bid Strategy
                                </label>
                                <select
                                    value={campaignData.bidStrategy}
                                    onChange={(e) => handleInputChange('bidStrategy', e.target.value)}
                                    className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-amber-500 focus:border-transparent"
                                >
                                    <option value="">Select bid strategy...</option>
                                    {BID_STRATEGIES.map(strategy => (
                                        <option key={strategy.value} value={strategy.value}>{strategy.label}</option>
                                    ))}
                                </select>
                            </div>

                            {/* Bid Amount - Required for Cost Cap and Bid Cap strategies */}
                            {(campaignData.bidStrategy === 'COST_CAP' || campaignData.bidStrategy === 'LOWEST_COST_WITH_BID_CAP') && (
                                <div>
                                    <label className="block text-sm font-medium text-gray-700 mb-2">
                                        {campaignData.bidStrategy === 'COST_CAP' ? 'Cost Cap Amount (USD)' : 'Bid Cap Amount (USD)'} *
                                    </label>
                                    <div className="relative">
                                        <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                                            <span className="text-gray-500">$</span>
                                        </div>
                                        <input
                                            type="number"
                                            value={campaignData.bidAmount || ''}
                                            onChange={(e) => handleInputChange('bidAmount', parseFloat(e.target.value) || 0)}
                                            placeholder="10.00"
                                            min="0.01"
                                            step="0.01"
                                            className="w-full pl-7 pr-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-amber-500 focus:border-transparent"
                                        />
                                    </div>
                                    <p className="text-xs text-gray-500 mt-1">
                                        {campaignData.bidStrategy === 'COST_CAP'
                                            ? 'Maximum average cost per result you want to maintain'
                                            : 'Maximum bid amount for each auction'}
                                    </p>
                                </div>
                            )}
                        </>
                    )}
                </div>
            )}

            {/* Navigation */}
            <div className="mt-8 flex justify-between">
                {onBack && (
                    <button
                        onClick={onBack}
                        className="px-6 py-3 text-gray-600 hover:text-gray-800 font-medium"
                    >
                        Back
                    </button>
                )}
                <button
                    onClick={handleNext}
                    disabled={loading}
                    className="ml-auto flex items-center gap-2 px-6 py-3 bg-amber-600 text-white rounded-lg font-medium hover:bg-amber-700 disabled:bg-gray-300 disabled:cursor-not-allowed"
                >
                    {loading ? 'Saving...' : 'Next Step'} <ChevronRight size={20} />
                </button>
            </div>
        </div>
    );
};

export default CampaignStep;
