"""The demo web server: a phone-style chat where you play the customer, and the owner's lead view.
Runs only on this PC. From the project folder:

    .\\.venv\\Scripts\\python.exe -m scripts.web

then open http://127.0.0.1:5050. Each customer message is one real Claude call (about $0.0002 on Haiku 5.5).
"""
import csv
import io
import logging
import os
import re
from datetime import datetime

from flask import Flask, Response, abort, jsonify, render_template, request, url_for
from werkzeug.exceptions import HTTPException

from scripts import theme
from scripts.config import load_config, local_time, office_open
from scripts.engine import Engine
from scripts.notify import PREVIEW_DIR, EmailNotifier, latest_preview
from scripts.provider import SimulatedProvider, is_fictional
from scripts.store import LEAD_STATUSES, Store

HOST, PORT = "127.0.0.1", 5050
MAX_TEXT = 1000  # characters per customer message
MAX_NOTES = 2000
URGENCY_FILTERS = ("emergency", "urgent", "routine", "unknown")
CARD_FIELDS = (("name", "Name"), ("callback_number", "Best number"), ("problem", "Problem"), ("address", "Address"),
               ("town", "Town"), ("urgency", "Urgency"), ("best_time", "Best time"), ("in_service_area", "In service area"))
CSV_FIELDS = ("conversation_id", "created_at", "status", "urgency", "name", "caller_number", "callback_number",
              "problem", "address", "town", "best_time", "in_service_area", "notes", "notified_at")
SOURCES = {"customer": "Customer", "assistant": "Written by the AI", "fixed": "Pre-written message"}
HANDOFF_REASONS = {"out_of_area": "outside the service area", "out_of_scope": "not a job we usually take",
                   "customer_requests_person": "customer asked for a person", "angry": "customer is upset",
                   "unsure": "the AI wasn't sure", "reply_blocked": "the code blocked the AI's reply",
                   "ai_unavailable": "the AI couldn't be reached", "message_cap": "conversation got too long",
                   "daily_budget": "the daily AI spending cap was reached"}
LOG_PATH = PREVIEW_DIR.parent / "logs" / "web.log"


def describe_event(event: dict) -> str | None:
    """A plain-English line for the 'behind the scenes' panel, or None for routine bookkeeping."""
    kind, detail = event["type"], event["detail"]
    reason = HANDOFF_REASONS.get(detail, detail.replace("_", " "))
    lines = {
        "missed_call": "Missed call detected. The greeting is a pre-written message.",
        "emergency_keyword": f"Code spotted emergency words ({detail.replace('_', ' ')}) and sent the pre-written "
                             "safety message before the AI's reply.",
        "emergency_ai": f"The AI judged this an emergency ({detail.replace('_', ' ')}); code sent the pre-written "
                        "safety message.",
        "reply_trimmed": f"Code removed a sentence from the AI's reply before sending it: “{detail}”",
        "guard_blocked": "Code blocked the AI's reply (" + detail.split(":")[0].replace("_", " ").replace(",", ", ")
                         + ") and passed the customer to a person.",
        "api_error": "The AI couldn't be reached, so a pre-written hand-off message was sent.",
        "handoff": f"Handed off to a person: {reason}.",
        "opt_out": "Code detected an opt-out. No more texts will be sent to this number.",
        "text_after_opt_out": "Message received after opting out: no reply sent.",
        "late_reply": "Message after the lead was finished: a pre-written acknowledgement was sent.",
        "owner_alert": f"Lead sent to the owner ({detail}).",
        "owner_notified": "Owner emailed through Gmail.",
        "notify_failed": "The owner email failed; the lead is still saved on the owner page.",
        "budget_reached": "The daily AI spending cap was reached, so the AI was skipped and a person will follow up.",
        "duplicate_ignored": "The same text arrived twice; the copy was ignored.",
        "person_requested": "Code noticed the customer asked for a person: after their next reply, a person takes over.",
    }
    return lines.get(kind)


def tel_link(lead: dict) -> str:
    """A tap-to-call link for the best number, falling back to the number they called from."""
    for number in (lead.get("callback_number"), lead.get("caller_number")):
        digits = re.sub(r"\D", "", number or "")
        if len(digits) == 10:
            return f"tel:+1{digits}"
        if len(digits) == 11 and digits.startswith("1"):
            return f"tel:+{digits}"
    return ""


