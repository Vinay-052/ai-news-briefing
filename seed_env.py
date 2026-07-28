#!/usr/bin/env python3
"""One-time: copy LLM + SMTP creds from the Odysseus app.db into ./.env.

Run once with the Odysseus venv, then you can delete this file:
    /home/vinay/projects/odysseus/venv/bin/python /home/vinay/ai-news-briefing/seed_env.py

It reads the already-configured (encrypted) model endpoint + email account from
Odysseus and writes them to a local .env (chmod 600). Secrets are only printed
masked.
"""
import os
import sys

ODY = "/home/vinay/projects/odysseus"
sys.path.insert(0, ODY)
os.chdir(ODY)

OWNER = "vinay"
ENV_PATH = "/home/vinay/ai-news-briefing/.env"


def main():
    from src.endpoint_resolver import resolve_endpoint

    url, model, headers = resolve_endpoint("research", owner=OWNER)
    if not url:
        url, model, headers = resolve_endpoint("utility", owner=OWNER)
    if not url:
        url, model, headers = resolve_endpoint("default", owner=OWNER)

    base = url or ""
    if base.endswith("/chat/completions"):
        base = base[: -len("/chat/completions")]
    auth = (headers or {}).get("Authorization", "") or ""
    api_key = auth.replace("Bearer ", "").strip() or (headers or {}).get("x-api-key", "")

    from routes.email_routes import _resolve_send_config
    cfg = _resolve_send_config(account_id=None, owner=OWNER) or {}
    smtp_host = cfg.get("smtp_host", "")
    smtp_port = cfg.get("smtp_port", 465)
    smtp_user = cfg.get("smtp_user", "") or cfg.get("from_address", "")
    smtp_pass = cfg.get("smtp_password", "") or cfg.get("password", "")
    from_addr = cfg.get("from_address", "") or smtp_user
    security = (cfg.get("smtp_security") or ("ssl" if str(smtp_port) == "465" else "starttls"))

    env = f"""# Seeded from Odysseus app.db. Edit as needed; keep this file chmod 600.
LLM_BASE_URL={base}
LLM_API_KEY={api_key}
LLM_MODEL={model}

SMTP_HOST={smtp_host}
SMTP_PORT={smtp_port}
SMTP_SECURITY={security}
SMTP_USER={smtp_user}
SMTP_PASS={smtp_pass}
MAIL_FROM={from_addr}
MAIL_TO={from_addr}

SOURCES=
KEYWORDS=
WINDOW_HOURS=24
PER_FEED_LIMIT=10
DETAIL_LIMIT=20
CONCURRENCY=3
EXTRACT_TIMEOUT=90
MAX_CONTENT_CHARS=12000
"""
    with open(ENV_PATH, "w") as f:
        f.write(env)
    os.chmod(ENV_PATH, 0o600)

    def mask(s):
        return (s[:6] + "…" + s[-4:]) if s and len(s) > 12 else ("<set>" if s else "<EMPTY>")

    print("wrote", ENV_PATH, "(chmod 600)")
    print("  LLM_BASE_URL:", base or "<EMPTY>")
    print("  LLM_MODEL   :", model or "<EMPTY>")
    print("  LLM_API_KEY :", mask(api_key))
    print("  SMTP        :", f"{smtp_host}:{smtp_port} {security} user={smtp_user or '<EMPTY>'} pass={mask(smtp_pass)}")
    print("  MAIL_TO     :", from_addr or "<EMPTY>")
    missing = [k for k, v in {"LLM_BASE_URL": base, "LLM_API_KEY": api_key, "LLM_MODEL": model,
                              "SMTP_HOST": smtp_host, "SMTP_PASS": smtp_pass}.items() if not v]
    if missing:
        print("  WARNING: empty ->", ", ".join(missing), "(fill these in .env manually)")


if __name__ == "__main__":
    main()
