import { safeLocalStorageGet, safeLocalStorageSet } from './safeLocalStorage';

const storageKey = (scope) => `namingTemplates_${scope}`;

// Resolve only the tokens supplied by the caller. Unknown tokens stay visible so
// a typo never silently changes a campaign or ad set name.
export function resolveNamingTemplate(pattern, tokens = {}) {
    return String(pattern || '').replace(/\{([a-zA-Z0-9_]+)\}/g, (match, key) => (
        Object.prototype.hasOwnProperty.call(tokens, key) ? String(tokens[key] ?? '') : match
    ));
}

export function getSavedTemplates(scope) {
    try {
        const parsed = JSON.parse(safeLocalStorageGet(storageKey(scope)) || '[]');
        return Array.isArray(parsed) ? parsed.filter(template => (
            template && template.id && template.label && typeof template.pattern === 'string'
        )) : [];
    } catch (error) {
        console.error('Could not read naming templates', error);
        return [];
    }
}

export function saveNamingTemplate(scope, label, pattern) {
    const template = {
        id: `template_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
        label: String(label).trim(),
        pattern: String(pattern).trim()
    };
    const templates = [...getSavedTemplates(scope), template];
    const saved = safeLocalStorageSet(storageKey(scope), JSON.stringify(templates));
    return saved ? template : null;
}

export function deleteNamingTemplate(scope, id) {
    const templates = getSavedTemplates(scope).filter(template => template.id !== id);
    const saved = safeLocalStorageSet(storageKey(scope), JSON.stringify(templates));
    return saved ? templates : getSavedTemplates(scope);
}
