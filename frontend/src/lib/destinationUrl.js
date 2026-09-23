/** Normalize clipboard/form input without changing the URL's query semantics. */
export function normalizeDestinationUrl(value) {
    return String(value || '').replace(/[\u200B-\u200D\uFEFF]/g, '').trim();
}

export function isValidDestinationUrl(value) {
    const normalized = normalizeDestinationUrl(value);
    try {
        const parsed = new URL(normalized);
        return (parsed.protocol === 'http:' || parsed.protocol === 'https:') && Boolean(parsed.hostname);
    } catch {
        return false;
    }
}
