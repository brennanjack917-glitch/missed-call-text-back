import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.config import load_config
from scripts.notify import EmailNotifier, build_email, latest_preview

LEAD = {"conversation_id": 7, "caller_number": "(555) 010-0187", "name": "<b>Dana</b>", "problem": "water heater leak",
        "address": "12 Elm St, Millbrook", "urgency": "emergency", "best_time": "now", "in_service_area": "yes",
        "handoff_reason": None}
MESSAGES = [{"source": "fixed", "body": "Hi, sorry we missed your call!"},
            {"source": "customer", "body": "<script>alert(1)</script> leaking everywhere"}]


class EmailTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = load_config()

    def test_emergency_subject_and_escaped_html(self):
        msg = build_email(LEAD, MESSAGES, self.cfg, "emergency")
        self.assertTrue(msg["Subject"].startswith("🚨 EMERGENCY: water heater leak (12 Elm St, Millbrook)"))
        html = msg.get_body(("html",)).get_content()
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("&lt;b&gt;Dana&lt;/b&gt;", html)
        self.assertIn("call this customer first", html)

    def test_handoff_email_explains_why(self):
        lead = {**LEAD, "urgency": "routine", "handoff_reason": "customer_requests_person"}
        msg = build_email(lead, MESSAGES, self.cfg, "handoff")
        self.assertTrue(msg["Subject"].startswith("Needs a person:"))
        self.assertIn("customer requests person", msg.get_body(("plain",)).get_content())

    def test_line_breaks_in_customer_text_cannot_inject_headers(self):
        lead = {**LEAD, "problem": "leak\r\nBcc: attacker@example.com"}
        self.assertNotIn("\n", build_email(lead, MESSAGES, self.cfg, "complete")["Subject"])

    def test_without_gmail_settings_saves_a_preview_and_reports_not_emailed(self):
        with tempfile.TemporaryDirectory() as d:
            notifier = EmailNotifier(self.cfg, {}, preview_dir=Path(d))
            self.assertFalse(notifier(LEAD, MESSAGES, "emergency"))
            self.assertTrue(notifier.last_preview.exists())
            self.assertIn("EMERGENCY", notifier.last_preview.read_text(encoding="utf-8"))
            self.assertEqual(latest_preview(7, Path(d)), notifier.last_preview)
            self.assertIsNone(latest_preview(8, Path(d)))

    def test_sending_switched_off_only_saves_a_preview(self):
        gmail = {"GMAIL_ADDRESS": "owner@example.com", "GMAIL_APP_PASSWORD": "x"}
        with tempfile.TemporaryDirectory() as d, mock.patch("scripts.notify.send_email") as send:
            notifier = EmailNotifier(self.cfg, gmail, preview_dir=Path(d), send=False)
            self.assertFalse(notifier(LEAD, MESSAGES, "complete"))
            send.assert_not_called()
            notifier.send = True
            self.assertTrue(notifier(LEAD, MESSAGES, "complete"))
            send.assert_called_once()
            self.assertTrue(notifier.last_preview.exists())  # a copy is kept either way


if __name__ == "__main__":
    unittest.main()
