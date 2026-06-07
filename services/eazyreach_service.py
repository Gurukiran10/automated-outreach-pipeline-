from __future__ import annotations

import requests

from config.settings import get_settings
from models.contact import Contact, VerificationStatus
from utils.logger import get_logger
from utils.retry import retry

logger = get_logger(__name__)
settings = get_settings()

# TODO: Confirm exact Eazyreach API endpoint and auth scheme.
# Assumed endpoint: POST /email/find
# Request:  { "linkedin_url": "https://linkedin.com/in/johndoe" }
# Response: {
#   "email": "john@stripe.com",
#   "status": "verified",       # "verified" | "catch_all" | "invalid"
#   "confidence": 0.95
# }
#
# Alternative assumed endpoint: POST /email/bulk
# Request:  { "linkedin_urls": ["https://..."] }


class EazyreachService:
    """Wrapper around the Eazyreach LinkedIn-to-email API."""

    def __init__(self) -> None:
        self.base_url = settings.eazyreach_base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {settings.eazyreach_api_key}",
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
        logger.debug("POST %s payload=%s", url, payload)
        return self.session.post(url, json=payload, timeout=self.timeout)

    def find_email(self, contact: Contact) -> Contact:
        """Enrich *contact* with a verified email via Eazyreach."""
        if not contact.linkedin_url:
            logger.warning("No LinkedIn URL for contact %s — skipping Eazyreach.", contact.name)
            return contact

        logger.info("Fetching verified email for %s (%s)", contact.name, contact.linkedin_url)

        # TODO: Replace with actual Eazyreach endpoint path once confirmed.
        response = self._post("/email/find", {"linkedin_url": contact.linkedin_url})

        if response.status_code == 401:
            raise PermissionError("Eazyreach: Invalid API key.")

        if response.status_code == 404:
            logger.warning("Eazyreach: Email not found for %s", contact.linkedin_url)
            contact.email_status = VerificationStatus.INVALID
            return contact

        if response.status_code == 422:
            logger.warning("Eazyreach: Unprocessable LinkedIn URL: %s", contact.linkedin_url)
            return contact

        response.raise_for_status()
        data: dict = response.json()

        email = data.get("email")
        status_raw = data.get("status", "unknown")

        try:
            status = VerificationStatus(status_raw.lower())
        except ValueError:
            status = VerificationStatus.UNKNOWN

        contact.verified_email = email
        contact.email_status = status

        if email:
            logger.info("Verified email for %s: %s (%s)", contact.name, email, status_raw)
        else:
            logger.warning("No email returned by Eazyreach for %s", contact.name)

        return contact

    def find_emails_bulk(self, contacts: list[Contact]) -> list[Contact]:
        """Enrich each contact one at a time (Eazyreach may support bulk later)."""
        enriched: list[Contact] = []
        for contact in contacts:
            try:
                enriched.append(self.find_email(contact))
            except Exception as exc:
                logger.error("Eazyreach error for %s: %s", contact.name, exc)
                enriched.append(contact)
        return enriched

    # ------------------------------------------------------------------
    # Mock implementation
    # ------------------------------------------------------------------
    def find_email_mock(self, contact: Contact) -> Contact:
        logger.warning("Eazyreach API key not set — returning mock email for %s.", contact.name)
        if contact.company_domain:
            slug = contact.name.lower().replace(" ", ".")
            contact.verified_email = f"{slug}@{contact.company_domain}"
            contact.email_status = VerificationStatus.VERIFIED
        return contact

    def enrich_contacts(self, contacts: list[Contact]) -> list[Contact]:
        if not settings.eazyreach_api_key:
            return [self.find_email_mock(c) for c in contacts]
        return self.find_emails_bulk(contacts)
