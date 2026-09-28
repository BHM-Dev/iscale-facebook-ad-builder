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
        return true;
    } catch (e) {
        console.error('localStorage write failed', e);
        return false;
    }
};

// Launch receipts are useful immediately after a Meta write, including after an
// accidental browser refresh, but must not become a durable local history.
// sessionStorage has exactly that lifetime: this tab session only.
export const safeSessionStorageGet = (key) => {
    try {
        return sessionStorage.getItem(key);
    } catch (e) {
        console.error('sessionStorage read failed', e);
        return null;
    }
};

export const safeSessionStorageSet = (key, value) => {
    try {
        sessionStorage.setItem(key, value);
        return true;
    } catch (e) {
        console.error('sessionStorage write failed', e);
        return false;
    }
};

export const safeSessionStorageRemove = (key) => {
    try {
        sessionStorage.removeItem(key);
    } catch (e) {
        console.error('sessionStorage removal failed', e);
    }
};
