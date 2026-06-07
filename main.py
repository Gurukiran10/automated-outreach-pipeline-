#!/usr/bin/env python3
"""
Automated Outreach Pipeline — CLI entry point.

Usage:
    python main.py stripe.com
    python main.py stripe.com --limit 5 --dry-run --verbose

    # Service connectivity tests (no domain required):
    python main.py --test-ocean
    python main.py --test-prospeo
    python main.py --test-brevo
"""
from __future__ import annotations

import argparse
import sys

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()


# ─── Argument parser ──────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="outreach",
        description="AI-powered B2B outreach pipeline: Ocean.io → Prospeo → EazyReach → Brevo",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py stripe.com
  python main.py stripe.com --limit 5
  python main.py stripe.com --dry-run
  python main.py stripe.com --limit 3 --dry-run --verbose

  # API connectivity smoke tests:
  python main.py --test-ocean
  python main.py --test-prospeo
  python main.py --test-brevo
        """,
    )

    parser.add_argument(
        "domain",
        nargs="?",
        default=None,
        help="Seed company domain, e.g. stripe.com (not required for --test-* flags)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Max lookalike companies to process (default: OCEAN_LOOKALIKE_LIMIT from .env)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run all stages but skip email dispatch",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable DEBUG-level logging",
    )

    # ── Service test flags ───────────────────────────────────────────────────
    test_group = parser.add_argument_group("service tests")
    test_group.add_argument(
        "--test-ocean",
        action="store_true",
        help="Run Ocean.io connectivity test (requires OCEAN_API_KEY)",
    )
    test_group.add_argument(
        "--test-prospeo",
        action="store_true",
        help="Run Prospeo connectivity test (requires PROSPEO_API_KEY)",
    )
    test_group.add_argument(
        "--test-brevo",
        action="store_true",
        help="Run Brevo connectivity test (requires BREVO_API_KEY)",
    )

    return parser.parse_args()


# ─── Service smoke tests ──────────────────────────────────────────────────────

def _status(ok: bool) -> str:
    return "[green]PASS[/]" if ok else "[red]FAIL[/]"


def test_ocean() -> bool:
    """
    Smoke test: search for a single lookalike of 'stripe.com' and print the result.
    Verifies API key, endpoint, request format, and response parsing.
    """
    console.rule("[bold cyan]Ocean.io connectivity test[/]")
    try:
        from src.services.ocean_service import OceanService
        svc = OceanService()
        console.print("Calling POST /v2/search/companies?apiToken=... (domain=stripe.com, limit=1)")
        result = svc.find_lookalikes("stripe.com", limit=1)
        companies = result.companies

        table = Table(title="Ocean.io result", show_header=True)
        table.add_column("Domain")
        table.add_column("Name")
        table.add_column("Industry")
        table.add_column("Score")
        for c in companies:
            table.add_row(
                c.domain or "—",
                c.name or "—",
                c.industry or "—",
                f"{c.similarity_score:.2f}" if c.similarity_score else "—",
            )
        console.print(table)
        console.print(f"Total available: {result.total_found}")
        console.print(f"\n[bold]{_status(True)} Ocean.io returned {len(companies)} result(s)[/]")
        return True

    except EnvironmentError as exc:
        console.print(f"[red]{exc}[/]")
        return False
    except Exception as exc:
        console.print_exception()
        console.print(f"[red]Ocean.io test FAILED: {exc}[/]")
        return False


def test_prospeo() -> bool:
    """
    Smoke test: fetch account information, then search 1 contact for 'stripe.com'.
    Verifies API key, /account-information, and /search-person endpoints.
    """
    console.rule("[bold cyan]Prospeo connectivity test[/]")
    passed = True
    try:
        from src.services.prospeo_service import ProspeoService
        svc = ProspeoService()

        # 1. Account info
        console.print("Calling GET /account-information …")
        info = svc.get_account_info()
        console.print(
            f"  Plan: [bold]{info.get('current_plan')}[/] | "
            f"Credits remaining: [bold]{info.get('remaining_credits')}[/] | "
            f"Credits used: {info.get('used_credits')}"
        )
        console.print(f"  {_status(True)} /account-information")

        # 2. Person search
        console.print("\nCalling POST /search-person (domain=stripe.com, page=1) …")
        result = svc.search_person("stripe.com", page=1)
        contacts = result.contacts

        table = Table(title="Prospeo /search-person result", show_header=True)
        table.add_column("Name")
        table.add_column("Title")
        table.add_column("Email")
        table.add_column("LinkedIn")
        for c in contacts[:5]:
            table.add_row(
                c.name or "—",
                c.title or "—",
                c.email or c.verified_email or "—",
                (c.linkedin_url or "—")[:50],
            )
        console.print(table)
        console.print(
            f"  Page 1 returned {len(contacts)} contacts | "
            f"total_count={result.total_found} | has_more={result.has_more}"
        )
        console.print(f"  {_status(True)} /search-person")

    except EnvironmentError as exc:
        console.print(f"[red]{exc}[/]")
        passed = False
    except Exception as exc:
        console.print_exception()
        console.print(f"[red]Prospeo test FAILED: {exc}[/]")
        passed = False

    console.print(f"\n[bold]{_status(passed)} Prospeo test {'passed' if passed else 'failed'}[/]")
    return passed


def test_brevo() -> bool:
    """
    Smoke test: verify sender and call GET /senders to confirm the configured
    sender email is active. Does NOT send an actual email.
    """
    console.rule("[bold cyan]Brevo connectivity test[/]")
    passed = True
    try:
        from src.config import get_brevo
        from src.services.brevo_service import BrevoService

        cfg = get_brevo()
        svc = BrevoService()

        console.print(f"Configured sender: {cfg.sender_name} <{cfg.sender_email}>")
        console.print("Calling GET /senders to verify sender is active …")

        is_active = svc.verify_sender()

        table = Table(title="Brevo sender check", show_header=False)
        table.add_column("Field")
        table.add_column("Value")
        table.add_row("sender_name", cfg.sender_name)
        table.add_row("sender_email", cfg.sender_email)
        table.add_row("sender_active", "Yes" if is_active else "No — verify in Brevo dashboard")
        table.add_row("base_url", cfg.base_url)
        console.print(table)

        if not is_active:
            console.print(
                "[yellow]Sender not yet active. "
                "Go to app.brevo.com → Senders & IP → Add a sender.[/]"
            )
            passed = False
        else:
            console.print(f"  {_status(True)} Sender verified")

    except EnvironmentError as exc:
        console.print(f"[red]{exc}[/]")
        passed = False
    except Exception as exc:
        console.print_exception()
        console.print(f"[red]Brevo test FAILED: {exc}[/]")
        passed = False

    console.print(f"\n[bold]{_status(passed)} Brevo test {'passed' if passed else 'failed'}[/]")
    return passed


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    args = parse_args()

    if args.verbose:
        import logging
        for name in [
            "src.services.ocean_service",
            "src.services.prospeo_service",
            "src.services.eazyreach_service",
            "src.services.brevo_service",
            "src.pipeline.outreach_pipeline",
        ]:
            logging.getLogger(name).setLevel(logging.DEBUG)

    # ── Service test mode ────────────────────────────────────────────────────
    any_test = args.test_ocean or args.test_prospeo or args.test_brevo
    if any_test:
        results: dict[str, bool] = {}
        if args.test_ocean:
            results["Ocean.io"] = test_ocean()
            console.print()
        if args.test_prospeo:
            results["Prospeo"] = test_prospeo()
            console.print()
        if args.test_brevo:
            results["Brevo"] = test_brevo()
            console.print()

        # Summary table
        table = Table(title="Test Summary", show_header=True)
        table.add_column("Service")
        table.add_column("Result")
        for service, ok in results.items():
            table.add_row(service, _status(ok))
        console.print(Panel(table, border_style="blue"))

        sys.exit(0 if all(results.values()) else 1)

    # ── Pipeline mode ────────────────────────────────────────────────────────
    if not args.domain:
        console.print(
            "[red]Error:[/] A domain is required for pipeline mode.\n"
            "Usage: python main.py stripe.com\n"
            "       python main.py --test-ocean  (to test without a domain)"
        )
        sys.exit(1)

    try:
        from src.pipeline.outreach_pipeline import OutreachPipeline
        pipeline = OutreachPipeline()
        pipeline.run(domain=args.domain, limit=args.limit, dry_run=args.dry_run)

    except KeyboardInterrupt:
        console.print("\n[yellow]Pipeline interrupted by user.[/]")
        sys.exit(0)
    except EnvironmentError as exc:
        console.print(f"\n[red]Configuration error:[/] {exc}")
        sys.exit(1)
    except PermissionError as exc:
        console.print(f"\n[red]API authentication error:[/] {exc}")
        sys.exit(1)
    except Exception:
        console.print_exception()
        sys.exit(1)


if __name__ == "__main__":
    main()
