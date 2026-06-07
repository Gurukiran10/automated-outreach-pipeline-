"""BrevoService — transactional email dispatch via Brevo (v3 API)."""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.config import get_app, get_brevo
from src.logger import get_logger
from src.models import Contact, EmailResult, SendStatus
from src.utils import render_email

logger = get_logger(__name__)

# ─── Brevo Transactional Email API v3 ─────────────────────────────────────────
#
# Docs:  https://developers.brevo.com/docs/send-a-transactional-email
# Auth:  Header  api-key: YOUR_KEY
#
# POST https://api.brevo.com/v3/smtp/email
#
# Request:
# {
#   "sender":      { "name": "Gurukiran", "email": "gurukiran.s@seedlinglabs.com" },
#   "to":          [{ "email": "john@stripe.com", "name": "John Doe" }],
#   "subject":     "Quick idea for Stripe",
#   "textContent": "Hi John, ...",        # plain text
#   "htmlContent": "<p>Hi John, ...</p>"  # optional HTML version
# }
#
# Response (201 Created):
# { "messageId": "<202506071234.abc123@smtp-relay.brevo.com>" }
#
# Error responses:
#   400 { "code": "...", "message": "..." }  — invalid payload / unverified sender
#   401 { "code": "...", "message": "..." }  — bad API key
#   429 — rate limit; honour Retry-After header
#
# Note: The sender email must be a verified sender or belong to a verified domain
#       in your Brevo account before emails will actually be delivered.
# ─────────────────────────────────────────────────────────────────────────────

_RETRYABLE = (
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
    requests.exceptions.ChunkedEncodingError,
)

_SUCCESS_CODES = {200, 201}  # Brevo returns 201 on successful send


def _require_key() -> None:
    if not get_brevo().api_key:
        raise EnvironmentError(
            "BREVO_API_KEY is not set. "
            "Add it to your .env file before sending emails."
        )


