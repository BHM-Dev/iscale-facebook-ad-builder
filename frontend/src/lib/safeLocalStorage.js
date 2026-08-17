// localStorage can throw (Safari private browsing, full storage) — anything that
// reads/writes localStorage as a convenience cache should never take down an
// otherwise successful handler over a quota or availability error.

export const safeLocalStorageGet = (key) => {
    try {
        return localStorage.getItem(key);
    } catch (e) {
        console.error('localStorage read failed', e);
        return null;
    }
};

export const safeLocalStorageSet = (key, value) => {
    try {
        localStorage.setItem(key, value);
    } catch (e) {
        console.error('localStorage write failed', e);
    }
};
