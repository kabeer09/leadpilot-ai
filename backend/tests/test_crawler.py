"""Tests for the multi-stage exhibitor crawler."""
import pytest
from app.services.crawler import ExhibitorCrawler, CrawlerStats


def test_crawler_stats_initialization():
    stats = CrawlerStats()
    assert stats.listing_pages_processed == 0
    assert stats.exhibitor_profile_urls_found == 0
    assert stats.exhibitor_profiles_processed == 0
    assert stats.companies_extracted == 0
    assert stats.websites_found == 0
    assert stats.company_websites_crawled == 0
    assert stats.contact_pages_found == 0
    assert stats.emails_found == 0
    assert stats.phones_found == 0
    assert stats.whatsapp_found == 0
    assert stats.errors == 0
    assert stats.error_details == []


def test_crawler_stats_to_dict():
    stats = CrawlerStats()
    stats.listing_pages_processed = 5
    stats.companies_extracted = 10
    stats.errors = 1
    stats.error_details = ["Timeout: http://example.com"]
    d = stats.to_dict()
    assert d["listing_pages_processed"] == 5
    assert d["companies_extracted"] == 10
    assert d["errors"] == 1
    assert len(d["error_details"]) == 1


def test_crawler_initialization():
    crawler = ExhibitorCrawler(
        start_url="https://example.com/exhibitors",
        max_pages=50,
        max_depth=2,
        request_delay=0.5,
    )
    assert crawler.start_url == "https://example.com/exhibitors"
    assert crawler.max_pages == 50
    assert crawler.max_depth == 2
    assert crawler.request_delay == 0.5
    assert crawler.domain == "example.com"
    assert len(crawler.visited_urls) == 0
    assert len(crawler.exhibitor_profile_urls) == 0


def test_crawler_is_same_domain():
    crawler = ExhibitorCrawler(start_url="https://example.com/exhibitors")
    assert crawler._is_same_domain("https://example.com/company/abc") is True
    assert crawler._is_same_domain("https://other.com/company/abc") is False


def test_crawler_should_exclude():
    crawler = ExhibitorCrawler(start_url="https://example.com/exhibitors")
    assert crawler._should_exclude("https://example.com/login") is True
    assert crawler._should_exclude("https://example.com/admin") is True
    assert crawler._should_exclude("https://example.com/api/data") is True
    assert crawler._should_exclude("https://example.com/privacy") is True
    assert crawler._should_exclude("https://example.com/company/abc") is False


def test_crawler_is_exhibitor_profile_url():
    crawler = ExhibitorCrawler(start_url="https://example.com/exhibitors")
    assert crawler._is_exhibitor_profile_url("https://example.com/exhibitor/abc") is True
    assert crawler._is_exhibitor_profile_url("https://example.com/company/abc") is True
    assert crawler._is_exhibitor_profile_url("https://example.com/participant/abc") is True
    assert crawler._is_exhibitor_profile_url("https://example.com/about") is False


def test_crawler_profile_url_plural_forms():
    crawler = ExhibitorCrawler(start_url="https://www.springfair.com/exhibitors")
    # Spring Fair slugs: /exhibitors/{company-slug}
    assert crawler._is_exhibitor_profile_url("https://www.springfair.com/exhibitors/3d-studio-gifts") is True
    assert crawler._is_exhibitor_profile_url("https://www.springfair.com/exhibitors/s-gifts") is True
    assert crawler._is_exhibitor_profile_url("https://example.com/brands/acme") is True
    assert crawler._is_exhibitor_profile_url("https://example.com/companies/acme-ltd") is True
    # Listing pages and A-Z tabs are NOT profiles
    assert crawler._is_exhibitor_profile_url("https://www.springfair.com/exhibitors") is False
    assert crawler._is_exhibitor_profile_url("https://www.springfair.com/exhibitors/l") is False
    assert crawler._is_exhibitor_profile_url("https://www.springfair.com/exhibitors/categories") is False
    # Atlanta numeric form still works
    atl = ExhibitorCrawler(start_url="https://www.atlantamarket.com/exhibitor/Directory")
    assert atl._is_exhibitor_profile_url("https://www.atlantamarket.com/exhibitor/118533") is True
    assert atl._is_exhibitor_profile_url("https://www.atlantamarket.com/exhibitor") is False


class _StubEl:
    def __init__(self, text):
        self._text = text

    def inner_text(self):
        return self._text


