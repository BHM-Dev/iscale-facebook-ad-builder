import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { PauseCircle, PlayCircle, Trash2, Plus, RefreshCw, AlertTriangle, CheckCircle, Zap, Target, Bell, TrendingUp, TrendingDown, Search, Pencil, Copy } from 'lucide-react';
import { useToast } from '../context/ToastContext';
import { authFetch } from '../lib/facebookApi';

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1';

const METRIC_LABELS = { cpl: 'Cost Per Lead', cpa: 'Cost Per Action', ctr: 'CTR', roas: 'ROAS' };
const METRIC_UNITS  = { cpl: '$', cpa: '$', ctr: '%', roas: 'x' };

const ACTION_OPTIONS = [
  { value: 'pause', label: 'Pause the target', icon: PauseCircle, color: 'text-red-500' },
  { value: 'notify', label: 'Notify (Slack only, no change on Meta)', icon: Bell, color: 'text-blue-500' },
  { value: 'increase_budget', label: 'Increase budget', icon: TrendingUp, color: 'text-emerald-600' },
  { value: 'decrease_budget', label: 'Decrease budget', icon: TrendingDown, color: 'text-amber-600' },
  { value: 'increase_bid', label: 'Increase bid', icon: TrendingUp, color: 'text-emerald-600' },
  { value: 'decrease_bid', label: 'Decrease bid', icon: TrendingDown, color: 'text-amber-600' },
  { value: 'duplicate', label: 'Duplicate the ad set', icon: Copy, color: 'text-violet-600' },
];
const ACTION_LABELS = Object.fromEntries(ACTION_OPTIONS.map(a => [a.value, a.label]));
// Renamed from BUDGET_ACTIONS (Phase 2) — bid actions share the exact same
// percent-adjust field/validation/confirm-step as budget actions, so they're
// folded into the same gate rather than duplicating it. Matches the backend
// rename in auto_pause.py.
const PERCENT_ACTIONS = new Set(['increase_budget', 'decrease_budget', 'increase_bid', 'decrease_bid']);
const DUPLICATE_ACTION = 'duplicate';
const ACTION_BADGE_CLS = {
  pause: 'bg-red-50 text-red-600',
  notify: 'bg-blue-50 text-blue-600',
  increase_budget: 'bg-emerald-50 text-emerald-700',
  decrease_budget: 'bg-amber-50 text-amber-700',
  increase_bid: 'bg-emerald-50 text-emerald-700',
  decrease_bid: 'bg-amber-50 text-amber-700',
  duplicate: 'bg-violet-50 text-violet-700',
};
// Action-specific "already fired" copy — a generic red "Triggered" pill reads
// identically for a paused ad set and a budget change, which pre-push review
// flagged as a real gap (Joel can't tell what actually happened at a glance).
const TRIGGERED_LABELS = {
  pause: 'Paused',
  notify: 'Notified',
  increase_budget: 'Budget increased',
  decrease_budget: 'Budget decreased',
  increase_bid: 'Bid increased',
  decrease_bid: 'Bid decreased',
  duplicate: 'Duplicated',
};

// Best-effort CURRENT budget for the pre-commit confirmation step, from whatever
// this app already has cached locally (adsets/saved) — not a live Meta read, which
// would mean one API call per selected ad set just to show a preview. The rule
// itself always reads the true live value at fire time (facebook_service.py),
// so a stale preview here can't cause a wrong amount to actually be sent to Meta —
// it can only make the PREVIEW number look off by however much has drifted since
// the last sync. Labeled "as of last sync" in the UI so that's not implied to be live.
const currentBudgetCents = (adset) => {
  // Daily and lifetime budgets are mutually exclusive on both the ad set and its
  // CBO campaign — checking daily first, then lifetime, at each level covers
  // both without guessing which one an ad set actually uses. Missing this for
  // lifetime-budget ad sets meant the pre-commit confirm step (§4.1 of
  // AdBuilder-Competitor-Synthesis-Redesign-Brief.md) silently showed nothing
  // for them — the exact "no current -> new preview" gap it exists to close.
  // Caught in Codex's review.
  if (adset.daily_budget) return { cents: adset.daily_budget, source: 'ad set', unit: 'day' };
  if (adset.lifetime_budget) return { cents: adset.lifetime_budget, source: 'ad set', unit: 'lifetime' };
  if (adset.campaign_daily_budget) return { cents: adset.campaign_daily_budget, source: 'CBO campaign', unit: 'day' };
  if (adset.campaign_lifetime_budget) return { cents: adset.campaign_lifetime_budget, source: 'CBO campaign', unit: 'lifetime' };
  return null;
};

