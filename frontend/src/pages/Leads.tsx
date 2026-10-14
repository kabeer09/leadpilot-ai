import { useState, useEffect, useCallback } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { Search, Filter, Star, Mail, Phone, MessageSquare, Building2, Globe, MapPin, Package, Download, ArrowUpDown, Send, RefreshCw, CheckSquare, Square, Clock, AlertCircle } from 'lucide-react'
import { getLeads, exportLeadsCsv, getCompanyFilters, getEmailFollowupsDue, sendFollowUp, bulkFollowUp } from '../services/api'
import BulkSendPanel from '../components/BulkSendPanel'
import type { Lead } from '../types'

const statusColors: Record<string, string> = {
  NEW: 'bg-gray-100 text-gray-800',
  ENRICHED: 'bg-blue-100 text-blue-800',
  SCORED: 'bg-indigo-100 text-indigo-800',
  EMAIL_GENERATED: 'bg-purple-100 text-purple-800',
  EMAIL_VALIDATED: 'bg-violet-100 text-violet-800',
  EMAIL_SENT: 'bg-green-100 text-green-800',
  FOLLOWUP_DUE: 'bg-yellow-100 text-yellow-800',
  WHATSAPP_SENT: 'bg-emerald-100 text-emerald-800',
  REPLIED: 'bg-orange-100 text-orange-800',
  INTERESTED: 'bg-pink-100 text-pink-800',
  MEETING_PROPOSED: 'bg-rose-100 text-rose-800',
  MEETING_BOOKED: 'bg-red-100 text-red-800',
  QUALIFIED: 'bg-teal-100 text-teal-800',
}

const priorityColors: Record<string, string> = {
  HIGH: 'bg-red-100 text-red-800',
  MEDIUM: 'bg-yellow-100 text-yellow-800',
  LOW: 'bg-gray-100 text-gray-800',
}

function renderFollowUpStatus(lead: Lead) {
  const o = lead.last_outreach
  if (!o) return <span className="text-xs text-gray-400">—</span>
  const followUpCount = (o as any).follow_up_count || 0
  const followUpSentAt = (o as any).follow_up_sent_at
  if (followUpCount > 0) {
    return (
      <div>
        <span className="badge bg-yellow-100 text-yellow-800">
          <Clock className="mr-1 h-3 w-3" />
          Follow-up #{followUpCount}
        </span>
        {followUpSentAt && (
          <p className="mt-1 text-xs text-gray-400">{new Date(followUpSentAt).toLocaleDateString()}</p>
        )}
      </div>
    )
  }
  if (o.status === 'SENT' && o.sent_at) {
    const sentDate = new Date(o.sent_at)
    const hoursSince = (Date.now() - sentDate.getTime()) / (1000 * 60 * 60)
    if (hoursSince >= 24) {
      return (
        <span className="badge bg-orange-100 text-orange-800">
          <AlertCircle className="mr-1 h-3 w-3" />
          Due now
        </span>
      )
    }
  }
  return <span className="text-xs text-gray-400">—</span>
}

