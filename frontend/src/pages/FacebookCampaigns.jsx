import React, { useState, useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import { Check, Target, Users, Image as ImageIcon, CreditCard, Megaphone, CheckCircle2, RefreshCw, ChevronLeft, ChevronRight } from 'lucide-react';
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

// Right-column summary rail — renders only from CampaignContext + the launchSummary
// snapshot each step pushes into it (see CampaignContext.jsx). Never re-derives a
// count itself, so it can't drift from what the step that owns that number shows.
const SummaryRow = ({ label, value }) => (
    <div className="grid grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)] items-start gap-3 py-1 text-sm">
        <span className="min-w-0 text-gray-500">{label}</span>
        <span className={`min-w-0 break-words text-right font-medium leading-5 ${value ? 'text-gray-900' : 'text-gray-400'}`}>
            {value || 'Not selected'}
        </span>
    </div>
);

const LaunchSummaryPanel = ({ currentStep, batchMode, selectedAdAccount, campaignData, adsetData, creativeData, launchSummary, isExpanded, onToggle }) => {
    const creativeSource = batchMode === 'match-import'
        ? 'Naming Convention Import'
        : creativeData?.creatives?.length
        ? (creativeData.creatives.some(c => c.source === 'drive') ? 'Drive Creative Library' : 'Upload / Generated Ads')
        : null;

    return (
        <div>
            <button
                type="button"
                onClick={onToggle}
                aria-expanded={isExpanded}
                className={`flex w-full items-center rounded-md py-1 text-left hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-amber-500 ${isExpanded ? 'justify-between px-1 gap-3' : 'justify-center px-0'}`}
                title={isExpanded ? 'Collapse Launch Plan' : 'Expand Launch Plan'}
            >
                {isExpanded && <span className="text-xs font-semibold uppercase tracking-wide text-gray-400">Launch Plan</span>}
                <span className={`flex items-center text-xs font-medium text-gray-500 ${isExpanded ? 'gap-2' : ''}`}>
                    {!isExpanded ? <ChevronLeft size={18} /> : null}
                    {isExpanded && <>
                    {launchSummary.totalAds ?? '—'} ads
                    <ChevronRight size={16} />
                    </>}
                </span>
            </button>
            {isExpanded && <>
            <div className="divide-y divide-gray-100">
                <SummaryRow label="Account" value={selectedAdAccount?.name} />
                <SummaryRow label="Campaign" value={campaignData?.name} />
                <SummaryRow label="Ad set" value={adsetData?.name} />
                <SummaryRow label="Facebook Page" value={creativeData?.pageName || creativeData?.pageId} />
                <SummaryRow label="Creative source" value={creativeSource} />
            </div>
            <div className="mt-3 pt-3 border-t border-gray-100 divide-y divide-gray-100">
                <div className="flex items-baseline justify-between gap-3 text-sm py-1">
                    <span className="text-gray-500">Creatives</span>
                    <span className="text-right font-medium text-gray-900">{launchSummary.creativeCount ?? '—'}</span>
                </div>
                <div className="flex items-baseline justify-between gap-3 text-sm py-1">
                    <span className="text-gray-500">Headlines</span>
                    <span className="text-right font-medium text-gray-900">{launchSummary.headlineCount ?? '—'}</span>
                </div>
                <div className="flex items-baseline justify-between gap-3 text-sm py-1">
                    <span className="text-gray-500">Bodies</span>
                    <span className="text-right font-medium text-gray-900">{launchSummary.bodyCount ?? '—'}</span>
                </div>
                <div className="flex items-baseline justify-between gap-3 text-sm py-1.5">
                    <span className="text-gray-700 font-semibold">Total ads</span>
                    <span className="text-right font-bold text-amber-700">{launchSummary.totalAds ?? '—'}</span>
                </div>
                {launchSummary.excludedCount > 0 && (
                    <div className="flex items-baseline justify-between gap-3 text-sm py-1">
                        <span className="text-gray-500">Excluded</span>
                        <span className="text-right font-medium text-gray-900">{launchSummary.excludedCount}</span>
                    </div>
                )}
                <div className="flex items-baseline justify-between gap-3 text-sm py-1">
                    <span className="text-gray-500">Warnings</span>
                    <span className={`text-right font-medium ${launchSummary.warningCount ? 'text-amber-700' : 'text-gray-900'}`}>
                        {launchSummary.warningCount ?? '—'}
                    </span>
                </div>
            </div>
            <div className="mt-3 pt-3 border-t border-gray-100">
                <div className="flex items-baseline justify-between gap-3 text-sm py-1">
                    <span className="text-gray-500">Status</span>
                    <span className={`text-right font-semibold ${currentStep >= 6 ? 'text-emerald-700' : 'text-gray-700'}`}>
                        {currentStep >= 6 ? 'Launched (paused)' : 'Not launched'}
                    </span>
                </div>
            </div>
            </>}
        </div>
    );
};

const FacebookCampaignWizardInner = () => {
    const [currentStep, setCurrentStep] = useState(1);
    const [isLaunchPlanExpanded, setIsLaunchPlanExpanded] = useState(false);
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
    const { selectedAdAccount, campaignData, adsetData, creativeData, launchSummary, setLaunchSummary } = useCampaign();

    // Switching between standard combinations and naming-convention import is a
    // different build path. Clear the previous path's counts before the new
    // step mounts and recalculates them, so the summary rail never displays
    // stale totals during the transition.
    const handleBatchModeChange = (nextMode) => {
        setLaunchSummary(prev => ({
            ...prev,
            creativeCount: null,
            headlineCount: null,
            bodyCount: null,
            totalAds: null,
            warningCount: null,
            readyCount: null,
            excludedCount: null,
        }));
        setBatchMode(nextMode);
    };
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
        { id: 1, label: 'Account', icon: CreditCard, description: 'Choose which Meta ad account to build in.' },
        { id: 2, label: 'Campaign', icon: Target, description: 'Pick an existing campaign or create a new one.' },
        { id: 3, label: 'Ad Set', icon: Users, description: 'Pick an existing ad set or create a new one.' },
        { id: 4, label: 'Creative', icon: ImageIcon, description: 'Add media, copy, and destination details.' },
        { id: 5, label: 'Review', icon: Megaphone, description: 'Check every ad before it reaches Meta.' },
        { id: 6, label: 'Launch', icon: CheckCircle2, description: 'Ads are created as paused, ready to activate.' },
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
        <div className="max-w-[1400px] mx-auto space-y-6">
            {/* Context header — title stays put, but the breadcrumb below it is what
                keeps account/campaign/ad set visible for the rest of the flow instead of
                only during Step 1. Each crumb only appears once its step is behind us
                (isCompleted), and clicking one jumps back via the existing goToStep. */}
            <div>
                <h1 className="text-3xl font-bold text-gray-900 mb-2 flex items-center gap-3">
                    <Megaphone size={32} className="text-amber-600" />
                    Launch Ads
                </h1>
                {(selectedAdAccount || campaignData?.name || adsetData?.name) && currentStep > 1 ? (
                    <div className="flex items-center gap-1.5 text-sm flex-wrap">
                        {selectedAdAccount && (
                            <button
                                type="button"
                                onClick={() => goToStep(1)}
                                className="rounded-md px-1.5 py-0.5 font-medium text-gray-700 hover:bg-amber-50 hover:text-amber-800 transition-colors"
                            >
                                {selectedAdAccount.name}
                            </button>
                        )}
                        {currentStep > 2 && campaignData?.name && (
                            <>
                                <span className="text-gray-300">/</span>
                                <button
                                    type="button"
                                    onClick={() => goToStep(2)}
                                    className="rounded-md px-1.5 py-0.5 font-medium text-gray-700 hover:bg-amber-50 hover:text-amber-800 transition-colors"
                                >
                                    {campaignData.name}
                                </button>
                            </>
                        )}
                        {currentStep > 3 && adsetData?.name && (
                            <>
                                <span className="text-gray-300">/</span>
                                <button
                                    type="button"
                                    onClick={() => goToStep(3)}
                                    className="rounded-md px-1.5 py-0.5 font-medium text-gray-700 hover:bg-amber-50 hover:text-amber-800 transition-colors"
                                >
                                    {adsetData.name}
                                </button>
                            </>
                        )}
                    </div>
                ) : (
                    <p className="text-gray-600">Create and manage your Facebook ad campaigns</p>
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

            {/* Launcher shell — three regions: step rail (left, desktop only — mobile
                keeps the horizontal progress bar below since a vertical rail doesn't
                fit a narrow screen), current workspace (center, unchanged step
                components), launch summary rail (right). Full responsive collapse of
                the summary rail into a mobile drawer is Phase 1B — for now it just
                stacks full-width under the workspace, which keeps every screen size
                free of horizontal overflow. */}
            <div className={`grid grid-cols-1 items-start gap-5 ${isLaunchPlanExpanded ? 'lg:grid-cols-[190px_minmax(0,1fr)_260px]' : 'lg:grid-cols-[190px_minmax(0,1fr)_44px]'}`}>
                {/* Desktop step rail */}
                <div className="hidden lg:block bg-white rounded-xl shadow-sm border border-gray-200 p-4 lg:sticky lg:top-4">
                    <div className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">Launch Steps</div>
                    <ol className="space-y-1">
                        {steps.map((step) => {
                            const isCompleted = step.id < currentStep;
                            const isCurrent = step.id === currentStep;
                            const isBlocked = step.id > currentStep;
                            return (
                                <li key={step.id}>
                                    <button
                                        type="button"
                                        onClick={() => goToStep(step.id)}
                                        disabled={!isCompleted}
                                        title={isBlocked
                                            ? 'Complete the steps above first'
                                            : isCompleted
                                                ? `Edit ${step.label} — your current selections stay saved`
                                                : undefined}
                                        aria-label={isCompleted ? `Edit ${step.label}; current selections stay saved` : step.label}
                                        className={`w-full flex items-start gap-2.5 rounded-lg px-2.5 py-2 text-left transition-colors ${isCurrent ? 'bg-amber-50 border border-amber-200' : isCompleted ? 'hover:bg-gray-50 cursor-pointer' : 'cursor-default'}`}
                                    >
                                        <span className={`mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full ${isCompleted || isCurrent ? 'bg-amber-600 text-white' : 'bg-gray-100 text-gray-400'}`}>
                                            {isCompleted ? <Check size={14} /> : <step.icon size={13} />}
                                        </span>
                                        <span className="min-w-0">
                                            <span className={`block text-sm font-medium ${isCurrent ? 'text-amber-900' : isCompleted ? 'text-gray-700' : 'text-gray-400'}`}>
                                                {step.label}
                                            </span>
                                            {isCurrent && (
                                                <span className="block text-xs text-amber-700 mt-0.5">{step.description}</span>
                                            )}
                                        </span>
                                    </button>
                                </li>
                            );
                        })}
                    </ol>
                </div>

                {/* Mobile compact progress bar — same step data, horizontal layout,
                    the only form that fits a narrow screen without a redesign. */}
                <div className="lg:hidden bg-white rounded-xl shadow-sm border border-gray-200 p-4">
                    <div className="flex justify-between items-center relative">
                        <div className="absolute top-1/2 left-0 w-full h-1 bg-gray-100 -z-10 rounded-full" />
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
                </div>

                {/* Center: current workspace — unchanged step components, just wrapped */}
                <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
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
                            <BatchModeToggle batchMode={batchMode} setBatchMode={handleBatchModeChange} />
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
                            <h2 className="text-3xl font-bold mb-4">Ads Created as Paused</h2>
                            <p className="text-gray-600 mb-8">
                                Your ads were created in Meta with delivery paused. In Ads Manager, activate the campaign, the applicable ad set, and the new ads; if this batch used an already-active ad set, activate only the new ads.
                            </p>
                            <Link
                                to="/campaign-performance"
                                className="inline-flex items-center gap-2 rounded-lg bg-amber-600 px-5 py-2.5 text-sm font-semibold text-white hover:bg-amber-700"
                            >
                                Open Campaign Performance
                            </Link>
                        </div>
                    )}
                </div>
                </div>

                {/* Launch Plan summary rail */}
                <div className={`min-w-0 bg-white rounded-xl border border-gray-200 shadow-sm lg:sticky lg:top-4 lg:max-h-[calc(100vh-2rem)] lg:overflow-y-auto ${isLaunchPlanExpanded ? 'p-4' : 'p-2'}`}>
                    <LaunchSummaryPanel
                        currentStep={currentStep}
                        batchMode={batchMode}
                        selectedAdAccount={selectedAdAccount}
                        campaignData={campaignData}
                        adsetData={adsetData}
                        creativeData={creativeData}
                        launchSummary={launchSummary}
                        isExpanded={isLaunchPlanExpanded}
                        onToggle={() => setIsLaunchPlanExpanded(expanded => !expanded)}
                    />
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
