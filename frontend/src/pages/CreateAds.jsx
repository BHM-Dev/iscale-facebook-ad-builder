import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { FileImage, Video, Zap, Shuffle, ArrowRight, HardDrive, Rocket } from 'lucide-react';
import { authFetch } from '../lib/facebookApi';

const DRIVE_LAUNCH_TOOL = {
    path: '/facebook-campaigns',
    icon: HardDrive,
    title: 'Launch from Drive',
    description: 'Skip generation — mass-upload and launch ads straight from your synced Google Drive folder. Pick an ad account, campaign, and ad set, then choose "Drive Creative Library" on the Creative step.',
};

const TOOLS = [
    {
        path: '/image-ads',
        icon: FileImage,
        iconBg: 'bg-gray-100',
        iconColor: 'text-gray-700',
        borderHover: 'hover:border-gray-300',
        ctaColor: 'text-gray-900',
        title: 'Image Ad',
        description: 'Guided wizard — select a brand, product, copy, and template, then generate a polished image ad.',
    },
    {
        path: '/batch-generate',
        icon: Zap,
        iconBg: 'bg-gray-100',
        iconColor: 'text-gray-700',
        borderHover: 'hover:border-gray-300',
        ctaColor: 'text-gray-900',
        title: 'Batch Generate',
        badge: 'Fast',
        description: 'Have copy variants ready? Upload a reference image and generate one creative per variant in a single run.',
    },
    {
        path: '/ad-remix',
        icon: Shuffle,
        iconBg: 'bg-gray-100',
        iconColor: 'text-gray-700',
        borderHover: 'hover:border-gray-300',
        ctaColor: 'text-gray-900',
        title: 'Build New Ad',
        description: 'Deconstruct a winning ad into its blueprint and regenerate it with your own brand, product, and copy.',
    },
    {
        path: '/video-ads',
        icon: Video,
        iconBg: 'bg-gray-100',
        iconColor: 'text-gray-700',
        borderHover: 'hover:border-gray-300',
        ctaColor: 'text-gray-900',
        title: 'Video Ad',
        description: 'Generate video ads from product shots or stock footage. Ideal for Reels, Stories, and in-feed video.',
    },
];