class BrevoService:
    """Send personalised outreach emails via Brevo transactional API."""

    def __init__(self) -> None:
        self._cfg = get_brevo()
        self._app = get_app()
        self._session = requests.Session()
        self._session.headers.update(
            {
                "api-key": self._cfg.api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
        )

    # ── Low-level HTTP ────────────────────────────────────────────────────────

    @retry(
        retry=retry_if_exception_type(_RETRYABLE),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=1, max=30),
        reraise=True,
    )
    def _post(self, endpoint: str, payload: dict[str, Any]) -> requests.Response:
        url = f"{self._cfg.base_url.rstrip('/')}/{endpoint.lstrip('/')}"
        logger.debug("POST %s | to=%s", url, payload.get("to"))
        t0 = time.monotonic()
        response = self._session.post(url, json=payload, timeout=self._app.request_timeout_seconds)
        elapsed = time.monotonic() - t0
        logger.debug(
            "POST %s | status=%d | elapsed=%.2fs", url, response.status_code, elapsed
        )
        return response

    def _handle_rate_limit(self, response: requests.Response) -> requests.Response | None:
        """If 429, sleep Retry-After seconds and return None (caller should retry)."""
        if response.status_code == 429:
            wait = float(
                response.headers.get("Retry-After", self._app.retry_wait_seconds)
            )
            logger.warning("Brevo rate limited — waiting %.1fs", wait)
            time.sleep(wait)
            return None
        return response

    # ── Core send logic ───────────────────────────────────────────────────────

    def _build_payload(self, contact: Contact) -> tuple[str, str, dict[str, Any]]:
        """Build (subject, body, request_payload) for *contact*."""
        subject, body = render_email(
            name=contact.name,
            company=contact.company or "",
            title=contact.title or "your role",
        )
        payload: dict[str, Any] = {
            "sender": {
                "name": self._cfg.sender_name,
                "email": self._cfg.sender_email,
            },
            "to": [{"email": contact.best_email, "name": contact.name}],
            "subject": subject,
            "textContent": body,
        }
        return subject, body, payload

    def _result_skipped(self, contact: Contact, reason: str) -> EmailResult:
        subject, body = render_email(
            name=contact.name,
            company=contact.company or "",
            title=contact.title or "your role",
        )
        return EmailResult(
            contact_name=contact.name,
            contact_title=contact.title,
            company=contact.company,
            email="",
            subject=subject,
            body=body,
            status=SendStatus.SKIPPED,
            error=reason,
        )

    def _result_failed(
        self, contact: Contact, email: str, subject: str, body: str, error: str
    ) -> EmailResult:
        return EmailResult(
            contact_name=contact.name,
            contact_title=contact.title,
            company=contact.company,
            email=email,
            subject=subject,
            body=body,
            status=SendStatus.FAILED,
            error=error,
        )

    def send_one(self, contact: Contact) -> EmailResult:
        """Send a single personalised email to *contact*."""
        _require_key()

        if not contact.best_email:
            logger.warning("Brevo — skipping %s: no email address", contact.name)
            return self._result_skipped(contact, "No email address available")

        subject, body, payload = self._build_payload(contact)
        email_addr = contact.best_email

        logger.info("Brevo — sending to %s <%s>", contact.name, email_addr)

        response = self._post("/smtp/email", payload)

        # Handle rate limit with one retry
        if response.status_code == 429:
            self._handle_rate_limit(response)
            response = self._post("/smtp/email", payload)

        if response.status_code == 401:
            raise PermissionError(
                "Brevo: Invalid API key. Check BREVO_API_KEY in your .env file."
            )

        if response.status_code == 400:
            err = response.json() if response.content else {}
            error_msg = err.get("message") or err.get("code") or "Bad request"
            logger.error(
                "Brevo — 400 for %s <%s>: %s", contact.name, email_addr, error_msg
            )
            return self._result_failed(contact, email_addr, subject, body, error_msg)

        if response.status_code not in _SUCCESS_CODES:
            error_msg = f"Unexpected status {response.status_code}"
            logger.error("Brevo — %s for %s", error_msg, email_addr)
            response.raise_for_status()

        message_id = response.json().get("messageId", "")
        logger.info(
            "Brevo — sent to %s <%s> | messageId=%s", contact.name, email_addr, message_id
        )
        return EmailResult(
            contact_name=contact.name,
            contact_title=contact.title,
            company=contact.company,
            email=email_addr,
            subject=subject,
            body=body,
            status=SendStatus.SENT,
            message_id=message_id,
            sent_at=datetime.now(tz=timezone.utc),
        )

    def send_bulk(self, contacts: list[Contact]) -> list[EmailResult]:
        """Send emails to a list of contacts, collecting per-contact results."""
        results: list[EmailResult] = []
        for contact in contacts:
            try:
                results.append(self.send_one(contact))
            except PermissionError:
                raise  # propagate auth errors immediately
            except Exception as exc:
                logger.error("Brevo — unhandled error for %s: %s", contact.name, exc)
                email_addr = contact.best_email or ""
                subject, body = render_email(
                    name=contact.name,
                    company=contact.company or "",
                    title=contact.title or "your role",
                )
                results.append(
                    self._result_failed(contact, email_addr, subject, body, str(exc))
                )
        return results

    def verify_sender(self) -> bool:
        """
        Light check: send a GET to /senders and verify our sender is listed.
        Returns True if the configured sender email exists and is active.
        """
        _require_key()
        url = f"{self._cfg.base_url.rstrip('/')}/senders"
        logger.debug("GET %s (sender verification)", url)
        response = self._session.get(url, timeout=self._app.request_timeout_seconds)

        if response.status_code == 401:
            raise PermissionError("Brevo: Invalid API key.")

        response.raise_for_status()
        senders = response.json().get("senders") or []
        active = [
            s for s in senders
            if s.get("email") == self._cfg.sender_email and s.get("active")
        ]
        if not active:
            logger.warning(
                "Brevo — sender <%s> not found or not active. "
                "Verify it at app.brevo.com → Senders.",
                self._cfg.sender_email,
            )
            return False
        logger.info("Brevo — sender <%s> is verified and active.", self._cfg.sender_email)
        return True

    def run(self, contacts: list[Contact]) -> list[EmailResult]:
        """Entry point used by the pipeline."""
        _require_key()
        return self.send_bulk(contacts)
