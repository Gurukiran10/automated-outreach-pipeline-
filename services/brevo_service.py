from __future__ import annotations

from datetime import datetime, timezone

import requests

from config.settings import get_settings
from models.contact import Contact
from models.email_result import EmailResult, SendStatus
from utils.helpers import build_email_body
from utils.logger import get_logger
from utils.retry import retry

logger = get_logger(__name__)
settings = get_settings()

# Brevo (formerly Sendinblue) Transactional Email API
# Docs: https://developers.brevo.com/reference/sendtransacemail
# Endpoint: POST https://api.brevo.com/v3/smtp/email
# Headers:  api-key: <BREVO_API_KEY>
# Request:
# {
#   "sender": { "name": "Gurukiran", "email": "gurukiran.s@seedlinglabs.com" },
#   "to": [{ "email": "john@stripe.com", "name": "John Doe" }],
#   "subject": "Quick idea for Stripe",
#   "textContent": "Hi John, ..."
# }
# Response: { "messageId": "<...@smtp-relay.brevo.com>" }


class BrevoService:
    """Wrapper around the Brevo transactional email API."""

    def __init__(self) -> None:
        self.base_url = settings.brevo_base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update(
            {
                "api-key": settings.brevo_api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
        )
        self.timeout = settings.request_timeout

    @retry(
        max_attempts=settings.retry_max_attempts,
        backoff_factor=settings.retry_backoff_factor,
        initial_wait=settings.retry_initial_wait,
    )
    def _post(self, endpoint: str, payload: dict) -> requests.Response:
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        logger.debug("POST %s", url)
        return self.session.post(url, json=payload, timeout=self.timeout)

    def send_email(self, contact: Contact) -> EmailResult:
        email_addr = contact.verified_email or contact.email
        if not email_addr:
            logger.warning("No email address for %s — skipping.", contact.name)
            return EmailResult(
                contact_name=contact.name,
                contact_title=contact.title,
                company=contact.company,
                email="",
                subject="",
                body="",
                status=SendStatus.SKIPPED,
                error="No email address available",
            )

        subject, body = build_email_body(
            name=contact.name,
            company=contact.company or "",
            title=contact.title or "your role",
        )

        payload = {
            "sender": {
                "name": settings.brevo_sender_name,
                "email": settings.brevo_sender_email,
            },
            "to": [{"email": email_addr, "name": contact.name}],
            "subject": subject,
            "textContent": body,
        }

        logger.info("Sending email to %s <%s>", contact.name, email_addr)
        response = self._post("/smtp/email", payload)

        if response.status_code == 401:
            raise PermissionError("Brevo: Invalid API key.")

        if response.status_code == 400:
            error_msg = response.json().get("message", "Bad request")
            logger.error("Brevo rejected email to %s: %s", email_addr, error_msg)
            return EmailResult(
                contact_name=contact.name,
                contact_title=contact.title,
                company=contact.company,
                email=email_addr,
                subject=subject,
                body=body,
                status=SendStatus.FAILED,
                error=error_msg,
            )

        response.raise_for_status()
        data = response.json()
        message_id = data.get("messageId", "")

        logger.info("Email sent to %s — message_id=%s", email_addr, message_id)
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
        results: list[EmailResult] = []
        for contact in contacts:
            try:
                results.append(self.send_email(contact))
            except Exception as exc:
                logger.error("Failed to send email to %s: %s", contact.name, exc)
                email_addr = contact.verified_email or contact.email or ""
                subject, body = build_email_body(
                    name=contact.name,
                    company=contact.company or "",
                    title=contact.title or "your role",
                )
                results.append(
                    EmailResult(
                        contact_name=contact.name,
                        contact_title=contact.title,
                        company=contact.company,
                        email=email_addr,
                        subject=subject,
                        body=body,
                        status=SendStatus.FAILED,
                        error=str(exc),
                    )
                )
        return results

    # ------------------------------------------------------------------
    # Mock implementation
    # ------------------------------------------------------------------
    def send_email_mock(self, contact: Contact) -> EmailResult:
        email_addr = contact.verified_email or contact.email or ""
        subject, body = build_email_body(
            name=contact.name,
            company=contact.company or "",
            title=contact.title or "your role",
        )
        logger.warning(
            "[MOCK] Would send email to %s <%s> subject=%r",
            contact.name,
            email_addr,
            subject,
        )
        return EmailResult(
            contact_name=contact.name,
            contact_title=contact.title,
            company=contact.company,
            email=email_addr,
            subject=subject,
            body=body,
            status=SendStatus.SENT,
            message_id=f"mock-{contact.name.lower().replace(' ', '-')}",
            sent_at=datetime.now(tz=timezone.utc),
        )

    def dispatch(self, contacts: list[Contact]) -> list[EmailResult]:
        if not settings.brevo_api_key:
            logger.warning("Brevo API key not set — using mock send.")
            return [self.send_email_mock(c) for c in contacts]
        return self.send_bulk(contacts)
