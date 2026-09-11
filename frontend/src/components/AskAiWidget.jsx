import React, { useState } from 'react';
import { MessageSquare, RefreshCw, Send, Sparkles, X } from 'lucide-react';
import { authFetch } from '../lib/facebookApi';
import { useToast } from '../context/ToastContext';
import { useCampaign } from '../context/CampaignContext';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1';

const DATE_PRESETS = [
  { value: 'yesterday', label: 'Yesterday' },
  { value: 'last_3d', label: 'Last 3 Days' },
  { value: 'last_7d', label: 'Last 7 Days' },
  { value: 'last_30d', label: 'Last 30 Days' },
  { value: 'this_month', label: 'MTD' },
];

const EXAMPLES = [
  'What are my worst ad sets today?',
  'Which creatives have the highest CPL?',
  'Show me frequency issues across all campaigns',
  'Any pixel or tracking problems I should know about?',
];

function renderInline(text) {
  return text.split(/(\*\*[^*]+\*\*)/g).map((part, index) => {
    const bold = part.match(/^\*\*(.+)\*\*$/);
    return bold
      ? <strong key={index} className="font-semibold text-gray-900">{bold[1]}</strong>
      : part;
  });
}

function MarkdownAnswer({ text }) {
  if (!text) return null;
  return (
    <div className="space-y-1">
      {text.split('\n').map((line, index) => (
        line.trim()
          ? <p key={index} className="text-sm leading-relaxed">{renderInline(line)}</p>
          : <div key={index} className="h-1" />
      ))}
    </div>
  );
}

export default function AskAiWidget() {
  const { activeAccountId } = useCampaign();
  const { showError } = useToast();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [answer, setAnswer] = useState('');
  const [loading, setLoading] = useState(false);
  const [datePreset, setDatePreset] = useState('last_7d');
  const [showExamples, setShowExamples] = useState(false);

  const askAI = async () => {
    if (!query.trim() || loading) return;
    setLoading(true);
    setAnswer('');
    try {
      const response = await authFetch(`${API_URL}/ai-insights/query`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query: query.trim(),
          ad_account_id: activeAccountId || undefined,
          date_preset: datePreset,
        }),
      });
      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(error.detail || 'Query failed');
      }
      const data = await response.json();
      setAnswer(data.answer || 'No answer returned.');
    } catch (error) {
      showError(error.message || 'AI query failed — try again');
    } finally {
      setLoading(false);
    }
  };

  const clear = () => {
    setAnswer('');
    setQuery('');
  };

  return (
    <div className="fixed bottom-6 right-6 z-50 flex flex-col items-end gap-3">
      {open && (
        <div className="w-[min(28rem,calc(100vw-2rem))] overflow-hidden rounded-xl border border-gray-200 bg-white shadow-xl">
          <div className="flex items-center justify-between border-b border-gray-100 px-4 py-3">
            <div className="flex items-center gap-2">
              <Sparkles size={15} className="text-violet-500" />
              <span className="text-sm font-semibold text-gray-900">Ask AI</span>
              <span className="hidden text-xs font-normal text-gray-400 sm:inline">powered by Claude + live Meta data</span>
            </div>
            <button type="button" onClick={() => setOpen(false)} className="rounded-md p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600" title="Close Ask AI" aria-label="Close Ask AI">
              <X size={16} />
            </button>
          </div>
          <div className="p-4">
            <div className="mb-2 flex flex-wrap gap-2">
              {DATE_PRESETS.map(preset => (
                <button key={preset.value} type="button" onClick={() => setDatePreset(preset.value)} className={`rounded-full border px-2.5 py-1 text-xs transition-colors ${datePreset === preset.value ? 'border-violet-400 bg-violet-50 font-medium text-violet-700' : 'border-gray-200 text-gray-500 hover:border-violet-300 hover:text-violet-600'}`}>
                  {preset.label}
                </button>
              ))}
            </div>
            <div className="flex gap-2">
              <input type="text" value={query} onChange={event => setQuery(event.target.value)} onKeyDown={event => event.key === 'Enter' && askAI()} placeholder="e.g. What are my worst performing ad sets this week?" className="min-w-0 flex-1 rounded-lg border border-gray-200 px-3 py-2 text-sm focus:border-transparent focus:outline-none focus:ring-2 focus:ring-violet-400" disabled={loading} />
              <button type="button" onClick={askAI} disabled={loading || !query.trim()} className="flex shrink-0 items-center gap-1.5 rounded-lg bg-violet-600 px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-violet-700 disabled:cursor-not-allowed disabled:opacity-50">
                {loading ? <><RefreshCw size={13} className="animate-spin" /> Thinking...</> : <><Send size={13} /> Ask</>}
              </button>
            </div>
            {!answer && !loading && (
              <div className="mt-2">
                <button type="button" onClick={() => setShowExamples(value => !value)} className="flex items-center gap-1 text-xs text-gray-400 transition-colors hover:text-violet-600">
                  Examples {showExamples ? '▴' : '▾'}
                </button>
                {showExamples && <div className="mt-2 flex flex-wrap gap-2">{EXAMPLES.map(example => <button key={example} type="button" onClick={() => { setQuery(example); setShowExamples(false); }} className="rounded-full border border-gray-200 px-2.5 py-1 text-left text-xs text-gray-500 transition-colors hover:border-violet-300 hover:text-violet-600">{example}</button>)}</div>}
              </div>
            )}
            {answer && (
              <div className="mt-3 max-h-[min(24rem,50vh)] overflow-y-auto rounded-lg border border-gray-100 bg-gray-50 p-4">
                <div className="flex items-start gap-2"><MessageSquare size={14} className="mt-0.5 shrink-0 text-violet-400" /><MarkdownAnswer text={answer} /></div>
                <button type="button" onClick={clear} className="mt-2 text-xs text-gray-400 transition-colors hover:text-gray-600">Clear</button>
              </div>
            )}
          </div>
        </div>
      )}
      <button type="button" onClick={() => setOpen(value => !value)} className="flex h-14 w-14 items-center justify-center rounded-full bg-violet-600 text-white shadow-lg transition-colors hover:bg-violet-700 focus:outline-none focus:ring-2 focus:ring-violet-400 focus:ring-offset-2" title={open ? 'Close Ask AI' : 'Ask AI about campaign performance'} aria-label={open ? 'Close Ask AI' : 'Ask AI about campaign performance'}>
        {open ? <X size={22} /> : <Sparkles size={22} />}
      </button>
    </div>
  );
}
