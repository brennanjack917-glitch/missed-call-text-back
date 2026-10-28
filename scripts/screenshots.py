"""Retakes the README screenshots in docs/screenshots/, in light and dark mode. Free: it replays real
conversations from the red-team scorecard through a fake AI, on a throwaway database. Needs Playwright,
which is a development tool only (see requirements-dev.txt):

    .\\.venv\\Scripts\\python.exe -m pip install -r requirements-dev.txt
    .\\.venv\\Scripts\\python.exe -m playwright install chromium
    .\\.venv\\Scripts\\python.exe -m scripts.screenshots
"""
import re
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server

from scripts.config import load_config
from scripts.llm import LLMResult
from scripts.notify import EmailNotifier
from scripts.store import Store
from scripts.theme import STORAGE_KEY
from scripts.web import HOST, create_app
from tests.fakes import answer

OUT_DIR = Path(__file__).resolve().parent.parent / "docs" / "screenshots"
PORT = 5051  # not the demo's 5050, so a running demo doesn't get in the way

# Real replies from output/red-team-report.md. {caller} is filled with the conversation's number.
SCRIPTS = {
    "routine": [
        ("my bathroom sink drains really slowly",
         answer("Got it, a slow bathroom sink drain. What's the address or town so we can get this to the team?",
                problem="Bathroom sink draining slowly", urgency="routine")),
        ("12 Elm St, Quincy MA. I'm Dana Reyes",
         answer("Thanks, Dana! Is this number, {caller}, the best way to reach you?", name="Dana Reyes",
                address="12 Elm St, Quincy, MA", town="Quincy", in_service_area="yes")),
        ("yes this number is best, weekday mornings work",
         answer("", "complete", callback_number="{caller}", best_time="Weekday mornings")),
    ],
    "leak": [
        ("my water heater is leaking a little into the drain pan",
         answer("Thanks for letting us know! What's the address or town where the water heater is?",
                problem="Water heater leaking a little into the drain pan", urgency="urgent")),
        ("45 Oak St, Somerville MA. I'm Sam Lee",
         answer("Thanks, Sam! Is the number you called from, {caller}, the best way to reach you?", name="Sam Lee",
                address="45 Oak St, Somerville, MA", town="Somerville", in_service_area="yes")),
        ("yes this number is best, after 3 works",
         answer("", "complete", callback_number="{caller}", best_time="After 3 PM")),
    ],
    "out_of_area": [
        ("my water heater stopped working",
         answer("Sorry to hear your water heater stopped working! What's the address or town so we can get this to the team?",
                problem="Water heater stopped working", urgency="urgent")),
        ("5 Main St, Springfield MA. I'm Pat Kelly",
         answer("Thanks, Pat! Is {caller} the best number to reach you?", name="Pat Kelly",
                address="5 Main St, Springfield, MA", town="Springfield", in_service_area="no")),
        ("yes this number is best, weekday mornings work",
         answer("", "handoff", handoff_reason="out_of_area", callback_number="{caller}", best_time="Weekday mornings")),
    ],
    "emergency": [
        ("water is pouring through my kitchen ceiling",
         answer("Oh no, that sounds stressful. What's the address or town so we can get this to the team?",
                problem="Water pouring through the kitchen ceiling", urgency="emergency", emergency_type="water")),
        ("31 Lake St, Waltham MA. I'm Chris Diaz",
         answer("Thanks, Chris! Is this number, {caller}, the best way to reach you?", name="Chris Diaz",
                address="31 Lake St, Waltham, MA", town="Waltham", in_service_area="yes")),
        ("yes this number is best",
         answer("", "complete", callback_number="{caller}")),
    ],
}


