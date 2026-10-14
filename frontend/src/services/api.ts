import axios from 'axios';
import type {
  Source,
  Company,
  Lead,
  LeadDetail,
  AnalyticsOverview,
  Outreach,
  Meeting,
  CrawlJob,
  DuplicateCandidate,
} from '../types';

const api = axios.create({
  baseURL: '/api',
  headers: { 'Content-Type': 'application/json' },
});

// Sources
export const createSource = (data: { name: string; url: string }) =>
  api.post<Source>('/sources', data).then((r) => r.data);

export const getSources = () =>
  api.get<Source[]>('/sources').then((r) => r.data);

export const getSource = (id: number) =>
  api.get<Source>(`/sources/${id}`).then((r) => r.data);

export const triggerCrawl = (id: number, params?: { max_profiles?: number; skip_website_crawl?: boolean; min_quality?: number; profile_offset?: number }) =>
  api.post(`/sources/${id}/crawl`, null, { params }).then((r) => r.data);

export const getCrawlStatus = (id: number) =>
  api.get<{ source_id: number; status: string; last_crawled_at: string | null }>(`/sources/${id}/status`).then((r) => r.data);

// Crawl jobs
export const getCrawlJobs = (params?: { status?: string; limit?: number }) =>
  api.get<CrawlJob[]>('/sources/jobs', { params }).then((r) => r.data);

export const getCrawlJob = (id: number) =>
  api.get<CrawlJob>(`/sources/jobs/${id}`).then((r) => r.data);

export const retryCrawlJob = (id: number) =>
  api.post(`/sources/jobs/${id}/retry`).then((r) => r.data);

// Companies
export interface CompanyList {
  items: Company[];
  total: number;
}

export const getCompanies = (params?: Record<string, string>) =>
  api.get<Company[]>('/companies', { params }).then((r) => ({
    items: r.data,
    total: parseInt(r.headers['x-total-count'] || String(r.data.length), 10),
  }));

export const getCompanyFilters = () =>
  api.get<{ sources: { id: number; name: string }[]; countries: string[]; categories: string[]; company_types: string[] }>('/companies/filters').then((r) => r.data);

export const getCompany = (id: number) =>
  api.get<Company>(`/companies/${id}`).then((r) => r.data);

export const updateCompany = (id: number, data: { notes?: string; verified?: boolean; company_type?: string }) =>
  api.patch<Company>(`/companies/${id}`, data).then((r) => r.data);

export const getDuplicates = (status = 'pending') =>
  api.get<DuplicateCandidate[]>('/companies/duplicates', { params: { status } }).then((r) => r.data);

export const resolveDuplicate = (id: number, status: 'reviewed' | 'dismissed') =>
  api.post(`/companies/duplicates/${id}/resolve`, { status }).then((r) => r.data);

export const enrichCompany = (id: number) =>
  api.post(`/companies/${id}/enrich`).then((r) => r.data);

export const enrichCompaniesBulk = () =>
  api.post('/companies/enrich-bulk').then((r) => r.data);

export const importCSV = (file: File) => {
  const form = new FormData();
  form.append('file', file);
  return api.post('/companies/import-csv', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  }).then((r) => r.data);
};

// Leads
export const getLeads = (params?: { status?: string; priority?: string; source_id?: number; category?: string; email_filter?: 'eligible' | 'sent' | 'not_sent' | 'followup_due'; sort?: string; skip?: number; limit?: number }) =>
  api.get<Lead[]>('/leads', { params }).then((r) => r.data);

export const exportLeadsCsv = (params?: Record<string, string | number>) =>
  api.get('/leads/export/csv', { params, responseType: 'blob' }).then((r) => {
    const url = window.URL.createObjectURL(new Blob([r.data], { type: 'text/csv' }));
    const a = document.createElement('a');
    a.href = url;
    a.download = 'leads_export.csv';
    a.click();
    window.URL.revokeObjectURL(url);
  });

export const getLead = (id: number) =>
  api.get<LeadDetail>(`/leads/${id}`).then((r) => r.data);

export const scoreLead = (id: number) =>
  api.post(`/leads/${id}/score`).then((r) => r.data);

export const generateEmail = (id: number) =>
  api.post<{ lead_id: number; subject: string; body: string; used_fallback: boolean }>(`/leads/${id}/generate-email`).then((r) => r.data);

