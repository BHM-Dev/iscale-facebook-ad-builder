// Single source of truth for authenticated requests and token refresh.
//
// There used to be TWO independent implementations of this — one in
// lib/facebookApi.js (imported directly by pages) and one in
// context/AuthContext.jsx (returned from useAuth()). Both read and wrote the
// same localStorage tokens, and both had their own single-flight guard that
// knew nothing about the other's. The backend rotates the refresh token on
// every use, so when a component using one and a component using the other
// both hit a 401 in the same tick, both POSTed /auth/refresh with the same
// token: one won, one got a 401 back. The losing path then either handed the
// caller a raw 401 (FastAPI's "Not authenticated", which reads as a broken
// feature) or logged the user out of a session that was one moment from fine.
// BulkAdCreation.jsx and AdCreativeStep.jsx use both at once, so this was
// reachable in normal use.
//
// Everything now funnels through here: one refresh, one in-flight promise, one
// place that decides a session is dead.

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1';

// Shown in place of FastAPI's raw "Not authenticated" / "Could not validate
// credentials". Call sites already read `detail` off the error body, so
// substituting the body here fixes the message everywhere without touching them.
export const SESSION_EXPIRED_MESSAGE = 'Your session has expired. Sign in again to continue.';

const listeners = new Set();

/**
 * Subscribe to auth transport events. Returns an unsubscribe function.
 *  { type: 'tokens', accessToken, refreshToken } — tokens were written or cleared
 *  { type: 'session-expired' }                  — refresh failed definitively
 */
export const onAuthEvent = (listener) => {
    listeners.add(listener);
    return () => listeners.delete(listener);
};

const emit = (event) => {
    listeners.forEach((listener) => {
        try {
            listener(event);
        } catch (err) {
            console.error('Auth event listener failed', err);
        }
    });
};

export const getAccessToken = () => localStorage.getItem('accessToken');
export const getRefreshToken = () => localStorage.getItem('refreshToken');

// Only one refresh is ever in flight, across every caller in the app.
let refreshInFlight = null;
// Latched so the app is told a session died exactly once, no matter how many
// requests discover it. Reset whenever tokens are written or cleared.
let sessionDead = false;

export const setTokens = ({ accessToken, refreshToken }) => {
    if (accessToken) localStorage.setItem('accessToken', accessToken);
    if (refreshToken) localStorage.setItem('refreshToken', refreshToken);
    sessionDead = false;
    emit({ type: 'tokens', accessToken: getAccessToken(), refreshToken: getRefreshToken() });
};

export const clearTokens = () => {
    localStorage.removeItem('accessToken');
    localStorage.removeItem('refreshToken');
    sessionDead = false;
    emit({ type: 'tokens', accessToken: null, refreshToken: null });
};

const markSessionDead = () => {
    if (sessionDead) return;
    sessionDead = true;
    emit({ type: 'session-expired' });
};

// Any request that comes back without a 401 proves the session is alive, so the
// latch has to clear here too. Without this it only ever cleared on login or
// logout: one false positive (see the cross-tab note in authFetch) would leave
// the "session expired" banner up indefinitely over an app that works fine.
const markSessionAlive = () => {
    if (!sessionDead) return;
    sessionDead = false;
    emit({ type: 'session-restored' });
};

// Joel keeps several tabs open, and the session-expired banner tells him to sign
// in on a new tab and come back. localStorage is shared across tabs but module
// state is not, so without this the tab he came back to would still believe the
// session was dead. `storage` only fires in OTHER tabs, which is exactly the
// case we need. Also covers the reverse: signing out in one tab stops the others
// from insisting they are still logged in.
if (typeof window !== 'undefined') {
    window.addEventListener('storage', (event) => {
        if (event.key !== 'accessToken') return;
        // Only a WRITTEN token means the session came back. Loading /login in the
        // new tab runs AuthProvider's mount check, which clears dead tokens — a
        // removal, not a sign-in. Treating that as "restored" made this tab drop
        // its banner while its token was still null, so Joel could look back, see
        // nothing wrong, and click Launch into another 401.
        if (event.newValue) {
            sessionDead = false;
            emit({ type: 'tokens', accessToken: getAccessToken(), refreshToken: getRefreshToken() });
        }
    });
}

