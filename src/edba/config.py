"""Runtime settings, read from environment variables prefixed with ``EDBA_``."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="EDBA_", env_file=".env", extra="ignore")

    env: Literal["dev", "test", "prod"] = "dev"
    database_url: str = "sqlite:///./edba.db"
    secret_key: str = Field(default="dev-only-change-me-0123456789abcdef", min_length=32)
    # Fernet key for secrets at rest (bank passwords). Derived from secret_key when empty.
    data_key: str = ""
    upload_dir: Path = Path("./var/uploads")

    # Bootstrap T-Admin
    t_admin_email: str = "tadmin@edba.example"

    # Login one-time codes
    otp_ttl_seconds: int = 300
    otp_max_attempts: int = 5

    # Mail: "inbox" stores messages in the database (viewable at /dev/mailbox), "smtp" sends.
    mail_backend: Literal["inbox", "smtp"] = "inbox"
    mail_from: str = "no-reply@edba.example"
    smtp_host: str = "localhost"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""

    # External connectors
    bank_gateway_url: str = "http://127.0.0.1:8000/gateway"
    connector_timeout_seconds: float = 10.0
    # Comma separated host allow-list for outbound API calls; empty = allow all.
    connector_allowed_hosts: str = ""
    # Mount the demo campus/bank gateway inside the web app under /gateway.
    mount_demo_gateway: bool = True

    # API tokens
    token_ttl_minutes: int = 60

    # Fixed system settlement account (the platform's own bank account)
    system_bank_name: str = "E-DBA Bank"
    system_account_name: str = "E-DBA account"
    system_account_no: str = "596117071864958"

    @property
    def is_dev(self) -> bool:
        return self.env == "dev"

    @property
    def allowed_hosts(self) -> set[str]:
        return {h.strip().lower() for h in self.connector_allowed_hosts.split(",") if h.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()
