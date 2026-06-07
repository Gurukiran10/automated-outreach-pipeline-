"""Unit tests for Pydantic domain models."""
from __future__ import annotations

import pytest

from src.models import (
    Company,
    Contact,
    EmailResult,
    PipelineResult,
    SendStatus,
    VerificationStatus,
)


class TestCompany:
    def test_domain_normalised_on_init(self):
        c = Company(domain="https://www.Stripe.com/payments")
        assert c.domain == "stripe.com"

    def test_domain_strips_http(self):
        assert Company(domain="http://adyen.com").domain == "adyen.com"

    def test_equality_by_domain(self):
        a = Company(domain="stripe.com")
        b = Company(domain="stripe.com", name="Stripe Inc")
        assert a == b

    def test_inequality_different_domains(self):
        assert Company(domain="stripe.com") != Company(domain="adyen.com")

    def test_hashable(self):
        companies = {Company(domain="stripe.com"), Company(domain="adyen.com")}
        assert len(companies) == 2


class TestContact:
    def test_display_name_uses_first_name(self):
        c = Contact(name="John Doe", first_name="John")
        assert c.display_name == "John"

    def test_display_name_falls_back_to_split(self):
        c = Contact(name="Jane Smith")
        assert c.display_name == "Jane"

    def test_best_email_prefers_verified(self):
        c = Contact(name="X", email="x@old.com", verified_email="x@new.com")
        assert c.best_email == "x@new.com"

    def test_best_email_falls_back_to_email(self):
        c = Contact(name="X", email="x@old.com")
        assert c.best_email == "x@old.com"

    def test_linkedin_normalised(self):
        c = Contact(name="X", linkedin_url="johndoe")
        assert c.linkedin_url == "https://www.linkedin.com/in/johndoe"

    def test_linkedin_unchanged_when_full_url(self):
        url = "https://linkedin.com/in/johndoe"
        c = Contact(name="X", linkedin_url=url)
        assert c.linkedin_url == url

    def test_equality_by_linkedin(self):
        a = Contact(name="A", linkedin_url="https://linkedin.com/in/johndoe")
        b = Contact(name="B", linkedin_url="https://linkedin.com/in/johndoe")
        assert a == b

    def test_to_flat_dict_has_expected_keys(self):
        c = Contact(name="John Doe", title="CEO", company="Stripe", company_domain="stripe.com")
        d = c.to_flat_dict()
        assert "name" in d
        assert "title" in d
        assert "verified_email" in d
        assert "email_status" in d

    def test_email_status_default_pending(self):
        c = Contact(name="X")
        assert c.email_status == VerificationStatus.PENDING


class TestEmailResult:
    def test_to_flat_dict_includes_status(self):
        r = EmailResult(
            contact_name="John",
            email="john@stripe.com",
            subject="Hello",
            body="Body",
            status=SendStatus.SENT,
        )
        d = r.to_flat_dict()
        assert d["status"] == "sent"
        assert d["contact_name"] == "John"


class TestPipelineResult:
    def test_summary_rows_returns_expected_count(self):
        r = PipelineResult(source_domain="stripe.com", companies_found=5, contacts_found=10)
        rows = r.summary_rows()
        assert len(rows) == 7

    def test_summary_rows_values_are_strings(self):
        r = PipelineResult(source_domain="stripe.com", companies_found=3)
        for label, value in r.summary_rows():
            assert isinstance(label, str)
            assert isinstance(value, str)
