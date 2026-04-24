import React, { useState, useEffect, useCallback } from 'react';
import { PauseCircle, PlayCircle, Trash2, Plus, RefreshCw, AlertTriangle, CheckCircle, TrendingDown, DollarSign, Target, Zap } from 'lucide-react';
import { useToast } from '../context/ToastContext';
import { authFetch } from '../lib/facebookApi';

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1';

const METRIC_LABELS = { cpl: 'Cost Per Lead', cpa: 'Cost Per Action', ctr: 'CTR' };
const METRIC_UNITS  = { cpl: '$', cpa: '$', ctr: '%' };
const DATE_PRESETS  = [
  { value: 'today',       label: 'Today' },
  { value: 'yesterday',   label: 'Yesterday' },
  { value: 'last_7d',     label: 'Last 7 Days' },
  { value: 'last_14d',    label: 'Last 14 Days' },
  { value: 'last_30d',    label: 'Last 30 Days' },
];

// ── Inline insights card for one ad set ──────────────────────────────────────
function InsightsCard({ fbAdsetId, adsetName, adAccountId, datePreset }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    if (!fbAdsetId) return;
    setLoading(true); setError(null);
    try {
      const params = new URLSearchParams({ date_preset: datePreset });
      if (adAccountId) params.set('ad_account_id', adAccountId);
      const res = await authFetch(`${API_BASE}/auto-pause/insights/${fbAdsetId}?${params}`);
      if (!res.ok) { const e = await res.json(); throw new Error(e.detail || 'Failed'); }
      setData(await res.json());
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  }, [fbAdsetId, adAccountId, datePreset]);

  useEffect(() => { load(); }, [load]);

  if (!fbAdsetId) return <span className="text-xs text-gray-400 italic">Not launched yet</span>;
  if (loading) return <span className="text-xs text-gray-400 animate-pulse">Loading...</span>;
  if (error) return <span className="text-xs text-red-500">{error}</span>;
  if (!data) return null;

  return (
    <div className="flex flex-wrap gap-4 text-sm">
      <Stat label="Spend"  value={`$${data.spend.toFixed(2)}`} />
      <Stat label="Leads"  value={data.leads} />
      <Stat label="CPL"    value={data.cpl != null ? `$${data.cpl.toFixed(2)}` : '—'} highlight={data.cpl > 60} />
      <Stat label="Clicks" value={data.clicks.toLocaleString()} />
      <Stat label="CTR"    value={`${parseFloat(data.ctr).toFixed(2)}%`} />
    </div>
  );
}

function Stat({ label, value, highlight }) {
  return (
    <div className="flex flex-col">
      <span className="text-xs text-gray-500">{label}</span>
      <span className={`font-semibold ${highlight ? 'text-red-600' : 'text-gray-900'}`}>{value}</span>
    </div>
  );
}

// ── Add-rule modal ────────────────────────────────────────────────────────────
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
              type="number" min="0" className="input-base"
              value={form.threshold}
              onChange={e => setForm({...form, threshold: Number(e.target.value)})}
            />
            <p className="text-xs text-gray-500 mt-1">
              Pause when {METRIC_LABELS[form.metric]} {form.operator === 'greater_than' ? '>' : '<'} {METRIC_UNITS[form.metric]}{form.threshold}
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

