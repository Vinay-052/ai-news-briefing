import asyncio
import json
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from unittest.mock import patch

import httpx

import brief
from briefing_store import DAYS, PRESETS, Store, drain, next_run, run_headless
from config import make_config, using_config
from webapp import Dashboard


class DispatchTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.store = Store(self.directory)

    def event(self, preset="politics", **values):
        event = dict(PRESETS[preset], days=DAYS, timezone="Asia/Kolkata",
                     enabled=True, email=False, weekly=False, keywords="", window=24)
        event.update(values)
        return self.store.save_event(event)

    def configured_gateway(self):
        self.store.save_settings({
            "LLM_PROVIDER": "openai", "LLM_BASE_URL": "https://model.example/v1",
            "LLM_MODEL": "fixture-model", "REQUIRE_API_KEY": False,
            "SMTP_HOST": "smtp.example", "SMTP_SECURITY": "plain",
            "MAIL_FROM": "news@example.com", "MAIL_TO": "reader@example.com",
            "PDF_DIR": str(self.directory), "SAVE_PDF": True, "ATTACH_PDF": True,
        })

    def test_distinct_timezone_schedules_and_idempotency(self):
        first = self.event(time="09:00", days=[0])
        second = self.event("trends", time="10:00", timezone="UTC", days=[0])
        with self.store.connect() as db:
            db.execute("UPDATE events SET changed=0")
        now = datetime(2026, 11, 23, 3, 30, tzinfo=timezone.utc)
        self.store.queue_due(now)
        self.store.queue_due(now)
        self.assertEqual([run["event_id"] for run in self.store.runs()], [first["id"]])
        self.store.queue_due(now.replace(hour=10))
        self.assertEqual([run["event_id"] for run in self.store.runs()], [second["id"], first["id"]])

    def test_sunday_skills_and_dst_repeat(self):
        event = self.event("ai", time="01:30", timezone="America/New_York", days=[6], weekly=True)
        with self.store.connect() as db:
            db.execute("UPDATE events SET changed=0")
        for hour in (5, 6):
            self.store.queue_due(datetime(2026, 11, 1, hour, 35, tzinfo=timezone.utc))
        with self.store.connect() as db:
            rows = db.execute("SELECT event_id, weekly FROM runs").fetchall()
        self.assertEqual([tuple(row) for row in rows], [(event["id"], 1)])

    def test_schedule_activation_and_delete_cancel_queued(self):
        event = self.event()
        self.store.queue_due(datetime(2020, 1, 1, 20, tzinfo=timezone.utc))
        self.assertEqual(self.store.runs(), [])
        run_id = self.store.enqueue(event["id"])
        self.store.delete_event(event["id"])
        self.assertEqual(self.store.runs()[0]["status"], "cancelled")
        self.assertEqual(self.store.runs()[0]["id"], run_id)

    def test_settings_hide_secrets_and_drop_them_when_endpoint_changes(self):
        view = self.store.save_settings({"LLM_API_KEY": "example-secret"})
        self.assertIs(view["LLM_API_KEY"], True)
        self.assertNotIn("example-secret", json.dumps(view))
        self.store.save_settings({"LLM_API_KEY": ""})
        self.assertEqual(self.store.settings()["LLM_API_KEY"], "example-secret")
        view = self.store.save_settings({"LLM_PROVIDER": "chatgpt", "LLM_BASE_URL": "https://api.openai.com/v1"})
        self.assertIs(view["LLM_API_KEY"], False)
        self.assertEqual(self.store.settings()["LLM_API_KEY"], "")
        self.assertEqual((self.directory / "settings.json").stat().st_mode & 0o777, 0o600)
        with self.assertRaises(ValueError):
            self.store.save_settings({"CONCURRENCY": 0})

    def test_chatgpt_and_opencode_requests(self):
        async def call(provider, endpoint, response):
            def reply(request):
                self.assertEqual(request.url.path, endpoint)
                self.assertEqual(request.headers["Authorization"], "Bearer fixture-key")
                body = json.loads(request.content)
                if provider == "chatgpt":
                    self.assertIs(body["store"], False)
                    self.assertEqual(body["input"], "Fixture prompt")
                else:
                    self.assertEqual(body["messages"][0]["content"], "Fixture prompt")
                return httpx.Response(200, json=response)

            cfg = make_config({
                "LLM_PROVIDER": provider, "LLM_BASE_URL": "https://sample.example/v1",
                "LLM_MODEL": "fixture", "LLM_API_KEY": "fixture-key",
            })
            with using_config(cfg):
                async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
                    self.assertEqual(await brief.llm_call(client, "Fixture prompt"), "Fixture response")

        asyncio.run(call("chatgpt", "/v1/responses", {
            "status": "completed", "output": [
                {"type": "message", "content": [{"type": "output_text", "text": "Fixture response"}]},
            ],
        }))
        asyncio.run(call("opencode", "/v1/chat/completions",
                         {"choices": [{"message": {"content": "Fixture response"}}]}))

    def test_pipeline_archives_and_sends_linked_email_and_pdf(self):
        self.configured_gateway()
        event = self.event(sources="https://news.example/rss.xml", email=True)
        run_id = self.store.enqueue(event["id"])
        primary = "https://news.example/story-one"
        related = "https://news.example/story-two"
        feed = f"""<rss version="2.0"><channel><title>Example News</title>
          <item><title>Budget approved by council</title><link>{primary}</link><description>Budget approved.</description></item>
          <item><title>Budget approved by council</title><link>{related}</link><description>Budget approved.</description></item>
          </channel></rss>"""
        article_content = "The council voted to adopt the budget after a public hearing."
        article = f"<html><title>Council budget</title><article><p>{article_content * 6}</p></article></html>"
        def reply(request):
            if request.url.host == "model.example":
                prompt = json.loads(request.content)["messages"][0]["content"]
                self.assertIn("politics and public policy", prompt)
                self.assertIn("general audience", prompt)
                return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({
                    "what_happened": "The council approved the budget.",
                    "why_it_matters": "It sets the spending plan.", "summary": "Council approved a budget.",
                    "builder_takeaway": "Watch the implementation.", "category": "Politics", "relevant": True,
                })}}]})
            self.assertEqual(request.url.host, "news.example")
            return httpx.Response(200, text=feed if request.url.path == "/rss.xml" else article)

        client = httpx.AsyncClient
        def client_with_fixture(**kwargs):
            return client(transport=httpx.MockTransport(reply), **kwargs)

        with patch("brief.httpx.AsyncClient", side_effect=client_with_fixture), \
             patch("brief._host_is_public", return_value=True), patch("brief.smtplib.SMTP") as smtp:
            drain(self.store)
        row = self.store.runs()[0]
        self.assertEqual((row["status"], row["article_count"], row["delivered"]), ("complete", 1, 1))
        html = self.store.report(run_id)
        self.assertIn(f'href="{primary}"', html)
        self.assertIn(f'href="{related}"', html)
        self.assertIn("What to watch", html)
        self.assertIn("Politics Briefing", html)
        message = smtp.return_value.__enter__.return_value.send_message.call_args.args[0]
        self.assertIsInstance(message, EmailMessage)
        self.assertIn(primary, message.get_body(preferencelist=("plain",)).get_content())
        self.assertIn(related, message.get_body(preferencelist=("html",)).get_content())
        self.assertEqual(next(message.iter_attachments()).get_content_type(), "application/pdf")
        edition = self.store.articles(run_id)
        self.assertTrue(edition["structured"])
        self.assertEqual(edition["articles"][0]["link"], primary)
        self.assertEqual(edition["articles"][0]["also_seen_in"][0]["link"], related)
        self.assertEqual(edition["articles"][0]["writeup"]["what_happened"], "The council approved the budget.")
        self.assertEqual([a["link"] for a in self.store.explore(hours=24)], [primary])

    def test_headless_dry_run_writes_archive_without_sending(self):
        self.configured_gateway()
        event = self.event(email=True)
        with patch("brief.HERE", self.directory), patch("brief.build_briefing", return_value=(
             {"articles": [], "errors": []}, None, "<html>Fixture report</html>")), patch("brief.send_email") as email:
            self.assertEqual(run_headless(self.store, event["id"], dry=True), 0)
        email.assert_not_called()
        row = self.store.runs()[0]
        self.assertEqual(row["status"], "complete")
        self.assertEqual((self.directory / "last_briefing.html").read_text(), self.store.report(row["id"]))

    def test_email_failure_preserves_archive(self):
        self.configured_gateway()
        run_id = self.store.enqueue(self.event(email=True)["id"])
        with patch("brief.build_briefing", return_value=(
             {"articles": [], "errors": []}, None, "<html>Fixture report</html>")), \
             patch("brief.send_email", side_effect=OSError("SMTP unavailable")), self.assertLogs("briefing_store"):
            drain(self.store)
        row = self.store.runs()[0]
        self.assertEqual((row["status"], row["delivered"]), ("failed", 0))
        self.assertIn("Fixture report", self.store.report(run_id))

    def test_http_dashboard_events_and_report(self):
        try:
            server = Dashboard(0, self.store)
        except PermissionError:
            self.skipTest("The test environment prevents binding to localhost")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        base_url = f"http://127.0.0.1:{server.server_port}"
        headers = {"X-Briefing-Request": "dashboard"}
        with httpx.Client(base_url=base_url) as client:
            self.assertEqual(client.get("/").status_code, 200)
            self.assertEqual(client.get("/app.js").status_code, 200)
            self.assertEqual(client.get("/api/settings", headers={"Host": "another.example"}).status_code, 403)
            data = client.get("/api/presets").json()["trends"]
            self.assertEqual(client.post("/api/events", json=data).status_code, 403)
            response = client.post("/api/events", json=data, headers=headers)
            self.assertEqual(response.status_code, 201)
            event_id = response.json()["id"]
            run = client.post(f"/api/events/{event_id}/run", json={}, headers=headers)
            self.assertEqual(run.status_code, 202)
            run_id = run.json()["id"]
            with self.store.connect() as db:
                db.execute("UPDATE runs SET html=? WHERE id=?", ("<html><head></head><body>Fixture</body></html>", run_id))
            report = client.get(f"/reports/{run_id}")
            self.assertIn('<base target="_blank">', report.text)
            self.assertIn("sandbox", report.headers["Content-Security-Policy"])
            self.assertEqual(client.get("/api/dashboard").json()["runs"][0]["id"], run_id)


