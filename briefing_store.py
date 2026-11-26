"""Durable briefing events and a worker shared by the dashboard and cron."""
from __future__ import annotations

import fcntl
import json
import logging
import os
import re
import sqlite3
import tempfile
import time
from contextlib import closing, contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from config import DEFAULTS, STATE_DIR, make_config, using_config

log = logging.getLogger(__name__)
SECRETS = {"LLM_API_KEY", "SMTP_PASS"}
PRESETS = {
    "ai": {"name": "AI News Briefing", "topic": "ai", "sources": "", "time": "08:00"},
    "politics": {
        "name": "Politics Briefing", "topic": "politics and public policy", "time": "12:00",
        "sources": "https://feeds.bbci.co.uk/news/politics/rss.xml\nhttps://feeds.bbci.co.uk/news/world/rss.xml",
    },
    "trends": {
        "name": "Trends Briefing", "topic": "technology, business and cultural trends", "time": "17:00",
        "sources": "https://feeds.bbci.co.uk/news/technology/rss.xml\nhttps://feeds.bbci.co.uk/news/business/rss.xml",
    },
}
DAYS = list(range(7))


def validate_url(value, label):
    try:
        url = urlsplit(value)
        if (url.scheme in ("http", "https") and url.hostname and not url.username
                and not url.password and not url.fragment and not any(c.isspace() for c in value)):
            _ = url.port
            return
    except ValueError:
        pass
    raise ValueError(f"{label} must be an HTTP or HTTPS URL without credentials.")


