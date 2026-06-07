"""Unit tests for EazyReachService (HTTP mocking via responses library)."""
from __future__ import annotations

import pytest
import responses as resp

from src.models import Contact, VerificationStatus
from src.services.eazyreach_service import EazyReachService

_ENRICH_URL = "https://api.eazyreach.io/v1/email/find"


def _svc(monkeypatch):
    monkeypatch.setenv("EAZYREACH_API_KEY", "test-key")
    from src.config import get_eazyreach
    get_eazyreach.cache_clear()
    return EazyReachService()


# ─── Key validation ───────────────────────────────────────────────────────────


class TestEazyReachKeyValidation:
    def test_run_raises_without_key(self, monkeypatch):
        monkeypatch.setenv("EAZYREACH_API_KEY", "")
        from src.config import get_eazyreach
        get_eazyreach.cache_clear()
        with pytest.raises(EnvironmentError, match="EAZYREACH_API_KEY"):
            EazyReachService().run([Contact(name="X", linkedin_url="https://linkedin.com/in/x")])

    def test_enrich_one_raises_without_key(self, monkeypatch):
        monkeypatch.setenv("EAZYREACH_API_KEY", "")
        from src.config import get_eazyreach
        get_eazyreach.cache_clear()
        with pytest.raises(EnvironmentError, match="EAZYREACH_API_KEY"):
            EazyReachService().enrich_one(Contact(name="X", linkedin_url="https://linkedin.com/in/x"))


# ─── HTTP behaviour ───────────────────────────────────────────────────────────


class TestEazyReachServiceHTTP:
    @resp.activate
    def test_successful_enrichment(self, monkeypatch):
        svc = _svc(monkeypatch)
        resp.add(
            resp.POST, _ENRICH_URL,
            json={
                "email": "john@stripe.com",
                "status": "verified",
                "confidence": 0.97,
                "phone": "+1-555-0100",
                "location": "San Francisco, CA",
                "seniority": "director",
                "department": "engineering",
            },
            status=200,
        )
        contact = Contact(
            name="John Doe",
            linkedin_url="https://linkedin.com/in/johndoe",
            company_domain="stripe.com",
        )
        result = svc.enrich_one(contact)
        assert result.verified_email == "john@stripe.com"
        assert result.email_status == VerificationStatus.VERIFIED
        assert result.phone == "+1-555-0100"
        assert result.seniority == "director"

    @resp.activate
    def test_404_returns_contact_with_unknown_status(self, monkeypatch):
        svc = _svc(monkeypatch)
        resp.add(resp.POST, _ENRICH_URL, json={}, status=404)
        contact = Contact(name="X", linkedin_url="https://linkedin.com/in/x")
        result = svc.enrich_one(contact)
        assert result.verified_email is None
        assert result.email_status == VerificationStatus.UNKNOWN

    @resp.activate
    def test_401_raises_permission_error(self, monkeypatch):
        svc = _svc(monkeypatch)
        resp.add(resp.POST, _ENRICH_URL, json={}, status=401)
        contact = Contact(name="X", linkedin_url="https://linkedin.com/in/x")
        with pytest.raises(PermissionError, match="EazyReach"):
            svc.enrich_one(contact)

    def test_no_linkedin_url_skips_http(self, monkeypatch):
        svc = _svc(monkeypatch)
        contact = Contact(name="No LinkedIn")
        result = svc.enrich_one(contact)
        assert result.verified_email is None