export const validateEmail = (id: number) =>
  api.post<{ lead_id: number; is_valid: boolean; errors: string[]; warnings: string[] }>(`/leads/${id}/validate`).then((r) => r.data);

export const queueLeadEmail = (id: number) =>
  api.post<{ lead_id: number; outreach_id: number; subject: string; status: string }>(`/leads/${id}/queue-email`).then((r) => r.data);

export const queueWhatsappFollowup = (lead_id: number, message?: string) =>
  api.post('/outreach/followups/queue', { lead_id, message }).then((r) => r.data);

export const getFollowupsDue = () =>
  api.get<{ lead_id: number; company_name: string | null; to_phone: string | null; email_sent_at: string | null }[]>('/outreach/followups/due').then((r) => r.data);

export const scanFollowups = () =>
  api.post<{ due_found: number; queued: number; skipped: unknown[] }>('/outreach/followups/scan').then((r) => r.data);

// 24-hour email follow-ups (Workflow C)
export const getEmailFollowupsDue = () =>
  api.get<{ lead_id: number; company_name: string | null; to_email: string | null; email_sent_at: string | null; thread_id: string | null }[]>('/outreach/followups/email-due').then((r) => r.data);

export const sendFollowUp = (lead_id: number, data?: { subject?: string; message?: string; dry_run?: boolean }) =>
  api.post(`/outreach/${lead_id}/follow-up`, data || {}).then((r) => r.data);

export const bulkFollowUp = (data: { limit?: number; dry_run?: boolean }) =>
  api.post<{ due: number; sent: number; skipped: number; errors: string[] }>('/outreach/followups/bulk', data).then((r) => r.data);

// Analytics
export const getAnalytics = () =>
  api.get<AnalyticsOverview>('/analytics/overview').then((r) => r.data);

export const getByCountry = (source_id?: number) =>
  api.get<{ label: string; count: number }[]>('/analytics/companies/by-country', { params: source_id ? { source_id } : {} }).then((r) => r.data);

export const getByFair = () =>
  api.get<{ source_id: number; fair: string; companies: number }[]>('/analytics/companies/by-fair').then((r) => r.data);

export const getByCategory = (source_id?: number) =>
  api.get<{ label: string; companies: number }[]>('/analytics/companies/by-category', { params: source_id ? { source_id } : {} }).then((r) => r.data);

export const getByType = (source_id?: number) =>
  api.get<{ label: string; count: number }[]>('/analytics/companies/by-type', { params: source_id ? { source_id } : {} }).then((r) => r.data);

export const getContactAvailability = (source_id?: number) =>
  api.get<Record<string, number>>('/analytics/companies/contact-availability', { params: source_id ? { source_id } : {} }).then((r) => r.data);

export const getCompleteness = (source_id?: number) =>
  api.get<{ bucket: string; count: number }[]>('/analytics/companies/completeness', { params: source_id ? { source_id } : {} }).then((r) => r.data);

export const getDiscoveries = (days = 30, source_id?: number) =>
  api.get<{ date: string; companies: number }[]>('/analytics/companies/discoveries', { params: { days, ...(source_id ? { source_id } : {}) } }).then((r) => r.data);

export const getCrawlingStats = () =>
  api.get<{ total_jobs: number; by_status: Record<string, number>; successful: number; failed: number; running: number }>('/analytics/crawling').then((r) => r.data);

// Outreach
export const getOutreach = (params?: { status?: string; channel?: string }) =>
  api.get<Outreach[]>('/outreach', { params }).then((r) => r.data);

export const sendBulkEmail = (data: { subject?: string; message?: string; use_ai?: boolean; limit?: number; dry_run?: boolean; account_id?: number }) =>
  api.post<{ dry_run?: boolean; count?: number; preview?: { lead_id: number; company_name: string | null; to_email: string | null; lead_score: number; subject: string }[]; message?: string; total?: number }>('/outreach/send-all', data).then((r) => r.data);

export const bulkSendStatus = () =>
  api.get<{ state: string; total: number; sent: number; failed: number; skipped: number; errors: string[] }>('/outreach/send-all/status').then((r) => r.data);

export const checkReplies = () =>
  api.post<{ checked: number; matched: number; categories: Record<string, number> }>('/outreach/check-replies').then((r) => r.data);

