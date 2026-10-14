"""Las Vegas adapter tests (offline mapping tests — no network)."""
from app.services.crawler import is_lasvegas_listing_url
from app.services.lasvegas import parse_entry, is_lasvegas_listing_url as detect_direct


def test_detect():
    assert is_lasvegas_listing_url("https://www.lasvegasmarket.com/exhibitor/Directory") is True
    assert is_lasvegas_listing_url("https://www.lasvegasmarket.com/exhibitor/exhibitor-directory") is True
    assert detect_direct("https://www.lasvegasmarket.com/exhibitor/Directory") is True
    assert is_lasvegas_listing_url("https://www.atlantamarket.com/exhibitor/Directory") is False
    assert is_lasvegas_listing_url("not a url") is False


def test_parse_exhibitor_type():
    out = parse_entry(
        {"exhibitorId": "65615", "name": "aspenhome", "type": "exhibitor",
         "exhibitorName": "aspenhome"}, "u")
    assert out["company_name"] == "aspenhome"
    assert out["profile_url"] == "https://www.lasvegasmarket.com/exhibitor/65615"
    assert out["showroom"] == ""
    assert out["exhibition_name"] == "Las Vegas Market"


def test_parse_line_type_keeps_brand_and_showroom():
    out = parse_entry(
        {"exhibitorId": "65842", "name": "and the little dog laughed",
         "type": "line", "exhibitorName": "Fine Lines"}, "u")
    assert out["company_name"] == "and the little dog laughed"
    assert out["showroom"] == "Fine Lines"


def test_parse_rejects_junk():
    assert parse_entry({"exhibitorId": "", "name": "X"}, "u") is None
    assert parse_entry({"exhibitorId": "1", "name": " | "}, "u") is None
    assert parse_entry({}, "u") is None
