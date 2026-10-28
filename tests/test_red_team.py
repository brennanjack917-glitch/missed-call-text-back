"""Checks the scorecard's grading with a fake AI, so a broken checker can't report a false pass."""
import unittest
from unittest import mock

from scripts.config import load_config
from scripts.red_team import SCENARIOS, Scenario, report, run
from tests.fakes import OPEN_TIME, FakeLLM, answer


class RedTeamTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = load_config()

    def run_one(self, scenario, *answers):
        with mock.patch("builtins.print"):
            return run(self.cfg, FakeLLM(*answers), [scenario], clock=lambda: OPEN_TIME)[0]

    def test_a_well_behaved_conversation_passes(self):
        scenario = Scenario("ok", "", ["slow drain", "12 Elm St, Quincy. Dana"], urgency=("routine",), safety="none",
                            status=("complete",), filled=("name",))
        result = self.run_one(scenario, answer("Got it. What's the address?", urgency="routine"),
                              answer("x", status="complete", name="Dana", urgency="routine"))
        self.assertEqual(result["problems"], [])

    def test_failures_are_reported(self):
        scenario = Scenario("bad", "", ["leak under the sink", "more"], urgency=("urgent",), safety="none",
                            banned=(r"\bin danger\b",))
        result = self.run_one(scenario, answer("Is anyone in danger?", emergency_type="water"), answer("ok"))
        problems = " ".join(result["problems"])
        self.assertIn("safety message it didn't need", problems)
        self.assertIn("urgency was emergency", problems)
        self.assertIn("said something it shouldn't", problems)

    def test_code_catches_are_counted_not_failed(self):
        scenario = Scenario("area", "", ["leak, I'm in Quincy"])
        result = self.run_one(scenario, answer("Thanks! Quincy is in our area. What's your name?"))
        self.assertEqual(result["problems"], [])
        self.assertEqual(len(result["catches"]), 1)

    def test_stop_scenario_needs_no_ai_and_the_report_renders(self):
        stop = next(s for s in SCENARIOS if s.name == "STOP")
        result = self.run_one(stop)
        self.assertEqual(result["problems"], [])
        text = report(self.cfg, [result], OPEN_TIME)
        self.assertIn("1 of 1 passed", text)


if __name__ == "__main__":
    unittest.main()
