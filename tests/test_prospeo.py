"""Tests for ProspeoService — real API format, no mocks."""
from __future__ import annotations

import json

import pytest
import responses as resp

from src.models import VerificationStatus


# ─── Constants / helpers ──────────────────────────────────────────────────────

BASE = "https://api.prospeo.io"
SEARCH_PERSON_URL = f"{BASE}/search-person"
ENRICH_PERSON_URL = f"{BASE}/enrich-person"
BULK_ENRICH_URL = f"{BASE}/bulk-enrich-person"
ENRICH_COMPANY_URL = f"{BASE}/enrich-company"
ACCOUNT_INFO_URL = f"{BASE}/account-information"

_PERSON_RESULT = {
    "person": {
        "person_id": "aaa111",
        "first_name": "John",
        "last_name": "Doe",
        "full_name": "John Doe",
        "linkedin_url": "https://www.linkedin.com/in/johndoe",
        "current_job_title": "Vice President of Sales",
        # email.revealed=false in /search-person — address is masked until enriched
        "email": {"status": "VERIFIED", "revealed": False, "email": "j***@stripe.com"},
        "location": {"country": "United States", "country_code": "US", "city": "San Francisco"},
        "seniority": "Vice President",
        "department": "Sales",
    },
    "company": {"name": "Stripe", "domain": "stripe.com", "website": "https://stripe.com"},
}

_SEARCH_RESPONSE = {
    "error": False,
    "results": [_PERSON_RESULT],
    "pagination": {
        "current_page": 1, "per_page": 25, "total_page": 3, "total_count": 72,
    },
}

_ENRICH_RESPONSE = {
    "error": False,
    "person": {
        "full_name": "Jane Smith",
        "first_name": "Jane",
        "last_name": "Smith",
        "linkedin_url": "https://www.linkedin.com/in/janesmith",
        "current_job_title": "CEO",
        "email": {"status": "VERIFIED", "revealed": True, "email": "jane@adyen.com"},
        "location": {"country": "Netherlands", "city": "Amsterdam"},
    },
    "company": {"name": "Adyen", "website": "https://adyen.com"},
}

_ACCOUNT_RESPONSE = {
    "error": False,
    "response": {
        "current_plan": "STARTER",
        "remaining_credits": 99,
        "used_credits": 1,
        "next_quota_renewal_days": 25,
    },
}


def _svc(monkeypatch):
    monkeypatch.setenv("PROSPEO_API_KEY", "test-prospeo-key")
    monkeypatch.setenv("PROSPEO_BASE_URL", BASE)
    monkeypatch.setenv("PROSPEO_CONTACTS_PER_DOMAIN", "25")
    monkeypatch.setenv("PROSPEO_MAX_PAGES", "4")
    monkeypatch.setenv("PROSPEO_ONLY_VERIFIED_EMAIL", "true")
    from src.config import get_prospeo
    get_prospeo.cache_clear()
    from src.services.prospeo_service import ProspeoService
    return ProspeoService()


# ─── Key validation ───────────────────────────────────────────────────────────

class TestProspeoKeyValidation:
    def test_search_person_raises_without_key(self, monkeypatch):
        monkeypatch.setenv("PROSPEO_API_KEY", "")
        from src.config import get_prospeo
        get_prospeo.cache_clear()
        from src.services.prospeo_service import ProspeoService
        with pytest.raises(EnvironmentError, match="PROSPEO_API_KEY"):
            ProspeoService().search_person("stripe.com")

    def test_run_raises_without_key(self, monkeypatch):
        monkeypatch.setenv("PROSPEO_API_KEY", "")
        from src.config import get_prospeo
        get_prospeo.cache_clear()
        from src.services.prospeo_service import ProspeoService
        with pytest.raises(EnvironmentError, match="PROSPEO_API_KEY"):
            ProspeoService().run("stripe.com")

    def test_enrich_person_raises_without_key(self, monkeypatch):
        monkeypatch.setenv("PROSPEO_API_KEY", "")
        from src.config import get_prospeo
        get_prospeo.cache_clear()
        from src.services.prospeo_service import ProspeoService
        with pytest.raises(EnvironmentError, match="PROSPEO_API_KEY"):
            ProspeoService().enrich_person("https://linkedin.com/in/john")

    def test_enrich_company_raises_without_key(self, monkeypatch):
        monkeypatch.setenv("PROSPEO_API_KEY", "")
        from src.config import get_prospeo
        get_prospeo.cache_clear()
        from src.services.prospeo_service import ProspeoService
        with pytest.raises(EnvironmentError, match="PROSPEO_API_KEY"):
            ProspeoService().enrich_company("adyen.com")


