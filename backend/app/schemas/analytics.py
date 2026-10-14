"""Analytics schemas."""
from pydantic import BaseModel


class AnalyticsOverview(BaseModel):
    total_companies: int
    total_contacts: int
    total_leads: int
    emails_sent: int
    emails_failed: int
    replies: int
    reply_rate: float
    interested: int
    meetings_booked: int
    qualified: int
    followups_due: int
    whatsapp_sent: int
    # Outreach tracking (all derived from real records)
    emails_sent_today: int = 0
    replies_today: int = 0
    email_followups_due: int = 0
    email_followups_sent: int = 0
    unsubscribed: int = 0
