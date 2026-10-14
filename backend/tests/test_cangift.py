"""CanGift adapter tests (offline mapping tests — no network)."""
from app.services.crawler import is_cangift_listing_url
from app.services.cangift import parse_company, is_cangift_listing_url as detect_direct


def _record(**overrides):
    base = {
        "CompanyName": "Arcadia Puzzles",
        "Phone": "647-300-9043",
        "CountryPhoneCode": "1",
        "Website": "www.arcadiapuzzles.com",
        "City": "Markham",
        "Address1": "2 Freeman Williams Street",
        "Address2": "L6C 3M8",
        "ProvinceName": "Ontario",
        "CountryName": "CANADA",
        "BoothNumber": "5208",
        "Booths": [{"BoothNumber": "5208"}],
        "Description": None,
        "Slogan": "Great puzzles",
        "InterestTags": [{"Text": "Toys"}, {"Text": "Games"}],
        "Products": [],
    }
    base.update(overrides)
    return base


def test_detect():
    url = "https://cangift.org/toronto-fall-gift-home-market/exhibiting-companies/"
    assert is_cangift_listing_url(url) is True
    assert detect_direct(url) is True
    assert is_cangift_listing_url("https://www.atlantamarket.com/exhibitor/Directory") is False
    assert is_cangift_listing_url("not a url") is False


def test_parse_full_record():
    out = parse_company(_record(), "https://listing.example", "https://api.example")
    assert out["company_name"] == "Arcadia Puzzles"
    assert out["website"] == "https://www.arcadiapuzzles.com"
    assert out["phones"] == ["+1 647-300-9043"]
    assert out["booth"] == "5208"
    assert out["city"] == "Markham"
    assert out["country"] == "Canada"
    assert "Toys" in out["industry"]
    assert out["exhibition_name"] == "CanGift Toronto Gift + Home Market"


def test_parse_minimal_record():
    out = parse_company({"CompanyName": "925 Sterling"}, "u", "a")
    assert out["company_name"] == "925 Sterling"
    assert out["website"] is None
    assert out["phones"] == []


def test_parse_rejects_junk():
    assert parse_company({"CompanyName": ""}, "u", "a") is None
    assert parse_company({}, "u", "a") is None


def test_parse_strips_markup_and_unescapes():
    out = parse_company({"CompanyName": "<b>A &amp; B Gifts</b>"}, "u", "a")
    assert out["company_name"] == "A & B Gifts"


def test_parse_email_in_freetext():
    out = parse_company({"CompanyName": "Mail Co",
                         "AdditionalInfo": "Write to hello@mailco.example today"}, "u", "a")
    assert out["emails"] == ["hello@mailco.example"]
