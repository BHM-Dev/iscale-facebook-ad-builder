import React, { useEffect } from 'react';
import { budgetPercentChange } from '../lib/liveBudget';
import { describeBudgetRatio } from '../lib/budgetErrors';

// Presentational confirm for a budget change. `change`: { type: 'adset'|'campaign', name, id,
// dollars, currentDollars, currentIsLive, budgetType?, largeChange?: {ratio}, label? }.
export default function BudgetConfirmModal({ change, onCancel, onConfirm }) {
    // Keyboard path for repeated scaling: the confirm button is autofocused (Enter confirms), Esc cancels.
    useEffect(() => {
        if (!change) return undefined;
        const onKey = (e) => { if (e.key === 'Escape') onCancel(); };
        window.addEventListener('keydown', onKey);
        return () => window.removeEventListener('keydown', onKey);
    }, [change, onCancel]);
    if (!change) return null;
    const pct = change.currentDollars > 0 ? budgetPercentChange(change.currentDollars, change.dollars) : null;
    const abo = change.type === 'campaign' && change.budgetType === 'ABO';
    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4 backdrop-blur-sm" role="presentation">
            <div className="w-full max-w-md rounded-2xl bg-white p-6 shadow-xl" role="dialog" aria-modal="true" aria-labelledby="budget-confirm-title">
                <h2 id="budget-confirm-title" className="text-lg font-bold text-gray-900">
                    {change.scale
                        ? `Scale ${change.type === 'campaign' ? 'campaign' : 'ad set'} budget +20%?`
                        : (change.type === 'campaign' ? 'Update campaign budget in Meta?' : 'Update ad set budget in Meta?')}
                </h2>
                <p className="mt-3 break-words text-sm font-semibold text-gray-800">{change.name || change.id}</p>
                {change.type === 'campaign' && change.budgetType === 'CBO' && (
                    <p className="mt-1 text-xs font-medium text-indigo-700">Campaign budget (CBO) — applies to every ad set in this campaign.</p>
                )}
                {abo ? (
                    <div role="alert" className="mt-2 rounded-lg border border-red-300 bg-red-50 px-3 py-2 text-sm leading-6 font-medium text-red-900">
                        This removes the campaign-level budget and switches spend control to the ad sets. Delivery continues immediately on each ad set&apos;s existing budget.
                    </div>
                ) : (
                    <p className="mt-2 text-sm leading-6 text-gray-600">
                        This changes the daily budget from{' '}
                        <strong>{change.currentDollars != null ? `$${change.currentDollars.toLocaleString()}` : 'the current Meta value'}</strong>
                        {change.currentDollars != null && (change.currentIsLive
                            ? ' (live in Meta)'
                            : <span className="font-semibold text-amber-700"> (last synced — could not verify live)</span>)}
                        {' '}to <strong>{`$${change.dollars.toLocaleString()}/day`}</strong>
                        {pct ? ` (${pct})` : ''}. The change takes effect in Meta immediately.
                    </p>
                )}
                {change.largeChange && (
                    <div role="alert" className="mt-3 rounded-lg border border-red-300 bg-red-50 px-3 py-2 text-sm font-semibold text-red-900">
                        Large change: {describeBudgetRatio(change.largeChange.ratio)} vs the live budget. Double-check the amount before confirming.
                    </div>
                )}
                <div className="mt-6 flex justify-end gap-3">
                    <button type="button" onClick={onCancel} className="rounded-lg border border-gray-200 bg-white px-4 py-2 text-sm font-semibold text-gray-700 hover:bg-gray-50">Cancel</button>
                    <button type="button" autoFocus onClick={onConfirm} className={`rounded-lg px-4 py-2 text-sm font-semibold text-white ${change.largeChange ? 'bg-red-600 hover:bg-red-700' : 'bg-indigo-600 hover:bg-indigo-700'}`}>
                        {change.largeChange ? `Yes, apply ${describeBudgetRatio(change.largeChange.ratio)}` : (change.confirmLabel || 'Update in Meta')}
                    </button>
                </div>
            </div>
        </div>
    );
}
