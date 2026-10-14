import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
  LineChart,
  Line,
} from 'recharts'
import { getAnalytics, getByCountry, getByFair, getByCategory, getByType, getContactAvailability, getCompleteness, getDiscoveries, getCrawlingStats, getTrends } from '../services/api'
import { RefreshCw } from 'lucide-react'
import type { AnalyticsOverview } from '../types'

const COLORS = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899']

export default function Analytics() {
  const [data, setData] = useState<AnalyticsOverview | null>(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null)
  const [days, setDays] = useState(30)
  const [fairId, setFairId] = useState('')
  const [fairs, setFairs] = useState<{ source_id: number; fair: string; companies: number }[]>([])
  const [byCountry, setByCountry] = useState<{ label: string; count: number }[]>([])
  const [byCategory, setByCategory] = useState<{ label: string; companies: number }[]>([])
  const [byType, setByType] = useState<{ label: string; count: number }[]>([])
  const [availability, setAvailability] = useState<Record<string, number> | null>(null)
  const [completeness, setCompleteness] = useState<{ bucket: string; count: number }[]>([])
  const [discoveries, setDiscoveries] = useState<{ date: string; companies: number }[]>([])
  const [trends, setTrends] = useState<{ date: string; discovered: number; sent: number; replies: number; bounced: number; reply_rate: number }[]>([])
  const [crawling, setCrawling] = useState<{ total_jobs: number; by_status: Record<string, number>; successful: number; failed: number; running: number } | null>(null)

  useEffect(() => {
    loadAnalytics()
  }, [])

  const loadAnalytics = async () => {
    try {
      const stats = await getAnalytics()
      setData(stats)
      setUpdatedAt(new Date())
    } catch (err) {
      console.error('Failed to load analytics:', err)
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }

  const loadBreakdowns = async (d: number, fair: string) => {
    try {
      const sid = fair ? parseInt(fair) : undefined
      const [c, cat, t, av, comp, disc, cr, f, tr] = await Promise.all([
        getByCountry(sid), getByCategory(sid), getByType(sid),
        getContactAvailability(sid), getCompleteness(sid),
        getDiscoveries(d, sid), getCrawlingStats(), getByFair(),
        getTrends(d),
      ])
      setTrends(tr)
      setByCountry(c.slice(0, 10))
      setByCategory(cat.slice(0, 10))
      setByType(t)
      setAvailability(av)
      setCompleteness(comp)
      setDiscoveries(disc)
      setCrawling(cr)
      setFairs(f)
    } catch (err) {
      console.error('Failed to load breakdowns:', err)
    }
  }

  useEffect(() => {
    loadBreakdowns(days, fairId)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [days, fairId])

  const handleRefresh = async () => {
    setRefreshing(true)
    await loadAnalytics()
  }

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary-600 border-t-transparent" />
      </div>
    )
  }

  const funnelData = [
    { name: 'Companies', value: data?.total_companies ?? 0 },
    { name: 'Contacts', value: data?.total_contacts ?? 0 },
    { name: 'Emails Sent', value: data?.emails_sent ?? 0 },
    { name: 'Replies', value: data?.replies ?? 0 },
    { name: 'Interested', value: data?.interested ?? 0 },
    { name: 'Meetings', value: data?.meetings_booked ?? 0 },
    { name: 'Qualified', value: data?.qualified ?? 0 },
  ]

  const pieData = [
    { name: 'Emails Sent', value: data?.emails_sent ?? 0 },
    { name: 'Replies', value: data?.replies ?? 0 },
    { name: 'Interested', value: data?.interested ?? 0 },
    { name: 'Meetings', value: data?.meetings_booked ?? 0 },
  ]

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Analytics</h1>
          <p className="mt-1 text-sm text-gray-500">
            Track your outreach performance and conversion funnel.
            {updatedAt && <span className="ml-1">Updated {updatedAt.toLocaleTimeString()}.</span>}
            {' '}Replies refresh automatically every hour while Gmail is connected.
          </p>
        </div>
        <button onClick={handleRefresh} disabled={refreshing} className="btn-secondary text-sm">
          <RefreshCw className={`mr-2 h-4 w-4 ${refreshing ? 'animate-spin' : ''}`} />
          {refreshing ? 'Refreshing...' : 'Refresh'}
        </button>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <div className="card text-center">
          <p className="text-3xl font-bold text-primary-600">{data?.total_companies ?? 0}</p>
          <p className="text-sm text-gray-500">Companies</p>
        </div>
        <div className="card text-center">
          <p className="text-3xl font-bold text-green-600">{data?.emails_sent ?? 0}</p>
          <p className="text-sm text-gray-500">Emails Sent</p>
        </div>
        <div className="card text-center">
          <p className="text-3xl font-bold text-orange-600">{data?.replies ?? 0}</p>
          <p className="text-sm text-gray-500">Replies</p>
        </div>
        <div className="card text-center">
          <p className="text-3xl font-bold text-purple-600">{data?.meetings_booked ?? 0}</p>
          <p className="text-sm text-gray-500">Meetings</p>
        </div>
      </div>

      {/* Funnel Chart */}
      <div className="card">
        <h2 className="text-lg font-semibold text-gray-900">Conversion Funnel</h2>
        <div className="mt-4 h-80">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={funnelData}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="name" />
              <YAxis />
              <Tooltip />
              <Bar dataKey="value" fill="#3b82f6" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Reply Rate */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="card">
          <h2 className="text-lg font-semibold text-gray-900">Outreach Breakdown</h2>
          <div className="mt-4 h-64">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={pieData}
                  cx="50%"
                  cy="50%"
                  innerRadius={60}
                  outerRadius={80}
                  paddingAngle={5}
                  dataKey="value"
                >
                  {pieData.map((_, index) => (
                    <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="card">
          <h2 className="text-lg font-semibold text-gray-900">Key Metrics</h2>
          <div className="mt-4 space-y-4">
            <div className="flex justify-between">
              <span className="text-sm text-gray-600">Reply Rate</span>
              <span className="font-medium">{data?.reply_rate ?? 0}%</span>
            </div>
            <div className="flex justify-between">
              <span className="text-sm text-gray-600">Follow-ups Due</span>
              <span className="font-medium">{data?.followups_due ?? 0}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-sm text-gray-600">WhatsApp Sent</span>
              <span className="font-medium">{data?.whatsapp_sent ?? 0}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-sm text-gray-600">Emails Failed</span>
              <span className="font-medium text-red-600">{data?.emails_failed ?? 0}</span>
            </div>
          </div>
        </div>
      </div>

      {/* Filters for breakdowns */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
        <div>
          <label className="block text-sm font-medium text-gray-700">Fair</label>
          <select value={fairId} onChange={(e) => setFairId(e.target.value)} className="input mt-1 pr-8">
            <option value="">All fairs</option>
            {fairs.map((f) => (
              <option key={f.source_id} value={f.source_id}>{f.fair} ({f.companies.toLocaleString()})</option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700">Discoveries window</label>
          <select value={days} onChange={(e) => setDays(parseInt(e.target.value))} className="input mt-1 pr-8">
            <option value={7}>Last 7 days</option>
            <option value={30}>Last 30 days</option>
            <option value={90}>Last 90 days</option>
          </select>
        </div>
      </div>

      {/* Breakdowns */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="card">
          <h2 className="text-lg font-semibold text-gray-900">Companies by country (top 10)</h2>
          <div className="mt-4 h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={byCountry} layout="vertical">
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis type="number" />
                <YAxis dataKey="label" type="category" width={110} tick={{ fontSize: 11 }} />
                <Tooltip />
                <Bar dataKey="count" fill="#3b82f6" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="card">
          <h2 className="text-lg font-semibold text-gray-900">Companies by product category (top 10)</h2>
          <div className="mt-4 h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={byCategory} layout="vertical">
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis type="number" />
                <YAxis dataKey="label" type="category" width={110} tick={{ fontSize: 11 }} />
                <Tooltip />
                <Bar dataKey="companies" fill="#10b981" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="card">
          <h2 className="text-lg font-semibold text-gray-900">Companies by type</h2>
          <div className="mt-4 space-y-2">
            {byType.map((t) => (
              <div key={t.label} className="flex items-center justify-between text-sm">
                <span className="text-gray-600">{t.label}</span>
                <Link to={`/companies?type=${encodeURIComponent(t.label)}`} className="font-medium text-primary-600 hover:text-primary-700">
                  {t.count.toLocaleString()}
                </Link>
              </div>
            ))}
            {byType.length === 0 && <p className="text-sm text-gray-400">No data yet.</p>}
          </div>
          <h2 className="mt-6 text-lg font-semibold text-gray-900">Contact availability</h2>
          {availability ? (
            <div className="mt-2 space-y-2 text-sm">
              {[
                ['With email', availability.with_email, '/companies?has_email=true'],
                ['With phone', availability.with_phone, '/companies?has_phone=true'],
                ['With website', availability.with_website, '/companies?has_website=true'],
                ['With products', availability.with_products, '/companies'],
                ['Missing contact', availability.missing_contact, '/companies?has_email=false'],
              ].map(([label, value, to]) => (
                <div key={label as string} className="flex items-center justify-between">
                  <span className="text-gray-600">{label}</span>
                  <Link to={to as string} className="font-medium text-primary-600 hover:text-primary-700">
                    {(value as number)?.toLocaleString() ?? 0}
                  </Link>
                </div>
              ))}
            </div>
          ) : <p className="mt-2 text-sm text-gray-400">No data yet.</p>}
        </div>

        <div className="card">
          <h2 className="text-lg font-semibold text-gray-900">Discoveries per day</h2>
          <div className="mt-4 h-64">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={discoveries}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="date" tick={{ fontSize: 10 }} />
                <YAxis />
                <Tooltip />
                <Line type="monotone" dataKey="companies" stroke="#8b5cf6" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
          <h2 className="mt-6 text-lg font-semibold text-gray-900">Outreach trends per day</h2>
          <p className="mt-1 text-xs text-gray-500">Sent vs replies vs bounces. Reply rate uses each day's sent cohort.</p>
          <div className="mt-4 h-64">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={trends}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="date" tick={{ fontSize: 10 }} />
                <YAxis />
                <Tooltip />
                <Line type="monotone" dataKey="sent" stroke="#3b82f6" strokeWidth={2} dot={false} />
                <Line type="monotone" dataKey="replies" stroke="#10b981" strokeWidth={2} dot={false} />
                <Line type="monotone" dataKey="bounced" stroke="#ef4444" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
          <h2 className="mt-6 text-lg font-semibold text-gray-900">Data completeness</h2>
          <div className="mt-2 space-y-2 text-sm">
            {completeness.map((b) => (
              <div key={b.bucket} className="flex items-center justify-between">
                <span className="text-gray-600">{b.bucket}</span>
                <span className="font-medium">{b.count.toLocaleString()}</span>
              </div>
            ))}
          </div>
          <h2 className="mt-6 text-lg font-semibold text-gray-900">Crawl jobs</h2>
          {crawling ? (
            <div className="mt-2 space-y-2 text-sm">
              <div className="flex items-center justify-between">
                <span className="text-gray-600">Total jobs</span>
                <Link to="/jobs" className="font-medium text-primary-600 hover:text-primary-700">{crawling.total_jobs}</Link>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-gray-600">Successful</span>
                <Link to="/jobs" className="font-medium text-green-700">{crawling.successful}</Link>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-gray-600">Failed</span>
                <Link to="/jobs" className="font-medium text-red-600">{crawling.failed}</Link>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-gray-600">Running</span>
                <span className="font-medium">{crawling.running}</span>
              </div>
            </div>
          ) : <p className="mt-2 text-sm text-gray-400">No data yet.</p>}
        </div>
      </div>
    </div>
  )
}
