import React, { useEffect, useMemo, useState } from 'react';
import { Plus, Save, Trash2, X } from 'lucide-react';
import { NAMING_TOKEN_LIST, resolveNamingTemplate } from '../lib/namingTemplates';

const LEVEL_LABELS = { campaign: 'Campaign template', adset: 'Ad set template', ad: 'Ad template' };

const CodeTable = ({ title, rows, setRows, labelKey, limit }) => {
    const update = (index, field, value) => setRows(rows.map((row, rowIndex) => rowIndex === index ? { ...row, [field]: value } : row));
    return <section>
        <div className="mb-2 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-gray-900">{title}</h3>
            <button type="button" disabled={rows.length >= limit} onClick={() => setRows([...rows, { [labelKey]: '', code: '' }])} className="inline-flex items-center gap-1 text-xs font-semibold text-indigo-600 disabled:text-gray-300"><Plus size={13} />Add</button>
        </div>
        <div className="space-y-2">
            {rows.map((row, index) => <div key={index} className="rounded-lg border border-gray-200 bg-gray-50 p-2.5">
                <div className="grid grid-cols-[1fr_92px_28px] gap-2">
                    <input value={row[labelKey] || ''} maxLength={120} onChange={event => update(index, labelKey, event.target.value)} placeholder={labelKey === 'wave' ? 'Vehicle W2' : 'Funeral Homes'} className="rounded-md border border-gray-300 bg-white px-2 py-1.5 text-sm" />
                    <input value={row.code || ''} maxLength={16} onChange={event => update(index, 'code', event.target.value.toUpperCase())} placeholder="Code" className="rounded-md border border-gray-300 bg-white px-2 py-1.5 text-sm font-semibold uppercase" />
                    <button type="button" aria-label={`Remove ${title} row`} onClick={() => setRows(rows.filter((_, rowIndex) => rowIndex !== index))} className="text-gray-400 hover:text-red-600"><Trash2 size={15} /></button>
                </div>
                <p className="mt-1 text-[11px] text-gray-400">{row.seen ? `seen in ${row.seen} ad sets` : 'added manually'}</p>
            </div>)}
            {!rows.length && <p className="rounded-lg border border-dashed border-gray-300 px-3 py-4 text-center text-xs text-gray-400">No codes yet. Add one or save an observed suggestion.</p>}
        </div>
    </section>;
};

