"""EazyReachService — LinkedIn-to-email enrichment (EazyReach API)."""
from __future__ import annotations

import time
from typing import Any

import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.config import get_app, get_eazyreach
from src.logger import get_logger
from src.models import Contact, VerificationStatus

logger = get_logger(__name__)

# ─── EazyReach API ────────────────────────────────────────────────────────────
#
# TODO: Confirm the following with EazyReach support before going live.
#       The endpoint paths and request format below are assumed based on
#       standard LinkedIn enrichment API conventions.
#
# Auth:    Authorization: Bearer YOUR_EAZYREACH_API_KEY
# Base:    https://api.eazyreach.io/v1   (set EAZYREACH_BASE_URL in .env)
#
# Single enrichment:
#   POST /email/find
#   Request:  { "linkedin_url": "https://www.linkedin.com/in/johndoe" }
#   Response:
#   {
#     "email":      "john.doe@company.com",
#     "status":     "verified",     # "verified" | "catch_all" | "invalid" | "unknown"
#     "confidence": 0.97,
#     "phone":      "+1-555-0100",
#     "location":   "San Francisco, CA",
#     "seniority":  "director",
#     "department": "engineering"
#   }
#
# Bulk enrichment (assumed):
#   POST /email/bulk
#   Request:  { "linkedin_urls": ["https://...", "https://..."] }
#   Response: { "results": [ { "linkedin_url": "...", "email": "...", ... } ] }
#
# ─────────────────────────────────────────────────────────────────────────────

_RETRYABLE = (
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
    requests.exceptions.ChunkedEncodingError,
)


def _require_key() -> None:
    if not get_eazyreach().api_key:
        raise EnvironmentError(
            "EAZYREACH_API_KEY is not set. "
            "Add it to your .env file before calling EazyReach."
        )


class EazyReachService:
    """Enrich contacts with verified work emails via EazyReach."""

    def __init__(self) -> None:
        self._cfg = get_eazyreach()
        self._app = get_app()
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {self._cfg.api_key}",
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
        logger.debug("POST %s | payload=%s", url, payload)
        t0 = time.monotonic()
        response = self._session.post(url, json=payload, timeout=self._app.request_timeout_seconds)
        elapsed = time.monotonic() - t0
        logger.debug(
            "POST %s | status=%d | elapsed=%.2fs", url, response.status_code, elapsed
        )
        return response

    def _handle_rate_limit(self, response: requests.Response, endpoint: str) -> None:
        if response.status_code == 429:
            wait = float(
                response.headers.get("Retry-After", self._app.retry_wait_seconds)
            )
            logger.warning("EazyReach %s rate limited — waiting %.1fs", endpoint, wait)
            time.sleep(wait)

    # ── Public methods ────────────────────────────────────────────────────────

    def enrich_one(self, contact: Contact) -> Contact:
        """
        Enrich *contact* with a verified email via EazyReach /email/find.
        Returns the contact unchanged if LinkedIn URL is missing or API fails.
        """
        _require_key()

        if not contact.linkedin_url:
            logger.warning(
                "EazyReach — skipping %s: no LinkedIn URL", contact.name
            )
            return contact

        logger.info("EazyReach /email/find — %s", contact.linkedin_url)

        # TODO: Replace endpoint path once confirmed with EazyReach support
        response = self._post("/email/find", {"linkedin_url": contact.linkedin_url})
        self._handle_rate_limit(response, "/email/find")

        if response.status_code == 429:
            response = self._post("/email/find", {"linkedin_url": contact.linkedin_url})

        if response.status_code == 401:
            raise PermissionError(
                "EazyReach: Invalid API key. Check EAZYREACH_API_KEY in your .env file."
            )

        if response.status_code in (404, 422):
            logger.warning(
                "EazyReach /email/find — no result for %s (status=%d)",
                contact.linkedin_url, response.status_code,
            )
            contact.email_status = VerificationStatus.UNKNOWN
            return contact

        response.raise_for_status()
        data: dict[str, Any] = response.json()

        email = data.get("email")
        status_raw = data.get("status", "unknown")

        try:
            status = VerificationStatus(status_raw.lower())
        except ValueError:
            status = VerificationStatus.UNKNOWN

        contact.verified_email = email
        contact.email_status = status
        contact.phone = contact.phone or data.get("phone")
        contact.location = contact.location or data.get("location")
        contact.seniority = contact.seniority or data.get("seniority")
        contact.department = contact.department or data.get("department")

        if email:
            logger.info(
                "EazyReach — %s → %s (%s, confidence=%.2f)",
                contact.name, email, status_raw, data.get("confidence", 0),
            )
        else:
            logger.debug(
                "EazyReach — no email returned for %s", contact.name
            )
        return contact

    def enrich_many(self, contacts: list[Contact]) -> list[Contact]:
        """Enrich each contact sequentially, skipping those without LinkedIn URLs."""
        enriched: list[Contact] = []
        for contact in contacts:
            try:
                enriched.append(self.enrich_one(contact))
            except PermissionError:
                raise  # propagate auth failures immediately
            except Exception as exc:
                logger.error(
                    "EazyReach — error enriching %s: %s", contact.name, exc
                )
                enriched.append(contact)
        return enriched

    def run(self, contacts: list[Contact]) -> list[Contact]:
        """Entry point used by the pipeline."""
        _require_key()
        return self.enrich_many(contacts)
