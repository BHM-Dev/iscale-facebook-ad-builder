import { safeLocalStorageGet, safeLocalStorageSet } from './safeLocalStorage';

export const DEFAULT_NAMING_TEMPLATES = {
    campaign: '{brand_code} | {budget_type} | {objective_tag} | {wave} {niche} | {tracking} | {date:MM.DD.YYYY}',
    adset: '{wave_code}-{niche_code} | {angle}',
    ad: '{wave_code}-{niche_code}-{seq:02}-{concept}-{media}-{ratio}',
};

export const NAMING_TOKEN_LIST = [
    'brand_code', 'budget_type', 'objective_tag', 'wave', 'wave_code', 'niche',
    'niche_code', 'angle', 'tracking', 'date:MM.DD.YYYY', 'seq:02', 'concept',
    'media', 'ratio', 'date', 'objective', 'countries', 'age_range', 'media_name',
    'headline_num', 'body_num', 'campaign_name', 'ad_set_name',
].map(key => ({ key, label: key.replace(/_/g, ' ') }));

const storageKey = scope => `namingTemplates_${scope}`;
// Tokens that are normally blank (e.g. no objective tag for most campaigns): drop silently.
const OPTIONAL_TOKENS = new Set(['objective_tag']);
const TOKEN_RE = /\{([a-zA-Z0-9_]+)(?::([^}]+))?\}/g;
const pad = (value, width) => String(value ?? '').padStart(width, '0');

