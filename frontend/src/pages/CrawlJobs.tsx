import { useState, useEffect, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { RefreshCw, RotateCcw, CheckCircle, XCircle, Loader2, Clock } from 'lucide-react'
import { getCrawlJobs, getCrawlJob, retryCrawlJob } from '../services/api'
import type { CrawlJob } from '../types'

const statusColors: Record<string, string> = {
  PENDING: 'bg-gray-100 text-gray-800',
  CRAWLING: 'bg-blue-100 text-blue-800',
  COMPLETED: 'bg-green-100 text-green-800',
  FAILED: 'bg-red-100 text-red-800',
}

export default function CrawlJobs() {
  const [jobs, setJobs] = useState<CrawlJob[]>([])
  const [loading, setLoading] = useState(true)
  const [selected, setSelected] = useState<CrawlJob | null>(null)
  const [actionMsg, setActionMsg] = useState('')

  const load = useCallback(async () => {
    try {
      setJobs(await getCrawlJobs({ limit: 100 }))
    } catch (err) {
      console.error('Failed to load crawl jobs:', err)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
    const t = setInterval(async () => {
      try {
        const list = await getCrawlJobs({ limit: 100 })
        setJobs(list)
        if (selected) {
          const fresh = list.find((j) => j.id === selected.id)
          if (fresh && fresh.status !== selected.status) {
            setSelected(await getCrawlJob(selected.id))
          }
        }
      } catch {
        // ignore polling blips
      }
    }, 10000)
    return () => clearInterval(t)
  }, [load, selected])

  const handleRetry = async (id: number) => {
    if (!window.confirm(`Retry crawl job #${id}? Already-saved companies are skipped, gaps are filled — no duplicates.`)) return
    try {
      const r = await retryCrawlJob(id)
      setActionMsg(`Retry started as job #${r.job_id}.`)
      await load()
    } catch (err: any) {
      setActionMsg(err?.response?.data?.detail || 'Retry failed.')
    }
    setTimeout(() => setActionMsg(''), 5000)
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
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Crawl Jobs</h1>
          <p className="mt-1 text-sm text-gray-500">Every crawl run, its progress, and safe retry.</p>
        </div>
        <button onClick={load} className="btn-secondary text-sm">
          <RefreshCw className="mr-2 h-4 w-4" /> Refresh
        </button>
      </div>

      {actionMsg && (
        <div className="rounded-lg bg-blue-50 p-3 text-sm text-blue-700">{actionMsg}</div>
      )}

      {jobs.length === 0 ? (
        <div className="card text-center text-sm text-gray-500">
          No crawl jobs yet. Start one from the <Link to="/import" className="underline">Add Website</Link> page.
        </div>
      ) : (
        <div className="card overflow-x-auto p-0">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Job</th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Source</th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Status</th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Discovered</th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Started</th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 bg-white">
              {jobs.map((job) => (
                <tr key={job.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 text-sm font-medium text-gray-900">#{job.id}</td>
                  <td className="px-4 py-3 text-sm text-gray-600">
                    <Link to={`/companies?source_id=${job.source_id}`} className="text-primary-600 hover:text-primary-700">
                      Source #{job.source_id}
                    </Link>
                    <p className="max-w-[280px] truncate text-xs text-gray-400">{job.url}</p>
                  </td>
                  <td className="px-4 py-3">
                    <span className={`badge ${statusColors[job.status] || 'bg-gray-100 text-gray-800'}`}>
                      {job.status === 'CRAWLING' ? <Loader2 className="mr-1 h-3 w-3 animate-spin" /> : null}
                      {job.status}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-600">{job.companies_discovered.toLocaleString()}</td>
                  <td className="px-4 py-3 text-sm text-gray-500">
                    {job.started_at ? new Date(job.started_at).toLocaleString() : '—'}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex gap-2">
                      <button onClick={() => getCrawlJob(job.id).then(setSelected).catch(() => {})} className="btn-secondary text-xs">
                        Details
                      </button>
                      {(job.status === 'FAILED' || job.status === 'COMPLETED') && (
                        <button onClick={() => handleRetry(job.id)} className="btn-secondary text-xs" title="Safe: existing rows are skipped, gaps filled">
                          <RotateCcw className="mr-1 h-3 w-3" /> Retry
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {selected && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={() => setSelected(null)}>
          <div className="w-full max-w-lg rounded-xl bg-white p-6" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-bold text-gray-900">Job #{selected.id}</h2>
              <button onClick={() => setSelected(null)} className="btn-secondary text-sm">Close</button>
            </div>
            <dl className="mt-4 grid grid-cols-2 gap-3 text-sm">
              <div><dt className="text-gray-500">Status</dt><dd className="font-medium">{selected.status}</dd></div>
              <div><dt className="text-gray-500">URL</dt><dd className="max-w-[220px] truncate font-medium" title={selected.url}>{selected.url}</dd></div>
              <div><dt className="text-gray-500">Pages visited</dt><dd className="font-medium">{selected.pages_visited}</dd></div>
              <div><dt className="text-gray-500">Companies discovered</dt><dd className="font-medium">{selected.companies_discovered}</dd></div>
              <div><dt className="text-gray-500">Records created</dt><dd className="font-medium">{selected.records_created}</dd></div>
              <div><dt className="text-gray-500">Duplicates flagged</dt><dd className="font-medium">{selected.duplicates_flagged}</dd></div>
              <div><dt className="text-gray-500">Started</dt><dd className="font-medium">{selected.started_at ? new Date(selected.started_at).toLocaleString() : '—'}</dd></div>
              <div><dt className="text-gray-500">Finished</dt><dd className="font-medium">{selected.finished_at ? new Date(selected.finished_at).toLocaleString() : '—'}</dd></div>
            </dl>
            {selected.errors.length > 0 && (
              <div className="mt-4">
                <p className="text-sm font-medium text-red-600">Errors ({selected.errors.length})</p>
                <ul className="mt-1 max-h-32 list-inside list-disc overflow-y-auto text-xs text-red-600">
                  {selected.errors.map((e, i) => <li key={i}>{e}</li>)}
                </ul>
              </div>
            )}
            <div className="mt-4 flex items-center gap-2 text-xs text-gray-500">
              {selected.status === 'COMPLETED' ? <CheckCircle className="h-4 w-4 text-green-600" /> : null}
              {selected.status === 'FAILED' ? <XCircle className="h-4 w-4 text-red-600" /> : null}
              {selected.status === 'CRAWLING' ? <Clock className="h-4 w-4 text-blue-600" /> : null}
              Retrying never duplicates — saved rows are skipped automatically.
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