function NamingSettingsContents({ onClose, accountName, preset, setPreset, onSave, saving, loading, legacySuggestions = {} }) {
    const [draft, setDraft] = useState(preset);
    const [focusedLevel, setFocusedLevel] = useState('campaign');
    const baseline = useMemo(() => JSON.stringify(preset), [preset]);

    useEffect(() => {
        const closeOnEscape = event => { if (event.key === 'Escape') onClose(); };
        window.addEventListener('keydown', closeOnEscape);
        return () => window.removeEventListener('keydown', closeOnEscape);
    }, [onClose]);
    const dirty = JSON.stringify(draft) !== baseline;
    const hasUnsavedChanges = dirty || !preset.saved;
    const updateTemplate = (level, value) => setDraft(current => ({ ...current, templates: { ...current.templates, [level]: value } }));
    const insertToken = key => updateTemplate(focusedLevel, `${draft.templates?.[focusedLevel] || ''}{${key}}`);
    const save = async () => {
        const saved = await onSave(draft);
        if (saved) {
            setPreset(saved);
            setDraft(saved);
        }
    };

    return <div className="fixed inset-0 z-[100]">
        <button type="button" aria-label="Close naming settings" className="absolute inset-0 bg-gray-950/35 backdrop-blur-[1px]" onClick={onClose} />
        <aside className="absolute inset-y-0 right-0 flex w-full max-w-xl flex-col bg-white shadow-2xl">
            <header className="flex items-start justify-between border-b border-gray-200 px-5 py-4">
                <div><h2 className="text-lg font-bold text-gray-950">Naming setup</h2><p className="mt-0.5 text-xs text-gray-500">{accountName || 'Selected ad account'} · one shared convention</p></div>
                <button type="button" onClick={onClose} className="rounded-lg p-2 text-gray-500 hover:bg-gray-100"><X size={19} /></button>
            </header>
            <div className="flex-1 space-y-6 overflow-y-auto px-5 py-5">
                {loading ? <p className="text-sm text-gray-500">Loading naming setup…</p> : <>
                    <section className="grid grid-cols-2 gap-3">
                        <label className="text-xs font-semibold text-gray-700">Brand code<input maxLength={40} value={draft.brand_code || ''} onChange={event => setDraft(current => ({ ...current, brand_code: event.target.value }))} placeholder="RHO v1" className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm font-normal" /></label>
                        <label className="text-xs font-semibold text-gray-700">Tracking tag<input maxLength={40} value={draft.tracking_tag || ''} onChange={event => setDraft(current => ({ ...current, tracking_tag: event.target.value }))} placeholder="CAPI" className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm font-normal" /></label>
                        <label className="col-span-2 flex items-center gap-2 text-xs font-semibold text-gray-700"><input type="checkbox" checked={draft.uppercase !== false} onChange={event => setDraft(current => ({ ...current, uppercase: event.target.checked }))} className="rounded border-gray-300 text-indigo-600" />Uppercase campaign and ad-set values (brand and concepts keep their case)</label>
                    </section>
                    <section>
                        <h3 className="mb-2 text-sm font-semibold text-gray-900">Templates</h3>
                        <div className="space-y-3">{Object.entries(LEVEL_LABELS).map(([level, label]) => <label key={level} className="block text-xs font-semibold text-gray-700">{label}<input maxLength={300} value={draft.templates?.[level] || ''} onFocus={() => setFocusedLevel(level)} onChange={event => updateTemplate(level, event.target.value)} className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 font-mono text-xs font-normal" />
                            <span className="mt-1 block truncate text-[11px] font-normal text-gray-500">Preview: {resolveNamingTemplate(draft.templates?.[level], { brand_code: draft.brand_code || 'RHO v1', budget_type: 'ABO', objective_tag: '', wave: draft.waves?.[0]?.wave || 'VEHICLE W2', wave_code: draft.waves?.[0]?.code || 'WW8', niche: draft.niche_codes?.[0]?.niche || 'FUNERAL HOMES', niche_code: draft.niche_codes?.[0]?.code || 'FUN', angle: 'FLEET AND CREW', tracking: draft.tracking_tag || 'CAPI', date: new Date(), seq: 1, concept: 'HearseAndStaff', media: 'IMG', ratio: '1x1' }, { uppercase: draft.uppercase && level !== 'ad' })}</span>
                            {(legacySuggestions[level] || []).length > 0 && <span className="mt-1 block text-[11px] font-normal text-gray-400">Browser suggestion: <button type="button" onClick={() => updateTemplate(level, legacySuggestions[level].at(-1).pattern)} className="font-semibold text-indigo-600">use “{legacySuggestions[level].at(-1).label}”</button></span>}
                        </label>)}</div>
                        <div className="mt-3 flex flex-wrap gap-1.5">{NAMING_TOKEN_LIST.map(token => <button key={token.key} type="button" onClick={() => insertToken(token.key)} className="rounded-full border border-gray-200 bg-gray-50 px-2 py-1 font-mono text-[10px] text-gray-600 hover:border-indigo-300 hover:text-indigo-700">{`{${token.key}}`}</button>)}</div>
                    </section>
                    <CodeTable title="Waves" rows={draft.waves || []} setRows={waves => setDraft(current => ({ ...current, waves }))} labelKey="wave" limit={100} />
                    <CodeTable title="Niche codes" rows={draft.niche_codes || []} setRows={niche_codes => setDraft(current => ({ ...current, niche_codes }))} labelKey="niche" limit={500} />
                </>}
            </div>
            <footer className="flex items-center justify-between border-t border-gray-200 px-5 py-4">
                <p className="text-xs text-gray-500">Nothing applies until you save.</p>
                <button type="button" disabled={saving || loading || !hasUnsavedChanges || draft.loadFailed} title={draft.loadFailed ? 'Naming settings failed to load — reload before saving so the shared setup is not overwritten' : undefined} onClick={save} className="relative inline-flex items-center gap-2 rounded-lg bg-gray-950 px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-40"><Save size={15} />{saving ? 'Saving…' : 'Save'}{hasUnsavedChanges && <span className="absolute -right-1 -top-1 h-2.5 w-2.5 rounded-full bg-amber-500 ring-2 ring-white" />}</button>
            </footer>
        </aside>
    </div>;
}

export default function NamingSettingsDrawer({ open, ...props }) {
    return open ? <NamingSettingsContents {...props} /> : null;
}