# ─── Request format ───────────────────────────────────────────────────────────

class TestProspeoRequestFormat:
    @resp.activate
    def test_auth_sent_as_x_key_header(self, monkeypatch):
        """`X-KEY` header carries the API key, not Authorization."""
        svc = _svc(monkeypatch)
        resp.add(resp.POST, SEARCH_PERSON_URL, json=_SEARCH_RESPONSE, status=200)
        svc.search_person("stripe.com")
        call = resp.calls[0]
        assert call.request.headers.get("X-KEY") == "test-prospeo-key"
        assert "Authorization" not in call.request.headers

    @resp.activate
    def test_search_person_body_has_page_and_domain_filter(self, monkeypatch):
        svc = _svc(monkeypatch)
        resp.add(resp.POST, SEARCH_PERSON_URL, json=_SEARCH_RESPONSE, status=200)
        svc.search_person("stripe.com", page=2)
        body = json.loads(resp.calls[0].request.body)
        assert body["page"] == 2
        assert "filters" in body
        # v2 format: company.websites.include (NOT company_website.include)
        assert "company" in body["filters"]
        assert "stripe.com" in body["filters"]["company"]["websites"]["include"]

    @resp.activate
    def test_enrich_person_body_has_linkedin_url(self, monkeypatch):
        svc = _svc(monkeypatch)
        resp.add(resp.POST, ENRICH_PERSON_URL, json=_ENRICH_RESPONSE, status=200)
        svc.enrich_person("https://www.linkedin.com/in/janesmith")
        body = json.loads(resp.calls[0].request.body)
        assert body["data"]["linkedin_url"] == "https://www.linkedin.com/in/janesmith"
        assert body.get("only_verified_email") is True

    @resp.activate
    def test_bulk_enrich_chunks_over_50(self, monkeypatch):
        """60 URLs → 2 HTTP requests (50 + 10)."""
        svc = _svc(monkeypatch)
        bulk_resp = {"error": False, "matched": [], "not_matched": [], "invalid_datapoints": []}
        resp.add(resp.POST, BULK_ENRICH_URL, json=bulk_resp, status=200)
        resp.add(resp.POST, BULK_ENRICH_URL, json=bulk_resp, status=200)
        urls = [f"https://linkedin.com/in/person{i}" for i in range(60)]
        svc.bulk_enrich_persons(urls)
        assert len(resp.calls) == 2


# ─── /search-person response parsing ─────────────────────────────────────────

