// Page-to-page handoffs (`pendingRemixCreative`, `pendingQuickAd`, ...) live in
// localStorage and are deleted by the page that reads them. If that page never
// opens, or errors before reading, the handoff used to sit forever and prefill a
// later, unrelated session with stale data (2026-11-01 review).
//
// installPendingTimestamps() stamps every pending* write with its time (by
// wrapping localStorage.setItem for those keys only), and the sweep at app start
// removes any handoff older than the TTL — without touching the many
// writers/readers (some are in launch-critical files). Keys with no stamp
// (written before this shipped) start their clock at the first sweep.

export const PENDING_TTL_MS = 2 * 60 * 60 * 1000;
const SEEN_KEY = 'pendingHandoffsSeenAt';

// pending*-named keys that are NOT short-lived handoffs and must never expire.
// pendingGeneratedAdMetaLinks (BatchPushModal) is a durable retry queue: it holds
// Meta ad ids whose write-back to generated_ads hasn't succeeded yet.
export const PERSISTENT_PENDING_KEYS = new Set(['pendingGeneratedAdMetaLinks']);

function isHandoffKey(key) {
  return typeof key === 'string' && key.startsWith('pending') && key !== SEEN_KEY && !PERSISTENT_PENDING_KEYS.has(key);
}

export function sweepPendingHandoffs(storage = globalThis.localStorage, now = Date.now()) {
  try {
    if (!storage) return [];
    let seen = {};
    try { seen = JSON.parse(storage.getItem(SEEN_KEY) || '{}') || {}; } catch { seen = {}; }
    const present = [];
    for (let i = 0; i < storage.length; i += 1) {
      const key = storage.key(i);
      if (isHandoffKey(key)) present.push(key);
    }
    const removed = [];
    const nextSeen = {};
    for (const key of present) {
      const firstSeen = Number(seen[key]) || now;
      if (now - firstSeen > PENDING_TTL_MS) {
        storage.removeItem(key);
        removed.push(key);
      } else {
        nextSeen[key] = firstSeen;
      }
    }
    if (Object.keys(nextSeen).length) storage.setItem(SEEN_KEY, JSON.stringify(nextSeen));
    else storage.removeItem(SEEN_KEY);
    return removed;
  } catch {
    return []; // storage blocked (private mode etc.) — never break app start
  }
}

export function stampPendingWrite(storage, key, now = Date.now()) {
  if (!isHandoffKey(key)) return;
  let seen = {};
  try { seen = JSON.parse(storage.getItem(SEEN_KEY) || '{}') || {}; } catch { seen = {}; }
  seen[key] = now;
  storage.setItem(SEEN_KEY, JSON.stringify(seen));
}

let installed = false;
export function installPendingTimestamps(proto = globalThis.Storage?.prototype) {
  try {
    if (installed || !proto || !proto.setItem) return;
    const original = proto.setItem;
    proto.setItem = function setItemWithPendingStamp(key, value) {
      original.call(this, key, value);
      if (isHandoffKey(key)) {
        try {
          let seen = {};
          try { seen = JSON.parse(this.getItem(SEEN_KEY) || '{}') || {}; } catch { seen = {}; }
          seen[key] = Date.now();
          original.call(this, SEEN_KEY, JSON.stringify(seen));
        } catch { /* stamping is best-effort */ }
      }
    };
    installed = true;
  } catch { /* never break app start */ }
}
