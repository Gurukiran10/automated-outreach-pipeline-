from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class SendStatus(str, Enum):
    SENT = "sent"
    FAILED = "failed"
    SKIPPED = "skipped"
    PENDING = "pending"


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


class PipelineResult(BaseModel):
    source_domain: str
    run_at: datetime = Field(default_factory=datetime.utcnow)
    companies_found: int = 0
    contacts_found: int = 0
    verified_emails: int = 0
    emails_sent: int = 0
    emails_failed: int = 0
    emails_skipped: int = 0
    companies: list[dict] = Field(default_factory=list)
    contacts: list[dict] = Field(default_factory=list)
    email_results: list[EmailResult] = Field(default_factory=list)

    def summary(self) -> str:
        lines = [
            "",
            "=" * 33,
            "OUTREACH SUMMARY",
            "=" * 33,
            f"Companies Found:  {self.companies_found}",
            f"Contacts Found:   {self.contacts_found}",
            f"Verified Emails:  {self.verified_emails}",
            "=" * 33,
        ]
        return "\n".join(lines)
