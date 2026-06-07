"""Tests for OceanService — real v3 API format, no mocks."""
from __future__ import annotations

import json

import pytest
import responses as resp

from src.models import Company


# ─── Shared fixtures / constants ──────────────────────────────────────────────

OCEAN_SEARCH_URL = "https://api.ocean.io/v3/search/companies"

# v3 item format: {"company": {...}, "relevance": "A"}
_ITEM_1 = {
    "company": {
        "domain": "adyen.com",
        "name": "Adyen",
        "industries": ["FinTech", "Financial Services"],
        "employeeCountOcean": 5123,
        "primaryCountry": "nl",
        "description": "Global payments platform",
    },
    "relevance": "A",
}

_ITEM_2 = {
    "company": {
        "domain": "checkout.com",
        "name": "Checkout.com",
        "industries": ["Payments"],
        "employeeCountOcean": 1700,
        "primaryCountry": "gb",
    },
    "relevance": "B",
}


def _svc(monkeypatch):
    monkeypatch.setenv("OCEAN_API_KEY", "test-ocean-key")
    monkeypatch.setenv("OCEAN_BASE_URL", "https://api.ocean.io")
    monkeypatch.setenv("OCEAN_LOOKALIKE_LIMIT", "10")
    from src.config import get_ocean
    get_ocean.cache_clear()
    from src.services.ocean_service import OceanService
    return OceanService()


def _wrap(items, total=None, cursor=None):
    """Build a v3 response envelope."""
    body = {
        "detail": "OK",
        "total": total if total is not None else len(items),
        "creditsUsed": len(items) * 0.2,
        "companies": items,
    }
    if cursor is not None:
        body["searchAfter"] = cursor
    return body


# ─── Key validation ───────────────────────────────────────────────────────────

class TestOceanKeyValidation:
    def test_run_raises_without_key(self, monkeypatch):
        monkeypatch.setenv("OCEAN_API_KEY", "")
        from src.config import get_ocean
        get_ocean.cache_clear()
        from src.services.ocean_service import OceanService
        with pytest.raises(EnvironmentError, match="OCEAN_API_KEY"):
            OceanService().run("stripe.com")

    def test_find_lookalikes_raises_without_key(self, monkeypatch):
        monkeypatch.setenv("OCEAN_API_KEY", "")
        from src.config import get_ocean
        get_ocean.cache_clear()
        from src.services.ocean_service import OceanService
        with pytest.raises(EnvironmentError, match="OCEAN_API_KEY"):
            OceanService().find_lookalikes("stripe.com")

    def test_search_lookalikes_raises_without_key(self, monkeypatch):
        monkeypatch.setenv("OCEAN_API_KEY", "")
        from src.config import get_ocean
        get_ocean.cache_clear()
        from src.services.ocean_service import OceanService
        with pytest.raises(EnvironmentError, match="OCEAN_API_KEY"):
            OceanService().search_lookalikes("stripe.com")


# ─── Request format ───────────────────────────────────────────────────────────

