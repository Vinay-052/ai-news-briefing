#!/usr/bin/env python3
"""Configure the AI News Briefing without hand-editing .env.

Stdlib only — runs with any python3, venv or not.

    ./configure.py                      # interactive: walk every setting
    ./configure.py --show               # print current config (secrets masked)
    ./configure.py --email              # just the email section
    ./configure.py --llm                # just the LLM section
    ./configure.py --briefing           # just the briefing options
    ./configure.py --set MAIL_TO=a@b.c --set LLM_MODEL=claude-opus-5
    ./configure.py --test-llm           # verify the model endpoint answers
    ./configure.py --test-email         # send a small test message
    ./configure.py --schedule 10:00     # change the daily cron time
    ./configure.py --schedule off       # remove the cron entry

Writes .env in place (0600), preserving comments and key order, and keeps a
one-generation backup at .env.bak.
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENV = HERE / ".env"
ENV_BAK = HERE / ".env.bak"
EXAMPLE = HERE / ".env.example"
RUN_SH = HERE / "run.sh"

SECRET_KEYS = {"LLM_API_KEY", "SMTP_PASS"}

# key -> (prompt, section, help)
FIELDS = {
    # --- email ---
    "MAIL_TO": ("Send briefing TO", "email", "Recipient address (comma-separate for several)"),
    "MAIL_FROM": ("Send FROM", "email", "Usually the same as SMTP_USER"),
    "SMTP_HOST": ("SMTP host", "email", "e.g. smtp.gmail.com"),
    "SMTP_PORT": ("SMTP port", "email", "465 for ssl, 587 for starttls"),
    "SMTP_SECURITY": ("SMTP security", "email", "ssl | starttls | plain"),
    "SMTP_USER": ("SMTP username", "email", "Usually your full email address"),
    "SMTP_PASS": ("SMTP password", "email", "Gmail: a 16-char App Password, not your login password"),
    # --- llm ---
    "LLM_BASE_URL": ("LLM base URL", "llm", "OpenAI-compatible base, ending in /v1"),
    "LLM_API_KEY": ("LLM API key", "llm", "Sent as: Authorization: Bearer <key>"),
    "LLM_MODEL": ("LLM model", "llm", "e.g. claude-opus-4-7, gpt-4o, llama3.1"),
    # --- briefing ---
    "SOURCES": ("Sources", "briefing", "Comma-separated URLs; blank = bundled 25-source preset"),
    "KEYWORDS": ("Keyword filter", "briefing", "Comma-separated; blank = keep everything"),
    "WINDOW_HOURS": ("Time window (hours)", "briefing", "How far back to look, e.g. 24"),
    "PER_FEED_LIMIT": ("Per-feed limit", "briefing", "Max articles taken from each source"),
    "DETAIL_LIMIT": ("Full detail cards", "briefing", "Rest render as a compact list"),
    "CONCURRENCY": ("Concurrency", "briefing", "Parallel article summaries; lower if rate-limited"),
    "EXTRACT_TIMEOUT": ("LLM timeout (s)", "briefing", "Per-article LLM call timeout"),
    "MAX_CONTENT_CHARS": ("Max content chars", "briefing", "Article text sent to the model"),
    "LLM_MAX_RETRIES": ("LLM max retries", "briefing", "Retries on 429/5xx"),
    "LLM_BACKOFF_BASE": ("LLM backoff base (s)", "briefing", "Exponential backoff seed"),
}

SECTION_TITLES = {
    "email": "Email delivery",
    "llm": "Model endpoint",
    "briefing": "Briefing behaviour",
}

# Falls back to these (defined in config.py) when a key is absent from .env.
CODE_DEFAULTS = {
    "SMTP_PORT": "465", "SMTP_SECURITY": "ssl",
    "WINDOW_HOURS": "24", "PER_FEED_LIMIT": "10", "DETAIL_LIMIT": "20",
    "CONCURRENCY": "3", "EXTRACT_TIMEOUT": "90", "MAX_CONTENT_CHARS": "12000",
    "LLM_MAX_RETRIES": "4", "LLM_BACKOFF_BASE": "2",
}


# ------------------------------------------------------------------ env io
def read_env() -> dict:
    data = {}
    if ENV.exists():
        for line in ENV.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if not s or s.startswith("#") or "=" not in s:
                continue
            k, v = s.split("=", 1)
            data[k.strip()] = v.strip().strip('"').strip("'")
    return data


def write_env(updates: dict):
    """Upsert keys, preserving existing comments, order and untouched values."""
    if not updates:
        return
    lines = []
    if ENV.exists():
        ENV_BAK.write_text(ENV.read_text(encoding="utf-8"), encoding="utf-8")
        os.chmod(ENV_BAK, 0o600)
        lines = ENV.read_text(encoding="utf-8").splitlines()
    elif EXAMPLE.exists():
        lines = EXAMPLE.read_text(encoding="utf-8").splitlines()

    seen = set()
    out = []
    for line in lines:
        m = re.match(r"^(\s*)([A-Z0-9_]+)(\s*)=(.*)$", line)
        if m and m.group(2) in updates:
            key = m.group(2)
            comment = ""
            cm = re.search(r"\s+#\s.*$", m.group(4))
            if cm:
                comment = cm.group(0)
            out.append(f"{key}={updates[key]}{comment}")
            seen.add(key)
        else:
            out.append(line)
    for k, v in updates.items():
        if k not in seen:
            out.append(f"{k}={v}")

    ENV.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
    os.chmod(ENV, 0o600)


# ------------------------------------------------------------------ validation
def validate(key: str, value: str) -> str | None:
    """Return an error string, or None when the value is acceptable."""
    v = (value or "").strip()
    if key in ("MAIL_TO", "MAIL_FROM", "SMTP_USER") and v:
        for part in [p.strip() for p in v.split(",") if p.strip()]:
            if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", part):
                return f"not a valid email address: {part}"
    if key == "SMTP_SECURITY" and v and v.lower() not in ("ssl", "starttls", "plain"):
        return "must be one of: ssl, starttls, plain"
    if key == "LLM_BASE_URL" and v and not v.startswith(("http://", "https://")):
        return "must start with http:// or https://"
    if key in ("SMTP_PORT", "WINDOW_HOURS", "PER_FEED_LIMIT", "DETAIL_LIMIT",
               "CONCURRENCY", "EXTRACT_TIMEOUT", "MAX_CONTENT_CHARS", "LLM_MAX_RETRIES"):
        if v and not v.isdigit():
            return "must be a whole number"
    if key == "LLM_BACKOFF_BASE" and v:
        try:
            float(v)
        except ValueError:
            return "must be a number"
    return None


def mask(key: str, value: str) -> str:
    if not value:
        return "(empty)"
    if key in SECRET_KEYS:
        return value[:4] + "…" + value[-4:] if len(value) > 10 else "(set)"
    return value


# ------------------------------------------------------------------ display
def show():
    env = read_env()
    if not ENV.exists():
        print(f"No .env yet at {ENV}. Run ./configure.py to create one.")
        return
    print(f"Config: {ENV}\n")
    for sect in ("email", "llm", "briefing"):
        print(f"  {SECTION_TITLES[sect]}")
        for key, (label, s, _) in FIELDS.items():
            if s != sect:
                continue
            val = env.get(key, "")
            if val:
                shown = mask(key, val)
            elif key == "SOURCES":
                shown = "(bundled 25-source preset)"
            elif key in CODE_DEFAULTS:
                shown = f"{CODE_DEFAULTS[key]}  (default)"
            elif key == "KEYWORDS":
                shown = "(no filter)"
            else:
                shown = "(empty)"
            print(f"    {key:<18} {shown}")
        print()
    print("  Schedule")
    print(f"    cron              {current_cron() or '(not scheduled)'}")


# ------------------------------------------------------------------ interactive
def prompt_section(sect: str, env: dict) -> dict:
    updates = {}
    print(f"\n── {SECTION_TITLES[sect]} " + "─" * (44 - len(SECTION_TITLES[sect])))
    print("   (press Enter to keep the current value)\n")
    for key, (label, s, help_text) in FIELDS.items():
        if s != sect:
            continue
        cur = env.get(key, "")
        if cur:
            shown = mask(key, cur)
        elif key in CODE_DEFAULTS:
            shown = f"{CODE_DEFAULTS[key]} (default)"
        elif key == "SOURCES":
            shown = "bundled preset"
        else:
            shown = "(empty)"
        print(f"  {label}  —  {help_text}")
        while True:
            if key in SECRET_KEYS:
                raw = getpass.getpass(f"    [{shown}] (hidden): ")
            else:
                raw = input(f"    [{shown}]: ")
            if raw.strip() == "":
                break
            err = validate(key, raw)
            if err:
                print(f"    !! {err}")
                continue
            updates[key] = raw.strip()
            break
        print()
    return updates


def interactive(sections):
    env = read_env()
    if not ENV.exists():
        print("No .env found — creating one from .env.example.\n")
    updates = {}
    for sect in sections:
        updates.update(prompt_section(sect, env))
    if not updates:
        print("No changes made.")
        return
    print("About to write:")
    for k, v in updates.items():
        print(f"  {k} = {mask(k, v)}")
    if input("\nApply these changes? [y/N]: ").strip().lower() not in ("y", "yes"):
        print("Aborted; nothing written.")
        return
    write_env(updates)
    print(f"\nWrote {ENV} (backup at {ENV_BAK.name})")
    print("Verify with:  ./configure.py --test-llm   and   ./configure.py --test-email")


# ------------------------------------------------------------------ tests
def test_llm() -> int:
    env = read_env()
    base = env.get("LLM_BASE_URL", "").rstrip("/")
    key = env.get("LLM_API_KEY", "")
    model = env.get("LLM_MODEL", "")
    if not (base and key and model):
        print("!! LLM_BASE_URL / LLM_API_KEY / LLM_MODEL must all be set.")
        return 2
    url = base + "/chat/completions"
    body = json.dumps({"model": model, "max_tokens": 8,
                       "messages": [{"role": "user", "content": "Reply with just: OK"}]}).encode()
    req = urllib.request.Request(url, data=body, headers={
        "Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    print(f"POST {url}\n  model: {model}")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read().decode())
        reply = (data["choices"][0]["message"]["content"] or "").strip()
        print(f"  OK — model replied: {reply[:60]!r}")
        return 0
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:300]
        print(f"  !! HTTP {e.code}: {detail}")
        if e.code == 401:
            print("     → check LLM_API_KEY")
        elif e.code == 404:
            print("     → check LLM_BASE_URL (should end in /v1) and LLM_MODEL")
        elif e.code == 429:
            print("     → rate limited; the briefing retries automatically")
        return 1
    except Exception as e:
        print(f"  !! {type(e).__name__}: {e}")
        return 1


def test_email() -> int:
    import smtplib
    import ssl
    from email.message import EmailMessage

    env = read_env()
    host = env.get("SMTP_HOST", "")
    port = int(env.get("SMTP_PORT", "465") or 465)
    user = env.get("SMTP_USER", "")
    pw = env.get("SMTP_PASS", "")
    sec = (env.get("SMTP_SECURITY", "ssl") or "ssl").lower()
    to = env.get("MAIL_TO", "") or user
    frm = env.get("MAIL_FROM", "") or user
    if not (host and to):
        print("!! SMTP_HOST and MAIL_TO must be set.")
        return 2
    msg = EmailMessage()
    msg["From"] = frm
    msg["To"] = to
    msg["Subject"] = "AI News Briefing — configuration test"
    msg.set_content("If you can read this, email delivery is configured correctly.")
    print(f"Sending test message to {to} via {host}:{port} ({sec})…")
    try:
        ctx = ssl.create_default_context()
        if sec == "ssl":
            with smtplib.SMTP_SSL(host, port, context=ctx, timeout=30) as s:
                if user:
                    s.login(user, pw)
                s.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=30) as s:
                if sec == "starttls":
                    s.starttls(context=ctx)
                if user:
                    s.login(user, pw)
                s.send_message(msg)
        print("  OK — sent. Check the inbox.")
        return 0
    except smtplib.SMTPAuthenticationError as e:
        print(f"  !! auth rejected: {e}")
        print("     → Gmail needs a 16-char App Password (not your account password)")
        return 1
    except Exception as e:
        print(f"  !! {type(e).__name__}: {e}")
        return 1


# ------------------------------------------------------------------ cron
def current_cron() -> str:
    try:
        out = subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout
    except FileNotFoundError:
        return ""
    for line in out.splitlines():
        if "ai-news-briefing/run.sh" in line and not line.strip().startswith("#"):
            return line.strip()
    return ""


def set_schedule(spec: str) -> int:
    try:
        existing = subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout
    except FileNotFoundError:
        print("!! crontab not available on this system.")
        return 1
    kept = [ln for ln in existing.splitlines()
            if "ai-news-briefing/run.sh" not in ln and "AI News Briefing" not in ln]

    if spec.lower() in ("off", "none", "disable"):
        new = "\n".join(kept).strip()
        subprocess.run(["crontab", "-"], input=(new + "\n") if new else "", text=True, check=True)
        print("Removed the scheduled run. (Run it manually with ./run.sh)")
        return 0

    m = re.fullmatch(r"(\d{1,2}):(\d{2})", spec.strip())
    if not m:
        print("!! Use HH:MM (24-hour), e.g. --schedule 10:00 — or 'off'.")
        return 2
    hh, mm = int(m.group(1)), int(m.group(2))
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        print("!! Hour must be 0-23 and minute 0-59.")
        return 2
    kept += ["# AI News Briefing — daily, local time",
             f"{mm} {hh} * * * {RUN_SH}"]
    subprocess.run(["crontab", "-"], input="\n".join(kept).strip() + "\n", text=True, check=True)
    tz = ""
    try:
        tz = subprocess.run(["date", "+%Z"], capture_output=True, text=True).stdout.strip()
    except Exception:
        pass
    print(f"Scheduled daily at {hh:02d}:{mm:02d} {tz} (cron uses local time).")
    return 0


# ------------------------------------------------------------------ main
def main() -> int:
    p = argparse.ArgumentParser(
        description="Configure the AI News Briefing (.env + schedule).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Run with no arguments to walk through every setting interactively.")
    p.add_argument("--show", action="store_true", help="print current config, secrets masked")
    p.add_argument("--email", action="store_true", help="configure email delivery only")
    p.add_argument("--llm", action="store_true", help="configure the model endpoint only")
    p.add_argument("--briefing", action="store_true", help="configure briefing options only")
    p.add_argument("--set", action="append", metavar="KEY=VALUE", default=[],
                   help="set a value non-interactively (repeatable)")
    p.add_argument("--test-llm", action="store_true", help="check the model endpoint answers")
    p.add_argument("--test-email", action="store_true", help="send a small test message")
    p.add_argument("--schedule", metavar="HH:MM|off", help="set or remove the daily cron run")
    a = p.parse_args()

    if a.show:
        show()
        return 0
    if a.schedule:
        return set_schedule(a.schedule)
    if a.test_llm and not a.set:
        return test_llm()
    if a.test_email and not a.set:
        return test_email()

    if a.set:
        updates = {}
        for item in a.set:
            if "=" not in item:
                print(f"!! --set needs KEY=VALUE, got: {item}")
                return 2
            k, v = item.split("=", 1)
            k, v = k.strip().upper(), v.strip()
            if k not in FIELDS:
                print(f"!! unknown setting: {k}")
                print("   known:", ", ".join(sorted(FIELDS)))
                return 2
            err = validate(k, v)
            if err:
                print(f"!! {k}: {err}")
                return 2
            updates[k] = v
        write_env(updates)
        for k, v in updates.items():
            print(f"set {k} = {mask(k, v)}")
        print(f"Wrote {ENV} (backup at {ENV_BAK.name})")
        rc = 0
        if a.test_llm:
            rc |= test_llm()
        if a.test_email:
            rc |= test_email()
        return rc

    sections = [s for s, on in (("email", a.email), ("llm", a.llm), ("briefing", a.briefing)) if on]
    if not sections:
        sections = ["email", "llm", "briefing"]
    try:
        interactive(sections)
    except (KeyboardInterrupt, EOFError):
        print("\nAborted; nothing written.")
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