class _StubPage:
    """Minimal Page stub for name-extraction tests."""

    def __init__(self, h1=None, title=""):
        self._h1 = h1
        self._title = title

    def query_selector(self, sel):
        if sel == "h1" and self._h1 is not None:
            return _StubEl(self._h1)
        return None

    def title(self):
        return self._title


def test_extract_profile_name_prefers_anchor():
    crawler = ExhibitorCrawler(start_url="https://example.com/x")
    page = _StubPage(h1="H1 Name", title="T - Site")
    assert crawler._extract_profile_name(page, "https://example.com/exhibitor/1", "A & B Home Group") == "A & B Home Group"


def test_extract_profile_name_falls_back_to_title():
    # Hyve case: empty anchor + generic h1 -> use <title>
    crawler = ExhibitorCrawler(start_url="https://www.springfair.com/exhibitors")
    page = _StubPage(h1="Exhibitors", title="3D Studio Gifts - Spring Fair 2027")
    assert crawler._extract_profile_name(page, "https://www.springfair.com/exhibitors/3d-studio-gifts", "") == "3D Studio Gifts"


def test_extract_profile_name_rejects_junk():
    crawler = ExhibitorCrawler(start_url="https://example.com/x")
    assert crawler._extract_profile_name(_StubPage(h1="Exhibitors", title="Exhibitors"), "u", "") is None


def test_crawler_normalize_url():
    crawler = ExhibitorCrawler(start_url="https://example.com/exhibitors")
    assert crawler._normalize_url("https://example.com/company/abc/") == "https://example.com/company/abc"
    assert crawler._normalize_url("https://example.com/company/abc#section") == "https://example.com/company/abc"
    assert crawler._normalize_url("https://EXAMPLE.com/company/abc") == "https://example.com/company/abc"
    # query strings are kept: letter tabs are distinct pages
    assert crawler._normalize_url("https://www.springfair.com/exhibitors?azletter=A") == \
        "https://www.springfair.com/exhibitors?azletter=a"
    assert crawler._normalize_url("https://www.springfair.com/exhibitors?azletter=A") != \
        crawler._normalize_url("https://www.springfair.com/exhibitors?azletter=B")


def test_crawler_is_social_media():
    crawler = ExhibitorCrawler(start_url="https://example.com/exhibitors")
    assert crawler._is_social_media("https://www.facebook.com/example") is True
    assert crawler._is_social_media("https://www.linkedin.com/company/example") is True
    assert crawler._is_social_media("https://www.instagram.com/example") is True
    assert crawler._is_social_media("https://www.example.com") is False


def test_clean_booth_text_stand_codes():
    assert ExhibitorCrawler._clean_booth_text("4G83") == "4G83"
    assert ExhibitorCrawler._clean_booth_text("B1 11-B2") == "B1 11-B2"
    assert ExhibitorCrawler._clean_booth_text(
        "Hall: Halls 2 - 3 + 3a Stand: 3W15") == "3W15"
    assert ExhibitorCrawler._clean_booth_text(
        "Hall: Halls 6,7,8 Stand: 6A30") == "6A30"
    assert ExhibitorCrawler._clean_booth_text("1G01-1J02") == "1G01-1J02"


def test_needs_website_crawl_adaptive():
    full = {"website": "https://example.com",
            "emails": ["a@example.com"], "phones": ["+1234567890"]}
    assert ExhibitorCrawler.needs_website_crawl(full) is False
    missing_phone = {"website": "https://example.com",
                     "emails": ["a@example.com"], "phones": []}
    assert ExhibitorCrawler.needs_website_crawl(missing_phone) is True
    missing_email = {"website": "https://example.com",
                     "emails": [], "phones": ["+1234567890"]}
    assert ExhibitorCrawler.needs_website_crawl(missing_email) is True
    no_website = {"website": None, "emails": [], "phones": []}
    assert ExhibitorCrawler.needs_website_crawl(no_website) is False
    bare = {"website": "https://example.com", "emails": [], "phones": []}
    assert ExhibitorCrawler.needs_website_crawl(bare) is True


def test_slice_profiles_chunks():
    items = list(range(250))
    c = ExhibitorCrawler(start_url="https://example.com/x",
                         max_profiles=100, profile_offset=0)
    assert c._slice_profiles(items) == list(range(100))
    c2 = ExhibitorCrawler(start_url="https://example.com/x",
                          max_profiles=100, profile_offset=100)
    assert c2._slice_profiles(items) == list(range(100, 200))
    c3 = ExhibitorCrawler(start_url="https://example.com/x",
                          max_profiles=100, profile_offset=200)
    assert c3._slice_profiles(items) == list(range(200, 250))
    c_all = ExhibitorCrawler(start_url="https://example.com/x")
    assert c_all._slice_profiles(items) == items
    c_off = ExhibitorCrawler(start_url="https://example.com/x", profile_offset=50)
    assert c_off._slice_profiles(items) == list(range(50, 250))


