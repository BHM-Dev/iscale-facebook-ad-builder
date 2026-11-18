// Show-last-data-instantly cache (2026-11-18). A page paints what it showed last time (same account and date
// range) while fresh data loads, instead of a blank skeleton. Memory first, sessionStorage so a reload in the
// same tab also benefits. Entries older than MAX_AGE_MS are ignored. Never throws.
const MAX_AGE_MS = 30 * 60 * 1000;
const PREFIX = 'pageCache:';
const mem = new Map();

export function readPageCache(key, now = Date.now()) {
    let entry = mem.get(key);
    if (!entry) {
        try {
            const raw = sessionStorage.getItem(PREFIX + key);
            entry = raw ? JSON.parse(raw) : null;
            if (entry) mem.set(key, entry);
        } catch {
            entry = null;
        }
    }
    if (!entry || typeof entry.at !== 'number' || now - entry.at > MAX_AGE_MS) return null;
    return entry;
}

export function writePageCache(key, data, now = Date.now()) {
    const entry = { at: now, data };
    mem.set(key, entry);
    try {
        sessionStorage.setItem(PREFIX + key, JSON.stringify(entry));
    } catch {
        // Quota or private mode: memory copy still works for in-app navigation.
    }
}

export function minutesAgo(at, now = Date.now()) {
    const mins = Math.max(0, Math.round((now - at) / 60000));
    return mins < 1 ? 'less than a minute ago' : `${mins} min ago`;
}

// Called on logout so the next person in this tab never sees the previous person's numbers.
export function clearPageCache() {
    mem.clear();
    try {
        Object.keys(sessionStorage).filter(k => k.startsWith(PREFIX)).forEach(k => sessionStorage.removeItem(k));
    } catch {
        // ignore
    }
}