export const getReadyOutreach = () =>
  api.get<Outreach[]>('/outreach/ready').then((r) => r.data);

export const queueOutreachEmail = (data: { lead_id: number; subject?: string; message?: string }) =>
  api.post('/outreach', data).then((r) => r.data);

export const markOutreachSent = (id: number, message_id?: string) =>
  api.post(`/outreach/${id}/sent`, message_id ? { message_id } : {}).then((r) => r.data);

// Meetings
export const getMeetings = () =>
  api.get<Meeting[]>('/meetings').then((r) => r.data);

export const proposeMeeting = (data: { lead_id: number; start_time: string; end_time: string }) =>
  api.post<Meeting>('/meetings/propose', data).then((r) => r.data);

export const bookMeeting = (id: number) =>
  api.post<Meeting>(`/meetings/${id}/book`).then((r) => r.data);

export const cancelMeeting = (id: number) =>
  api.post<Meeting>(`/meetings/${id}/cancel`).then((r) => r.data);

export const checkAvailability = (data: { start_time: string; end_time: string }) =>
  api.post<{ available: boolean; conflicts: unknown[]; message: string }>('/meetings/availability', data).then((r) => r.data);

// Webhooks
export const sendGmailWebhook = (data: { outreach_id: number; event_type: string }) =>
  api.post('/webhooks/gmail', data).then((r) => r.data);

export const sendWhatsappWebhook = (data: { outreach_id: number; event_type: string }) =>
  api.post('/webhooks/whatsapp', data).then((r) => r.data);

// Google OAuth
export const getGoogleLogin = () =>
  api.get<{ auth_url: string }>('/auth/google/login').then((r) => r.data);

export const getGoogleStatus = () =>
  api.get<{ connected: boolean; email: string | null; active_id: number | null; accounts: { id: number; email: string; active: boolean; access_ok?: boolean; last_verified_at?: string | null }[]; oauth_configured: boolean }>('/auth/google/status').then((r) => r.data);

// Outreach tracking (dashboard)
export const getOutreachSummary = () =>
  api.get<{ total_companies: number; total_leads: number; eligible_leads: number; emails_sent_total: number; emails_sent_today: number; replies_today: number; interested: number; bounced: number; followups_due: number; followups_sent: number; unsubscribed: number; meetings_booked: number }>('/outreach/summary').then((r) => r.data);

export const getSentEmails = (limit = 50) =>
  api.get<{ outreach_id: number; lead_id: number; company: string | null; to_email: string | null; campaign_id: number | null; subject: string | null; sent_at: string | null; reply_at: string | null; thread_id: string | null; thread_url: string | null; status: string; follow_up_count: number; next_action: string }[]>('/outreach/sent', { params: { limit } }).then((r) => r.data);

// New-batch sending (never-contacted only, idempotent run)
export const newBatchPreview = (params: { subject?: string; message?: string; campaign_id?: number; limit?: number; min_score?: number; source_id?: number }) =>
  api.get<{ count: number; campaign_id: number | null; rows: { lead_id: number; company: string | null; to_email: string | null; source: string | null; source_id: number | null; relevance_score: number; priority: string | null; country: string | null; subject: string; body: string }[] }>('/outreach/new-batch/preview', { params }).then((r) => r.data);

export const newBatchRun = (data: { subject?: string; message?: string; campaign_id?: number; limit?: number; min_score?: number; source_id?: number }) =>
  api.post<{ sent: number; failed: number; skipped: unknown[]; errors: string[]; campaign_id: number | null }>('/outreach/new-batch/run', data).then((r) => r.data);

// Lead timeline (chronological outreach + activities + meetings)
export const getLeadTimeline = (id: number) =>
  api.get<{ lead_id: number; status: string; score: number; events: Record<string, unknown>[] }>(`/leads/${id}/timeline`).then((r) => r.data);

// Company contacts (rollup + every audited value with source URLs)
export const getCompanyContacts = (id: number) =>
  api.get<{ company_id: number; primary: Record<string, unknown> | null; items: { id: number; contact_type: string; display_value: string; normalized_value: string; source_url: string | null; source_page_type: string | null; is_primary: boolean; verification_status: string; validity_status: string; merge_status: string; extracted_at: string | null }[]; coverage: { emails: string[]; phones: string[]; whatsapp: string[]; has_email: boolean; has_phone: boolean; has_whatsapp: boolean; contactable: boolean } }>(`/companies/${id}/contacts`).then((r) => r.data);

