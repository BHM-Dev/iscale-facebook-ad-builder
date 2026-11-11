import React, { useEffect, useState } from 'react';
import { Sparkles, X } from 'lucide-react';
import { LATEST_RELEASE_ID, notesToShow } from '../lib/releaseNotes';
import { safeLocalStorageGet, safeLocalStorageSet } from '../lib/safeLocalStorage';

const storageKey = userId => `whatsNewSeen_${userId}`;

// Shows release notes the signed-in user hasn't seen yet, once. Nothing new = no popup.
// "Seen" is per user, per browser (no server state on the login path).
export default function WhatsNewModal({ user }) {
    const [notes, setNotes] = useState([]);
    const userId = user?.id || user?.email;

    useEffect(() => {
        if (!userId) return;
        const raw = safeLocalStorageGet(storageKey(userId));
        const lastSeen = raw == null || raw === '' ? null : Number(raw);
        const pending = notesToShow(Number.isFinite(lastSeen) ? lastSeen : null);
        if (pending.length) setNotes(pending);
        else safeLocalStorageSet(storageKey(userId), String(LATEST_RELEASE_ID));
    }, [userId]);

    const close = () => {
        safeLocalStorageSet(storageKey(userId), String(LATEST_RELEASE_ID));
        setNotes([]);
    };

    useEffect(() => {
        if (!notes.length) return undefined;
        const onKey = event => { if (event.key === 'Escape') close(); };
        document.addEventListener('keydown', onKey);
        return () => document.removeEventListener('keydown', onKey);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [notes.length]);

    if (!notes.length) return null;
    return (
        <div className="fixed inset-0 z-[80] flex items-center justify-center bg-gray-900/40 p-4 backdrop-blur-sm" role="dialog" aria-modal="true" aria-labelledby="whats-new-title" onMouseDown={event => { if (event.target === event.currentTarget) close(); }}>
            <div className="max-h-[85vh] w-full max-w-lg overflow-y-auto rounded-2xl bg-white shadow-xl">
                <div className="flex items-start justify-between border-b border-gray-100 px-5 py-4">
                    <h2 id="whats-new-title" className="flex items-center gap-2 text-base font-semibold text-gray-900">
                        <Sparkles size={18} className="text-indigo-500" /> What's new
                    </h2>
                    <button type="button" onClick={close} aria-label="Close what's new" className="text-gray-400 hover:text-gray-600"><X size={18} /></button>
                </div>
                <ul className="divide-y divide-gray-100 px-5">
                    {notes.map(note => (
                        <li key={note.id} className="py-3.5">
                            <div className="flex items-baseline justify-between gap-3">
                                <h3 className="text-sm font-semibold text-gray-900">{note.title}</h3>
                                <span className="shrink-0 text-[11px] text-gray-400">{new Date(`${note.date}T12:00:00Z`).toLocaleDateString('en-US', { month: 'short', day: 'numeric', timeZone: 'UTC' })}</span>
                            </div>
                            <p className="mt-1 text-sm leading-5 text-gray-600">{note.body}</p>
                        </li>
                    ))}
                </ul>
                <div className="border-t border-gray-100 px-5 py-3 text-right">
                    <button type="button" onClick={close} className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700">Got it</button>
                </div>
            </div>
        </div>
    );
}
