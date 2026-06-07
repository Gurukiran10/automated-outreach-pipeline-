"""All domain models for the outreach platform."""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


# ─── Enums ────────────────────────────────────────────────────────────────────


class VerificationStatus(str, Enum):
    VERIFIED = "verified"
    CATCH_ALL = "catch_all"
    INVALID = "invalid"
    UNKNOWN = "unknown"
    PENDING = "pending"


class SendStatus(str, Enum):
    SENT = "sent"
    FAILED = "failed"
    SKIPPED = "skipped"
    PENDING = "pending"


# ─── Company ──────────────────────────────────────────────────────────────────


class Company(BaseModel):
    domain: str
    name: str | None = None
    industry: str | None = None
    employee_count: int | None = None
    country: str | None = None
    description: str | None = None
    similarity_score: float | None = None

    @field_validator("domain")
    @classmethod
    def normalise_domain(cls, v: str) -> str:
        return (
            v.lower()
            .strip()
            .removeprefix("https://")
            .removeprefix("http://")
            .removeprefix("www.")
            .split("/")[0]
        )

    def __hash__(self) -> int:
        return hash(self.domain)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Company):
            return NotImplemented
        return self.domain == other.domain


class LookalikeResponse(BaseModel):
    source_domain: str
    companies: list[Company] = Field(default_factory=list)
    total_found: int = 0


# ─── Contact ──────────────────────────────────────────────────────────────────


class Contact(BaseModel):
    name: str
    first_name: str | None = None
    last_name: str | None = None
    title: str | None = None
    linkedin_url: str | None = None
    company: str | None = None
    company_domain: str | None = None
    email: str | None = None
    verified_email: str | None = None
    email_status: VerificationStatus = VerificationStatus.PENDING

    # EazyReach enrichment fields
    phone: str | None = None
    location: str | None = None
    seniority: str | None = None
    department: str | None = None

    @field_validator("linkedin_url")
    @classmethod
    def normalise_linkedin(cls, v: str | None) -> str | None:
        if not v:
            return None
        v = v.strip()
        if not v.startswith("http"):
            v = f"https://www.linkedin.com/in/{v}"
        return v

    @property
    def display_name(self) -> str:
        return self.first_name or (self.name.split()[0] if self.name else "there")

    @property
    def best_email(self) -> str | None:
        return self.verified_email or self.email

    def __hash__(self) -> int:
        return hash(self.linkedin_url or self.email or self.name)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Contact):
            return NotImplemented
        if self.linkedin_url and other.linkedin_url:
            return self.linkedin_url == other.linkedin_url
        if self.email and other.email:
            return self.email == other.email
        return self.name == other.name

    def to_flat_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "title": self.title,
            "company": self.company,
            "company_domain": self.company_domain,
            "email": self.email,
            "verified_email": self.verified_email,
            "email_status": self.email_status.value,
            "linkedin_url": self.linkedin_url,
            "phone": self.phone,
            "location": self.location,
            "seniority": self.seniority,
            "department": self.department,
        }


class ContactList(BaseModel):
    domain: str
    contacts: list[Contact] = Field(default_factory=list)
    total_found: int = 0
    page: int = 1
    has_more: bool = False


# ─── Email ────────────────────────────────────────────────────────────────────


class EmailResult(BaseModel):
    contact_name: str
    contact_title: str | None = None
    company: str | None = None
    email: str
    subject: str
    body: str
    status: SendStatus = SendStatus.PENDING
    message_id: str | None = None
    error: str | None = None
    sent_at: datetime | None = None

    def to_flat_dict(self) -> dict[str, Any]:
        return {
            "contact_name": self.contact_name,
            "contact_title": self.contact_title,
            "company": self.company,
            "email": self.email,
            "subject": self.subject,
            "status": self.status.value,
            "message_id": self.message_id,
            "error": self.error,
            "sent_at": str(self.sent_at) if self.sent_at else None,
        }


# ─── Pipeline result ──────────────────────────────────────────────────────────


class PipelineResult(BaseModel):
    source_domain: str
    run_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))
    companies_found: int = 0
    contacts_found: int = 0
    verified_emails: int = 0
    emails_sent: int = 0
    emails_failed: int = 0
    emails_skipped: int = 0
    companies: list[dict[str, Any]] = Field(default_factory=list)
    contacts: list[dict[str, Any]] = Field(default_factory=list)
    email_results: list[EmailResult] = Field(default_factory=list)

    def summary_rows(self) -> list[tuple[str, str]]:
        return [
            ("Source domain", self.source_domain),
            ("Companies found", str(self.companies_found)),
            ("Contacts found", str(self.contacts_found)),
            ("Verified emails", str(self.verified_emails)),
            ("Emails sent", str(self.emails_sent)),
            ("Emails failed", str(self.emails_failed)),
            ("Emails skipped", str(self.emails_skipped)),
        ]