// ── Main page ─────────────────────────────────────────────────────────────────
export default function CampaignPerformance() {
  const { showSuccess, showError, showInfo } = useToast();
  const [adsets, setAdsets]     = useState([]);
  const [rules, setRules]       = useState([]);
  const [datePreset, setDatePreset] = useState('last_7d');
  const [adAccountId, setAdAccountId] = useState('');
  const [loadingAdsets, setLoadingAdsets] = useState(false);
  const [checking, setChecking] = useState(false);
  const [showAddRule, setShowAddRule] = useState(false);
  const [lastCheckResult, setLastCheckResult] = useState(null);

  const loadAdsets = useCallback(async () => {
    setLoadingAdsets(true);
    try {
      const res = await authFetch(`${API_BASE}/facebook/adsets/saved`);
      if (!res.ok) throw new Error('Failed to load ad sets');
      const data = await res.json();
      setAdsets(Array.isArray(data) ? data : data.adsets || []);
    } catch (e) { showError(e.message); }
    finally { setLoadingAdsets(false); }
  }, []);

  const loadRules = useCallback(async () => {
    try {
      const res = await authFetch(`${API_BASE}/auto-pause/rules`);
      if (!res.ok) throw new Error('Failed to load rules');
      setRules(await res.json());
    } catch (e) { showError(e.message); }
  }, []);

  // Auto-populate Ad Account ID from the connected Facebook account
  useEffect(() => {
    authFetch(`${API_BASE}/facebook/accounts`)
      .then(res => res.ok ? res.json() : null)
      .then(accounts => {
        if (Array.isArray(accounts) && accounts.length > 0) {
          setAdAccountId(accounts[0].account_id || '');
        }
      })
      .catch(() => {}); // silent fail — field stays editable
  }, []);

  useEffect(() => { loadAdsets(); loadRules(); }, [loadAdsets, loadRules]);

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
      const params = adAccountId ? `?ad_account_id=${adAccountId}` : '';
      const res = await authFetch(`${API_BASE}/auto-pause/check${params}`, { method: 'POST' });
      if (!res.ok) throw new Error('Check failed');
      const result = await res.json();
      setLastCheckResult(result);
      if (result.paused.length > 0) {
        showSuccess(`Paused ${result.paused.length} ad set(s)! Check results below.`);
      } else {
        showSuccess(`Check complete — no rules breached. ${result.rules_evaluated} rules evaluated.`);
      }
      loadAdsets(); loadRules();
    } catch (e) { showError(e.message); }
    finally { setChecking(false); }
  };

  const activeAdsets = adsets.filter(a => a.fb_adset_id);

  return (
    <div className="max-w-6xl mx-auto space-y-8">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-2">
            <TrendingDown size={26} className="text-red-500" />
            Performance &amp; Auto-Pause
          </h1>
          <p className="text-gray-500 text-sm mt-1">
            Live Meta Insights · Rules checked every 30 minutes automatically
          </p>
        </div>
        <div className="flex items-center gap-3">
          <select
            className="border border-gray-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500"
            value={datePreset}
            onChange={e => setDatePreset(e.target.value)}
          >
            {DATE_PRESETS.map(d => <option key={d.value} value={d.value}>{d.label}</option>)}
          </select>
          <div className="relative">
            <input
              type="text"
              placeholder="Ad Account ID"
              className="border border-gray-200 rounded-lg pl-3 pr-8 py-2 text-sm w-48 focus:ring-2 focus:ring-indigo-500 focus:outline-none"
              value={adAccountId}
              onChange={e => setAdAccountId(e.target.value)}
            />
            {adAccountId && (
              <span className="absolute right-2 top-1/2 -translate-y-1/2 w-2 h-2 rounded-full bg-green-400" title="Account connected" />
            )}
          </div>
          <button
            onClick={runCheck}
            disabled={checking}
            className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium text-white transition-colors"
            style={{ backgroundColor: checking ? '#9CA3AF' : '#2D2463' }}
          >
            <RefreshCw size={14} className={checking ? 'animate-spin' : ''} />
            {checking ? 'Checking...' : 'Check Now'}
          </button>
        </div>
      </div>

      {/* Last check results */}
      {lastCheckResult && lastCheckResult.paused.length > 0 && (
        <div className="bg-red-50 border border-red-200 rounded-xl p-4">
          <h3 className="font-semibold text-red-800 flex items-center gap-2 mb-2">
            <PauseCircle size={16} /> Auto-paused {lastCheckResult.paused.length} ad set(s)
          </h3>
          {lastCheckResult.paused.map((p, i) => (
            <div key={i} className="text-sm text-red-700">
              <strong>{p.adset}</strong> — {p.reason}
            </div>
          ))}
        </div>
      )}

      {/* Ad Set Performance Table */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
        <div className="px-6 py-4 border-b border-gray-100 flex items-center justify-between">
          <h2 className="font-semibold text-gray-900 flex items-center gap-2">
            <Target size={16} className="text-gray-400" /> Ad Set Performance
          </h2>
          <button
            onClick={loadAdsets}
            className="text-gray-400 hover:text-gray-600 transition-colors"
            title="Refresh"
          >
            <RefreshCw size={14} />
          </button>
        </div>

        {loadingAdsets ? (
          <div className="p-8 text-center text-gray-400 text-sm">Loading ad sets...</div>
        ) : activeAdsets.length === 0 ? (
          <div className="p-8 text-center text-gray-400 text-sm">
            No launched ad sets found. Create and launch a campaign first.
          </div>
        ) : (
          <div className="divide-y divide-gray-50">
            {activeAdsets.map(adset => (
              <div key={adset.id} className="px-6 py-4">
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center flex-wrap gap-2">
                    <span className="font-medium text-gray-900 text-sm">{adset.name}</span>
                    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                      adset.status === 'ACTIVE'
                        ? 'bg-green-100 text-green-700'
                        : 'bg-gray-100 text-gray-500'
                    }`}>
                      {adset.status}
                    </span>
                    {(() => {
                      const adsetRules = rules.filter(r => r.adset_id === adset.id);
                      const activeRule = adsetRules.find(r => r.is_active && !r.triggered_at);
                      const triggeredRule = adsetRules.find(r => r.triggered_at);
                      if (triggeredRule) return (
                        <span className="text-xs px-2 py-0.5 rounded-full font-medium bg-red-100 text-red-700 flex items-center gap-1">
                          <PauseCircle size={10} /> Rule triggered
                        </span>
                      );
                      if (activeRule) return (
                        <span className="text-xs px-2 py-0.5 rounded-full font-medium bg-indigo-50 text-indigo-600 flex items-center gap-1">
                          <Zap size={10} /> Rule active
                        </span>
                      );
                      return null;
                    })()}
                  </div>
                  <span className="text-xs text-gray-400">{adset.fb_adset_id}</span>
                </div>
                <InsightsCard
                  fbAdsetId={adset.fb_adset_id}
                  adsetName={adset.name}
                  adAccountId={adAccountId}
                  datePreset={datePreset}
                />
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Auto-Pause Rules */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
        <div className="px-6 py-4 border-b border-gray-100 flex items-center justify-between">
          <h2 className="font-semibold text-gray-900 flex items-center gap-2">
            <PauseCircle size={16} className="text-red-500" /> Auto-Pause Rules
          </h2>
          <button
            onClick={() => setShowAddRule(true)}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium text-white"
            style={{ backgroundColor: '#2D2463' }}
          >
            <Plus size={14} /> Add Rule
          </button>
        </div>

        {rules.length === 0 ? (
          <div className="p-8 text-center">
            <PauseCircle size={32} className="text-gray-200 mx-auto mb-2" />
            <p className="text-gray-500 text-sm">No rules yet.</p>
            <p className="text-gray-400 text-xs mt-1">Add a rule to automatically pause ad sets when performance drops.</p>
          </div>
        ) : (
          <div className="divide-y divide-gray-50">
            {rules.map(rule => (
              <div key={rule.id} className={`px-6 py-4 flex items-center justify-between gap-4 ${!rule.is_active ? 'opacity-50' : ''}`}>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-medium text-gray-900 text-sm truncate">{rule.adset_name || rule.adset_id}</span>
                    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                      rule.triggered_at ? 'bg-red-100 text-red-700' : rule.is_active ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'
                    }`}>
                      {rule.triggered_at ? 'Triggered' : rule.is_active ? 'Active' : 'Disabled'}
                    </span>
                  </div>
                  <p className="text-xs text-gray-500 mt-0.5">
                    Pause if {METRIC_LABELS[rule.metric]} {rule.operator === 'greater_than' ? '>' : '<'} {METRIC_UNITS[rule.metric]}{rule.threshold}
                    {' '}after {METRIC_UNITS.cpl}{rule.min_spend} spend
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