def test_slice_beyond_end_records_error():
    c = ExhibitorCrawler(start_url="https://example.com/x",
                         max_profiles=100, profile_offset=500)
    assert c._slice_profiles([1, 2, 3]) == []
    assert c.stats.errors == 1
    assert "offset 500" in c.stats.error_details[0]


def test_expand_page_sequences():
    from app.services.crawler import _expand_page_sequences
    urls = [
        "https://www.hpmkt.com/ExhibitorDirectory?pageindex=1",
        "https://www.hpmkt.com/ExhibitorDirectory?pageindex=2",
        "https://www.hpmkt.com/ExhibitorDirectory?pageindex=176",
    ]
    out = _expand_page_sequences(urls, cap=200)
    assert len(out) == 176
    nums = sorted(int(u.split("pageindex=")[1]) for u in out)
    assert nums == list(range(1, 177))
    # capped synthesis keeps discovered links: 1..10 plus the found 176
    capped = _expand_page_sequences(urls, cap=10)
    assert sorted(int(u.split("pageindex=")[1]) for u in capped) == list(range(1, 11)) + [176]
    assert _expand_page_sequences(["https://x.example/about"]) == ["https://x.example/about"]


class _FakeEl:
    def __init__(self, href):
        self._href = href

    def get_attribute(self, name):
        return self._href


class _FakePage:
    def __init__(self, url, hrefs):
        self.url = url
        self._hrefs = hrefs

    def query_selector_all(self, sel):
        return [_FakeEl(h) for h in self._hrefs]


def test_pagination_stays_in_listing():
    crawler = ExhibitorCrawler(start_url="https://www.hpmkt.com/ExhibitorDirectory")
    page = _FakePage(
        "https://www.hpmkt.com/ExhibitorDirectory",
        [
            "/ExhibitorDirectory?pageindex=1",
            "/ExhibitorDirectory?pageindex=2",
            "/ExhibitorDirectory?pageindex=176",
            "/visit/travel",
            "/exhibitor/12345",
            "https://www.facebook.com/sharer/sharer.php?u=x",
        ],
    )
    out = crawler._find_pagination(page)
    assert any("pageindex=176" in u for u in out)
    assert not any("visit/travel" in u for u in out)
    assert not any("facebook" in u for u in out)
    # profile links are collected as profiles, never as pagination
    assert not any("/exhibitor/12345" in u for u in out)


def test_pagination_rejects_cross_section():
    crawler = ExhibitorCrawler(start_url="https://example.com/fair/exhibitors")
    page = _FakePage(
        "https://example.com/fair/exhibitors",
        ["/fair/about", "/fair/exhibitors?page=2", "/other/list?page=3"],
    )
    out = crawler._find_pagination(page)
    assert out == ["https://example.com/fair/exhibitors?page=2"]


def test_collect_returns_counts():
    crawler = ExhibitorCrawler(start_url="https://example.com/fair/exhibitors")

    class _T(_FakeEl):
        def __init__(self, href, text=""):
            super().__init__(href)
            self._text = text

        def inner_text(self):
            return self._text

    class _P(_FakePage):
        def query_selector_all(self, sel):
            return [_T("/fair/exhibitors", "Exhibitors"),
                    _T("/fair/company/abc", "ABC Corp")]

    n_links, added = crawler._collect_profile_links(_P("https://example.com/fair/exhibitors", []))
    assert n_links == 2
    assert added == 1


def test_drop_shared_website_domains():
    data = (
        [{"company_name": f"Co {i}", "website": "https://venue.example/info"}
         for i in range(8)]
        + [{"company_name": "Real Co", "website": "https://realco.example"}]
    )
    cleaned = ExhibitorCrawler.drop_shared_website_domains(data, threshold=8)
    assert cleaned == 8
    assert all(d["website"] is None for d in data[:8])
    assert data[8]["website"] == "https://realco.example"


def test_drop_shared_domains_keeps_rare():
    data = [
        {"company_name": "A", "website": "https://venue.example/x"},
        {"company_name": "B", "website": "https://venue.example/y"},
        {"company_name": "C", "website": None},
    ]
    assert ExhibitorCrawler.drop_shared_website_domains(data, threshold=8) == 0
    assert data[0]["website"] == "https://venue.example/x"
