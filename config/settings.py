from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings

load_dotenv(Path(__file__).parent.parent / ".env")


class Settings(BaseSettings):
    # Ocean.io
    ocean_api_key: str = Field(default="", env="OCEAN_API_KEY")
    ocean_base_url: str = Field(default="https://api.ocean.io/v1", env="OCEAN_BASE_URL")
    ocean_lookalike_limit: int = Field(default=10, env="OCEAN_LOOKALIKE_LIMIT")

    # Prospeo
    prospeo_api_key: str = Field(default="", env="PROSPEO_API_KEY")
    prospeo_base_url: str = Field(default="https://api.prospeo.io", env="PROSPEO_BASE_URL")
    prospeo_contacts_per_domain: int = Field(default=5, env="PROSPEO_CONTACTS_PER_DOMAIN")

    # Brevo (Sendinblue)
    brevo_api_key: str = Field(default="", env="BREVO_API_KEY")
    brevo_base_url: str = Field(default="https://api.brevo.com/v3", env="BREVO_BASE_URL")
    brevo_sender_name: str = Field(default="Gurukiran", env="BREVO_SENDER_NAME")
    brevo_sender_email: str = Field(default="gurukiran.s@seedlinglabs.com", env="BREVO_SENDER_EMAIL")

    # Retry / rate-limit
    retry_max_attempts: int = Field(default=3, env="RETRY_MAX_ATTEMPTS")
    retry_backoff_factor: float = Field(default=2.0, env="RETRY_BACKOFF_FACTOR")
    retry_initial_wait: float = Field(default=1.0, env="RETRY_INITIAL_WAIT")
    request_timeout: int = Field(default=30, env="REQUEST_TIMEOUT")

    # Output
    output_dir: Path = Field(default=Path("output"), env="OUTPUT_DIR")
    output_file: str = Field(default="results.json", env="OUTPUT_FILE")

    model_config = {"env_file": ".env", "extra": "ignore"}

    @property
    def output_path(self) -> Path:
        return self.output_dir / self.output_file


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
