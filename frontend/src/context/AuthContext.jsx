import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import {
    authFetch as sharedAuthFetch,
    refreshAccessToken as sharedRefreshAccessToken,
    clearTokens,
    setTokens,
    onAuthEvent,
} from '../lib/authClient';

const AuthContext = createContext();

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1';

export const useAuth = () => {
    const context = useContext(AuthContext);
    if (!context) {
        throw new Error('useAuth must be used within AuthProvider');
    }
    return context;
};

// The API is not consistent about its error envelope: FastAPI's HTTPException uses
// {detail}, while slowapi's rate limiter returns {error}. Reading only `detail`
// turned a 429 into a bare "Login failed" with no hint that the user was simply
// throttled — which reads as the app being broken.
async function authErrorMessage(response, fallback) {
    const data = await response.json().catch(() => ({}));
    if (response.status === 429) {
        const retryAfter = Number(response.headers.get('Retry-After'));
        const wait = Number.isFinite(retryAfter) && retryAfter > 0
            ? `about ${retryAfter} second${retryAfter === 1 ? '' : 's'}`
            : 'a minute';
        return `Too many attempts. Wait ${wait} and try again.`;
    }
    return data.detail || data.error || fallback;
}

export const AuthProvider = ({ children }) => {
    const [user, setUser] = useState(null);
    const [accessToken, setAccessToken] = useState(localStorage.getItem('accessToken'));
    const [refreshToken, setRefreshToken] = useState(localStorage.getItem('refreshToken'));
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    // Set when the shared auth client determines the session is definitively
    // gone. We deliberately do NOT logout() here — Layout shows a banner with a
    // sign-in button instead, so nobody loses an in-progress page.
    const [sessionExpired, setSessionExpired] = useState(false);

    // lib/authClient owns the tokens; mirror its writes into React state so
    // anything reading `accessToken` off the context stays correct.
    useEffect(() => onAuthEvent((event) => {
        if (event.type === 'tokens') {
            setAccessToken(event.accessToken);
            setRefreshToken(event.refreshToken);
            setSessionExpired(false);
        } else if (event.type === 'session-expired') {
            setSessionExpired(true);
        } else if (event.type === 'session-restored') {
            // A later request succeeded, so an earlier expiry verdict was wrong
            // (or has been fixed in another tab). Take the banner down.
            setSessionExpired(false);
        }
    }), []);

    // Check if user is authenticated on mount.
    //
    // This path DOES logout() on a dead refresh token, unlike authFetch, which
    // raises the banner instead. That difference is deliberate: at mount there is
    // no in-progress work to protect, and the login form is the right destination.
    // It is also what makes the banner's "sign in on a new tab" flow work — the
    // new tab clears the stale tokens on load and shows the form.
    useEffect(() => {
        const initAuth = async () => {
            if (accessToken) {
                try {
                    await fetchUser();
                } catch (err) {
                    // Token might be expired, try to refresh
                    if (refreshToken) {
                        try {
                            await refreshAccessToken();
                        } catch (refreshErr) {
                            // Only logout if it's a definitive auth failure (401/403)
                            // If it's a network error or 500, keep the tokens so we can try again later
                            if (refreshErr.status === 401 || refreshErr.status === 403) {
                                logout();
                            }
                        }
                    } else {
                        logout();
                    }
                }
            }
            setLoading(false);
        };
        initAuth();
    }, []);

    // Auto-refresh token every 6 days to prevent expiration (tokens last 7 days)
    useEffect(() => {
        if (!refreshToken) return;

        const refreshInterval = setInterval(async () => {
            try {
                await refreshAccessToken();
            } catch (err) {
                // Silently fail - will retry on next interval or next API call
                console.log('Background token refresh failed, will retry');
            }
        }, 6 * 24 * 60 * 60 * 1000); // 6 days in ms

        return () => clearInterval(refreshInterval);
    }, [refreshToken]);

    const fetchUser = async () => {
        // Always read from localStorage so this works correctly after a token refresh
        // (React state update from setAccessToken is async; localStorage is updated synchronously)
        const token = localStorage.getItem('accessToken') || accessToken;

        // 8-second timeout prevents a hung backend from locking the loading screen forever
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 8000);

        let response;
        try {
            response = await fetch(`${API_URL}/auth/me`, {
                headers: { 'Authorization': `Bearer ${token}` },
                signal: controller.signal,
            });
        } finally {
            clearTimeout(timeoutId);
        }

        if (!response.ok) {
            throw new Error('Failed to fetch user');
        }

        const userData = await response.json();
        setUser(userData);
        return userData;
    };

    const login = async (email, password) => {
        setError(null);
        try {
            const response = await fetch(`${API_URL}/auth/login/json`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ email, password }),
            });

            if (!response.ok) {
                throw new Error(await authErrorMessage(response, 'Login failed'));
            }

            const data = await response.json();
            setTokens({ accessToken: data.access_token, refreshToken: data.refresh_token });

            // Fetch user data
            const userResponse = await fetch(`${API_URL}/auth/me`, {
                headers: {
                    'Authorization': `Bearer ${data.access_token}`,
                },
            });

            if (userResponse.ok) {
                const userData = await userResponse.json();
                setUser(userData);
            }

            return data;
        } catch (err) {
            setError(err.message);
            throw err;
        }
    };

    const register = async (email, password, name) => {
        setError(null);
        try {
            const response = await fetch(`${API_URL}/auth/register`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ email, password, name }),
            });

            if (!response.ok) {
                throw new Error(await authErrorMessage(response, 'Registration failed'));
            }

            const userData = await response.json();

            // Auto-login after registration
            await login(email, password);

            return userData;
        } catch (err) {
            setError(err.message);
            throw err;
        }
    };

    const logout = useCallback(async () => {
        // Optionally call the logout endpoint
        if (accessToken && refreshToken) {
            try {
                await fetch(`${API_URL}/auth/logout`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'Authorization': `Bearer ${accessToken}`,
                    },
                    body: JSON.stringify({ refresh_token: refreshToken }),
                });
            } catch (err) {
                // Ignore errors during logout
            }
        }

        setUser(null);
        clearTokens();
    }, [accessToken, refreshToken]);

    // Both the token refresh and the authenticated-fetch wrapper live in
    // lib/authClient.js now. This context used to carry its own copy of each,
    // with its own single-flight guard that knew nothing about the one in
    // lib/facebookApi.js — see the header comment in authClient.js for what that
    // race did to live sessions. Only the user-fetch on top is context-specific.
    const refreshAccessToken = async () => {
        const token = await sharedRefreshAccessToken();
        await fetchUser();
        return token;
    };

    // Same function object for the life of the app. The old useCallback churned
    // whenever logout's deps changed, refiring the fetches of every component
    // that lists authFetch in its useEffect deps.
    const authFetch = sharedAuthFetch;

    // Check if user has a specific role
    const hasRole = useCallback((roleName) => {
        if (!user) return false;
        if (user.is_superuser) return true;
        return user.roles?.some(role => role.name === roleName) || false;
    }, [user]);

    // Check if user has a specific permission
    const hasPermission = useCallback((permissionName) => {
        if (!user) return false;
        if (user.is_superuser) return true;
        return user.roles?.some(role =>
            role.permissions?.some(perm => perm.name === permissionName)
        ) || false;
    }, [user]);

    const value = {
        user,
        accessToken,
        loading,
        error,
        sessionExpired,
        isAuthenticated: !!user,
        login,
        register,
        logout,
        authFetch,
        hasRole,
        hasPermission,
        refreshAccessToken,
    };

    return (
        <AuthContext.Provider value={value}>
            {children}
        </AuthContext.Provider>
    );
};
