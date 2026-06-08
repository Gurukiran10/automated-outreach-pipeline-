"""Integration-style tests for OutreachPipeline (all services mocked)."""
from __future__ import annotations

import pytest

from src.models import (
    Company,
    Contact,
    ContactList,
    EmailResult,
    LookalikeResponse,
    SendStatus,
)


@pytest.fixture()
def mock_ocean(mocker):
    svc = mocker.MagicMock()
    svc.run.return_value = LookalikeResponse(
        source_domain="stripe.com",
        companies=[
            Company(domain="adyen.com", name="Adyen", similarity_score=0.91),
            Company(domain="braintree.com", name="Braintree", similarity_score=0.88),
        ],
        total_found=2,
    )
    mocker.patch("src.pipeline.outreach_pipeline.OceanService", return_value=svc)
    return svc


@pytest.fixture()
def mock_prospeo(mocker):
    def _contacts(domain: str):
        return ContactList(
            domain=domain,
            contacts=[
                Contact(
                    name=f"Alice {domain}",
                    first_name="Alice",
                    title="Head of Sales",
                    linkedin_url=f"https://linkedin.com/in/alice-{domain.split('.')[0]}",
                    company=domain.split(".")[0].title(),
                    company_domain=domain,
                    email_status=VerificationStatus.PENDING,
                )
            ],
            total_found=1,
        )

    svc = mocker.MagicMock()
    svc.run.side_effect = _contacts
    mocker.patch("src.pipeline.outreach_pipeline.ProspeoService", return_value=svc)
    return svc



@pytest.fixture()
def mock_brevo(mocker):
    def _send(contacts):
        return [
            EmailResult(
                contact_name=c.name,
                email=c.best_email or "",
                subject="Quick idea",
                body="Body",
                status=SendStatus.SENT,
                message_id="mock-id",
            )
            for c in contacts
        ]

    svc = mocker.MagicMock()
    svc.run.side_effect = _send
    mocker.patch("src.pipeline.outreach_pipeline.BrevoService", return_value=svc)
    return svc


@pytest.fixture()
def mock_confirm_yes(mocker):
    mocker.patch("src.pipeline.outreach_pipeline.confirm", return_value=True)


@pytest.fixture()
def mock_export(mocker):
    mocker.patch("src.pipeline.outreach_pipeline.export_contacts_csv")
    mocker.patch("src.pipeline.outreach_pipeline.export_results_csv")
    mocker.patch("src.pipeline.outreach_pipeline.export_json")


class TestOutreachPipeline:
    def test_dry_run_skips_email_stage(
        self, mock_ocean, mock_prospeo, mock_brevo, mock_export
    ):
        from src.pipeline.outreach_pipeline import OutreachPipeline

        pipeline = OutreachPipeline()
        result = pipeline.run("stripe.com", dry_run=True)

        assert result.companies_found == 2
        assert result.contacts_found > 0
        mock_brevo.run.assert_not_called()
        assert result.emails_skipped > 0

    def test_full_run_sends_emails(
        self,
        mock_ocean,
        mock_prospeo,
        mock_brevo,
        mock_confirm_yes,
        mock_export,
    ):
        from src.pipeline.outreach_pipeline import OutreachPipeline

        pipeline = OutreachPipeline()
        result = pipeline.run("stripe.com")

        assert result.companies_found == 2
        assert result.contacts_found > 0
        assert result.emails_sent > 0
        assert result.emails_failed == 0

    def test_domain_normalised(
        self, mock_ocean, mock_prospeo, mock_brevo, mock_confirm_yes, mock_export
    ):
        from src.pipeline.outreach_pipeline import OutreachPipeline

        pipeline = OutreachPipeline()
        result = pipeline.run("https://www.Stripe.com")
        assert result.source_domain == "stripe.com"

    def test_exports_called(
        self,
        mock_ocean,
        mock_prospeo,
        mock_brevo,
        mock_confirm_yes,
        mocker,
    ):
        contacts_csv = mocker.patch("src.pipeline.outreach_pipeline.export_contacts_csv")
        results_csv = mocker.patch("src.pipeline.outreach_pipeline.export_results_csv")
        json_exp = mocker.patch("src.pipeline.outreach_pipeline.export_json")

        from src.pipeline.outreach_pipeline import OutreachPipeline

        OutreachPipeline().run("stripe.com")

        contacts_csv.assert_called_once()
        results_csv.assert_called_once()
        json_exp.assert_called_once()

    def test_user_declines_no_emails_sent(
        self, mock_ocean, mock_prospeo, mock_brevo, mock_export, mocker
    ):
        mocker.patch("src.pipeline.outreach_pipeline.confirm", return_value=False)

        from src.pipeline.outreach_pipeline import OutreachPipeline

        result = OutreachPipeline().run("stripe.com")
        mock_brevo.run.assert_not_called()
        assert result.emails_skipped > 0
