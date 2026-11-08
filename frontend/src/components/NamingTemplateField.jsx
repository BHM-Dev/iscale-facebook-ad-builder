import React from 'react';
import { Settings2 } from 'lucide-react';
import { missingNamingTokens, parseName, resolveNamingTemplate } from '../lib/namingTemplates';

const labelForToken = token => token.replace(/_/g, ' ');

const NamingTemplateField = ({
    value,
    onChange,
    onManualChange,
    placeholder,
    tokens = {},
    scope,
    preset,
    template,
    manuallyEdited = false,
    onOpenNaming,
    onUseTemplate,
    disabled = false,
    patternMode = false,
}) => {
    const pattern = template || preset?.templates?.[scope] || '';
    const missing = missingNamingTokens(pattern, tokens);
    const generated = resolveNamingTemplate(pattern, tokens, {
        uppercase: Boolean(preset?.uppercase && scope !== 'ad'),
        keepMissing: true,
    });
    const matched = !manuallyEdited && missing.length === 0 && Boolean(parseName(value, pattern));
    const badge = patternMode
        ? { text: 'template', className: 'bg-indigo-50 text-indigo-700' }
        : manuallyEdited
        ? { text: 'custom', className: 'bg-gray-100 text-gray-600' }
        : missing.length
            ? { text: `fill ${missing.map(labelForToken).join(', ')}`, className: 'bg-amber-50 text-amber-700' }
            : matched
                ? { text: '✓ matches', className: 'bg-emerald-50 text-emerald-700' }
                : { text: 'custom', className: 'bg-gray-100 text-gray-600' };

    return <div>
        <div className="flex items-center gap-2 rounded-lg border border-gray-300 bg-white px-3 focus-within:border-transparent focus-within:ring-2 focus-within:ring-amber-500">
            <input
                type="text"
                value={value}
                disabled={disabled}
                onChange={event => (onManualChange || onChange)(event.target.value)}
                placeholder={placeholder}
                className="min-w-0 flex-1 border-0 bg-transparent px-1 py-2 focus:outline-none disabled:bg-gray-50"
            />
            <span className={`shrink-0 rounded-full px-2 py-0.5 text-[11px] font-bold ${badge.className}`}>{badge.text}</span>
        </div>
        <div className="mt-1.5 flex flex-wrap items-center gap-3 text-xs">
            {manuallyEdited && onUseTemplate && <button type="button" className="font-semibold text-amber-700 hover:text-amber-900" onClick={() => onUseTemplate(generated)}>Use template</button>}
            {onOpenNaming && <button type="button" className="inline-flex items-center gap-1 font-semibold text-indigo-600 hover:text-indigo-800" onClick={onOpenNaming}><Settings2 size={12} />Naming</button>}
            {!preset?.saved && <span className="text-gray-400">Shared setup not saved yet</span>}
        </div>
    </div>;
};

export default NamingTemplateField;
