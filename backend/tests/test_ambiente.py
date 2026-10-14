"""Ambiente adapter tests (offline mapping tests — no network)."""
from app.services.crawler import is_ambiente_search_url
from app.services.ambiente import parse_exhibitor, _normalize_website, _valid_email


def test_is_ambiente_search_url():
    assert is_ambiente_search_url(
        "https://ambiente.messefrankfurt.com/frankfurt/en/exhibitor-search.html?page=1&pagesize=30"
    ) is True
    assert is_ambiente_search_url("https://www.atlantamarket.com/exhibitor/Directory") is False
    assert is_ambiente_search_url("https://example.com/exhibitors") is False
    assert is_ambiente_search_url("not a url") is False


def _record(**overrides):
    base = {
        "name": "2M2 Group AB",
        "rewriteId": "2m2-group-ab",
        "homepage": "www.2m2.se",
        "href": "www.2m2.se",
        "address": {
            "street": "Inre Kustvägen 22-24",
            "city": "Bastad",
            "zip": "269 43",
            "tel": "+46 431 222 22",
            "country": {"id": "SWE", "iso3": "SWE", "label": "Sweden"},
            "email": "vincent@2m2.se",
        },
        "description": {"text": "Trading and direct import company."},
        "exhibition": {
            "name": "Ambiente 2027",
            "exhibitionHall": [{"name": "3.0", "stand": [{"name": "G01"}]}],
        },
        "categories": [{"name": "Table & Table Select"}],
        "products": {"products": [
            {"name": "UPCYCLE", "description": {"text": "Upcycled decor"}},
        ]},
    }
    base.update(overrides)
    return base


def test_parse_full_record():
    out = parse_exhibitor(_record(), "https://listing.example", "https://api.example")
    assert out["company_name"] == "2M2 Group AB"
    assert out["website"] == "https://www.2m2.se"
    assert out["country"] == "Sweden"
    assert out["city"] == "Bastad"
    assert out["hall"] == "3.0"
    assert out["booth"] == "G01"
    assert out["industry"] == "Table & Table Select"
    assert out["emails"] == ["vincent@2m2.se"]
    assert out["phones"] == ["+46 431 222 22"]
    assert [p["name"] for p in out["products"]] == ["UPCYCLE"]
    assert "Trading" in out["description"]


def test_parse_minimal_record():
    out = parse_exhibitor({"name": "5a Trade SAS"}, "https://listing.example", "https://api.example")
    assert out["company_name"] == "5a Trade SAS"
    assert out["website"] is None
    assert out["emails"] == []
    assert out["products"] == []


def test_parse_rejects_junk_names():
    assert parse_exhibitor({"name": " | "}, "u", "a") is None
    assert parse_exhibitor({"name": ""}, "u", "a") is None
    assert parse_exhibitor({}, "u", "a") is None


def test_parse_strips_search_highlight_markup():
    out = parse_exhibitor(
        {"name": '<span class="highlighted">Zwilling</span> J.A. Henckels AG'},
        "u", "a",
    )
    assert out["company_name"] == "Zwilling J.A. Henckels AG"


def test_parse_rejects_bad_email():
    out = parse_exhibitor(_record(address={"email": "not-an-email"}), "u", "a")
    assert out["emails"] == []


def test_normalize_website():
    assert _normalize_website("www.2m2.se") == "https://www.2m2.se"
    assert _normalize_website("https://example.com/") == "https://example.com/"
    assert _normalize_website("") is None
    assert _normalize_website(None) is None
    assert _normalize_website("not a site") is None


def test_valid_email():
    assert _valid_email("info@abhomeinc.com") == "info@abhomeinc.com"
    assert _valid_email("info@example.com") is None  # template domain rejected
    assert _valid_email("bad@") is None
    assert _valid_email(None) is None
