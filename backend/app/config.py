"""Application configuration loaded from environment variables."""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Central settings object. All values come from env / .env file."""

    # Database
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5434/leadpilot"

    # Ollama
    OLLAMA_HOST: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "gemma3:1b"

    # Gmail / n8n
    GMAIL_ENABLED: bool = True

    # Outreach guardrails
    OUTREACH_SENDING_ENABLED: bool = True
    DAILY_SEND_CAP: int = 100
    N8N_WEBHOOK_URL: str = ""  # n8n webhook URL for pushing outreach tasks
    N8N_API_URL: str = ""      # optional n8n REST API base URL
    N8N_API_KEY: str = ""      # optional n8n API key

    # WhatsApp
    WHATSAPP_ENABLED: bool = False
    WHATSAPP_PROVIDER: str = ""
    WHATSAPP_API_URL: str = ""
    WHATSAPP_ACCESS_TOKEN: str = ""

    # Google OAuth (Gmail + Calendar)
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = "http://localhost:8001/api/auth/google/callback"
    GOOGLE_CALENDAR_ENABLED: bool = False
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REFRESH_TOKEN: str = ""

    # App
    APP_URL: str = "http://localhost:8001"
    FRONTEND_URL: str = "http://localhost:5173"
    MEETING_DURATION_MINUTES: int = 30
    FOLLOWUP_DELAY_HOURS: int = 24
    FOLLOWUP_SCAN_INTERVAL_MINUTES: int = 60
    FOLLOWUP_SCHEDULER_ENABLED: bool = True

    # Security
    SECRET_KEY: str = "change-me-in-production"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24

    # Enrichment
    CRAWL_DELAY_SECONDS: float = 2.0
    MAX_RETRIES: int = 2
    ENRICHMENT_TIMEOUT_SECONDS: int = 15

    # Bulk Gmail sending (5s+ pacing keeps us under Gmail's per-user
    # rate limit; 429s are retried with backoff inside gmail.send_email)
    BULK_SEND_LIMIT: int = 50
    BULK_SEND_DELAY_SECONDS: float = 5.0

    # Crawler parallelism (one browser per worker; DB writes stay serialized)
    CRAWL_WORKERS: int = 3

    # Automated daily sending (scheduler; Gmail quota-aware)
    AUTO_SEND_ENABLED: bool = False
    AUTO_SEND_HOUR: int = 9
    AUTO_SEND_DAILY_LIMIT: int = 100
    AUTO_SEND_DAY_QUOTA: int = 450

    # Automated daily send (scheduler)
    AUTO_SEND_ENABLED: bool = True
    AUTO_SEND_DAILY_LIMIT: int = 100
    AUTO_SEND_HOUR_UTC: int = 9

    # Automatic 24h email follow-ups (scheduler; fail-closed)
    FOLLOWUP_AUTO_SEND_ENABLED: bool = True
    FOLLOWUP_AUTO_SEND_LIMIT: int = 20

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
