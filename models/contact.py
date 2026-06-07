from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, HttpUrl, field_validator


class VerificationStatus(str, Enum):
    VERIFIED = "verified"
    CATCH_ALL = "catch_all"
    INVALID = "invalid"
    UNKNOWN = "unknown"
    PENDING = "pending"


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

    @field_validator("linkedin_url")
    @classmethod
    def normalise_linkedin(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if v and not v.startswith("http"):
            v = f"https://www.linkedin.com/in/{v}"
        return v

    @property
    def display_name(self) -> str:
        return self.first_name or self.name.split()[0] if self.name else "there"

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


class ContactList(BaseModel):
    domain: str
    contacts: list[Contact] = Field(default_factory=list)
    total_found: int = 0
    page: int = 1
    has_more: bool = False