class TestProspeoSearchPerson:
    @resp.activate
    def test_contact_parsed_correctly(self, monkeypatch):
        svc = _svc(monkeypatch)
        resp.add(resp.POST, SEARCH_PERSON_URL, json=_SEARCH_RESPONSE, status=200)
        result = svc.search_person("stripe.com")
        assert len(result.contacts) == 1
        c = result.contacts[0]
        assert c.name == "John Doe"
        assert c.first_name == "John"
        assert c.last_name == "Doe"
        assert c.title == "Vice President of Sales"
        # email is masked (revealed=false) in /search-person — should not be stored
        assert c.email is None
        assert c.email_status == VerificationStatus.VERIFIED
        assert c.linkedin_url == "https://www.linkedin.com/in/johndoe"
        assert c.company == "Stripe"
        assert c.company_domain == "stripe.com"  # uses company.domain directly

    @resp.activate
    def test_pagination_fields_populated(self, monkeypatch):
        svc = _svc(monkeypatch)
        resp.add(resp.POST, SEARCH_PERSON_URL, json=_SEARCH_RESPONSE, status=200)
        result = svc.search_person("stripe.com", page=1)
        assert result.page == 1
        assert result.total_found == 72
        assert result.has_more is True

    @resp.activate
    def test_last_page_has_more_false(self, monkeypatch):
        svc = _svc(monkeypatch)
        last_page = {
            **_SEARCH_RESPONSE,
            "pagination": {"current_page": 3, "per_page": 25, "total_page": 3, "total_count": 72},
        }
        resp.add(resp.POST, SEARCH_PERSON_URL, json=last_page, status=200)
        result = svc.search_person("stripe.com", page=3)
        assert result.has_more is False

    @resp.activate
    def test_contact_without_name_skipped(self, monkeypatch):
        svc = _svc(monkeypatch)
        nameless = {
            "person": {"first_name": "", "last_name": "", "full_name": ""},
            "company": {"name": "Stripe"},
        }
        no_name_resp = {**_SEARCH_RESPONSE, "results": [nameless]}
        resp.add(resp.POST, SEARCH_PERSON_URL, json=no_name_resp, status=200)
        result = svc.search_person("stripe.com")
        assert len(result.contacts) == 0

    @resp.activate
    def test_error_true_raises(self, monkeypatch):
        svc = _svc(monkeypatch)
        resp.add(
            resp.POST, SEARCH_PERSON_URL,
            json={"error": True, "message": "Quota exceeded"},
            status=200,
        )
        with pytest.raises(RuntimeError, match="Quota exceeded"):
            svc.search_person("stripe.com")

    @resp.activate
    def test_pagination_walks_multiple_pages(self, monkeypatch):
        svc = _svc(monkeypatch)
        page1 = {
            **_SEARCH_RESPONSE,
            "pagination": {"current_page": 1, "per_page": 25, "total_page": 2, "total_count": 2},
        }
        page2_person = {
            **_PERSON_RESULT,
            "person": {**_PERSON_RESULT["person"], "full_name": "Jane Doe"},
        }
        page2 = {
            "error": False,
            "results": [page2_person],
            "pagination": {"current_page": 2, "per_page": 25, "total_page": 2, "total_count": 2},
        }
        resp.add(resp.POST, SEARCH_PERSON_URL, json=page1, status=200)
        resp.add(resp.POST, SEARCH_PERSON_URL, json=page2, status=200)
        result = svc.search_all_pages("stripe.com", max_contacts=50)
        assert len(result.contacts) == 2
        assert len(resp.calls) == 2


# ─── /enrich-person response parsing ─────────────────────────────────────────

class TestProspeoEnrichPerson:
    @resp.activate
    def test_enrich_returns_verified_email(self, monkeypatch):
        svc = _svc(monkeypatch)
        resp.add(resp.POST, ENRICH_PERSON_URL, json=_ENRICH_RESPONSE, status=200)
        contact = svc.enrich_person("https://www.linkedin.com/in/janesmith")
        assert contact is not None
        assert contact.verified_email == "jane@adyen.com"
        assert contact.email_status == VerificationStatus.VERIFIED

    @resp.activate
    def test_enrich_returns_none_on_404(self, monkeypatch):
        svc = _svc(monkeypatch)
        resp.add(resp.POST, ENRICH_PERSON_URL, json={}, status=404)
        result = svc.enrich_person("https://linkedin.com/in/ghost")
        assert result is None

    @resp.activate
    def test_enrich_none_email_when_not_revealed(self, monkeypatch):
        svc = _svc(monkeypatch)
        not_revealed = {
            **_ENRICH_RESPONSE,
            "person": {
                **_ENRICH_RESPONSE["person"],
                "email": {"status": "VERIFIED", "revealed": False, "email": None},
            },
        }
        resp.add(resp.POST, ENRICH_PERSON_URL, json=not_revealed, status=200)
        contact = svc.enrich_person("https://linkedin.com/in/janesmith")
        assert contact is not None
        assert contact.verified_email is None


