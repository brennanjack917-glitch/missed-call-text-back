"""Lead emails to the owner, sent through Gmail. Without Gmail settings, the email is saved as an
HTML preview file instead, so the demo works with no accounts."""
import re
import smtplib
import ssl
from email.message import EmailMessage
from html import escape
from pathlib import Path

PREVIEW_DIR = Path(__file__).resolve().parent.parent / "output" / "email-previews"

LABELS = (("name", "Name"), ("caller_number", "Called from"), ("callback_number", "Best number"),
          ("problem", "Problem"), ("address", "Address"), ("town", "Town"),
          ("urgency", "Urgency"), ("best_time", "Best time"), ("in_service_area", "In service area"))
SPEAKERS = {"customer": "Customer", "assistant": "Assistant", "fixed": "Auto message"}


def send_email(env: dict[str, str], msg: EmailMessage) -> None:
    msg["From"] = env["GMAIL_ADDRESS"]
    msg["To"] = env.get("ALERT_TO") or env["GMAIL_ADDRESS"]
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context()) as smtp:
        smtp.login(env["GMAIL_ADDRESS"], env["GMAIL_APP_PASSWORD"].replace(" ", ""))
        smtp.send_message(msg)


def subject_for(lead: dict, cfg: dict, reason: str) -> str:
    what = lead.get("problem") or "details pending"
    where = lead.get("address") or lead["caller_number"]
    if lead.get("urgency") == "emergency":
        prefix = "🚨 EMERGENCY"
    elif reason == "handoff":
        prefix = "Needs a person"
    else:
        prefix = "New lead"
    # Customer text goes in the subject, so strip line breaks that could inject headers
    return re.sub(r"[\r\n]+", " ", f"{prefix}: {what} ({where}) | {cfg['business']['name']}")


def build_email(lead: dict, messages: list[dict], cfg: dict, reason: str) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = subject_for(lead, cfg, reason)
    rows = [(label, lead.get(key) or "not given") for key, label in LABELS]
    if reason == "handoff":
        rows.append(("Why a person is needed", (lead.get("handoff_reason") or "not given").replace("_", " ")))
    transcript = [(SPEAKERS.get(m["source"], m["source"]), m["body"]) for m in messages]

    text = "\n".join(f"{label}: {value}" for label, value in rows)
    text += "\n\nRecent messages:\n" + "\n".join(f"{who}: {body}" for who, body in transcript)
    msg.set_content(text)

    emergency = lead.get("urgency") == "emergency"
    banner = ('<div style="background:#b91c1c;color:#fff;padding:8px 12px;border-radius:8px;font-weight:700">'
              'EMERGENCY: call this customer first</div>') if emergency else ""
    table = "".join(f'<tr><td style="color:#6b7280;padding:2px 12px 2px 0">{escape(label)}</td>'
                    f'<td style="padding:2px 0">{escape(str(value))}</td></tr>' for label, value in rows)
    chat = "".join(f'<p style="margin:4px 0"><strong>{escape(who)}:</strong> {escape(body)}</p>'
                   for who, body in transcript)
    msg.add_alternative(
        f'<div style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;max-width:560px">{banner}'
        f'<table style="margin:12px 0">{table}</table>'
        f'<div style="border-top:1px solid #e3e6eb;padding-top:8px;font-size:14px">{chat}</div>'
        f'<p style="color:#9ca3af;font-size:12px">Sent by the missed-call assistant for '
        f'{escape(cfg["business"]["name"])}.</p></div>', subtype="html")
    return msg


def preview_path(conv_id: int, reason: str, preview_dir: Path = PREVIEW_DIR) -> Path:
    return preview_dir / f"lead-{conv_id}-{reason}.html"


def latest_preview(conv_id: int, preview_dir: Path = PREVIEW_DIR) -> Path | None:
    """The most recent saved email for a lead, if any."""
    files = list(preview_dir.glob(f"lead-{int(conv_id)}-*.html")) if preview_dir.exists() else []
    return max(files, key=lambda p: p.stat().st_mtime_ns) if files else None


class EmailNotifier:
    """Saves every owner email as a preview file, and also sends it through Gmail when Gmail is set up
    and sending is switched on. The web demo starts with sending off, so test chats don't fill your inbox."""

    def __init__(self, cfg: dict, env: dict[str, str], preview_dir: Path = PREVIEW_DIR, send: bool = True):
        self.cfg = cfg
        self.env = env
        self.preview_dir = preview_dir
        self.send = send
        self.last_preview: Path | None = None

    def gmail_ready(self) -> bool:
        return bool(self.env.get("GMAIL_ADDRESS") and self.env.get("GMAIL_APP_PASSWORD"))

    def __call__(self, lead: dict, messages: list[dict], reason: str) -> bool:
        msg = build_email(lead, messages, self.cfg, reason)
        self.preview_dir.mkdir(parents=True, exist_ok=True)
        path = preview_path(lead["conversation_id"], reason, self.preview_dir)
        path.write_text(msg.get_body(("html",)).get_content(), encoding="utf-8")
        self.last_preview = path
        if self.send and self.gmail_ready():
            send_email(self.env, msg)
            return True
        return False
