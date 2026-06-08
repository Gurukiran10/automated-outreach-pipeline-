"""ProspeoService — wrapper around the Prospeo REST API."""
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

from src.config import get_app, get_prospeo
from src.logger import get_logger
from src.models import Company, Contact, ContactList, VerificationStatus

logger = get_logger(__name__)

# ─── Prospeo API reference ────────────────────────────────────────────────────
#
# Docs:    https://prospeo.io/api-docs
# Base URL: https://api.prospeo.io
# Auth:    Header  X-KEY: YOUR_API_KEY
#          All endpoints use POST except /account-information (GET).
#
# ── Endpoints used ────────────────────────────────────────────────────────────
#
# POST /search-person
#   Find people by domain, seniority, etc.
#   Request:
#   {
#     "page": 1,
#     "filters": {
#       "company": { "websites": { "include": ["stripe.com"] } },
#       "person_seniority": { "include": ["C-Suite", "Vice President", "Director", "Founder/Owner", "Manager"] }
#     }
#   }
#   Response:
#   {
#     "error": false,
#     "results": [
#       {
#         "person": {
#           "person_id": "...", "first_name": "John", "last_name": "Doe",
#           "full_name": "John Doe",
#           "linkedin_url": "https://www.linkedin.com/in/johndoe",
#           "current_job_title": "CEO",
#           "email": { "status": "VERIFIED", "revealed": false, "email": "j***@stripe.com" },
#           "location": { "country": "United States", "country_code": "US",
#                         "state": "California", "city": "San Francisco" }
#         },
#         "company": { "name": "Stripe", "domain": "stripe.com",
#                       "website": "https://stripe.com", "employee_count": 12975, ... }
#       }
#     ],
#     "pagination": { "current_page": 1, "per_page": 25, "total_page": 88, "total_count": 2197 }
#   }
#   Note: email.revealed is false in search results — emails are masked until enriched.
#
# POST /enrich-person
#   Enrich a single person by LinkedIn URL (or name + company).
#   Request:
#   {
#     "only_verified_email": true,
#     "data": { "linkedin_url": "https://www.linkedin.com/in/johndoe" }
#   }
#   Response:
#   {
#     "error": false,
#     "person": {
#       "full_name": "John Doe",
#       "email": { "status": "VERIFIED", "revealed": true, "email": "john@stripe.com" },
#       "linkedin_url": "...",
#       "location": { "country": "US", "city": "San Francisco" }
#     },
#     "company": { "name": "Stripe", "website": "https://stripe.com" }
#   }
#
# POST /bulk-enrich-person
#   Up to 50 people per request.
#   Request:
#   {
#     "only_verified_email": true,
#     "data": [
#       { "identifier": "1", "linkedin_url": "https://linkedin.com/in/john" },
#       { "identifier": "2", "linkedin_url": "https://linkedin.com/in/jane" }
#     ]
#   }
#   Response:
#   {
#     "error": false,
#     "matched": [ { "identifier": "1", "person": {...}, "company": {...} } ],
#     "not_matched": ["2"],
#     "invalid_datapoints": []
#   }
#
# POST /enrich-company
#   Request:  { "data": { "company_website": "stripe.com" } }
#   Response: { "error": false, "company": { ... } }
#
# GET /account-information
#   Response: { "error": false, "response": { "remaining_credits": 99, ... } }
#
# Rate limits (HTTP 429 on breach):
#   Enrich — Starter: 5/s, 300/min, 2000/day
#   Search  — Starter: 1/s, 30/min, 1000/day
#
# HTTP status codes:
#   200 = success  |  400 = general error  |  401 = bad key  |  429 = rate limit
# ─────────────────────────────────────────────────────────────────────────────

_RETRYABLE = (
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
    requests.exceptions.ChunkedEncodingError,
)

# Valid Prospeo seniority values (from /api-docs/enum/seniorities)
_DEFAULT_SENIORITY = ["C-Suite", "Vice President", "Director", "Founder/Owner", "Manager"]

_BULK_ENRICH_MAX = 50  # Prospeo hard limit per bulk-enrich request


def _require_key() -> None:
    if not get_prospeo().api_key:
        raise EnvironmentError(
            "PROSPEO_API_KEY is not set. "
            "Add it to your .env file before calling Prospeo."
        )


