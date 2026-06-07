"""Centralised configuration — all settings loaded from environment / .env file."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class OceanSettings(BaseSettings):
    api_key: str = Field(default="", alias="OCEAN_API_KEY")
    # Auth is passed as ?apiToken= query param — base URL has no path version
    base_url: str = Field(default="https://api.ocean.io", alias="OCEAN_BASE_URL")
    lookalike_limit: int = Field(default=10, alias="OCEAN_LOOKALIKE_LIMIT")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)


class ProspeoSettings(BaseSettings):
    api_key: str = Field(default="", alias="PROSPEO_API_KEY")
    base_url: str = Field(default="https://api.prospeo.io", alias="PROSPEO_BASE_URL")
    # Max contacts fetched per lookalike domain (25 per page, Prospeo max)
    contacts_per_domain: int = Field(default=25, alias="PROSPEO_CONTACTS_PER_DOMAIN")
    # Max pages to walk per domain when paginating
    max_pages: int = Field(default=4, alias="PROSPEO_MAX_PAGES")
    # Only return contacts with a verified email from /search-person
    only_verified_email: bool = Field(default=True, alias="PROSPEO_ONLY_VERIFIED_EMAIL")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)


class EazyReachSettings(BaseSettings):
    api_key: str = Field(default="", alias="EAZYREACH_API_KEY")
    # TODO: Confirm base URL with EazyReach support team
    base_url: str = Field(default="https://api.eazyreach.io/v1", alias="EAZYREACH_BASE_URL")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)


class BrevoSettings(BaseSettings):
    api_key: str = Field(default="", alias="BREVO_API_KEY")
    base_url: str = Field(default="https://api.brevo.com/v3", alias="BREVO_BASE_URL")
    sender_name: str = Field(default="Gurukiran", alias="BREVO_SENDER_NAME")
    sender_email: str = Field(default="gurukiran.s@seedlinglabs.com", alias="BREVO_SENDER_EMAIL")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)


class AppSettings(BaseSettings):
    # HTTP
    request_timeout_seconds: int = Field(default=30, alias="REQUEST_TIMEOUT_SECONDS")
    retry_max_attempts: int = Field(default=3, alias="RETRY_MAX_ATTEMPTS")
    retry_wait_seconds: float = Field(default=2.0, alias="RETRY_WAIT_SECONDS")
    retry_backoff_multiplier: float = Field(default=2.0, alias="RETRY_BACKOFF_MULTIPLIER")

    # Directories
    data_dir: Path = Field(default=Path("data"), alias="DATA_DIR")
    log_dir: Path = Field(default=Path("logs"), alias="LOG_DIR")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    @field_validator("log_level")
    @classmethod
    def upper_log_level(cls, v: str) -> str:
        return v.upper()

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_ocean() -> OceanSettings:
    return OceanSettings()


@lru_cache(maxsize=1)
def get_prospeo() -> ProspeoSettings:
    return ProspeoSettings()


@lru_cache(maxsize=1)
def get_eazyreach() -> EazyReachSettings:
    return EazyReachSettings()


@lru_cache(maxsize=1)
def get_brevo() -> BrevoSettings:
    return BrevoSettings()


@lru_cache(maxsize=1)
def get_app() -> AppSettings:
    return AppSettings()
