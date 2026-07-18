"""Config layer. Reads env vars; auto-detects LIVE vs MOCK per capability."""
from __future__ import annotations
import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Settings:
    start_url: str = "https://anishgupta.eu"
    max_pages: int = 250
    max_depth: int = 5
    request_delay: float = 0.15
    timeout: int = 20

    # thresholds (deterministic rule engine)
    title_min: int = 15
    title_max: int = 65
    desc_min: int = 50
    desc_max: int = 160
    thin_words: int = 150

    # secrets / live hooks (absent -> that capability degrades to mock/console)
    claude_api_key: str = field(default_factory=lambda: os.getenv("CLAUDE_API_KEY", "").strip())
    claude_model: str = field(default_factory=lambda: os.getenv("CLAUDE_MODEL", "claude-sonnet-5"))
    slack_webhook: str = field(default_factory=lambda: os.getenv("SLACK_WEBHOOK_URL", "").strip())
    dataforseo_login: str = field(default_factory=lambda: os.getenv("DATAFORSEO_LOGIN", "").strip())
    dataforseo_password: str = field(default_factory=lambda: os.getenv("DATAFORSEO_PASSWORD", "").strip())

    # email (SMTP) — defaults target Gmail; override host/port for other providers
    email_from: str = field(default_factory=lambda: os.getenv("EMAIL_FROM", "").strip())
    email_app_password: str = field(default_factory=lambda: os.getenv("EMAIL_APP_PASSWORD", "").strip())
    email_to: str = field(default_factory=lambda: os.getenv("EMAIL_TO", "").strip())
    smtp_host: str = field(default_factory=lambda: os.getenv("SMTP_HOST", "smtp.gmail.com"))
    smtp_port: int = field(default_factory=lambda: int(os.getenv("SMTP_PORT", "587")))

    # AI cost model (USD per 1M tokens) — sonnet-class defaults
    price_in_per_m: float = 3.0
    price_out_per_m: float = 15.0

    base_dir: Path = field(default_factory=lambda: Path(__file__).resolve().parent.parent)

    @property
    def ai_mode(self) -> str:
        return "live" if self.claude_api_key else "mock"

    @property
    def slack_mode(self) -> str:
        return "live" if self.slack_webhook else "console"

    @property
    def serp_mode(self) -> str:
        return "live" if (self.dataforseo_login and self.dataforseo_password) else "mock"

    @property
    def email_mode(self) -> str:
        return "live" if (self.email_from and self.email_app_password and self.email_to) else "off"

    @property
    def db_path(self) -> Path:
        return self.base_dir / "warehouse.db"

    @property
    def out_dir(self) -> Path:
        d = self.base_dir / "reports"
        d.mkdir(exist_ok=True)
        return d

    def banner(self) -> str:
        return (f"mode: AI={self.ai_mode} · Slack={self.slack_mode} · Email={self.email_mode} "
                f"· SERP={self.serp_mode} · model={self.claude_model if self.ai_mode == 'live' else '—'}")
