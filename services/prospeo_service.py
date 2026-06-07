from __future__ import annotations

import requests

from config.settings import get_settings
from models.contact import Contact, ContactList, VerificationStatus
from utils.logger import get_logger
from utils.retry import retry

logger = get_logger(__name__)
settings = get_settings()

# Prospeo API reference: https://prospeo.io/api
# Domain search endpoint: POST https://api.prospeo.io/domain-search
# Request:  { "company": "stripe.com", "limit": 5, "offset": 0 }
# Response: {
#   "response": {
#     "email_list": [
#       {
#         "first_name": "John",
#         "last_name": "Doe",
#         "full_name": "John Doe",
#         "title": "CEO",
#         "linkedin_url": "https://linkedin.com/in/johndoe",
#         "company": "Stripe",
#         "email": { "value": "john@stripe.com", "status": "verified" }
#       }
#     ],
#     "total": 100
#   }
# }


class ProspeoService:
    """Wrapper around the Prospeo Domain Search API."""

    def __init__(self) -> None:
        self.base_url = settings.prospeo_base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update(
            {
                "X-KEY": settings.prospeo_api_key,
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

    def _parse_contact(self, item: dict, domain: str) -> Contact | None:
        email_data = item.get("email", {})
        email_val = email_data.get("value") if isinstance(email_data, dict) else None
        status_raw = email_data.get("status", "unknown") if isinstance(email_data, dict) else "unknown"

        try:
            status = VerificationStatus(status_raw.lower())
        except ValueError:
            status = VerificationStatus.UNKNOWN

        full_name = item.get("full_name") or f"{item.get('first_name', '')} {item.get('last_name', '')}".strip()
        if not full_name:
            return None

        return Contact(
            name=full_name,
            first_name=item.get("first_name"),
            last_name=item.get("last_name"),
            title=item.get("title"),
            linkedin_url=item.get("linkedin_url"),
            company=item.get("company"),
            company_domain=domain,
            email=email_val,
            email_status=status,
        )

    def search_domain(self, domain: str, limit: int | None = None, offset: int = 0) -> ContactList:
        limit = limit or settings.prospeo_contacts_per_domain
        logger.info("Searching contacts for domain: %s (limit=%d, offset=%d)", domain, limit, offset)

        response = self._post(
            "/domain-search",
            {"company": domain, "limit": limit, "offset": offset},
        )

        if response.status_code == 401:
            raise PermissionError("Prospeo: Invalid API key.")

        if response.status_code == 404:
            logger.warning("Prospeo: No contacts found for %s", domain)
            return ContactList(domain=domain)

        response.raise_for_status()
        data = response.json()
        inner = data.get("response", data)

        contacts: list[Contact] = []
        for item in inner.get("email_list", []):
            contact = self._parse_contact(item, domain)
            if contact:
                contacts.append(contact)

        total = inner.get("total", len(contacts))
        has_more = (offset + limit) < total

        logger.info("Prospeo returned %d contacts for %s", len(contacts), domain)
        return ContactList(
            domain=domain,
            contacts=contacts,
            total_found=total,
            page=(offset // limit) + 1,
            has_more=has_more,
        )

    def search_domain_all_pages(self, domain: str, max_contacts: int | None = None) -> ContactList:
        """Paginate through all results up to *max_contacts*."""
        limit = settings.prospeo_contacts_per_domain
        max_contacts = max_contacts or limit
        all_contacts: list[Contact] = []
        offset = 0
        total_found = 0

        while len(all_contacts) < max_contacts:
            page_result = self.search_domain(domain, limit=limit, offset=offset)
            total_found = page_result.total_found
            all_contacts.extend(page_result.contacts)

            if not page_result.has_more or not page_result.contacts:
                break
            offset += limit

        return ContactList(
            domain=domain,
            contacts=all_contacts[:max_contacts],
            total_found=total_found,
        )

    # ------------------------------------------------------------------
    # Mock implementation
    # ------------------------------------------------------------------
    def search_domain_mock(self, domain: str) -> ContactList:
        logger.warning("Prospeo API key not set — returning mock contacts for %s.", domain)
        company_name = domain.split(".")[0].title()
        contacts = [
            Contact(
                name=f"Alice {company_name}",
                first_name="Alice",
                last_name=company_name,
                title="Head of Sales",
                linkedin_url=f"https://linkedin.com/in/alice-{domain.split('.')[0]}",
                company=company_name,
                company_domain=domain,
                email_status=VerificationStatus.PENDING,
            ),
            Contact(
                name=f"Bob {company_name}",
                first_name="Bob",
                last_name=company_name,
                title="VP Engineering",
                linkedin_url=f"https://linkedin.com/in/bob-{domain.split('.')[0]}",
                company=company_name,
                company_domain=domain,
                email_status=VerificationStatus.PENDING,
            ),
        ]
        return ContactList(domain=domain, contacts=contacts, total_found=len(contacts))

    def find_contacts(self, domain: str) -> ContactList:
        if not settings.prospeo_api_key:
            return self.search_domain_mock(domain)
        return self.search_domain_all_pages(domain)
