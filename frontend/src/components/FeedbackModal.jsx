import React, { useEffect, useId, useRef, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { X, ImagePlus } from 'lucide-react';
import { authFetch } from '../lib/facebookApi';
import { useToast } from '../context/ToastContext';
import { useCampaign } from '../context/CampaignContext';

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1';

function plainError(error, fallback) {
    // fetch() rejects with a TypeError ("Failed to fetch") when the API can't be reached.
    if (error instanceof TypeError) return "Couldn't reach the Ad Builder. Check your connection and try again — your text is still here.";
    return error?.message || fallback;
}

// "Send feedback" from any page (2026-11-17). The page and ad account are pinned when the form opens (a draft
// can't end up filed against a page the person navigated to later), and browser details are attached
// automatically so the report can be reproduced without a follow-up question.
export default function FeedbackModal({ isOpen, onClose }) {
    const location = useLocation();
    const { activeAccountId } = useCampaign();
    const { showSuccess, showError } = useToast();
    const [message, setMessage] = useState('');
    const [file, setFile] = useState(null);
    const [sending, setSending] = useState(false);
    const [pinned, setPinned] = useState(null);   // { page, path, account } captured at open
    const titleId = useId();
    const textRef = useRef(null);
    const dialogRef = useRef(null);
    const sendingRef = useRef(false);
    const pinnedRef = useRef(null);
    const closeRef = useRef(onClose);
    useEffect(() => { closeRef.current = onClose; }, [onClose]);
    sendingRef.current = sending;

    const close = () => { if (!sendingRef.current) onClose(); };

    useEffect(() => {
        if (!isOpen) return undefined;
        const page = `${location.pathname}${location.search}`;
        // A draft belongs to the page it was written on: opening on another page starts fresh.
        if (pinnedRef.current && pinnedRef.current.page !== page) { setMessage(''); setFile(null); }
        pinnedRef.current = { page, path: location.pathname, account: activeAccountId || null };
        setPinned(pinnedRef.current);
        const opener = document.activeElement;
        requestAnimationFrame(() => textRef.current?.focus());
        const onKey = (e) => {
            if (e.key === 'Escape' && !e.defaultPrevented) { e.preventDefault(); if (!sendingRef.current) closeRef.current(); return; }
            if (e.key !== 'Tab' || !dialogRef.current) return;
            const focusable = dialogRef.current.querySelectorAll('button:not([disabled]), textarea, input, [href]');
            if (!focusable.length) return;
            const first = focusable[0];
            const last = focusable[focusable.length - 1];
            if (!dialogRef.current.contains(document.activeElement)) { e.preventDefault(); (e.shiftKey ? last : first).focus(); }
            else if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
            else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
        };
        document.addEventListener('keydown', onKey);
        return () => {
            document.removeEventListener('keydown', onKey);
            if (opener && typeof opener.focus === 'function') opener.focus();
        };
        // Pin only when the form opens, never while it is open.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [isOpen]);

    if (!isOpen || !pinned) return null;

    const onPaste = (e) => {
        const image = Array.from(e.clipboardData?.items || []).find(item => item.type.startsWith('image/'));
        if (!image) return;
        const blob = image.getAsFile();
        if (blob) {
            e.preventDefault();
            setFile(new File([blob], `screenshot-${Date.now()}.png`, { type: blob.type || 'image/png' }));
        }
    };

    const submit = async () => {
        if (message.trim().length < 3 || sending) return;
        setSending(true);
        try {
            let screenshotUrl = null;
            if (file) {
                const form = new FormData();
                form.append('file', file);
                const up = await authFetch(`${API_BASE}/uploads/`, { method: 'POST', body: form });
                if (!up.ok) {
                    const err = await up.json().catch(() => ({}));
                    throw new Error(typeof err.detail === 'string' ? `Screenshot: ${err.detail}` : 'The screenshot could not be uploaded. Remove it or try a smaller image.');
                }
                screenshotUrl = (await up.json()).url || null;
            }
            const res = await authFetch(`${API_BASE}/feedback`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    message: message.trim(),
                    page_path: pinned.page,
                    screenshot_url: screenshotUrl,
                    context: {
                        ad_account_id: pinned.account,
                        page_title: document.title,
                        viewport: `${window.innerWidth}x${window.innerHeight}`,
                        user_agent: navigator.userAgent.slice(0, 200),
                        sent_at: new Date().toISOString(),
                    },
                }),
            });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(typeof err.detail === 'string' ? err.detail : 'Feedback could not be sent. Try again — your text is still here.');
            }
            const saved = await res.json().catch(() => ({}));
            showSuccess(`Thanks, feedback ${saved.id ? `#${String(saved.id).slice(0, 6)} ` : ''}sent to Steve.`);
            setMessage('');
            setFile(null);
            pinnedRef.current = null;
            setPinned(null);
            onClose();
        } catch (error) {
            showError(plainError(error, 'Feedback could not be sent. Try again.'));
        } finally {
            setSending(false);
        }
    };

    const tooShort = message.trim().length < 3;

    return (
        <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50 p-4" onClick={close}>
            <div ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby={titleId}
                className="bg-white rounded-xl max-w-lg w-full p-6 shadow-xl" onClick={e => e.stopPropagation()}>
                <div className="flex items-start justify-between mb-3">
                    <div>
                        <h3 id={titleId} className="text-lg font-bold text-gray-900">Send feedback</h3>
                        <p className="text-sm text-gray-500 mt-1">
                            About <span className="font-mono text-gray-700">{pinned.path}</span>
                            {pinned.account ? <> · <span className="font-mono text-gray-700">{pinned.account}</span></> : null}
                        </p>
                    </div>
                    <button onClick={close} disabled={sending} aria-label="Close" className="text-gray-400 hover:text-gray-500 disabled:opacity-40"><X size={20} /></button>
                </div>
                <p className="mb-3 text-xs text-gray-500">
                    The page, ad account and browser are attached automatically. For anything urgent, like a live launch or spend
                    problem, message Steve in Slack instead.
                </p>
                <textarea
                    ref={textRef}
                    value={message}
                    onChange={e => setMessage(e.target.value)}
                    onPaste={onPaste}
                    onKeyDown={e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); submit(); } }}
                    maxLength={4000}
                    rows={5}
                    placeholder="What happened, or what would make this page better? Include what you clicked and what you expected. You can paste a screenshot here."
                    className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
                <div className="mt-3 flex items-center justify-between gap-3">
                    <label className="inline-flex items-center gap-2 text-sm text-gray-600 cursor-pointer hover:text-gray-900 focus-within:ring-2 focus-within:ring-blue-500 rounded">
                        <ImagePlus size={16} />
                        <span className="truncate max-w-[200px]">{file ? file.name : 'Attach or paste a screenshot'}</span>
                        <input type="file" accept="image/png,image/jpeg,image/webp" className="sr-only"
                            onChange={e => setFile(e.target.files?.[0] || null)} />
                    </label>
                    {file && <button type="button" onClick={() => setFile(null)} className="text-xs text-gray-500 hover:text-gray-800">Remove</button>}
                    <div className="flex gap-2 ml-auto">
                        <button onClick={close} disabled={sending} className="px-4 py-2 text-sm text-gray-700 hover:bg-gray-100 rounded-lg font-medium disabled:opacity-40">Close</button>
                        <button onClick={submit} disabled={sending || tooShort} title={tooShort ? 'Write a few words first' : 'Send (⌘+Enter)'}
                            className="px-4 py-2 text-sm text-white bg-blue-600 hover:bg-blue-700 disabled:opacity-50 rounded-lg font-medium">
                            {sending ? 'Sending…' : 'Send'}
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
}
