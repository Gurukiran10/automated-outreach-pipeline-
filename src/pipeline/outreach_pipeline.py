"""OutreachPipeline — orchestrates all four service stages."""
from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

from src.config import get_app
from src.logger import get_logger
from src.models import Contact, PipelineResult, SendStatus, VerificationStatus
from src.services.brevo_service import BrevoService
from src.services.eazyreach_service import EazyReachService
from src.services.ocean_service import OceanService
from src.services.prospeo_service import ProspeoService
from src.utils import (
    confirm,
    deduplicate,
    export_contacts_csv,
    export_json,
    export_results_csv,
    normalise_domain,
)

logger = get_logger(__name__)
console = Console()


class OutreachPipeline:
    def __init__(self) -> None:
        self._ocean = OceanService()
        self._prospeo = ProspeoService()
        self._eazyreach = EazyReachService()
        self._brevo = BrevoService()
        self._app = get_app()

    # ──────────────────────────────────────────────────────────────────
    # Stage 1 — Ocean.io: lookalike companies
    # ──────────────────────────────────────────────────────────────────
    def _stage_lookalikes(self, domain: str, limit: int | None) -> list[str]:
        with Progress(
            SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
            TimeElapsedColumn(), console=console, transient=True,
        ) as progress:
            progress.add_task("Ocean.io — finding lookalike companies…", total=None)
            result = self._ocean.run(domain, limit)

        domains = [normalise_domain(c.domain) for c in result.companies if c.domain]
        domains = deduplicate(domains, key_fn=lambda d: d)
        console.print(f"  [green]✓[/] [bold]{len(domains)}[/] lookalike companies found")
        return domains

    # ──────────────────────────────────────────────────────────────────
    # Stage 2 — Prospeo: contacts per domain
    # ──────────────────────────────────────────────────────────────────
    def _stage_contacts(self, domains: list[str]) -> list[Contact]:
        all_contacts: list[Contact] = []

        with Progress(
            SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
            BarColumn(), TextColumn("{task.completed}/{task.total}"),
            TimeElapsedColumn(), console=console,
        ) as progress:
            task = progress.add_task("Prospeo — searching contacts…", total=len(domains))
            for domain in domains:
                try:
                    result = self._prospeo.run(domain)
                    all_contacts.extend(result.contacts)
                except Exception as exc:
                    logger.error("Prospeo error for %s: %s", domain, exc)
                finally:
                    progress.advance(task)

        all_contacts = deduplicate(
            all_contacts,
            key_fn=lambda c: c.linkedin_url or c.email or c.name,
        )
        console.print(f"  [green]✓[/] [bold]{len(all_contacts)}[/] unique contacts found")
        return all_contacts

    # ──────────────────────────────────────────────────────────────────
    # Stage 3 — EazyReach: verify/enrich emails
    # ──────────────────────────────────────────────────────────────────
    def _stage_enrich(self, contacts: list[Contact]) -> list[Contact]:
        needs_enrichment = [c for c in contacts if c.linkedin_url and not c.verified_email]

        with Progress(
            SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
            BarColumn(), TextColumn("{task.completed}/{task.total}"),
            TimeElapsedColumn(), console=console,
        ) as progress:
            task = progress.add_task("EazyReach — enriching contacts…", total=len(needs_enrichment))
            enriched: list[Contact] = []
            for contact in needs_enrichment:
                try:
                    enriched.append(self._eazyreach.run([contact])[0])
                except Exception as exc:
                    logger.error("EazyReach error for %s: %s", contact.name, exc)
                    enriched.append(contact)
                finally:
                    progress.advance(task)

        # Merge back contacts that already had emails
        already_have = [c for c in contacts if c not in needs_enrichment]
        verified = [
            c for c in enriched
            if c.best_email and c.email_status in (VerificationStatus.VERIFIED, VerificationStatus.CATCH_ALL)
        ]
        verified += [c for c in already_have if c.best_email]

        console.print(f"  [green]✓[/] [bold]{len(verified)}[/] contacts with verified emails")
        return verified

    # ──────────────────────────────────────────────────────────────────
    # Safety checkpoint + Stage 4 — Brevo: send emails
    # ──────────────────────────────────────────────────────────────────
    def _stage_send(self, contacts: list[Contact], result: PipelineResult) -> PipelineResult:
        self._print_checkpoint(result)

        if not contacts:
            console.print("\n[yellow]No contacts with verified emails — nothing to send.[/]")
            return result

        if not confirm("\nProceed to send emails?"):
            logger.info("User declined email dispatch.")
            result.emails_skipped = len(contacts)
            return result

        with Progress(
            SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
            BarColumn(), TextColumn("{task.completed}/{task.total}"),
            TimeElapsedColumn(), console=console,
        ) as progress:
            task = progress.add_task("Brevo — dispatching emails…", total=len(contacts))
            email_results = []
            for contact in contacts:
                try:
                    email_results.append(self._brevo.run([contact])[0])
                except Exception as exc:
                    logger.error("Brevo error for %s: %s", contact.name, exc)
                finally:
                    progress.advance(task)

        result.email_results = email_results
        result.emails_sent = sum(1 for r in email_results if r.status == SendStatus.SENT)
        result.emails_failed = sum(1 for r in email_results if r.status == SendStatus.FAILED)
        result.emails_skipped = sum(1 for r in email_results if r.status == SendStatus.SKIPPED)
        console.print(
            f"  [green]✓[/] Sent [bold]{result.emails_sent}[/] | "
            f"Failed [bold red]{result.emails_failed}[/] | "
            f"Skipped [bold yellow]{result.emails_skipped}[/]"
        )
        return result

    # ──────────────────────────────────────────────────────────────────
    # Rich output helpers
    # ──────────────────────────────────────────────────────────────────
    def _print_checkpoint(self, result: PipelineResult) -> None:
        table = Table(title="OUTREACH SUMMARY", show_header=False, box=None, padding=(0, 2))
        table.add_column("Metric", style="bold")
        table.add_column("Value", justify="right", style="cyan")
        for label, value in result.summary_rows():
            table.add_row(label, value)
        console.print(Panel(table, border_style="bright_blue"))

    def _print_final(self, result: PipelineResult) -> None:
        table = Table(title="PIPELINE COMPLETE", show_header=False, box=None, padding=(0, 2))
        table.add_column("Metric", style="bold")
        table.add_column("Value", justify="right", style="green")
        for label, value in result.summary_rows():
            table.add_row(label, value)
        console.print(Panel(table, border_style="green"))

    # ──────────────────────────────────────────────────────────────────
    # Export helpers
    # ──────────────────────────────────────────────────────────────────
    def _export(self, contacts: list[Contact], result: PipelineResult) -> None:
        data_dir = self._app.data_dir

        contact_rows = [c.to_flat_dict() for c in contacts]
        if contact_rows:
            export_contacts_csv(contact_rows, data_dir)

        email_rows = [r.to_flat_dict() for r in result.email_results]
        if email_rows:
            export_results_csv(email_rows, data_dir)

        export_json(result.model_dump(), data_dir)

    # ──────────────────────────────────────────────────────────────────
    # Orchestrator
    # ──────────────────────────────────────────────────────────────────
    def run(self, domain: str, limit: int | None = None, dry_run: bool = False) -> PipelineResult:
        domain = normalise_domain(domain)
        console.rule(f"[bold blue]Outreach Pipeline — {domain}[/]")

        result = PipelineResult(source_domain=domain)

        # 1. Lookalikes
        console.print("\n[bold cyan]Stage 1 / 4 — Lookalike Companies[/]")
        lookalike_domains = self._stage_lookalikes(domain, limit)
        result.companies_found = len(lookalike_domains)
        result.companies = [{"domain": d} for d in lookalike_domains]

        # 2. Contacts
        console.print("\n[bold cyan]Stage 2 / 4 — Decision-Maker Discovery[/]")
        contacts = self._stage_contacts(lookalike_domains)
        result.contacts_found = len(contacts)
        result.contacts = [c.to_flat_dict() for c in contacts]

        # 3. Enrich
        console.print("\n[bold cyan]Stage 3 / 4 — Email Enrichment[/]")
        verified_contacts = self._stage_enrich(contacts)
        result.verified_emails = len(verified_contacts)

        # 4. Send (or dry-run skip)
        console.print("\n[bold cyan]Stage 4 / 4 — Email Dispatch[/]")
        if dry_run:
            console.print("  [yellow]--dry-run enabled — skipping email dispatch.[/]")
            result.emails_skipped = len(verified_contacts)
        else:
            result = self._stage_send(verified_contacts, result)

        # Export
        self._export(verified_contacts, result)
        self._print_final(result)

        return result