class ProviderAndReaderTest(unittest.TestCase):
    # Share the fixtures without re-running DispatchTest's own tests.
    setUp = DispatchTest.setUp
    event = DispatchTest.event
    configured_gateway = DispatchTest.configured_gateway

    def test_anthropic_request(self):
        def reply(request):
            self.assertEqual(request.url.path, "/v1/messages")
            self.assertEqual(request.headers["x-api-key"], "fixture-key")
            self.assertEqual(request.headers["anthropic-version"], "2023-06-01")
            self.assertNotIn("Authorization", request.headers)
            body = json.loads(request.content)
            self.assertEqual(body["messages"][0]["content"], "Fixture prompt")
            return httpx.Response(200, json={"content": [{"type": "text", "text": "Fixture response"}]})

        async def call():
            cfg = make_config({"LLM_PROVIDER": "anthropic", "LLM_BASE_URL": "https://claude.example/v1",
                               "LLM_MODEL": "claude-fixture", "LLM_API_KEY": "fixture-key"})
            with using_config(cfg):
                async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
                    return await brief.llm_call(client, "Fixture prompt")

        self.assertEqual(asyncio.run(call()), "Fixture response")
        with using_config(make_config({"LLM_PROVIDER": "anthropic", "LLM_API_KEY": ""})):
            with self.assertRaises(ValueError):
                brief.check_configuration()

    def test_provider_profiles_mask_keys_and_drive_event_runs(self):
        profile = self.store.save_provider({
            "name": "Claude", "LLM_PROVIDER": "anthropic", "LLM_BASE_URL": "https://claude.example/v1",
            "LLM_MODEL": "claude-fixture", "LLM_API_KEY": "secret-one", "REQUIRE_API_KEY": True})
        self.assertIs(profile["LLM_API_KEY"], True)
        self.assertIs(self.store.providers()[0]["LLM_API_KEY"], True)
        # A blank key keeps the stored one while the endpoint is unchanged...
        self.store.save_provider(dict(profile, LLM_API_KEY="", LLM_MODEL="claude-other"), profile["id"])
        self.assertEqual(self.store.provider(profile["id"])["LLM_API_KEY"], "secret-one")
        # ...but never follows the profile to a different host.
        self.store.save_provider(dict(profile, LLM_API_KEY="", LLM_BASE_URL="https://elsewhere.example/v1"),
                                 profile["id"])
        self.assertEqual(self.store.provider(profile["id"])["LLM_API_KEY"], "")
        self.store.save_provider(dict(profile, LLM_API_KEY="secret-two"), profile["id"])
        with self.assertRaises(ValueError):
            self.store.save_provider(dict(profile, LLM_PROVIDER="bogus"))

        event = self.event(provider=profile["id"])
        with self.assertRaises(ValueError):
            self.event(provider=999)
        with self.assertRaises(ValueError):
            self.store.delete_provider(profile["id"])

        seen = {}
        def build(name, **kwargs):
            seen.update(provider=brief.CONFIG.PROVIDER, model=brief.CONFIG.LLM_MODEL, key=brief.CONFIG.LLM_API_KEY)
            return {"articles": [], "errors": []}, None, "<html></html>"
        self.store.enqueue(event["id"])
        with patch("brief.build_briefing", side_effect=build):
            drain(self.store)
        self.assertEqual(seen, {"provider": "anthropic", "model": "claude-fixture", "key": "secret-two"})

        self.store.save_event(dict(self.store.event(event["id"]), provider=None), event["id"])
        self.store.delete_provider(profile["id"])
        self.assertEqual(self.store.providers(), [])

    def test_connection_test_reports_failures_without_leaking_the_key(self):
        self.store.save_settings({"LLM_PROVIDER": "chatgpt", "LLM_BASE_URL": "https://model.example/v1",
                                  "LLM_MODEL": "fixture", "LLM_API_KEY": "leaky-key"})
        with patch("brief.test_connection", side_effect=RuntimeError("denied for leaky-key")):
            result = self.store.test_provider()
        self.assertFalse(result["ok"])
        self.assertNotIn("leaky-key", result["message"])
        with patch("brief.test_connection", return_value="ready"):
            self.assertTrue(self.store.test_provider()["ok"])

    def test_next_run_and_readiness(self):
        event = self.event(time="09:00", timezone="UTC", days=[0])
        stored = self.store.event(event["id"])
        monday = datetime(2026, 11, 23, 8, 0, tzinfo=timezone.utc)
        self.assertEqual(next_run(stored, 0, monday), datetime(2026, 11, 23, 9, 0, tzinfo=timezone.utc).timestamp())
        self.assertEqual(next_run(stored, 0, monday.replace(hour=10)),
                         datetime(2026, 11, 30, 9, 0, tzinfo=timezone.utc).timestamp())
        self.assertIsNone(next_run(dict(stored, enabled=False), 0, monday))
        self.store.save_settings({"LLM_PROVIDER": "chatgpt", "LLM_BASE_URL": "https://model.example/v1",
                                  "LLM_MODEL": "fixture"})
        self.assertIn("API key", self.store.readiness()["model"])

    def test_resend_archived_edition_by_email(self):
        self.configured_gateway()
        run_id = self.store.enqueue(self.event()["id"])
        with self.assertRaises(KeyError):
            self.store.email_run(run_id)
        with self.store.connect() as db:
            db.execute("UPDATE runs SET html=?, status='complete' WHERE id=?", ("<html>Edition</html>", run_id))
        with patch("brief.send_email") as send:
            self.assertEqual(self.store.email_run(run_id)["to"], "reader@example.com")
        self.assertIn("Politics Briefing", send.call_args.args[1])
        self.assertEqual(self.store.runs()[0]["delivered"], 1)
        # Editions archived before the reader existed still open, with no articles.
        self.assertFalse(self.store.articles(run_id)["structured"])

    def test_http_reader_explore_and_provider_routes(self):
        try:
            server = Dashboard(0, self.store)
        except PermissionError:
            self.skipTest("The test environment prevents binding to localhost")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        headers = {"X-Briefing-Request": "dashboard"}
        run_id = self.store.enqueue(self.event()["id"])
        payload = {"articles": [{"title": "Story", "link": "https://news.example/a"}], "errors": [], "skills": None}
        with self.store.connect() as db:
            db.execute("UPDATE runs SET news=?, html='<html></html>', status='complete' WHERE id=?",
                       (json.dumps(payload), run_id))
        with httpx.Client(base_url=f"http://127.0.0.1:{server.server_port}") as client:
            dashboard = client.get("/api/dashboard").json()
            self.assertIn("ready", dashboard)
            self.assertIn("next_run", dashboard["events"][0])
            self.assertEqual(client.get(f"/api/runs/{run_id}").json()["articles"][0]["title"], "Story")
            self.assertEqual(client.get("/api/explore?hours=24").json()["articles"][0]["run_id"], run_id)
            self.assertEqual(client.get("/api/explore?hours=abc").status_code, 400)
            created = client.post("/api/providers", headers=headers, json={
                "name": "Gateway", "LLM_PROVIDER": "openai", "LLM_BASE_URL": "https://gw.example/v1",
                "LLM_MODEL": "m", "LLM_API_KEY": "k", "REQUIRE_API_KEY": True})
            self.assertEqual(created.status_code, 201)
            self.assertIs(created.json()["LLM_API_KEY"], True)
            provider_id = created.json()["id"]
            self.assertNotIn('"k"', client.get("/api/dashboard").text)
            with patch("brief.test_connection", return_value="ready"):
                tested = client.post("/api/providers/test", headers=headers, json={"provider": provider_id})
            self.assertTrue(tested.json()["ok"])
            deleted = client.post(f"/api/providers/{provider_id}/delete", headers=headers, json={})
            self.assertEqual(deleted.json(), {"deleted": True})
