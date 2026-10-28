"""Chat with the real assistant in the terminal: you play the customer.
Uses your ANTHROPIC_API_KEY (each conversation costs well under a cent on Haiku 5.5) and saves
the lead to data/leads.db. Run from the project folder:

    .\\.venv\\Scripts\\python.exe -m scripts.try_conversation
"""
import random
import sys
from datetime import datetime, timezone

from scripts.config import load_config
from scripts.engine import Engine
from scripts.env import load_env, require
from scripts.llm import ClaudeClient
from scripts.notify import EmailNotifier
from scripts.store import Store


def show(texts: list[str]) -> None:
    for text in texts:
        print(f"\n  Assistant: {text}")


def main() -> None:
    env = load_env()
    require(env, "ANTHROPIC_API_KEY")
    cfg = load_config()
    store = Store()
    email = EmailNotifier(cfg, env)
    engine = Engine(cfg, store, ClaudeClient(cfg, env["ANTHROPIC_API_KEY"]), [email])
    # 555-0100 to 555-0199 are reserved for fiction, so these never reach a real person
    caller = sys.argv[1] if len(sys.argv) > 1 else f"(617) 555-01{random.randint(0, 99):02d}"

    print(f"Simulating a missed call from {caller} to {cfg['business']['name']}.")
    print("Type as the customer. Press Enter on an empty line to stop.")
    sent = engine.handle_missed_call(caller, datetime.now(timezone.utc))
    if not sent:
        print("No text sent: this number opted out or was texted in the last "
              f"{cfg['assistant']['dedupe_hours']} hours. Pass a different number as an argument.")
        return
    show(sent)
    conv_id = store.latest_conversation(caller)["id"]

    while store.conversation(conv_id)["status"] == "active":
        text = input("\nYou: ").strip()
        if not text:
            break
        show(engine.handle_customer_text(caller, text, datetime.now(timezone.utc)))

    conv, lead, cost = store.conversation(conv_id), store.lead(conv_id), store.conversation_cost(conv_id)
    print("\n--- Lead saved ---")
    for field in ("name", "callback_number", "problem", "address", "town", "urgency", "best_time", "in_service_area"):
        print(f"  {field}: {lead[field]}")
    print(f"  conversation status: {conv['status']}" + (f" ({conv['handoff_reason']})" if conv["handoff_reason"] else ""))
    print(f"\n--- Cost --- {cost['calls']} AI calls, {cost['input_tokens']} input + {cost['output_tokens']} output tokens"
          f" ({cost['cache_read_tokens']} read from cache): about ${cost['cost']:.4f}")
    if lead["notified_at"]:
        print("Owner email sent.")
    elif email.last_preview:
        print(f"Gmail isn't set up, so the owner email was saved here instead: {email.last_preview}")
    if lead["notified_at"] and email.last_preview:
        print(f"A copy is saved here: {email.last_preview}")


if __name__ == "__main__":
    main()
