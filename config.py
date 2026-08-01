"""Config for the AI News Briefing script.

Reads a local `.env` (KEY=VALUE lines) sitting next to this file; real
environment variables override it. No external dependency (no python-dotenv).
"""
import os
import re
from pathlib import Path
from urllib.parse import urlparse

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


def _path(key, default=""):
    """A filesystem setting, with ~ expanded (relative paths stay relative)."""
    v = _get(key, default)
    return os.path.expanduser(v) if v else v


def _bool(key, default):
    v = _get(key, "").strip().lower()
    if not v:
        return default
    return v not in ("0", "false", "no", "off")


class Config:
    # LLM. Two providers:
    #   ollama  — a local Ollama server, native /api/chat (default)
    #   openai  — any OpenAI-compatible /chat/completions gateway
    # "auto" picks ollama when the base URL looks like an Ollama host.
    LLM_PROVIDER = (_get("LLM_PROVIDER", "auto") or "auto").lower()
    LLM_BASE_URL = _get("LLM_BASE_URL", "http://localhost:11434")
    LLM_API_KEY = _get("LLM_API_KEY")       # not needed for local ollama
    LLM_MODEL = _get("LLM_MODEL", "gemma4:26b")

    # Ollama-only knobs. num_ctx must cover MAX_CONTENT_CHARS (~4 chars/token)
    # plus the prompt, or Ollama silently truncates the article. Thinking is off
    # by default: it burns the num_predict budget without improving the JSON.
    LLM_NUM_CTX = _int("LLM_NUM_CTX", 8192)
    # Ceiling for the automatic growth in brief._fit_num_ctx. Raise it only if
    # the machine has the RAM for the extra KV cache.
    LLM_MAX_NUM_CTX = _int("LLM_MAX_NUM_CTX", 32768)
    LLM_THINK = _bool("LLM_THINK", False)
    LLM_KEEP_ALIVE = _get("LLM_KEEP_ALIVE", "30m")   # keep weights resident between calls
    # Cron may fire before the ollama service is accepting requests (e.g. just
    # after a reboot). Wait this long for it rather than failing every article.
    LLM_STARTUP_WAIT = _int("LLM_STARTUP_WAIT", 120)

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
    # 0 => provider default (see below). Local generation is far slower than a
    # hosted gateway, and one GPU serves one request at a time.
    LLM_TIMEOUT = _int("LLM_TIMEOUT", 0)
    LLM_CONCURRENCY = _int("LLM_CONCURRENCY", 0)

    # PDF archive: every run drops a dated copy next to the script.
    SAVE_PDF = _bool("SAVE_PDF", True)
    PDF_DIR = _path("PDF_DIR")                   # blank => the script's folder
    ATTACH_PDF = _bool("ATTACH_PDF", False)      # also attach it to the email

    # Weekly CV-vs-news skills gap (./skills.py, or brief.py --weekly)
    CV_PATH = _path("CV_PATH")                   # blank => cv.pdf next to the script
    SKILLS_WINDOW_DAYS = _int("SKILLS_WINDOW_DAYS", 7)
    MAX_SKILL_GAPS = _int("MAX_SKILL_GAPS", 8)
    HISTORY_KEEP_DAYS = _int("HISTORY_KEEP_DAYS", 60)


def _resolve_provider(cfg) -> str:
    if cfg.LLM_PROVIDER in ("ollama", "openai"):
        return cfg.LLM_PROVIDER
    url = (cfg.LLM_BASE_URL or "").lower()
    return "ollama" if ("11434" in url or "ollama" in url) else "openai"


def _is_ollama_cloud(cfg) -> bool:
    """Ollama Cloud (https://ollama.com) rather than a server you run.

    It speaks the same native API, but it is multi-tenant: it will serve
    parallel requests, it has no weights to keep resident, and its model list
    is not something you `ollama pull`. Those three differences drive the
    defaults below and the request built in brief._ollama_request.
    """
    host = urlparse(cfg.LLM_BASE_URL or "").hostname or ""
    return host.lower().endswith("ollama.com")


CONFIG = Config()

# Resolved once, so callers never re-derive it.
CONFIG.PROVIDER = _resolve_provider(CONFIG)
CONFIG.OLLAMA_CLOUD = CONFIG.PROVIDER == "ollama" and _is_ollama_cloud(CONFIG)
if not CONFIG.LLM_TIMEOUT:
    if CONFIG.OLLAMA_CLOUD:
        # Hosted and fast, but the weekly analysis still asks for 8000 tokens —
        # minutes, not the 90s an article summary needs.
        CONFIG.LLM_TIMEOUT = 300
    elif CONFIG.PROVIDER == "ollama":
        CONFIG.LLM_TIMEOUT = 900
    else:
        CONFIG.LLM_TIMEOUT = CONFIG.EXTRACT_TIMEOUT
if not CONFIG.LLM_CONCURRENCY:
    # One local GPU serves one request at a time; a hosted service does not.
    CONFIG.LLM_CONCURRENCY = 1 if (CONFIG.PROVIDER == "ollama" and not CONFIG.OLLAMA_CLOUD) \
        else CONFIG.CONCURRENCY