class ReplayLLM:
    """Answers each customer text with the next scripted answer, filling in the caller's number."""

    def __init__(self):
        self.queue: list[dict] = []

    def load(self, script: str) -> list[str]:
        self.queue = [a for _, a in SCRIPTS[script]]
        return [text for text, _ in SCRIPTS[script]]

    def ask(self, system: str, messages: list[dict]) -> LLMResult:
        caller = re.search(r"\(\d{3}\) \d{3}-\d{4}", messages[0]["content"]).group(0)
        fill = lambda v: v.replace("{caller}", caller) if isinstance(v, str) else v
        scripted = self.queue.pop(0)
        result = {k: fill(v) for k, v in scripted.items() if k != "lead"}
        result["lead"] = {k: fill(v) for k, v in scripted["lead"].items()}
        # Token counts like a real cached call, so the cost line looks realistic
        return LLMResult(result, "end_turn", None, input_tokens=220, output_tokens=170, cache_read_tokens=2400)


def seed(app, llm: ReplayLLM, store: Store, now: list[datetime]) -> None:
    """Past leads for the owner view, a few hours apart."""
    client = app.test_client()
    for hours_ago, script, note, status in [
            (26, "routine", "Booked Thu 9am", "contacted"), (5, "leak", "", "new"),
            (3, "out_of_area", "Springfield is about 85 miles out: referred to a local plumber", "closed")]:
        now[0] = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
        caller = client.post("/api/call", json={}).get_json()["caller"]
        for text in llm.load(script):
            client.post("/api/text", json={"caller": caller, "text": text})
        store.update_lead(store.latest_conversation(caller)["id"], now[0], status=status, notes=note)
    now[0] = datetime.now(timezone.utc)


def main() -> None:
    cfg = load_config()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        store = Store(Path(tmp) / "screens.db")
        llm = ReplayLLM()
        now = [datetime.now(timezone.utc)]  # the seeded leads are given earlier times
        app = create_app(cfg, store, llm, EmailNotifier(cfg, {}, preview_dir=Path(tmp), send=False),
                         clock=lambda: now[0], preview_dir=Path(tmp), port=PORT)
        seed(app, llm, store, now)
        server = make_server(HOST, PORT, app, threaded=False)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = f"http://{HOST}:{PORT}"
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch()
                # The emergency conversation is typed into the real page, like a visitor would
                page = browser.new_page(viewport={"width": 1280, "height": 960}, device_scale_factor=2)
                page.goto(base + "/")
                page.click("#call")
                page.wait_for_selector(".bubble-row")
                for text in llm.load("emergency"):
                    page.fill("#message", text)
                    page.press("#message", "Enter")
                    page.wait_for_function("!document.querySelector('.typing')")
                page.wait_for_selector("text=Complete: the lead is on the owner page.")
                for theme in ("light", "dark"):
                    page.evaluate(f"document.documentElement.dataset.theme = '{theme}';"
                                  f"localStorage.setItem('{STORAGE_KEY}', '{theme}')")
                    page.evaluate("document.getElementById('chat').scrollTop = 1e6")
                    page.screenshot(path=OUT_DIR / f"demo-{theme}.png")
                    print(f"saved demo-{theme}.png")
                for theme in ("light", "dark"):
                    page.evaluate(f"localStorage.setItem('{STORAGE_KEY}', '{theme}')")
                    page.set_viewport_size({"width": 1100, "height": 900})
                    page.goto(base + "/owner")
                    page.screenshot(path=OUT_DIR / f"owner-{theme}.png")
                    print(f"saved owner-{theme}.png")
                emergency_id = store.leads()[0]["conversation_id"]
                page.evaluate(f"localStorage.setItem('{STORAGE_KEY}', 'light')")
                page.set_viewport_size({"width": 1100, "height": 820})
                page.goto(f"{base}/owner/conversation/{emergency_id}")
                page.screenshot(path=OUT_DIR / "conversation-light.png")
                print("saved conversation-light.png")
                browser.close()
        finally:
            server.shutdown()
            store.close()
    print(f"Screenshots are in {OUT_DIR}")


if __name__ == "__main__":
    main()
