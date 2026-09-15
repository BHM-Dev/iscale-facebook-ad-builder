import React, { useRef, useState } from 'react';
import { ChevronDown, Plus, Trash2, X } from 'lucide-react';
import {
    deleteNamingTemplate,
    getSavedTemplates,
    resolveNamingTemplate,
    saveNamingTemplate
} from '../lib/namingTemplates';

const NamingTemplateField = ({ value, onChange, placeholder, tokens, tokenList, scope }) => {
    const [isOpen, setIsOpen] = useState(false);
    const [isSaving, setIsSaving] = useState(false);
    const [templates, setTemplates] = useState(() => getSavedTemplates(scope));
    const [labelDraft, setLabelDraft] = useState('');
    const [patternDraft, setPatternDraft] = useState(value || '');
    const [saveError, setSaveError] = useState('');
    const patternInputRef = useRef(null);

    const openSaveForm = () => {
        setPatternDraft(value || '');
        setLabelDraft('');
        setSaveError('');
        setIsSaving(true);
        setIsOpen(true);
    };

    const handleSave = () => {
        const label = labelDraft.trim();
        const pattern = patternDraft.trim();
        if (!label || !pattern) return;

        const savedTemplate = saveNamingTemplate(scope, label, pattern);
        if (!savedTemplate) {
            setSaveError('Could not save locally. Check browser storage and try again.');
            return;
        }
        setTemplates(getSavedTemplates(scope));
        setIsSaving(false);
    };

    const handleDelete = (id) => {
        setTemplates(deleteNamingTemplate(scope, id));
    };

    const insertToken = (key) => {
        const token = `{${key}}`;
        const input = patternInputRef.current;
        if (!input) {
            setPatternDraft(current => `${current}${token}`);
            return;
        }

        const start = input.selectionStart ?? patternDraft.length;
        const end = input.selectionEnd ?? start;
        const nextPattern = `${patternDraft.slice(0, start)}${token}${patternDraft.slice(end)}`;
        setPatternDraft(nextPattern);
        requestAnimationFrame(() => {
            input.focus();
            const cursor = start + token.length;
            input.setSelectionRange(cursor, cursor);
        });
    };

    return (
        <>
            <input
                type="text"
                value={value}
                onChange={(e) => onChange(e.target.value)}
                placeholder={placeholder}
                className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-amber-500 focus:border-transparent"
            />

            <div className="relative mt-2">
                <button
                    type="button"
                    onClick={() => setIsOpen(current => !current)}
                    className="inline-flex items-center gap-1.5 text-xs font-medium text-gray-600 hover:text-gray-900"
                    aria-expanded={isOpen}
                >
                    Templates
                    <ChevronDown size={14} className={isOpen ? 'rotate-180' : ''} />
                </button>

                {isOpen && (
                    <div className="mt-2 rounded-lg border border-gray-200 bg-white p-3 shadow-sm">
                        {templates.length > 0 ? (
                            <div className="space-y-2">
                                {templates.map(template => (
                                    <div key={template.id} className="flex items-start gap-2 rounded-md bg-gray-50 p-2">
                                        <button
                                            type="button"
                                            onClick={() => onChange(resolveNamingTemplate(template.pattern, tokens))}
                                            className="min-w-0 flex-1 text-left"
                                        >
                                            <span className="block truncate text-xs font-semibold text-gray-800">{template.label}</span>
                                            <span className="block truncate text-xs text-gray-500">{resolveNamingTemplate(template.pattern, tokens)}</span>
                                        </button>
                                        <button
                                            type="button"
                                            onClick={() => handleDelete(template.id)}
                                            className="rounded p-1 text-gray-400 hover:bg-red-50 hover:text-red-600"
                                            aria-label={`Delete ${template.label} template`}
                                        >
                                            <Trash2 size={14} />
                                        </button>
                                    </div>
                                ))}
                            </div>
                        ) : (
                            <p className="text-xs text-gray-500">No saved templates yet.</p>
                        )}

                        {!isSaving ? (
                            <button
                                type="button"
                                onClick={openSaveForm}
                                className="mt-3 inline-flex items-center gap-1 text-xs font-medium text-amber-700 hover:text-amber-900"
                            >
                                <Plus size={14} />
                                Save current name as template
                            </button>
                        ) : (
                            <div className="mt-3 border-t border-gray-100 pt-3">
                                <div className="mb-2 flex items-center justify-between">
                                    <span className="text-xs font-semibold text-gray-700">New template</span>
                                    <button type="button" onClick={() => setIsSaving(false)} className="text-gray-400 hover:text-gray-700" aria-label="Cancel saving template">
                                        <X size={14} />
                                    </button>
                                </div>
                                <input
                                    type="text"
                                    value={labelDraft}
                                    onChange={(e) => setLabelDraft(e.target.value)}
                                    placeholder="Template name"
                                    className="mb-2 w-full rounded-md border border-gray-300 px-2.5 py-1.5 text-xs focus:border-amber-500 focus:ring-1 focus:ring-amber-500"
                                />
                                <input
                                    ref={patternInputRef}
                                    type="text"
                                    value={patternDraft}
                                    onChange={(e) => setPatternDraft(e.target.value)}
                                    placeholder="Pattern, e.g. {date} - Auto Insurance"
                                    className="w-full rounded-md border border-gray-300 px-2.5 py-1.5 text-xs focus:border-amber-500 focus:ring-1 focus:ring-amber-500"
                                />
                                <div className="mt-2 flex flex-wrap gap-1">
                                    {tokenList.map(token => (
                                        <button
                                            key={token.key}
                                            type="button"
                                            onClick={() => insertToken(token.key)}
                                            className="rounded-full bg-gray-100 px-2 py-1 text-[11px] text-gray-700 hover:bg-amber-100"
                                        >
                                            {`{${token.key}}`}
                                        </button>
                                    ))}
                                </div>
                                <p className="mt-2 truncate text-xs text-gray-500">
                                    Preview: {resolveNamingTemplate(patternDraft, tokens)}
                                </p>
                                {saveError && <p className="mt-2 text-xs text-red-600">{saveError}</p>}
                                <button
                                    type="button"
                                    onClick={handleSave}
                                    disabled={!labelDraft.trim() || !patternDraft.trim()}
                                    className="mt-2 rounded-md bg-amber-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-amber-700 disabled:cursor-not-allowed disabled:opacity-50"
                                >
                                    Save template
                                </button>
                            </div>
                        )}
                    </div>
                )}
            </div>
        </>
    );
};

export default NamingTemplateField;
