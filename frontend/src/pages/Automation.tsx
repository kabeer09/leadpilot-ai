import { useState, useEffect, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { Activity, Send, ShieldAlert, RefreshCw, Loader2, GitMerge, EyeOff } from 'lucide-react'
import {
  getAutomationHealth, getEmailFollowupsDue, bulkFollowUp,
  newBatchPreview, newBatchRun, getSuppressions, addSuppression,
  getDQDuplicates, dqMergePreview, dqMergeApply, getMerges,
  exclusionsPreview, exclusionsApply,
} from '../services/api'

export default function Automation() {
  const [health, setHealth] = useState<Record<string, unknown> | null>(null)
  const [due, setDue] = useState<{ lead_id: number; company_name: string | null; to_email: string | null; email_sent_at: string | null }[]>([])
  const [busy, setBusy] = useState<string | null>(null)
  const [msg, setMsg] = useState('')
  const [batch, setBatch] = useState<{ count: number; rows: { lead_id: number; company: string | null; to_email: string | null; relevance_score: number; subject: string; body: string }[] } | null>(null)
  const [batchLimit, setBatchLimit] = useState(20)
  const [suppress, setSuppress] = useState<{ id: number; value: string; value_type: string; reason: string }[]>([])
  const [supValue, setSupValue] = useState('')
  const [dups, setDups] = useState<{ id: number; match_type: string; confidence: number; company_a: { id: number; name: string } | null; company_b: { id: number; name: string } | null }[]>([])
  const [mergeReport, setMergeReport] = useState<Record<string, unknown> | null>(null)
  const [merges, setMerges] = useState<Record<string, unknown>[]>([])
  const [excl, setExcl] = useState<{ would_exclude: number; sample: { id: number; name: string }[] } | null>(null)

  const load = useCallback(async () => {
    try { setHealth(await getAutomationHealth() as Record<string, unknown>) } catch {}
    try { setDue(await getEmailFollowupsDue()) } catch {}
    try { setSuppress(await getSuppressions()) } catch {}
    try { setDups(await getDQDuplicates() as typeof dups) } catch {}
    try { setMerges(await getMerges()) } catch {}
  }, [])

  useEffect(() => { load() }, [load])

  const run = async (key: string, fn: () => Promise<unknown>, done: (r: unknown) => void) => {
    setBusy(key); setMsg('')
    try { done(await fn()); await load() } catch (e: unknown) {
      setMsg((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Action failed')
    } finally { setBusy(null) }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Automation</h1>
        <p className="mt-1 text-sm text-gray-500">Health, follow-ups, new batches, data quality — all from live records. Nothing sends without your approval except the scheduler toggles in Settings.</p>
      </div>

      {/* Health */}
      <div className="card">
        <div className="flex items-center gap-2">
          <Activity className="h-5 w-5 text-primary-600" />
          <h2 className="text-lg font-semibold text-gray-900">Automation health</h2>
          <button onClick={() => load()} className="btn-secondary ml-auto text-xs"><RefreshCw className="mr-1 h-3 w-3" /> Refresh</button>
        </div>
        {!health ? <p className="mt-2 text-sm text-gray-400">Loading…</p> : (
          <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
            {[
              { l: 'Last email sent', v: (health.last_email_sent_at as string) ? new Date(health.last_email_sent_at as string).toLocaleString() : '—' },
              { l: 'Last reply', v: (health.last_reply_at as string) ? new Date(health.last_reply_at as string).toLocaleString() : '—' },
              { l: 'Last crawl', v: (health.last_crawl_at as string) ? new Date(health.last_crawl_at as string).toLocaleString() : '—' },
              { l: 'Gmail accounts', v: String(health.gmail_accounts_connected ?? 0) },
              { l: 'Pending email', v: String(health.pending_email ?? 0) },
              { l: 'Pending WhatsApp', v: String(health.pending_whatsapp ?? 0) },
              { l: 'Running crawls', v: String(health.running_crawls ?? 0) },
              { l: 'Follow-ups due', v: String(due.length) },
            ].map((s) => (
              <div key={s.l} className="rounded-lg border border-gray-200 p-3">
                <p className="text-sm font-bold text-gray-900">{s.v}</p>
                <p className="text-xs text-gray-500">{s.l}</p>
              </div>
            ))}
          </div>
        )}
        {((health?.latest_errors as unknown[]) || []).length > 0 && (
          <div className="mt-3 rounded-lg bg-red-50 p-3 text-xs text-red-700">
            <p className="font-medium">Latest errors</p>
            {((health?.latest_errors as { outreach_id: number; error: string }[]) || []).map((e) => (
              <p key={e.outreach_id}>#{e.outreach_id}: {e.error}</p>
            ))}
          </div>
        )}
      </div>

      {/* Follow-ups */}
      <div className="card">
        <div className="flex items-center gap-2">
          <Send className="h-5 w-5 text-primary-600" />
          <h2 className="text-lg font-semibold text-gray-900">24h email follow-ups ({due.length} due)</h2>
          <button
            onClick={() => run('fu', () => bulkFollowUp({ limit: 50, dry_run: false }), (r) => setMsg(`Follow-ups: ${JSON.stringify(r)}`))}
            disabled={busy === 'fu' || due.length === 0}
            className="btn-primary ml-auto text-sm"
          >
            {busy === 'fu' ? <Loader2 className="h-4 w-4 animate-spin" /> : `Send all due`} 
          </button>
        </div>
        <div className="mt-2 max-h-48 space-y-1 overflow-y-auto">
          {due.slice(0, 15).map((d) => (
            <p key={d.lead_id} className="text-xs text-gray-600">
              <Link to={`/leads/${d.lead_id}`} className="text-primary-600">#{d.lead_id}</Link> {d.company_name} &lt;{d.to_email}&gt;
            </p>
          ))}
          {due.length === 0 && <p className="text-sm text-gray-400">Nothing due — replies and suppressions stop follow-ups automatically.</p>}
        </div>
      </div>

      {/* New batch (approved sends only) */}
      <div className="card">
        <h2 className="text-lg font-semibold text-gray-900">New batch (never-contacted only)</h2>
        <p className="mt-1 text-xs text-gray-500">Preview first. Run sends via Gmail with per-lead locking — retries never double-send. Previously contacted addresses are excluded automatically.</p>
        <div className="mt-3 flex items-end gap-2">
          <div>
            <label className="block text-sm font-medium text-gray-700">Max recipients</label>
            <input type="number" min={1} max={50} value={batchLimit} onChange={(e) => setBatchLimit(parseInt(e.target.value) || 20)} className="input mt-1 w-28" />
          </div>
          <button onClick={() => run('pv', () => newBatchPreview({ limit: batchLimit }), (r) => setBatch(r as typeof batch))} disabled={busy === 'pv'} className="btn-secondary text-sm">
            {busy === 'pv' ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Preview'}
          </button>
          <button
            onClick={() => { if (window.confirm(`Send to ${batch?.count ?? batchLimit} new leads via Gmail?`)) run('run', () => newBatchRun({ limit: batchLimit }), (r) => { setMsg(`Batch: ${JSON.stringify(r)}`); setBatch(null) }) }}
            disabled={busy === 'run' || !batch || batch.count === 0}
            className="btn-primary text-sm"
          >
            {busy === 'run' ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Approve & send'}
          </button>
        </div>
        {batch && (
          <div className="mt-3 rounded-lg border border-gray-200 p-3">
            <p className="text-sm font-medium">{batch.count} recipients (showing {Math.min(10, batch.count)})</p>
            <div className="mt-2 max-h-48 space-y-1 overflow-y-auto">
              {batch.rows.slice(0, 10).map((r) => (
                <p key={r.lead_id} className="text-xs text-gray-600">#{r.lead_id} {r.company} &lt;{r.to_email}&gt; (score {r.relevance_score}) — {r.subject}</p>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Suppressions */}
      <div className="card">
        <div className="flex items-center gap-2">
          <ShieldAlert className="h-5 w-5 text-primary-600" />
          <h2 className="text-lg font-semibold text-gray-900">Suppression list ({suppress.length})</h2>
        </div>
        <div className="mt-3 flex items-end gap-2">
          <div className="flex-1">
            <label className="block text-sm font-medium text-gray-700">Suppress an address</label>
            <input value={supValue} onChange={(e) => setSupValue(e.target.value)} placeholder="name@company.com" className="input mt-1" />
          </div>
          <button onClick={() => run('sup', () => addSuppression({ value: supValue }), () => setSupValue(''))} disabled={busy === 'sup' || !supValue} className="btn-secondary text-sm">Suppress</button>
        </div>
        <div className="mt-2 max-h-40 space-y-1 overflow-y-auto">
          {suppress.slice(0, 20).map((s) => (
            <p key={s.id} className="text-xs text-gray-600">{s.value} <span className="text-gray-400">({s.value_type} · {s.reason})</span></p>
          ))}
        </div>
      </div>

      {/* Duplicates + merges */}
      <div className="card">
        <div className="flex items-center gap-2">
          <GitMerge className="h-5 w-5 text-primary-600" />
          <h2 className="text-lg font-semibold text-gray-900">Duplicates ({dups.length} pending · {merges.length} merged)</h2>
          <Link to="/companies" className="ml-auto text-sm text-primary-600">Review in Companies</Link>
        </div>
        <div className="mt-2 max-h-48 space-y-2 overflow-y-auto">
          {dups.slice(0, 10).map((d) => (
            <div key={d.id} className="flex flex-wrap items-center gap-2 rounded-lg border border-gray-100 p-2 text-xs">
              <span className="font-medium">{d.company_a?.name}</span>
              <span className="text-gray-400">↔ {d.company_b?.name} ({d.match_type}, {Math.round((d.confidence || 0) * 100)}%)</span>
              <button
                onClick={() => run(`mp${d.id}`, () => dqMergePreview(d.company_a!.id, d.company_b!.id), (r) => setMergeReport({ ...(r as object), a: d.company_a, b: d.company_b }))}
                className="btn-secondary ml-auto text-xs"
              >
                Dry-run merge
              </button>
            </div>
          ))}
          {dups.length === 0 && <p className="text-sm text-gray-400">No pending duplicates.</p>}
        </div>
        {mergeReport && (
          <div className="mt-3 rounded-lg border border-yellow-200 bg-yellow-50 p-3 text-xs">
            <p className="font-medium">Merge dry-run: {(mergeReport.b as { name: string })?.name} → {(mergeReport.a as { name: string })?.name}</p>
            <p className="mt-1 text-gray-700">
              Leads repointed: {String(mergeReport.leads_repointed)} · Outreach preserved: {String(mergeReport.outreach_preserved)} ·
              Contacts: {String(mergeReport.contacts_repointed)} · Fields filled: {JSON.stringify(mergeReport.fields_would_fill)}
            </p>
            <button
              onClick={() => { if (window.confirm('Merge these companies? History is preserved, the duplicate stays flagged MERGED.')) run('ma', () => dqMergeApply((mergeReport.a as { id: number }).id, (mergeReport.b as { id: number }).id), (r) => { setMsg(`Merged: ${JSON.stringify(r)}`); setMergeReport(null) }) }}
              disabled={busy === 'ma'}
              className="btn-primary mt-2 text-xs"
            >
              {busy === 'ma' ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Apply merge'}
            </button>
          </div>
        )}
      </div>

      {/* Exclusions */}
      <div className="card">
        <div className="flex items-center gap-2">
          <EyeOff className="h-5 w-5 text-primary-600" />
          <h2 className="text-lg font-semibold text-gray-900">No-contact exclusions</h2>
          <button onClick={() => run('ep', () => exclusionsPreview(), (r) => setExcl(r as typeof excl))} disabled={busy === 'ep'} className="btn-secondary ml-auto text-sm">
            {busy === 'ep' ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Dry-run report'}
          </button>
        </div>
        {excl && (
          <div className="mt-2 text-xs text-gray-600">
            <p>{excl.would_exclude} companies have no usable contact anywhere. Sample: {excl.sample.slice(0, 5).map((s) => s.name).join(' · ')}</p>
            <button
              onClick={() => { if (window.confirm(`Exclude ${excl.would_exclude} companies from prospecting? They stay in the DB and can be restored.`)) run('ea', () => exclusionsApply(), (r) => { setMsg(`Excluded: ${JSON.stringify(r)}`); setExcl(null) }) }}
              disabled={busy === 'ea'}
              className="btn-secondary mt-2 text-xs"
            >
              {busy === 'ea' ? <Loader2 className="h-4 w-4 animate-spin" /> : `Apply exclusion (${excl.would_exclude})`}
            </button>
          </div>
        )}
      </div>

      {msg && <div className="rounded-lg bg-blue-50 p-3 text-sm text-blue-800">{msg}</div>}
    </div>
  )
}
