from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from utils.logger import get_logger

logger = get_logger(__name__)


def normalise_domain(domain: str) -> str:
    domain = domain.lower().strip()
    domain = re.sub(r"^https?://", "", domain)
    domain = re.sub(r"^www\.", "", domain)
    return domain.split("/")[0]


def deduplicate(items: list[Any], key_fn: Any) -> list[Any]:
    seen: set = set()
    unique: list[Any] = []
    for item in items:
        k = key_fn(item)
        if k not in seen:
            seen.add(k)
            unique.append(item)
    return unique


def build_email_body(name: str, company: str, title: str) -> tuple[str, str]:
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


def save_json(data: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, default=str, ensure_ascii=False)
    logger.info("Results saved to %s", path)


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def prompt_yes_no(message: str) -> bool:
    while True:
        answer = input(f"{message} (y/n): ").strip().lower()
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            return False
        print("Please enter 'y' or 'n'.")
