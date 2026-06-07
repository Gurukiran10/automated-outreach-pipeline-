"""Utility helpers: domain normalisation, deduplication, email templating, export."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, TypeVar

import pandas as pd

from src.logger import get_logger

logger = get_logger(__name__)

T = TypeVar("T")


# ─── Domain helpers ───────────────────────────────────────────────────────────


def normalise_domain(domain: str) -> str:
    """Strip protocol, www, and trailing path from a domain string."""
    domain = domain.lower().strip()
    domain = re.sub(r"^https?://", "", domain)
    domain = re.sub(r"^www\.", "", domain)
    return domain.split("/")[0]


# ─── Deduplication ────────────────────────────────────────────────────────────


def deduplicate(items: list[T], key_fn: Callable[[T], Any]) -> list[T]:
    """Return *items* with duplicates removed, preserving insertion order."""
    seen: set[Any] = set()
    unique: list[T] = []
    for item in items:
        k = key_fn(item)
        if k not in seen:
            seen.add(k)
            unique.append(item)
    return unique


# ─── Email templating ─────────────────────────────────────────────────────────


def render_email(name: str, company: str, title: str) -> tuple[str, str]:
    """Return (subject, body) for the outreach email template."""
    first_name = name.split()[0] if name else "there"
    subject = f"Quick idea for {company}"
    body = (
        f"Hi {first_name},\n\n"
        f"I came across {company} and noticed your role as {title}.\n\n"
        "I wanted to reach out because we help companies improve outbound "
        "prospecting and automate outreach.\n\n"
        "Would love to connect.\n\n"
        "Best regards,\n"
        "Gurukiran"
    )
    return subject, body


# ─── Export ───────────────────────────────────────────────────────────────────


def _timestamped_stem(stem: str) -> str:
    ts = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"{stem}_{ts}"


def export_contacts_csv(rows: list[dict[str, Any]], data_dir: Path, stem: str = "contacts") -> Path:
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / f"{_timestamped_stem(stem)}.csv"
    df = pd.DataFrame(rows)
    df.to_csv(path, index=False, encoding="utf-8")
    logger.info("Contacts exported to CSV: %s (%d rows)", path, len(df))
    return path


def export_results_csv(rows: list[dict[str, Any]], data_dir: Path, stem: str = "email_results") -> Path:
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / f"{_timestamped_stem(stem)}.csv"
    df = pd.DataFrame(rows)
    df.to_csv(path, index=False, encoding="utf-8")
    logger.info("Email results exported to CSV: %s (%d rows)", path, len(df))
    return path


def export_json(data: Any, data_dir: Path, stem: str = "results") -> Path:
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / f"{_timestamped_stem(stem)}.json"
    with path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, default=str, ensure_ascii=False)
    logger.info("Results exported to JSON: %s", path)
    return path


# ─── CLI prompt ───────────────────────────────────────────────────────────────


def confirm(prompt: str) -> bool:
    """Prompt the user for a yes/no answer; return True for 'y'."""
    while True:
        answer = input(f"{prompt} (y/n): ").strip().lower()
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            return False
        print("  Please enter 'y' or 'n'.")