def number(value, label, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{label} must be between {low} and {high}.")
    return value


def validate_event(data):
    event = {}
    for key, limit in {"name": 80, "topic": 180, "sources": 12000, "keywords": 1000}.items():
        value = data.get(key, "")
        if not isinstance(value, str) or len(value) > limit or "\x00" in value:
            raise ValueError(f"Invalid {key}.")
        event[key] = value.strip()
    if not event["name"] or not event["topic"] or "\n" in event["name"] or "\r" in event["name"]:
        raise ValueError("Enter a name and topic.")
    event["topic"] = "ai" if event["topic"].lower() == "ai" else event["topic"]
    sources = [item.strip() for item in re.split(r"[,\n]", event["sources"]) if item.strip()]
    if len(sources) > 50 or (not sources and event["topic"] != "ai"):
        raise ValueError("Provide up to 50 sources. The AI topic can use the bundled feeds.")
    for source in sources:
        validate_url(source, "Each source")
    event["window"] = number(data.get("window"), "Lookback hours", 0, 720)
    event["time"] = data.get("time")
    if not isinstance(event["time"], str) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", event["time"]):
        raise ValueError("Enter a valid schedule time.")
    event["timezone"] = data.get("timezone")
    try:
        ZoneInfo(event["timezone"])
    except (ValueError, TypeError, ZoneInfoNotFoundError):
        raise ValueError("Use an IANA time zone such as Asia/Kolkata.")
    days = data.get("days")
    if not isinstance(days, list) or not days or any(type(day) is not int or day not in DAYS for day in days):
        raise ValueError("Choose at least one day.")
    event["days"] = sorted(set(days))
    for key in ("enabled", "email", "weekly"):
        if type(data.get(key)) is not bool:
            raise ValueError(f"Invalid {key} value.")
        event[key] = data[key]
    if event["weekly"] and event["topic"] != "ai":
        raise ValueError("The weekly skills gap is available for the AI topic.")
    # None means "use the default provider from Settings".
    provider = data.get("provider")
    if provider is not None and (type(provider) is not int or provider < 1):
        raise ValueError("Choose a valid AI provider.")
    event["provider"] = provider
    return event


PROVIDER_TYPES = ("ollama", "chatgpt", "anthropic", "opencode", "openai")


def validate_provider(data):
    profile = {}
    for key, limit in {"name": 60, "LLM_PROVIDER": 20, "LLM_BASE_URL": 2048, "LLM_MODEL": 200}.items():
        value = data.get(key, "")
        if not isinstance(value, str) or len(value) > limit or any(c in value for c in "\x00\r\n"):
            raise ValueError(f"Invalid {key}.")
        profile[key] = value.strip()
    if not profile["name"] or not profile["LLM_MODEL"]:
        raise ValueError("Enter a name and model ID.")
    if profile["LLM_PROVIDER"] not in PROVIDER_TYPES:
        raise ValueError("Choose a valid AI provider.")
    validate_url(profile["LLM_BASE_URL"], "Provider endpoint")
    require = data.get("REQUIRE_API_KEY", True)
    if type(require) is not bool:
        raise ValueError("Invalid REQUIRE_API_KEY value.")
    profile["REQUIRE_API_KEY"] = require
    key = data.get("LLM_API_KEY", "")
    if key is not None and (not isinstance(key, str) or len(key) > 4096 or any(c in key for c in "\r\n")):
        raise ValueError("Invalid API key.")
    return profile, key


def next_run(event, changed, now=None):
    """The next scheduled time (epoch seconds) for an enabled event, or None."""
    if not event.get("enabled"):
        return None
    now = now or datetime.now(timezone.utc)
    zone = ZoneInfo(event["timezone"])
    local = now.astimezone(zone)
    hour, minute = map(int, event["time"].split(":"))
    for offset in range(8):
        day = local + timedelta(days=offset)
        if day.weekday() not in event["days"]:
            continue
        due = day.replace(hour=hour, minute=minute, second=0, microsecond=0, fold=0).timestamp()
        if due > now.timestamp() and due >= changed:
            return due
    return None


def local_zone():
    name = os.environ.get("TZ", "")
    localtime = Path("/etc/localtime").resolve().as_posix()
    if not name and "/zoneinfo/" in localtime:
        name = localtime.split("/zoneinfo/")[-1]
    try:
        return ZoneInfo(name).key
    except (ValueError, ZoneInfoNotFoundError):
        return "UTC"


class Store:
    def __init__(self, directory=None):
        self.directory = Path(directory or STATE_DIR)
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.path = self.directory / "briefings.sqlite3"
        # Create with restrictive permissions before SQLite opens its journals.
        os.close(os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600))
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, data TEXT NOT NULL, changed REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS runs (
                    id INTEGER PRIMARY KEY, event_id INTEGER NOT NULL, event TEXT NOT NULL,
                    slot TEXT, created REAL NOT NULL, finished REAL, status TEXT NOT NULL,
                    email INTEGER NOT NULL, weekly INTEGER NOT NULL, delivered INTEGER NOT NULL DEFAULT 0,
                    html TEXT, article_count INTEGER, issues INTEGER, error TEXT,
                    UNIQUE(event_id, slot)
                );
                CREATE TABLE IF NOT EXISTS providers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, data TEXT NOT NULL
                );
            """)
            # Archives created before the in-app reader have no structured articles.
            if "news" not in {col["name"] for col in db.execute("PRAGMA table_info(runs)")}:
                db.execute("ALTER TABLE runs ADD COLUMN news TEXT")
            initial = dict(PRESETS["ai"], sources=DEFAULTS["SOURCES_RAW"], days=DAYS,
                           timezone=local_zone(), enabled=False, email=bool(DEFAULTS["SMTP_HOST"]),
                           weekly=True, keywords=", ".join(DEFAULTS["KEYWORDS"]),
                           window=DEFAULTS["WINDOW_HOURS"])
            # SQLite's sequence retains the original ID if the user deletes the event.
            db.execute("""INSERT OR IGNORE INTO events(id, data, changed)
                          SELECT 1, ?, ? WHERE NOT EXISTS
                          (SELECT 1 FROM sqlite_sequence WHERE name = 'events')""",
                       (json.dumps(initial), time.time()))

    @contextmanager
    def connect(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.row_factory = sqlite3.Row
            yield db

    @staticmethod
    def _event(row):
        # Events saved before provider profiles existed use the default provider.
        return dict({"provider": None}, **json.loads(row["data"]), id=row["id"])

    def events(self):
        with self.connect() as db:
            return [dict(self._event(row), next_run=next_run(self._event(row), row["changed"]))
                    for row in db.execute("SELECT * FROM events ORDER BY id")]

    def event(self, event_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
            if row is None:
                raise KeyError("Event not found.")
            return self._event(row)

    def save_event(self, data, event_id=None):
        event = validate_event(data)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if event["provider"] is not None and db.execute(
                    "SELECT 1 FROM providers WHERE id = ?", (event["provider"],)).fetchone() is None:
                raise ValueError("That AI provider no longer exists.")
            if event_id is None:
                event_id = db.execute("INSERT INTO events(data, changed) VALUES (?, ?)",
                                      (json.dumps(event), time.time())).lastrowid
            else:
                row = db.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
                if row is None:
                    raise KeyError("Event not found.")
                old = self._event(row)
                schedule_keys = ("enabled", "time", "days", "timezone")
                changed = time.time() if any(old[key] != event[key] for key in schedule_keys) else row["changed"]
                db.execute("UPDATE events SET data = ?, changed = ? WHERE id = ?",
                           (json.dumps(event), changed, event_id))
        return dict(event, id=event_id)

    def delete_event(self, event_id):
        with self.connect() as db:
            if not db.execute("DELETE FROM events WHERE id = ?", (event_id,)).rowcount:
                raise KeyError("Event not found.")
            db.execute("UPDATE runs SET status='cancelled', finished=? WHERE event_id=? AND status='queued'",
                       (time.time(), event_id))

    # ---- AI provider profiles -------------------------------------------
    def providers(self, *, secrets=False):
        with self.connect() as db:
            rows = db.execute("SELECT * FROM providers ORDER BY id").fetchall()
        result = []
        for row in rows:
            profile = dict(json.loads(row["data"]), id=row["id"])
            if not secrets:
                profile["LLM_API_KEY"] = bool(profile.get("LLM_API_KEY"))
            result.append(profile)
        return result

    def provider(self, provider_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM providers WHERE id = ?", (provider_id,)).fetchone()
        if row is None:
            raise KeyError("Provider not found.")
        return json.loads(row["data"])

    def save_provider(self, data, provider_id=None):
        profile, key = validate_provider(data)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = {}
            if provider_id is not None:
                row = db.execute("SELECT * FROM providers WHERE id = ?", (provider_id,)).fetchone()
                if row is None:
                    raise KeyError("Provider not found.")
                old = json.loads(row["data"])
            # Blank keeps the stored key, None clears it. A key never follows the
            # profile to a different endpoint, so it cannot leak to a new host.
            moved = any(old.get(name) != profile[name] for name in ("LLM_PROVIDER", "LLM_BASE_URL"))
            if key is None or (key == "" and moved):
                profile["LLM_API_KEY"] = ""
            else:
                profile["LLM_API_KEY"] = key or old.get("LLM_API_KEY", "")
            if provider_id is None:
                provider_id = db.execute("INSERT INTO providers(data) VALUES (?)",
                                         (json.dumps(profile),)).lastrowid
            else:
                db.execute("UPDATE providers SET data = ? WHERE id = ?", (json.dumps(profile), provider_id))
        return dict(profile, id=provider_id, LLM_API_KEY=bool(profile["LLM_API_KEY"]))

    def delete_provider(self, provider_id):
        users = [event["name"] for event in self.events() if event.get("provider") == provider_id]
        if users:
            raise ValueError("Used by " + ", ".join(users) + ". Switch those events to another provider first.")
        with self.connect() as db:
            if not db.execute("DELETE FROM providers WHERE id = ?", (provider_id,)).rowcount:
                raise KeyError("Provider not found.")

    def config_for(self, provider_id=None, overrides=None):
        """Settings, with a provider profile's model and endpoint swapped in."""
        values = dict(overrides or {})
        if provider_id is not None:
            try:
                profile = self.provider(provider_id)
            except KeyError:
                log.warning("Provider %s was removed; using the default provider.", provider_id)
            else:
                values.update({key: profile[key] for key in
                               ("LLM_PROVIDER", "LLM_BASE_URL", "LLM_MODEL", "LLM_API_KEY", "REQUIRE_API_KEY")})
        return make_config(self.settings(), values)

    def test_provider(self, provider_id=None):
        import brief

        # Keep the button responsive: no long Ollama startup wait or retries.
        cfg = self.config_for(provider_id, {"LLM_STARTUP_WAIT": 5, "LLM_MAX_RETRIES": 0})
        try:
            with using_config(cfg):
                reply = brief.test_connection()
        except Exception as exc:
            message = str(exc) or type(exc).__name__
            if cfg.LLM_API_KEY:
                message = message.replace(cfg.LLM_API_KEY, "[redacted]")
            return {"ok": False, "message": message[:400]}
        return {"ok": True, "message": f"{cfg.LLM_MODEL} replied: {reply[:80] or '(empty reply)'}"}

    def readiness(self):
        """What the dashboard should prompt the user to set up first."""
        import brief

        cfg = make_config(self.settings())
        with using_config(cfg):
            try:
                brief.check_configuration()
                model = ""
            except ValueError as exc:
                model = str(exc)
        return {"model": model, "email": bool(cfg.SMTP_HOST and cfg.MAIL_FROM and cfg.MAIL_TO)}

    def email_run(self, run_id):
        import brief

        with self.connect() as db:
            row = db.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if row is None or row["html"] is None:
            raise KeyError("Briefing not available.")
        cfg = make_config(self.settings())
        if not (cfg.SMTP_HOST and cfg.MAIL_FROM and cfg.MAIL_TO):
            raise ValueError("Set the SMTP host, sender, and recipients in Settings.")
        event = json.loads(row["event"])
        stamp = datetime.fromtimestamp(row["created"], ZoneInfo(event["timezone"]))
        try:
            with using_config(cfg):
                brief.send_email(row["html"], f"{event['name']} — {stamp:%b %d, %Y}")
        except Exception as exc:
            log.exception("Emailing briefing %s failed", run_id)
            message = f"Email failed: {exc}"
            if cfg.SMTP_PASS:
                message = message.replace(cfg.SMTP_PASS, "[redacted]")
            raise ValueError(message[:300]) from None
        with self.connect() as db:
            db.execute("UPDATE runs SET delivered = 1 WHERE id = ?", (run_id,))
        return {"sent": True, "to": cfg.MAIL_TO}

    def settings(self):
        # A supplied directory is also used by isolated tests and previews.
        path = self.directory / "settings.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    def public_settings(self):
        settings = dict(DEFAULTS, **self.settings())
        return {key: bool(value) if key in SECRETS else value for key, value in settings.items()}

    def save_settings(self, data):
        with self.connect() as db:
            # Serialize read/merge/write across dashboard processes.
            db.execute("BEGIN IMMEDIATE")
            settings = self.settings()
            previous = make_config(settings)
            for key, value in data.items():
                if key not in DEFAULTS or key in ("SOURCES_RAW", "KEYWORDS", "WINDOW_HOURS"):
                    raise ValueError(f"Unknown setting: {key}")
                if key in SECRETS and value == "":
                    continue
                if key in SECRETS and value is None:
                    value = ""
                default = DEFAULTS[key]
                if type(default) is float and type(value) is int:
                    value = float(value)
                if type(value) is not type(default):
                    raise ValueError(f"Invalid value for {key}.")
                if isinstance(value, str) and (len(value) > 4096 or "\r" in value or "\n" in value):
                    raise ValueError(f"Invalid value for {key}.")
                if type(value) in (int, float):
                    low, high = NUMERIC_LIMITS[key]
                    if not low <= value <= high:
                        raise ValueError(f"{key} must be between {low} and {high}.")
                settings[key] = value
            cfg = make_config(settings)
            for names, key in (
                (("LLM_PROVIDER", "LLM_BASE_URL"), "LLM_API_KEY"),
                (("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_SECURITY"), "SMTP_PASS"),
            ):
                if not data.get(key) and any(getattr(cfg, name) != getattr(previous, name) for name in names):
                    settings[key] = ""
            validate_url(cfg.LLM_BASE_URL, "Provider endpoint")
            if cfg.LLM_PROVIDER not in ("auto", "ollama", "openai", "chatgpt", "opencode", "anthropic"):
                raise ValueError("Choose a valid AI provider.")
            if cfg.SMTP_SECURITY not in ("ssl", "starttls", "plain"):
                raise ValueError("Choose a valid SMTP security mode.")
            if cfg.LLM_MAX_NUM_CTX < cfg.LLM_NUM_CTX:
                raise ValueError("Maximum context must be at least the default context.")
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.directory, delete=False) as f:
                scratch = Path(f.name)
                try:
                    json.dump(settings, f)
                    f.flush()
                    os.fsync(f.fileno())
                    os.replace(scratch, self.directory / "settings.json")
                finally:
                    scratch.unlink(missing_ok=True)
        return self.public_settings()

    @staticmethod
    def _enqueue(db, event, email, weekly, slot=None):
        return db.execute("""
            INSERT OR IGNORE INTO runs(event_id, event, slot, created, status, email, weekly)
            VALUES (?, ?, ?, ?, 'queued', ?, ?)
        """, (event["id"], json.dumps(event), slot, time.time(), email, weekly)).lastrowid

    def enqueue(self, event_id, *, email=None, weekly=False):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
            if row is None:
                raise KeyError("Event not found.")
            event = self._event(row)
            return self._enqueue(db, event, event["email"] if email is None else email, bool(weekly))

    def queue_due(self, now=None):
        now = now or datetime.now(timezone.utc)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            for row in db.execute("SELECT * FROM events"):
                event = self._event(row)
                if not event["enabled"]:
                    continue
                local = now.astimezone(ZoneInfo(event["timezone"]))
                hour, minute = map(int, event["time"].split(":"))
                for day in (local, local - timedelta(days=1)):
                    if day.weekday() not in event["days"]:
                        continue
                    due = day.replace(hour=hour, minute=minute, second=0, microsecond=0, fold=0)
                    age = now.timestamp() - due.timestamp()
                    if 0 <= age < 86400 and due.timestamp() >= row["changed"]:
                        self._enqueue(db, event, event["email"], event["weekly"] and day.weekday() == 6,
                                      day.date().isoformat())
                        break

    def runs(self):
        with self.connect() as db:
            return [self._run(row) for row in db.execute("""
                SELECT id, event_id, event, created, finished, status, email, delivered,
                       article_count, issues, error, html IS NOT NULL AS readable
                FROM runs ORDER BY id DESC
            """)]

    @staticmethod
    def _run(row):
        result = dict(row)
        result["name"] = json.loads(result.pop("event"))["name"]
        return result

    def articles(self, run_id):
        """One edition's structured articles for the in-app reader."""
        with self.connect() as db:
            row = db.execute("""SELECT id, event_id, event, created, status, news, html IS NOT NULL AS readable
                                FROM runs WHERE id = ?""", (run_id,)).fetchone()
        if row is None:
            raise KeyError("Briefing not found.")
        event = json.loads(row["event"])
        payload = json.loads(row["news"]) if row["news"] else {"articles": [], "errors": [], "skills": None}
        return dict(payload, id=row["id"], event_id=row["event_id"], name=event["name"], topic=event["topic"],
                    created=row["created"], status=row["status"], readable=bool(row["readable"]),
                    structured=row["news"] is not None)

    def explore(self, *, hours=0, event_id=None, limit=300):
        """Articles across every completed edition, newest edition first, de-duplicated by link."""
        since = time.time() - hours * 3600 if hours else 0
        query = "SELECT id, event_id, event, created, news FROM runs WHERE news IS NOT NULL AND created >= ?"
        params = [since]
        if event_id is not None:
            query += " AND event_id = ?"
            params.append(event_id)
        seen, result = set(), []
        with self.connect() as db:
            for row in db.execute(query + " ORDER BY id DESC", params):
                name = json.loads(row["event"])["name"]
                for article in json.loads(row["news"])["articles"]:
                    if article.get("link") in seen:
                        continue
                    seen.add(article.get("link"))
                    result.append(dict(article, run_id=row["id"], event_id=row["event_id"],
                                       edition=name, edition_created=row["created"]))
                    if len(result) >= limit:
                        return result
        return result

    def report(self, run_id):
        with self.connect() as db:
            row = db.execute("SELECT html FROM runs WHERE id = ?", (run_id,)).fetchone()
        if row is None or row["html"] is None:
            raise KeyError("Briefing not available.")
        return row["html"]

    @contextmanager
    def worker_lock(self, *, wait=False):
        with (self.directory / "worker.lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX if wait else fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                yield False
            else:
                yield True


READER_FIELDS = ("title", "source", "link", "timestamp", "category", "signal", "audiences",
                 "status_tags", "scores", "writeup", "summary", "also_seen_in", "top_signal")


def reader_payload(news, skills=None):
    """The subset of a pipeline result the dashboard reader needs."""
    articles = [{key: article.get(key) for key in READER_FIELDS} for article in news.get("articles", [])]
    for article in articles:
        article["also_seen_in"] = [{"source": item.get("source"), "link": item.get("link")}
                                   for item in article.get("also_seen_in") or []]
    errors = [{"url": error.get("url"), "status": error.get("status")} for error in news.get("errors", [])]
    return {"articles": articles, "errors": errors, "sources": len(news.get("input_sources") or []),
            "skills": skills}


NUMERIC_LIMITS = {
    "LLM_NUM_CTX": (512, 1048576), "LLM_MAX_NUM_CTX": (512, 1048576),
    "LLM_STARTUP_WAIT": (0, 3600), "SMTP_PORT": (1, 65535), "PER_FEED_LIMIT": (1, 100),
    "DETAIL_LIMIT": (0, 100), "CONCURRENCY": (1, 32), "EXTRACT_TIMEOUT": (1, 3600),
    "MAX_CONTENT_CHARS": (500, 100000), "LLM_MAX_RETRIES": (0, 10), "LLM_BACKOFF_BASE": (0, 60),
    "LLM_TIMEOUT": (0, 3600), "LLM_CONCURRENCY": (0, 32), "SKILLS_WINDOW_DAYS": (1, 365),
    "MAX_SKILL_GAPS": (1, 50), "HISTORY_KEEP_DAYS": (1, 3650),
}


def execute(store, row, *, dry=False):
    import brief

    event = json.loads(row["event"])
    cfg = None
    try:
        cfg = store.config_for(event.get("provider"), {
            "TOPIC": event["topic"], "SOURCES_RAW": event["sources"], "WINDOW_HOURS": event["window"],
            "KEYWORDS": [word.strip() for word in event["keywords"].split(",") if word.strip()],
        })
        with using_config(cfg):
            name = event["name"]
            stamp = datetime.now(ZoneInfo(event["timezone"]))
            news, skills, html = brief.build_briefing(name, weekly=bool(row["weekly"]) and cfg.TOPIC == "ai",
                                                       strict=True, when=stamp)
            with store.connect() as db:
                db.execute("UPDATE runs SET html=?, news=?, article_count=?, issues=? WHERE id=?",
                           (html, json.dumps(reader_payload(news, skills)), len(news["articles"]),
                            len(news["errors"]), row["id"]))
            pdf = brief.save_pdf(news, skills, name, stamp, row["id"])
            if dry:
                (brief.HERE / "last_briefing.html").write_text(html, encoding="utf-8")
            if row["email"]:
                brief.check_configuration(email=True)
                subject = f"{name} — {stamp:%b %d, %Y}" + (" + skills gap" if skills else "")
                brief.send_email(html, subject, attach=pdf if cfg.ATTACH_PDF else None)
    except Exception as exc:
        log.exception("Briefing %s failed", row["id"])
        error = str(exc) if isinstance(exc, ValueError) else "Run failed. Check the server log for details."
        if cfg is not None:
            for secret in (cfg.LLM_API_KEY, cfg.SMTP_PASS):
                if secret:
                    error = error.replace(secret, "[redacted]")
        status = "failed"
    else:
        status, error = "complete", None
    with store.connect() as db:
        db.execute("UPDATE runs SET status=?, error=?, finished=?, delivered=? WHERE id=?",
                   (status, error, time.time(), status == "complete" and row["email"], row["id"]))
    return status == "complete"


def recover_interrupted(store):
    with store.connect() as db:
        db.execute("""UPDATE runs SET status='failed', finished=?, error=?
                      WHERE status='running'""",
                   (time.time(), "Worker stopped before confirming completion."))


def process_next(store, *, target=None, dry=False):
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        if target is None:
            row = db.execute("SELECT * FROM runs WHERE status='queued' ORDER BY id LIMIT 1").fetchone()
        else:
            row = db.execute("SELECT * FROM runs WHERE id=?", (target,)).fetchone()
        if row is None:
            return None
        db.execute("UPDATE runs SET status='running' WHERE id=?", (row["id"],))
    return execute(store, row, dry=dry)


def drain(store):
    with store.worker_lock() as locked:
        if locked:
            recover_interrupted(store)
            while process_next(store) is not None:
                store.queue_due()


def run_headless(store, event_id, *, dry=False, weekly=False):
    with store.worker_lock(wait=True):
        recover_interrupted(store)
        try:
            run_id = store.enqueue(event_id, email=False if dry else None, weekly=weekly)
        except KeyError:
            log.error("Event %s does not exist.", event_id)
            return 2
        return 0 if process_next(store, target=run_id, dry=dry) else 1
