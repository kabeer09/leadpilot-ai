"""Phase 2 — WhatsApp finder tests."""
import pytest
from app.services.whatsapp_finder import WhatsAppFinder


def test_whatsapp_finder_initialization():
    finder = WhatsAppFinder(timeout=15000)
    assert finder.timeout == 15000


def test_normalize_number_valid():
    finder = WhatsAppFinder()
    assert finder._normalize_number("+1 234 567 8900") == "12345678900"
    assert finder._normalize_number("+44 20 7946 0958") == "442079460958"


def test_normalize_number_invalid():
    finder = WhatsAppFinder()
    assert finder._normalize_number("123") is None  # Too short
    assert finder._normalize_number("12345678901234567890") is None  # Too long


def test_normalize_number_with_plus():
    finder = WhatsAppFinder()
    result = finder._normalize_number("+91 98765 43210")
    assert result == "919876543210"