// Automation health
export const getAutomationHealth = () =>
  api.get<{ last_crawl_at: string | null; running_crawls: number; last_email_sent_at: string | null; last_reply_at: string | null; last_whatsapp_sent_at: string | null; pending_email: number; pending_whatsapp: number; gmail_accounts_connected: number; scheduler: Record<string, unknown>; latest_errors: { outreach_id: number; lead_id: number; channel: string; error: string; at: string }[] }>('/automation/health').then((r) => r.data);

// Outreach trends
export const getTrends = (days = 30) =>
  api.get<{ date: string; discovered: number; sent: number; replies: number; bounced: number; reply_rate: number }[]>('/analytics/trends', { params: { days } }).then((r) => r.data);

// Data quality: duplicates, merges, exclusions, suppressions
export const getDQDuplicates = (status = 'pending') =>
  api.get<DuplicateCandidate[]>('/data-quality/duplicates', { params: { status } }).then((r) => r.data);

export const dqMergePreview = (canonical_id: number, duplicate_id: number) =>
  api.post('/data-quality/deduplicate/preview', { canonical_id, duplicate_id }).then((r) => r.data);

export const dqMergeApply = (canonical_id: number, duplicate_id: number, note?: string) =>
  api.post('/data-quality/deduplicate/apply', { canonical_id, duplicate_id, note }).then((r) => r.data);

export const getMerges = () =>
  api.get<Record<string, unknown>[]>('/data-quality/merges').then((r) => r.data);

export const exclusionsPreview = () =>
  api.post<{ would_exclude: number; sample: { id: number; name: string; source_id: number }[]; dry_run: boolean; note: string }>('/data-quality/exclusions/preview').then((r) => r.data);

export const exclusionsApply = () =>
  api.post<{ excluded: number; note: string }>('/data-quality/exclusions/apply').then((r) => r.data);

export const getSuppressions = () =>
  api.get<{ id: number; value: string; value_type: string; reason: string; source: string | null }[]>('/data-quality/suppressions').then((r) => r.data);

export const addSuppression = (data: { value: string; value_type?: string; reason?: string }) =>
  api.post('/data-quality/suppressions', data).then((r) => r.data);

export const approveWhatsapp = (contact_id: number, evidence?: string) =>
  api.post(`/data-quality/whatsapp/approve/${contact_id}`, { evidence }).then((r) => r.data);

export const selectGoogleAccount = (account_id: number) =>
  api.post('/auth/google/select', { account_id }).then((r) => r.data);

export const disconnectGoogle = (account_id?: number) =>
  api.post('/auth/google/disconnect', account_id ? { account_id } : {}).then((r) => r.data);

export const testGmailSend = (to: string) =>
  api.get('/auth/google/test-send', { params: { to } }).then((r) => r.data);

export const getGoogleClient = () =>
  api.get<{ client_id_set: boolean; client_secret_set: boolean; redirect_uri: string; from_ui: boolean }>('/settings/google-client').then((r) => r.data);

export const saveGoogleClient = (data: { client_id?: string; client_secret?: string; redirect_uri?: string }) =>
  api.put('/settings/google-client', data).then((r) => r.data);

export const getAutoSendState = () =>
  api.get<{ enabled: boolean; daily_limit: number; send_hour_utc: number; last_run_date: string | null; last_sent: number; last_status: string }>('/settings/auto-send-state').then((r) => r.data);

export const updateAutomation = (data: { auto_send_enabled?: boolean; auto_send_daily_limit?: number }) =>
  api.put('/settings/automation', data).then((r) => r.data);

// Analytics pipeline
export const getPipeline = () =>
  api.get<{ stages: { step: number; label: string; count: number; detail?: Record<string, number> }[] }>('/analytics/pipeline').then((r) => r.data);

export const getEmailMatch = () =>
  api.get<{ checked: number; matched: number; mismatched: number; match_rate: number; mismatch_samples: { company: string; website: string | null; email: string; alternate: string | null; reason: string }[] }>('/analytics/email-match').then((r) => r.data);
