import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Globe, Play, Loader2, CheckCircle, AlertCircle, Info } from 'lucide-react'
import { createSource, triggerCrawl, getCrawlStatus } from '../services/api'

function looksBlocked(url: string): string | null {
  let host = ''
  try {
    host = new URL(url).hostname.toLowerCase()
  } catch {
    return 'That is not a valid http(s) URL.'
  }
  if (!['http:', 'https:'].includes(new URL(url).protocol)) return 'Only http(s) URLs are allowed.'
  if (['localhost', '127.0.0.1', '0.0.0.0', '::1'].some((h) => host === h || host.endsWith('.local'))) {
    return 'Local/private addresses are blocked for safety.'
  }
  if (/^(10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)/.test(host)) return 'Private network addresses are blocked.'
  return null
}

export default function AddWebsite() {
  const [url, setUrl] = useState('')
  const [fairName, setFairName] = useState('')
  const [category, setCategory] = useState('')
  const [maxCompanies, setMaxCompanies] = useState('100')
  const [startFrom, setStartFrom] = useState('')
  const [onlyComplete, setOnlyComplete] = useState(true)
  const [skipWebsites, setSkipWebsites] = useState(false)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [progress, setProgress] = useState('')
  const [jobId, setJobId] = useState<number | null>(null)
  const [doneSourceId, setDoneSourceId] = useState<number | null>(null)
  const [doneCategory, setDoneCategory] = useState('')

  const start = async () => {
    setMessage('')
    setError('')
    setJobId(null)
    const blocked = looksBlocked(url)
    if (blocked) {
      setError(blocked)
      return
    }
    setBusy(true)
    setProgress('Creating source…')
    try {
      const source = await createSource({ name: fairName || url, url })
      setProgress('Crawl job started — discovering pages…')
      const res = await triggerCrawl(source.id, {
        max_profiles: maxCompanies ? parseInt(maxCompanies) : undefined,
        skip_website_crawl: skipWebsites,
        min_quality: onlyComplete ? 0.2 : 0.0,
        profile_offset: startFrom ? parseInt(startFrom) : 0,
      })
      setJobId(res.job_id)
      // Poll this job to completion (up to ~20 min), then report honestly.
      for (let i = 0; i < 240; i++) {
        await new Promise((r) => setTimeout(r, 5000))
        try {
          const st = await getCrawlStatus(source.id)
          if (st.status === 'COMPLETED') {
            setProgress('')
            setDoneSourceId(source.id)
            setDoneCategory(category)
            setMessage(`Crawl complete!`)
            break
          }
          if (st.status === 'FAILED') {
            setProgress('')
            setError('Crawl failed — the site may block automated access. Check Crawl Jobs for details.')
            break
          }
          const s = (i + 1) * 5
          setProgress(`Crawling… (${Math.floor(s / 60)}m ${s % 60}s elapsed)`)
        } catch {
          // ignore polling blips
        }
      }
      setUrl('')
    } catch (err: any) {
      setProgress('')
      setError(err?.response?.data?.detail || 'Failed to start. The source may already be crawling (duplicates blocked).')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Add Website / Import Exhibitors</h1>
        <p className="mt-1 text-sm text-gray-500">
          Enter a company website, fair exhibitor directory, or profile page. Public pages only —
          logins, CAPTCHAs and private addresses are never bypassed.
        </p>
      </div>

      <div className="card space-y-4">
        <div>
          <label className="block text-sm font-medium text-gray-700">Website / directory URL *</label>
          <input
            type="url" value={url} onChange={(e) => setUrl(e.target.value)}
            placeholder="https://example-fair.com/exhibitors"
            className="input mt-1" onKeyDown={(e) => e.key === 'Enter' && start()}
          />
        </div>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div>
            <label className="block text-sm font-medium text-gray-700">Exhibition / fair name (optional)</label>
            <input
              type="text" value={fairName} onChange={(e) => setFairName(e.target.value)}
              placeholder="e.g. Ambiente 2027" className="input mt-1"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700">Product category (optional)</label>
            <input
              type="text" value={category} onChange={(e) => setCategory(e.target.value)}
              placeholder="e.g. Furniture" className="input mt-1"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700">Max companies (limit)</label>
            <div className="mt-1 flex flex-wrap items-center gap-2">
              {[50, 100, 500].map((n) => (
                <button
                  key={n}
                  type="button"
                  onClick={() => setMaxCompanies(String(n))}
                  className={`rounded-lg border px-3 py-1.5 text-sm ${maxCompanies === String(n) ? 'border-primary-600 bg-primary-50 text-primary-700' : 'border-gray-300 text-gray-600'}`}
                >
                  {n}
                </button>
              ))}
              <button
                type="button"
                onClick={() => setMaxCompanies('')}
                className={`rounded-lg border px-3 py-1.5 text-sm ${maxCompanies === '' ? 'border-primary-600 bg-primary-50 text-primary-700' : 'border-gray-300 text-gray-600'}`}
              >
                All
              </button>
            </div>
            <p className="mt-1 text-xs text-gray-500">Stops after N companies saved. Blank = entire directory.</p>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700">Start from # (continue chunks)</label>
            <input
              type="number" min={0} value={startFrom}
              onChange={(e) => setStartFrom(e.target.value)}
              placeholder="0 = from the start"
              className="input mt-1"
            />
            <p className="mt-1 text-xs text-gray-500">E.g. 100 with limit 100 crawls profiles 101–200. Re-runs never duplicate.</p>
          </div>
          <label className="flex items-center gap-2 text-sm text-gray-600" title="Skips name-only rows; keeps companies with contact, product, website or description details">
            <input type="checkbox" checked={onlyComplete} onChange={(e) => setOnlyComplete(e.target.checked)} className="rounded border-gray-300" />
            Only save companies with proper details
          </label>
          <label className="flex items-center gap-2 text-sm text-gray-600">
            <input type="checkbox" checked={skipWebsites} onChange={(e) => setSkipWebsites(e.target.checked)} className="rounded border-gray-300" />
            Skip company websites (directory data only — faster)
          </label>
        </div>

        <button onClick={start} disabled={busy || !url} className="btn-primary">
          {busy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Play className="mr-2 h-4 w-4" />}
          {busy ? 'Crawling…' : 'Start crawl'}
        </button>

        {progress && (
          <div className="flex items-center gap-2 rounded-lg bg-blue-50 p-3 text-sm text-blue-700">
            <Loader2 className="h-4 w-4 animate-spin" />{progress}
          </div>
        )}
        {message && (
          <div className="flex items-center gap-2 rounded-lg bg-green-50 p-3 text-sm text-green-700">
            <CheckCircle className="h-4 w-4" />{message}
            {jobId && <Link to="/jobs" className="ml-2 underline">View job #{jobId}</Link>}
            {doneSourceId && (
              <Link to={`/companies?source_id=${doneSourceId}${doneCategory ? `&category=${encodeURIComponent(doneCategory)}` : ''}`} className="ml-2 underline">
                View results
              </Link>
            )}
          </div>
        )}
        {error && (
          <div className="flex items-center gap-2 rounded-lg bg-red-50 p-3 text-sm text-red-700">
            <AlertCircle className="h-4 w-4" />{error}
          </div>
        )}
        <div className="flex items-start gap-2 rounded-lg bg-gray-50 p-3 text-xs text-gray-500">
          <Info className="mt-0.5 h-4 w-4 shrink-0" />
          <span>Results save incrementally — a failed crawl keeps what it found, and retrying never duplicates. Track progress on the <Link to="/jobs" className="underline">Crawl Jobs</Link> page.</span>
        </div>
      </div>

      <div className="card">
        <h2 className="flex items-center gap-2 text-lg font-semibold text-gray-900">
          <Globe className="h-5 w-5 text-primary-600" /> What gets extracted
        </h2>
        <ul className="mt-2 list-inside list-disc space-y-1 text-sm text-gray-600">
          <li>Company name, description, type, products &amp; categories</li>
          <li>Official website, public email / phone / WhatsApp (domain-validated)</li>
          <li>Only <strong>validated</strong> emails are stored — bad syntax and tracker addresses are dropped</li>
          <li>Thin name-only rows are skipped when “proper details” is on</li>
          <li>Country, city, address, booth/hall, fair name, source URLs</li>
          <li>Only published facts — missing data stays empty, never invented</li>
        </ul>
      </div>
    </div>
  )
}
