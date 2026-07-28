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


def _bool(key, default):
    v = _get(key, "").strip().lower()
    if not v:
        return default
    return v not in ("0", "false", "no", "off")


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

    # PDF archive: every run drops a dated copy next to the script.
    SAVE_PDF = _bool("SAVE_PDF", True)
    PDF_DIR = _get("PDF_DIR")                    # blank => the script's folder
    ATTACH_PDF = _bool("ATTACH_PDF", False)      # also attach it to the email

    # Weekly CV-vs-news skills gap (./skills.py, or brief.py --weekly)
    CV_PATH = _get("CV_PATH")                    # blank => Vinay_Balraj_AI_Developer_CV.pdf
    SKILLS_WINDOW_DAYS = _int("SKILLS_WINDOW_DAYS", 7)
    MAX_SKILL_GAPS = _int("MAX_SKILL_GAPS", 8)
    HISTORY_KEEP_DAYS = _int("HISTORY_KEEP_DAYS", 60)


CONFIG = Config()
