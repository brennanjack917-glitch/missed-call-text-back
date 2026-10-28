"""A free stand-in for Zapier or a CRM: receives the leads the demo sends and shows them on a page.
In .env set LEAD_WEBHOOK_URL=http://127.0.0.1:5051/ (LEAD_WEBHOOK_SECRET is optional), then run this in a
second terminal next to the demo:

    .\\.venv\\Scripts\\python.exe -m scripts.webhook_receiver

and open http://127.0.0.1:5051. Leads are kept in memory only, so they're gone when it stops.
"""
import hmac
import json
from datetime import datetime
from html import escape
from http.server import BaseHTTPRequestHandler, HTTPServer

from scripts.webhook import sign

HOST, PORT = "127.0.0.1", 5051
MAX_BODY = 1_000_000  # bytes
KEEP = 20  # most recent leads shown


def signature_ok(secret: str, body: bytes, header: str | None) -> bool:
    return hmac.compare_digest(sign(secret, body), header or "")


def render(received: list[dict]) -> str:
    items = []
    for item in received:
        lead = item["payload"].get("lead") or {}
        title = f"{lead.get('name') or 'Name not given'}: {lead.get('problem') or 'problem not given'}"
        items.append(
            f'<article><p><strong>{escape(str(item["payload"].get("event")))}</strong> · {escape(item["at"])}'
            f' · {"signature checked" if item["signed"] else "not signed"}</p><h2>{escape(title)}</h2>'
            f'<pre>{escape(json.dumps(item["payload"], indent=2))}</pre></article>')
    body = "".join(items) or "<p>No leads yet. Finish a conversation on the demo page and it shows up here.</p>"
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta http-equiv="refresh" content="3">'
            '<meta name="viewport" content="width=device-width, initial-scale=1"><title>Webhook test receiver</title>'
            '<style>body{font-family:-apple-system,Segoe UI,Roboto,sans-serif;max-width:760px;margin:24px auto;'
            'padding:0 16px;background:#fff;color:#111}article{border:1px solid #e3e6eb;border-radius:8px;'
            'padding:4px 16px;margin:12px 0}pre{overflow-x:auto;font-size:12px}h2{font-size:16px}'
            '@media (prefers-color-scheme:dark){body{background:#111;color:#eee}article{border-color:#333}}</style>'
            '</head><body><h1>Webhook test receiver</h1><p>Leads the demo sent here, newest first. '
            'The page refreshes every 3 seconds.</p>' + body + '</body></html>')


def make_handler(secret: str, received: list[dict], log=None):
    class Handler(BaseHTTPRequestHandler):
        def local_only(self) -> bool:
            """Like the demo server: refuses requests that other websites route here through your browser."""
            port = self.server.server_address[1]
            if self.headers.get("Host") in (f"{HOST}:{port}", f"localhost:{port}"):
                return True
            self.reply(403, "Forbidden")
            return False

        def do_POST(self):
            if not self.local_only():
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = 0
            if not 0 < length <= MAX_BODY:
                return self.reply(400, "Missing or oversized body")
            body = self.rfile.read(length)
            if secret and not signature_ok(secret, body, self.headers.get("X-Signature-256")):
                return self.reply(401, "Signature does not match LEAD_WEBHOOK_SECRET")
            try:
                payload = json.loads(body)
            except ValueError:
                return self.reply(400, "Not JSON")
            if not isinstance(payload, dict):
                return self.reply(400, "Expected a JSON object")
            received.insert(0, {"at": datetime.now().strftime("%I:%M:%S %p"), "signed": bool(secret), "payload": payload})
            del received[KEEP:]
            if log:
                log(f"Received {payload.get('event')} for lead {(payload.get('lead') or {}).get('conversation_id')}")
            self.reply(200, "ok")

        def do_GET(self):
            if not self.local_only():
                return
            if self.path != "/":
                return self.reply(404, "Not found")
            self.reply(200, render(received), "text/html; charset=utf-8")

        def reply(self, code: int, text: str, content_type: str = "text/plain; charset=utf-8"):
            data = text.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):  # the one line per lead above is enough
            pass

    return Handler


def main() -> None:
    from scripts.env import load_env

    secret = load_env().get("LEAD_WEBHOOK_SECRET", "")
    server = HTTPServer((HOST, PORT), make_handler(secret, [], log=print))
    print(f"Webhook test receiver at http://{HOST}:{PORT}  (signature check {'on' if secret else 'off'})")
    print(f"Set LEAD_WEBHOOK_URL=http://{HOST}:{PORT}/ in .env and restart the demo. Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