// ── Add-rule modal ─────────────────────────────────────────────────────────────
function AddRuleModal({ adsets, ads, onClose, onCreated }) {
  const { showSuccess, showError } = useToast();
  const [selectedIds, setSelectedIds] = useState(() => new Set(adsets[0] ? [adsets[0].id] : []));
  const [search, setSearch] = useState('');
  const [form, setForm] = useState({
    scope: 'adset',
    metric: 'cpl',
    operator: 'greater_than',
    threshold: 50,
    min_spend: 20,
    action: 'pause',
    budget_adjust_pct: 20,
    duplicate_all_ads: true,
    duplicate_name_suffix: '- Copy',
    duplicate_append_number: false,
    duplicate_pause_original: false,
    duplicate_repeat: false,
  });
  const [saving, setSaving] = useState(false);
  // 'form' | 'confirm' — budget/bid actions AND duplicate get a mandatory second
  // step listing every matched ad set before anything is written: budget/bid
  // moves money, duplicate moves ad-set structure (new ad sets, new ads). Only
  // pause/notify skip straight to save() since neither does either.
  const [step, setStep] = useState('form');

  const targets = form.scope === 'ad' ? ads : adsets;
  const filteredTargets = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return targets;
    return targets.filter(a => a.name?.toLowerCase().includes(q));
  }, [targets, search]);

  const toggleAdset = (id) => {
    setSelectedIds(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const toggleAll = () => {
    setSelectedIds(prev => {
      const allFilteredSelected = filteredTargets.length > 0 && filteredTargets.every(a => prev.has(a.id));
      if (allFilteredSelected) {
        // Deselect just the currently-visible (filtered) set, keep any other selections intact
        const next = new Set(prev);
        filteredTargets.forEach(a => next.delete(a.id));
        return next;
      }
      const next = new Set(prev);
      filteredTargets.forEach(a => next.add(a.id));
      return next;
    });
  };

  const validateBeforeContinue = () => {
    if (selectedIds.size === 0) { showError(`Select at least one ${form.scope === 'ad' ? 'ad' : 'ad set'}`); return false; }
    if (form.scope === 'ad' && selectedIds.size > 1) { showError('Select one ad for an ad-scoped rule'); return false; }
    if (PERCENT_ACTIONS.has(form.action) && (!form.budget_adjust_pct || form.budget_adjust_pct <= 0)) {
      showError('Enter an adjustment percentage greater than 0');
      return false;
    }
    if (form.action === DUPLICATE_ACTION && !form.duplicate_name_suffix?.trim()) {
      showError('Enter a name suffix for the duplicated ad set');
      return false;
    }
    return true;
  };

  // Budget/bid and duplicate actions never submit directly from the form — they
  // route through the confirm step below first (P0 per pre-push review:
  // bulk-scoped money or structure changes need a review-before-commit step,
  // not just a live count).
  const handlePrimaryAction = () => {
    if (!validateBeforeContinue()) return;
    if (PERCENT_ACTIONS.has(form.action) || form.action === DUPLICATE_ACTION) {
      setStep('confirm');
    } else {
      save();
    }
  };

  const save = async () => {
    if (!validateBeforeContinue()) return;
    setSaving(true);
    try {
      const isDuplicate = form.action === DUPLICATE_ACTION;
      const selected = targets.filter(t => selectedIds.has(t.id));
      const isAd = form.scope === 'ad';
      const payload = isAd ? {
        adset_id: selected[0].adset_id,
        scope: 'ad',
        fb_ad_id: selected[0].fb_ad_id,
        ad_name: selected[0].name,
      } : {
        adset_ids: Array.from(selectedIds),
        scope: 'adset',
      };
      const res = await authFetch(`${API_BASE}/auto-pause/rules${isAd ? '' : '/bulk'}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ...payload,
          metric: form.metric,
          operator: form.operator,
          threshold: form.threshold,
          min_spend: form.min_spend,
          action: form.action,
          budget_adjust_pct: PERCENT_ACTIONS.has(form.action) ? form.budget_adjust_pct : null,
          // These fields are non-nullable in RuleCreate because they have
          // defaults for Duplicate rules. Omitting them for every other action
          // lets Pydantic apply those defaults; sending null causes five
          // validation errors before an ordinary pause/notify rule can be
          // created.
          ...(isDuplicate ? {
            duplicate_all_ads: form.duplicate_all_ads,
            duplicate_name_suffix: form.duplicate_name_suffix,
            duplicate_append_number: form.duplicate_append_number,
            duplicate_pause_original: form.duplicate_pause_original,
            duplicate_repeat: form.duplicate_repeat,
          } : {}),
        }),
      });
      if (!res.ok) {
        let e;
        try {
          e = await res.json();
        } catch {
          throw new Error('Couldn’t create the rule. The server returned an unreadable error; check your connection and retry.');
        }
        const detail = Array.isArray(e.detail)
          ? e.detail.map(item => {
              const location = Array.isArray(item?.loc) ? ` (${item.loc.slice(1).join('.')})` : '';
              return `${item?.msg || item?.detail || JSON.stringify(item)}${location}`;
            }).join('; ')
          : e.detail;
        throw new Error(detail || 'Failed to create rule');
      }
      const data = await res.json();
      const createdCount = data.created ?? 1;
      showSuccess(`${createdCount} rule${createdCount !== 1 ? 's' : ''} created`);
      onCreated();
      onClose();
    } catch (e) { showError(e.message); }
    finally { setSaving(false); }
  };

  const allFilteredSelected = filteredTargets.length > 0 && filteredTargets.every(a => selectedIds.has(a.id));
  const selectedAdsets = adsets.filter(a => selectedIds.has(a.id));

  // ── Confirm step (budget/bid actions, and duplicate) — every matched ad set
  // previewed before anything is written. Replaces "a live count is the only
  // guardrail" with an actual line-by-line preview.
  if (step === 'confirm') {
    const isDuplicate = form.action === DUPLICATE_ACTION;
    const isBid = form.action === 'increase_bid' || form.action === 'decrease_bid';
    const pct = (form.action === 'increase_budget' || form.action === 'increase_bid') ? form.budget_adjust_pct : -form.budget_adjust_pct;
    return (
      <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50">
        <div className="bg-white rounded-2xl shadow-xl p-6 w-full max-w-lg max-h-[90vh] overflow-y-auto">
          <h2 className="text-lg font-bold text-gray-900 mb-1 flex items-center gap-2">
            <AlertTriangle size={20} className="text-amber-500" /> Confirm {isDuplicate ? 'duplicate' : isBid ? 'bid' : 'budget'} rule
          </h2>
          <p className="text-sm text-gray-600 mb-4">
            {isDuplicate
              ? 'Review every ad set this rule will apply to before creating it. Each row fires independently and creates a real new ad set (and, unless set to empty, new ads) on Meta — not a preview.'
              : 'Review every ad set this rule will apply to before creating it. Each row fires independently — this is real live Meta spend, not a preview.'}
          </p>

          <div className="border border-gray-200 rounded-lg divide-y divide-gray-50 max-h-64 overflow-y-auto mb-4">
            {(form.scope === 'ad' ? ads.filter(a => selectedIds.has(a.id)) : selectedAdsets).map(a => {
              if (isDuplicate) {
                return (
                  <div key={a.id} className="px-3 py-2 text-sm">
                    <div className="font-medium text-gray-900 truncate">{a.name}</div>
                    <div className="text-xs text-gray-500">
                      Clones to <strong>"{a.name}{form.duplicate_name_suffix}{form.duplicate_append_number ? ' N' : ''}"</strong>
                      {form.duplicate_append_number ? ' (N = next free number, computed live at fire time)' : ''}
                      {form.duplicate_all_ads ? ', with all its ads' : ', empty (no ads)'}
                      {form.duplicate_pause_original ? ' — original will be paused' : ''}
                    </div>
                  </div>
                );
              }
              const current = currentBudgetCents(a);
              return (
                <div key={a.id} className="px-3 py-2 text-sm">
                  <div className="font-medium text-gray-900 truncate">{a.name}</div>
                  {isBid ? (
                    <div className="text-xs text-gray-500">
                      Bid amount adjusted by {pct > 0 ? '+' : ''}{pct}% — read live from Meta when this rule fires (no cached bid to preview here).
                    </div>
                  ) : current ? (
                    <div className="text-xs text-gray-500">
                      Current ({current.source}, {current.unit === 'lifetime' ? 'lifetime budget' : 'daily budget'}, as of last sync): <strong>${(current.cents / 100).toFixed(2)}</strong>
                      {' → '}
                      new: <strong className={form.action === 'increase_budget' ? 'text-emerald-700' : 'text-amber-700'}>
                        ${((current.cents / 100) * (1 + pct / 100)).toFixed(2)}
                      </strong>
                      {' '}(computed here for preview — the actual rule always reads the live value again when it fires)
                    </div>
                  ) : (
                    <div className="text-xs text-amber-600">No cached budget on file — will be read live from Meta when this rule fires.</div>
                  )}
                </div>
              );
            })}
          </div>

          <div className="bg-amber-50 border border-amber-200 rounded-lg px-3 py-2 text-xs text-amber-800 mb-4">
            This creates {selectedAdsets.length} independent rule{selectedAdsets.length !== 1 ? 's' : ''} — each can be
            edited or disabled on its own afterward.{' '}
            {form.duplicate_repeat
              ? 'This rule repeats — it will keep firing on this ad set until you disable it or turn off repeat.'
              : "None of them run more than once; every rule disables itself the moment it fires, so it won't keep compounding this change every 30 minutes unattended."}
          </div>

          <div className="flex gap-3">
            <button onClick={() => setStep('form')} className="flex-1 btn-secondary">Back</button>
            <button onClick={save} disabled={saving} className="flex-1 btn-primary">
              {saving ? 'Creating...' : `Confirm & Create ${selectedAdsets.length > 1 ? `${selectedAdsets.length} Rules` : 'Rule'}`}
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50">
      <div className="bg-white rounded-2xl shadow-xl p-6 w-full max-w-lg max-h-[90vh] overflow-y-auto">
        <h2 className="text-lg font-bold text-gray-900 mb-4 flex items-center gap-2">
          <PauseCircle size={20} className="text-red-500" /> New Rule
        </h2>

        <div className="space-y-4">
          <Field label={form.scope === 'ad' ? 'Ad' : 'Ad Set(s)'}>
            <div className="flex gap-2 mb-2">
              {['adset', 'ad'].map(scope => (
                <button key={scope} type="button" onClick={() => { setForm({...form, scope, action: scope === 'ad' && !['pause', 'notify'].includes(form.action) ? 'pause' : form.action}); setSelectedIds(new Set()); setSearch(''); }} className={`px-3 py-1.5 rounded-lg text-xs font-medium border ${form.scope === scope ? 'bg-gray-900 text-white border-gray-900' : 'bg-white text-gray-600 border-gray-200'}`}>
                  {scope === 'ad' ? 'Ad' : 'Ad Set'}
                </button>
              ))}
            </div>
            {targets.length === 0 ? (
              <div className="px-3 py-2 text-sm text-amber-700 bg-amber-50 border border-amber-200 rounded-lg">
                No {form.scope === 'ad' ? 'tracked ads' : 'tracked ad sets'} found. Sync them in Campaign Performance first.
              </div>
            ) : (
              <div className="border border-gray-200 rounded-lg overflow-hidden">
                <div className="flex items-center gap-2 px-2 py-1.5 border-b border-gray-100 bg-gray-50">
                  <Search size={13} className="text-gray-400 flex-shrink-0" />
                  <input
                    type="text"
                    placeholder={`Search ${form.scope === 'ad' ? 'ads' : 'ad sets'}...`}
                    value={search}
                    onChange={e => setSearch(e.target.value)}
                    className="flex-1 min-w-0 text-sm bg-transparent outline-none"
                  />
                  {form.scope !== 'ad' && (
                    <button type="button" onClick={toggleAll} className="text-xs font-medium text-blue-600 hover:text-blue-800 flex-shrink-0">
                      {allFilteredSelected ? 'Deselect all' : 'Select all'}
                    </button>
                  )}
                </div>
                <div className="max-h-40 overflow-y-auto divide-y divide-gray-50">
                  {filteredTargets.length === 0 ? (
                    <div className="px-3 py-3 text-xs text-gray-400 text-center">No matching {form.scope === 'ad' ? 'ads' : 'ad sets'}</div>
                  ) : filteredTargets.map(a => (
                    <label key={a.id} className="flex items-center gap-2 px-3 py-2 text-sm hover:bg-gray-50 cursor-pointer">
                      <input type={form.scope === 'ad' ? 'radio' : 'checkbox'} checked={selectedIds.has(a.id)} onChange={() => form.scope === 'ad' ? setSelectedIds(new Set([a.id])) : toggleAdset(a.id)} />
                      <span className="truncate">{a.name}{form.scope === 'ad' && a.adset_name ? ` · ${a.adset_name}` : ''}</span>
                    </label>
                  ))}
                </div>
              </div>
            )}
            {/* Live match count — the one UX detail worth copying exactly from Birch's
                Automated Rules builder ("Estimated match: N ad sets"): see it before you
                commit, not after. */}
            <p className="text-xs mt-1.5 font-medium text-gray-600">
              Applies to <span className="text-gray-900">{selectedIds.size}</span> {form.scope === 'ad' ? 'ad' : `ad set${selectedIds.size !== 1 ? 's' : ''}`}
            </p>
          </Field>

          <Field label="Action">
            <select className="input-base" value={form.action} onChange={e => setForm({...form, action: e.target.value})}>
              {ACTION_OPTIONS.filter(a => form.scope === 'ad' ? ['pause', 'notify'].includes(a.value) : true).map(a => <option key={a.value} value={a.value}>{form.scope === 'ad' && a.value === 'pause' ? 'Pause the ad' : form.scope === 'ad' && a.value === 'notify' ? 'Notify (Slack only, no change on Meta)' : a.label}</option>)}
            </select>
          </Field>

          {PERCENT_ACTIONS.has(form.action) && (
            <>
              {/* Hard visual break from the low-friction pause/notify path — this
                  moves real, live ad spend on Meta with no confirmation dialog on
                  Meta's own side (unlike Ads Manager, which confirms every manual
                  budget edit). Shown the moment a budget/bid action is picked, before
                  any field below it is even filled in. */}
              <div className="flex items-start gap-2 bg-amber-50 border border-amber-300 rounded-lg px-3 py-2.5 text-xs text-amber-900">
                <AlertTriangle size={15} className="text-amber-600 flex-shrink-0 mt-0.5" />
                <span>
                  <strong>This automatically changes live {form.action.includes('bid') ? 'bid amount' : 'ad spend'} on Meta</strong> — unattended, checked every
                  30 minutes, with no confirmation dialog when it fires. It disables itself after firing once.
                  {form.action.includes('bid') && (
                    <> If the ad set has no manual bid cap set (e.g. it's running Meta's automatic "Lowest Cost" bidding —
                    common on BHM ad sets), this rule can't do anything and will disable itself with an error the first
                    time it checks — visible in the rule's fire history.</>
                  )}
                </span>
              </div>
              <Field label={`Adjust ${form.action.includes('bid') ? 'bid' : 'budget'} by (%)`}>
                <input
                  type="number" min="1" max="100" className="input-base"
                  value={form.budget_adjust_pct}
                  onChange={e => setForm({...form, budget_adjust_pct: Number(e.target.value)})}
                />
                <p className="text-xs text-gray-500 mt-1">
                  {form.action.startsWith('increase') ? 'Increases' : 'Decreases'} the ad set's
                  {form.action.includes('bid') ? ' bid amount' : " (or its CBO campaign's) current budget"} by this
                  percentage. Reads the live Meta value at fire time, not a cached one.
                </p>
              </Field>
            </>
          )}

          {form.action === DUPLICATE_ACTION && (
            <>
              <div className="flex items-start gap-2 bg-violet-50 border border-violet-300 rounded-lg px-3 py-2.5 text-xs text-violet-900">
                <AlertTriangle size={15} className="text-violet-600 flex-shrink-0 mt-0.5" />
                <span>
                  <strong>This creates a real new ad set on Meta, starting from zero spend</strong> — unattended,
                  checked every 30 minutes. Riskier than a budget/bid nudge: it's brand-new inventory, not an
                  adjustment to something already running. The new ad set (and its ads, if included) launch
                  <strong> PAUSED</strong> — nothing spends until someone reviews and turns it on. It inherits the
                  original's budget (or shares its CBO campaign's budget) exactly as-is. Disables itself after firing
                  once unless "Repeat" is checked below.
                </span>
              </div>

              <Field label="Ads to include">
                <div className="flex gap-4 text-sm">
                  <label className="flex items-center gap-1.5">
                    <input type="radio" checked={form.duplicate_all_ads} onChange={() => setForm({...form, duplicate_all_ads: true})} />
                    All ads
                  </label>
                  <label className="flex items-center gap-1.5">
                    <input type="radio" checked={!form.duplicate_all_ads} onChange={() => setForm({...form, duplicate_all_ads: false})} />
                    Empty ad set (no ads)
                  </label>
                </div>
              </Field>

              <Field label="New ad set name suffix">
                <input
                  type="text" className="input-base"
                  value={form.duplicate_name_suffix}
                  onChange={e => setForm({...form, duplicate_name_suffix: e.target.value})}
                />
                <label className="flex items-center gap-1.5 text-xs text-gray-600 mt-1.5">
                  <input type="checkbox" checked={form.duplicate_append_number} onChange={e => setForm({...form, duplicate_append_number: e.target.checked})} />
                  Append a number if the name already exists (e.g. "- Copy 2")
                </label>
              </Field>

              <Field label="Original ad set">
                <label className="flex items-center gap-1.5 text-sm">
                  <input type="checkbox" checked={form.duplicate_pause_original} onChange={e => setForm({...form, duplicate_pause_original: e.target.checked})} />
                  Pause the original ad set after duplicating
                </label>
              </Field>

              <Field label="Repeat">
                <label className="flex items-center gap-1.5 text-sm">
                  <input type="checkbox" checked={form.duplicate_repeat} onChange={e => setForm({...form, duplicate_repeat: e.target.checked})} />
                  Keep creating a new duplicate every time this rule re-breaches (24h minimum between duplicates) —
                  default is one-shot, like Birch
                </label>
              </Field>
            </>
          )}

          <Field label="Metric">
            <select className="input-base" value={form.metric} onChange={e => setForm({...form, metric: e.target.value})}>
              <option value="cpl">Cost Per Lead (CPL)</option>
              <option value="cpa">Cost Per Action (CPA)</option>
              <option value="ctr">Click-Through Rate (CTR)</option>
              <option value="roas">ROAS</option>
            </select>
          </Field>

          <Field label="Condition">
            <select className="input-base" value={form.operator} onChange={e => setForm({...form, operator: e.target.value})}>
              <option value="greater_than">Greater than (&gt;)</option>
              <option value="less_than">Less than (&lt;)</option>
            </select>
          </Field>

          <Field label={`Threshold (${METRIC_UNITS[form.metric]})`}>
            <input
              type="number" min="0" step={form.metric === 'roas' ? '0.1' : '1'} className="input-base"
              value={form.threshold}
              onChange={e => setForm({...form, threshold: Number(e.target.value)})}
            />
            <p className="text-xs text-gray-500 mt-1">
              {ACTION_LABELS[form.action]} when {METRIC_LABELS[form.metric]} {form.operator === 'greater_than' ? '>' : '<'} {form.metric === 'roas' ? '' : METRIC_UNITS[form.metric]}{form.threshold}{form.metric === 'roas' ? 'x' : ''}
            </p>
          </Field>

          <Field label="Minimum Spend Before Rule Fires ($)">
            <input
              type="number" min="0" className="input-base"
              value={form.min_spend}
              onChange={e => setForm({...form, min_spend: Number(e.target.value)})}
            />
            <p className="text-xs text-gray-500 mt-1">Avoid false positives — wait until this much is spent first</p>
          </Field>

          {/* Clarify what "N ad sets" actually creates — this is N independent rows,
              not one saved cohort/filter. Editing "the batch" later means editing
              each rule; that's a real difference from Birch's dynamic match count
              worth stating up front rather than let it surface as a surprise. */}
          {selectedIds.size > 1 && (
            <p className="text-xs text-gray-400 -mt-2">
              Creates {selectedIds.size} separate rules, one per ad set — each can be edited or disabled independently afterward.
            </p>
          )}
        </div>

        <div className="flex gap-3 mt-6">
          <button onClick={onClose} className="flex-1 btn-secondary">Cancel</button>
          <button onClick={handlePrimaryAction} disabled={saving || adsets.length === 0} className="flex-1 btn-primary">
            {saving ? 'Saving...' : (PERCENT_ACTIONS.has(form.action) || form.action === DUPLICATE_ACTION)
              ? 'Review & Continue'
              : `Create Rule${selectedIds.size > 1 ? ` (${selectedIds.size})` : ''}`}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Edit-rule modal ────────────────────────────────────────────────────────────
// Existing rules previously had NO way to change action/threshold/percentage
// short of delete-and-recreate, despite the backend's PATCH /rules/{id} fully
// supporting it (correct re-validation on the action+pct combination) since the
// rules-engine generalization shipped. Follow-up from that same review.
function EditRuleModal({ rule, onClose, onSaved }) {
  const { showSuccess, showError } = useToast();
  const [form, setForm] = useState({
    metric: rule.metric,
    operator: rule.operator,
    threshold: rule.threshold,
    min_spend: rule.min_spend,
    action: rule.action,
    budget_adjust_pct: rule.budget_adjust_pct || 20,
    duplicate_all_ads: rule.duplicate_all_ads ?? true,
    duplicate_name_suffix: rule.duplicate_name_suffix || '- Copy',
    duplicate_append_number: rule.duplicate_append_number || false,
    duplicate_pause_original: rule.duplicate_pause_original || false,
    duplicate_repeat: rule.duplicate_repeat || false,
  });
  const [saving, setSaving] = useState(false);

  const save = async () => {
    if (PERCENT_ACTIONS.has(form.action) && (!form.budget_adjust_pct || form.budget_adjust_pct <= 0)) {
      showError('Enter an adjustment percentage greater than 0');
      return;
    }
    if (form.action === DUPLICATE_ACTION && !form.duplicate_name_suffix?.trim()) {
      showError('Enter a name suffix for the duplicated ad set');
      return;
    }
    setSaving(true);
    try {
      const isDuplicate = form.action === DUPLICATE_ACTION;
      const res = await authFetch(`${API_BASE}/auto-pause/rules/${rule.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          metric: form.metric,
          operator: form.operator,
          threshold: form.threshold,
          min_spend: form.min_spend,
          action: form.action,
          budget_adjust_pct: PERCENT_ACTIONS.has(form.action) ? form.budget_adjust_pct : null,
          duplicate_all_ads: isDuplicate ? form.duplicate_all_ads : null,
          duplicate_name_suffix: isDuplicate ? form.duplicate_name_suffix : null,
          duplicate_append_number: isDuplicate ? form.duplicate_append_number : null,
          duplicate_pause_original: isDuplicate ? form.duplicate_pause_original : null,
          duplicate_repeat: isDuplicate ? form.duplicate_repeat : null,
        }),
      });
      if (!res.ok) { const e = await res.json(); throw new Error(e.detail || 'Failed to update rule'); }
      showSuccess('Rule updated');
      onSaved();
      onClose();
    } catch (e) { showError(e.message); }
    finally { setSaving(false); }
  };

  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50">
      <div className="bg-white rounded-2xl shadow-xl p-6 w-full max-w-lg max-h-[90vh] overflow-y-auto">
        <h2 className="text-lg font-bold text-gray-900 mb-1 flex items-center gap-2">
          <Pencil size={18} className="text-gray-500" /> Edit Rule
        </h2>
        <p className="text-sm text-gray-500 mb-4">{rule.adset_name || rule.adset_id}</p>

        <div className="space-y-4">
          <Field label="Action">
            <select className="input-base" value={form.action} onChange={e => setForm({...form, action: e.target.value})}>
              {ACTION_OPTIONS.filter(a => rule.scope === 'ad' ? ['pause', 'notify'].includes(a.value) : true).map(a => <option key={a.value} value={a.value}>{rule.scope === 'ad' && a.value === 'pause' ? 'Pause the ad' : a.label}</option>)}
            </select>
          </Field>

          {PERCENT_ACTIONS.has(form.action) && (
            <>
              <div className="flex items-start gap-2 bg-amber-50 border border-amber-300 rounded-lg px-3 py-2.5 text-xs text-amber-900">
                <AlertTriangle size={15} className="text-amber-600 flex-shrink-0 mt-0.5" />
                <span>
                  <strong>This automatically changes live {form.action.includes('bid') ? 'bid amount' : 'ad spend'} on Meta</strong> — unattended, checked every
                  30 minutes, with no confirmation dialog when it fires.
                  {form.action.includes('bid') && (
                    <> If the ad set has no manual bid cap set (e.g. it's running Meta's automatic "Lowest Cost" bidding),
                    this rule can't do anything and will disable itself with an error the first time it checks — visible
                    in the rule's fire history.</>
                  )}
                </span>
              </div>
              <Field label={`Adjust ${form.action.includes('bid') ? 'bid' : 'budget'} by (%)`}>
                <input
                  type="number" min="1" max="100" className="input-base"
                  value={form.budget_adjust_pct}
                  onChange={e => setForm({...form, budget_adjust_pct: Number(e.target.value)})}
                />
              </Field>
            </>
          )}

          {form.action === DUPLICATE_ACTION && (
            <>
              <div className="flex items-start gap-2 bg-violet-50 border border-violet-300 rounded-lg px-3 py-2.5 text-xs text-violet-900">
                <AlertTriangle size={15} className="text-violet-600 flex-shrink-0 mt-0.5" />
                <span>
                  <strong>This creates a real new ad set on Meta, starting from zero spend</strong> — unattended,
                  checked every 30 minutes. The new ad set (and its ads, if included) launch <strong>PAUSED</strong> —
                  nothing spends until someone reviews and turns it on. It inherits the original's budget (or shares
                  its CBO campaign's budget) exactly as-is.
                </span>
              </div>

              <Field label="Ads to include">
                <div className="flex gap-4 text-sm">
                  <label className="flex items-center gap-1.5">
                    <input type="radio" checked={form.duplicate_all_ads} onChange={() => setForm({...form, duplicate_all_ads: true})} />
                    All ads
                  </label>
                  <label className="flex items-center gap-1.5">
                    <input type="radio" checked={!form.duplicate_all_ads} onChange={() => setForm({...form, duplicate_all_ads: false})} />
                    Empty ad set (no ads)
                  </label>
                </div>
              </Field>

              <Field label="New ad set name suffix">
                <input
                  type="text" className="input-base"
                  value={form.duplicate_name_suffix}
                  onChange={e => setForm({...form, duplicate_name_suffix: e.target.value})}
                />
                <label className="flex items-center gap-1.5 text-xs text-gray-600 mt-1.5">
                  <input type="checkbox" checked={form.duplicate_append_number} onChange={e => setForm({...form, duplicate_append_number: e.target.checked})} />
                  Append a number if the name already exists (e.g. "- Copy 2")
                </label>
              </Field>

              <Field label="Original ad set">
                <label className="flex items-center gap-1.5 text-sm">
                  <input type="checkbox" checked={form.duplicate_pause_original} onChange={e => setForm({...form, duplicate_pause_original: e.target.checked})} />
                  Pause the original ad set after duplicating
                </label>
              </Field>

              <Field label="Repeat">
                <label className="flex items-center gap-1.5 text-sm">
                  <input type="checkbox" checked={form.duplicate_repeat} onChange={e => setForm({...form, duplicate_repeat: e.target.checked})} />
                  Keep creating a new duplicate every time this rule re-breaches (24h minimum between duplicates)
                </label>
              </Field>
            </>
          )}

          <Field label="Metric">
            <select className="input-base" value={form.metric} onChange={e => setForm({...form, metric: e.target.value})}>
              <option value="cpl">Cost Per Lead (CPL)</option>
              <option value="cpa">Cost Per Action (CPA)</option>
              <option value="ctr">Click-Through Rate (CTR)</option>
              <option value="roas">ROAS</option>
            </select>
          </Field>

          <Field label="Condition">
            <select className="input-base" value={form.operator} onChange={e => setForm({...form, operator: e.target.value})}>
              <option value="greater_than">Greater than (&gt;)</option>
              <option value="less_than">Less than (&lt;)</option>
            </select>
          </Field>

          <Field label={`Threshold (${METRIC_UNITS[form.metric]})`}>
            <input
              type="number" min="0" step={form.metric === 'roas' ? '0.1' : '1'} className="input-base"
              value={form.threshold}
              onChange={e => setForm({...form, threshold: Number(e.target.value)})}
            />
          </Field>

          <Field label="Minimum Spend Before Rule Fires ($)">
            <input
              type="number" min="0" className="input-base"
              value={form.min_spend}
              onChange={e => setForm({...form, min_spend: Number(e.target.value)})}
            />
          </Field>
        </div>

        <div className="flex gap-3 mt-6">
          <button onClick={onClose} className="flex-1 btn-secondary">Cancel</button>
          <button onClick={save} disabled={saving} className="flex-1 btn-primary">
            {saving ? 'Saving...' : 'Save Changes'}
          </button>
        </div>
      </div>
    </div>
  );
}

