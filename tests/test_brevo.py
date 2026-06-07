"""Tests for BrevoService — real API format, no mocks."""
from __future__ import annotations

import json

import pytest
import responses as resp

from src.models import Contact, SendStatus


# ─── Constants / helpers ──────────────────────────────────────────────────────

BASE = "https://api.brevo.com/v3"
SEND_URL = f"{BASE}/smtp/email"
SENDERS_URL = f"{BASE}/senders"

_CONTACT = Contact(
    name="John Doe",
    first_name="John",
    title="VP Sales",
    company="Stripe",
    company_domain="stripe.com",
    verified_email="john@stripe.com",
)

_CONTACT_NO_EMAIL = Contact(
    name="Jane Smith",
    title="CEO",
    company="Adyen",
)


def _svc(monkeypatch, sender_email: str = "gurukiran.s@seedlinglabs.com"):
    monkeypatch.setenv("BREVO_API_KEY", "test-brevo-key")
    monkeypatch.setenv("BREVO_BASE_URL", BASE)
    monkeypatch.setenv("BREVO_SENDER_NAME", "Gurukiran")
    monkeypatch.setenv("BREVO_SENDER_EMAIL", sender_email)
    from src.config import get_brevo
    get_brevo.cache_clear()
    from src.services.brevo_service import BrevoService
    return BrevoService()


# ─── Key validation ───────────────────────────────────────────────────────────

class TestBrevoKeyValidation:
    def test_send_raises_without_key(self, monkeypatch):
        monkeypatch.setenv("BREVO_API_KEY", "")
        from src.config import get_brevo
        get_brevo.cache_clear()
        from src.services.brevo_service import BrevoService
        with pytest.raises(EnvironmentError, match="BREVO_API_KEY"):
            BrevoService().send_one(_CONTACT)

    def test_run_raises_without_key(self, monkeypatch):
        monkeypatch.setenv("BREVO_API_KEY", "")
        from src.config import get_brevo
        get_brevo.cache_clear()
        from src.services.brevo_service import BrevoService
        with pytest.raises(EnvironmentError, match="BREVO_API_KEY"):
            BrevoService().run([_CONTACT])

    def test_verify_sender_raises_without_key(self, monkeypatch):
        monkeypatch.setenv("BREVO_API_KEY", "")
        from src.config import get_brevo
        get_brevo.cache_clear()
        from src.services.brevo_service import BrevoService
        with pytest.raises(EnvironmentError, match="BREVO_API_KEY"):
            BrevoService().verify_sender()


# ─── Request format ───────────────────────────────────────────────────────────

class TestBrevoRequestFormat:
    @resp.activate
    def test_auth_sent_as_api_key_header(self, monkeypatch):
        """`api-key` header carries the key — not Authorization."""
        svc = _svc(monkeypatch)
        resp.add(resp.POST, SEND_URL, json={"messageId": "<id@brevo.com>"}, status=201)
        svc.send_one(_CONTACT)
        call = resp.calls[0]
        assert call.request.headers.get("api-key") == "test-brevo-key"
        assert "Authorization" not in call.request.headers

    @resp.activate
    def test_request_body_structure(self, monkeypatch):
        """POST body must contain sender, to, subject, and textContent."""
        svc = _svc(monkeypatch)
        resp.add(resp.POST, SEND_URL, json={"messageId": "<id@brevo.com>"}, status=201)
        svc.send_one(_CONTACT)
        body = json.loads(resp.calls[0].request.body)
        assert body["sender"]["email"] == "gurukiran.s@seedlinglabs.com"
        assert body["sender"]["name"] == "Gurukiran"
        assert body["to"][0]["email"] == "john@stripe.com"
        assert body["to"][0]["name"] == "John Doe"
        assert "subject" in body
        assert "textContent" in body

    @resp.activate
    def test_subject_contains_company_name(self, monkeypatch):
        svc = _svc(monkeypatch)
        resp.add(resp.POST, SEND_URL, json={"messageId": "<id@brevo.com>"}, status=201)
        svc.send_one(_CONTACT)
        body = json.loads(resp.calls[0].request.body)
        assert "Stripe" in body["subject"]

    @resp.activate
    def test_body_contains_first_name(self, monkeypatch):
        svc = _svc(monkeypatch)
        resp.add(resp.POST, SEND_URL, json={"messageId": "<id@brevo.com>"}, status=201)
        svc.send_one(_CONTACT)
        body = json.loads(resp.calls[0].request.body)
        assert "John" in body["textContent"]

    @resp.activate
    def test_uses_verified_email_over_plain_email(self, monkeypatch):
        """verified_email is preferred over email when both are present."""
        svc = _svc(monkeypatch)
        contact = Contact(
            name="X", email="old@example.com", verified_email="new@example.com", company="Ex"
        )
        resp.add(resp.POST, SEND_URL, json={"messageId": "<id@brevo.com>"}, status=201)
        svc.send_one(contact)
        body = json.loads(resp.calls[0].request.body)
        assert body["to"][0]["email"] == "new@example.com"


# ─── Successful send ──────────────────────────────────────────────────────────

