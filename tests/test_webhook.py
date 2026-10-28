import json
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

from scripts.config import load_config
from scripts.engine import Engine
from scripts.store import Store
from scripts.webhook import WebhookNotifier, sign, url_problem
from scripts.webhook_receiver import make_handler, render, signature_ok
from tests.fakes import OPEN_TIME, FakeLLM, answer

CALLER = "(555) 010-0187"
MESSAGES = [{"source": "fixed", "body": "Hi, sorry we missed your call!"},
            {"source": "customer", "body": "water heater leaking"}]


class Server:
    """Runs a handler on a free port on this PC for the length of a test."""

    def __init__(self, handler):
        self.httpd = HTTPServer(("127.0.0.1", 0), handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def fixed_reply(code: int, delay: float = 0, location: str = ""):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            time.sleep(delay)
            self.send_response(code)
            if location:
                self.send_header("Location", location)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *args):
            pass

    return Handler


class WebhookTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = load_config()

    def setUp(self):
        self.store = Store(":memory:")
        self.conv_id = self.store.create_conversation(CALLER, OPEN_TIME, "")
        self.store.update_lead(self.conv_id, OPEN_TIME, name="Dana", problem="water heater leak", urgency="emergency")
        self.servers = []

    def tearDown(self):
        for server in self.servers:
            server.close()
        self.store.close()

    def serve(self, handler) -> str:
        server = Server(handler)
        self.servers.append(server)
        return server.url

    def notifier(self, url: str, secret: str = "", timeout: float = 2) -> WebhookNotifier:
        env = {"LEAD_WEBHOOK_URL": url, "LEAD_WEBHOOK_SECRET": secret}
        return WebhookNotifier(self.cfg, env, self.store, clock=lambda: OPEN_TIME, timeout=timeout)

    def lead(self) -> dict:
        return {**self.store.lead(self.conv_id), "handoff_reason": None}

    def event_types(self) -> list[str]:
        return [e["type"] for e in self.store.events(self.conv_id)]


class SendingTests(WebhookTestCase):
    def test_sends_the_lead_as_json_and_marks_it_synced(self):
        received = []
        notifier = self.notifier(self.serve(make_handler("", received)))
        self.assertFalse(notifier(self.lead(), MESSAGES, "emergency"))  # never counts as reaching the owner
        payload = received[0]["payload"]
        self.assertEqual(payload["event"], "lead.emergency")
        self.assertEqual(payload["business"], "Harbor Plumbing & Heating")
        self.assertEqual(payload["lead"]["name"], "Dana")
        self.assertEqual(payload["lead"]["conversation_id"], self.conv_id)
        self.assertEqual(payload["messages"][0], {"from": "auto_message", "body": "Hi, sorry we missed your call!"})
        self.assertEqual(self.store.lead(self.conv_id)["crm_sync_status"], "synced")
        self.assertIn("webhook_sent", self.event_types())

    def test_signed_when_a_secret_is_set(self):
        received = []
        notifier = self.notifier(self.serve(make_handler("s3cret", received)), secret="s3cret")
        notifier(self.lead(), MESSAGES, "complete")
        self.assertTrue(received and received[0]["signed"])
        self.assertEqual(self.store.lead(self.conv_id)["crm_sync_status"], "synced")

    def test_wrong_secret_is_refused_by_the_receiver(self):
        received = []
        notifier = self.notifier(self.serve(make_handler("right", received)), secret="wrong")
        notifier(self.lead(), MESSAGES, "complete")
        self.assertEqual(received, [])
        self.assertEqual(self.store.lead(self.conv_id)["crm_sync_status"], "failed")

    def test_server_error_marks_failed_without_raising(self):
        notifier = self.notifier(self.serve(fixed_reply(500)))
        self.assertFalse(notifier(self.lead(), MESSAGES, "complete"))
        self.assertEqual(self.store.lead(self.conv_id)["crm_sync_status"], "failed")
        self.assertIn("webhook_failed", self.event_types())

    def test_timeout_marks_failed(self):
        notifier = self.notifier(self.serve(fixed_reply(200, delay=1)), timeout=0.2)
        notifier(self.lead(), MESSAGES, "complete")
        self.assertEqual(self.store.lead(self.conv_id)["crm_sync_status"], "failed")

    def test_nothing_listening_marks_failed(self):
        url = self.serve(fixed_reply(200))
        self.servers.pop().close()
        self.notifier(url)(self.lead(), MESSAGES, "complete")
        self.assertEqual(self.store.lead(self.conv_id)["crm_sync_status"], "failed")

    def test_redirects_are_not_followed(self):
        received = []
        target = self.serve(make_handler("", received))
        notifier = self.notifier(self.serve(fixed_reply(307, location=target)))
        notifier(self.lead(), MESSAGES, "complete")
        self.assertEqual(received, [])
        self.assertEqual(self.store.lead(self.conv_id)["crm_sync_status"], "failed")

    def test_no_address_means_off(self):
        notifier = self.notifier("")
        self.assertFalse(notifier.enabled())
        self.assertFalse(notifier(self.lead(), MESSAGES, "complete"))
        self.assertEqual(self.store.lead(self.conv_id)["crm_sync_status"], "not_synced")
        self.assertNotIn("webhook_failed", self.event_types())