function Field({ label, children }) {
  return (
    <div>
      <label className="block text-sm font-medium text-gray-700 mb-1">{label}</label>
      {children}
    </div>
  );
}

// Surfaces GET /auto-pause/rules/{id}/logs — built on the backend as part of this
// generalization but, before this fix, never wired into the UI at all (pre-push
// review P0: no way for Joel to see what a rule actually DID after it fired —
// old→new budget, success/error — short of asking an engineer to query the DB).
function RuleHistoryToggle({ rule }) {
  const { showError } = useToast();
  const [open, setOpen] = useState(false);
  const [logs, setLogs] = useState(null);
  const [loading, setLoading] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const res = await authFetch(`${API_BASE}/auto-pause/rules/${rule.id}/logs`);
      if (!res.ok) throw new Error('Failed to load history');
      setLogs(await res.json());
    } catch (e) { showError(e.message); }
    finally { setLoading(false); }
  };

  const toggle = () => {
    const next = !open;
    setOpen(next);
    if (next && logs === null) load();
  };

  return (
    <div className="relative">
      <button
        onClick={toggle}
        className="p-1.5 rounded-lg hover:bg-gray-100 transition-colors text-gray-400 hover:text-gray-700"
        title="View fire history"
      >
        <Target size={16} />
      </button>
      {open && (
        <div className="absolute right-0 top-full mt-1 w-80 max-h-64 overflow-y-auto bg-white border border-gray-200 rounded-lg shadow-lg z-20 text-left">
          <div className="px-3 py-2 border-b border-gray-100 text-xs font-semibold text-gray-700">Fire history</div>
          {loading ? (
            <div className="px-3 py-4 text-xs text-gray-400 text-center flex items-center justify-center gap-2">
              <RefreshCw size={12} className="animate-spin" /> Loading...
            </div>
          ) : !logs || logs.length === 0 ? (
            <div className="px-3 py-4 text-xs text-gray-400 text-center">Never fired</div>
          ) : (
            <div className="divide-y divide-gray-50">
              {logs.map(l => (
                <div key={l.id} className="px-3 py-2 text-xs">
                  <div className="flex items-center justify-between gap-2">
                    <span className={`font-medium ${l.result === 'success' ? 'text-gray-900' : 'text-red-600'}`}>
                      {l.result === 'success' ? (TRIGGERED_LABELS[l.action] || l.action) : `Error (${ACTION_LABELS[l.action] || l.action})`}
                    </span>
                    <span className="text-gray-400 flex-shrink-0">{new Date(l.created_at).toLocaleString()}</span>
                  </div>
                  {l.detail && <div className="text-gray-500 mt-0.5">{l.detail}</div>}
                  {l.scope === 'ad' && <div className="text-violet-600 mt-0.5">Ad: {l.ad_name || l.fb_ad_id}</div>}
                  <div className="text-gray-400 mt-0.5">
                    {METRIC_LABELS[l.metric] || l.metric} {l.metric_value != null ? `$${l.metric_value}` : ''} vs threshold {l.threshold}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Main page ──────────────────────────────────────────────────────────────────
export default function AutoPauseRules() {
  const { showSuccess, showError, showInfo } = useToast();
  const [rules, setRules]     = useState([]);
  const [adsets, setAdsets]   = useState([]);
  const [ads, setAds]         = useState([]);
  const [loading, setLoading] = useState(true);
  const [checking, setChecking] = useState(false);
  const [showAddRule, setShowAddRule] = useState(false);
  const [editingRule, setEditingRule] = useState(null);
  const [lastCheckResult, setLastCheckResult] = useState(null);

  const loadRules = useCallback(async () => {
    try {
      const res = await authFetch(`${API_BASE}/auto-pause/rules`);
      if (!res.ok) throw new Error('Failed to load rules');
      setRules(await res.json());
    } catch (e) { showError(e.message); }
  }, [showError]);

  const loadAdsets = useCallback(async () => {
    try {
      const res = await authFetch(`${API_BASE}/facebook/adsets/saved`);
      if (!res.ok) throw new Error('Failed to load ad sets');
      const data = await res.json();
      setAdsets(Array.isArray(data) ? data : data.adsets || []);
    } catch (error) { void error; /* non-fatal — adsets only needed for rule creation */ }
  }, []);

  const loadAds = useCallback(async () => {
    try {
      const adAccountId = localStorage.getItem('fb_ad_account_id') || '';
      const params = new URLSearchParams({ include_all: 'true' });
      if (adAccountId) params.set('ad_account_id', adAccountId);
      const res = await authFetch(`${API_BASE}/auto-pause/ads-bulk?${params.toString()}`);
      if (!res.ok) throw new Error('Failed to load ads');
      const data = await res.json();
      const byFbAdset = new Map(adsets.map(a => [String(a.fb_adset_id), a]));
      setAds(Object.entries(data || {}).flatMap(([fbAdsetId, rows]) => (rows || []).map(row => {
        const parent = byFbAdset.get(String(fbAdsetId));
        return parent ? { id: row.ad_id, fb_ad_id: row.ad_id, name: row.ad_name || row.ad_id, adset_id: parent.id, adset_name: parent.name, fb_adset_id: fbAdsetId } : null;
      }).filter(Boolean)));
    } catch (error) { void error; /* non-fatal — ads only needed for ad-scoped rule creation */ }
  }, [adsets]);

  useEffect(() => {
    Promise.all([loadRules(), loadAdsets()]).finally(() => setLoading(false));
  }, [loadRules, loadAdsets]);

  // Lazy — only when the Add Rule modal is actually opened, and only once per
  // session (ads.length gate). `include_all=true` makes this call a full
  // account-wide ACTIVE/PAUSED-ads-with-creative fetch (get_account_ads_with_
  // creative), the same heavier call the Copy Library page only runs from a
  // manual "Sync" button — firing it unconditionally on every page mount
  // (the prior version of this effect) turns a rarely-used, deliberately
  // manual operation into an automatic one on every visit to this page,
  // which is exactly the kind of avoidable Meta API volume this repo has a
  // documented incident from (project_adbuilder_meta_app_review_rejection).
  useEffect(() => {
    if (showAddRule && adsets.length && ads.length === 0) loadAds();
  }, [showAddRule, adsets, ads.length, loadAds]);

  const deleteRule = async (ruleId) => {
    if (!window.confirm('Delete this auto-pause rule? This cannot be undone.')) return;
    try {
      const res = await authFetch(`${API_BASE}/auto-pause/rules/${ruleId}`, { method: 'DELETE' });
      if (!res.ok) throw new Error('Failed to delete rule');
      showSuccess('Rule deleted');
      loadRules();
    } catch (e) { showError(e.message); }
  };

  const toggleRule = async (rule) => {
    try {
      const res = await authFetch(`${API_BASE}/auto-pause/rules/${rule.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ is_active: !rule.is_active }),
      });
      if (!res.ok) throw new Error('Failed to update rule');
      showSuccess(rule.is_active ? 'Rule disabled' : 'Rule enabled');
      loadRules();
    } catch (e) { showError(e.message); }
  };

  const runCheck = async () => {
    setChecking(true);
    showInfo('Checking all rules against live Meta data...');
    try {
      const adAccountId = localStorage.getItem('fb_ad_account_id') || '';
      const params = adAccountId ? `?ad_account_id=${adAccountId}` : '';
      const res = await authFetch(`${API_BASE}/auto-pause/check${params}`, { method: 'POST' });
      if (!res.ok) throw new Error('Check failed');
      const result = await res.json();
      setLastCheckResult(result);
      const firedCount = (result.paused?.length || 0) + (result.notified?.length || 0) + (result.budget_adjusted?.length || 0)
        + (result.bid_adjusted?.length || 0) + (result.duplicated?.length || 0);
      const errorCount = result.errors?.length || 0;
      if (firedCount > 0) {
        showSuccess(`${firedCount} rule(s) fired!`);
      } else if (errorCount > 0) {
        showError(`${errorCount} rule(s) errored — see details below.`);
      } else {
        showSuccess(`All clear — ${result.rules_evaluated} rules evaluated, none triggered.`);
      }
      loadRules();
    } catch (e) { showError(e.message); }
    finally { setChecking(false); }
  };

  return (
    <div className="max-w-4xl mx-auto space-y-8">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-2">
            <PauseCircle size={24} className="text-red-500" />
            Rules Engine
          </h1>
          <p className="text-gray-500 text-sm mt-1">
            Pause an ad set, notify Slack, adjust its budget/bid, or duplicate it when a metric breaches a threshold — checked automatically every 30 minutes.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={runCheck}
            disabled={checking}
            className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium text-white transition-colors disabled:opacity-50"
            style={{ backgroundColor: checking ? '#9CA3AF' : '#2D2463' }}
          >
            <RefreshCw size={14} className={checking ? 'animate-spin' : ''} />
            {checking ? 'Checking...' : 'Run Check Now'}
          </button>
          <button
            onClick={() => setShowAddRule(true)}
            className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium bg-red-500 text-white hover:bg-red-600 transition-colors"
          >
            <Plus size={14} /> Add Rule
          </button>
        </div>
      </div>

      {/* Last check result */}
      {lastCheckResult && (() => {
        const paused = lastCheckResult.paused || [];
        const notified = lastCheckResult.notified || [];
        const budgetAdjusted = lastCheckResult.budget_adjusted || [];
        const bidAdjusted = lastCheckResult.bid_adjusted || [];
        const duplicated = lastCheckResult.duplicated || [];
        const errors = lastCheckResult.errors || [];
        const firedCount = paused.length + notified.length + budgetAdjusted.length + bidAdjusted.length + duplicated.length;
        const targetCount = (items) => {
          const ads = items.filter(item => item.scope === 'ad').length;
          const adsets = items.length - ads;
          const parts = [];
          if (adsets) parts.push(`${adsets} ad set${adsets !== 1 ? 's' : ''}`);
          if (ads) parts.push(`${ads} ad${ads !== 1 ? 's' : ''}`);
          return parts.join(' and ');
        };
        const targetName = (item) => item.ad ? `${item.adset} / ${item.ad}` : item.adset;
        // Errors can exist even when nothing fired (an insights fetch failure, or a
        // rule action that threw) — previously this branch only checked firedCount,
        // so a run with 0 fires but real errors silently rendered as "All clear"
        // with no indication anything went wrong. Caught in pre-push review.
        return (
          <div className={`rounded-xl p-4 border space-y-3 ${firedCount > 0 || errors.length > 0 ? 'bg-red-50 border-red-200' : 'bg-green-50 border-green-200'}`}>
            {firedCount === 0 && errors.length === 0 ? (
              <div className="flex items-center gap-2 text-green-800 text-sm font-medium">
                <CheckCircle size={16} /> All clear — {lastCheckResult.rules_evaluated} rule{lastCheckResult.rules_evaluated !== 1 ? 's' : ''} evaluated, none triggered.
              </div>
            ) : (
              <>
                {errors.length > 0 && (
                  <div>
                    <h3 className="font-semibold text-red-900 flex items-center gap-2 mb-1">
                      <AlertTriangle size={16} /> {errors.length} rule{errors.length !== 1 ? 's' : ''} errored
                    </h3>
                    {errors.map((e, i) => (
                      <div key={i} className="text-sm text-red-800"><strong>{e.adset || e.rule_id}</strong> — {e.error || e.reason}</div>
                    ))}
                  </div>
                )}
                {paused.length > 0 && (
                  <div>
                    <h3 className="font-semibold text-red-800 flex items-center gap-2 mb-1">
                      <PauseCircle size={16} /> Paused {targetCount(paused)}
                    </h3>
                    {paused.map((p, i) => (
                      <div key={i} className="text-sm text-red-700"><strong>{targetName(p)}</strong> — {p.reason}</div>
                    ))}
                  </div>
                )}
                {notified.length > 0 && (
                  <div>
                    <h3 className="font-semibold text-blue-800 flex items-center gap-2 mb-1">
                      <Bell size={16} /> Notified for {targetCount(notified)}
                    </h3>
                    {notified.map((n, i) => (
                      <div key={i} className="text-sm text-blue-700"><strong>{targetName(n)}</strong> — {n.reason}</div>
                    ))}
                  </div>
                )}
                {budgetAdjusted.length > 0 && (
                  <div>
                    <h3 className="font-semibold text-emerald-800 flex items-center gap-2 mb-1">
                      <TrendingUp size={16} /> Budget adjusted on {budgetAdjusted.length} ad set{budgetAdjusted.length !== 1 ? 's' : ''}
                    </h3>
                    {budgetAdjusted.map((b, i) => (
                      <div key={i} className="text-sm text-emerald-700"><strong>{b.adset}</strong> — {b.detail}</div>
                    ))}
                  </div>
                )}
                {bidAdjusted.length > 0 && (
                  <div>
                    <h3 className="font-semibold text-emerald-800 flex items-center gap-2 mb-1">
                      <TrendingUp size={16} /> Bid adjusted on {bidAdjusted.length} ad set{bidAdjusted.length !== 1 ? 's' : ''}
                    </h3>
                    {bidAdjusted.map((b, i) => (
                      <div key={i} className="text-sm text-emerald-700"><strong>{b.adset}</strong> — {b.detail}</div>
                    ))}
                  </div>
                )}
                {duplicated.length > 0 && (
                  <div>
                    <h3 className="font-semibold text-violet-800 flex items-center gap-2 mb-1">
                      <Copy size={16} /> Duplicated {duplicated.length} ad set{duplicated.length !== 1 ? 's' : ''}
                    </h3>
                    {duplicated.map((d, i) => (
                      <div key={i} className="text-sm text-violet-700"><strong>{d.adset}</strong> — {d.detail}</div>
                    ))}
                  </div>
                )}
              </>
            )}
          </div>
        );
      })()}

      {/* Rules list */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
        <div className="px-6 py-4 border-b border-gray-100">
          <h2 className="font-semibold text-gray-900 flex items-center gap-2">
            <Target size={15} className="text-gray-400" />
            Active Rules
            {!loading && (
              <span className="text-xs text-gray-400 font-normal">{rules.length} rule{rules.length !== 1 ? 's' : ''}</span>
            )}
          </h2>
        </div>

        {loading ? (
          <div className="p-10 text-center text-gray-400 text-sm flex items-center justify-center gap-2">
            <RefreshCw size={14} className="animate-spin" /> Loading rules...
          </div>
        ) : rules.length === 0 ? (
          <div className="p-10 text-center">
            <PauseCircle size={36} className="text-gray-200 mx-auto mb-3" />
            <p className="text-gray-500 text-sm font-medium">No rules yet</p>
            <p className="text-gray-400 text-xs mt-1 max-w-xs mx-auto">
              Pause, notify, or adjust budget automatically when a metric crosses a threshold — checked every 30 minutes.
            </p>
            <button
              onClick={() => setShowAddRule(true)}
              className="mt-4 flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium bg-red-500 text-white hover:bg-red-600 transition-colors mx-auto"
            >
              <Plus size={13} /> Create your first rule
            </button>
          </div>
        ) : (
          <div className="divide-y divide-gray-50">
            {rules.map(rule => {
              const triggeredLabel = TRIGGERED_LABELS[rule.action] || 'Triggered';
              return (
              <div key={rule.id} className={!rule.is_active ? 'opacity-50' : ''}>
                <div className="px-6 py-4 flex items-center justify-between gap-4">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-medium text-gray-900 text-sm truncate">{rule.scope === 'ad' ? (rule.ad_name || rule.fb_ad_id) : (rule.adset_name || rule.adset_id)}</span>
                      <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${rule.scope === 'ad' ? 'bg-violet-50 text-violet-700' : 'bg-gray-100 text-gray-600'}`}>
                        {rule.scope === 'ad' ? 'Ad' : 'Ad Set'}
                      </span>
                      <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${ACTION_BADGE_CLS[rule.action] || 'bg-gray-100 text-gray-700'}`}>
                        {rule.scope === 'ad' && rule.action === 'pause' ? 'Pause the ad' : ACTION_LABELS[rule.action] || rule.action}
                      </span>
                      <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                        rule.triggered_at
                          // Red only for pause (a real red=bad/stopped outcome in Joel's
                          // Ads Manager mental model) — Duplicate is a scaling action, not
                          // a stop, so it stays in the action's own violet rather than
                          // reusing pause's alarm color (joel-perspective P2).
                          ? (rule.action === DUPLICATE_ACTION ? 'bg-violet-100 text-violet-700' : 'bg-red-100 text-red-700')
                          : rule.is_active
                            ? 'bg-green-100 text-green-700'
                            : 'bg-gray-100 text-gray-500'
                      }`}>
                        {/* Action-specific copy, not a generic "Triggered" — a budget
                            rule that already fired and disabled itself reads very
                            differently from a paused ad set (pre-push review P1). */}
                        {rule.triggered_at ? triggeredLabel : rule.is_active ? 'Active' : 'Disabled'}
                      </span>
                    </div>

                    {/* Ad names are commonly reused across ad sets (creative-testing
                        naming conventions) — without the parent ad set shown, Joel
                        can't tell at a glance which campaign/budget an ad-scoped rule
                        actually governs on a tool that pauses live spend (pre-push
                        review, MEDIUM). adset_name is already in the API payload. */}
                    {rule.scope === 'ad' && (
                      <p className="text-xs text-gray-400 mt-0.5 truncate">
                        in {rule.adset_name || rule.adset_id}
                      </p>
                    )}

                    <p className="text-xs text-gray-500 mt-1">
                      {rule.scope === 'ad' && rule.action === 'pause' ? 'Pause the ad' : ACTION_LABELS[rule.action] || rule.action}
                      {PERCENT_ACTIONS.has(rule.action) && rule.budget_adjust_pct ? ` by ${rule.budget_adjust_pct}%` : ''}
                      {' '}if {METRIC_LABELS[rule.metric]} {rule.operator === 'greater_than' ? '>' : '<'} {METRIC_UNITS[rule.metric]}{rule.threshold}
                      {' '}after ${rule.min_spend} spend
                    </p>

                    {rule.trigger_reason && (
                      <p className="text-xs text-red-600 mt-0.5 flex items-center gap-1">
                        <AlertTriangle size={10} /> {rule.trigger_reason}
                      </p>
                    )}

                    {rule.last_checked_at && (
                      <p className="text-xs text-gray-400 mt-0.5">
                        Last checked: {new Date(rule.last_checked_at).toLocaleString()}
                      </p>
                    )}
                  </div>

                  <div className="flex items-center gap-2 flex-shrink-0">
                    <RuleHistoryToggle rule={rule} />
                    <button
                      onClick={() => setEditingRule(rule)}
                      className="p-1.5 rounded-lg hover:bg-gray-100 transition-colors text-gray-400 hover:text-gray-700"
                      title="Edit rule"
                    >
                      <Pencil size={16} />
                    </button>
                    <button
                      onClick={() => toggleRule(rule)}
                      className="p-1.5 rounded-lg hover:bg-gray-100 transition-colors text-gray-400 hover:text-gray-700"
                      title={rule.is_active ? 'Disable rule' : 'Enable rule'}
                    >
                      {rule.is_active ? <PauseCircle size={16} /> : <PlayCircle size={16} />}
                    </button>
                    <button
                      onClick={() => deleteRule(rule.id)}
                      className="p-1.5 rounded-lg hover:bg-red-50 transition-colors text-gray-400 hover:text-red-500"
                      title="Delete rule"
                    >
                      <Trash2 size={16} />
                    </button>
                  </div>
                </div>
              </div>
              );
            })}
          </div>
        )}
      </div>

      {/* How it works */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6">
        <h3 className="font-semibold text-gray-800 text-sm mb-3 flex items-center gap-2">
          <Zap size={14} className="text-amber-500" /> How the Rules Engine Works
        </h3>
        <div className="grid grid-cols-1 sm:grid-cols-4 gap-4 text-xs text-gray-500">
          <div className="flex flex-col gap-1">
            <span className="font-semibold text-gray-700">1. Pick ad set(s) + an action</span>
            <span>Select one or more ad sets and what should happen: pause, notify Slack, or adjust budget.</span>
          </div>
          <div className="flex flex-col gap-1">
            <span className="font-semibold text-gray-700">2. Set a threshold</span>
            <span>Define a metric (CPL, CTR, ROAS) and the value that triggers the action.</span>
          </div>
          <div className="flex flex-col gap-1">
            <span className="font-semibold text-gray-700">3. Set a minimum spend</span>
            <span>Prevent false positives — the rule only fires after enough data has accumulated.</span>
          </div>
          <div className="flex flex-col gap-1">
            <span className="font-semibold text-gray-700">4. Runs automatically</span>
            <span>The system checks every 30 minutes. You can also trigger a manual check at any time.</span>
          </div>
        </div>
        {/* Unlike Ads Manager's own automated rules (which stay on until you turn
            them off), Pause/Increase/Decrease rules here fire once and disable
            themselves — flagged in pre-push review as a real behavior difference
            worth stating explicitly, not just in a rule-row badge. */}
        <p className="text-xs text-gray-400 mt-4 pt-4 border-t border-gray-100">
          Unlike Ads Manager's own automated rules: Pause, budget/bid, and Duplicate rules here fire <strong>once</strong>, then
          disable themselves — they won't keep re-firing every 30 minutes (Duplicate can be set to repeat instead).
          Notify rules keep re-checking (with a 4-hour cooldown between repeat Slack alerts for the same ongoing breach)
          since nothing changes on Meta to disable.
        </p>
      </div>

      {showAddRule && (
        <AddRuleModal
          adsets={adsets}
          ads={ads}
          onClose={() => setShowAddRule(false)}
          onCreated={loadRules}
        />
      )}

      {editingRule && (
        <EditRuleModal
          rule={editingRule}
          onClose={() => setEditingRule(null)}
          onSaved={loadRules}
        />
      )}
    </div>
  );
}
