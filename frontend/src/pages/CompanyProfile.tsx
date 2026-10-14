import { useState, useEffect } from 'react'
import { useParams, Link } from 'react-router-dom'
import {
  ArrowLeft, Building2, Globe, Mail, Phone, MessageSquare, CheckCircle,
  AlertTriangle, Save, MapPin, Package, Link as LinkIcon, ShieldCheck,
} from 'lucide-react'
import { getCompany, updateCompany, enrichCompany, getCompanyContacts } from '../services/api'
import type { Company } from '../types'
import { emailMatchesWebsite } from '../types'

const TYPE_LABELS: Record<string, string> = {
  manufacturer: 'Manufacturer', wholesaler: 'Wholesaler', distributor: 'Distributor',
  retailer: 'Retailer', importer: 'Importer', exporter: 'Exporter', brand: 'Brand',
  unknown: 'Unknown',
}

export default function CompanyProfile() {
  const { id } = useParams<{ id: string }>()
  const [company, setCompany] = useState<Company | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [enriching, setEnriching] = useState(false)
  const [notes, setNotes] = useState('')
  const [msg, setMsg] = useState('')
  const [audit, setAudit] = useState<{ items: { id: number; contact_type: string; display_value: string; source_url: string | null; source_page_type: string | null; is_primary: boolean; verification_status: string }[]; coverage: { emails: string[]; phones: string[]; whatsapp: string[] } | null }>({ items: [], coverage: null })

  const load = async () => {
    try {
      const data = await getCompany(parseInt(id!))
      setCompany(data)
      setNotes(data.notes || '')
      getCompanyContacts(parseInt(id!)).then((c) => setAudit({ items: c.items, coverage: c.coverage })).catch(() => {})
    } catch (err) {
      console.error('Failed to load company:', err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (id) load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id])

  const saveField = async (data: { notes?: string; verified?: boolean; company_type?: string }) => {
    setSaving(true)
    try {
      const updated = await updateCompany(parseInt(id!), data)
      setCompany(updated)
      setNotes(updated.notes || '')
      setMsg('Saved.')
      setTimeout(() => setMsg(''), 2500)
    } catch {
      setMsg('Save failed.')
    } finally {
      setSaving(false)
    }
  }

  const handleEnrich = async () => {
    if (!company?.website) return
    setEnriching(true)
    try {
      await enrichCompany(company.id)
      await load()
      setMsg('Enriched from company website.')
      setTimeout(() => setMsg(''), 3000)
    } catch {
      setMsg('Enrichment failed.')
    } finally {
      setEnriching(false)
    }
  }

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary-600 border-t-transparent" />
      </div>
    )
  }

  if (!company) {
    return (
      <div className="card text-center">
        <p className="text-gray-500">Company not found.</p>
        <Link to="/companies" className="mt-4 inline-block text-primary-600 hover:text-primary-700">Back to Companies</Link>
      </div>
    )
  }

  const contacts = company.contacts || []
  const products = company.products || []
  const warnings: string[] = []
  if (!contacts.some((c) => c.business_email)) warnings.push('No public business email found.')
  if (!contacts.some((c) => c.phone)) warnings.push('No public business phone found.')
  if (!company.website) warnings.push('No official website recorded.')
  if (!company.description) warnings.push('No company description available.')
  if (products.length === 0) warnings.push('No products recorded.')
  const unverified = contacts.filter((c) => c.business_email && !emailMatchesWebsite(c.business_email, company.website))
  if (unverified.length > 0) warnings.push(`${unverified.length} email(s) don't match the company website domain — verify before sending.`)

  const completeness = company.completeness != null ? Math.round(company.completeness * 100) : null

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-4">
        <Link to="/companies" className="btn-secondary"><ArrowLeft className="h-4 w-4" /></Link>
        <div className="flex-1">
          <h1 className="flex items-center gap-2 text-2xl font-bold text-gray-900">
            <Building2 className="h-6 w-6 text-primary-600" />
            {company.company_name}
          </h1>
          <p className="mt-1 flex flex-wrap items-center gap-2 text-sm text-gray-500">
            <span className="badge bg-indigo-100 text-indigo-800">{TYPE_LABELS[company.company_type || 'unknown'] || company.company_type}</span>
            {company.verified ? (
              <span className="badge bg-green-100 text-green-800">Verified{company.last_verified ? ` ${new Date(company.last_verified).toLocaleDateString()}` : ''}</span>
            ) : (
              <span className="badge bg-gray-100 text-gray-800">Unverified</span>
            )}
            {completeness != null && <span className="badge bg-blue-100 text-blue-800">{completeness}% complete</span>}
          </p>
        </div>
        <button onClick={handleEnrich} disabled={enriching || !company.website} className="btn-secondary text-sm" title="Re-crawl the company website for contacts">
          {enriching ? 'Enriching…' : 'Enrich'}
        </button>
      </div>

      {msg && <div className="rounded-lg bg-blue-50 p-3 text-sm text-blue-700">{msg}</div>}

      {warnings.length > 0 && (
        <div className="rounded-lg border border-yellow-200 bg-yellow-50 p-4">
          <p className="flex items-center gap-2 text-sm font-medium text-yellow-800">
            <AlertTriangle className="h-4 w-4" /> Data-quality warnings
          </p>
          <ul className="mt-1 list-inside list-disc text-sm text-yellow-700">
            {warnings.map((w, i) => <li key={i}>{w}</li>)}
          </ul>
        </div>
      )}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* Overview */}
        <div className="card">
          <h2 className="text-lg font-semibold text-gray-900">Overview</h2>
          {company.description ? (
            <p className="mt-2 text-sm text-gray-700">{company.description}</p>
          ) : (
            <p className="mt-2 text-sm italic text-gray-400">Not available — no description published by the source.</p>
          )}
          <div className="mt-4 space-y-2 text-sm">
            {(company.city || company.country) && (
              <p className="flex items-center gap-2 text-gray-600">
                <MapPin className="h-4 w-4 text-gray-400" />
                {[company.address, company.city, company.country].filter(Boolean).join(', ')}
              </p>
            )}
            {company.website && (
              <p className="flex items-center gap-2">
                <Globe className="h-4 w-4 text-gray-400" />
                <a href={company.website} target="_blank" rel="noopener noreferrer" className="text-primary-600 hover:text-primary-700">{company.website}</a>
              </p>
            )}
            {(company.hall || company.booth) && (
              <p className="text-gray-600">Hall {company.hall || '?'} · Booth {company.booth || '?'}</p>
            )}
            {company.industry && <p className="text-gray-600">Industry: {company.industry}</p>}
          </div>
          <div className="mt-4 border-t border-gray-100 pt-3 text-xs text-gray-500">
            <p>Fair: {company.exhibition_name || '—'}</p>
            <p>First seen: {new Date(company.created_at).toLocaleString()} · Updated: {new Date(company.updated_at).toLocaleString()}</p>
          </div>
        </div>

        {/* Contacts */}
        <div className="card">
          <h2 className="text-lg font-semibold text-gray-900">Public contacts ({contacts.length})</h2>
          {contacts.length === 0 ? (
            <p className="mt-2 text-sm italic text-gray-400">Not available — no public contacts found yet.</p>
          ) : (
            <ul className="mt-2 space-y-3">
              {contacts.map((c) => (
                <li key={c.id} className="rounded-lg border border-gray-100 p-3 text-sm">
                  {c.business_email ? (
                    <p className="flex flex-wrap items-center gap-1">
                      <Mail className="h-4 w-4 text-gray-400" />{c.business_email}
                      {emailMatchesWebsite(c.business_email, company.website) ? (
                        <span className="rounded bg-green-100 px-1.5 py-0.5 text-[10px] font-medium text-green-800">domain ✓ verified pattern</span>
                      ) : (
                        <span className="rounded bg-yellow-100 px-1.5 py-0.5 text-[10px] font-medium text-yellow-800">unverified</span>
                      )}
                      <span className="text-xs text-gray-400">({c.email_source || 'directory'})</span>
                    </p>
                  ) : <p className="italic text-gray-400">No email — not available</p>}
                  {c.alternate_email && c.alternate_email !== c.business_email && (
                    <p className="mt-1 text-gray-500">Alt: {c.alternate_email}</p>
                  )}
                  <p className="mt-1 flex items-center gap-1">
                    <Phone className="h-4 w-4 text-gray-400" />{c.phone || <span className="italic text-gray-400">Not available</span>}
                  </p>
                  {c.whatsapp_number && (
                    <p className="mt-1 flex items-center gap-1 text-green-700">
                      <MessageSquare className="h-4 w-4" />{c.whatsapp_number}
                    </p>
                  )}
                  {c.email_source_url && (
                    <a href={c.email_source_url} target="_blank" rel="noopener noreferrer" className="mt-1 inline-flex items-center gap-1 text-xs text-primary-600 hover:text-primary-700">
                      <LinkIcon className="h-3 w-3" /> Found at source page
                    </a>
                  )}
                </li>
              ))}
            </ul>
          )}
          <Link to={`/leads?q=${encodeURIComponent(company.company_name)}`} className="btn-secondary mt-4 text-sm">
            Open associated lead
          </Link>
        </div>

        {/* Audited contact values (every discovery + exact source) */}
        {audit.items.length > 0 && (
          <div className="card">
            <h2 className="text-lg font-semibold text-gray-900">All discovered values ({audit.items.length})</h2>
            <p className="mt-1 text-xs text-gray-500">Every email/phone/WhatsApp ever found, with the exact page it came from. Nothing is overwritten.</p>
            <ul className="mt-3 space-y-2">
              {audit.items.map((it) => (
                <li key={it.id} className="flex flex-wrap items-center gap-2 rounded-lg border border-gray-100 p-2 text-sm">
                  <span className="badge bg-gray-100 text-gray-700">{it.contact_type}</span>
                  <span className="font-medium text-gray-900">{it.display_value}</span>
                  {it.is_primary && <span className="badge bg-blue-100 text-blue-800">primary</span>}
                  <span className="text-xs text-gray-400">{it.verification_status}{it.source_page_type ? ` · ${it.source_page_type}` : ''}</span>
                  {it.source_url && (
                    <a href={it.source_url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-xs text-primary-600 hover:text-primary-700">
                      <LinkIcon className="h-3 w-3" /> source
                    </a>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      {/* Products */}
      <div className="card">
        <h2 className="flex items-center gap-2 text-lg font-semibold text-gray-900">
          <Package className="h-5 w-5 text-primary-600" /> Products &amp; services ({products.length})
        </h2>
        {products.length === 0 ? (
          <p className="mt-2 text-sm italic text-gray-400">Not available — no products recorded for this company.</p>
        ) : (
          <ul className="mt-2 grid grid-cols-1 gap-2 md:grid-cols-2">
            {products.map((p) => (
              <li key={p.id} className="rounded-lg border border-gray-100 p-3">
                <p className="text-sm font-medium">{p.name}</p>
                {p.category && <p className="text-xs text-gray-500">Category: {p.category}</p>}
                {p.description && <p className="mt-1 text-xs text-gray-600">{p.description}</p>}
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Source pages */}
      <div className="card">
        <h2 className="text-lg font-semibold text-gray-900">Source pages</h2>
        <ul className="mt-2 space-y-1 text-sm">
          {[
            ['Exhibitor profile', company.exhibitor_url],
            ['Source URL', company.source_url],
            ['Enrichment source', company.enrichment_source_url],
          ].map(([label, url]) => (
            <li key={label}>
              <span className="text-gray-500">{label}: </span>
              {url ? (
                <a href={url} target="_blank" rel="noopener noreferrer" className="text-primary-600 hover:text-primary-700">
                  {url.length > 70 ? url.slice(0, 70) + '…' : url}
                </a>
              ) : <span className="italic text-gray-400">Not available</span>}
            </li>
          ))}
        </ul>
      </div>

      {/* Curation */}
      <div className="card">
        <h2 className="flex items-center gap-2 text-lg font-semibold text-gray-900">
          <ShieldCheck className="h-5 w-5 text-primary-600" /> Curation
        </h2>
        <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-3">
          <div>
            <label className="block text-sm font-medium text-gray-700">Company type</label>
            <select
              value={company.company_type || 'unknown'}
              onChange={(e) => saveField({ company_type: e.target.value })}
              className="input mt-1"
            >
              {Object.keys(TYPE_LABELS).map((t) => <option key={t} value={t}>{TYPE_LABELS[t]}</option>)}
            </select>
          </div>
          <div className="flex items-end">
            <button
              onClick={() => saveField({ verified: !company.verified })}
              disabled={saving}
              className="btn-secondary text-sm"
            >
              {company.verified ? 'Unmark verified' : 'Mark verified'}
            </button>
          </div>
        </div>
        <div className="mt-3">
          <label className="block text-sm font-medium text-gray-700">Internal notes</label>
          <textarea
            value={notes} onChange={(e) => setNotes(e.target.value)} rows={2}
            placeholder="Private notes about this company…" className="input mt-1"
          />
          <button onClick={() => saveField({ notes })} disabled={saving} className="btn-primary mt-2 text-sm">
            <Save className="mr-2 h-4 w-4" /> Save notes
          </button>
        </div>
      </div>
    </div>
  )
}