class AddressTests(unittest.TestCase):
    def test_only_https_or_this_pc(self):
        self.assertIsNone(url_problem("https://hooks.zapier.com/hooks/catch/1/abc/"))
        self.assertIsNone(url_problem("http://127.0.0.1:5051/"))
        self.assertIsNone(url_problem("http://localhost:5051/"))
        for bad in ("http://hooks.zapier.com/x", "ftp://example.com", "file:///C:/leads.json", "https://", "example.com"):
            self.assertIsNotNone(url_problem(bad), bad)

    def test_bad_address_turns_the_webhook_off(self):
        notifier = WebhookNotifier({}, {"LEAD_WEBHOOK_URL": "http://example.com/hook"}, store=None)
        self.assertFalse(notifier.enabled())
        self.assertIn("https://", notifier.problem)


class ReceiverTests(unittest.TestCase):
    def test_signature_check(self):
        body = b'{"event": "lead.complete"}'
        self.assertTrue(signature_ok("k", body, sign("k", body)))
        self.assertFalse(signature_ok("k", body, sign("other", body)))
        self.assertFalse(signature_ok("k", body, None))

    def test_page_escapes_customer_text(self):
        page = render([{"at": "10:00:00 AM", "signed": False,
                        "payload": {"event": "lead.complete", "lead": {"name": "<script>x</script>"}}}])
        self.assertNotIn("<script>x", page)
        self.assertIn("&lt;script&gt;", page)

    def test_refuses_requests_for_other_host_names(self):
        server = Server(make_handler("", []))
        try:
            request = urllib.request.Request(server.url, headers={"Host": "evil.example"})
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(request, timeout=2)
            self.assertEqual(caught.exception.code, 403)
            caught.exception.close()
        finally:
            server.close()


class EngineIntegrationTests(WebhookTestCase):
    def test_finished_conversation_reaches_the_webhook(self):
        received = []
        webhook = self.notifier(self.serve(make_handler("", received)))
        engine = Engine(self.cfg, self.store, FakeLLM(answer(status="complete", name="Sam", problem="clogged drain")),
                        [webhook])
        engine.handle_missed_call("(555) 010-0199", OPEN_TIME)
        engine.handle_customer_text("(555) 010-0199", "my kitchen drain is clogged, I'm Sam", OPEN_TIME)
        conv = self.store.latest_conversation("(555) 010-0199")
        self.assertEqual(received[0]["payload"]["event"], "lead.complete")
        self.assertEqual(received[0]["payload"]["lead"]["name"], "Sam")
        self.assertEqual(self.store.lead(conv["id"])["crm_sync_status"], "synced")
        json.dumps(received[0]["payload"])  # stays plain JSON


if __name__ == "__main__":
    unittest.main()
