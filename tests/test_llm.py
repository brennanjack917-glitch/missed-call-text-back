import json
import re
import unittest
from types import SimpleNamespace

import anthropic

from scripts.config import load_config
from scripts.llm import ANSWER_SCHEMA, ClaudeClient, LLMResult, build_system_prompt, estimate_cost, validate_answer
from tests.fakes import answer


def fake_response(text: str, stop_reason: str = "end_turn"):
    usage = SimpleNamespace(input_tokens=1200, output_tokens=150, cache_read_input_tokens=1000,
                            cache_creation_input_tokens=0)
    content = [SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=text)]
    return SimpleNamespace(content=content, stop_reason=stop_reason, usage=usage)


class FakeMessages:
    def __init__(self, response=None, error=None):
        self.response, self.error, self.kwargs = response, error, None

    def create(self, **kwargs):
        self.kwargs = kwargs
        if self.error:
            raise self.error
        return self.response


def client_with(messages: FakeMessages, cfg) -> ClaudeClient:
    return ClaudeClient(cfg, client=SimpleNamespace(messages=messages))


class SystemPromptTests(unittest.TestCase):
    def test_prompt_is_fully_filled_in(self):
        prompt = build_system_prompt(load_config())
        self.assertTrue(prompt.startswith("## Role"))
        self.assertEqual(re.findall(r"\{\w+\}", prompt), [])
        for fact in ["Harbor Plumbing & Heating", "within about 50 miles of Boston, MA", "Worcester",
                     "Springfield", "drain cleaning", "Sun closed", "320"]:
            self.assertIn(fact, prompt)

    def test_schema_closes_every_object(self):
        def objects(node):
            if isinstance(node, dict):
                if node.get("type") == "object":
                    yield node
                for value in node.values():
                    yield from objects(value)
            elif isinstance(node, list):
                for value in node:
                    yield from objects(value)
        for obj in objects(ANSWER_SCHEMA):
            self.assertIs(obj["additionalProperties"], False)
            self.assertEqual(set(obj["required"]), set(obj["properties"]))


class ValidateAnswerTests(unittest.TestCase):
    def test_normalizes_capitalization(self):
        data = answer(status="Complete", emergency_type="WATER", urgency="Urgent")
        cleaned = validate_answer(data)
        self.assertEqual((cleaned["status"], cleaned["emergency_type"], cleaned["lead"]["urgency"]),
                         ("complete", "water", "urgent"))

    def test_rejects_bad_shapes(self):
        self.assertIsNone(validate_answer("nope"))
        self.assertIsNone(validate_answer({"reply": "hi"}))
        self.assertIsNone(validate_answer(answer(status="finished")))


class ClaudeClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = load_config()

    def test_sends_expected_request_and_parses_answer(self):
        messages = FakeMessages(fake_response(json.dumps(answer(problem="clogged drain"))))
        result = client_with(messages, self.cfg).ask("SYSTEM", [{"role": "user", "content": "hi"}])
        self.assertIsNone(result.error)
        self.assertEqual(result.answer["lead"]["problem"], "clogged drain")
        self.assertEqual((result.input_tokens, result.output_tokens, result.cache_read_tokens), (1200, 150, 1000))
        sent = messages.kwargs
        self.assertEqual(sent["model"], "claude-haiku-5-5")
        self.assertEqual(sent["output_config"]["effort"], "low")
        self.assertEqual(sent["output_config"]["format"]["type"], "json_schema")
        self.assertEqual(sent["system"][0]["cache_control"], {"type": "ephemeral"})
        for banned in ("temperature", "top_p", "top_k", "thinking"):
            self.assertNotIn(banned, sent)

    def test_refusal_and_cutoff_are_errors(self):
        for stop in ("refusal", "max_tokens"):
            result = client_with(FakeMessages(fake_response("", stop)), self.cfg).ask("S", [])
            self.assertIsNone(result.answer)
            self.assertIn(stop, result.error)
            self.assertEqual(result.input_tokens, 1200)  # still billed, so still counted

    def test_bad_json_is_an_error(self):
        result = client_with(FakeMessages(fake_response("{not json")), self.cfg).ask("S", [])
        self.assertIsNone(result.answer)

    def test_api_error_is_caught(self):
        error = anthropic.APIConnectionError(request=SimpleNamespace(method="POST", url="x"))
        result = client_with(FakeMessages(error=error), self.cfg).ask("S", [])
        self.assertIsNone(result.answer)
        self.assertIn("APIConnectionError", result.error)

    def test_cost_estimate(self):
        result = LLMResult(None, input_tokens=1_000_000, output_tokens=1_000_000, cache_read_tokens=1_000_000)
        self.assertAlmostEqual(estimate_cost(self.cfg, result), 0.10 + 0.50 + 0.01)


if __name__ == "__main__":
    unittest.main()
