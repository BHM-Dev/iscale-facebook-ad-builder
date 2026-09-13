import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { PauseCircle, PlayCircle, Trash2, Plus, RefreshCw, AlertTriangle, CheckCircle, Zap, Target, Bell, TrendingUp, TrendingDown, Search } from 'lucide-react';
import { useToast } from '../context/ToastContext';
import { authFetch } from '../lib/facebookApi';

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1';

const METRIC_LABELS = { cpl: 'Cost Per Lead', cpa: 'Cost Per Action', ctr: 'CTR', roas: 'ROAS' };
const METRIC_UNITS  = { cpl: '$', cpa: '$', ctr: '%', roas: 'x' };

const ACTION_OPTIONS = [
  { value: 'pause', label: 'Pause the ad set', icon: PauseCircle, color: 'text-red-500' },
  { value: 'notify', label: 'Notify (Slack only, no change on Meta)', icon: Bell, color: 'text-blue-500' },
  { value: 'increase_budget', label: 'Increase budget', icon: TrendingUp, color: 'text-emerald-600' },
  { value: 'decrease_budget', label: 'Decrease budget', icon: TrendingDown, color: 'text-amber-600' },
];
const ACTION_LABELS = Object.fromEntries(ACTION_OPTIONS.map(a => [a.value, a.label]));
const BUDGET_ACTIONS = new Set(['increase_budget', 'decrease_budget']);
const ACTION_BADGE_CLS = {
  pause: 'bg-red-50 text-red-600',
  notify: 'bg-blue-50 text-blue-600',
  increase_budget: 'bg-emerald-50 text-emerald-700',
  decrease_budget: 'bg-amber-50 text-amber-700',
};
// Action-specific "already fired" copy — a generic red "Triggered" pill reads
// identically for a paused ad set and a budget change, which pre-push review
// flagged as a real gap (Joel can't tell what actually happened at a glance).
const TRIGGERED_LABELS = {
  pause: 'Paused',
  notify: 'Notified',
  increase_budget: 'Budget increased',
  decrease_budget: 'Budget decreased',
};

// Best-effort CURRENT budget for the pre-commit confirmation step, from whatever
// this app already has cached locally (adsets/saved) — not a live Meta read, which
// would mean one API call per selected ad set just to show a preview. The rule
// itself always reads the true live value at fire time (facebook_service.py),
// so a stale preview here can't cause a wrong amount to actually be sent to Meta —
// it can only make the PREVIEW number look off by however much has drifted since
// the last sync. Labeled "as of last sync" in the UI so that's not implied to be live.
const currentBudgetCents = (adset) => {
  if (adset.daily_budget) return { cents: adset.daily_budget, source: 'ad set' };
  if (adset.campaign_daily_budget) return { cents: adset.campaign_daily_budget, source: 'CBO campaign' };
  return null;
};

