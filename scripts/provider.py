"""Providers connect a phone company to the engine. Each one turns its own events into the engine's two
events ("missed call" and "customer text") and delivers the texts the engine returns.

SimulatedProvider is the demo's stand-in: the web page plays the caller, and "sending" a text just hands
it back to the page. A later TwilioProvider would receive Twilio's webhooks and send real texts instead,
with the engine unchanged."""
import random
from datetime import datetime, timedelta, timezone
from typing import Callable

from scripts.engine import Engine

# 555-0100 to 555-0199 are reserved for fiction, so these never reach a real person
AREA_CODES = ("617", "781", "857", "978", "508")


def fictional_numbers() -> list[str]:
    return [f"({area}) 555-01{n:02d}" for area in AREA_CODES for n in range(100)]


def is_fictional(number: str) -> bool:
    return number in set(fictional_numbers())


class SimulatedProvider:
    def __init__(self, engine: Engine, clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        self.engine = engine
        self.clock = clock

    def new_caller(self) -> str:
        """A fictional number that hasn't been texted recently, so the once-a-day rule never blocks a demo."""
        store, now = self.engine.store, self.clock()
        window = timedelta(hours=self.engine.cfg["assistant"]["dedupe_hours"])
        free = []
        for number in fictional_numbers():
            latest = store.latest_conversation(number)
            if store.is_opted_out(number):
                continue
            if latest is None or datetime.fromisoformat(latest["started_at"]) <= now - window:
                free.append(number)
        if not free:
            raise RuntimeError("Every demo number was used in the last day; try again tomorrow.")
        return random.choice(free)

    def missed_call(self, caller: str) -> list[str]:
        return self.engine.handle_missed_call(caller, self.clock())

    def incoming_text(self, caller: str, text: str) -> list[str]:
        return self.engine.handle_customer_text(caller, text, self.clock())
