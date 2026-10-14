import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { Database, RefreshCw, ExternalLink, AlertCircle } from 'lucide-react'
import { getSources, getCrawlStatus } from '../services/api'
import type { Source } from '../types'

export default function Sources() {
  const [sources, setSources] = useState<Source[]>([])
  const [loading, setLoading] = useState(true)
  const [counts, setCounts] = useState<Record<number, number>>({})

  const load = async () => {
    try {
      const list = await getSources()
      setSources(list)
      // Per-source company counts via filtered companies endpoint
      const { getCompanies } = await import('../services/api')
      const entries: Record<number, number> = {}
      await Promise.all(list.map(async (s) => {
        try {
          const r = await getCompanies({ source_id: String(s.id), limit: '1' })
          entries[s.id] = r.total
        } catch {
          entries[s.id] = 0
        }
      }))
      setCounts(entries)
    } catch (err) {
      console.error('Failed to load sources:', err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

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
          <h1 className="text-2xl font-bold text-gray-900">Sources</h1>
          <p className="mt-1 text-sm text-gray-500">Fair directories and website sources with crawl history.</p>
        </div>
        <div className="flex gap-2">
          <Link to="/import" className="btn-primary text-sm">Add Website</Link>
          <button onClick={load} className="btn-secondary text-sm">
            <RefreshCw className="mr-2 h-4 w-4" /> Refresh
          </button>
        </div>
      </div>

      {sources.length === 0 ? (
        <div className="card text-center text-sm text-gray-500">
          No sources yet. <Link to="/import" className="underline">Add your first website</Link>.
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          {sources.map((s) => (
            <SourceCard key={s.id} source={s} count={counts[s.id] ?? 0} />
          ))}
        </div>
      )}
    </div>
  )
}

function SourceCard({ source, count }: { source: Source; count: number }) {
  const [status, setStatus] = useState<string>(source.status)
  useEffect(() => {
    let live = true
    getCrawlStatus(source.id).then((st) => { if (live) setStatus(st.status) }).catch(() => {})
    return () => { live = false }
  }, [source.id])

  return (
    <div className="card">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="truncate font-medium text-gray-900">{source.name}</h2>
          <a href={source.url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-xs text-blue-600 hover:text-blue-700">
            {source.url.length > 60 ? source.url.slice(0, 60) + '…' : source.url}
            <ExternalLink className="h-3 w-3" />
          </a>
        </div>
        <span className={`badge shrink-0 ${status === 'COMPLETED' ? 'bg-green-100 text-green-800' : status === 'CRAWLING' ? 'bg-blue-100 text-blue-800' : status === 'FAILED' ? 'bg-red-100 text-red-800' : 'bg-gray-100 text-gray-800'}`}>
          {status}
        </span>
      </div>
      <div className="mt-3 flex items-center gap-4 text-sm text-gray-600">
        <span className="flex items-center gap-1">
          <Database className="h-4 w-4 text-gray-400" />
          {count.toLocaleString()} companies
        </span>
        <span className="text-xs text-gray-400">
          Last crawl: {source.last_crawled_at ? new Date(source.last_crawled_at).toLocaleString() : 'never'}
        </span>
      </div>
      {status === 'FAILED' && (
        <p className="mt-2 flex items-center gap-1 text-xs text-red-600">
          <AlertCircle className="h-3 w-3" /> Last run failed — retry safely from Crawl Jobs (no duplicates).
        </p>
      )}
      <div className="mt-3 flex gap-2">
        <Link to={`/companies?source_id=${source.id}`} className="btn-secondary text-xs">View companies</Link>
        <Link to="/jobs" className="btn-secondary text-xs">Crawl history</Link>
      </div>
    </div>
  )
}
