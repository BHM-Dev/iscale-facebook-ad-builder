import React from 'react';
import { useNavigate } from 'react-router-dom';
import { FileImage, Video, Zap, Shuffle, ArrowRight } from 'lucide-react';

const TOOLS = [
    {
        path: '/image-ads',
        icon: FileImage,
        iconBg: 'bg-amber-100',
        iconColor: 'text-amber-600',
        borderHover: 'hover:border-amber-200',
        ctaColor: 'text-amber-600',
        title: 'Image Ad',
        description: 'Guided wizard — select a brand, product, copy, and template, then generate a polished image ad.',
    },
    {
        path: '/batch-generate',
        icon: Zap,
        iconBg: 'bg-violet-100',
        iconColor: 'text-violet-600',
        borderHover: 'hover:border-violet-200',
        ctaColor: 'text-violet-600',
        title: 'Batch Generate',
        badge: 'Fast',
        description: 'Have copy variants ready? Upload a reference image and generate one creative per variant in a single run.',
    },
    {
        path: '/ad-remix',
        icon: Shuffle,
        iconBg: 'bg-green-100',
        iconColor: 'text-green-600',
        borderHover: 'hover:border-green-200',
        ctaColor: 'text-green-600',
        title: 'Ad Remix',
        description: 'Deconstruct a winning ad into its blueprint and regenerate it with your own brand, product, and copy.',
    },
    {
        path: '/video-ads',
        icon: Video,
        iconBg: 'bg-blue-100',
        iconColor: 'text-blue-600',
        borderHover: 'hover:border-blue-200',
        ctaColor: 'text-blue-600',
        title: 'Video Ad',
        description: 'Generate video ads from product shots or stock footage. Ideal for Reels, Stories, and in-feed video.',
    },
];

export default function CreateAds() {
    const navigate = useNavigate();

    return (
        <div className="max-w-5xl mx-auto">
            <div className="mb-8">
                <h1 className="text-3xl font-bold text-gray-900">Build Creatives</h1>
                <p className="text-gray-600 mt-2">Choose your workflow</p>
            </div>

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
                                <span className="absolute top-4 right-4 text-xs font-semibold px-2 py-0.5 rounded-full bg-violet-100 text-violet-700">
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
