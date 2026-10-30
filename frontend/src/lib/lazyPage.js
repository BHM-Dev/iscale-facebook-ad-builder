import { lazy } from 'react';

// Route-level code splitting. Each page is its own chunk, so a deploy no longer
// re-downloads every page up front.
//
// Stale-tab guard: a deploy replaces every hashed chunk (see frontend/Dockerfile),
// so a tab opened before the deploy asks for a chunk that no longer exists and the
// import rejects. Reload once to pick up the new index.html; the sessionStorage flag
// stops a reload loop if the chunk is genuinely broken (then the error surfaces).
const RELOAD_FLAG = 'chunkReloadAt';

export function lazyPage(importer) {
  return lazy(() =>
    importer().then(
      (mod) => {
        try { sessionStorage.removeItem(RELOAD_FLAG); } catch { /* storage blocked */ }
        return mod;
      },
      (err) => {
        let last = 0;
        let canMark = true;
        try { last = Number(sessionStorage.getItem(RELOAD_FLAG) || 0); } catch { canMark = false; }
        // Only reload when the flag can be written; without storage a broken chunk would reload forever.
        if (canMark && Date.now() - last > 30000) {
          try { sessionStorage.setItem(RELOAD_FLAG, String(Date.now())); } catch { throw err; }
          window.location.reload();
          return new Promise(() => {}); // keep Suspense showing until the reload lands
        }
        throw err;
      },
    ),
  );
}
