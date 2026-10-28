import copy
import unittest

from scripts.config import fill, hours_text, load_config, message, office_open, validate
from tests.fakes import CLOSED_TIME, OPEN_TIME


class ConfigTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = load_config()

    def test_real_config_loads_and_fills_business_name(self):
        greeting = message(self.cfg, "greeting")
        self.assertIn("Harbor Plumbing & Heating", greeting)
        self.assertNotIn("{", greeting)

    def test_every_message_fills_completely(self):
        # {town} is filled in by the engine at hand-off time
        texts = [fill(v, self.cfg, town="Melrose") for k, v in self.cfg["messages"].items() if k != "safety"]
        texts += [fill(v, self.cfg) for v in self.cfg["messages"]["safety"].values()]
        for text in texts:
            self.assertNotIn("{", text)

    def test_unknown_placeholders_are_left_alone(self):
        self.assertEqual(fill("Hi {nobody}", self.cfg), "Hi {nobody}")

    def test_office_hours(self):
        self.assertTrue(office_open(self.cfg, OPEN_TIME))
        self.assertFalse(office_open(self.cfg, CLOSED_TIME))

    def test_hours_text_groups_days(self):
        self.assertEqual(hours_text(self.cfg), "Mon-Fri 7:00 AM-5:00 PM; Sat 8:00 AM-12:00 PM; Sun closed")

    def test_missing_safety_message_is_rejected(self):
        broken = copy.deepcopy(self.cfg)
        del broken["messages"]["safety"]["gas"]
        with self.assertRaises(ValueError) as ctx:
            validate(broken)
        self.assertIn("messages.safety.gas", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
