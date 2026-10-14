import { useState, useEffect } from 'react'
import { Save, Building2, Mail, Calendar, MessageSquare, Upload, Clock, Shield, LogIn, LogOut, CheckCircle, AlertCircle, RefreshCw } from 'lucide-react'
import { importCSV, getGoogleLogin, getGoogleStatus, disconnectGoogle, testGmailSend, getGoogleClient, saveGoogleClient, selectGoogleAccount, getAutoSendState, updateAutomation, checkReplies, getOutreachSummary } from '../services/api'

export default function Settings() {
  const [seller, setSeller] = useState({
    business_name: 'New Look Impex',
    business_description: 'Manufacturer and exporter of metal urlis, metal diyas, decorative metal lanterns, festival decor, home decor, copper and brass handicrafts.',
    products: 'Metal urlis, Metal diyas, Decorative metal lanterns, Festival decor, Home decor, Copper and brass handicrafts',
    country: 'India',
    city: 'Moradabad',
    website: '',
    catalogue_url: '',
    meeting_url: '',
    sender_name: '',
  })

  const [settings, setSettings] = useState({
    followup_delay_hours: 24,
    meeting_duration_minutes: 30,
    email_enabled: true,
    whatsapp_enabled: false,
    calendar_enabled: false,
    crawl_delay_seconds: 2.0,
  })

  const [saved, setSaved] = useState(false)
  const [importing, setImporting] = useState(false)
  const [message, setMessage] = useState('')
  const [google, setGoogle] = useState<{ connected: boolean; email: string | null; oauth_configured: boolean; accounts: { id: number; email: string; active: boolean; access_ok?: boolean; last_verified_at?: string | null }[] }>({ connected: false, email: null, oauth_configured: false, accounts: [] })
  const [syncing, setSyncing] = useState(false)
  const [googleMsg, setGoogleMsg] = useState('')
  const [testEmail, setTestEmail] = useState('')
  const [oauthForm, setOauthForm] = useState({ client_id: '', client_secret: '' })
  const [oauthState, setOauthState] = useState({ client_id_set: false, from_ui: false })
  const [autoSend, setAutoSend] = useState({ enabled: false, daily_limit: 100, last_run_date: null as string | null, last_sent: 0, last_status: 'idle' })

  const reloadGoogle = async () => {
    try {
      const g = await getGoogleStatus()
      setGoogle({ connected: g.connected, email: g.email, oauth_configured: g.oauth_configured, accounts: g.accounts || [] })
    } catch {}
    try {
      const o = await getGoogleClient()
      setOauthState({ client_id_set: o.client_id_set, from_ui: o.from_ui })
    } catch {}
    try {
      const a = await getAutoSendState()
      setAutoSend({ enabled: a.enabled, daily_limit: a.daily_limit, last_run_date: a.last_run_date, last_sent: a.last_sent, last_status: a.last_status })
    } catch {}
  }

  const handleSaveOauth = async () => {
    try {
      await saveGoogleClient({ client_id: oauthForm.client_id, client_secret: oauthForm.client_secret || undefined })
      setOauthForm({ client_id: '', client_secret: '' })
      setGoogleMsg('OAuth client saved. Now Connect with Google.')
      await reloadGoogle()
    } catch {
      setGoogleMsg('Failed to save OAuth client.')
    }
  }

  const handleSelectAccount = async (id: number) => {
    await selectGoogleAccount(id)
    await reloadGoogle()
  }

  const handleDisconnectAccount = async (id: number) => {
    await disconnectGoogle(id)
    setGoogleMsg('Account removed.')
    await reloadGoogle()
  }

  useEffect(() => {
    reloadGoogle()
    const params = new URLSearchParams(window.location.search)
    if (params.get('google') === 'connected') {
      const verified = params.get('verified')
      setGoogleMsg(
        verified === '1'
          ? 'Gmail connected and access verified — syncing replies now…'
          : verified === '0'
            ? 'Gmail connected, but the inbox check failed — try Send test below.'
            : 'Gmail connected successfully!'
      )
      getGoogleStatus().then(setGoogle).catch(() => {})
      // Immediately pull replies + outreach totals so every page shows
      // the new account's data without manual refreshes.
      setSyncing(true)
      checkReplies()
        .then((r) => setGoogleMsg(`Gmail live — ${r.checked} messages checked, ${r.matched} replies matched.`))
        .catch(() => {})
        .finally(() => { setSyncing(false); reloadGoogle() })
      getOutreachSummary().catch(() => {})
    } else if (params.get('google') === 'error') {
      const reason = params.get('reason')
      setGoogleMsg(
        reason === 'denied'
          ? 'Access was denied on the Google screen. Please try again and click Allow.'
          : reason === 'token'
            ? 'Google rejected the login handshake. Check the OAuth client + redirect URI.'
            : reason === 'profile'
              ? 'Login succeeded but reading your Gmail address failed. Try connecting again.'
              : 'Gmail connection failed. Check the OAuth setup.'
      )
    }
  }, [])

  const handleSave = () => {
    setSaved(true)
    setTimeout(() => setSaved(false), 3000)
  }

  const handleImportCSV = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    setImporting(true)
    try {
      const result = await importCSV(file)
      setMessage(result.message)
      setTimeout(() => setMessage(''), 5000)
    } catch (err) {
      setMessage('CSV import failed.')
      setTimeout(() => setMessage(''), 3000)
    } finally {
      setImporting(false)
      e.target.value = ''
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Settings</h1>
          <p className="mt-1 text-sm text-gray-500">
            Configure your seller profile, automation settings, and data import.
          </p>
        </div>
      </div>

      {/* Google Login — any Gmail, no .env needed */}
      <div className="card">
        <div className="flex items-center gap-2">
          <LogIn className="h-5 w-5 text-primary-600" />
          <h2 className="text-lg font-semibold text-gray-900">Google Login</h2>
        </div>
        <p className="mt-1 text-sm text-gray-500">
          Anyone can connect their own Gmail here — no server setup. Paste the
          OAuth client once below, then Connect with Google. Sending, replies
          and auto-send use the selected account.
        </p>
        <div className="mt-4 space-y-3">
          <div className="rounded-lg border border-gray-200 p-3">
            <p className="text-sm font-medium text-gray-700">OAuth client (paste once — replaces .env)</p>
            <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
              <input
                type="text" placeholder="Client ID (...apps.googleusercontent.com)"
                value={oauthForm.client_id}
                onChange={(e) => setOauthForm({ ...oauthForm, client_id: e.target.value })}
                className="input text-sm"
              />
              <input
                type="password" placeholder="Client secret (leave blank to keep saved)"
                value={oauthForm.client_secret}
                onChange={(e) => setOauthForm({ ...oauthForm, client_secret: e.target.value })}
                className="input text-sm"
              />
            </div>
            <div className="mt-2 flex items-center gap-2">
              <button onClick={handleSaveOauth} className="btn-secondary text-sm">Save client</button>
              {oauthState.client_id_set && (
                <span className="text-xs text-green-700">client saved {oauthState.from_ui ? '(from here)' : '(from server env)'}</span>
              )}
            </div>
          </div>
          {google.accounts.length > 0 ? (
            <div className="space-y-2">
              {google.accounts.map((a) => (
                <div key={a.id} className={`flex items-center justify-between rounded-lg border p-2 text-sm ${a.active ? 'border-green-300 bg-green-50' : 'border-gray-200'}`}>
                  <span className="flex items-center gap-2">
                    <CheckCircle className={`h-4 w-4 ${a.active ? 'text-green-600' : 'text-gray-300'}`} />
                    {a.email}
                    {a.active && <span className="badge bg-green-100 text-green-800">sending</span>}
                    {a.access_ok
                      ? <span className="badge bg-blue-100 text-blue-800" title={a.last_verified_at ? `Verified ${new Date(a.last_verified_at).toLocaleString()}` : 'Access verified'}>verified</span>
                      : <span className="badge bg-yellow-100 text-yellow-800" title="Login saved but inbox access not confirmed yet">unverified</span>}
                  </span>
                  <div className="flex gap-2">
                    {!a.active && (
                      <button onClick={() => handleSelectAccount(a.id)} className="btn-secondary text-xs">Use this</button>
                    )}
                    <button onClick={() => handleDisconnectAccount(a.id)} className="btn-secondary text-xs">Remove</button>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="flex items-center gap-2 rounded-lg bg-gray-50 p-3 text-sm text-gray-600">
              <AlertCircle className="h-4 w-4" />
              {google.oauth_configured ? 'No Gmail connected yet' : 'Save the OAuth client above first'}
            </div>
          )}
          <div className="flex flex-wrap gap-2">
            <button
              onClick={async () => {
                try {
                  const r = await getGoogleLogin()
                  window.location.href = r.auth_url
                } catch {
                  setGoogleMsg('OAuth client missing — paste it above first.')
                }
              }}
              className="btn-primary text-sm"
            >
              <LogIn className="mr-2 h-4 w-4" /> Connect with Google
            </button>
          </div>
          {google.connected && (
            <div className="flex flex-col gap-2 sm:flex-row sm:items-end">
              <div className="flex-1">
                <label className="block text-sm font-medium text-gray-700">Send a test email to</label>
                <input
                  type="email"
                  value={testEmail}
                  onChange={(e) => setTestEmail(e.target.value)}
                  placeholder="you@example.com"
                  className="input mt-1"
                />
              </div>
              <button
                onClick={async () => {
                  try {
                    await testGmailSend(testEmail)
                    setGoogleMsg(`Test email sent to ${testEmail}`)
                  } catch {
                    setGoogleMsg('Test send failed.')
                  }
                }}
                disabled={!testEmail}
                className="btn-secondary text-sm"
              >
                <Mail className="mr-2 h-4 w-4" /> Send test
              </button>
            </div>
          )}
          {syncing && (
            <div className="flex items-center gap-2 rounded-lg bg-gray-50 p-3 text-sm text-gray-600">
              <RefreshCw className="h-4 w-4 animate-spin" /> Syncing Gmail replies…
            </div>
          )}
          {googleMsg && (
            <div className="rounded-lg bg-blue-50 p-3 text-sm text-blue-700">{googleMsg}</div>
          )}
        </div>
      </div>

      {/* Automatic daily sending (Gmail-limit aware) */}
      <div className="card">
        <div className="flex items-center gap-2">
          <Clock className="h-5 w-5 text-primary-600" />
          <h2 className="text-lg font-semibold text-gray-900">Automatic email schedule</h2>
        </div>
        <p className="mt-1 text-sm text-gray-500">
          When on, the scheduler emails top-scoring leads every morning (after 9am UTC):
          at most the daily limit, never pushing the day past 450 sends total.
          Replies and WhatsApp follow-ups keep working automatically.
        </p>
        <div className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-end">
          <button
            onClick={async () => {
              const next = !autoSend.enabled
              await updateAutomation({ auto_send_enabled: next })
              setAutoSend({ ...autoSend, enabled: next })
            }}
            className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${autoSend.enabled ? 'bg-primary-600' : 'bg-gray-200'}`}
          >
            <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${autoSend.enabled ? 'translate-x-6' : 'translate-x-1'}`} />
          </button>
          <div>
            <label className="block text-sm font-medium text-gray-700">Max per day</label>
            <input
              type="number" min={1} max={500}
              value={autoSend.daily_limit}
              onChange={(e) => setAutoSend({ ...autoSend, daily_limit: parseInt(e.target.value) || 100 })}
              onBlur={async () => { await updateAutomation({ auto_send_daily_limit: autoSend.daily_limit }) }}
              className="input mt-1 w-32"
            />
          </div>
          <p className="text-xs text-gray-500">
            {autoSend.last_status !== 'idle' || autoSend.last_run_date
              ? `Last run: ${autoSend.last_run_date || '—'} — ${autoSend.last_sent} sent (${autoSend.last_status})`
              : 'Never run yet'}
          </p>
        </div>
      </div>

      {/* CSV Import */}
      <div className="card">
        <div className="flex items-center gap-2">
          <Upload className="h-5 w-5 text-primary-600" />
          <h2 className="text-lg font-semibold text-gray-900">CSV Import</h2>
        </div>
        <p className="mt-1 text-sm text-gray-500">
          Import company names and official website URLs from a CSV file.
          The system will match records carefully and flag ambiguous matches for manual review.
        </p>
        <div className="mt-4 space-y-3">
          <div>
            <label className="block text-sm font-medium text-gray-700">CSV File</label>
            <p className="text-xs text-gray-500 mt-1">
              Required columns: <code>company_name</code>, <code>website</code> (or <code>url</code>)
            </p>
            <input
              type="file"
              accept=".csv"
              onChange={handleImportCSV}
              className="mt-2 block w-full text-sm text-gray-500 file:mr-4 file:rounded-lg file:border-0 file:bg-primary-50 file:px-4 file:py-2 file:text-sm file:font-medium file:text-primary-700 hover:file:bg-primary-100"
            />
          </div>
          <div className="rounded-lg bg-gray-50 p-3">
            <p className="text-xs font-medium text-gray-700">Example CSV format:</p>
            <pre className="mt-1 text-xs text-gray-600">{`company_name,website
Example Corp,https://example.com
Another Inc,https://another.com`}</pre>
          </div>
          {message && (
            <div className="rounded-lg bg-blue-50 p-3 text-sm text-blue-700">{message}</div>
          )}
        </div>
      </div>

      {/* Seller Profile */}
      <div className="card">
        <div className="flex items-center gap-2">
          <Building2 className="h-5 w-5 text-primary-600" />
          <h2 className="text-lg font-semibold text-gray-900">Seller Profile</h2>
        </div>
        <p className="mt-1 text-sm text-gray-500">
          This information is used in AI-generated emails.
        </p>
        <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div>
            <label className="block text-sm font-medium text-gray-700">Business Name</label>
            <input
              type="text"
              value={seller.business_name}
              onChange={(e) => setSeller({ ...seller, business_name: e.target.value })}
              className="input mt-1"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700">Sender Name</label>
            <input
              type="text"
              value={seller.sender_name}
              onChange={(e) => setSeller({ ...seller, sender_name: e.target.value })}
              placeholder="Your name"
              className="input mt-1"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700">Country</label>
            <input
              type="text"
              value={seller.country}
              onChange={(e) => setSeller({ ...seller, country: e.target.value })}
              className="input mt-1"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700">City</label>
            <input
              type="text"
              value={seller.city}
              onChange={(e) => setSeller({ ...seller, city: e.target.value })}
              className="input mt-1"
            />
          </div>
          <div className="sm:col-span-2">
            <label className="block text-sm font-medium text-gray-700">Business Description</label>
            <textarea
              value={seller.business_description}
              onChange={(e) => setSeller({ ...seller, business_description: e.target.value })}
              rows={3}
              className="input mt-1"
            />
          </div>
          <div className="sm:col-span-2">
            <label className="block text-sm font-medium text-gray-700">Products (comma-separated)</label>
            <textarea
              value={seller.products}
              onChange={(e) => setSeller({ ...seller, products: e.target.value })}
              rows={2}
              className="input mt-1"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700">Website</label>
            <input
              type="url"
              value={seller.website}
              onChange={(e) => setSeller({ ...seller, website: e.target.value })}
              className="input mt-1"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700">Catalogue URL</label>
            <input
              type="url"
              value={seller.catalogue_url}
              onChange={(e) => setSeller({ ...seller, catalogue_url: e.target.value })}
              className="input mt-1"
            />
          </div>
        </div>
      </div>

      {/* Automation Settings */}
      <div className="card">
        <div className="flex items-center gap-2">
          <Clock className="h-5 w-5 text-primary-600" />
          <h2 className="text-lg font-semibold text-gray-900">Automation Settings</h2>
        </div>
        <div className="mt-4 space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-gray-700">Email Outreach</p>
              <p className="text-sm text-gray-500">Send personalized emails to leads</p>
            </div>
            <button
              onClick={() => setSettings({ ...settings, email_enabled: !settings.email_enabled })}
              className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                settings.email_enabled ? 'bg-primary-600' : 'bg-gray-200'
              }`}
            >
              <span
                className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                  settings.email_enabled ? 'translate-x-6' : 'translate-x-1'
                }`}
              />
            </button>
          </div>
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-gray-700">WhatsApp Follow-up</p>
              <p className="text-sm text-gray-500">Send WhatsApp messages after delay</p>
            </div>
            <button
              onClick={() => setSettings({ ...settings, whatsapp_enabled: !settings.whatsapp_enabled })}
              className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                settings.whatsapp_enabled ? 'bg-primary-600' : 'bg-gray-200'
              }`}
            >
              <span
                className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                  settings.whatsapp_enabled ? 'translate-x-6' : 'translate-x-1'
                }`}
              />
            </button>
          </div>
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-gray-700">Google Calendar</p>
              <p className="text-sm text-gray-500">Enable meeting booking</p>
            </div>
            <button
              onClick={() => setSettings({ ...settings, calendar_enabled: !settings.calendar_enabled })}
              className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                settings.calendar_enabled ? 'bg-primary-600' : 'bg-gray-200'
              }`}
            >
              <span
                className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                  settings.calendar_enabled ? 'translate-x-6' : 'translate-x-1'
                }`}
              />
            </button>
          </div>
          <div className="grid grid-cols-2 gap-4 pt-4">
            <div>
              <label className="block text-sm font-medium text-gray-700">Follow-up Delay (hours)</label>
              <input
                type="number"
                value={settings.followup_delay_hours}
                onChange={(e) => setSettings({ ...settings, followup_delay_hours: parseInt(e.target.value) })}
                className="input mt-1"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700">Meeting Duration (min)</label>
              <input
                type="number"
                value={settings.meeting_duration_minutes}
                onChange={(e) => setSettings({ ...settings, meeting_duration_minutes: parseInt(e.target.value) })}
                className="input mt-1"
              />
            </div>
          </div>
        </div>
      </div>

      {/* Crawl Settings */}
      <div className="card">
        <div className="flex items-center gap-2">
          <Shield className="h-5 w-5 text-primary-600" />
          <h2 className="text-lg font-semibold text-gray-900">Crawl Settings</h2>
        </div>
        <p className="mt-1 text-sm text-gray-500">
          Configure crawl behavior. URLs are validated to prevent requests to unsafe destinations.
        </p>
        <div className="mt-4">
          <label className="block text-sm font-medium text-gray-700">Crawl Delay (seconds)</label>
          <p className="text-xs text-gray-500 mt-1">
            Time between requests to the same website. Higher values are more polite.
          </p>
          <input
            type="number"
            step="0.5"
            min="0.5"
            value={settings.crawl_delay_seconds}
            onChange={(e) => setSettings({ ...settings, crawl_delay_seconds: parseFloat(e.target.value) })}
            className="input mt-1 w-40"
          />
        </div>
      </div>

      {/* Save Button */}
      <div className="flex justify-end">
        <button onClick={handleSave} className="btn-primary">
          <Save className="mr-2 h-4 w-4" />
          {saved ? 'Saved!' : 'Save Settings'}
        </button>
      </div>
    </div>
  )
}
