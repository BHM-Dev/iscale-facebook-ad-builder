import React, { useState, useEffect, useRef } from 'react';
import { Check, Target, Users, Image as ImageIcon, CreditCard, Megaphone, CheckCircle2, RefreshCw } from 'lucide-react';
import { CampaignProvider, useCampaign } from '../context/CampaignContext';
import { useToast } from '../context/ToastContext';
import AdAccountStep from '../components/AdAccountStep';
import CampaignStep from '../components/CampaignStep';
import AdSetStep from '../components/AdSetStep';
import AdCreativeStep from '../components/AdCreativeStep';
import BulkAdCreation from '../components/BulkAdCreation';
import BulkMatchImport from '../components/BulkMatchImport';

// How long Quick Ad's auto-advance chain (Account → Campaign → Ad Set) is given to
// fully resolve before giving up and letting Joel proceed manually from wherever it
// stalled — a bad/deleted campaign or ad set ID, or a slow Meta fetch, should never
// leave him staring at a step that silently never advances with no explanation.
const QUICK_AD_TIMEOUT_MS = 8000;

// Same idea as Quick Ad's timeout, for the Drive Launch shortcut below — same
// 3-step chain length (Account → Campaign → Ad Set), same failure shape.
const DRIVE_LAUNCH_TIMEOUT_MS = 8000;

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
    const [currentStep, setCurrentStep] = useState(1);
    const [batchMode, setBatchMode] = useState('combinations'); // 'combinations' | 'match-import'
    const [formData, setFormData] = useState({
        adAccountId: null,
        campaignId: null,
        adSetId: null,
        creativeId: null,
    });

    // ── Quick Ad auto-advance (AdBuilder-QuickAd-Feature-Brief.md) ──────────────
    // CampaignPerformance's "Quick Ad" button seeds the exact localStorage cache
    // keys AdAccountStep/CampaignStep/AdSetStep already read for their own
    // "restore last used" behavior, then writes `pendingQuickAd` and navigates
    // here. Rather than forcing currentStep to 4 outright (which would skip past
    // those steps' own mount effects — the ones that actually populate
    // selectedAdAccount/campaignData/adsetData with real Meta data, not just an
    // id), this lets each step mount and run its existing, already-reviewed
    // auto-select-from-cache logic, and advances the instant each one resolves to
    // the intended target — so Joel never has to search for or click any of them,
    // he just watches it land on Creative.
    const { showWarning } = useToast();
    const { selectedAdAccount, campaignData, adsetData } = useCampaign();
    const [quickAdTarget, setQuickAdTarget] = useState(null);
    // Persists past quickAdTarget being cleared — this is what actually answers
    // pre-push review's P0 (joel-perspective): "which account/campaign/ad set did
    // Quick Ad land me on?" needs to stay visible on the Creative/Bulk Ads/Review
    // steps, not just flash during the ~1-2s auto-advance itself.
    const [quickAdResolved, setQuickAdResolved] = useState(null);
    const quickAdTimeoutRef = useRef(null);

    const stopQuickAd = (warningMessage) => {
        // Deliberately reads state via the functional updater, NOT the outer
        // `quickAdTarget` closure variable — the timeout callback that calls this is
        // scheduled once inside the mount-only effect below, so its closure over
        // `quickAdTarget` is permanently stuck at that render's value (null). Only
        // the updater form is guaranteed to see the CURRENT value regardless of
        // which render's closure is calling it. This does mean showWarning (a side
        // effect) runs inside the updater — StrictMode double-invokes updaters in
        // dev, so a real timeout could show the toast twice in dev only (never in
        // prod, pre-push review re-audit: LOW, not worth the correctness tradeoff of
        // "fixing" it the other way).
        clearTimeout(quickAdTimeoutRef.current);
        setQuickAdTarget(current => {
            if (current && warningMessage) showWarning(warningMessage);
            return null;
        });
    };

    useEffect(() => {
        let raw;
        try {
            raw = localStorage.getItem('pendingQuickAd');
        } catch {
            raw = null;
        }
        if (!raw) return;
        try {
            localStorage.removeItem('pendingQuickAd');
        } catch { /* non-fatal */ }
        try {
            const parsed = JSON.parse(raw);
            if (parsed?.ad_account_id && parsed?.fb_campaign_id && parsed?.fb_adset_id) {
                setQuickAdTarget(parsed);
                quickAdTimeoutRef.current = setTimeout(() => {
                    stopQuickAd(
                        parsed.adset_name
                            ? `Couldn't auto-load "${parsed.adset_name}" — continue manually below.`
                            : "Couldn't auto-load the campaign/ad set — continue manually below."
                    );
                }, QUICK_AD_TIMEOUT_MS);
            }
        } catch {
            // Malformed payload — fail open, just behave like a normal visit to this page.
        }
        return () => clearTimeout(quickAdTimeoutRef.current);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    useEffect(() => {
        if (!quickAdTarget) return;
        if (currentStep === 1) {
            if (selectedAdAccount?.id === quickAdTarget.ad_account_id) {
                setCurrentStep(2);
            } else if (selectedAdAccount) {
                // AdAccountStep resolved to SOMETHING, but not the target — e.g. the
                // seeded lastSelectedAdAccountId wasn't in the fetched list (token
                // permission gap, pagination) and it silently fell back to the first
                // account instead. Don't wait out the full timeout showing a wrong
                // account as if it were normal — fail fast with a specific reason.
                // Caught in pre-push review (code-auditor: HIGH).
                stopQuickAd("Quick Ad couldn't find that ad account in your list — continuing manually from here.");
            }
        } else if (currentStep === 2 && campaignData?.fbCampaignId === quickAdTarget.fb_campaign_id) {
            setCurrentStep(3);
        } else if (currentStep === 3 && adsetData?.fbAdsetId === quickAdTarget.fb_adset_id) {
            setQuickAdResolved({
                accountName: selectedAdAccount?.name || '',
                campaignName: campaignData?.name || '',
                adsetName: adsetData?.name || quickAdTarget.adset_name || '',
            });
            setCurrentStep(4);
            clearTimeout(quickAdTimeoutRef.current);
            setQuickAdTarget(null);
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [quickAdTarget, currentStep, selectedAdAccount, campaignData, adsetData]);

    // ── Drive Launch shortcut (Build Creatives → "Launch from Drive") ───────────
    // Unlike Quick Ad, this has no specific account/campaign/ad set target to match
    // against — Joel hasn't picked anything yet, he just wants to skip re-clicking
    // through Account → Campaign → Ad Set when each one already restores its own
    // last-used selection from cache. So this chain just watches for each step to
    // resolve ANYTHING (cache or context) and advances, rather than waiting for a
    // specific id like Quick Ad does. forceExistingMode is required for Campaign/Ad
    // Set — both default to "new" mode otherwise and never run their cache-restore
    // effect at all (see CampaignStep.jsx / AdSetStep.jsx).
    const [driveLaunchActive, setDriveLaunchActive] = useState(false);
    // Persists past driveLaunchActive being cleared — same reasoning as
    // quickAdResolved above. Unlike Quick Ad, this shortcut has no specific target
    // to name up front, so THIS is the only place Joel ever finds out which
    // account/campaign/ad set he actually landed on (pre-push review, joel-
    // perspective: P0 — a shortcut whose whole point is "don't make me re-pick
    // these" must not also make it invisible what got auto-picked; he juggles
    // multiple niches/ad accounts and could otherwise mass-launch Drive creatives
    // into the wrong one without any visible confirmation).
    const [driveLaunchResolved, setDriveLaunchResolved] = useState(null);
    const driveLaunchTimeoutRef = useRef(null);

    const stopDriveLaunch = (warningMessage) => {
        clearTimeout(driveLaunchTimeoutRef.current);
        setDriveLaunchActive(current => {
            if (current && warningMessage) showWarning(warningMessage);
            return false;
        });
    };

    useEffect(() => {
        let raw;
        try {
            raw = localStorage.getItem('pendingDriveLaunch');
        } catch {
            raw = null;
        }
        if (!raw) return;
        try {
            localStorage.removeItem('pendingDriveLaunch');
        } catch { /* non-fatal */ }
        // If Quick Ad's own pending flag is ALSO sitting in localStorage (e.g. two
        // tabs, an interrupted navigation), let Quick Ad's exact-match chain own the
        // auto-advance instead of running both — they'd otherwise both react to the
        // same currentStep/context changes with no precedence between them (pre-push
        // review, code-auditor: MEDIUM).
        let quickAdRaw;
        try {
            quickAdRaw = localStorage.getItem('pendingQuickAd');
        } catch {
            quickAdRaw = null;
        }
        if (quickAdRaw) return;
        setDriveLaunchActive(true);
        driveLaunchTimeoutRef.current = setTimeout(() => {
            stopDriveLaunch("Couldn't auto-resolve an ad account/campaign/ad set — continue manually below.");
        }, DRIVE_LAUNCH_TIMEOUT_MS);
        return () => clearTimeout(driveLaunchTimeoutRef.current);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    useEffect(() => {
        if (!driveLaunchActive) return;
        if (currentStep === 1 && selectedAdAccount) {
            setCurrentStep(2);
        } else if (currentStep === 2 && campaignData?.fbCampaignId) {
            setCurrentStep(3);
        } else if (currentStep === 3 && adsetData?.fbAdsetId) {
            // Capture what actually got auto-selected BEFORE landing on Creative —
            // this is the only place Joel can see it, since unlike Quick Ad there's
            // no named target to show up front (pre-push review: both code-auditor
            // and joel-perspective flagged this as BLOCKING/P0 — a shortcut that
            // silently accepts whatever was last cached, with zero confirmation,
            // risks mass-launching Drive creatives into the wrong niche/ad set).
            setDriveLaunchResolved({
                accountName: selectedAdAccount?.name || '',
                campaignName: campaignData?.name || '',
                adsetName: adsetData?.name || '',
            });
            setCurrentStep(4);
            clearTimeout(driveLaunchTimeoutRef.current);
            setDriveLaunchActive(false);
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [driveLaunchActive, currentStep, selectedAdAccount, campaignData, adsetData]);

    const steps = [
        { id: 1, label: 'Ad Account', icon: CreditCard },
        { id: 2, label: 'Campaign', icon: Target },
        { id: 3, label: 'Ad Set', icon: Users },
        { id: 4, label: 'Creative', icon: ImageIcon },
        { id: 5, label: 'Bulk Ads', icon: Megaphone },
        { id: 6, label: 'Review & Launch', icon: CheckCircle2 },
    ];

    // Manual navigation always wins over the auto-advance chain — the instant Joel
    // clicks Next/Back himself, Quick Ad steps aside rather than racing his click
    // (pre-push review: MEDIUM — an in-flight auto-advance effect could otherwise
    // fire alongside a manual step change and produce a confusing double-jump, or
    // a stale timeout toast for a "failure" that was actually just Joel taking over).
    const handleNext = () => {
        if (quickAdTarget) stopQuickAd(null);
        if (driveLaunchActive) stopDriveLaunch(null);
        if (currentStep < steps.length) {
            setCurrentStep(currentStep + 1);
        }
    };

    const handleBack = () => {
        if (quickAdTarget) stopQuickAd(null);
        if (driveLaunchActive) stopDriveLaunch(null);
        if (currentStep > 1) {
            setCurrentStep(currentStep - 1);
        }
    };

    // Lets Joel jump directly back to any already-completed step (e.g. Ad Account)
    // instead of clicking Back repeatedly — the step tracker rendered these as
    // plain non-interactive icons before, which was the ONLY way to switch ad
    // account/campaign/ad set once past Step 1. That became a real dead end once
    // the page-level "Meta account" banner was hidden on this route (it never
    // actually drove this wizard anyway — see the comment in Layout.jsx — but at
    // least it LOOKED like an escape hatch). Only completed steps are clickable;
    // you can't skip ahead to a step you haven't reached yet.
    const goToStep = (stepId) => {
        if (stepId >= currentStep) return;
        if (quickAdTarget) stopQuickAd(null);
        if (driveLaunchActive) stopDriveLaunch(null);
        setCurrentStep(stepId);
    };

    return (
        <div className="max-w-6xl mx-auto space-y-8">
            {/* Header */}
            <div className="flex items-start justify-between gap-4 flex-wrap">
                <div>
                    <h1 className="text-3xl font-bold text-gray-900 mb-2 flex items-center gap-3">
                        <Megaphone size={32} className="text-amber-600" />
                        Facebook Campaigns
                    </h1>
                    <p className="text-gray-600">Create and manage your Facebook ad campaigns</p>
                </div>
                {/* Always-visible ad account indicator once one is picked — this page's
                    own account selection (Step 1) is a completely separate thing from
                    the "Meta account" banner Layout.jsx hides here (see that file's
                    comment), so without this there was no way to see which account
                    you're building against past Step 1 short of jumping back to check.
                    Clicking it jumps straight back to Ad Account via goToStep. */}
                {selectedAdAccount && currentStep > 1 && (
                    <button
                        type="button"
                        onClick={() => goToStep(1)}
                        className="flex items-center gap-2 rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm hover:border-amber-300 hover:bg-amber-50 transition-colors"
                    >
                        <CreditCard size={15} className="text-gray-400" />
                        <span className="text-gray-500">Ad Account:</span>
                        <span className="font-semibold text-gray-900">{selectedAdAccount.name}</span>
                    </button>
                )}
            </div>

            {/* Quick Ad auto-advance banner — shown only while the auto-select chain
                from CampaignPerformance's "Quick Ad" button is still resolving. Names
                the step it's on (out of 3) so an 8-second wait reads as progress, not
                a frozen page. */}
            {quickAdTarget && (
                <div className="flex items-center gap-2 bg-teal-50 border border-teal-200 rounded-lg px-4 py-3 text-sm text-teal-800">
                    <RefreshCw size={15} className="animate-spin flex-shrink-0" />
                    <span>
                        <strong>Quick Ad:</strong> loading step {Math.min(currentStep, 3)} of 3
                        ({['ad account', 'campaign', 'ad set'][Math.min(currentStep, 3) - 1]})
                        {quickAdTarget.adset_name ? <> for <strong>{quickAdTarget.adset_name}</strong></> : ''} —
                        you'll land on Creative in a moment.
                    </span>
                </div>
            )}

            {/* Drive Launch shortcut banner — same shape as Quick Ad's above. Deliberately
                does NOT say "last-used" — AdAccountStep silently falls back to the first
                fetched account when there's no cache hit, so this can't promise it's
                restoring anything specific, only that it's resolving each step for you
                (pre-push review, code-auditor: HIGH — banner text must not claim more
                than the mechanism can back up). The persistent breadcrumb below is what
                lets Joel actually verify it before he builds or launches anything. */}
            {driveLaunchActive && (
                <div className="flex items-center gap-2 bg-blue-50 border border-blue-200 rounded-lg px-4 py-3 text-sm text-blue-800">
                    <RefreshCw size={15} className="animate-spin flex-shrink-0" />
                    <span>
                        <strong>Launch from Drive:</strong> resolving step {Math.min(currentStep, 3)} of 3
                        ({['ad account', 'campaign', 'ad set'][Math.min(currentStep, 3) - 1]}) —
                        you'll land on Creative in a moment.
                    </span>
                </div>
            )}

            {/* Persistent breadcrumb — this is what actually answers "which account/
                campaign/ad set did Quick Ad land me on," which the transient banner
                above (gone the instant it resolves) doesn't. Stays visible through
                Creative/Bulk Ads/Review so Joel never has to guess before he builds or
                launches against it. Caught in pre-push review (joel-perspective: P0). */}
            {quickAdResolved && currentStep >= 4 && (
                <div className="flex items-center gap-2 bg-teal-50 border border-teal-200 rounded-lg px-4 py-2.5 text-xs text-teal-800">
                    <CheckCircle2 size={14} className="flex-shrink-0" />
                    <span>
                        <strong>Quick Ad</strong> loaded: {quickAdResolved.accountName || 'this account'}
                        {' → '}{quickAdResolved.campaignName || 'this campaign'}
                        {' → '}{quickAdResolved.adsetName || 'this ad set'}
                    </span>
                </div>
            )}

            {/* Same idea for Drive Launch — no target was named up front, so this is
                the first and only place Joel sees what got auto-selected. Includes a
                one-click way to back out to Step 1 in case it's the wrong niche/ad
                account, rather than making him hunt for the right collapsed step header
                (pre-push review, joel-perspective: P0/P2). */}
            {driveLaunchResolved && currentStep >= 4 && (
                <div className="flex items-center justify-between gap-2 bg-blue-50 border border-blue-200 rounded-lg px-4 py-2.5 text-xs text-blue-800">
                    <span className="flex items-center gap-2">
                        <CheckCircle2 size={14} className="flex-shrink-0" />
                        <strong>Launch from Drive</strong> loaded: {driveLaunchResolved.accountName || 'this account'}
                        {' → '}{driveLaunchResolved.campaignName || 'this campaign'}
                        {' → '}{driveLaunchResolved.adsetName || 'this ad set'}
                    </span>
                    <button
                        type="button"
                        onClick={() => { setDriveLaunchResolved(null); setCurrentStep(1); }}
                        className="font-semibold underline shrink-0 hover:text-blue-900"
                    >
                        Not right? Switch
                    </button>
                </div>
            )}

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
                            <button
                                key={step.id}
                                type="button"
                                onClick={() => goToStep(step.id)}
                                disabled={!isCompleted}
                                className={`flex flex-col items-center gap-2 bg-white px-2 ${isCompleted ? 'cursor-pointer' : 'cursor-default'}`}
                            >
                                <div
                                    className={`w-10 h-10 rounded-full flex items-center justify-center transition-all duration-300 ${isCompleted || isCurrent
                                        ? 'bg-amber-600 text-white shadow-md scale-110'
                                        : 'bg-gray-100 text-gray-400'
                                        } ${isCompleted ? 'hover:scale-125' : ''}`}
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
                            </button>
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
                            forceExistingMode={Boolean(quickAdTarget) || driveLaunchActive}
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
                            forceExistingMode={Boolean(quickAdTarget) || driveLaunchActive}
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
