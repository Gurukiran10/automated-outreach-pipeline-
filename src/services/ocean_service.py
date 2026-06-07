"""OceanService — wrapper around the Ocean.io Company Search API (v3)."""
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

from src.config import get_app, get_ocean
from src.logger import get_logger
from src.models import Company, LookalikeResponse

logger = get_logger(__name__)

# ─── Ocean.io API v3 reference ────────────────────────────────────────────────
#
# Auth:  API token passed as QUERY PARAMETER — NOT a header
#        POST https://api.ocean.io/v3/search/companies?apiToken=YOUR_KEY
#
# Request body:
# {
#   "size": 10,                             # max results per call
#   "searchAfter": "cursor-string",         # omit on first page
#   "companiesFilters": {
#     "lookalikeDomains": ["stripe.com"]    # flat list of seed domains
#   }
# }
# Note: no "from" field, no "minScore", no "matchingStrategy" — v3 removed them.
#
# Response:
# {
#   "searchAfter": "NoRgrAbCA...",          # STRING cursor — omit key if last page
#   "detail":      "OK",
#   "total":       15599,
#   "creditsUsed": 0.4,
#   "companies": [
#     {
#       "company": {
#         "domain":              "adyen.com",
#         "name":                "Adyen",
#         "employeeCountOcean":  5123,       # integer
#         "primaryCountry":      "nl",       # 2-letter ISO code
#         "industries":          ["FinTech", "Financial Services"],
#         "industryCategories":  ["Financial Services", "Payments"],
#         "description":         "...",
#         "companySize":         "1001-5000",
#         ...
#       },
#       "relevance": "A"                    # letter grade: A > B > C > D
#     }
#   ]
# }
# ─────────────────────────────────────────────────────────────────────────────

_RETRYABLE = (
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
    requests.exceptions.ChunkedEncodingError,
)

# Map Ocean.io relevance letter grades to a 0–1 similarity score
_RELEVANCE_SCORE: dict[str, float] = {
    "A": 1.00,
    "B": 0.80,
    "C": 0.60,
    "D": 0.40,
}


def _require_key() -> None:
    if not get_ocean().api_key:
        raise EnvironmentError(
            "OCEAN_API_KEY is not set. "
            "Add it to your .env file before calling Ocean.io."
        )


class OceanService:
    """Find lookalike companies given a seed domain via Ocean.io."""

    def __init__(self) -> None:
        self._cfg = get_ocean()
        self._app = get_app()
        self._session = requests.Session()
        self._session.headers.update(
            {
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
    def _post(self, path: str, payload: dict[str, Any]) -> requests.Response:
        url = f"{self._cfg.base_url.rstrip('/')}/{path.lstrip('/')}"
        params = {"apiToken": self._cfg.api_key}

        logger.debug("POST %s | payload=%s", url, payload)
        t0 = time.monotonic()
        response = self._session.post(
            url, json=payload, params=params, timeout=self._app.request_timeout_seconds
        )
        elapsed = time.monotonic() - t0
        logger.debug(
            "POST %s | status=%d | elapsed=%.2fs", url, response.status_code, elapsed
        )
        return response

    def _handle_rate_limit(self, response: requests.Response) -> None:
        if response.status_code == 429:
            wait = float(
                response.headers.get("Retry-After", self._app.retry_wait_seconds)
            )
            logger.warning(
                "Ocean.io rate limit hit — waiting %.1fs (Retry-After header)", wait
            )
            time.sleep(wait)

    # ── Response parsing ──────────────────────────────────────────────────────

    @staticmethod
    def _parse_company(item: dict[str, Any]) -> Company | None:
        """
        Map a v3 result item to our Company model.

        Accepts either a full item dict {"company": {...}, "relevance": "A"}
        or a bare company dict (used in tests).
        """
        if "company" in item:
            c = item["company"]
            relevance = item.get("relevance")
        else:
            c = item
            relevance = item.get("relevance") or item.get("score")

        domain = c.get("domain") or c.get("website") or c.get("rootUrl") or ""
        if not domain:
            return None

        employee_count = c.get("employeeCountOcean") or c.get("employeeCountLinkedin")
        if employee_count is not None:
            try:
                employee_count = int(employee_count)
            except (TypeError, ValueError):
                employee_count = None

        country = c.get("primaryCountry") or c.get("country")

        industries = c.get("industries") or c.get("industryCategories") or []
        industry = industries[0] if industries else c.get("industry")

        if isinstance(relevance, str):
            similarity_score = _RELEVANCE_SCORE.get(relevance.upper())
        elif isinstance(relevance, (int, float)):
            similarity_score = float(relevance)
        else:
            similarity_score = None

        return Company(
            domain=domain,
            name=c.get("name") or c.get("companyName"),
            industry=industry,
            employee_count=employee_count,
            country=country,
            description=c.get("description"),
            similarity_score=similarity_score,
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def search_lookalikes(
        self,
        domain: str,
        limit: int | None = None,
        search_after: str | None = None,
    ) -> tuple[list[Company], int, str | None]:
        """
        Single-page lookalike search.

        Returns (companies, total_found, next_search_after_cursor).
        Pass *search_after* from the previous call to paginate.
        """
        _require_key()
        limit = limit or self._cfg.lookalike_limit

        payload: dict[str, Any] = {
            "size": limit,
            "companiesFilters": {
                "lookalikeDomains": [domain],
            },
        }
        if search_after:
            payload["searchAfter"] = search_after

        logger.info(
            "Ocean.io — searching lookalikes for %s (limit=%d)",
            domain,
            limit,
        )

        response = self._post("/v3/search/companies", payload)
        self._handle_rate_limit(response)

        if response.status_code == 429:
            response = self._post("/v3/search/companies", payload)

        if response.status_code == 401:
            raise PermissionError(
                "Ocean.io: Invalid API token. "
                "Check OCEAN_API_KEY in your .env file."
            )
        if response.status_code == 400:
            detail = response.json() if response.content else {}
            raise ValueError(f"Ocean.io bad request: {detail}")

        response.raise_for_status()
        data: dict = response.json()

        items = data.get("companies") or []
        total = data.get("total") or len(items)
        next_cursor: str | None = data.get("searchAfter") or None

        companies: list[Company] = []
        for item in items:
            company = self._parse_company(item)
            if company:
                companies.append(company)

        logger.info(
            "Ocean.io — page returned %d companies (total available: %d)",
            len(companies),
            total,
        )
        return companies, total, next_cursor

    def find_lookalikes(self, domain: str, limit: int | None = None) -> LookalikeResponse:
        """
        Fetch lookalike companies, walking pages with the searchAfter cursor
        until *limit* results are collected or no more pages remain.
        """
        limit = limit or self._cfg.lookalike_limit
        all_companies: list[Company] = []
        total_found = 0
        cursor: str | None = None

        while len(all_companies) < limit:
            batch_size = min(limit - len(all_companies), 100)
            companies, total_found, cursor = self.search_lookalikes(
                domain, limit=batch_size, search_after=cursor
            )
            all_companies.extend(companies)
            if not companies or cursor is None:
                break

        all_companies = all_companies[:limit]
        logger.info(
            "Ocean.io — collected %d lookalike companies for %s",
            len(all_companies),
            domain,
        )
        return LookalikeResponse(
            source_domain=domain,
            companies=all_companies,
            total_found=total_found,
        )

    def run(self, domain: str, limit: int | None = None) -> LookalikeResponse:
        """Entry point used by the pipeline."""
        _require_key()
        return self.find_lookalikes(domain, limit)
