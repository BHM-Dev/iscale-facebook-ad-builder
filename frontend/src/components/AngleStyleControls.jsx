import React from 'react';
import { STYLE_ANGLES, getStyleAngle } from '../data/adStyles';

const VISUAL_FIELDS = [
    ['mood', 'Mood'],
    ['lighting', 'Lighting'],
    ['composition', 'Composition'],
    ['design_style', 'Design Style'],
];

export default function AngleStyleControls({ value = {}, onChange, compact = false }) {
    const applyAngle = (label) => {
        const preset = getStyleAngle(label);
        onChange({
            ...value,
            angle: label,
            ...(preset ? {
                mood: preset.mood,
                lighting: preset.lighting,
                composition: preset.composition,
                design_style: preset.design_style,
                prompt_instruction: preset.promptInstruction,
            } : {}),
        });
    };

    return (
        <div className={`space-y-3 ${compact ? 'rounded-lg bg-gray-50 p-3' : 'rounded-xl border border-amber-200 bg-amber-50/40 p-4'}`}>
            <div>
                <label className="block text-xs font-semibold text-gray-700 mb-1">Angle</label>
                <select
                    value={value.angle || ''}
                    onChange={(e) => applyAngle(e.target.value)}
                    className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 bg-white focus:outline-none focus:ring-2 focus:ring-amber-400"
                >
                    <option value="">Choose an angle…</option>
                    {STYLE_ANGLES.map(angle => <option key={angle.label} value={angle.label}>{angle.label}</option>)}
                </select>
                <p className="text-[11px] text-gray-500 mt-1">Applies a visual starting point. You can override any field below.</p>
            </div>
            {VISUAL_FIELDS.map(([field, label]) => (
                <div key={field}>
                    <label className="block text-[11px] font-medium text-gray-600 mb-1">{label}</label>
                    <input
                        type="text"
                        value={value[field] || ''}
                        onChange={(e) => onChange({ ...value, [field]: e.target.value })}
                        className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 bg-white focus:outline-none focus:ring-2 focus:ring-amber-400"
                    />
                </div>
            ))}
        </div>
    );
}
