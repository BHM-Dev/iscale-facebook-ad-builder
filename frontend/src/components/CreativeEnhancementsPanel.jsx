import React, { useState } from 'react';

export const CREATIVE_ENHANCEMENT_OPTIONS = [
    { key: 'advantage_plus_creative', label: 'Advantage+ Creative', description: 'Allow Meta to apply its available creative optimizations.' },
    { key: 'enhance_cta', label: 'CTA Enhancement', description: 'Allow Meta to optimize the call-to-action presentation.' },
    { key: 'image_animation', label: 'Image Animation', description: 'Allow Meta to animate eligible image creatives.' },
    { key: 'image_brightness_and_contrast', label: 'Brightness & Contrast', description: 'Allow Meta to adjust image brightness and contrast.' },
    { key: 'image_templates', label: 'Image Templates', description: 'Allow Meta to apply eligible image template treatments.' },
    { key: 'image_touchups', label: 'Image Touchups', description: 'Allow Meta to apply eligible image touchups.' },
    { key: 'image_uncrop', label: 'Image Uncrop', description: 'Allow Meta to expand an image for placement fit.' },
    { key: 'site_extensions', label: 'Site Extensions', description: 'Allow eligible site extension treatments.' },
    { key: 'standard_enhancements', label: 'Standard Enhancements', description: 'Opt into Meta’s standard enhancement bundle.' },
    { key: 'text_generation', label: 'Text Generation', description: 'Allow Meta to generate eligible text variations.' },
    { key: 'text_optimizations', label: 'Text Optimizations', description: 'Allow Meta to optimize eligible text variations.' },
];

export default function CreativeEnhancementsPanel({ value = {}, onChange, className = '' }) {
    const [isOpen, setIsOpen] = useState(false);
    const enabledCount = Object.values(value).filter(Boolean).length;
    const toggle = (key) => onChange({ ...value, [key]: !value[key] });

    return (
        <div className={`border border-gray-200 rounded-lg bg-gray-50 overflow-hidden ${className}`}>
            <button type="button" onClick={() => setIsOpen(prev => !prev)} className="w-full flex items-center justify-between px-4 py-3 text-left text-sm font-semibold text-gray-800 hover:bg-gray-100">
                <span className="flex items-center gap-2">
                    Creative Enhancements
                    <span className="text-xs font-normal text-gray-500">optional · default off</span>
                    {enabledCount > 0 && <span className="px-2 py-0.5 rounded-full bg-amber-100 text-amber-800 text-xs font-medium">{enabledCount} enabled</span>}
                </span>
                <span className="text-xs text-gray-500">{isOpen ? 'Hide' : 'Show'}</span>
            </button>
            {isOpen && <div className="border-t border-gray-200 px-4 py-3 space-y-2">
                {/* "per ad request" read as "set this separately for each ad" in a
                    batch context (joel-perspective pre-push review) — this panel is
                    shown once per session/batch and its selection applies to every
                    ad created in that session, on all four surfaces it now appears
                    on. Wording below is accurate for both the single-ad and
                    bulk/batch cases. */}
                <p className="text-xs text-gray-500 mb-3">Applies to every ad created in this session. Nothing is sent to Meta unless you enable a toggle.</p>
                {CREATIVE_ENHANCEMENT_OPTIONS.map(option => <label key={option.key} className="flex items-start gap-3 rounded-md px-2 py-2 hover:bg-white cursor-pointer">
                    <input type="checkbox" checked={Boolean(value[option.key])} onChange={() => toggle(option.key)} className="mt-0.5 rounded text-amber-600 focus:ring-amber-500" />
                    <span><span className="block text-sm font-medium text-gray-700">{option.label}</span><span className="block text-xs text-gray-500">{option.description}</span></span>
                </label>)}
            </div>}
        </div>
    );
}
