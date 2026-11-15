import React, { useEffect, useId, useRef } from 'react';
import { Trash2, AlertTriangle, X } from 'lucide-react';

const ConfirmationModal = ({
    isOpen,
    onClose,
    onConfirm,
    title,
    message,
    confirmText = 'Delete',
    cancelText = 'Cancel',
    isDestructive = true,
    icon: Icon = Trash2
}) => {
    const titleId = useId();
    const cancelRef = useRef(null);
    const dialogRef = useRef(null);
    // Callers pass an inline onClose; reading it through a ref keeps the effect from re-running (and
    // re-stealing focus) on every parent render.
    const onCloseRef = useRef(onClose);
    useEffect(() => { onCloseRef.current = onClose; }, [onClose]);

    // Escape cancels; focus starts on Cancel (the safe choice for a destructive action) and goes back to
    // whatever opened the dialog when it closes.
    useEffect(() => {
        if (!isOpen) return undefined;
        const opener = document.activeElement;
        cancelRef.current?.focus();
        const onKey = (e) => {
            if (e.key === 'Escape' && !e.defaultPrevented) { e.preventDefault(); onCloseRef.current(); return; }
            if (e.key !== 'Tab' || !dialogRef.current) return;
            // Keep Tab inside the dialog (aria-modal promises the page behind is inert).
            const focusable = dialogRef.current.querySelectorAll('button:not([disabled]), [href], input, select, textarea, [tabindex]:not([tabindex="-1"])');
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
    }, [isOpen]);

    if (!isOpen) return null;

    return (
        <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50 p-4" onClick={onClose}>
            <div className="bg-white rounded-xl max-w-md w-full p-6 shadow-xl transform transition-all" onClick={e => e.stopPropagation()}
                ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby={titleId}>
                <div className="flex items-center gap-4 mb-6">
                    <div className={`w-12 h-12 rounded-full flex items-center justify-center flex-shrink-0 ${isDestructive ? 'bg-red-100' : 'bg-blue-100'}`}>
                        <Icon className={isDestructive ? 'text-red-600' : 'text-blue-600'} size={24} />
                    </div>
                    <div className="flex-1">
                        <h3 id={titleId} className="text-lg font-bold text-gray-900">{title}</h3>
                        <p className="text-gray-500 text-sm mt-1">{message}</p>
                    </div>
                    <button onClick={onClose} aria-label="Close" className="text-gray-400 hover:text-gray-500 self-start">
                        <X size={20} />
                    </button>
                </div>
                <div className="flex justify-end gap-3">
                    <button
                        ref={cancelRef}
                        onClick={onClose}
                        className="px-4 py-2 text-gray-700 hover:bg-gray-100 rounded-lg transition-colors font-medium"
                    >
                        {cancelText}
                    </button>
                    <button
                        onClick={() => {
                            onConfirm();
                            onClose();
                        }}
                        className={`px-4 py-2 text-white rounded-lg transition-colors font-medium shadow-sm ${isDestructive
                            ? 'bg-red-600 hover:bg-red-700'
                            : 'bg-blue-600 hover:bg-blue-700'
                            }`}
                    >
                        {confirmText}
                    </button>
                </div>
            </div>
        </div>
    );
};

export default ConfirmationModal;