export default function Leads() {
  const [searchParams] = useSearchParams()
  const [leads, setLeads] = useState<Lead[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState(searchParams.get('q') || '')
  const [statusFilter, setStatusFilter] = useState('')
  const [priorityFilter, setPriorityFilter] = useState('')
  const [fairFilter, setFairFilter] = useState('')
  const [categoryFilter, setCategoryFilter] = useState('')
  const [emailFilter, setEmailFilter] = useState<'' | 'eligible' | 'sent' | 'not_sent' | 'followup_due'>('')
  const [sort, setSort] = useState('score_desc')
  const [pageSize, setPageSize] = useState(50)
  const [page, setPage] = useState(0)
  const [exporting, setExporting] = useState(false)
  const [fairs, setFairs] = useState<{ id: number; name: string }[]>([])
  const [categories, setCategories] = useState<string[]>([])
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())
  const [followupDue, setFollowupDue] = useState<{ lead_id: number; company_name: string | null; to_email: string | null; email_sent_at: string | null; thread_id: string | null }[]>([])
  const [followupBusy, setFollowupBusy] = useState(false)
  const [followupMsg, setFollowupMsg] = useState('')

  const loadLeads = useCallback(async () => {
    try {
      const params: Record<string, string | number> = { limit: 500 }
      if (statusFilter) params.status = statusFilter
      if (priorityFilter) params.priority = priorityFilter
      if (fairFilter) params.source_id = parseInt(fairFilter)
      if (categoryFilter) params.category = categoryFilter
      if (emailFilter) params.email_filter = emailFilter
      if (sort) params.sort = sort
      const data = await getLeads(params as { status?: string; priority?: string })
      setLeads(data)
    } catch (err) {
      console.error('Failed to load leads:', err)
    } finally {
      setLoading(false)
    }
  }, [statusFilter, priorityFilter, fairFilter, categoryFilter, emailFilter, sort])

  useEffect(() => {
    loadLeads()
  }, [loadLeads])

  useEffect(() => {
    getCompanyFilters().then((f) => {
      setFairs(f.sources)
      setCategories(f.categories)
    }).catch(() => {})
  }, [])

  useEffect(() => {
    if (emailFilter === 'followup_due') {
      getEmailFollowupsDue().then(setFollowupDue).catch(() => {})
    }
  }, [emailFilter])

  const toggleSelect = (id: number) => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const handleBulkFollowUp = async () => {
    setFollowupBusy(true)
    setFollowupMsg('')
    try {
      const r = await bulkFollowUp({ limit: 50, dry_run: false })
      setFollowupMsg(`Follow-ups: ${r.sent} sent, ${r.skipped} skipped`)
      loadLeads()
    } catch (err: any) {
      setFollowupMsg(err?.response?.data?.detail || 'Follow-up failed')
    } finally {
      setFollowupBusy(false)
    }
  }

  const handleSendToSelected = async () => {
    if (selectedIds.size === 0) return
    if (!window.confirm(`Queue email for ${selectedIds.size} selected leads?`)) return
    // Use the bulk send panel's queue mechanism — for now, alert user
    alert(`Selected ${selectedIds.size} leads. Use "Send email to all" panel above to send to eligible leads, or use the queue-bulk API.`)
  }

  const filteredLeads = leads.filter((lead) => {
    if (search) {
      const q = search.toLowerCase()
      const hay = [
        lead.company?.company_name, lead.company?.country, lead.company?.industry,
        lead.contact?.business_email, lead.contact?.phone, String(lead.id),
      ].filter(Boolean).join(' ').toLowerCase()
      if (!hay.includes(q)) return false
    }
    return true
  })

  const allSelected = filteredLeads.length > 0 && filteredLeads.every((l) => selectedIds.has(l.id))
  const toggleSelectAll = () => {
    if (allSelected) setSelectedIds(new Set())
    else setSelectedIds(new Set(filteredLeads.map((l) => l.id)))
  }

  const totalPages = Math.max(1, Math.ceil(filteredLeads.length / pageSize))
  const pageLeads = filteredLeads.slice(page * pageSize, page * pageSize + pageSize)

  const handleExport = async () => {
    setExporting(true)
    try {
      const params: Record<string, string | number> = {}
      if (statusFilter) params.status = statusFilter
      if (priorityFilter) params.priority = priorityFilter
      if (fairFilter) params.source_id = parseInt(fairFilter)
      if (categoryFilter) params.category = categoryFilter
      await exportLeadsCsv(params)
    } catch (err) {
      console.error('Export failed:', err)
    } finally {
      setExporting(false)
    }
  }

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary-600 border-t-transparent" />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Leads</h1>
        <p className="mt-1 text-sm text-gray-500">
          Manage and track all your B2B leads with company contact information.
        </p>
      </div>

      {/* Bulk send: custom template -> Gmail -> follow-up */}
      <BulkSendPanel onDone={loadLeads} />

      {/* Filters */}
      <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
          <input
            type="text"
            placeholder="Search company, phone, email…"
            value={search}
            onChange={(e) => { setSearch(e.target.value); setPage(0) }}
            className="input pl-10"
          />
        </div>
        <div className="relative">
          <Filter className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
          <select
            value={statusFilter}
            onChange={(e) => { setStatusFilter(e.target.value); setPage(0) }}
            className="input pl-10 pr-8"
          >
            <option value="">All Status</option>
            {Object.keys(statusColors).map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
        </div>
        <div className="relative">
          <select
            value={priorityFilter}
            onChange={(e) => { setPriorityFilter(e.target.value); setPage(0) }}
            className="input pr-8"
          >
            <option value="">All Priority</option>
            {Object.keys(priorityColors).map((p) => (
              <option key={p} value={p}>{p}</option>
            ))}
          </select>
        </div>
        <select
          value={fairFilter}
          onChange={(e) => { setFairFilter(e.target.value); setPage(0) }}
          className="input pr-8" title="Fair / source"
        >
          <option value="">All fairs</option>
          {fairs.map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}
        </select>
        <select
          value={categoryFilter}
          onChange={(e) => { setCategoryFilter(e.target.value); setPage(0) }}
          className="input pr-8" title="Product category"
        >
          <option value="">All categories</option>
          {categories.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
        <select
          value={emailFilter}
          onChange={(e) => { setEmailFilter(e.target.value as typeof emailFilter); setPage(0) }}
          className="input pr-8" title="Email status filter"
        >
          <option value="">All email status</option>
          <option value="eligible">Eligible to send</option>
          <option value="sent">Already sent email</option>
          <option value="not_sent">Never sent email</option>
          <option value="followup_due">24h follow-up due</option>
        </select>
        <select
          value={sort}
          onChange={(e) => setSort(e.target.value)}
          className="input pr-8" title="Sort by"
        >
          <option value="score_desc">Score ↓</option>
          <option value="score_asc">Score ↑</option>
          <option value="name">Company A–Z</option>
          <option value="updated_desc">Recently updated</option>
        </select>
        <select
          value={pageSize}
          onChange={(e) => { setPageSize(parseInt(e.target.value)); setPage(0) }}
          className="input pr-8" title="Rows per page"
        >
          {[25, 50, 100].map((n) => <option key={n} value={n}>{n} / page</option>)}
        </select>
        <button onClick={handleExport} disabled={exporting} className="btn-secondary text-sm" title="Download filtered leads as CSV">
          <Download className="mr-2 h-4 w-4" />{exporting ? 'Exporting…' : 'Export CSV'}
        </button>
        {emailFilter === 'followup_due' && (
          <button onClick={handleBulkFollowUp} disabled={followupBusy} className="btn-primary text-sm" title="Send 24h follow-up emails to all due leads">
            {followupBusy ? <RefreshCw className="mr-2 h-4 w-4 animate-spin" /> : <Send className="mr-2 h-4 w-4" />}
            {followupBusy ? 'Sending…' : `Send 24h follow-ups (${followupDue.length})`}
          </button>
        )}
        {selectedIds.size > 0 && (
          <button onClick={handleSendToSelected} className="btn-secondary text-sm" title="Queue email for selected leads">
            <CheckSquare className="mr-2 h-4 w-4" /> Queue {selectedIds.size} selected
          </button>
        )}
      </div>
      {followupMsg && (
        <div className="rounded-lg bg-blue-50 p-3 text-sm text-blue-800">{followupMsg}</div>
      )}

      {/* Table */}
      <div className="card overflow-hidden p-0">
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-3 py-3">
                  <button onClick={toggleSelectAll} className="text-gray-400 hover:text-gray-600" title="Select all">
                    {allSelected ? <CheckSquare className="h-4 w-4" /> : <Square className="h-4 w-4" />}
                  </button>
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Company</th>
                <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Contact</th>
                <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Email sent?</th>
                <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Follow-up</th>
                <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Score</th>
                <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Priority</th>
                <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Status</th>
                <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Created</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 bg-white">
              {filteredLeads.length === 0 ? (
                <tr>
                  <td colSpan={9} className="px-6 py-12 text-center text-sm text-gray-500">
                    No leads match. Adjust filters or add a source URL on the Dashboard.
                  </td>
                </tr>
              ) : (
                pageLeads.map((lead) => {
                  const company = lead.company
                  const contact = lead.contact
                  const products = company?.products || []
                  const isSelected = selectedIds.has(lead.id)

                  return (
                    <tr key={lead.id} className={`hover:bg-gray-50 ${isSelected ? 'bg-blue-50' : ''}`}>
                      <td className="px-3 py-4">
                        <button onClick={() => toggleSelect(lead.id)} className="text-gray-400 hover:text-gray-600">
                          {isSelected ? <CheckSquare className="h-4 w-4 text-primary-600" /> : <Square className="h-4 w-4" />}
                        </button>
                      </td>
                      <td className="px-6 py-4">
                        <Link to={`/leads/${lead.id}`} className="text-sm font-medium text-primary-600 hover:text-primary-700">
                          {company?.company_name || `Lead #${lead.id}`}
                        </Link>
                        {company?.industry && (
                          <p className="text-xs text-gray-500">{company.industry}</p>
                        )}
                        {company?.website && (
                          <a
                            href={company.website}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-xs text-blue-600 hover:text-blue-700 flex items-center gap-1 mt-0.5"
                          >
                            <Globe className="h-3 w-3" />
                            Website
                          </a>
                        )}
                        {products.length > 0 && (
                          <p className="text-xs text-gray-400 mt-0.5 flex items-center gap-1">
                            <Package className="h-3 w-3" />
                            {products.length} product{products.length > 1 ? 's' : ''}
                          </p>
                        )}
                      </td>
                      <td className="px-6 py-4">
                        <div className="space-y-1">
                          {contact?.business_email && (
                            <a
                              href={`mailto:${contact.business_email}`}
                              className="flex items-center gap-1 text-xs text-blue-600 hover:text-blue-700"
                            >
                              <Mail className="h-3 w-3" />
                              {contact.business_email}
                            </a>
                          )}
                          {contact?.phone && (
                            <span className="flex items-center gap-1 text-xs text-gray-600">
                              <Phone className="h-3 w-3" />
                              {contact.phone}
                            </span>
                          )}
                          {contact?.whatsapp_number && (
                            <span className="flex items-center gap-1 text-xs text-green-600">
                              <MessageSquare className="h-3 w-3" />
                              WhatsApp
                            </span>
                          )}
                          {!contact?.business_email && !contact?.phone && !contact?.whatsapp_number && (
                            <span className="text-xs text-gray-400">No contact</span>
                          )}
                        </div>
                      </td>
                      <td className="px-6 py-4">
                        {(() => {
                          const o = lead.last_outreach
                          if (!o) return <span className="text-xs text-gray-400">Not sent</span>
                          const color =
                            o.status === 'SENT' ? 'bg-green-100 text-green-800' :
                            o.status === 'REPLIED' ? 'bg-orange-100 text-orange-800' :
                            o.status === 'FAILED' || o.status === 'BOUNCED' ? 'bg-red-100 text-red-800' :
                            o.status === 'DELIVERED' ? 'bg-blue-100 text-blue-800' :
                            'bg-gray-100 text-gray-800'
                          const threadUrl = (o as any).provider_thread_id
                            ? `https://mail.google.com/mail/u/0/#inbox/${(o as any).provider_thread_id}`
                            : null
                          return (
                            <div>
                              <span className={`badge ${color}`}>
                                {o.channel === 'WHATSAPP' ? 'WA ' : ''}{o.status}
                              </span>
                              {o.sent_at && (
                                <p className="mt-1 text-xs text-gray-400">{new Date(o.sent_at).toLocaleDateString()}</p>
                              )}
                              {threadUrl && (
                                <a href={threadUrl} target="_blank" rel="noopener noreferrer" className="mt-0.5 block text-xs text-blue-600 hover:text-blue-700">
                                  Gmail thread
                                </a>
                              )}
                            </div>
                          )
                        })()}
                      </td>
                      <td className="px-6 py-4">
                        {renderFollowUpStatus(lead)}
                      </td>
                      <td className="px-6 py-4">
                        <div className="flex items-center gap-2">
                          <div className="h-2 w-16 rounded-full bg-gray-200">
                            <div
                              className="h-2 rounded-full bg-primary-600"
                              style={{ width: `${lead.lead_score}%` }}
                            />
                          </div>
                          <span className="text-sm text-gray-600">{lead.lead_score}</span>
                        </div>
                      </td>
                      <td className="px-6 py-4">
                        <span className={`badge ${priorityColors[lead.lead_priority] || 'bg-gray-100 text-gray-800'}`}>
                          {lead.lead_priority}
                        </span>
                      </td>
                      <td className="px-6 py-4">
                        <span className={`badge ${statusColors[lead.status] || 'bg-gray-100 text-gray-800'}`}>
                          {lead.status}
                        </span>
                      </td>
                      <td className="px-6 py-4 text-sm text-gray-500">
                        {new Date(lead.created_at).toLocaleDateString()}
                      </td>
                    </tr>
                  )
                })
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Pager */}
      <div className="flex items-center justify-between">
        <p className="text-xs text-gray-500">
          Page {page + 1} of {totalPages} ({filteredLeads.length.toLocaleString()} leads)
        </p>
        <div className="flex gap-2">
          <button
            onClick={() => setPage((p) => Math.max(0, p - 1))}
            disabled={page === 0}
            className="btn-secondary text-xs"
          >
            Prev
          </button>
          <button
            onClick={() => setPage((p) => (p + 1 < totalPages ? p + 1 : p))}
            disabled={page + 1 >= totalPages}
            className="btn-secondary text-xs"
          >
            Next
          </button>
        </div>
      </div>
    </div>
  )
}
