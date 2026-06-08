from __future__ import annotations

from config.settings import get_settings
from models.contact import Contact, VerificationStatus
from models.email_result import PipelineResult, SendStatus
from services.brevo_service import BrevoService
from services.ocean_service import OceanService
from services.prospeo_service import ProspeoService
from utils.helpers import deduplicate, normalise_domain, prompt_yes_no, save_json
from utils.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()


class OutreachPipeline:
    def __init__(self) -> None:
        self.ocean = OceanService()
        self.prospeo = ProspeoService()
        self.brevo = BrevoService()

    # ------------------------------------------------------------------
    # Stage 1 – Ocean.io: lookalike companies
    # ------------------------------------------------------------------
    def stage_lookalikes(self, domain: str) -> list[str]:
        logger.info("=== Stage 1: Ocean.io Lookalikes ===")
        result = self.ocean.find_lookalikes(domain)
        domains = [normalise_domain(c.domain) for c in result.companies if c.domain]
        domains = deduplicate(domains, key_fn=lambda d: d)
        logger.info("Found %d unique lookalike domains.", len(domains))
        return domains

    # ------------------------------------------------------------------
    # Stage 2 – Prospeo: contacts per domain
    # ------------------------------------------------------------------
    def stage_contacts(self, domains: list[str]) -> list[Contact]:
        logger.info("=== Stage 2: Prospeo Contact Search ===")
        all_contacts: list[Contact] = []

        for domain in domains:
            try:
                result = self.prospeo.find_contacts(domain)
                all_contacts.extend(result.contacts)
                logger.info("  %s → %d contacts", domain, len(result.contacts))
            except Exception as exc:
                logger.error("Prospeo error for %s: %s", domain, exc)

        all_contacts = deduplicate(
            all_contacts,
            key_fn=lambda c: c.linkedin_url or c.email or c.name,
        )
        logger.info("Total unique contacts: %d", len(all_contacts))
        return all_contacts

    # ------------------------------------------------------------------
    # Stage 3 – Prospeo Email Selection
    # ------------------------------------------------------------------
    def stage_verify_emails(self, contacts: list[Contact]) -> list[Contact]:
        logger.info("=== Stage 3: Prospeo Email Selection ===")
        for c in contacts:
            if c.email and not c.verified_email:
                c.verified_email = c.email
                c.email_status = VerificationStatus.VERIFIED

        verified = [c for c in contacts if c.verified_email or c.email]
        logger.info(
            "Selected %d contacts with emails out of %d.",
            len(verified),
            len(contacts),
        )
        return verified

    # ------------------------------------------------------------------
    # Stage 4 – Brevo: send emails (after user confirmation)
    # ------------------------------------------------------------------
    def stage_send_emails(self, contacts: list[Contact], pipeline_result: PipelineResult) -> PipelineResult:
        logger.info("=== Stage 4: Brevo Email Dispatch ===")

        print(pipeline_result.summary())
        if not contacts:
            print("\nNo contacts with verified emails. Nothing to send.")
            return pipeline_result

        if not prompt_yes_no("\nProceed to send emails?"):
            logger.info("User chose not to send emails.")
            pipeline_result.emails_skipped = len(contacts)
            return pipeline_result

        results = self.brevo.dispatch(contacts)
        pipeline_result.email_results = results
        pipeline_result.emails_sent = sum(1 for r in results if r.status == SendStatus.SENT)
        pipeline_result.emails_failed = sum(1 for r in results if r.status == SendStatus.FAILED)
        pipeline_result.emails_skipped = sum(1 for r in results if r.status == SendStatus.SKIPPED)

        logger.info(
            "Emails — sent: %d | failed: %d | skipped: %d",
            pipeline_result.emails_sent,
            pipeline_result.emails_failed,
            pipeline_result.emails_skipped,
        )
        return pipeline_result

    # ------------------------------------------------------------------
    # Orchestrator
    # ------------------------------------------------------------------
    def run(self, domain: str) -> PipelineResult:
        domain = normalise_domain(domain)
        logger.info("Starting outreach pipeline for: %s", domain)

        pipeline_result = PipelineResult(source_domain=domain)

        # Stage 1
        lookalike_domains = self.stage_lookalikes(domain)
        pipeline_result.companies_found = len(lookalike_domains)
        pipeline_result.companies = [{"domain": d} for d in lookalike_domains]

        # Stage 2
        contacts = self.stage_contacts(lookalike_domains)
        pipeline_result.contacts_found = len(contacts)
        pipeline_result.contacts = [c.model_dump() for c in contacts]

        # Stage 3
        verified_contacts = self.stage_verify_emails(contacts)
        pipeline_result.verified_emails = len(verified_contacts)

        # Stage 4 (with safety checkpoint)
        pipeline_result = self.stage_send_emails(verified_contacts, pipeline_result)

        # Persist results
        output_path = settings.output_path
        save_json(pipeline_result.model_dump(), output_path)
        logger.info("Pipeline complete. Results at %s", output_path)

        return pipeline_result
