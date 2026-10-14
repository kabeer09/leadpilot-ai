"""Phase 2 — Outreach service tests."""
import pytest
from datetime import datetime, timedelta
from app.services.outreach import is_email_ready_to_send, is_whatsapp_followup_due
from app.models.lead import Lead, LeadStatus
from app.models.outreach import Outreach, OutreachChannel, OutreachStatus
from app.models.contact import Contact, ContactType


def test_is_email_ready_to_send_new_lead():
    lead = Lead(status=LeadStatus.NEW)
    lead.contact = Contact(business_email="info@test.com", contact_type=ContactType.EMAIL)
    assert is_email_ready_to_send(lead) is True


def test_is_email_ready_to_send_already_sent():
    lead = Lead(status=LeadStatus.EMAIL_SENT)
    lead.contact = Contact(business_email="info@test.com", contact_type=ContactType.EMAIL)
    assert is_email_ready_to_send(lead) is False


def test_is_email_ready_to_send_replied():
    lead = Lead(status=LeadStatus.REPLIED)
    lead.contact = Contact(business_email="info@test.com", contact_type=ContactType.EMAIL)
    assert is_email_ready_to_send(lead) is False


def test_is_email_ready_to_send_unsubscribed():
    lead = Lead(status=LeadStatus.UNSUBSCRIBED)
    lead.contact = Contact(business_email="info@test.com", contact_type=ContactType.EMAIL)
    assert is_email_ready_to_send(lead) is False


def test_is_email_ready_to_send_no_contact():
    lead = Lead(status=LeadStatus.NEW)
    lead.contact = None
    assert is_email_ready_to_send(lead) is False


def test_is_email_ready_to_send_no_email():
    lead = Lead(status=LeadStatus.NEW)
    lead.contact = Contact(phone="+1234567890", contact_type=ContactType.PHONE)
    assert is_email_ready_to_send(lead) is False


def test_is_whatsapp_followup_due_too_early():
    lead = Lead(status=LeadStatus.EMAIL_SENT)
    lead.contact = Contact(
        business_email="info@test.com",
        whatsapp_number="+1234567890",
        contact_type=ContactType.EMAIL,
    )
    # Email sent 1 hour ago — too early
    email_outreach = Outreach(
        lead_id=1,
        channel=OutreachChannel.EMAIL,
        status=OutreachStatus.SENT,
        sent_at=datetime.utcnow() - timedelta(hours=1),
    )
    # Mock db session
    class MockQuery:
        def filter(self, *args):
            return self
        def order_by(self, *args):
            return self
        def first(self):
            return email_outreach
    class MockDB:
        def query(self, *args):
            return MockQuery()
    assert is_whatsapp_followup_due(lead, MockDB()) is False


def test_is_whatsapp_followup_due_after_24h():
    lead = Lead(status=LeadStatus.EMAIL_SENT)
    lead.contact = Contact(
        business_email="info@test.com",
        whatsapp_number="+1234567890",
        contact_type=ContactType.EMAIL,
    )
    # Email sent 25 hours ago — follow-up due
    email_outreach = Outreach(
        lead_id=1,
        channel=OutreachChannel.EMAIL,
        status=OutreachStatus.SENT,
        sent_at=datetime.utcnow() - timedelta(hours=25),
    )
    class MockQuery:
        def filter(self, *args):
            return self
        def order_by(self, *args):
            return self
        def first(self):
            return email_outreach
    class MockDB:
        def query(self, *args):
            return MockQuery()
    assert is_whatsapp_followup_due(lead, MockDB()) is True


def test_is_whatsapp_followup_due_no_whatsapp():
    lead = Lead(status=LeadStatus.EMAIL_SENT)
    lead.contact = Contact(
        business_email="info@test.com",
        contact_type=ContactType.EMAIL,
    )
    email_outreach = Outreach(
        lead_id=1,
        channel=OutreachChannel.EMAIL,
        status=OutreachStatus.SENT,
        sent_at=datetime.utcnow() - timedelta(hours=25),
    )
    class MockQuery:
        def filter(self, *args):
            return self
        def order_by(self, *args):
            return self
        def first(self):
            return email_outreach
    class MockDB:
        def query(self, *args):
            return MockQuery()
    assert is_whatsapp_followup_due(lead, MockDB()) is False