class TestBrevoSuccessfulSend:
    @resp.activate
    def test_201_returns_sent_status(self, monkeypatch):
        svc = _svc(monkeypatch)
        resp.add(resp.POST, SEND_URL, json={"messageId": "<abc@brevo.com>"}, status=201)
        result = svc.send_one(_CONTACT)
        assert result.status == SendStatus.SENT
        assert result.message_id == "<abc@brevo.com>"
        assert result.email == "john@stripe.com"
        assert result.sent_at is not None

    @resp.activate
    def test_200_also_accepted(self, monkeypatch):
        """Brevo sometimes returns 200 — treat both 200 and 201 as success."""
        svc = _svc(monkeypatch)
        resp.add(resp.POST, SEND_URL, json={"messageId": "<abc@brevo.com>"}, status=200)
        result = svc.send_one(_CONTACT)
        assert result.status == SendStatus.SENT

    def test_skipped_when_no_email(self, monkeypatch):
        """No HTTP request made when contact has no email."""
        svc = _svc(monkeypatch)
        result = svc.send_one(_CONTACT_NO_EMAIL)
        assert result.status == SendStatus.SKIPPED
        assert result.error is not None


# ─── Error handling ───────────────────────────────────────────────────────────

class TestBrevoErrorHandling:
    @resp.activate
    def test_401_raises_permission_error(self, monkeypatch):
        svc = _svc(monkeypatch)
        resp.add(resp.POST, SEND_URL, json={"message": "Unauthorized"}, status=401)
        with pytest.raises(PermissionError, match="Invalid API key"):
            svc.send_one(_CONTACT)

    @resp.activate
    def test_400_returns_failed_status(self, monkeypatch):
        svc = _svc(monkeypatch)
        resp.add(
            resp.POST, SEND_URL,
            json={"message": "Invalid email address"},
            status=400,
        )
        result = svc.send_one(_CONTACT)
        assert result.status == SendStatus.FAILED
        assert "Invalid email address" in (result.error or "")

    @resp.activate
    def test_429_waits_retry_after_and_retries(self, monkeypatch, mocker):
        svc = _svc(monkeypatch)
        sleep_mock = mocker.patch("src.services.brevo_service.time.sleep")
        resp.add(
            resp.POST, SEND_URL,
            json={}, status=429,
            headers={"Retry-After": "3"},
        )
        resp.add(resp.POST, SEND_URL, json={"messageId": "<id@brevo.com>"}, status=201)
        result = svc.send_one(_CONTACT)
        sleep_mock.assert_called_once_with(3.0)
        assert result.status == SendStatus.SENT

    @resp.activate
    def test_bulk_isolates_per_contact_failures(self, monkeypatch):
        """A failure on contact A must not abort contact B."""
        svc = _svc(monkeypatch)
        contact_b = Contact(
            name="Jane Doe", title="CTO", company="Adyen", verified_email="jane@adyen.com"
        )
        resp.add(resp.POST, SEND_URL, json={"message": "Sender not verified"}, status=400)
        resp.add(resp.POST, SEND_URL, json={"messageId": "<id2@brevo.com>"}, status=201)
        results = svc.send_bulk([_CONTACT, contact_b])
        assert len(results) == 2
        assert results[0].status == SendStatus.FAILED
        assert results[1].status == SendStatus.SENT

    @resp.activate
    def test_401_in_bulk_propagates(self, monkeypatch):
        """Auth errors must re-raise out of send_bulk."""
        svc = _svc(monkeypatch)
        resp.add(resp.POST, SEND_URL, json={}, status=401)
        with pytest.raises(PermissionError):
            svc.send_bulk([_CONTACT])


# ─── Sender verification ──────────────────────────────────────────────────────

class TestBrevoSenderVerification:
    @resp.activate
    def test_verify_sender_returns_true_when_active(self, monkeypatch):
        svc = _svc(monkeypatch)
        resp.add(
            resp.GET, SENDERS_URL,
            json={"senders": [{"email": "gurukiran.s@seedlinglabs.com", "active": True}]},
            status=200,
        )
        assert svc.verify_sender() is True

    @resp.activate
    def test_verify_sender_returns_false_when_inactive(self, monkeypatch):
        svc = _svc(monkeypatch)
        resp.add(
            resp.GET, SENDERS_URL,
            json={"senders": [{"email": "gurukiran.s@seedlinglabs.com", "active": False}]},
            status=200,
        )
        assert svc.verify_sender() is False

    @resp.activate
    def test_verify_sender_returns_false_when_not_listed(self, monkeypatch):
        svc = _svc(monkeypatch)
        resp.add(
            resp.GET, SENDERS_URL,
            json={"senders": [{"email": "other@example.com", "active": True}]},
            status=200,
        )
        assert svc.verify_sender() is False

    @resp.activate
    def test_verify_sender_401_raises(self, monkeypatch):
        svc = _svc(monkeypatch)
        resp.add(resp.GET, SENDERS_URL, json={}, status=401)
        with pytest.raises(PermissionError, match="Invalid API key"):
            svc.verify_sender()


# ─── Email template (unit, no HTTP) ──────────────────────────────────────────

class TestBrevoEmailTemplate:
    def test_build_payload_subject_format(self, monkeypatch):
        svc = _svc(monkeypatch)
        subject, body, payload = svc._build_payload(_CONTACT)
        assert subject == "Quick idea for Stripe"

    def test_build_payload_body_personalised(self, monkeypatch):
        svc = _svc(monkeypatch)
        _, body, _ = svc._build_payload(_CONTACT)
        assert "John" in body
        assert "VP Sales" in body
        assert "Stripe" in body

    def test_result_skipped_has_empty_email(self, monkeypatch):
        svc = _svc(monkeypatch)
        result = svc._result_skipped(_CONTACT_NO_EMAIL, "No email")
        assert result.status == SendStatus.SKIPPED
        assert result.email == ""
