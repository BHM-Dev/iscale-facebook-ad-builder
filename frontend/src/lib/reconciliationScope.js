// Shared identity rules for the two bulk launchers. Keep these fields stable:
// the lock is a safety boundary around one attempted Meta package, not around
// an account or a wizard page.

function stableSerialize(value) {
    if (value === null || value === undefined) return 'null';
    if (Array.isArray(value)) return `[${value.map(stableSerialize).join(',')}]`;
    if (typeof value === 'object') {
        return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${stableSerialize(value[key])}`).join(',')}}`;
    }
    return JSON.stringify(value);
}

function hashString(value) {
    let hash = 2166136261;
    for (let index = 0; index < value.length; index += 1) {
        hash ^= value.charCodeAt(index);
        hash = Math.imul(hash, 16777619);
    }
    return (hash >>> 0).toString(16).padStart(8, '0');
}

export function fingerprintReconciliationPackage(value) {
    return hashString(stableSerialize(value));
}

export function createReconciliationLaunchId() {
    if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
        return crypto.randomUUID();
    }
    return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}

export function getOrCreateReconciliationLaunchId(accountId, draftFingerprint) {
    const storageKey = `bulk-reconciliation-launch:${accountId || 'none'}:${draftFingerprint}`;
    try {
        const existing = sessionStorage.getItem(storageKey);
        if (existing) return existing;
        const created = createReconciliationLaunchId();
        sessionStorage.setItem(storageKey, created);
        return created;
    } catch {
        return createReconciliationLaunchId();
    }
}

export function buildReconciliationScope({ campaignData, adsetData, launchId }) {
    const campaignIdentity = campaignData?.isExisting
        ? (campaignData.fbCampaignId || campaignData.id || 'existing-campaign')
        : `new:${launchId}`;
    const adsetIdentity = adsetData?.isExisting
        ? (adsetData.fbAdsetId || adsetData.id || 'existing-adset')
        : `new:${launchId}`;
    return `campaign=${encodeURIComponent(campaignIdentity)}|adset=${encodeURIComponent(adsetIdentity)}|launch=${encodeURIComponent(launchId)}`;
}

export function buildReconciliationStorageKey(kind, accountId, scope) {
    return `bulk-${kind}-reconciliation:${accountId || 'none'}:${scope}`;
}

export function buildReconciliationRecord({ scope, packageFingerprint, readyAdNumbers = [], createdMetaIds = [], message, ...extra }) {
    return {
        blocked: true,
        scope,
        packageFingerprint,
        readyAdNumbers,
        createdMetaIds,
        message,
        recordedAt: new Date().toISOString(),
        ...extra,
    };
}
