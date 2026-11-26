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
from briefing_store import DAYS, PRESETS, Store, drain, run_headless
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
