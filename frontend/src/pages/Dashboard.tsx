import { useState, useEffect, useCallback } from 'react'
import { Link } from 'react-router-dom'
import {
  Building2,
  Users,
  Mail,
  MessageSquare,
  Calendar,
  TrendingUp,
  Search,
  Play,
  Loader2,
  CheckCircle,
  AlertCircle,
} from 'lucide-react'
import { createSource, triggerCrawl, getCrawlStatus, getAnalytics, getCompanies, getPipeline, getEmailMatch, getSources, getOutreachSummary, getSentEmails, checkReplies } from '../services/api'
import type { AnalyticsOverview, Company } from '../types'

const EXAMPLE_URLS = [
  { label: 'One Giant Leap', url: 'https://onegiantleap.com/exhibit/our-2026-exhibitors' },
  { label: 'Trade Fair Dates', url: 'https://www.tradefairdates.com/' },
  { label: 'Autumn Fair', url: 'https://www.autumnfair.com/' },
]

export default function Dashboard() {
  const [url, setUrl] = useState('')
  const [sourceName, setSourceName] = useState('')
  const [loading, setLoading] = useState(false)
  const [crawling, setCrawling] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [analytics, setAnalytics] = useState<AnalyticsOverview | null>(null)
  const [companies, setCompanies] = useState<Company[]>([])
  const [crawlProgress, setCrawlProgress] = useState('')
  const [resultSearch, setResultSearch] = useState('')
  const [resultCountry, setResultCountry] = useState('')
  const [resultPage, setResultPage] = useState(0)
  const [resultTotal, setResultTotal] = useState(0)
  const [matchStats, setMatchStats] = useState<{ match_rate: number; matched: number; mismatched: number } | null>(null)
  const [stillRunning, setStillRunning] = useState<{ id: number; name: string } | null>(null)
  const [pipeline, setPipeline] = useState<{ step: number; label: string; count: number; detail?: Record<string, number> }[]>([])
  const [contactOnly, setContactOnly] = useState(true)
  const [outreach, setOutreach] = useState<{ total_companies: number; total_leads: number; eligible_leads: number; emails_sent_total: number; emails_sent_today: number; replies_today: number; interested: number; bounced: number; followups_due: number; followups_sent: number; unsubscribed: number; meetings_booked: number } | null>(null)
  const [sentEmails, setSentEmails] = useState<{ outreach_id: number; lead_id: number; company: string | null; to_email: string | null; campaign_id: number | null; subject: string | null; sent_at: string | null; reply_at: string | null; thread_id: string | null; thread_url: string | null; status: string; follow_up_count: number; next_action: string }[]>([])
  const [syncMsg, setSyncMsg] = useState('')
  const [syncing, setSyncing] = useState(false)

  const loadAnalytics = useCallback(async () => {
    try {
      const stats = await getAnalytics()
      setAnalytics(stats)
    } catch (err) {
      console.error('Failed to load analytics:', err)
    }
  }, [])

  const loadOutreach = useCallback(async () => {
    try {
      const s = await getOutreachSummary()
      setOutreach(s)
    } catch {
      // outreach summary unavailable — analytics still shows core stats
    }
    try {
      const rows = await getSentEmails(50)
      setSentEmails(rows)
    } catch {
      // no sent emails yet
    }
  }, [])

  const handleSync = async () => {
    setSyncing(true)
    setSyncMsg('')
    try {
      const r = await checkReplies()
      setSyncMsg(`Gmail sync: ${r.checked} messages checked, ${r.matched} replies matched`)
      await loadOutreach()
      await loadAnalytics()
    } catch {
      setSyncMsg('Sync failed — is Gmail connected in Settings?')
    } finally {
      setSyncing(false)
    }
  }

  const PAGE_SIZE = 20
  const PREVIEW_POOL = 100

  const hasContact = (c: Company) =>
    (c.contacts || []).some((ct) => ct.business_email || ct.phone)

  const loadCompanies = useCallback(async (opts?: { search?: string; country?: string; page?: number; contacts?: boolean }) => {
    try {
      const onlyContacted = opts?.contacts ?? contactOnly
      // Newest rows often have no contacts yet (enrichment lags) — sample a
      // wider pool and surface contacted companies first.
      const params: Record<string, string> = { limit: String(onlyContacted ? PREVIEW_POOL : PAGE_SIZE) }
      const q = opts?.search ?? resultSearch
      const c = opts?.country ?? resultCountry
      const p = opts?.page ?? resultPage
      if (q) params.search = q
      if (c) params.country = c
      if (!onlyContacted && p > 0) params.skip = String(p * PAGE_SIZE)
      const data = await getCompanies(params)
      let items = data.items
      if (onlyContacted) {
        items = items.filter(hasContact)
      }
      setCompanies(items)
      setResultTotal(onlyContacted ? items.length : data.total)
    } catch (err) {
      console.error('Failed to load companies:', err)
    }
  }, [resultSearch, resultCountry, resultPage, contactOnly])

  useEffect(() => {
    loadAnalytics()
    loadOutreach()
    getPipeline().then((p) => setPipeline(p.stages)).catch(() => {})
    getEmailMatch().then((m) => setMatchStats({ match_rate: m.match_rate, matched: m.matched, mismatched: m.mismatched })).catch(() => {})
    // Fresh Gmail login lands back here (?google=connected): sync immediately
    // so replies + dashboard reflect the newly connected account.
    const params = new URLSearchParams(window.location.search)
    if (params.get('google') === 'connected') {
      handleSync()
    }
  }, [loadAnalytics, loadOutreach])

  useEffect(() => {
    loadCompanies()
  }, [loadCompanies])

  // Live updates: while any crawl runs, refresh stats + table every 20s
  // so freshly saved companies appear without manual reloads.
  useEffect(() => {
    const t = setInterval(async () => {
      try {
        const list = await getSources()
        const running = list.some((s) => s.status === 'CRAWLING')
        if (running) {
          await loadAnalytics()
          await loadCompanies()
          getPipeline().then((p) => setPipeline(p.stages)).catch(() => {})
        }
      } catch {
        // ignore polling errors
      }
    }, 20000)
    return () => clearInterval(t)
  }, [loadAnalytics, loadCompanies])

  const handleStart = async () => {
    if (!url) return
    setLoading(true)
    setMessage('')
    setError('')
    setCrawlProgress('')

    try {
      // Step 1: Create source
      setCrawlProgress('Creating source...')
      const source = await createSource({ name: sourceName || 'New Source', url })

      // Step 2: Trigger crawl
      setCrawling(true)
      setCrawlProgress('Crawl started! Discovering pages...')
      await triggerCrawl(source.id)

      // Step 3: Poll for completion (large directories take minutes)
      let attempts = 0
      const maxAttempts = 120 // 5s x 120 = 10 minutes max
      let completed = false
      let failed = false
      while (attempts < maxAttempts) {
        await new Promise((r) => setTimeout(r, 5000))
        attempts++

        try {
          const status = await getCrawlStatus(source.id)
          if (status.status === 'COMPLETED') {
            completed = true
            setCrawlProgress('Crawl complete! Loading data...')
            break
          } else if (status.status === 'FAILED') {
            failed = true
            break
          } else {
            const mins = Math.floor((attempts * 5) / 60)
            const secs = (attempts * 5) % 60
            setCrawlProgress(`Crawling directory… (${mins}m ${secs}s elapsed — large fairs take several minutes)`)
          }
        } catch {
          // Ignore polling errors
        }
      }

      if (failed) {
        setError('Crawl failed. The site may be blocking automated access.')
        setLoading(false)
        setCrawling(false)
        setCrawlProgress('')
        return
      }
      if (!completed) {
        // Still running server-side: NEVER claim completion. Data appears on refresh.
        setCrawlProgress('')
        setMessage('')
        setError('')
        setCrawling(false)
        setLoading(false)
        setStillRunning({ id: source.id, name: source.name })
        await loadAnalytics()
        await loadCompanies()
        return
      }

      // Step 4: Load results
      await loadAnalytics()
      await loadCompanies()
      setMessage(`Crawl complete! See results below.`)
      setUrl('')
      setSourceName('')
    } catch (err) {
      setError('Failed to start crawl. Check the URL and try again.')
    } finally {
      setLoading(false)
      setCrawling(false)
      setCrawlProgress('')
    }
  }

  const stats = [
    { label: 'Companies', value: analytics?.total_companies ?? 0, icon: Building2, color: 'bg-blue-500' },
    { label: 'Leads', value: analytics?.total_leads ?? 0, icon: Users, color: 'bg-green-500' },
    { label: 'Emails Sent', value: analytics?.emails_sent ?? 0, icon: Mail, color: 'bg-purple-500' },
    { label: 'Replies', value: analytics?.replies ?? 0, icon: MessageSquare, color: 'bg-orange-500' },
    { label: 'Meetings', value: analytics?.meetings_booked ?? 0, icon: Calendar, color: 'bg-pink-500' },
    { label: 'Qualified', value: analytics?.qualified ?? 0, icon: TrendingUp, color: 'bg-teal-500' },
  ]

  return (
    <div className="space-y-8">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Dashboard</h1>
        <p className="mt-1 text-sm text-gray-500">
          Generate qualified B2B opportunities from public exhibitor sources.
        </p>
      </div>

      {/* URL Input */}
      <div className="card">
        <h2 className="text-lg font-semibold text-gray-900">Start Lead Generation</h2>
        <p className="mt-1 text-sm text-gray-500">
          Enter a public exhibitor directory URL to discover companies.
        </p>
        <div className="mt-4 space-y-3">
          <div>
            <label className="block text-sm font-medium text-gray-700">Source Name (optional)</label>
            <input
              type="text"
              value={sourceName}
              onChange={(e) => setSourceName(e.target.value)}
              placeholder="e.g., LEAP 2026 Exhibitors"
              className="input mt-1"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700">Source URL</label>
            <input
              type="url"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://example.com/exhibitors"
              className="input mt-1"
              onKeyDown={(e) => e.key === 'Enter' && handleStart()}
            />
          </div>

          {/* Example URLs */}
          <div className="flex flex-wrap gap-2">
            {EXAMPLE_URLS.map((ex) => (
              <button
                key={ex.url}
                onClick={() => setUrl(ex.url)}
                className="badge bg-gray-100 text-gray-700 hover:bg-gray-200 cursor-pointer"
              >
                {ex.label}
              </button>
            ))}
          </div>

          <button
            onClick={handleStart}
            disabled={loading || !url}
            className="btn-primary w-full sm:w-auto"
          >
            {loading ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Play className="mr-2 h-4 w-4" />
            )}
            {loading ? 'Crawling...' : 'Start Lead Generation'}
          </button>

          {/* Progress */}
          {crawlProgress && (
            <div className="flex items-center gap-2 rounded-lg bg-blue-50 p-3 text-sm text-blue-700">
              <Loader2 className="h-4 w-4 animate-spin" />
              {crawlProgress}
            </div>
          )}

          {/* Success Message */}
          {message && (
            <div className="flex items-center gap-2 rounded-lg bg-green-50 p-3 text-sm text-green-700">
              <CheckCircle className="h-4 w-4" />
              {message}
            </div>
          )}

          {/* Error Message */}
          {error && (
            <div className="flex items-center gap-2 rounded-lg bg-red-50 p-3 text-sm text-red-700">
              <AlertCircle className="h-4 w-4" />
              {error}
            </div>
          )}
        </div>
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {stats.map((stat) => (
          <div key={stat.label} className="card flex items-center gap-4">
            <div className={`rounded-lg p-3 ${stat.color}`}>
              <stat.icon className="h-6 w-6 text-white" />
            </div>
            <div>
              <p className="text-2xl font-bold text-gray-900">{stat.value}</p>
              <p className="text-sm text-gray-500">{stat.label}</p>
            </div>
          </div>
        ))}
      </div>

      {/* Email outreach tracking (real records, auto-synced) */}
      <div className="card">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <h2 className="text-lg font-semibold text-gray-900">Email tracking</h2>
          <div className="flex items-center gap-2">
            {syncMsg && <span className="text-xs text-gray-500">{syncMsg}</span>}
            <button onClick={() => { handleSync() }} disabled={syncing} className="btn-secondary text-xs">
              {syncing ? <Loader2 className="mr-1 h-3 w-3 animate-spin" /> : null} Sync Gmail now
            </button>
            <Link to="/leads" className="text-sm text-primary-600 hover:text-primary-700">
              Open Leads
            </Link>
          </div>
        </div>
        <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
          {[
            { label: 'Sent today', value: outreach?.emails_sent_today ?? analytics?.emails_sent_today ?? 0 },
            { label: 'Replies today', value: outreach?.replies_today ?? analytics?.replies_today ?? 0 },
            { label: 'Follow-ups due', value: outreach?.followups_due ?? analytics?.email_followups_due ?? 0 },
            { label: 'Follow-ups sent', value: outreach?.followups_sent ?? analytics?.email_followups_sent ?? 0 },
            { label: 'Eligible leads', value: outreach?.eligible_leads ?? 0 },
            { label: 'Bounced', value: outreach?.bounced ?? 0 },
            { label: 'Unsubscribed', value: outreach?.unsubscribed ?? analytics?.unsubscribed ?? 0 },
            { label: 'Interested', value: outreach?.interested ?? analytics?.interested ?? 0 },
          ].map((s) => (
            <div key={s.label} className="rounded-lg border border-gray-200 p-3">
              <p className="text-xl font-bold text-gray-900">{s.value.toLocaleString()}</p>
              <p className="text-xs text-gray-500">{s.label}</p>
            </div>
          ))}
        </div>
        {sentEmails.length > 0 && (
          <div className="mt-4 overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-2 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Company</th>
                  <th className="px-4 py-2 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Email</th>
                  <th className="px-4 py-2 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Sent</th>
                  <th className="px-4 py-2 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Reply</th>
                  <th className="px-4 py-2 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Thread</th>
                  <th className="px-4 py-2 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Status</th>
                  <th className="px-4 py-2 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Next action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 bg-white">
                {sentEmails.slice(0, 20).map((r) => (
                  <tr key={r.outreach_id} className="hover:bg-gray-50">
                    <td className="px-4 py-2 text-sm font-medium text-gray-900">
                      <Link to={`/leads/${r.lead_id}`} className="text-primary-600 hover:text-primary-700">
                        {r.company || `Lead #${r.lead_id}`}
                      </Link>
                    </td>
                    <td className="px-4 py-2 text-xs text-gray-700">{r.to_email || '—'}</td>
                    <td className="px-4 py-2 text-xs text-gray-500">{r.sent_at ? new Date(r.sent_at).toLocaleString() : '—'}</td>
                    <td className="px-4 py-2 text-xs text-gray-500">{r.reply_at ? new Date(r.reply_at).toLocaleString() : '—'}</td>
                    <td className="px-4 py-2 text-xs">
                      {r.thread_url ? <a href={r.thread_url} target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:text-blue-700">Open</a> : '—'}
                    </td>
                    <td className="px-4 py-2 text-xs">
                      <span className="badge bg-gray-100 text-gray-800">{r.status}{r.follow_up_count > 0 ? ` · FU×${r.follow_up_count}` : ''}</span>
                    </td>
                    <td className="px-4 py-2 text-xs text-gray-600">{r.next_action}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="mt-2 text-xs text-gray-500">Showing latest {Math.min(20, sentEmails.length)} of {sentEmails.length} tracked sends. Full list on the Leads page.</p>
          </div>
        )}
      </div>

      {/* Still-running banner (poll timed out, crawl continues server-side) */}
      {stillRunning && (
        <div className="flex items-center gap-2 rounded-lg bg-yellow-50 p-3 text-sm text-yellow-800">
          <Loader2 className="h-4 w-4 animate-spin" />
          <span>
            Crawl of <strong>{stillRunning.name}</strong> is still running in the background
            (large directories take a while). New companies appear below and on the Companies page as they're saved — just refresh.
          </span>
          <button onClick={() => { loadAnalytics(); loadCompanies(); getPipeline().then((p) => setPipeline(p.stages)).catch(() => {}) }} className="btn-secondary ml-auto text-sm">
            Refresh
          </button>
        </div>
      )}

      {/* Email validation summary */}
      {matchStats && (
        <div className="card flex items-center gap-4">
          <div>
            <p className="text-2xl font-bold text-gray-900">{matchStats.match_rate}%</p>
            <p className="text-sm text-gray-500">emails match company website domains ({matchStats.matched.toLocaleString()} checked)</p>
          </div>
          <p className="text-sm text-gray-500">
            {matchStats.mismatched.toLocaleString()} need a human eye (free mailboxes, multi-brand domains, or no website).
            See the <Link to="/companies" className="text-primary-600 hover:text-primary-700">domain badges</Link> per company.
          </p>
        </div>
      )}

      {/* Recent Companies */}
      {companies.length > 0 && (
        <div className="card">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <h2 className="text-lg font-semibold text-gray-900">
              Companies {(analytics?.total_companies ?? 0) > 0 && <span className="text-sm font-normal text-gray-500">({analytics?.total_companies?.toLocaleString()} total)</span>}
            </h2>
            <Link to="/companies" className="text-sm text-primary-600 hover:text-primary-700">
              View all
            </Link>
          </div>
          <div className="mt-3 flex flex-col gap-2 sm:flex-row">
            <div className="relative flex-1">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
              <input
                type="text"
                placeholder="Search name..."
                value={resultSearch}
                onChange={(e) => { setResultSearch(e.target.value); setResultPage(0) }}
                className="input pl-10"
              />
            </div>
            <input
              type="text"
              placeholder="Filter country..."
              value={resultCountry}
              onChange={(e) => { setResultCountry(e.target.value); setResultPage(0) }}
              className="input sm:w-48"
            />
            <label className="flex items-center gap-2 whitespace-nowrap text-xs text-gray-600" title="Newest rows often have no contacts yet — enrichment lags behind discovery">
              <input
                type="checkbox"
                checked={contactOnly}
                onChange={(e) => { setContactOnly(e.target.checked); setResultPage(0) }}
                className="rounded border-gray-300"
              />
              With contacts first
            </label>
          </div>
          <div className="mt-4 overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-2 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Company</th>
                  <th className="px-4 py-2 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Email</th>
                  <th className="px-4 py-2 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Phone</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 bg-white">
                {companies
                  .filter((c) => {
                    if (!resultSearch) return true
                    const q = resultSearch.toLowerCase()
                    const contact = (c.contacts || [])[0]
                    return [c.company_name, c.country, c.city, contact?.business_email, contact?.phone]
                      .filter(Boolean).join(' ').toLowerCase().includes(q)
                  })
                  .slice(resultPage * PAGE_SIZE, resultPage * PAGE_SIZE + PAGE_SIZE)
                  .map((company) => {
                    const contact = (company.contacts || [])[0]
                    return (
                      <tr key={company.id} className="hover:bg-gray-50">
                        <td className="px-4 py-2">
                          <p className="text-sm font-medium text-gray-900">{company.company_name}</p>
                          <p className="text-xs text-gray-500">{[company.city, company.country].filter(Boolean).join(', ')}</p>
                        </td>
                        <td className="px-4 py-2 text-sm text-gray-700">{contact?.business_email || <span className="text-gray-400">—</span>}</td>
                        <td className="px-4 py-2 text-sm text-gray-700">{contact?.phone || <span className="text-gray-400">—</span>}</td>
                      </tr>
                    )
                  })}
              </tbody>
            </table>
          </div>
          <p className="mt-2 text-xs text-gray-500">
            {contactOnly
              ? `Showing companies with email/phone first (${resultTotal} in view) — full table with products on the Companies page.`
              : 'Showing up to 20 matches — full table with products on the Companies page.'}
          </p>
          <div className="mt-2 flex items-center justify-between">
            <p className="text-xs text-gray-500">
              Page {resultPage + 1} of {Math.max(1, Math.ceil(resultTotal / PAGE_SIZE))} ({resultTotal.toLocaleString()} total)
            </p>
            <div className="flex gap-2">
              <button
                onClick={() => setResultPage((p) => Math.max(0, p - 1))}
                disabled={resultPage === 0}
                className="btn-secondary text-xs"
              >
                Prev
              </button>
              <button
                onClick={() => setResultPage((p) => (p + 1) * PAGE_SIZE < resultTotal ? p + 1 : p)}
                disabled={(resultPage + 1) * PAGE_SIZE >= resultTotal}
                className="btn-secondary text-xs"
              >
                Next
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Funnel */}
      <div className="card">
        <h2 className="text-lg font-semibold text-gray-900">Lead Funnel</h2>
        <div className="mt-4 space-y-3">
          {[
            { label: 'Companies Discovered', value: analytics?.total_companies ?? 0, color: 'bg-blue-500' },
            { label: 'Contacts Found', value: analytics?.total_contacts ?? 0, color: 'bg-indigo-500' },
            { label: 'Emails Sent', value: analytics?.emails_sent ?? 0, color: 'bg-purple-500' },
            { label: 'Replies', value: analytics?.replies ?? 0, color: 'bg-orange-500' },
            { label: 'Interested', value: analytics?.interested ?? 0, color: 'bg-pink-500' },
            { label: 'Meetings', value: analytics?.meetings_booked ?? 0, color: 'bg-rose-500' },
            { label: 'Qualified Leads', value: analytics?.qualified ?? 0, color: 'bg-teal-500' },
          ].map((stage) => {
            const max = analytics?.total_companies ?? 1
            const pct = max > 0 ? Math.max(8, (stage.value / max) * 100) : 8
            return (
              <div key={stage.label} className="flex items-center gap-3">
                <div
                  className={`h-8 rounded-lg ${stage.color} flex items-center justify-center text-white text-sm font-medium transition-all`}
                  style={{ width: `${pct}%` }}
                >
                  {stage.value}
                </div>
                <span className="text-sm text-gray-600">{stage.label}</span>
              </div>
            )
          })}
        </div>
      </div>

      {/* How It Works — the 6-step workflow */}
      <div className="card">
        <h2 className="text-lg font-semibold text-gray-900">How It Works</h2>
        <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {(pipeline.length > 0 ? pipeline : [
            { step: 1, label: 'Discover exhibitor listings', count: 0 },
            { step: 2, label: 'Open each exhibitor profile', count: 0 },
            { step: 3, label: "Visit the company's website", count: 0 },
            { step: 4, label: 'Extract and validate business contacts', count: 0 },
            { step: 5, label: 'Save to PostgreSQL', count: 0 },
            { step: 6, label: 'Display companies in the dashboard', count: 0 },
          ]).map((s) => (
            <div key={s.step} className="rounded-lg border border-gray-200 p-4">
              <p className="text-xs font-medium uppercase tracking-wider text-primary-600">Step {s.step}</p>
              <p className="mt-1 text-sm font-medium text-gray-900">{s.label}</p>
              <p className="mt-1 text-2xl font-bold text-gray-900">{s.count.toLocaleString()}</p>
              {s.detail && (
                <p className="mt-1 text-xs text-gray-500">
                  {Object.entries(s.detail).map(([k, v]) => `${k}: ${v}`).join(' · ')}
                </p>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
