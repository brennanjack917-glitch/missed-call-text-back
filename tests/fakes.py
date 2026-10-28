"""Test helpers: a fake Claude that returns scripted answers, so tests never make paid API calls."""
from datetime import datetime, timezone

from scripts.llm import LLMResult

# Tuesday 2026-10-27, 10:00 AM in New York (office open)
OPEN_TIME = datetime(2026, 10, 27, 14, 0, tzinfo=timezone.utc)
# Tuesday 2026-10-27, 9:42 PM in New York (office closed)
CLOSED_TIME = datetime(2026, 10, 28, 1, 42, tzinfo=timezone.utc)


def answer(reply: str = "Got it. What's the address or town?", status: str = "collecting", **lead_and_flags) -> dict:
    """A well-formed model answer; keyword arguments override lead fields or flags."""
    lead = {"name": None, "problem": None, "address": None, "town": None, "callback_number": None,
            "urgency": "unknown", "best_time": None}
    flags = {"handoff_reason": "none", "emergency_type": "none", "in_service_area": "unclear"}
    for key, value in lead_and_flags.items():
        (lead if key in lead else flags)[key] = value
    return {"reply": reply, "lead": lead, "status": status, **flags}


class FakeLLM:
    """Returns queued results in order and remembers what it was asked."""

    def __init__(self, *results):
        self.results = list(results)
        self.calls: list[tuple[str, list[dict]]] = []

    def ask(self, system: str, messages: list[dict]) -> LLMResult:
        self.calls.append((system, [dict(m) for m in messages]))
        result = self.results.pop(0)
        if isinstance(result, LLMResult):
            return result
        return LLMResult(result, "end_turn", None, input_tokens=1000, output_tokens=100)


class RecordingNotifier:
    def __init__(self, returns: bool = True, fail: bool = False):
        self.calls: list[tuple[dict, list[dict], str]] = []
        self.returns = returns
        self.fail = fail

    def __call__(self, lead: dict, messages: list[dict], reason: str) -> bool:
        self.calls.append((lead, messages, reason))
        if self.fail:
            raise RuntimeError("smtp down")
        return self.returns
