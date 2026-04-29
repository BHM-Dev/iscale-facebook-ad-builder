import React, { useState, useEffect, useCallback } from 'react';
import { PauseCircle, PlayCircle, Trash2, Plus, RefreshCw, AlertTriangle, CheckCircle, Zap, Target } from 'lucide-react';
import { useToast } from '../context/ToastContext';
import { authFetch } from '../lib/facebookApi';

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1';

const METRIC_LABELS = { cpl: 'Cost Per Lead', cpa: 'Cost Per Action', ctr: 'CTR', roas: 'ROAS' };
const METRIC_UNITS  = { cpl: '$', cpa: '$', ctr: '%', roas: 'x' };

// ── Add-rule modal ─────────────────────────────────────────────────────────────
function AddRuleModal({ adsets, onClose, onCreated }) {
  const { showSuccess, showError } = useToast();
  const [form, setForm] = useState({
    adset_id: adsets[0]?.id || '',
    metric: 'cpl',
    operator: 'greater_than',
    threshold: 50,
    min_spend: 20,
  });
  const [saving, setSaving] = useState(false);

  const save = async () => {
    setSaving(true);
    try {
      const res = await authFetch(`${API_BASE}/auto-pause/rules`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form),
      });
      if (!res.ok) { const e = await res.json(); throw new Error(e.detail || 'Failed'); }
      showSuccess('Auto-pause rule created');
      onCreated();
      onClose();
    } catch (e) { showError(e.message); }
    finally { setSaving(false); }
  };

  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50">
      <div className="bg-white rounded-2xl shadow-xl p-6 w-full max-w-md">
        <h2 className="text-lg font-bold text-gray-900 mb-4 flex items-center gap-2">
          <PauseCircle size={20} className="text-red-500" /> New Auto-Pause Rule
        </h2>

        <div className="space-y-4">
          <Field label="Ad Set">
            <select className="input-base" value={form.adset_id} onChange={e => setForm({...form, adset_id: e.target.value})}>
              {adsets.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
            </select>
          </Field>

          <Field label="Metric">
            <select className="input-base" value={form.metric} onChange={e => setForm({...form, metric: e.target.value})}>
              <option value="cpl">Cost Per Lead (CPL)</option>
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
              Pause when {METRIC_LABELS[form.metric]} {form.operator === 'greater_than' ? '>' : '<'} {form.metric === 'roas' ? '' : METRIC_UNITS[form.metric]}{form.threshold}{form.metric === 'roas' ? 'x' : ''}
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
        </div>

        <div className="flex gap-3 mt-6">
          <button onClick={onClose} className="flex-1 btn-secondary">Cancel</button>
          <button onClick={save} disabled={saving} className="flex-1 btn-primary">
            {saving ? 'Saving...' : 'Create Rule'}
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
      if (result.paused.length > 0) {
        showSuccess(`Paused ${result.paused.length} ad set(s)!`);
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
            Auto-Pause Rules
          </h1>
          <p className="text-gray-500 text-sm mt-1">
            Rules are checked automatically every 30 minutes against live Meta data.
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
      {lastCheckResult && (
        <div className={`rounded-xl p-4 border ${
          lastCheckResult.paused.length > 0
            ? 'bg-red-50 border-red-200'
            : 'bg-green-50 border-green-200'
        }`}>
          {lastCheckResult.paused.length > 0 ? (
            <>
              <h3 className="font-semibold text-red-800 flex items-center gap-2 mb-2">
                <PauseCircle size={16} /> Auto-paused {lastCheckResult.paused.length} ad set(s)
              </h3>
              {lastCheckResult.paused.map((p, i) => (
                <div key={i} className="text-sm text-red-700">
                  <strong>{p.adset}</strong> — {p.reason}
                </div>
              ))}
            </>
          ) : (
            <div className="flex items-center gap-2 text-green-800 text-sm font-medium">
              <CheckCircle size={16} /> All clear — {lastCheckResult.rules_evaluated} rule{lastCheckResult.rules_evaluated !== 1 ? 's' : ''} evaluated, none triggered.
            </div>
          )}
        </div>
      )}

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
              Rules automatically pause ad sets when performance drops below your thresholds — checked every 30 minutes.
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
            {rules.map(rule => (
              <div
                key={rule.id}
                className={`px-6 py-4 flex items-center justify-between gap-4 ${!rule.is_active ? 'opacity-50' : ''}`}
              >
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-medium text-gray-900 text-sm truncate">{rule.adset_name || rule.adset_id}</span>
                    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                      rule.triggered_at
                        ? 'bg-red-100 text-red-700'
                        : rule.is_active
                          ? 'bg-green-100 text-green-700'
                          : 'bg-gray-100 text-gray-500'
                    }`}>
                      {rule.triggered_at ? 'Triggered' : rule.is_active ? 'Active' : 'Disabled'}
                    </span>
                  </div>

                  <p className="text-xs text-gray-500 mt-1">
                    Pause if {METRIC_LABELS[rule.metric]} {rule.operator === 'greater_than' ? '>' : '<'} {METRIC_UNITS[rule.metric]}{rule.threshold}
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
            ))}
          </div>
        )}
      </div>

      {/* How it works */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6">
        <h3 className="font-semibold text-gray-800 text-sm mb-3 flex items-center gap-2">
          <Zap size={14} className="text-amber-500" /> How Auto-Pause Works
        </h3>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 text-xs text-gray-500">
          <div className="flex flex-col gap-1">
            <span className="font-semibold text-gray-700">1. Set a threshold</span>
            <span>Define a metric (CPL, CTR, ROAS) and the value at which an ad set should be paused.</span>
          </div>
          <div className="flex flex-col gap-1">
            <span className="font-semibold text-gray-700">2. Set a minimum spend</span>
            <span>Prevent false positives — the rule only fires after enough data has accumulated.</span>
          </div>
          <div className="flex flex-col gap-1">
            <span className="font-semibold text-gray-700">3. Runs automatically</span>
            <span>The system checks every 30 minutes. You can also trigger a manual check at any time.</span>
          </div>
        </div>
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
