"""Runtime settings, read from environment variables (and an optional .env file)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader so the app runs without extra dependencies."""
    if not path.is_file():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _flag(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    model: str
    db_path: str
    web_search: bool
    free_daily_limit: int
    secure_cookies: bool
    demo_mode: bool
    demo_delay: float
    stripe_secret_key: str = ""
    stripe_price_id: str = ""
    stripe_webhook_secret: str = ""
    public_url: str = ""
    pro_price_label: str = "$12/month"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    admin_emails: tuple[str, ...] = ()
    company_name: str = "Boardroom"
    contact_email: str = "support@example.com"
    legal_updated: str = "October 9, 2026"
    max_concurrent_meetings: int = 2
    pro_daily_limit: int = 50
    pro_price_usd: float = 12.0

    @property
    def billing_enabled(self) -> bool:
        return bool(self.stripe_secret_key and self.stripe_price_id)

    @classmethod
    def from_env(cls) -> "Settings":
        _load_dotenv(ROOT / ".env")
        has_credentials = bool(
            os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
        )
        return cls(
            model=os.environ.get("BOARDROOM_MODEL", "claude-opus-5-5"),
            db_path=os.environ.get("BOARDROOM_DB_PATH", str(ROOT / "data" / "boardroom.db")),
            web_search=_flag("BOARDROOM_WEB_SEARCH", True),
            free_daily_limit=int(os.environ.get("BOARDROOM_FREE_DAILY_LIMIT", "3")),
            secure_cookies=_flag("BOARDROOM_SECURE_COOKIES", False),
            demo_mode=_flag("BOARDROOM_DEMO", False) or not has_credentials,
            demo_delay=float(os.environ.get("BOARDROOM_DEMO_DELAY", "0.025")),
            stripe_secret_key=os.environ.get("STRIPE_SECRET_KEY", ""),
            stripe_price_id=os.environ.get("STRIPE_PRICE_ID", ""),
            stripe_webhook_secret=os.environ.get("STRIPE_WEBHOOK_SECRET", ""),
            public_url=os.environ.get("BOARDROOM_PUBLIC_URL", "").rstrip("/"),
            pro_price_label=os.environ.get("BOARDROOM_PRO_PRICE_LABEL", "$12/month"),
            smtp_host=os.environ.get("SMTP_HOST", ""),
            smtp_port=int(os.environ.get("SMTP_PORT", "587")),
            smtp_username=os.environ.get("SMTP_USERNAME", ""),
            smtp_password=os.environ.get("SMTP_PASSWORD", ""),
            smtp_from=os.environ.get("SMTP_FROM", "") or os.environ.get("SMTP_USERNAME", ""),
            admin_emails=tuple(
                e.strip().lower() for e in os.environ.get("BOARDROOM_ADMIN_EMAILS", "").split(",") if e.strip()
            ),
            pro_price_usd=float(os.environ.get("BOARDROOM_PRO_PRICE_USD", "12")),
            company_name=os.environ.get("BOARDROOM_COMPANY_NAME", "Boardroom"),
            contact_email=os.environ.get("BOARDROOM_CONTACT_EMAIL", "support@example.com"),
            legal_updated=os.environ.get("BOARDROOM_LEGAL_UPDATED", "October 9, 2026"),
            max_concurrent_meetings=int(os.environ.get("BOARDROOM_MAX_CONCURRENT", "2")),
            pro_daily_limit=int(os.environ.get("BOARDROOM_PRO_DAILY_LIMIT", "50")),
        )
