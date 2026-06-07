from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


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
        return v.lower().strip().removeprefix("https://").removeprefix("http://").rstrip("/")

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