def csv_safe(value) -> str:
    """Stops a spreadsheet from treating customer text like '=HYPERLINK(...)' as a formula."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def create_app(cfg: dict, store: Store, llm, email: EmailNotifier, clock=None, preview_dir=PREVIEW_DIR,
               port: int = PORT) -> Flask:
    engine = Engine(cfg, store, llm, [email])
    provider = SimulatedProvider(engine, clock) if clock else SimulatedProvider(engine)
    app = Flask(__name__)
    app.config["TEMPLATES_AUTO_RELOAD"] = True  # page edits show on refresh, without restarting
    allowed_hosts = {f"{HOST}:{port}", f"localhost:{port}", "localhost"}  # "localhost" = Flask's test client

    @app.context_processor
    def page_basics():
        return {"business": cfg["business"], "theme": theme}

    @app.template_filter("local")
    def local(stamp: str) -> str:
        """A saved timestamp in the business's time zone, e.g. "Oct 27, 9:42 PM"."""
        when = local_time(cfg, datetime.fromisoformat(stamp))
        return f"{when:%b} {when.day}, {when:%I:%M %p}".replace(" 0", " ")

    @app.before_request
    def local_requests_only():
        # Blocks other websites from driving this server through your browser (DNS rebinding and forged
        # form posts): only pages served from here, sending JSON, can make changes.
        if request.host not in allowed_hosts:
            abort(403)
        if request.method == "POST" and not request.is_json:
            abort(415)

    @app.errorhandler(Exception)
    def unexpected_error(error):
        """Anything unexpected is written to the log; the page gets a short, friendly message."""
        if isinstance(error, HTTPException):
            return error
        app.logger.exception("Unexpected error on %s %s", request.method, request.path)
        if request.path.startswith("/api/"):
            return jsonify({"error": "Something went wrong on our side. The details are in output/logs/web.log."}), 500
        return "Something went wrong on our side. The details are in output/logs/web.log.", 500

    def body() -> dict:
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            abort(400)
        return data

    def caller_from(data_or_args) -> str:
        caller = str(data_or_args.get("caller", ""))
        if not is_fictional(caller):
            abort(400)
        return caller

    def state(caller: str) -> dict:
        conv = store.latest_conversation(caller)
        if conv is None:
            return {"caller": caller, "conversation": None}
        lead = store.lead(conv["id"])
        cost = store.conversation_cost(conv["id"])
        events = [line for line in (describe_event(e) for e in store.events(conv["id"])) if line]
        return {
            "caller": caller,
            "conversation": {"id": conv["id"], "status": conv["status"],
                             "handoff_reason": HANDOFF_REASONS.get(conv["handoff_reason"] or "", conv["handoff_reason"])},
            "messages": [{"from": "customer" if m["direction"] == "in" else m["source"], "body": m["body"]}
                         for m in store.messages(conv["id"])],
            "lead": {key: lead.get(key) for key, _ in CARD_FIELDS},
            "events": events,
            "cost": {"calls": cost["calls"], "dollars": round(cost["cost"], 5)},
            "email_preview": url_for("email_preview", conv_id=conv["id"])
                             if latest_preview(conv["id"], preview_dir) else None,
        }

    # Demo page

    @app.get("/")
    def demo():
        return render_template("demo.html", card_fields=CARD_FIELDS, sources=SOURCES,
                               office_open=office_open(cfg, provider.clock()),
                               gmail_ready=email.gmail_ready(), send_email=email.send)

    @app.post("/api/call")
    def api_call():
        body()
        caller = provider.new_caller()
        provider.missed_call(caller)
        return jsonify(state(caller))

    @app.post("/api/text")
    def api_text():
        data = body()
        caller = caller_from(data)
        text = str(data.get("text", "")).strip()
        if not text or len(text) > MAX_TEXT:
            return jsonify({"error": f"Messages must be 1 to {MAX_TEXT} characters."}), 400
        if store.latest_conversation(caller) is None:
            abort(404)
        provider.incoming_text(caller, text)
        return jsonify(state(caller))

    @app.get("/api/state")
    def api_state():
        return jsonify(state(caller_from(request.args)))

    @app.post("/api/settings")
    def api_settings():
        data = body()
        if "send_email" in data:
            email.send = bool(data["send_email"]) and email.gmail_ready()
        return jsonify({"send_email": email.send})

    # Owner view

    @app.get("/owner")
    def owner():
        status = request.args.get("status", "")
        urgency = request.args.get("urgency", "")
        query = request.args.get("q", "")[:100]
        leads = store.leads(status=status if status in LEAD_STATUSES else None,
                            urgency=urgency if urgency in URGENCY_FILTERS else None, query=query)
        for lead in leads:
            lead["tel"] = tel_link(lead)
            lead["handoff_reason"] = store.conversation(lead["conversation_id"])["handoff_reason"]
            lead["handoff_text"] = HANDOFF_REASONS.get(lead["handoff_reason"] or "", lead["handoff_reason"])
            lead["has_email"] = latest_preview(lead["conversation_id"], preview_dir) is not None
        return render_template("owner.html", leads=leads, counts=store.lead_counts(), statuses=LEAD_STATUSES,
                               urgencies=URGENCY_FILTERS, status=status, urgency=urgency, query=query)

    @app.post("/api/leads/<int:conv_id>")
    def api_update_lead(conv_id: int):
        data = body()
        if not store.db.execute("SELECT 1 FROM leads WHERE conversation_id = ?", (conv_id,)).fetchone():
            abort(404)
        changes = {}
        if "status" in data:
            if data["status"] not in LEAD_STATUSES:
                abort(400)
            changes["status"] = data["status"]
        if "notes" in data:
            changes["notes"] = str(data["notes"])[:MAX_NOTES]
        if not changes:
            abort(400)
        store.update_lead(conv_id, provider.clock(), **changes)
        return jsonify({"ok": True, "counts": store.lead_counts()})

    @app.get("/owner/conversation/<int:conv_id>")
    def conversation(conv_id: int):
        if not store.db.execute("SELECT 1 FROM conversations WHERE id = ?", (conv_id,)).fetchone():
            abort(404)
        lead = store.lead(conv_id)
        events = [line for line in (describe_event(e) for e in store.events(conv_id)) if line]
        return render_template("conversation.html", lead=lead, messages=store.messages(conv_id), sources=SOURCES,
                               events=events, card_fields=CARD_FIELDS, tel=tel_link(lead))

    @app.get("/owner/email/<int:conv_id>")
    def email_preview(conv_id: int):
        path = latest_preview(conv_id, preview_dir)
        if path is None:
            abort(404)
        return Response(path.read_text(encoding="utf-8"), mimetype="text/html")

    @app.post("/api/clear")
    def api_clear():
        if body().get("confirm") is not True:
            abort(400)
        store.clear_all()
        for path in preview_dir.glob("lead-*.html") if preview_dir.exists() else []:
            path.unlink()
        return jsonify({"ok": True})

    @app.get("/owner/leads.csv")
    def export_csv():
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(CSV_FIELDS)
        for lead in store.leads():
            writer.writerow([csv_safe(lead.get(f)) for f in CSV_FIELDS])
        stamp = provider.clock().strftime("%Y-%m-%d")
        # The byte-order mark makes Excel read accented names correctly
        return Response("﻿" + out.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="leads-{stamp}.csv"'})

    return app


def main() -> None:
    from scripts.env import load_env, require
    from scripts.llm import ClaudeClient

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=LOG_PATH, level=logging.WARNING, encoding="utf-8",
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    env = load_env()
    require(env, "ANTHROPIC_API_KEY")
    cfg = load_config()
    # Real emails start switched off; the demo page has a switch to turn them on
    email = EmailNotifier(cfg, env, send=False)
    app = create_app(cfg, Store(), ClaudeClient(cfg, env["ANTHROPIC_API_KEY"]), email)
    print(f"Demo running at http://{HOST}:{PORT}  (owner view: http://{HOST}:{PORT}/owner)")
    print("Press Ctrl+C to stop.")
    os.environ.setdefault("FLASK_SKIP_DOTENV", "1")  # our own scripts/env.py reads .env
    # One request at a time keeps the shared database connection simple; fine for a one-person demo
    app.run(host=HOST, port=PORT, debug=False, threaded=False)


if __name__ == "__main__":
    main()
