import { useState, useEffect, useCallback } from 'react'
import { useSearchParams, Link } from 'react-router-dom'
import { Search, RefreshCw, Upload, Filter, Globe, Mail, Users } from 'lucide-react'
import { getCompanies, getCompanyFilters, enrichCompany, enrichCompaniesBulk, importCSV, getDuplicates, resolveDuplicate } from '../services/api'
import type { Company, DuplicateCandidate } from '../types'
import { emailMatchesWebsite } from '../types'

const enrichmentStatusColors: Record<string, string> = {
  PENDING: 'bg-gray-100 text-gray-800',
  WEBSITE_FOUND: 'bg-blue-100 text-blue-800',
  ENRICHED: 'bg-green-100 text-green-800',
  NO_PUBLIC_CONTACT: 'bg-yellow-100 text-yellow-800',
  ACCESS_RESTRICTED: 'bg-red-100 text-red-800',
  RATE_LIMITED: 'bg-orange-100 text-orange-800',
  FAILED: 'bg-red-100 text-red-800',
}

export default function Companies() {
  const PAGE_SIZE = 50
  const [searchParams] = useSearchParams()
  const [companies, setCompanies] = useState<Company[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(0)
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState(searchParams.get('q') || '')
  const [statusFilter, setStatusFilter] = useState('')
  const [fairFilter, setFairFilter] = useState(searchParams.get('source_id') || '')
  const [countryFilter, setCountryFilter] = useState('')
  const [categoryFilter, setCategoryFilter] = useState(searchParams.get('category') || '')
  const [typeFilter, setTypeFilter] = useState(searchParams.get('type') || '')
  const [hasEmail, setHasEmail] = useState(searchParams.get('has_email') || '')
  const [hasPhone, setHasPhone] = useState(searchParams.get('has_phone') || '')
  const [hasWhatsapp, setHasWhatsapp] = useState('')
  const [contactable, setContactable] = useState('')
  const [lifecycle, setLifecycle] = useState('active')
  const [hasWebsite, setHasWebsite] = useState(searchParams.get('has_website') || '')
  const [verifiedFilter, setVerifiedFilter] = useState('')
  const [fairs, setFairs] = useState<{ id: number; name: string }[]>([])
  const [countries, setCountries] = useState<string[]>([])
  const [categories, setCategories] = useState<string[]>([])
  const [companyTypes, setCompanyTypes] = useState<string[]>([])
  const [dups, setDups] = useState<DuplicateCandidate[]>([])
  const [showDups, setShowDups] = useState(false)
  const [unresolvedOnly, setUnresolvedOnly] = useState(false)
  const [enriching, setEnriching] = useState<number | null>(null)
  const [bulkEnriching, setBulkEnriching] = useState(false)
  const [importing, setImporting] = useState(false)
  const [message, setMessage] = useState('')

  const loadCompanies = useCallback(async () => {
    try {
      const params: Record<string, string> = { limit: String(PAGE_SIZE), skip: String(page * PAGE_SIZE) }
      if (search) params.search = search
      if (statusFilter) params.enrichment_status = statusFilter
      if (fairFilter) params.source_id = fairFilter
      if (countryFilter) params.country = countryFilter
      if (categoryFilter) params.category = categoryFilter
      if (typeFilter) params.company_type = typeFilter
      if (hasEmail) params.has_email = hasEmail
      if (hasPhone) params.has_phone = hasPhone
      if (hasWhatsapp) params.has_whatsapp = hasWhatsapp
      if (contactable) params.contactable = contactable
      if (lifecycle !== 'active') params.lifecycle = lifecycle
      if (hasWebsite) params.has_website = hasWebsite
      if (verifiedFilter) params.verified = verifiedFilter
      if (unresolvedOnly) params.unresolved_only = 'true'
      const data = await getCompanies(params)
      setCompanies(data.items)
      setTotal(data.total)
    } catch (err) {
      console.error('Failed to load companies:', err)
    } finally {
      setLoading(false)
    }
  }, [search, statusFilter, fairFilter, countryFilter, categoryFilter, typeFilter, hasEmail, hasPhone, hasWhatsapp, contactable, lifecycle, hasWebsite, verifiedFilter, unresolvedOnly, page])

  useEffect(() => {
    getCompanyFilters().then((f) => {
      setFairs(f.sources)
      setCountries(f.countries)
      setCategories(f.categories)
      setCompanyTypes(f.company_types || [])
    }).catch(() => {})
    getDuplicates().then(setDups).catch(() => {})
  }, [])

  const resetPage = () => setPage(0)

  useEffect(() => {
    loadCompanies()
  }, [loadCompanies])

  const handleEnrich = async (id: number) => {
    setEnriching(id)
    try {
      await enrichCompany(id)
      await loadCompanies()
      setMessage('Company enriched successfully!')
      setTimeout(() => setMessage(''), 3000)
    } catch (err) {
      setMessage('Enrichment failed.')
      setTimeout(() => setMessage(''), 3000)
    } finally {
      setEnriching(null)
    }
  }

  const handleBulkEnrich = async () => {
    setBulkEnriching(true)
    try {
      const result = await enrichCompaniesBulk()
      await loadCompanies()
      setMessage(result.message)
      setTimeout(() => setMessage(''), 5000)
    } catch (err) {
      setMessage('Bulk enrichment failed.')
      setTimeout(() => setMessage(''), 3000)
    } finally {
      setBulkEnriching(false)
    }
  }

  const handleImportCSV = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    setImporting(true)
    try {
      await importCSV(file)
      await loadCompanies()
      setMessage('CSV import complete!')
      setTimeout(() => setMessage(''), 5000)
    } catch (err) {
      setMessage('CSV import failed.')
      setTimeout(() => setMessage(''), 3000)
    } finally {
      setImporting(false)
      e.target.value = ''
    }
  }

  const filtered = companies

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary-600 border-t-transparent" />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Companies</h1>
          <p className="mt-1 text-sm text-gray-500">
            All discovered companies with enrichment status and contact details.
          </p>
        </div>
        <div className="flex gap-2">
          <label className="btn-secondary cursor-pointer">
            <Upload className="mr-2 h-4 w-4" />
            {importing ? 'Importing...' : 'Import CSV'}
            <input type="file" accept=".csv" onChange={handleImportCSV} className="hidden" disabled={importing} />
          </label>
          <button
            onClick={handleBulkEnrich}
            disabled={bulkEnriching}
            className="btn-primary"
          >
            <RefreshCw className={`mr-2 h-4 w-4 ${bulkEnriching ? 'animate-spin' : ''}`} />
            {bulkEnriching ? 'Enriching...' : 'Bulk Enrich'}
          </button>
        </div>
      </div>

      {/* Filters: fair, country, product category, status */}
      <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
          <input
            type="text"
            placeholder="Search companies..."
            value={search}
            onChange={(e) => { setSearch(e.target.value); resetPage() }}
            className="input pl-10"
          />
        </div>
        <div className="relative">
          <Filter className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
          <select
            value={fairFilter}
            onChange={(e) => { setFairFilter(e.target.value); resetPage() }}
            className="input pl-10 pr-8"
            title="Fair directory"
          >
            <option value="">All fairs</option>
            {fairs.map((f) => (
              <option key={f.id} value={f.id}>{f.name}</option>
            ))}
          </select>
        </div>
        <select
          value={countryFilter}
          onChange={(e) => { setCountryFilter(e.target.value); resetPage() }}
          className="input pr-8"
          title="Country"
        >
          <option value="">All countries</option>
          {countries.map((c) => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>
        <select
          value={categoryFilter}
          onChange={(e) => { setCategoryFilter(e.target.value); resetPage() }}
          className="input pr-8"
          title="Product category"
        >
          <option value="">All categories</option>
          {categories.map((c) => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>
        <select
          value={typeFilter}
          onChange={(e) => { setTypeFilter(e.target.value); resetPage() }}
          className="input pr-8"
          title="Company type"
        >
          <option value="">All types</option>
          {companyTypes.map((c) => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>
        <select
          value={hasEmail}
          onChange={(e) => { setHasEmail(e.target.value); resetPage() }}
          className="input pr-8"
          title="Has email?"
        >
          <option value="">Email: any</option>
          <option value="true">Has email</option>
          <option value="false">No email</option>
        </select>
        <select
          value={hasPhone}
          onChange={(e) => { setHasPhone(e.target.value); resetPage() }}
          className="input pr-8"
          title="Has phone?"
        >
          <option value="">Phone: any</option>
          <option value="true">Has phone</option>
          <option value="false">No phone</option>
        </select>
        <select
          value={hasWebsite}
          onChange={(e) => { setHasWebsite(e.target.value); resetPage() }}
          className="input pr-8"
          title="Has website?"
        >
          <option value="">Website: any</option>
          <option value="true">Has website</option>
          <option value="false">No website</option>
        </select>
        <select
          value={hasWhatsapp}
          onChange={(e) => { setHasWhatsapp(e.target.value); resetPage() }}
          className="input pr-8"
          title="Has WhatsApp?"
        >
          <option value="">WhatsApp: any</option>
          <option value="true">Has WhatsApp</option>
          <option value="false">No WhatsApp</option>
        </select>
        <select
          value={contactable}
          onChange={(e) => { setContactable(e.target.value); resetPage() }}
          className="input pr-8"
          title="Contactable?"
        >
          <option value="">Contact: any</option>
          <option value="true">Contactable</option>
          <option value="false">No usable contact</option>
        </select>
        <select
          value={lifecycle}
          onChange={(e) => { setLifecycle(e.target.value); resetPage() }}
          className="input pr-8"
          title="Record lifecycle"
        >
          <option value="active">Active prospects</option>
          <option value="all">All incl. excluded</option>
          <option value="excluded">Excluded (no contact)</option>
          <option value="archived">Archived</option>
          <option value="merged">Merged</option>
        </select>
        <select
          value={verifiedFilter}
          onChange={(e) => { setVerifiedFilter(e.target.value); resetPage() }}
          className="input pr-8"
          title="Verified?"
        >
          <option value="">Verified: any</option>
          <option value="true">Verified</option>
          <option value="false">Unverified</option>
        </select>
        <div className="relative">
          <select
            value={statusFilter}
            onChange={(e) => { setStatusFilter(e.target.value); resetPage() }}
            className="input pr-8"
          >
            <option value="">All Status</option>
            {Object.keys(enrichmentStatusColors).map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
        </div>
        <label className="flex items-center gap-2 text-sm text-gray-600">
          <input
            type="checkbox"
            checked={unresolvedOnly}
            onChange={(e) => { setUnresolvedOnly(e.target.checked); resetPage() }}
            className="rounded border-gray-300"
          />
          Unresolved only
        </label>
      </div>

      {/* Message */}
      {message && (
        <div className="rounded-lg bg-blue-50 p-3 text-sm text-blue-700">
          {message}
        </div>
      )}

      {/* Stats */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <div className="card text-center">
          <p className="text-2xl font-bold text-gray-900">{total.toLocaleString()}</p>
          <p className="text-sm text-gray-500">Total</p>
        </div>
        <div className="card text-center">
          <p className="text-2xl font-bold text-green-600">
            {companies.filter((c) => c.enrichment_status === 'ENRICHED').length}
          </p>
          <p className="text-sm text-gray-500">Enriched</p>
        </div>
        <div className="card text-center">
          <p className="text-2xl font-bold text-gray-600">
            {companies.filter((c) => c.enrichment_status === 'PENDING').length}
          </p>
          <p className="text-sm text-gray-500">Pending</p>
        </div>
        <div className="card text-center">
          <p className="text-2xl font-bold text-red-600">
            {companies.filter((c) => c.enrichment_status === 'FAILED' || c.enrichment_status === 'ACCESS_RESTRICTED').length}
          </p>
          <p className="text-sm text-gray-500">Failed/Restricted</p>
        </div>
      </div>

      {/* Duplicate review queue (flagged, never auto-merged) */}
      {dups.length > 0 && (
        <div className="card">
          <button
            onClick={() => setShowDups(!showDups)}
            className="flex w-full items-center gap-2 text-left text-sm font-medium text-gray-900"
          >
            <Users className="h-4 w-4 text-yellow-600" />
            {dups.length} possible duplicate{dups.length > 1 ? 's' : ''} awaiting review
            <span className="text-xs text-gray-400">({showDups ? 'hide' : 'show'})</span>
          </button>
          {showDups && (
            <ul className="mt-3 space-y-2">
              {dups.slice(0, 20).map((d) => (
                <li key={d.id} className="flex flex-wrap items-center gap-2 rounded-lg border border-yellow-100 bg-yellow-50/50 p-2 text-xs">
                  <Link to={`/companies/${d.company_a?.id}`} className="font-medium text-primary-600 hover:text-primary-700">
                    {d.company_a?.name}
                  </Link>
                  <span className="text-gray-400">≈</span>
                  <Link to={`/companies/${d.company_b?.id}`} className="font-medium text-primary-600 hover:text-primary-700">
                    {d.company_b?.name}
                  </Link>
                  <span className="rounded bg-yellow-100 px-1.5 py-0.5 text-[10px] text-yellow-800">
                    {d.match_type} · {Math.round(d.confidence * 100)}%
                  </span>
                  <button
                    onClick={async () => {
                      await resolveDuplicate(d.id, 'dismissed')
                      setDups(dups.filter((x) => x.id !== d.id))
                    }}
                    className="btn-secondary ml-auto text-xs"
                  >
                    Dismiss
                  </button>
                  <button
                    onClick={async () => {
                      await resolveDuplicate(d.id, 'reviewed')
                      setDups(dups.filter((x) => x.id !== d.id))
                    }}
                    className="btn-secondary text-xs"
                  >
                    Confirm match
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {/* Company Table: company details | products | contact */}
      {filtered.length === 0 ? (
        <div className="card text-center text-sm text-gray-500">
          No companies found matching your criteria.
        </div>
      ) : (
        <div className="card overflow-x-auto p-0">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Company</th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Products</th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Contact</th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Status</th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 bg-white">
              {filtered.map((company) => {
                const contacts = company.contacts || []
                const contact = contacts.find((c) => c.business_email || c.phone || c.whatsapp_number)
                const email = contact?.business_email
                const match = emailMatchesWebsite(email, company.website)
                const products = company.products || []
                return (
                  <tr key={company.id} className="hover:bg-gray-50">
                    <td className="px-4 py-3 align-top">
                      <Link to={`/companies/${company.id}`} className="text-left text-sm font-medium text-primary-600 hover:text-primary-700">
                        {company.company_name}
                      </Link>
                      <p className="mt-0.5 flex flex-wrap items-center gap-1">
                        {company.company_type && company.company_type !== 'unknown' && (
                          <span className="rounded bg-indigo-50 px-1.5 py-0.5 text-[10px] font-medium text-indigo-700">{company.company_type}</span>
                        )}
                        {company.verified ? (
                          <span className="rounded bg-green-100 px-1.5 py-0.5 text-[10px] font-medium text-green-800">verified</span>
                        ) : null}
                        {company.completeness != null && (
                          <span className="rounded bg-blue-50 px-1.5 py-0.5 text-[10px] font-medium text-blue-700" title="Data completeness score">
                            {Math.round(company.completeness * 100)}%
                          </span>
                        )}
                      </p>
                      <p className="mt-0.5 text-xs text-gray-500">
                        {[company.city, company.country].filter(Boolean).join(', ')}
                        {(company.hall || company.booth) && ` · Hall ${company.hall || '?'} Booth ${company.booth || '?'}`}
                      </p>
                      {company.website && (
                        <a href={company.website} target="_blank" rel="noopener noreferrer" className="mt-0.5 inline-flex items-center gap-1 text-xs text-blue-600 hover:text-blue-700">
                          <Globe className="h-3 w-3" />{company.website.replace(/^https?:\/\//, '').split('/')[0]}
                        </a>
                      )}
                      {company.description && (
                        <p className="mt-1 line-clamp-2 max-w-md text-xs text-gray-500">{company.description}</p>
                      )}
                    </td>
                    <td className="px-4 py-3 align-top">
                      {products.length === 0 ? (
                        <span className="text-xs text-gray-400">—</span>
                      ) : (
                        <div>
                          <p className="text-xs font-medium text-gray-700">{products.length} product{products.length > 1 ? 's' : ''}</p>
                          <ul className="mt-1 list-inside list-disc text-xs text-gray-500">
                            {products.slice(0, 3).map((p) => <li key={p.id} className="truncate max-w-[220px]">{p.name}</li>)}
                          </ul>
                          {products.length > 3 && <p className="text-xs text-gray-400">+{products.length - 3} more</p>}
                        </div>
                      )}
                    </td>
                    <td className="px-4 py-3 align-top">
                      {!contact ? (
                        <span className="text-xs text-gray-400">No contact</span>
                      ) : (
                        <div className="space-y-1 text-xs">
                          {email && (
                            <div>
                              <span className="inline-flex items-center gap-1 text-gray-700">
                                <Mail className="h-3 w-3 text-gray-400" />{email}
                              </span>
                              {match ? (
                                <span className="ml-1 rounded bg-green-100 px-1.5 py-0.5 text-[10px] font-medium text-green-800">domain ✓</span>
                              ) : (
                                <span className="ml-1 rounded bg-yellow-100 px-1.5 py-0.5 text-[10px] font-medium text-yellow-800" title="Email domain differs from company website">unverified</span>
                              )}
                            </div>
                          )}
                          {contact.alternate_email && contact.alternate_email !== email && (
                            <p className="text-gray-500" title={contact.email_source === 'website' ? 'Directory email' : 'Website email'}>
                              alt: {contact.alternate_email}
                            </p>
                          )}
                          {contact.phone && <p className="text-gray-700">{contact.phone}</p>}
                          {contact.whatsapp_number && <p className="text-green-700">WA: {contact.whatsapp_number}</p>}
                        </div>
                      )}
                    </td>
                    <td className="px-4 py-3 align-top">
                      {company.enrichment_status && (
                        <span className={`badge ${enrichmentStatusColors[company.enrichment_status] || 'bg-gray-100 text-gray-800'}`}>
                          {company.enrichment_status}
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3 align-top">
                      <button
                        onClick={() => handleEnrich(company.id)}
                        disabled={enriching === company.id || !company.website}
                        className="btn-secondary text-xs"
                        title={company.website ? 'Enrich from company website' : 'No website to enrich from'}
                      >
                        <RefreshCw className={`mr-1 h-3 w-3 ${enriching === company.id ? 'animate-spin' : ''}`} />
                        {enriching === company.id ? '...' : 'Enrich'}
                      </button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
      {/* Pager */}
      {total > PAGE_SIZE && (
        <div className="flex items-center justify-between">
          <p className="text-xs text-gray-500">
            Page {page + 1} of {Math.max(1, Math.ceil(total / PAGE_SIZE))} ({total.toLocaleString()} companies)
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
              onClick={() => setPage((p) => ((p + 1) * PAGE_SIZE < total ? p + 1 : p))}
              disabled={(page + 1) * PAGE_SIZE >= total}
              className="btn-secondary text-xs"
            >
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
