import React from 'react';
import { X } from 'lucide-react';

// Shared "review the resolved image prompt before spending credits" gate.
// Used by Image Ad's Quick Generate and Batch Generate. hasTextCollision is
// optional — Batch Generate has no style catalog (no bakesInText concept), so
// it simply omits that prop and the warning banner never renders.
export default function PromptReviewModal({ promptReview, hasTextCollision, onTurnOffOverlay, onCancel, onApprove }) {
    const isLoading = promptReview.status === 'loading';

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" role="dialog" aria-modal="true" aria-labelledby="prompt-review-title">
            <div className="w-full max-w-2xl max-h-[90vh] overflow-y-auto rounded-2xl bg-white shadow-2xl">
                <div className="flex items-start justify-between border-b border-gray-200 px-6 py-5">
                    <div>
                        <h2 id="prompt-review-title" className="text-xl font-bold text-gray-900">Review before generating</h2>
                        <p className="mt-1 text-sm text-gray-500">Confirm the prompt before spending image-generation credits.</p>
                    </div>
                    <button type="button" onClick={onCancel} className="rounded-lg p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-700" aria-label="Close prompt review"><X size={20} /></button>
                </div>

                <div className="space-y-5 px-6 py-5">
                    {hasTextCollision && (
                        <div className="rounded-xl border border-amber-300 bg-amber-50 px-4 py-4">
                            <p className="text-sm font-semibold text-amber-900">This style already includes on-image text/graphics as part of its design. Your Text Overlay is also on, which usually causes overlapping, illegible text.</p>
                            <button type="button" onClick={onTurnOffOverlay} className="mt-3 rounded-lg bg-amber-600 px-3 py-2 text-sm font-semibold text-white hover:bg-amber-700">Turn off Text Overlay</button>
                        </div>
                    )}

                    <div>
                        <label htmlFor="resolved-image-prompt" className="mb-2 block text-sm font-semibold text-gray-800">Resolved image prompt</label>
                        {isLoading ? (
                            <div className="flex min-h-40 items-center justify-center rounded-xl border border-gray-200 bg-gray-50 text-sm text-gray-500">Preparing prompt…</div>
                        ) : (
                            <textarea id="resolved-image-prompt" readOnly value={promptReview.prompt} rows={8} className="w-full resize-y rounded-xl border border-gray-200 bg-gray-50 px-4 py-3 text-sm leading-relaxed text-gray-700 focus:outline-none" />
                        )}
                    </div>
                </div>

                <div className="flex flex-col-reverse gap-3 border-t border-gray-200 px-6 py-4 sm:flex-row sm:justify-end">
                    <button type="button" onClick={onCancel} className="rounded-lg border border-gray-300 px-4 py-2.5 text-sm font-semibold text-gray-700 hover:bg-gray-50">Cancel</button>
                    <button type="button" onClick={onApprove} disabled={isLoading || !promptReview.prompt} className="rounded-lg bg-amber-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-amber-700 disabled:cursor-not-allowed disabled:opacity-50">Approve &amp; Generate</button>
                </div>
            </div>
        </div>
    );
}