class TestOceanRequestFormat:
    @resp.activate
    def test_auth_sent_as_query_param_not_header(self, monkeypatch):
        """apiToken must appear in the query string, NOT in an Authorization header."""
        svc = _svc(monkeypatch)
        resp.add(resp.POST, OCEAN_SEARCH_URL, json=_wrap([_ITEM_1]), status=200)
        svc.find_lookalikes("stripe.com", limit=1)
        call = resp.calls[0]
        assert "apiToken=test-ocean-key" in call.request.url
        assert "Authorization" not in call.request.headers

    @resp.activate
    def test_request_body_uses_lookalike_domains_filter(self, monkeypatch):
        """Body must contain companiesFilters.lookalikeDomains as a flat string list."""
        svc = _svc(monkeypatch)
        resp.add(resp.POST, OCEAN_SEARCH_URL, json=_wrap([_ITEM_1]), status=200)
        svc.find_lookalikes("stripe.com", limit=1)
        body = json.loads(resp.calls[0].request.body)
        ld = body["companiesFilters"]["lookalikeDomains"]
        assert isinstance(ld, list)
        assert "stripe.com" in ld

    @resp.activate
    def test_no_from_field_in_first_page_request(self, monkeypatch):
        """v3 does not accept 'from' — first page has no 'from' or 'searchAfter'."""
        svc = _svc(monkeypatch)
        resp.add(resp.POST, OCEAN_SEARCH_URL, json=_wrap([_ITEM_1]), status=200)
        svc.find_lookalikes("stripe.com", limit=1)
        body = json.loads(resp.calls[0].request.body)
        assert "from" not in body
        assert "searchAfter" not in body

    @resp.activate
    def test_search_after_cursor_sent_on_second_page(self, monkeypatch):
        """When a cursor is provided, searchAfter must appear in the request body."""
        svc = _svc(monkeypatch)
        resp.add(
            resp.POST, OCEAN_SEARCH_URL,
            json=_wrap([_ITEM_1], total=50, cursor="cursor-abc"),
            status=200,
        )
        resp.add(
            resp.POST, OCEAN_SEARCH_URL,
            json=_wrap([_ITEM_2], total=50),
            status=200,
        )
        svc.find_lookalikes("stripe.com", limit=2)
        second_body = json.loads(resp.calls[1].request.body)
        assert second_body.get("searchAfter") == "cursor-abc"


# ─── Response parsing ─────────────────────────────────────────────────────────

class TestOceanResponseParsing:
    @resp.activate
    def test_employee_count_ocean_parsed(self, monkeypatch):
        """employeeCountOcean integer → employee_count."""
        svc = _svc(monkeypatch)
        resp.add(resp.POST, OCEAN_SEARCH_URL, json=_wrap([_ITEM_1]), status=200)
        result = svc.find_lookalikes("stripe.com", limit=1)
        assert result.companies[0].employee_count == 5123

    @resp.activate
    def test_primary_country_parsed(self, monkeypatch):
        """primaryCountry → company.country."""
        svc = _svc(monkeypatch)
        resp.add(resp.POST, OCEAN_SEARCH_URL, json=_wrap([_ITEM_1]), status=200)
        result = svc.find_lookalikes("stripe.com", limit=1)
        assert result.companies[0].country == "nl"

    @resp.activate
    def test_industries_first_item_as_industry(self, monkeypatch):
        """First element of industries[] → company.industry."""
        svc = _svc(monkeypatch)
        resp.add(resp.POST, OCEAN_SEARCH_URL, json=_wrap([_ITEM_1]), status=200)
        result = svc.find_lookalikes("stripe.com", limit=1)
        assert result.companies[0].industry == "FinTech"

    @resp.activate
    def test_relevance_a_maps_to_score_1(self, monkeypatch):
        """relevance='A' → similarity_score=1.0."""
        svc = _svc(monkeypatch)
        resp.add(resp.POST, OCEAN_SEARCH_URL, json=_wrap([_ITEM_1]), status=200)
        result = svc.find_lookalikes("stripe.com", limit=1)
        assert result.companies[0].similarity_score == pytest.approx(1.0)

    @resp.activate
    def test_relevance_b_maps_to_score_08(self, monkeypatch):
        """relevance='B' → similarity_score=0.8."""
        svc = _svc(monkeypatch)
        resp.add(resp.POST, OCEAN_SEARCH_URL, json=_wrap([_ITEM_2]), status=200)
        result = svc.find_lookalikes("stripe.com", limit=1)
        assert result.companies[0].similarity_score == pytest.approx(0.8)

    @resp.activate
    def test_hits_without_domain_skipped(self, monkeypatch):
        """Items missing a domain should be silently dropped."""
        svc = _svc(monkeypatch)
        bad_item = {"company": {"name": "No Domain Corp"}, "relevance": "A"}
        resp.add(
            resp.POST, OCEAN_SEARCH_URL,
            json=_wrap([bad_item, _ITEM_1], total=2),
            status=200,
        )
        result = svc.find_lookalikes("stripe.com", limit=5)
        assert len(result.companies) == 1
        assert result.companies[0].domain == "adyen.com"

    @resp.activate
    def test_total_found_populated(self, monkeypatch):
        svc = _svc(monkeypatch)
        resp.add(
            resp.POST, OCEAN_SEARCH_URL,
            json=_wrap([_ITEM_1], total=15599),
            status=200,
        )
        result = svc.find_lookalikes("stripe.com", limit=1)
        assert result.total_found == 15599

    @resp.activate
    def test_description_mapped(self, monkeypatch):
        svc = _svc(monkeypatch)
        resp.add(resp.POST, OCEAN_SEARCH_URL, json=_wrap([_ITEM_1]), status=200)
        result = svc.find_lookalikes("stripe.com", limit=1)
        assert result.companies[0].description == "Global payments platform"


