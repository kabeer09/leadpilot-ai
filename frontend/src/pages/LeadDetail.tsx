import { useState, useEffect } from 'react'
import { useParams, Link } from 'react-router-dom'
import {
  ArrowLeft,
  Building2,
  Mail,
  Phone,
  MessageSquare,
  Calendar,
  Star,
  CheckCircle,
  XCircle,
  Clock,
} from 'lucide-react'
import { getLead, scoreLead, generateEmail, validateEmail, queueLeadEmail, queueWhatsappFollowup, proposeMeeting, bookMeeting, approveWhatsapp } from '../services/api'
import type { LeadDetail as LeadDetailType } from '../types'

export default function LeadDetail() {
  const { id } = useParams<{ id: string }>()
  const [lead, setLead] = useState<LeadDetailType | null>(null)
  const [loading, setLoading] = useState(true)
  const [actionLoading, setActionLoading] = useState<string | null>(null)
  const [emailResult, setEmailResult] = useState<{ subject: string; body: string; used_fallback: boolean } | null>(null)
  const [validationResult, setValidationResult] = useState<{ is_valid: boolean; errors: string[]; warnings: string[] } | null>(null)
  const [queueResult, setQueueResult] = useState<{ outreach_id: number; subject: string } | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)

  useEffect(() => {
    if (id) loadLead()
  }, [id])

  const loadLead = async () => {
    try {
      const data = await getLead(parseInt(id!))
      setLead(data)
    } catch (err) {
      console.error('Failed to load lead:', err)
    } finally {
      setLoading(false)
    }
  }

  const handleScore = async () => {
    setActionLoading('score')
    try {
      await scoreLead(parseInt(id!))
      await loadLead()
    } finally {
      setActionLoading(null)
    }
  }

  const handleGenerateEmail = async () => {
    setActionLoading('email')
    setActionError(null)
    try {
      const draft = await generateEmail(parseInt(id!))
      setEmailResult(draft)
      await loadLead()
    } catch (err: any) {
      setActionError(err?.response?.data?.detail || 'Failed to generate email')
    } finally {
      setActionLoading(null)
    }
  }

  const handleValidate = async () => {
    setActionLoading('validate')
    setActionError(null)
    try {
      const result = await validateEmail(parseInt(id!))
      setValidationResult(result)
      await loadLead()
    } catch (err: any) {
      setActionError(err?.response?.data?.detail || 'Failed to validate email')
    } finally {
      setActionLoading(null)
    }
  }

  const handleQueueEmail = async () => {
    setActionLoading('queue')
    setActionError(null)
    try {
      const result = await queueLeadEmail(parseInt(id!))
      setQueueResult(result)
      await loadLead()
    } catch (err: any) {
      setActionError(err?.response?.data?.detail || 'Failed to queue email')
    } finally {
      setActionLoading(null)
    }
  }

  const handleQueueWhatsapp = async () => {
    setActionLoading('waqueue')
    setActionError(null)
    try {
      const result = await queueWhatsappFollowup(parseInt(id!))
      setQueueResult({ outreach_id: result.id, subject: 'WhatsApp follow-up' })
      await loadLead()
    } catch (err: any) {
      setActionError(err?.response?.data?.detail || 'Failed to queue WhatsApp follow-up')
    } finally {
      setActionLoading(null)
    }
  }

  const handleProposeMeeting = async () => {
    setActionLoading('propose')
    setActionError(null)
    try {
      await proposeMeeting({ lead_id: parseInt(id!), start_time: meetingStart, end_time: meetingEnd })
      setMeetingStart('')
      setMeetingEnd('')
      await loadLead()
    } catch (err: any) {
      setActionError(err?.response?.data?.detail || 'Failed to propose meeting')
    } finally {
      setActionLoading(null)
    }
  }

  const handleBookMeeting = async (meetingId: number) => {
    setActionLoading('book')
    setActionError(null)
    try {
      await bookMeeting(meetingId)
      await loadLead()
    } catch (err: any) {
      setActionError(err?.response?.data?.detail || 'Failed to book meeting')
    } finally {
      setActionLoading(null)
    }
  }

  const showWhatsappQueue = lead && (lead.status === 'FOLLOWUP_DUE' || lead.status === 'EMAIL_SENT') && !!lead.contact?.whatsapp_number
  const [meetingStart, setMeetingStart] = useState('')
  const [meetingEnd, setMeetingEnd] = useState('')
  const showMeetingSection = lead && ['INTERESTED', 'MEETING_PROPOSED', 'REPLIED', 'QUALIFIED'].includes(lead.status)
  const proposedMeeting = lead?.meetings.find((m) => m.status === 'PROPOSED')
  const bookedMeeting = lead?.meetings.find((m) => m.status === 'CONFIRMED' && m.meet_url)

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary-600 border-t-transparent" />
      </div>
    )
  }

  if (!lead) {
    return (
      <div className="card text-center">
        <p className="text-gray-500">Lead not found.</p>
        <Link to="/leads" className="mt-4 inline-block text-primary-600 hover:text-primary-700">
          Back to Leads
        </Link>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center gap-4">
        <Link to="/leads" className="btn-secondary">
          <ArrowLeft className="h-4 w-4" />
        </Link>
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Lead #{lead.id}</h1>
          <p className="text-sm text-gray-500">Lead details and outreach management</p>
        </div>
      </div>

      {/* Company Info */}
      {lead.company && (
        <div className="card">
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <Building2 className="h-5 w-5 text-primary-600" />
              <h2 className="text-lg font-semibold text-gray-900">Company</h2>
            </div>
            <Link to={`/companies/${lead.company.id}`} className="btn-secondary text-sm">
              Open full profile
            </Link>
          </div>
          <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div>
              <p className="text-sm text-gray-500">Name</p>
              <p className="font-medium">{lead.company.company_name}</p>
            </div>
            {lead.company.industry && (
              <div>
                <p className="text-sm text-gray-500">Industry</p>
                <p className="font-medium">{lead.company.industry}</p>
              </div>
            )}
            {lead.company.country && (
              <div>
                <p className="text-sm text-gray-500">Country</p>
                <p className="font-medium">{lead.company.country}</p>
              </div>
            )}
            {lead.company.website && (
              <div>
                <p className="text-sm text-gray-500">Website</p>
                <a href={lead.company.website} target="_blank" rel="noopener noreferrer" className="text-primary-600 hover:text-primary-700">
                  {lead.company.website}
                </a>
              </div>
            )}
          </div>
          {lead.company.description && (
            <div className="mt-4">
              <p className="text-sm text-gray-500">Description</p>
              <p className="mt-1 text-sm text-gray-700">{lead.company.description}</p>
            </div>
          )}
        </div>
      )}

      {/* Contact Info */}
      {lead.contact && (
        <div className="card">
          <h2 className="text-lg font-semibold text-gray-900">Contact</h2>
          <div className="mt-4 space-y-3">
            {lead.contact.business_email && (
              <div className="flex items-center gap-2">
                <Mail className="h-4 w-4 text-gray-400" />
                <span className="text-sm">{lead.contact.business_email}</span>
              </div>
            )}
            {lead.contact.phone && (
              <div className="flex items-center gap-2">
                <Phone className="h-4 w-4 text-gray-400" />
                <span className="text-sm">{lead.contact.phone}</span>
              </div>
            )}
            {lead.contact.whatsapp_number && (
              <div className="flex flex-wrap items-center gap-2">
                <MessageSquare className="h-4 w-4 text-gray-400" />
                <span className="text-sm">{lead.contact.whatsapp_number}</span>
                {(lead.contact as { whatsapp_eligible?: boolean }).whatsapp_eligible ? (
                  <span className="badge bg-green-100 text-green-800">WhatsApp approved</span>
                ) : (
                  <button
                    onClick={async () => {
                      if (!window.confirm(`Approve ${lead.contact!.whatsapp_number} for WhatsApp messaging? Only approve numbers verified as business contacts.`)) return
                      try {
                        await approveWhatsapp(lead.contact!.id, 'approved from lead detail page')
                        const updated = await getLead(parseInt(id!))
                        setLead(updated)
                      } catch {
                        setActionError('Approval failed')
                      }
                    }}
                    className="btn-secondary text-xs"
                    title="Required before any automated WhatsApp message"
                  >
                    Approve WhatsApp
                  </button>
                )}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Lead Score */}
      <div className="card">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold text-gray-900">Lead Score</h2>
          <button
            onClick={handleScore}
            disabled={actionLoading === 'score'}
            className="btn-secondary text-sm"
          >
            {actionLoading === 'score' ? 'Scoring...' : 'Recalculate'}
          </button>
        </div>
        <div className="mt-4 flex items-center gap-4">
          <div className="flex-1">
            <div className="h-4 rounded-full bg-gray-200">
              <div
                className="h-4 rounded-full bg-primary-600 transition-all"
                style={{ width: `${lead.lead_score}%` }}
              />
            </div>
          </div>
          <span className="text-2xl font-bold text-gray-900">{lead.lead_score}/100</span>
        </div>
        <div className="mt-2">
          <span className={`badge ${
            lead.lead_priority === 'HIGH' ? 'bg-red-100 text-red-800' :
            lead.lead_priority === 'MEDIUM' ? 'bg-yellow-100 text-yellow-800' :
            'bg-gray-100 text-gray-800'
          }`}>
            {lead.lead_priority}
          </span>
        </div>
        {lead.ai_reason && (
          <div className="mt-4">
            <p className="text-sm text-gray-500">AI Reasoning</p>
            <p className="mt-1 text-sm text-gray-700">{lead.ai_reason}</p>
          </div>
        )}
      </div>

      {/* AI Email */}
      <div className="card">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold text-gray-900">AI Email → n8n</h2>
          <div className="flex gap-2">
            <button
              onClick={handleGenerateEmail}
              disabled={actionLoading === 'email'}
              className="btn-secondary text-sm"
            >
              {actionLoading === 'email' ? 'Generating...' : 'Generate'}
            </button>
            <button
              onClick={handleValidate}
              disabled={actionLoading === 'validate'}
              className="btn-secondary text-sm"
            >
              {actionLoading === 'validate' ? 'Validating...' : 'Validate'}
            </button>
            <button
              onClick={handleQueueEmail}
              disabled={actionLoading === 'queue'}
              className="btn-primary text-sm"
              title="Queue the validated email for Gmail sending via n8n"
            >
              {actionLoading === 'queue' ? 'Queueing...' : 'Queue for sending'}
            </button>
          </div>
        </div>
        {actionError && (
          <div className="mt-4 rounded-lg border border-red-200 bg-red-50 p-3">
            <p className="text-sm text-red-700">{actionError}</p>
          </div>
        )}
        {emailResult && (
          <div className="mt-4 rounded-lg border border-gray-200 p-3">
            <p className="text-sm font-medium text-gray-900">Draft: {emailResult.subject}</p>
            {emailResult.used_fallback && (
              <p className="mt-1 text-xs text-yellow-700">AI unavailable — used fallback template.</p>
            )}
            <p className="mt-2 whitespace-pre-wrap text-sm text-gray-700">{emailResult.body}</p>
          </div>
        )}
        {lead.ai_summary && (
          <div className="mt-4">
            <p className="text-sm text-gray-500">AI Summary</p>
            <p className="mt-1 text-sm text-gray-700">{lead.ai_summary}</p>
          </div>
        )}
        {queueResult && (
          <div className="mt-4 rounded-lg border border-green-200 bg-green-50 p-3">
            <p className="text-sm font-medium text-green-800">
              Queued for Gmail sending via n8n (outreach #{queueResult.outreach_id})
            </p>
            <p className="mt-1 text-xs text-green-700">
              The next n8n poll picks it up from GET /api/outreach/ready.
            </p>
          </div>
        )}
        {validationResult && (
          <div className="mt-4">
            <div className={`flex items-center gap-2 ${validationResult.is_valid ? 'text-green-600' : 'text-red-600'}`}>
              {validationResult.is_valid ? <CheckCircle className="h-5 w-5" /> : <XCircle className="h-5 w-5" />}
              <span className="font-medium">{validationResult.is_valid ? 'Valid' : 'Invalid'}</span>
            </div>
            {validationResult.errors.length > 0 && (
              <div className="mt-2">
                <p className="text-sm font-medium text-red-600">Errors:</p>
                <ul className="mt-1 list-inside list-disc text-sm text-red-600">
                  {validationResult.errors.map((e, i) => <li key={i}>{e}</li>)}
                </ul>
              </div>
            )}
            {validationResult.warnings.length > 0 && (
              <div className="mt-2">
                <p className="text-sm font-medium text-yellow-600">Warnings:</p>
                <ul className="mt-1 list-inside list-disc text-sm text-yellow-600">
                  {validationResult.warnings.map((w, i) => <li key={i}>{w}</li>)}
                </ul>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Meetings */}
      {showMeetingSection && (
        <div className="card">
          <div className="flex items-center gap-2">
            <Calendar className="h-5 w-5 text-primary-600" />
            <h2 className="text-lg font-semibold text-gray-900">Meeting</h2>
          </div>
          {bookedMeeting?.meet_url && (
            <div className="mt-4 rounded-lg border border-green-200 bg-green-50 p-3">
              <p className="text-sm font-medium text-green-800">Booked on Google Calendar</p>
              <a href={bookedMeeting.meet_url} target="_blank" rel="noopener noreferrer" className="mt-1 inline-block text-sm text-primary-600 hover:text-primary-700">
                Join Google Meet →
              </a>
            </div>
          )}
          {proposedMeeting && (
            <div className="mt-4 flex items-center justify-between rounded-lg border border-gray-200 p-3">
              <div>
                <p className="text-sm font-medium">
                  Proposed: {new Date(proposedMeeting.start_time).toLocaleString()} – {new Date(proposedMeeting.end_time).toLocaleString()}
                </p>
                <p className="text-xs text-gray-500">Status: {proposedMeeting.status}</p>
              </div>
              <button
                onClick={() => handleBookMeeting(proposedMeeting.id)}
                disabled={actionLoading === 'book'}
                className="btn-primary text-sm"
              >
                {actionLoading === 'book' ? 'Booking...' : 'Book on Google Calendar'}
              </button>
            </div>
          )}
          {!proposedMeeting && !bookedMeeting && (
            <div className="mt-4 flex flex-col gap-2 sm:flex-row sm:items-end">
              <div>
                <label className="text-xs text-gray-500">Start</label>
                <input
                  type="datetime-local"
                  value={meetingStart}
                  onChange={(e) => setMeetingStart(e.target.value)}
                  className="mt-1 block rounded-lg border border-gray-300 px-3 py-2 text-sm"
                />
              </div>
              <div>
                <label className="text-xs text-gray-500">End</label>
                <input
                  type="datetime-local"
                  value={meetingEnd}
                  onChange={(e) => setMeetingEnd(e.target.value)}
                  className="mt-1 block rounded-lg border border-gray-300 px-3 py-2 text-sm"
                />
              </div>
              <button
                onClick={handleProposeMeeting}
                disabled={actionLoading === 'propose' || !meetingStart || !meetingEnd}
                className="btn-secondary text-sm"
              >
                {actionLoading === 'propose' ? 'Proposing...' : 'Propose meeting'}
              </button>
            </div>
          )}
        </div>
      )}

      {/* Outreach History */}
      {showWhatsappQueue && (
        <div className="rounded-lg border border-yellow-200 bg-yellow-50 p-4">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-yellow-800">
                {lead.status === 'FOLLOWUP_DUE' ? '24h WhatsApp follow-up is due' : 'Email sent — WhatsApp follow-up available'}
              </p>
              <p className="mt-1 text-xs text-yellow-700">
                Queues an AI-drafted message to {lead.contact?.whatsapp_number} for sending via n8n.
              </p>
            </div>
            <button
              onClick={handleQueueWhatsapp}
              disabled={actionLoading === 'waqueue'}
              className="btn-primary text-sm"
            >
              {actionLoading === 'waqueue' ? 'Queueing...' : 'Queue WhatsApp'}
            </button>
          </div>
        </div>
      )}
      {lead.outreach.length > 0 && (
        <div className="card">
          <h2 className="text-lg font-semibold text-gray-900">Outreach History</h2>
          <div className="mt-4 space-y-3">
            {lead.outreach.map((o) => (
              <div key={o.id} className="flex items-center justify-between rounded-lg border border-gray-200 p-3">
                <div>
                  <p className="text-sm font-medium">{o.subject || o.channel}</p>
                  <p className="text-xs text-gray-500">{o.channel} - {o.status}</p>
                </div>
                <span className={`badge ${
                  o.status === 'SENT' ? 'bg-green-100 text-green-800' :
                  o.status === 'FAILED' ? 'bg-red-100 text-red-800' :
                  'bg-gray-100 text-gray-800'
                }`}>
                  {o.status}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Activity Timeline */}
      {lead.activities.length > 0 && (
        <div className="card">
          <h2 className="text-lg font-semibold text-gray-900">Activity Timeline</h2>
          <div className="mt-4 space-y-3">
            {lead.activities.map((a) => (
              <div key={a.id} className="flex items-start gap-3">
                <div className="mt-1">
                  <Clock className="h-4 w-4 text-gray-400" />
                </div>
                <div>
                  <p className="text-sm font-medium">{a.activity_type}</p>
                  {a.description && <p className="text-sm text-gray-500">{a.description}</p>}
                  <p className="text-xs text-gray-400">{new Date(a.created_at).toLocaleString()}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
