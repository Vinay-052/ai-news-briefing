"""Local dashboard and optional headless scheduler for News Briefing."""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from briefing_store import DAYS, PRESETS, Store, drain, local_zone
from sources import AI_NEWS_SOURCES

WEB = Path(__file__).resolve().parent / "web"
ASSETS = {
    "/": ("index.html", "text/html"),
    "/app.js": ("app.js", "text/javascript"),
    "/style.css": ("style.css", "text/css"),
    "/favicon.svg": ("favicon.svg", "image/svg+xml"),
    "/favicon.ico": ("favicon.ico", "image/x-icon"),
    "/apple-touch-icon.png": ("apple-touch-icon.png", "image/png"),
}
log = logging.getLogger(__name__)


class Dashboard(ThreadingHTTPServer):
    def __init__(self, port, store):
        super().__init__(("127.0.0.1", port), Handler)
        self.store = store
        self.wake = threading.Event()
        port = self.server_port
        self.hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        if port == 80:
            self.hosts.update({"127.0.0.1", "localhost"})


class Handler(BaseHTTPRequestHandler):
    def send(self, status, body, mime, policy=None):
        self.send_response(status)
        # Binary assets (icons) must not claim a text charset.
        text = mime.startswith("text/") or mime in ("application/json", "image/svg+xml")
        self.send_header("Content-Type", mime + "; charset=utf-8" if text else mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("Content-Security-Policy", policy or (
            "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
            "img-src 'self'; frame-src 'self'; frame-ancestors 'self'; base-uri 'none'; form-action 'none'"
        ))
        self.end_headers()
        self.wfile.write(body)

    def json(self, data, status=200):
        self.send(status, json.dumps(data).encode(), "application/json")

    def do_GET(self):
        self.route("GET")

    def do_POST(self):
        self.route("POST")

    def route(self, method):
        if self.headers.get("Host") not in self.server.hosts:
            self.json({"error": "Invalid host."}, 403)
            return
        if self.headers.get("Sec-Fetch-Site") in ("cross-site", "same-site"):
            self.json({"error": "Open the dashboard directly."}, 403)
            return
        try:
            if method == "GET":
                self.read()
            else:
                if (self.headers.get("X-Briefing-Request") != "dashboard"
                        or self.headers.get_content_type() != "application/json"):
                    self.json({"error": "Expected a dashboard JSON request."}, 403)
                    return
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 65536:
                    self.json({"error": "Request is empty or too large."}, 413)
                    return
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise ValueError("Expected an object.")
                self.write(data)
        except KeyError as exc:
            self.json({"error": str(exc.args[0])}, 404)
        except ValueError as exc:
            self.json({"error": str(exc)}, 400)
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception:
            log.exception("Dashboard request failed")
            self.json({"error": "Request failed. Check the server log."}, 500)

    def read(self):
        store = self.server.store
        url = urlsplit(self.path)
        query = parse_qs(url.query)
        if url.path in ASSETS:
            filename, mime = ASSETS[url.path]
            self.send(200, (WEB / filename).read_bytes(), mime)
        elif self.path == "/api/dashboard":
            self.json({"events": store.events(), "runs": store.runs(),
                       "providers": store.providers(), "ready": store.readiness()})
        elif match := re.fullmatch(r"/api/runs/(\d+)", self.path):
            self.json(store.articles(int(match[1])))
        elif url.path == "/api/explore":
            def integer(name):
                value = (query.get(name) or [""])[0]
                if value and not value.isdigit():
                    raise ValueError(f"Invalid {name}.")
                return int(value) if value else None
            self.json({"articles": store.explore(hours=integer("hours") or 0, event_id=integer("event"))})
        elif self.path == "/api/settings":
            self.json(store.public_settings())
        elif self.path == "/api/presets":
            presets = {key: dict(value, days=DAYS, timezone=local_zone(), enabled=False,
                                 email=False, weekly=False, keywords="", window=24)
                       for key, value in PRESETS.items()}
            # Friendly names for the starter URLs, shown beside them in the source editor.
            presets["labels"] = {source["url"]: source["name"] for source in AI_NEWS_SOURCES}
            self.json(presets)
        elif match := re.fullmatch(r"/reports/(\d+)", self.path):
            html = store.report(int(match[1])).replace("<head>", '<head><base target="_blank">', 1)
            self.send(200, html.encode(), "text/html",
                      "sandbox allow-popups allow-popups-to-escape-sandbox; default-src 'none'; "
                      "style-src 'unsafe-inline'; frame-ancestors 'self'; form-action 'none'")
        else:
            raise KeyError("Page not found.")

    def write(self, data):
        store = self.server.store
        if self.path == "/api/events":
            self.json(store.save_event(data), 201)
        elif self.path == "/api/settings":
            self.json(store.save_settings(data))
        elif self.path == "/api/providers":
            self.json(store.save_provider(data), 201)
        elif self.path == "/api/providers/models":
            self.json(self.server.store.list_models(data))
        elif self.path == "/api/providers/test":
            provider = data.get("provider")
            if provider is not None and type(provider) is not int:
                raise ValueError("Invalid provider.")
            self.json(store.test_provider(provider))
        elif match := re.fullmatch(r"/api/providers/(\d+)(/delete)?", self.path):
            if match[2]:
                store.delete_provider(int(match[1]))
                self.json({"deleted": True})
            else:
                self.json(store.save_provider(data, int(match[1])))
        elif match := re.fullmatch(r"/api/runs/(\d+)/email", self.path):
            self.json(store.email_run(int(match[1])))
        elif match := re.fullmatch(r"/api/events/(\d+)(?:/(run|delete))?", self.path):
            event_id = int(match[1])
            action = match[2]
            if action == "run":
                weekly = data.get("weekly", False)
                if type(weekly) is not bool:
                    raise ValueError("Invalid weekly value.")
                email = data.get("email")
                if email is not None and type(email) is not bool:
                    raise ValueError("Invalid email value.")
                run_id = store.enqueue(event_id, email=email, weekly=weekly)
                self.server.wake.set()
                self.json({"id": run_id}, 202)
            elif action == "delete":
                store.delete_event(event_id)
                self.json({"deleted": True})
            else:
                self.json(store.save_event(data, event_id))
                self.server.wake.set()
        else:
            raise KeyError("Page not found.")

    def log_message(self, fmt, *args):
        # Polling is routine. Log HTTP errors and mutations only.
        if args[1] != "200" or not args[0].startswith("GET /api/"):
            super().log_message(fmt, *args)


def work(store, stop, wake):
    while not stop.is_set():
        try:
            store.queue_due()
            drain(store)
        except Exception:
            log.exception("Scheduler tick failed")
        wake.wait(10)
        wake.clear()


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("serve", "worker", "tick"), nargs="?", default="serve")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    store = Store()
    if args.mode == "tick":
        store.queue_due()
        drain(store)
        return
    stop = threading.Event()
    if args.mode == "worker":
        try:
            work(store, stop, threading.Event())
        except KeyboardInterrupt:
            return
    else:
        with Dashboard(args.port, store) as server:
            thread = threading.Thread(target=work, args=(store, stop, server.wake), daemon=True)
            thread.start()
            print(f"Dashboard: http://127.0.0.1:{server.server_port}", flush=True)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                stop.set()
                server.wake.set()


if __name__ == "__main__":
    main()