const doRefresh = async () => {
    // Read localStorage, never a closed-over variable: after one rotation any
    // captured copy is the already-invalidated token. The single-flight guard
    // covers concurrent callers, not sequential ones (e.g. the background
    // interval firing while a request triggers its own refresh).
    const currentRefreshToken = getRefreshToken();
    if (!currentRefreshToken) {
        const err = new Error('No refresh token');
        err.status = 401;
        throw err;
    }

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 8000);
    let response;
    try {
        response = await fetch(`${API_URL}/auth/refresh`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ refresh_token: currentRefreshToken }),
            signal: controller.signal,
        });
    } finally {
        clearTimeout(timeoutId);
    }

    if (!response.ok) {
        // Status is attached ONLY for real HTTP failures. A network error or
        // timeout throws above with no status, which is how callers tell "the
        // session is gone" apart from "the server is unreachable right now".
        const err = new Error('Failed to refresh token');
        err.status = response.status;
        throw err;
    }

    const data = await response.json();
    setTokens({ accessToken: data.access_token, refreshToken: data.refresh_token });
    return data.access_token;
};

/**
 * Refresh the access token. Concurrent callers share one request and all
 * receive the same new token. Throws on failure; `err.status` is set only when
 * the server rejected the token (401/403), not on network errors.
 */
export const refreshAccessToken = async () => {
    if (refreshInFlight) return refreshInFlight;
    refreshInFlight = doRefresh();
    try {
        return await refreshInFlight;
    } finally {
        // Cleared so a later expiry starts a fresh refresh rather than reusing
        // this settled promise.
        refreshInFlight = null;
    }
};

const sessionExpiredResponse = () => new Response(
    JSON.stringify({ detail: SESSION_EXPIRED_MESSAGE }),
    { status: 401, headers: { 'Content-Type': 'application/json' } },
);

/**
 * Authenticated fetch. Retries once after a silent refresh on 401.
 *
 * Always resolves with a Response — it never throws for auth reasons and never
 * tears the session down on its own. A definitively dead session comes back as
 * a 401 whose body is SESSION_EXPIRED_MESSAGE, and `session-expired` is emitted
 * so the app can offer a way back in one place. Joel asked not to be ejected to
 * the login screen mid-task: he keeps several tabs open with unsaved state, and
 * a clear message where he is beats losing the page.
 */
export const authFetch = async (url, options = {}) => {
    const makeRequest = (token) => fetch(url, {
        ...options,
        headers: {
            ...options.headers,
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
    });

    const token = getAccessToken();
    if (!token) {
        // No header at all is what produces FastAPI's "Not authenticated".
        markSessionDead();
        return sessionExpiredResponse();
    }

    let response = await makeRequest(token);
    if (response.status !== 401) {
        markSessionAlive();
        return response;
    }

    let newToken;
    try {
        newToken = await refreshAccessToken();
    } catch (err) {
        if (err.status === 401 || err.status === 403) {
            // The single-flight guard is per TAB — module state isn't shared —
            // and Joel runs several tabs. Two tabs can each 401 and each refresh
            // with the same stored token: the backend rotates it for the winner
            // and 401s the loser. Before declaring the session dead, check
            // whether another tab has since written a newer access token, and if
            // so just use it. Otherwise every multi-tab expiry would flash a
            // false "session expired" at whichever tab lost.
            const latest = getAccessToken();
            if (latest && latest !== token) {
                response = await makeRequest(latest);
                if (response.status !== 401) {
                    markSessionAlive();
                    return response;
                }
            }
            markSessionDead();
            return sessionExpiredResponse();
        }
        // Network error or 5xx: the session may well be fine, so say nothing
        // about it and hand back the original response.
        return response;
    }

    response = await makeRequest(newToken);
    if (response.status !== 401) {
        markSessionAlive();
        return response;
    }

    // A fresh token that still 401s means the account itself is no longer usable
    // (deactivated, permissions revoked) — not a stale token.
    markSessionDead();
    return sessionExpiredResponse();
};
