"""The only module that talks to Claude. Tests swap in a fake with the same ask() method,
so no test ever makes a paid API call."""
import json
from dataclasses import dataclass
from pathlib import Path

import anthropic

from scripts.config import fill, hours_text
from scripts.guard import LEAD_FIELDS, URGENCIES

RECIPE_PATH = Path(__file__).resolve().parent.parent / "workflow" / "conversation-recipe.md"

STATUSES = ("collecting", "complete", "handoff")
HANDOFF_REASONS = ("none", "customer_requests_person", "angry", "out_of_area", "out_of_scope", "unsure", "other")
EMERGENCY_ANSWERS = ("none", "gas", "carbon_monoxide", "fire", "water", "electrical", "other")
SERVICE_AREA = ("yes", "no", "unclear")

_NULLABLE_TEXT = {"anyOf": [{"type": "string"}, {"type": "null"}]}

# Shape every answer must have. Structured outputs enforce it; lengths are checked by the guard instead,
# because the schema can't express length limits.
ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "reply": {"type": "string"},
        "lead": {
            "type": "object",
            "properties": {field: ({"type": "string", "enum": list(URGENCIES)} if field == "urgency" else _NULLABLE_TEXT)
                           for field in LEAD_FIELDS},
            "required": list(LEAD_FIELDS),
            "additionalProperties": False,
        },
        "status": {"type": "string", "enum": list(STATUSES)},
        "handoff_reason": {"type": "string", "enum": list(HANDOFF_REASONS)},
        "emergency_type": {"type": "string", "enum": list(EMERGENCY_ANSWERS)},
        "in_service_area": {"type": "string", "enum": list(SERVICE_AREA)},
    },
    "required": ["reply", "lead", "status", "handoff_reason", "emergency_type", "in_service_area"],
    "additionalProperties": False,
}


@dataclass
class LLMResult:
    answer: dict | None
    stop_reason: str | None = None
    error: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


def build_system_prompt(cfg: dict, recipe_path: Path = RECIPE_PATH) -> str:
    """The conversation recipe from '## Role' onward, with the business settings filled in."""
    text = recipe_path.read_text(encoding="utf-8")
    text = text[text.index("\n## Role") + 1:]  # the heading line, not a mention of it in the intro
    return fill(text, cfg,
                services_offered="; ".join(cfg["services"]["offered"]),
                services_not_offered="; ".join(cfg["services"]["not_offered"]),
                center=cfg["service_area"]["center"],
                radius_miles=str(cfg["service_area"]["radius_miles"]),
                examples_inside=", ".join(cfg["service_area"]["examples_inside"]),
                examples_outside=", ".join(cfg["service_area"]["examples_outside"]),
                hours=hours_text(cfg),
                max_reply_chars=str(cfg["assistant"]["max_reply_chars"]))


def _pick(value, allowed: tuple[str, ...]) -> str | None:
    """Enum values compared case-insensitively (capitalization isn't guaranteed)."""
    value = str(value).strip().lower() if value is not None else ""
    return value if value in allowed else None


def validate_answer(data) -> dict | None:
    """A cleaned-up copy of the model's answer, or None if it doesn't have the expected shape."""
    if not isinstance(data, dict) or not isinstance(data.get("lead"), dict) or not isinstance(data.get("reply"), str):
        return None
    lead = {f: data["lead"].get(f) if isinstance(data["lead"].get(f), str) else None for f in LEAD_FIELDS}
    lead["urgency"] = _pick(lead["urgency"], URGENCIES) or "unknown"
    answer = {
        "reply": data["reply"].strip(),
        "lead": lead,
        "status": _pick(data.get("status"), STATUSES),
        "handoff_reason": _pick(data.get("handoff_reason"), HANDOFF_REASONS) or "other",
        "emergency_type": _pick(data.get("emergency_type"), EMERGENCY_ANSWERS) or "none",
        "in_service_area": _pick(data.get("in_service_area"), SERVICE_AREA) or "unclear",
    }
    return answer if answer["status"] else None


class ClaudeClient:
    def __init__(self, cfg: dict, api_key: str | None = None, client=None):
        self.cfg = cfg
        self.client = client or anthropic.Anthropic(api_key=api_key, max_retries=2, timeout=30.0)

    def ask(self, system: str, messages: list[dict]) -> LLMResult:
        settings = self.cfg["assistant"]
        try:
            response = self.client.messages.create(
                model=settings["model"],
                max_tokens=settings["max_tokens"],
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                messages=messages,
                output_config={"effort": settings["effort"],
                               "format": {"type": "json_schema", "schema": ANSWER_SCHEMA}},
            )
        except anthropic.APIError as e:
            return LLMResult(None, error=f"{type(e).__name__}: {e}")

        usage = response.usage
        tokens = dict(input_tokens=usage.input_tokens or 0, output_tokens=usage.output_tokens or 0,
                      cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
                      cache_write_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0)
        # A refusal or a cut-off reply can break the schema, so only a normal finish is trusted
        if response.stop_reason != "end_turn":
            return LLMResult(None, response.stop_reason, f"stopped: {response.stop_reason}", **tokens)
        text = next((block.text for block in response.content if block.type == "text"), "")
        try:
            answer = validate_answer(json.loads(text))
        except ValueError:
            answer = None
        if answer is None:
            return LLMResult(None, response.stop_reason, "answer did not match the expected shape", **tokens)
        return LLMResult(answer, response.stop_reason, None, **tokens)


def estimate_cost(cfg: dict, result: LLMResult) -> float:
    prices = cfg["assistant"]["prices"]
    return (result.input_tokens * prices["input"] + result.output_tokens * prices["output"]
            + result.cache_read_tokens * prices["cache_read"]
            + result.cache_write_tokens * prices["cache_write"]) / 1_000_000