class ProspeoService:
    """Find decision-makers, verified emails, and company data via Prospeo."""

    def __init__(self) -> None:
        self._cfg = get_prospeo()
        self._app = get_app()
        self._session = requests.Session()
        self._session.headers.update(
            {
                "X-KEY": self._cfg.api_key,
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
        logger.debug("POST %s | status=%d | elapsed=%.2fs", url, response.status_code, elapsed)
        return response

    def _get(self, endpoint: str) -> requests.Response:
        url = f"{self._cfg.base_url.rstrip('/')}/{endpoint.lstrip('/')}"
        logger.debug("GET %s", url)
        t0 = time.monotonic()
        response = self._session.get(url, timeout=self._app.request_timeout_seconds)
        elapsed = time.monotonic() - t0
        logger.debug("GET %s | status=%d | elapsed=%.2fs", url, response.status_code, elapsed)
        return response

    def _handle_rate_limit_wait(self, response: requests.Response, endpoint: str) -> None:
        if response.status_code == 429:
            wait = float(response.headers.get("Retry-After", self._app.retry_wait_seconds))
            logger.warning("Prospeo %s rate limited — waiting %.1fs", endpoint, wait)
            time.sleep(wait)

    def _check_errors(self, data: dict, endpoint: str) -> None:
        """Raise if Prospeo reports error:true in the response body."""
        if data.get("error"):
            msg = data.get("message") or data.get("error_message") or "Unknown Prospeo error"
            raise RuntimeError(f"Prospeo {endpoint} error: {msg}")

    def _raise_for_auth(self, response: requests.Response) -> None:
        if response.status_code == 401:
            raise PermissionError(
                "Prospeo: Invalid API key. Check PROSPEO_API_KEY in your .env file."
            )

    # ── Response parsers ──────────────────────────────────────────────────────

    @staticmethod
    def _parse_contact_from_result(result: dict[str, Any]) -> Contact | None:
        """Parse a /search-person result entry into a Contact."""
        person = result.get("person") or {}
        company = result.get("company") or {}

        full_name = (
            person.get("full_name")
            or f"{person.get('first_name', '')} {person.get('last_name', '')}".strip()
        )
        if not full_name:
            return None

        email_data = person.get("email") or {}
        # email.revealed=false in /search-person results means the address is masked
        revealed = email_data.get("revealed", False) if isinstance(email_data, dict) else False
        email_val = email_data.get("email") if (isinstance(email_data, dict) and revealed) else None
        status_raw = (email_data.get("status") or "UNKNOWN") if isinstance(email_data, dict) else "UNKNOWN"

        try:
            status = VerificationStatus(status_raw.upper().replace("-", "_").lower())
        except ValueError:
            status = VerificationStatus.UNKNOWN

        location = person.get("location") or {}
        # company.domain is a clean bare domain ("stripe.com"); fall back to stripping website URL
        company_domain = company.get("domain") or (
            (company.get("website") or "")
            .removeprefix("https://")
            .removeprefix("http://")
            .removeprefix("www.")
            .split("/")[0]
        ) or None

        return Contact(
            name=full_name,
            first_name=person.get("first_name"),
            last_name=person.get("last_name"),
            title=person.get("current_job_title") or person.get("headline"),
            linkedin_url=person.get("linkedin_url"),
            company=company.get("name"),
            company_domain=company_domain,
            email=email_val,
            email_status=status,
            location=f"{location.get('city', '')}, {location.get('country', '')}".strip(", ") or None,
            seniority=person.get("seniority"),
            department=person.get("department"),
        )

    @staticmethod
    def _parse_contact_from_enrich(data: dict[str, Any], source_domain: str | None) -> Contact | None:
        """Parse a /enrich-person response into a Contact."""
        person = data.get("person") or {}
        company = data.get("company") or {}

        full_name = person.get("full_name") or ""
        if not full_name:
            return None

        email_data = person.get("email") or {}
        email_val = email_data.get("email") if email_data.get("revealed") else None
        status_raw = (email_data.get("status") or "UNKNOWN")

        try:
            status = VerificationStatus(status_raw.lower())
        except ValueError:
            status = VerificationStatus.UNKNOWN

        location = person.get("location") or {}

        return Contact(
            name=full_name,
            first_name=person.get("first_name"),
            last_name=person.get("last_name"),
            title=person.get("current_job_title"),
            linkedin_url=person.get("linkedin_url"),
            company=company.get("name"),
            company_domain=source_domain or (
                (company.get("website") or "")
                .removeprefix("https://")
                .removeprefix("http://")
                .removeprefix("www.")
                .split("/")[0]
            ) or None,
            verified_email=email_val,
            email_status=status,
            location=f"{location.get('city', '')}, {location.get('country', '')}".strip(", ") or None,
        )

    @staticmethod
    def _parse_company(data: dict[str, Any]) -> Company | None:
        """Parse a /enrich-company response company object."""
        domain = (
            (data.get("website") or data.get("domain") or "")
            .removeprefix("https://")
            .removeprefix("http://")
            .removeprefix("www.")
            .split("/")[0]
        )
        if not domain:
            return None

        location = data.get("location") or {}
        return Company(
            domain=domain,
            name=data.get("name"),
            industry=data.get("industry"),
            employee_count=data.get("employee_count"),
            country=location.get("country"),
            description=data.get("description"),
        )

    # ── Public methods ────────────────────────────────────────────────────────

    def search_person(
        self,
        domain: str,
        page: int = 1,
        seniority: list[str] | None = None,
    ) -> ContactList:
        """
        Search for people at *domain* using /search-person.
        Returns one page (25 contacts max per Prospeo).
        """
        _require_key()
        seniority = seniority or _DEFAULT_SENIORITY
        logger.info("Prospeo /search-person — domain=%s page=%d", domain, page)

        payload: dict[str, Any] = {
            "page": page,
            "filters": {
                "company": {"websites": {"include": [domain]}},
                "person_seniority": {"include": seniority},
            },
        }

        response = self._post("/search-person", payload)
        for attempt in range(5):
            if response.status_code != 429:
                break
            wait = 2.0 ** attempt  # 1s, 2s, 4s, 8s, 16s
            logger.warning("Prospeo /search-person rate limited — waiting %.1fs", wait)
            time.sleep(wait)
            response = self._post("/search-person", payload)

        self._raise_for_auth(response)
        response.raise_for_status()
        data = response.json()
        self._check_errors(data, "/search-person")

        results = data.get("results") or []
        pagination = data.get("pagination") or {}
        total_page = pagination.get("total_page", 1)
        total_count = pagination.get("total_count", len(results))
        per_page = pagination.get("per_page", 25)

        contacts: list[Contact] = []
        for result in results:
            contact = self._parse_contact_from_result(result)
            if contact:
                contacts.append(contact)

        has_more = page < total_page
        logger.info(
            "Prospeo /search-person — %d contacts on page %d/%d (total: %d)",
            len(contacts), page, total_page, total_count,
        )
        return ContactList(
            domain=domain,
            contacts=contacts,
            total_found=total_count,
            page=page,
            has_more=has_more,
        )

    def search_all_pages(
        self,
        domain: str,
        max_contacts: int | None = None,
        seniority: list[str] | None = None,
    ) -> ContactList:
        """Paginate /search-person until max_contacts or all pages exhausted."""
        max_contacts = max_contacts or self._cfg.contacts_per_domain
        all_contacts: list[Contact] = []
        total_found = 0
        page = 1

        while len(all_contacts) < max_contacts and page <= self._cfg.max_pages:
            result = self.search_person(domain, page=page, seniority=seniority)
            total_found = result.total_found
            all_contacts.extend(result.contacts)
            if not result.has_more or not result.contacts:
                break
            page += 1

        trimmed = all_contacts[:max_contacts]
        logger.info(
            "Prospeo — collected %d contacts for %s (total available: %d)",
            len(trimmed), domain, total_found,
        )
        return ContactList(domain=domain, contacts=trimmed, total_found=total_found)

    def enrich_person(
        self,
        linkedin_url: str,
        only_verified: bool | None = None,
    ) -> Contact | None:
        """
        Enrich a single person by LinkedIn URL via /enrich-person.
        Returns None if not found or email not revealed.
        """
        _require_key()
        if only_verified is None:
            only_verified = self._cfg.only_verified_email

        logger.info("Prospeo /enrich-person — %s", linkedin_url)
        payload: dict[str, Any] = {
            "only_verified_email": only_verified,
            "data": {"linkedin_url": linkedin_url},
        }

        response = self._post("/enrich-person", payload)
        for attempt in range(5):
            if response.status_code != 429:
                break
            wait = 2.0 ** attempt  # 1s, 2s, 4s, 8s, 16s
            logger.warning("Prospeo /enrich-person rate limited — waiting %.1fs", wait)
            time.sleep(wait)
            response = self._post("/enrich-person", payload)

        self._raise_for_auth(response)

        if response.status_code == 404:
            logger.warning("Prospeo /enrich-person — not found: %s", linkedin_url)
            return None

        response.raise_for_status()
        data = response.json()
        self._check_errors(data, "/enrich-person")

        contact = self._parse_contact_from_enrich(data, source_domain=None)
        if contact and contact.verified_email:
            logger.info(
                "Prospeo /enrich-person — %s → %s (%s)",
                linkedin_url, contact.verified_email, contact.email_status.value,
            )
        else:
            logger.debug("Prospeo /enrich-person — no verified email for %s", linkedin_url)
        return contact

    def bulk_enrich_persons(
        self,
        linkedin_urls: list[str],
        only_verified: bool | None = None,
    ) -> list[Contact]:
        """
        Bulk-enrich up to 50 LinkedIn URLs at once via /bulk-enrich-person.
        Automatically chunks input if len > 50.
        """
        _require_key()
        if only_verified is None:
            only_verified = self._cfg.only_verified_email

        all_contacts: list[Contact] = []

        for i in range(0, len(linkedin_urls), _BULK_ENRICH_MAX):
            chunk = linkedin_urls[i : i + _BULK_ENRICH_MAX]
            data_items = [
                {"identifier": str(idx), "linkedin_url": url}
                for idx, url in enumerate(chunk, start=i)
            ]
            payload: dict[str, Any] = {
                "only_verified_email": only_verified,
                "data": data_items,
            }

            logger.info(
                "Prospeo /bulk-enrich-person — chunk %d-%d of %d",
                i, i + len(chunk) - 1, len(linkedin_urls),
            )
            response = self._post("/bulk-enrich-person", payload)
            for attempt in range(5):
                if response.status_code != 429:
                    break
                wait = 2.0 ** attempt  # 1s, 2s, 4s, 8s, 16s
                logger.warning("Prospeo /bulk-enrich-person rate limited — waiting %.1fs", wait)
                time.sleep(wait)
                response = self._post("/bulk-enrich-person", payload)

            self._raise_for_auth(response)
            response.raise_for_status()
            if i + _BULK_ENRICH_MAX < len(linkedin_urls):
                time.sleep(1)  # respect 1 req/s rate limit between chunks
            result = response.json()
            self._check_errors(result, "/bulk-enrich-person")

            matched = result.get("matched") or []
            not_matched = result.get("not_matched") or []
            logger.info(
                "Prospeo /bulk-enrich-person — matched=%d not_matched=%d",
                len(matched), len(not_matched),
            )

            for match in matched:
                contact = self._parse_contact_from_enrich(match, source_domain=None)
                if contact:
                    all_contacts.append(contact)

        return all_contacts

    def enrich_company(self, domain: str) -> Company | None:
        """Enrich a company by domain via /enrich-company."""
        _require_key()
        logger.info("Prospeo /enrich-company — %s", domain)
        payload = {"data": {"company_website": domain}}

        response = self._post("/enrich-company", payload)
        self._handle_rate_limit_wait(response, "/enrich-company")

        if response.status_code == 429:
            response = self._post("/enrich-company", payload)

        self._raise_for_auth(response)

        if response.status_code == 404:
            logger.warning("Prospeo /enrich-company — not found: %s", domain)
            return None

        response.raise_for_status()
        data = response.json()
        self._check_errors(data, "/enrich-company")

        company_data = data.get("company") or {}
        company = self._parse_company(company_data)
        if company:
            logger.info("Prospeo /enrich-company — %s → %s", domain, company.name)
        return company

    def get_account_info(self) -> dict[str, Any]:
        """Return account information including remaining credits."""
        _require_key()
        response = self._get("/account-information")
        self._raise_for_auth(response)
        response.raise_for_status()
        data = response.json()
        self._check_errors(data, "/account-information")
        info = data.get("response") or data
        logger.info(
            "Prospeo account — plan=%s remaining_credits=%s",
            info.get("current_plan"), info.get("remaining_credits"),
        )
        return info

    def run(self, domain: str) -> ContactList:
        """Entry point used by the pipeline — searches all pages for a domain."""
        _require_key()
        return self.search_all_pages(domain)