# ─── Error handling ───────────────────────────────────────────────────────────

class TestOceanErrorHandling:
    @resp.activate
    def test_401_raises_permission_error(self, monkeypatch):
        svc = _svc(monkeypatch)
        resp.add(resp.POST, OCEAN_SEARCH_URL, json={}, status=401)
        with pytest.raises(PermissionError, match="Invalid API token"):
            svc.find_lookalikes("stripe.com")

    @resp.activate
    def test_400_raises_value_error(self, monkeypatch):
        svc = _svc(monkeypatch)
        resp.add(resp.POST, OCEAN_SEARCH_URL, json={"message": "bad filter"}, status=400)
        with pytest.raises(ValueError, match="bad request"):
            svc.find_lookalikes("stripe.com")

    @resp.activate
    def test_429_waits_and_retries(self, monkeypatch, mocker):
        svc = _svc(monkeypatch)
        sleep_mock = mocker.patch("src.services.ocean_service.time.sleep")
        resp.add(
            resp.POST, OCEAN_SEARCH_URL,
            json={}, status=429,
            headers={"Retry-After": "1"},
        )
        resp.add(resp.POST, OCEAN_SEARCH_URL, json=_wrap([_ITEM_1]), status=200)
        result = svc.find_lookalikes("stripe.com", limit=1)
        sleep_mock.assert_called_once_with(1.0)
        assert len(result.companies) == 1


# ─── Company model — unit tests on the static parser ─────────────────────────

class TestOceanCompanyParser:
    def test_parse_item_full(self):
        from src.services.ocean_service import OceanService
        company = OceanService._parse_company(_ITEM_1)
        assert company is not None
        assert company.domain == "adyen.com"
        assert company.name == "Adyen"
        assert company.industry == "FinTech"
        assert company.employee_count == 5123
        assert company.country == "nl"
        assert company.description == "Global payments platform"
        assert company.similarity_score == pytest.approx(1.0)

    def test_parse_item_missing_domain_returns_none(self):
        from src.services.ocean_service import OceanService
        item = {"company": {"name": "No Domain"}, "relevance": "A"}
        assert OceanService._parse_company(item) is None

    def test_parse_item_relevance_b(self):
        from src.services.ocean_service import OceanService
        company = OceanService._parse_company(_ITEM_2)
        assert company is not None
        assert company.similarity_score == pytest.approx(0.8)

    def test_parse_item_unknown_relevance(self):
        from src.services.ocean_service import OceanService
        item = {**_ITEM_1, "relevance": "Z"}
        company = OceanService._parse_company(item)
        assert company is not None
        assert company.similarity_score is None

    def test_parse_bare_company_dict(self):
        """_parse_company also handles a bare company dict (no 'company' wrapper)."""
        from src.services.ocean_service import OceanService
        bare = {
            "domain": "paddle.com",
            "name": "Paddle",
            "employeeCountOcean": 400,
            "primaryCountry": "gb",
            "score": 0.74,
        }
        company = OceanService._parse_company(bare)
        assert company is not None
        assert company.domain == "paddle.com"
        assert company.employee_count == 400
        assert company.similarity_score == pytest.approx(0.74)