export default function CreateAds() {
    const navigate = useNavigate();
    const [launchPacks, setLaunchPacks] = useState([]);

    useEffect(() => {
        let cancelled = false;
        const loadLaunchPacks = async () => {
            try {
                const response = await authFetch(`${import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1'}/launch-packs`);
                if (!response.ok) return;
                const packs = await response.json();
                if (!cancelled) setLaunchPacks(Array.isArray(packs) ? packs : []);
            } catch {
                // Launch Packs are an accelerator, never a reason to block the
                // normal build workflows if the service is temporarily unavailable.
            }
        };
        loadLaunchPacks();
        return () => { cancelled = true; };
    }, []);

    const launchFromDrive = () => {
        // Consumed once by FacebookCampaigns.jsx on mount to auto-advance through
        // Ad Account → Campaign → Ad Set using each step's own last-used cache,
        // landing directly on Creative instead of making Joel re-click through
        // steps that were only ever going to restore the same selection anyway.
        try {
            localStorage.setItem('pendingDriveLaunch', '1');
        } catch { /* non-fatal — worst case Joel clicks through manually */ }
        navigate(DRIVE_LAUNCH_TOOL.path);
    };

    const launchFromPack = (pack) => {
        try {
            // The wizard's existing exact-target resolver reads these per-step
            // cache keys, while pendingLaunchPack makes it verify every ID rather
            // than silently accepting whichever target happens to be last used.
            localStorage.setItem('lastSelectedAdAccountId', pack.ad_account_id);
            localStorage.setItem(`lastSelectedCampaignId_${pack.ad_account_id}`, pack.campaign_id);
            localStorage.setItem(`lastSelectedAdSetId_${pack.campaign_id}`, pack.adset_id);
            localStorage.setItem('pendingLaunchPack', JSON.stringify(pack));
        } catch { /* The wizard will fall back to the normal, explicit flow. */ }
        navigate(DRIVE_LAUNCH_TOOL.path);
    };

    return (
        <div className="max-w-5xl mx-auto">
            <div className="mb-8">
                <h1 className="text-3xl font-bold text-gray-900">Build Creatives</h1>
                <p className="text-gray-600 mt-2">Choose your workflow</p>
            </div>

            <button
                onClick={launchFromDrive}
                className="group w-full flex items-center gap-5 p-6 mb-8 bg-blue-50 rounded-2xl border-2 border-blue-200 hover:border-blue-400 hover:shadow-lg transition-all duration-300 text-left"
            >
                <div className="w-14 h-14 shrink-0 bg-blue-100 rounded-2xl flex items-center justify-center group-hover:scale-110 transition-transform duration-300">
                    <HardDrive size={28} className="text-blue-700" />
                </div>
                <div className="flex-1">
                    <div className="flex items-center gap-2">
                        <h3 className="text-lg font-bold text-gray-900">{DRIVE_LAUNCH_TOOL.title}</h3>
                        <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-blue-100 text-blue-700">Already have creatives?</span>
                    </div>
                    <p className="text-gray-600 text-sm mt-1">{DRIVE_LAUNCH_TOOL.description}</p>
                </div>
                <div className="shrink-0 flex items-center gap-2 text-sm font-semibold text-blue-700 group-hover:gap-3 transition-all">
                    Get Started <ArrowRight size={16} />
                </div>
            </button>

            {launchPacks.length > 0 && (
                <section className="mb-8" aria-label="Saved launch packs">
                    <div className="flex items-baseline justify-between mb-3">
                        <h2 className="text-sm font-semibold text-gray-700">Saved launch packs</h2>
                        <span className="text-xs text-gray-500">Exact account, campaign, and ad set</span>
                    </div>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                        {launchPacks.slice(0, 6).map(pack => (
                            <button
                                key={pack.id}
                                type="button"
                                onClick={() => launchFromPack(pack)}
                                className="group flex items-center gap-3 rounded-xl border border-gray-200 bg-white px-4 py-3 text-left hover:border-blue-300 hover:shadow-sm transition"
                            >
                                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-blue-50 text-blue-700"><Rocket size={17} /></span>
                                <span className="min-w-0 flex-1">
                                    <span className="block truncate text-sm font-semibold text-gray-900">{pack.name}</span>
                                    <span className="block truncate text-xs text-gray-500">
                                        {[pack.ad_account_name || pack.ad_account_id, pack.campaign_name || pack.campaign_id, pack.adset_name || pack.adset_id].filter(Boolean).join(' → ')}
                                    </span>
                                </span>
                                <ArrowRight size={16} className="shrink-0 text-gray-400 group-hover:text-blue-600" />
                            </button>
                        ))}
                    </div>
                </section>
            )}

            <p className="text-sm font-semibold text-gray-500 mb-4">Or generate new creatives</p>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                {TOOLS.map(tool => {
                    const Icon = tool.icon;
                    return (
                        <button
                            key={tool.path}
                            onClick={() => navigate(tool.path)}
                            className={`group relative flex flex-col items-start p-8 bg-white rounded-2xl border-2 border-gray-100 ${tool.borderHover} hover:shadow-xl transition-all duration-300 text-left`}
                        >
                            {tool.badge && (
                                <span className={`absolute top-4 right-4 text-xs font-semibold px-2 py-0.5 rounded-full ${tool.badgeColor || 'bg-gray-100 text-gray-700'}`}>
                                    {tool.badge}
                                </span>
                            )}
                            <div className={`w-14 h-14 ${tool.iconBg} rounded-2xl flex items-center justify-center mb-5 group-hover:scale-110 transition-transform duration-300`}>
                                <Icon size={28} className={tool.iconColor} />
                            </div>
                            <h3 className="text-xl font-bold text-gray-900 mb-2">{tool.title}</h3>
                            <p className="text-gray-500 text-sm leading-relaxed flex-1">{tool.description}</p>
                            <div className={`mt-6 flex items-center gap-2 text-sm font-semibold ${tool.ctaColor} group-hover:gap-3 transition-all`}>
                                Get Started <ArrowRight size={16} />
                            </div>
                        </button>
                    );
                })}
            </div>
        </div>
    );
}
