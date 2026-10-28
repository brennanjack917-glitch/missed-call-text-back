import tempfile
import unittest
from pathlib import Path

from scripts.config import load_config, message, safety_message
from scripts.notify import EmailNotifier
from scripts.store import Store
from scripts.web import create_app, csv_safe, tel_link
from scripts.webhook import WebhookNotifier
from tests.fakes import OPEN_TIME, FakeLLM, answer


class WebTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = load_config()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.preview_dir = Path(self.tmp.name)
        self.store = Store(":memory:")
        self.email = EmailNotifier(self.cfg, {}, preview_dir=self.preview_dir, send=False)
        self.llm = FakeLLM()

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def client(self, *results):
        self.llm.results.extend(results)
        app = create_app(self.cfg, self.store, self.llm, self.email, clock=lambda: OPEN_TIME,
                         preview_dir=self.preview_dir)
        return app.test_client()

    def call(self, client):
        return client.post("/api/call", json={}).get_json()

    def text(self, client, caller, text):
        return client.post("/api/text", json={"caller": caller, "text": text})


class DemoTests(WebTestCase):
    def test_demo_page_loads(self):
        page = self.client().get("/").get_data(as_text=True)
        self.assertIn("Harbor Plumbing &amp; Heating", page)
        self.assertIn("Simulate missed call", page)

    def test_demo_page_says_whether_the_webhook_is_on(self):
        self.assertIn("CRM webhook: off.", self.client().get("/").get_data(as_text=True))
        for url, link in (("http://127.0.0.1:5051/", True), ("https://hooks.zapier.com/hooks/catch/1/secret/", False)):
            webhook = WebhookNotifier(self.cfg, {"LEAD_WEBHOOK_URL": url}, self.store)
            app = create_app(self.cfg, self.store, self.llm, self.email, clock=lambda: OPEN_TIME,
                             preview_dir=self.preview_dir, webhook=webhook)
            page = app.test_client().get("/").get_data(as_text=True)
            self.assertIn("CRM webhook: on.", page)
            self.assertEqual("Watch leads arrive" in page, link)
            self.assertNotIn("secret", page)  # a real address is never shown
        bad = WebhookNotifier(self.cfg, {"LEAD_WEBHOOK_URL": "http://example.com/hook"}, self.store)
        app = create_app(self.cfg, self.store, self.llm, self.email, clock=lambda: OPEN_TIME,
                         preview_dir=self.preview_dir, webhook=bad)
        self.assertIn("must start with https://", app.test_client().get("/").get_data(as_text=True))

    def test_missed_call_gives_a_fictional_number_and_the_greeting(self):
        state = self.call(self.client())
        self.assertRegex(state["caller"], r"^\(\d{3}\) 555-01\d\d$")
        self.assertEqual(state["messages"], [{"from": "fixed", "body": message(self.cfg, "greeting")}])
        self.assertEqual(state["conversation"]["status"], "active")

    def test_each_new_call_gets_a_number_not_texted_today(self):
        client = self.client()
        callers = {self.call(client)["caller"] for _ in range(5)}
        self.assertEqual(len(callers), 5)

    def test_full_conversation_fills_the_lead_card_and_explains_the_code(self):
        client = self.client(answer("Once you're safe, what's the address?", problem="gas smell"),
                             answer("x", status="complete", name="Dana", address="12 Elm St, Quincy"))
        caller = self.call(client)["caller"]
        state = self.text(client, caller, "I smell gas").get_json()
        self.assertEqual([m["body"] for m in state["messages"][1:]],
                         ["I smell gas", safety_message(self.cfg, "gas"), "Once you're safe, what's the address?"])
        self.assertEqual(state["lead"]["urgency"], "emergency")
        self.assertTrue(any("emergency words" in line for line in state["events"]))
        state = self.text(client, caller, "Dana, 12 Elm St Quincy").get_json()
        self.assertEqual(state["conversation"]["status"], "complete")
        self.assertEqual(state["lead"]["name"], "Dana")
        self.assertEqual(state["cost"]["calls"], 2)
        self.assertIsNotNone(state["email_preview"])
        self.assertIn("EMERGENCY", client.get(state["email_preview"]).get_data(as_text=True))

    def test_bad_requests_are_refused(self):
        client = self.client()
        caller = self.call(client)["caller"]
        self.assertEqual(self.text(client, caller, "").status_code, 400)
        self.assertEqual(self.text(client, caller, "x" * 1001).status_code, 400)
        self.assertEqual(self.text(client, "(617) 867-5309", "hi").status_code, 400)  # not a demo number
        self.assertEqual(self.text(client, "(617) 555-0100" if caller != "(617) 555-0100" else "(617) 555-0101",
                                   "hi").status_code, 404)  # no conversation yet
        self.assertEqual(self.llm.calls, [])

    def test_other_websites_cannot_drive_the_server(self):
        client = self.client()
        # A form post (what a forged cross-site request would be) is refused
        self.assertEqual(client.post("/api/call", data={"x": "1"}).status_code, 415)
        # A request addressed to another host name (DNS rebinding) is refused
        self.assertEqual(client.get("/", headers={"Host": "evil.example:5050"}).status_code, 403)

    def test_email_switch_needs_gmail(self):
        client = self.client()
        self.assertFalse(client.post("/api/settings", json={"send_email": True}).get_json()["send_email"])
        self.email.env = {"GMAIL_ADDRESS": "owner@example.com", "GMAIL_APP_PASSWORD": "x"}
        self.assertTrue(client.post("/api/settings", json={"send_email": True}).get_json()["send_email"])
        self.assertTrue(self.email.send)