// ── Add-rule modal ─────────────────────────────────────────────────────────────
function AddRuleModal({ adsets, onClose, onCreated }) {
  const { showSuccess, showError } = useToast();
  const [selectedIds, setSelectedIds] = useState(() => new Set(adsets[0] ? [adsets[0].id] : []));
  const [search, setSearch] = useState('');
  const [form, setForm] = useState({
    metric: 'cpl',
    operator: 'greater_than',
    threshold: 50,
    min_spend: 20,
    action: 'pause',
    budget_adjust_pct: 20,
  });
  const [saving, setSaving] = useState(false);
  // 'form' | 'confirm' — budget actions get a mandatory second step listing every
  // matched ad set's current → computed-new budget before anything is written.
  // Pause/notify skip straight to save() since neither moves money.
  const [step, setStep] = useState('form');

  const filteredAdsets = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return adsets;
    return adsets.filter(a => a.name?.toLowerCase().includes(q));
  }, [adsets, search]);

  const toggleAdset = (id) => {
    setSelectedIds(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const toggleAll = () => {
    setSelectedIds(prev => {
      const allFilteredSelected = filteredAdsets.length > 0 && filteredAdsets.every(a => prev.has(a.id));
      if (allFilteredSelected) {
        // Deselect just the currently-visible (filtered) set, keep any other selections intact
        const next = new Set(prev);
        filteredAdsets.forEach(a => next.delete(a.id));
        return next;
      }
      const next = new Set(prev);
      filteredAdsets.forEach(a => next.add(a.id));
      return next;
    });
  };

  const validateBeforeContinue = () => {
    if (selectedIds.size === 0) { showError('Select at least one ad set'); return false; }
    if (BUDGET_ACTIONS.has(form.action) && (!form.budget_adjust_pct || form.budget_adjust_pct <= 0)) {
      showError('Enter a budget adjustment percentage greater than 0');
      return false;
    }
    return true;
  };

  // Budget actions never submit directly from the form — they route through the
  // confirm step below first (P0 per pre-push review: bulk-scoped budget changes
  // need a review-before-commit step, not just a live count).
  const handlePrimaryAction = () => {
    if (!validateBeforeContinue()) return;
    if (BUDGET_ACTIONS.has(form.action)) {
      setStep('confirm');
    } else {
      save();
    }
  };

  const save = async () => {
    if (!validateBeforeContinue()) return;
    setSaving(true);
    try {
      const res = await authFetch(`${API_BASE}/auto-pause/rules/bulk`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          adset_ids: Array.from(selectedIds),
          metric: form.metric,
          operator: form.operator,
          threshold: form.threshold,
          min_spend: form.min_spend,
          action: form.action,
          budget_adjust_pct: BUDGET_ACTIONS.has(form.action) ? form.budget_adjust_pct : null,
        }),
      });
      if (!res.ok) { const e = await res.json(); throw new Error(e.detail || 'Failed'); }
      const data = await res.json();
      showSuccess(`${data.created} rule${data.created !== 1 ? 's' : ''} created`);
      onCreated();
      onClose();
    } catch (e) { showError(e.message); }
    finally { setSaving(false); }
  };

  const allFilteredSelected = filteredAdsets.length > 0 && filteredAdsets.every(a => selectedIds.has(a.id));
  const selectedAdsets = adsets.filter(a => selectedIds.has(a.id));

  // ── Confirm step (budget actions only) — every matched ad set + its current →
  // computed-new budget, reviewed before anything is written. Replaces "a live
  // count is the only guardrail" with an actual line-by-line preview.
  if (step === 'confirm') {
    const pct = form.action === 'increase_budget' ? form.budget_adjust_pct : -form.budget_adjust_pct;
    return (
      <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50">
        <div className="bg-white rounded-2xl shadow-xl p-6 w-full max-w-lg max-h-[90vh] overflow-y-auto">
          <h2 className="text-lg font-bold text-gray-900 mb-1 flex items-center gap-2">
            <AlertTriangle size={20} className="text-amber-500" /> Confirm budget rule
          </h2>
          <p className="text-sm text-gray-600 mb-4">
            Review every ad set this rule will apply to before creating it. Each row fires
            independently — this is real live Meta spend, not a preview.
          </p>

          <div className="border border-gray-200 rounded-lg divide-y divide-gray-50 max-h-64 overflow-y-auto mb-4">
            {selectedAdsets.map(a => {
              const current = currentBudgetCents(a);
              return (
                <div key={a.id} className="px-3 py-2 text-sm">
                  <div className="font-medium text-gray-900 truncate">{a.name}</div>
                  {current ? (
                    <div className="text-xs text-gray-500">
                      Current ({current.source}, as of last sync): <strong>${(current.cents / 100).toFixed(2)}</strong>
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
            edited or disabled on its own afterward. None of them run once; every rule disables itself the moment it fires,
            so it won't keep compounding this change every 30 minutes unattended.
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
          <Field label="Ad Set(s)">
            {adsets.length === 0 ? (
              <div className="px-3 py-2 text-sm text-amber-700 bg-amber-50 border border-amber-200 rounded-lg">
                No tracked ad sets found. Add ad sets in Campaign Performance first.
              </div>
            ) : (
              <div className="border border-gray-200 rounded-lg overflow-hidden">
                <div className="flex items-center gap-2 px-2 py-1.5 border-b border-gray-100 bg-gray-50">
                  <Search size={13} className="text-gray-400 flex-shrink-0" />
                  <input
                    type="text"
                    placeholder="Search ad sets..."
                    value={search}
                    onChange={e => setSearch(e.target.value)}
                    className="flex-1 min-w-0 text-sm bg-transparent outline-none"
                  />
                  <button type="button" onClick={toggleAll} className="text-xs font-medium text-blue-600 hover:text-blue-800 flex-shrink-0">
                    {allFilteredSelected ? 'Deselect all' : 'Select all'}
                  </button>
                </div>
                <div className="max-h-40 overflow-y-auto divide-y divide-gray-50">
                  {filteredAdsets.length === 0 ? (
                    <div className="px-3 py-3 text-xs text-gray-400 text-center">No matching ad sets</div>
                  ) : filteredAdsets.map(a => (
                    <label key={a.id} className="flex items-center gap-2 px-3 py-2 text-sm hover:bg-gray-50 cursor-pointer">
                      <input type="checkbox" checked={selectedIds.has(a.id)} onChange={() => toggleAdset(a.id)} />
                      <span className="truncate">{a.name}</span>
                    </label>
                  ))}
                </div>
              </div>
            )}
            {/* Live match count — the one UX detail worth copying exactly from Birch's
                Automated Rules builder ("Estimated match: N ad sets"): see it before you
                commit, not after. */}
            <p className="text-xs mt-1.5 font-medium text-gray-600">
              Applies to <span className="text-gray-900">{selectedIds.size}</span> ad set{selectedIds.size !== 1 ? 's' : ''}
            </p>
          </Field>

          <Field label="Action">
            <select className="input-base" value={form.action} onChange={e => setForm({...form, action: e.target.value})}>
              {ACTION_OPTIONS.map(a => <option key={a.value} value={a.value}>{a.label}</option>)}
            </select>
          </Field>

          {BUDGET_ACTIONS.has(form.action) && (
            <>
              {/* Hard visual break from the low-friction pause/notify path — this
                  moves real, live ad spend on Meta with no confirmation dialog on
                  Meta's own side (unlike Ads Manager, which confirms every manual
                  budget edit). Shown the moment a budget action is picked, before
                  any field below it is even filled in. */}
              <div className="flex items-start gap-2 bg-amber-50 border border-amber-300 rounded-lg px-3 py-2.5 text-xs text-amber-900">
                <AlertTriangle size={15} className="text-amber-600 flex-shrink-0 mt-0.5" />
                <span>
                  <strong>This automatically changes live ad spend on Meta</strong> — unattended, checked every
                  30 minutes, with no confirmation dialog when it fires. It disables itself after firing once.
                </span>
              </div>
              <Field label="Adjust budget by (%)">
                <input
                  type="number" min="1" max="100" className="input-base"
                  value={form.budget_adjust_pct}
                  onChange={e => setForm({...form, budget_adjust_pct: Number(e.target.value)})}
                />
                <p className="text-xs text-gray-500 mt-1">
                  {form.action === 'increase_budget' ? 'Increases' : 'Decreases'} the ad set's (or its CBO campaign's)
                  current budget by this percentage. Reads the live Meta value at fire time, not a cached one.
                </p>
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
            {saving ? 'Saving...' : BUDGET_ACTIONS.has(form.action)
              ? 'Review & Continue'
              : `Create Rule${selectedIds.size > 1 ? ` (${selectedIds.size})` : ''}`}
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
  const [loading, setLoading] = useState(true);
  const [checking, setChecking] = useState(false);
  const [showAddRule, setShowAddRule] = useState(false);
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
    } catch (_) { /* non-fatal — adsets only needed for rule creation */ }
  }, []);

  useEffect(() => {
    Promise.all([loadRules(), loadAdsets()]).finally(() => setLoading(false));
  }, [loadRules, loadAdsets]);

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
      const firedCount = (result.paused?.length || 0) + (result.notified?.length || 0) + (result.budget_adjusted?.length || 0);
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
            Pause an ad set, notify Slack, or adjust its budget when a metric breaches a threshold — checked automatically every 30 minutes.
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
        const errors = lastCheckResult.errors || [];
        const firedCount = paused.length + notified.length + budgetAdjusted.length;
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
                      <PauseCircle size={16} /> Paused {paused.length} ad set{paused.length !== 1 ? 's' : ''}
                    </h3>
                    {paused.map((p, i) => (
                      <div key={i} className="text-sm text-red-700"><strong>{p.adset}</strong> — {p.reason}</div>
                    ))}
                  </div>
                )}
                {notified.length > 0 && (
                  <div>
                    <h3 className="font-semibold text-blue-800 flex items-center gap-2 mb-1">
                      <Bell size={16} /> Notified for {notified.length} ad set{notified.length !== 1 ? 's' : ''}
                    </h3>
                    {notified.map((n, i) => (
                      <div key={i} className="text-sm text-blue-700"><strong>{n.adset}</strong> — {n.reason}</div>
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
                      <span className="font-medium text-gray-900 text-sm truncate">{rule.adset_name || rule.adset_id}</span>
                      <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${ACTION_BADGE_CLS[rule.action] || 'bg-gray-100 text-gray-700'}`}>
                        {ACTION_LABELS[rule.action] || rule.action}
                      </span>
                      <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                        rule.triggered_at
                          ? 'bg-red-100 text-red-700'
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

                    <p className="text-xs text-gray-500 mt-1">
                      {ACTION_LABELS[rule.action] || rule.action}
                      {BUDGET_ACTIONS.has(rule.action) && rule.budget_adjust_pct ? ` by ${rule.budget_adjust_pct}%` : ''}
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
          Unlike Ads Manager's own automated rules: Pause and budget-adjustment rules here fire <strong>once</strong>, then
          disable themselves — they won't keep re-firing every 30 minutes. Notify rules keep re-checking (with a
          4-hour cooldown between repeat Slack alerts for the same ongoing breach) since nothing changes on Meta to disable.
        </p>
      </div>

      {showAddRule && (
        <AddRuleModal
          adsets={adsets}
          onClose={() => setShowAddRule(false)}
          onCreated={loadRules}
        />
      )}
    </div>
  );
}
