from __future__ import annotations

import requests

from config.settings import get_settings
from models.company import Company, LookalikeResponse
from utils.logger import get_logger
from utils.retry import retry

logger = get_logger(__name__)
settings = get_settings()

# Ocean.io API reference: https://docs.ocean.io/
# Endpoint: POST /lookalikes
# Request:  { "domain": "stripe.com", "limit": 10, "filters": {...} }
# Response: { "companies": [ { "domain": ..., "name": ..., "industry": ... } ] }


class OceanService:
    """Wrapper around the Ocean.io Lookalike Companies API."""

    def __init__(self) -> None:
        self.base_url = settings.ocean_base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {settings.ocean_api_key}",
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

    def get_lookalikes(self, domain: str, limit: int | None = None) -> LookalikeResponse:
        """Return a list of lookalike companies for *domain*."""
        limit = limit or settings.ocean_lookalike_limit
        logger.info("Fetching lookalikes for domain: %s (limit=%d)", domain, limit)

        # TODO: Replace with actual Ocean.io endpoint path once confirmed.
        response = self._post(
            "/lookalikes",
            {"domain": domain, "limit": limit},
        )

        if response.status_code == 401:
            raise PermissionError("Ocean.io: Invalid API key or insufficient permissions.")

        if response.status_code == 404:
            logger.warning("Ocean.io: No lookalikes found for %s", domain)
            return LookalikeResponse(source_domain=domain)

        response.raise_for_status()
        data: dict = response.json()

        companies = [
            Company(
                domain=item.get("domain", ""),
                name=item.get("name"),
                industry=item.get("industry"),
                employee_count=item.get("employee_count"),
                country=item.get("country"),
                description=item.get("description"),
                similarity_score=item.get("similarity_score"),
            )
            for item in data.get("companies", [])
            if item.get("domain")
        ]

        logger.info("Ocean.io returned %d lookalike companies for %s", len(companies), domain)
        return LookalikeResponse(
            source_domain=domain,
            companies=companies,
            total_found=data.get("total", len(companies)),
        )

    # ------------------------------------------------------------------
    # Mock implementation — used when OCEAN_API_KEY is not set.
    # ------------------------------------------------------------------
    def get_lookalikes_mock(self, domain: str) -> LookalikeResponse:
        logger.warning("Ocean.io API key not set — returning mock lookalikes.")
        mock_domains = [
            "adyen.com",
            "braintree.com",
            "square.com",
            "paypal.com",
            "checkout.com",
            "mollie.com",
            "recurly.com",
            "chargebee.com",
            "zuora.com",
            "paddle.com",
        ]
        companies = [
            Company(domain=d, name=d.split(".")[0].title(), similarity_score=round(0.9 - i * 0.05, 2))
            for i, d in enumerate(mock_domains)
        ]
        return LookalikeResponse(source_domain=domain, companies=companies, total_found=len(companies))

    def find_lookalikes(self, domain: str) -> LookalikeResponse:
        if not settings.ocean_api_key:
            return self.get_lookalikes_mock(domain)
        return self.get_lookalikes(domain)