function formatDate(value, format = 'Mon D') {
    const date = value instanceof Date ? value : value ? new Date(value) : new Date();
    if (Number.isNaN(date.getTime())) return '';
    if (format === 'MM.DD.YYYY') return `${pad(date.getMonth() + 1, 2)}.${pad(date.getDate(), 2)}.${date.getFullYear()}`;
    if (format === 'MM.DD') return `${pad(date.getMonth() + 1, 2)}.${pad(date.getDate(), 2)}`;
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

function cleanName(value) {
    return String(value || '').split('|')
        .map(segment => segment.trim().replace(/--+/g, '-').replace(/^-+|-+$/g, '').trim())
        .filter(Boolean).join(' | ')
        .replace(/\s{2,}/g, ' ').replace(/-+(?=\s*\||$)/g, '').trim();
}

export function resolveNamingTemplate(pattern, tokens = {}, options = {}) {
    const preserved = [];
    const preserve = value => {
        const marker = `\u0000${preserved.length}\u0000`;
        preserved.push(value);
        return marker;
    };
    let resolved = String(pattern || '').replace(TOKEN_RE, (match, key, format) => {
        if (key === 'date') return formatDate(tokens.date, format || 'Mon D');
        if (key === 'seq') return pad(tokens.seq, Math.max(1, String(format || '1').length));
        if (!Object.prototype.hasOwnProperty.call(tokens, key)) return preserve(match);
        const value = String(tokens[key] ?? '');
        if (!value && options.keepMissing && !OPTIONAL_TOKENS.has(key)) return preserve(match);
        if (options.uppercase && ['brand_code', 'concept'].includes(key) && value) {
            return preserve(value);
        }
        return value;
    });
    resolved = cleanName(options.uppercase ? resolved.toUpperCase() : resolved);
    preserved.forEach((value, index) => { resolved = resolved.replace(`\u0000${index}\u0000`, value); });
    return resolved;
}

export function missingNamingTokens(pattern, tokens = {}) {
    return [...String(pattern || '').matchAll(TOKEN_RE)].map(match => match[1])
        .filter((key, index, all) => !['date', 'seq'].includes(key) && !OPTIONAL_TOKENS.has(key)
            && Object.prototype.hasOwnProperty.call(tokens, key)
            && !String(tokens[key] ?? '').trim() && all.indexOf(key) === index);
}

export function conceptFromFilename(name) {
    const base = String(name || '').split(/[\\/]/).at(-1) || '';
    return base.replace(/\.[a-z0-9]+$/i, '')
        .replace(/^[a-z0-9]+-[a-z0-9]+-\d+-/i, '')
        .replace(/-(IMG|VID)-(1x1|4x5|9x16)$/i, '')
        .replace(/[_\s-]+v\d+$/i, '').replace(/[_\s]+/g, '');
}

// `WW8-FUN-02-HearseAndStaff-IMG-1x1.jpg` -> 2. Joel numbers creatives on purpose; keep his number
// so the Meta ad name matches the Drive file. Returns null when the filename carries no sequence.
// `WW8-FUN-02-HearseAndStaff-IMG-4x5.jpg` is already a finished ad name: Joel names files in the
// convention on purpose. Use it verbatim (minus extension) so codes, ratio and version survive.
export function conventionNameFromFilename(name) {
    const base = (String(name || '').split(/[\\/]/).at(-1) || '').replace(/\.[a-z0-9]{2,5}$/i, '').trim();
    return /^[a-z0-9]{1,8}-[a-z0-9]{2,8}-\d{1,3}-\S+/i.test(base) ? base : null;
}

export function seqFromFilename(name) {
    const base = String(name || '').split(/[\\/]/).at(-1) || '';
    const match = /^[a-z0-9]+-[a-z0-9]+-(\d{1,3})-/i.exec(base);
    return match ? Number(match[1]) : null;
}

export function mediaToken(creative = {}) {
    return creative.mediaType === 'video' || creative.format === 'video' || /\.(mp4|mov|webm)$/i.test(creative.name || '') ? 'VID' : 'IMG';
}

export function ratioToken(creative = {}) {
    const source = `${creative.ratio || ''} ${creative.sizeLabel || ''} ${creative.size_name || ''} ${creative.name || ''}`;
    if (/9[:x]16/i.test(source) || creative.format === 'stories') return '9x16';
    if (/4[:x]5/i.test(source)) return '4x5';
    return '1x1';
}

const escapeRegex = value => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

function segmentRegex(segment, keys) {
    let cursor = 0;
    let result = '';
    for (const match of segment.matchAll(TOKEN_RE)) {
        result += escapeRegex(segment.slice(cursor, match.index)).replace(/\\ /g, '\\s+');
        keys.push(match[1]);
        result += `(?<t${keys.length - 1}>.+?)`;
        cursor = match.index + match[0].length;
    }
    return result + escapeRegex(segment.slice(cursor)).replace(/\\ /g, '\\s+');
}

export function parseName(name, template) {
    const segments = String(template || '').split('|').map(value => value.trim());
    const keys = [];
    let expression = '^';
    segments.forEach((segment, index) => {
        const tokenOnly = /^\{[a-zA-Z0-9_]+(?::[^}]+)?\}$/.test(segment);
        const part = segmentRegex(segment, keys);
        if (index === 0) expression += part;
        else if (tokenOnly) expression += `(?:\\s*\\|\\s*${part})?`;
        else expression += `\\s*\\|\\s*${part}`;
    });
    const matcher = new RegExp(`${expression}$`, 'i');
    const rawName = String(name || '');
    const match = [rawName, rawName.replace(/-H\d+B\d+(?:-[b-z])?$/i, ''), rawName.replace(/-[b-z]$/i, '')]
        .map(candidate => candidate.match(matcher)).find(Boolean);
    return match ? Object.fromEntries(keys.map((key, index) => [key, match.groups?.[`t${index}`] || ''])) : null;
}

export function uniqueNames(names) {
    const seen = new Map();
    return names.map(name => {
        const count = seen.get(name) || 0;
        seen.set(name, count + 1);
        return count === 0 ? name : `${name}-${String.fromCharCode(97 + count)}`;
    });
}

export function getSavedTemplates(scope) {
    try {
        const parsed = JSON.parse(safeLocalStorageGet(storageKey(scope)) || '[]');
        return Array.isArray(parsed) ? parsed.filter(template => template && template.id && template.label && typeof template.pattern === 'string') : [];
    } catch { return []; }
}

export function saveNamingTemplate(scope, label, pattern) {
    const template = { id: `template_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`, label: String(label).trim(), pattern: String(pattern).trim() };
    return safeLocalStorageSet(storageKey(scope), JSON.stringify([...getSavedTemplates(scope), template])) ? template : null;
}

export function deleteNamingTemplate(scope, id) {
    const templates = getSavedTemplates(scope).filter(template => template.id !== id);
    return safeLocalStorageSet(storageKey(scope), JSON.stringify(templates)) ? templates : getSavedTemplates(scope);
}
