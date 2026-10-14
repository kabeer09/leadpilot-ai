export interface Source {
  id: number;
  name: string;
  url: string;
  source_type: string;
  status: string;
  last_crawled_at: string | null;
  created_at: string;
}

export interface Company {
  id: number;
  source_id: number;
  company_name: string;
  website: string | null;
  description: string | null;
  industry: string | null;
  country: string | null;
  city: string | null;
  address: string | null;
  exhibition_name: string | null;
  hall: string | null;
  booth: string | null;
  source_url: string | null;
  exhibitor_url: string | null;

  // Enrichment fields
  enrichment_status?: string | null;
  enrichment_source_url?: string | null;
  enrichment_checked_at?: string | null;
  enrichment_confidence?: number | null;
  enrichment_method?: string | null;
  enrichment_error?: string | null;

  // Data-quality fields (§4/§7)
  company_type?: string | null;
  completeness?: number | null;
  verified?: boolean | null;
  last_verified?: string | null;
  normalized_name?: string | null;
  normalized_domain?: string | null;
  notes?: string | null;

  // Relations
  contacts?: Contact[];
  products?: Product[];

  created_at: string;
  updated_at: string;
}

export interface Product {
  id: number;
  company_id: number;
  name: string;
  category: string | null;
  description: string | null;
  source_url: string | null;
  created_at: string;
}

export interface Contact {
  id: number;
  company_id: number;
  business_email: string | null;
  alternate_email?: string | null;
  email_source?: string | null;
  normalized_email?: string | null;
  normalized_phone?: string | null;
  phone: string | null;
  whatsapp_number: string | null;
  email_source_url: string | null;
  whatsapp_source_url: string | null;
  verified: boolean;
  contact_type: string;
  created_at: string;
}

export function emailDomain(value: string | null | undefined): string {
  if (!value) return '';
  const v = value.trim().toLowerCase();
  if (v.includes('@') && !v.includes('://')) return v.split('@').pop() || '';
  try {
    const host = new URL(v.includes('://') ? v : `https://${v}`).hostname.replace(/^www\./, '');
    return host;
  } catch {
    return '';
  }
}

export function baseDomain(host: string): string {
  const parts = host.split('.').filter(Boolean);
  return parts.length >= 2 ? parts.slice(-2).join('.') : host;
}

function sld(host: string): string {
  const parts = host.split('.').filter(Boolean);
  if (parts.length <= 2) return parts[0] || '';
  return parts[parts.length - 2].length <= 3 ? parts[parts.length - 3] : parts[parts.length - 2];
}

/** Does this email belong to this company website? (free mailboxes never match) */
export function emailMatchesWebsite(email: string | null | undefined, website: string | null | undefined): boolean {
  const eh = emailDomain(email);
  const sh = emailDomain(website);
  if (!eh || !sh) return false;
  const free = ['gmail.com', 'yahoo.com', 'hotmail.com', 'outlook.com', 'live.com', 'icloud.com', 'aol.com'];
  if (free.includes(eh) || free.includes(baseDomain(eh))) return false;
  if (baseDomain(eh) === baseDomain(sh)) return true;
  return !!sld(eh) && sld(eh) === sld(sh);
}

export interface Lead {
  id: number;
  company_id: number;
  contact_id: number | null;
  campaign_id: number | null;
  lead_score: number;
  lead_priority: 'HIGH' | 'MEDIUM' | 'LOW';
  ai_summary: string | null;
  ai_reason: string | null;
  status: string;
  created_at: string;
  updated_at: string;
  company?: Company | null;
  contact?: Contact | null;
  last_outreach?: {
    id: number;
    channel: string;
    status: string;
    subject: string | null;
    sent_at: string | null;
    response_at: string | null;
    follow_up_count?: number;
    follow_up_sent_at?: string | null;
    provider_thread_id?: string | null;
  } | null;
}

export interface LeadDetail extends Lead {
  company: Company | null;
  contact: Contact | null;
  outreach: Outreach[];
  meetings: Meeting[];
  activities: Activity[];
}

export interface Outreach {
  id: number;
  lead_id: number;
  channel: string;
  status: string;
  subject: string | null;
  message: string | null;
  sent_at: string | null;
  scheduled_at: string | null;
  response_at: string | null;
  error: string | null;
  created_at: string;
  updated_at: string;
}

export interface CrawlJob {
  id: number;
  source_id: number;
  url: string;
  status: string;
  started_at: string | null;
  finished_at: string | null;
  pages_visited: number;
  companies_discovered: number;
  records_created: number;
  records_updated: number;
  duplicates_flagged: number;
  errors: string[];
  created_at: string;
}

export interface DuplicateCandidate {
  id: number;
  match_type: string;
  confidence: number;
  status: string;
  created_at: string;
  company_a: { id: number; name: string; source_id: number; website: string | null } | null;
  company_b: { id: number; name: string; source_id: number; website: string | null } | null;
}

export interface Meeting {
  id: number;
  lead_id: number;
  calendar_event_id: string | null;
  meet_url: string | null;
  start_time: string;
  end_time: string;
  status: string;
  created_at: string;
}

export interface Activity {
  id: number;
  lead_id: number;
  activity_type: string;
  description: string | null;
  metadata_: Record<string, unknown> | null;
  created_at: string;
}

export interface AnalyticsOverview {
  total_companies: number;
  total_contacts: number;
  total_leads: number;
  emails_sent: number;
  emails_failed: number;
  replies: number;
  reply_rate: number;
  interested: number;
  meetings_booked: number;
  qualified: number;
  followups_due: number;
  whatsapp_sent: number;
  emails_sent_today?: number;
  replies_today?: number;
  email_followups_due?: number;
  email_followups_sent?: number;
  unsubscribed?: number;
}

export interface SellerProfile {
  business_name: string;
  business_description: string;
  products: string[];
  country: string;
  city: string;
  website: string;
  catalogue_url: string;
  meeting_url: string;
  sender_name: string;
}

export interface EnrichmentResult {
  status: string;
  emails: string[];
  phones: string[];
  whatsapp: string[];
  source_url: string | null;
  confidence: number;
  method: string | null;
  error: string | null;
}
