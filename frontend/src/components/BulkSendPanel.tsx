import { useState, useEffect } from 'react'
import { Mail, Send, Eye, RefreshCw, Loader2 } from 'lucide-react'
import { sendBulkEmail, bulkSendStatus, checkReplies, getGoogleStatus } from '../services/api'

interface PreviewItem {
  lead_id: number;
  company_name: string | null;
  to_email: string | null;
  lead_score: number;
  subject: string;
}

export default function BulkSendPanel({ onDone }: { onDone: () => void }) {
  const [open, setOpen] = useState(false)
  const [subject, setSubject] = useState('Partnership inquiry for {company_name}')
  const [message, setMessage] = useState(
    'Dear {company_name} team,\n\nWe manufacture and export metal decor and home products from India. If relevant to your range, we would love to share our catalogue.\n\nWould you be open to a short 1-to-1 Google Meet?\n\nBest regards'
  )
  const [limit, setLimit] = useState(25)
  const [preview, setPreview] = useState<PreviewItem[] | null>(null)
  const [previewCount, setPreviewCount] = useState(0)
  const [job, setJob] = useState<{ state: string; total: number; sent: number; failed: number; skipped: number; errors: string[] } | null>(null)
  const [replies, setReplies] = useState<{ checked: number; matched: number; categories: Record<string, number> } | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [accounts, setAccounts] = useState<{ id: number; email: string; active: boolean }[]>([])
  const [accountId, setAccountId] = useState<number | null>(null)

  useEffect(() => {
    getGoogleStatus().then((g) => {
      setAccounts(g.accounts || [])
      const active = (g.accounts || []).find((a) => a.active)
      setAccountId(active ? active.id : null)
    }).catch(() => {})
  }, [])

  const pollJob = async () => {
    for (let i = 0; i < 60; i++) {
      await new Promise((r) => setTimeout(r, 5000))
      try {
        const s = await bulkSendStatus()
        setJob(s)
        if (s.state !== 'running') {
          onDone()
          break
        }
      } catch {
        break
      }
    }
  }

  const handlePreview = async () => {
    setBusy('preview')
    setError('')
    try {
      const r = await sendBulkEmail({ subject, message, limit, dry_run: true })
      setPreview(r.preview ?? null)
      setPreviewCount(r.count ?? 0)
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Preview failed')
    } finally {
      setBusy(null)
    }
  }

  const handleSend = async () => {
    if (!window.confirm(`Send this email to ~${previewCount || limit} leads via Gmail?`)) return
    setBusy('send')
    setError('')
    try {
      await sendBulkEmail({ subject, message, limit, dry_run: false, account_id: accountId ?? undefined })
      pollJob()
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Bulk send failed — is Gmail connected in Settings?')
    } finally {
      setBusy(null)
    }
  }

  const handleCheckReplies = async () => {
    setBusy('replies')
    setError('')
    try {
      const r = await checkReplies()
      setReplies(r)
      onDone()
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Reply check failed — is Gmail connected?')
    } finally {
      setBusy(null)
    }
  }

  if (!open) {
    return (
      <button onClick={() => setOpen(true)} className="btn-primary">
        <Send className="mr-2 h-4 w-4" /> Send email to all
      </button>
    )
  }

  return (
    <div className="card space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="flex items-center gap-2 text-lg font-semibold text-gray-900">
          <Mail className="h-5 w-5 text-primary-600" /> Send email to all leads
        </h2>
        <button onClick={() => setOpen(false)} className="btn-secondary text-sm">Close</button>
      </div>
      <p className="text-sm text-gray-500">
        Custom subject + body with placeholders: <code>{'{company_name}'}</code> <code>{'{country}'}</code> <code>{'{city}'}</code> <code>{'{website}'}</code> <code>{'{contact_email}'}</code>.
        Sends top-scoring eligible leads first via your connected Gmail. Replies are auto-classified on check.
      </p>
      <div className="grid grid-cols-1 gap-4">
        <div>
          <label className="block text-sm font-medium text-gray-700">Subject</label>
          <input value={subject} onChange={(e) => setSubject(e.target.value)} className="input mt-1" />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700">Body</label>
          <textarea value={message} onChange={(e) => setMessage(e.target.value)} rows={6} className="input mt-1" />
        </div>
        <div className="flex items-end gap-3">
          <div>
            <label className="block text-sm font-medium text-gray-700">Max leads</label>
            <input type="number" min={1} max={500} value={limit} onChange={(e) => setLimit(parseInt(e.target.value) || 25)} className="input mt-1 w-32" />
          </div>
          {accounts.length > 1 && (
            <div>
              <label className="block text-sm font-medium text-gray-700">Send from</label>
              <select value={accountId ?? ''} onChange={(e) => setAccountId(parseInt(e.target.value))} className="input mt-1">
                {accounts.map((a) => (
                  <option key={a.id} value={a.id}>{a.email}{a.active ? ' (default)' : ''}</option>
                ))}
              </select>
            </div>
          )}
          <button onClick={handlePreview} disabled={busy === 'preview'} className="btn-secondary text-sm">
            {busy === 'preview' ? <Loader2 className="h-4 w-4 animate-spin" /> : <Eye className="mr-1 h-4 w-4" />} Preview
          </button>
          <button onClick={handleSend} disabled={busy === 'send'} className="btn-primary text-sm">
            {busy === 'send' ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="mr-1 h-4 w-4" />} Send via Gmail
          </button>
          <button onClick={handleCheckReplies} disabled={busy === 'replies'} className="btn-secondary text-sm" title="Poll Gmail for replies and auto-classify them">
            {busy === 'replies' ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="mr-1 h-4 w-4" />} Check replies
          </button>
        </div>
      </div>
      {error && <div className="rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</div>}
      {preview && (
        <div className="rounded-lg border border-gray-200 p-3">
          <p className="text-sm font-medium text-gray-900">Preview: {previewCount} leads would receive this</p>
          <div className="mt-2 max-h-48 space-y-1 overflow-y-auto">
            {preview.slice(0, 10).map((p) => (
              <p key={p.lead_id} className="text-xs text-gray-600">
                #{p.lead_id} {p.company_name} &lt;{p.to_email}&gt; (score {p.lead_score})
              </p>
            ))}
          </div>
        </div>
      )}
      {job && (
        <div className="rounded-lg bg-blue-50 p-3 text-sm text-blue-800">
          Bulk job: <strong>{job.state}</strong> — {job.sent}/{job.total} sent, {job.failed} failed, {job.skipped} skipped
          {job.errors.length > 0 && <p className="mt-1 text-xs">{job.errors[0]}</p>}
        </div>
      )}
      {replies && (
        <div className="rounded-lg bg-green-50 p-3 text-sm text-green-800">
          Checked {replies.checked} Gmail messages, matched {replies.matched} replies
          {Object.keys(replies.categories).length > 0 && `: ${Object.entries(replies.categories).map(([k, v]) => `${k}×${v}`).join(', ')}`}
        </div>
      )}
    </div>
  )
}