# ─── /enrich-company ─────────────────────────────────────────────────────────

class TestProspeoEnrichCompany:
    @resp.activate
    def test_enrich_company_returns_company(self, monkeypatch):
        svc = _svc(monkeypatch)
        payload = {
            "error": False,
            "company": {
                "name": "Adyen",
                "website": "https://adyen.com",
                "industry": "Fintech",
                "employee_count": 3500,
                "location": {"country": "Netherlands"},
            },
        }
        resp.add(resp.POST, ENRICH_COMPANY_URL, json=payload, status=200)
        company = svc.enrich_company("adyen.com")
        assert company is not None
        assert company.name == "Adyen"
        assert company.domain == "adyen.com"
        assert company.industry == "Fintech"

    @resp.activate
    def test_enrich_company_404_returns_none(self, monkeypatch):
        svc = _svc(monkeypatch)
        resp.add(resp.POST, ENRICH_COMPANY_URL, json={}, status=404)
        assert svc.enrich_company("unknown.xyz") is None


# ─── /account-information ────────────────────────────────────────────────────

class TestProspeoAccountInfo:
    @resp.activate
    def test_account_info_returns_credits(self, monkeypatch):
        svc = _svc(monkeypatch)
        resp.add(resp.GET, ACCOUNT_INFO_URL, json=_ACCOUNT_RESPONSE, status=200)
        info = svc.get_account_info()
        assert info["current_plan"] == "STARTER"
        assert info["remaining_credits"] == 99

    @resp.activate
    def test_account_info_401_raises(self, monkeypatch):
        svc = _svc(monkeypatch)
        resp.add(resp.GET, ACCOUNT_INFO_URL, json={}, status=401)
        with pytest.raises(PermissionError, match="Invalid API key"):
            svc.get_account_info()


# ─── Error handling ───────────────────────────────────────────────────────────

class TestProspeoErrorHandling:
    @resp.activate
    def test_401_raises_permission_error(self, monkeypatch):
        svc = _svc(monkeypatch)
        resp.add(resp.POST, SEARCH_PERSON_URL, json={}, status=401)
        with pytest.raises(PermissionError, match="Invalid API key"):
            svc.search_person("stripe.com")

    @resp.activate
    def test_429_waits_and_retries(self, monkeypatch, mocker):
        svc = _svc(monkeypatch)
        sleep_mock = mocker.patch("src.services.prospeo_service.time.sleep")
        resp.add(
            resp.POST, SEARCH_PERSON_URL,
            json={}, status=429,
            headers={"Retry-After": "2"},
        )
        resp.add(resp.POST, SEARCH_PERSON_URL, json=_SEARCH_RESPONSE, status=200)
        result = svc.search_person("stripe.com")
        sleep_mock.assert_called_once_with(2.0)
        assert len(result.contacts) == 1


# ─── Bulk enrich response parsing ────────────────────────────────────────────

class TestProspecBulkEnrich:
    @resp.activate
    def test_matched_contacts_returned(self, monkeypatch):
        svc = _svc(monkeypatch)
        bulk_resp = {
            "error": False,
            "matched": [
                {
                    "identifier": "0",
                    "person": {
                        "full_name": "John Doe",
                        "email": {"status": "VERIFIED", "revealed": True, "email": "john@stripe.com"},
                        "linkedin_url": "https://linkedin.com/in/johndoe",
                    },
                    "company": {"name": "Stripe", "website": "https://stripe.com"},
                }
            ],
            "not_matched": ["1"],
            "invalid_datapoints": [],
        }
        resp.add(resp.POST, BULK_ENRICH_URL, json=bulk_resp, status=200)
        contacts = svc.bulk_enrich_persons(
            ["https://linkedin.com/in/johndoe", "https://linkedin.com/in/bad"]
        )
        assert len(contacts) == 1
        assert contacts[0].verified_email == "john@stripe.com"