class ErrorAndClearTests(WebTestCase):
    def test_unexpected_errors_get_a_friendly_message(self):
        client = self.client()
        caller = self.call(client)["caller"]
        self.llm.results.append("not a valid answer")  # makes the engine crash
        with self.assertLogs("scripts.web", level="ERROR"):
            r = self.text(client, caller, "hello")
        self.assertEqual(r.status_code, 500)
        self.assertIn("Something went wrong on our side", r.get_json()["error"])

    def test_clear_demo_data_needs_confirming(self):
        client = self.client(answer(status="complete"))
        caller = self.call(client)["caller"]
        self.text(client, caller, "done")
        self.assertTrue(list(self.preview_dir.glob("lead-*.html")))
        self.assertEqual(client.post("/api/clear", json={}).status_code, 400)
        self.assertEqual(len(self.store.leads()), 1)
        self.assertTrue(client.post("/api/clear", json={"confirm": True}).get_json()["ok"])
        self.assertEqual(self.store.leads(), [])
        self.assertEqual(list(self.preview_dir.glob("lead-*.html")), [])
        self.assertIsNone(client.get(f"/api/state?caller={caller}").get_json()["conversation"])


class OwnerTests(WebTestCase):
    def make_lead(self, caller, now=OPEN_TIME, **fields):
        conv_id = self.store.create_conversation(caller, now, "note")
        self.store.update_lead(conv_id, now, **fields)
        return conv_id

    def test_owner_page_lists_filters_and_escapes(self):
        self.make_lead("(617) 555-0101", name="<script>alert(1)</script>", problem="burst pipe", urgency="emergency")
        self.make_lead("(617) 555-0102", name="Sam", problem="slow drain", urgency="routine", status="contacted")
        client = self.client()
        page = client.get("/owner").get_data(as_text=True)
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertIn("&lt;script&gt;", page)
        self.assertIn('href="tel:+16175550101"', page)
        self.assertIn("1</span> new", page)
        filtered = client.get("/owner?status=contacted").get_data(as_text=True)
        self.assertIn("slow drain", filtered)
        self.assertNotIn("burst pipe", filtered)
        self.assertIn("burst pipe", client.get("/owner?q=BURST").get_data(as_text=True))
        self.assertIn("No leads match", client.get("/owner?q=nothing-like-this").get_data(as_text=True))

    def test_crm_badges_show_only_after_a_webhook_send(self):
        self.make_lead("(617) 555-0101", problem="burst pipe", crm_sync_status="synced")
        self.make_lead("(617) 555-0102", problem="slow drain", crm_sync_status="failed")
        self.make_lead("(617) 555-0103", problem="dripping tap")
        page = self.client().get("/owner").get_data(as_text=True)
        self.assertEqual(page.count("Sent to CRM"), 1)
        self.assertEqual(page.count("CRM send failed"), 1)

    def test_status_and_notes_save(self):
        conv_id = self.make_lead("(617) 555-0101")
        client = self.client()
        r = client.post(f"/api/leads/{conv_id}", json={"status": "contacted"})
        self.assertEqual(r.get_json()["counts"], {"new": 0, "contacted": 1, "closed": 0})
        client.post(f"/api/leads/{conv_id}", json={"notes": "left voicemail"})
        lead = self.store.lead(conv_id)
        self.assertEqual((lead["status"], lead["notes"]), ("contacted", "left voicemail"))
        self.assertEqual(client.post(f"/api/leads/{conv_id}", json={"status": "deleted"}).status_code, 400)
        self.assertEqual(client.post("/api/leads/999", json={"status": "closed"}).status_code, 404)

    def test_conversation_page_shows_who_wrote_each_text(self):
        client = self.client(answer("What's the address?"))
        caller = self.call(client)["caller"]
        self.text(client, caller, "<b>leaky</b> faucet")
        conv_id = self.store.latest_conversation(caller)["id"]
        page = client.get(f"/owner/conversation/{conv_id}").get_data(as_text=True)
        self.assertIn("&lt;b&gt;leaky&lt;/b&gt; faucet", page)
        self.assertIn("Pre-written message", page)
        self.assertIn("Written by the AI", page)
        self.assertEqual(client.get("/owner/conversation/999").status_code, 404)

    def test_csv_export(self):
        self.make_lead("(617) 555-0101", name="=HYPERLINK(\"http://x\")", problem="burst pipe", notes="call back")
        r = self.client().get("/owner/leads.csv")
        self.assertEqual(r.mimetype, "text/csv")
        self.assertIn("attachment", r.headers["Content-Disposition"])
        text = r.get_data(as_text=True)
        self.assertTrue(text.startswith("﻿conversation_id,created_at,status"))
        self.assertIn("'=HYPERLINK", text)
        self.assertIn("burst pipe", text)


class HelperTests(unittest.TestCase):
    def test_tel_link_prefers_the_confirmed_number(self):
        self.assertEqual(tel_link({"callback_number": "617-555-0199", "caller_number": "(617) 555-0101"}),
                         "tel:+16175550199")
        self.assertEqual(tel_link({"callback_number": "my cell", "caller_number": "(617) 555-0101"}),
                         "tel:+16175550101")
        self.assertEqual(tel_link({"callback_number": None, "caller_number": "unknown"}), "")

    def test_csv_safe(self):
        for risky in ["=1+1", "+1", "-1", "@SUM(A1)"]:
            self.assertTrue(csv_safe(risky).startswith("'"))
        self.assertEqual(csv_safe("Dana"), "Dana")
        self.assertEqual(csv_safe(None), "")


if __name__ == "__main__":
    unittest.main()
