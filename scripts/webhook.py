"""Sends each lead as JSON to a web address the owner chooses (LEAD_WEBHOOK_URL in .env), so Zapier, Make
or a CRM can pick it up. Without an address it does nothing. Try it for free with scripts/webhook_receiver.py."""
import hashlib
import hmac
import json
import urllib.error
import urllib.request
from datetime import datetime, timezone
from urllib.parse import urlsplit

from scripts.store import Store, ts

TIMEOUT = 10  # seconds to wait for the receiver before giving up
LEAD_KEYS = ("conversation_id", "created_at", "status", "urgency", "name", "caller_number", "callback_number",
             "problem", "address", "town", "best_time", "in_service_area", "summary", "handoff_reason")
SOURCES = {"customer": "customer", "assistant": "assistant", "fixed": "auto_message"}
LOCAL_HOSTS = ("127.0.0.1", "localhost")


def url_problem(url: str) -> str | None:
    """Why an address can't be used, or None if it's fine. Leads carry names and addresses, so only
    encrypted (https) addresses are allowed, apart from a test receiver on this PC."""
    parts = urlsplit(url)
    if parts.scheme == "https" and parts.hostname:
        return None
    if parts.scheme == "http" and parts.hostname in LOCAL_HOSTS:
        return None
    return "LEAD_WEBHOOK_URL must start with https:// (http:// is only allowed for 127.0.0.1 or localhost)"


def sign(secret: str, body: bytes) -> str:
    """The X-Signature-256 header, so the receiver can check a lead really came from this app."""
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def build_payload(lead: dict, messages: list[dict], cfg: dict, reason: str, now: datetime) -> dict:
    return {
        "event": f"lead.{reason}",  # lead.emergency, lead.complete or lead.handoff
        "business": cfg["business"]["name"],
        "sent_at": ts(now),
        "lead": {key: lead.get(key) for key in LEAD_KEYS},
        "messages": [{"from": SOURCES.get(m["source"], m["source"]), "body": m["body"]} for m in messages],
    }


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    """A redirect could quietly send the lead somewhere else (or over plain http), so it counts as a failure."""

    def redirect_request(self, *args, **kwargs):
        return None


class WebhookNotifier:
    """Posts the lead and records the result in the lead's crm_sync_status ("synced" or "failed"). It never
    counts as reaching the owner, and a failure never raises: the lead is already saved on the owner page."""

    def __init__(self, cfg: dict, env: dict[str, str], store: Store, clock=None, timeout: float = TIMEOUT):
        self.cfg = cfg
        self.url = env.get("LEAD_WEBHOOK_URL", "")
        self.secret = env.get("LEAD_WEBHOOK_SECRET", "")
        self.store = store
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.timeout = timeout
        self.problem = url_problem(self.url) if self.url else None
        self.opener = urllib.request.build_opener(_NoRedirects)

    def enabled(self) -> bool:
        return bool(self.url) and self.problem is None

    def __call__(self, lead: dict, messages: list[dict], reason: str) -> bool:
        if not self.enabled():
            return False
        now = self.clock()
        conv_id = lead["conversation_id"]
        body = json.dumps(build_payload(lead, messages, self.cfg, reason, now)).encode("utf-8")
        headers = {"Content-Type": "application/json", "User-Agent": "missed-call-text-back"}
        if self.secret:
            headers["X-Signature-256"] = sign(self.secret, body)
        request = urllib.request.Request(self.url, data=body, headers=headers, method="POST")
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                response.read(1024)
        except (OSError, ValueError) as e:  # covers HTTP errors, refused connections and timeouts
            if isinstance(e, urllib.error.HTTPError):
                e.close()
            self.store.update_lead(conv_id, now, crm_sync_status="failed")
            self.store.log_event(conv_id, "webhook_failed", now, f"{type(e).__name__}: {e}")
            return False
        self.store.update_lead(conv_id, now, crm_sync_status="synced")
        self.store.log_event(conv_id, "webhook_sent", now, reason)
        return False
