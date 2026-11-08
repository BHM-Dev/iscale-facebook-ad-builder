import { useCallback, useEffect, useMemo, useState } from 'react';
import { useToast } from '../context/ToastContext';
import { authFetch } from './facebookApi';
import { safeLocalStorageGet, safeLocalStorageSet } from './safeLocalStorage';
import { DEFAULT_NAMING_TEMPLATES, getSavedTemplates } from './namingTemplates';

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1';
const LEVELS = ['campaign', 'adset', 'ad'];

export const namingAccountId = account => String(account?.accountId || account?.id || account?.account_id || '');

const emptyPreset = accountId => ({
    ad_account_id: accountId,
    brand_code: '',
    tracking_tag: '',
    uppercase: true,
    templates: { ...DEFAULT_NAMING_TEMPLATES },
    waves: [],
    niche_codes: [],
    objective_tags: {},
    saved: false,
});

const mergeRows = (current = [], observed = [], field) => {
    const seen = new Set(current.map(row => String(row[field] || '').trim().toUpperCase()).filter(Boolean));
    return [...current, ...observed.filter(row => {
        const key = String(row[field] || '').trim().toUpperCase();
        if (!key || seen.has(key)) return false;
        seen.add(key);
        return true;
    })];
};

const legacyTemplates = () => Object.fromEntries(LEVELS.map(level => [level, getSavedTemplates(level)]));

export default function useNamingPreset(account) {
    const accountId = typeof account === 'string' ? account : namingAccountId(account);
    const { showError, showSuccess } = useToast();
    const [preset, setPreset] = useState(() => emptyPreset(accountId));
    const [loading, setLoading] = useState(Boolean(accountId));
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState(null);
    const [legacySuggestions, setLegacySuggestions] = useState(legacyTemplates);

    useEffect(() => {
        if (!accountId) {
            setPreset(emptyPreset(''));
            setLoading(false);
            return undefined;
        }
        let alive = true;
        setLoading(true);
        setError(null);
        Promise.all([
            authFetch(`${API_BASE}/naming-presets/${encodeURIComponent(accountId)}`).then(async response => {
                if (!response.ok) throw new Error('Could not load naming settings');
                return response.json();
            }),
            authFetch(`${API_BASE}/naming-presets/${encodeURIComponent(accountId)}/observed-codes`).then(response => response.ok ? response.json() : { waves: [], niche_codes: [] }).catch(() => ({ waves: [], niche_codes: [] })),
        ]).then(([loaded, observed]) => {
            if (!alive) return;
            const legacy = legacyTemplates();
            setLegacySuggestions(legacy);
            const legacyPatterns = Object.fromEntries(LEVELS.map(level => [level, legacy[level].at(-1)?.pattern]));
            setPreset({
                ...emptyPreset(accountId),
                ...loaded,
                templates: {
                    ...DEFAULT_NAMING_TEMPLATES,
                    ...(loaded.templates || {}),
                    ...(!loaded.saved ? Object.fromEntries(Object.entries(legacyPatterns).filter(([, value]) => value)) : {}),
                },
                brand_code: loaded.saved ? loaded.brand_code : (loaded.brand_code || observed.brand_code || ''),
                tracking_tag: loaded.saved ? loaded.tracking_tag : (loaded.tracking_tag || observed.tracking_tag || ''),
                waves: loaded.saved ? (loaded.waves || []) : mergeRows(loaded.waves, observed.waves, 'wave'),
                niche_codes: loaded.saved ? (loaded.niche_codes || []) : mergeRows(loaded.niche_codes, observed.niche_codes, 'niche'),
            });
        }).catch(loadError => {
            if (!alive) return;
            setError(loadError.message);
            showError('Naming settings did not load — names may be incomplete. Reload before saving naming changes.');
            setPreset({ ...emptyPreset(accountId), loadFailed: true });
        }).finally(() => alive && setLoading(false));
        return () => { alive = false; };
    }, [accountId]);

    const trackEvent = useCallback((event, props = {}) => {
        authFetch(`${API_BASE}/daily-close/event`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ event, props }),
        }).catch(() => {});
    }, []);

    const savePreset = useCallback(async (nextPreset = preset) => {
        if (!accountId) {
            showError('Choose an ad account before saving naming settings');
            return null;
        }
        setSaving(true);
        try {
            const body = {
                brand_code: nextPreset.brand_code || '',
                tracking_tag: nextPreset.tracking_tag || '',
                uppercase: nextPreset.uppercase !== false,
                templates: { ...DEFAULT_NAMING_TEMPLATES, ...(nextPreset.templates || {}) },
                waves: nextPreset.waves || [],
                niche_codes: nextPreset.niche_codes || [],
                objective_tags: nextPreset.objective_tags || {},
            };
            const response = await authFetch(`${API_BASE}/naming-presets/${encodeURIComponent(accountId)}`, {
                method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
            });
            const saved = await response.json().catch(() => ({}));
            if (!response.ok) throw new Error(saved.detail || 'Could not save naming settings');
            setPreset(saved);
            try { LEVELS.forEach(level => localStorage.removeItem(`namingTemplates_${level}`)); } catch { /* optional migration cleanup */ }
            setLegacySuggestions({ campaign: [], adset: [], ad: [] });
            safeLocalStorageSet(`namingPresetMigrated_${accountId}`, 'true');
            trackEvent('naming_preset_saved', { level: 'account' });
            showSuccess('Naming settings saved for this ad account');
            return saved;
        } catch (saveError) {
            showError(saveError.message || 'Could not save naming settings');
            return null;
        } finally {
            setSaving(false);
        }
    }, [accountId, preset, showError, showSuccess, trackEvent]);

    const lastWave = safeLocalStorageGet(`namingLastWave_${accountId}`) || '';
    const rememberWave = useCallback(wave => safeLocalStorageSet(`namingLastWave_${accountId}`, wave), [accountId]);
    const presetMatchesAccount = String(preset.ad_account_id || '').replace(/^act_/, '') === String(accountId || '').replace(/^act_/, '');
    const activePreset = presetMatchesAccount ? preset : emptyPreset(accountId);
    const activeLoading = loading || (Boolean(accountId) && !presetMatchesAccount);

    return useMemo(() => ({ accountId, preset: activePreset, setPreset, loading: activeLoading, saving, error, savePreset, legacySuggestions, lastWave, rememberWave, trackEvent }), [accountId, activePreset, activeLoading, saving, error, savePreset, legacySuggestions, lastWave, rememberWave, trackEvent]);
}
