"""Config for the AI News Briefing script.

Reads a local `.env` (KEY=VALUE lines) sitting next to this file; real
environment variables override it. No external dependency (no python-dotenv).
"""
import os
import re
from pathlib import Path

_ENV_PATH = Path(__file__).resolve().parent / ".env"


def _load_env(path: Path) -> dict:
    data = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            data[k.strip()] = v.strip().strip('"').strip("'")
    return data


_env = _load_env(_ENV_PATH)


def _get(key, default=""):
    return os.environ.get(key, _env.get(key, default))


def _int(key, default):
    try:
        return int(_get(key, str(default)) or default)
    except (TypeError, ValueError):
        return default


class Config:
    # LLM (OpenAI-compatible chat completions endpoint)
    LLM_BASE_URL = _get("LLM_BASE_URL")     # e.g. https://gateway.example.com/v1
    LLM_API_KEY = _get("LLM_API_KEY")
    LLM_MODEL = _get("LLM_MODEL")

    # Email (SMTP)
    SMTP_HOST = _get("SMTP_HOST")
    SMTP_PORT = _int("SMTP_PORT", 465)
    SMTP_USER = _get("SMTP_USER")
    SMTP_PASS = _get("SMTP_PASS")
    SMTP_SECURITY = (_get("SMTP_SECURITY", "ssl") or "ssl").lower()   # ssl | starttls | plain
    MAIL_FROM = _get("MAIL_FROM") or _get("SMTP_USER")
    MAIL_TO = _get("MAIL_TO") or (_get("MAIL_FROM") or _get("SMTP_USER"))

    # Briefing options
    SOURCES_RAW = _get("SOURCES")           # comma/newline separated; empty => bundled preset
    KEYWORDS = [k for k in re.split(r",", _get("KEYWORDS") or "") if k.strip()]
    WINDOW_HOURS = _int("WINDOW_HOURS", 24)
    PER_FEED_LIMIT = _int("PER_FEED_LIMIT", 10)
    DETAIL_LIMIT = _int("DETAIL_LIMIT", 20)
    CONCURRENCY = _int("CONCURRENCY", 3)
    EXTRACT_TIMEOUT = _int("EXTRACT_TIMEOUT", 90)
    MAX_CONTENT_CHARS = _int("MAX_CONTENT_CHARS", 12000)
    # Retry throttled/5xx LLM calls (gateways rate-limit long runs).
    LLM_MAX_RETRIES = _int("LLM_MAX_RETRIES", 4)
    LLM_BACKOFF_BASE = float(_get("LLM_BACKOFF_BASE", "2") or 2)


CONFIG = Config()
