import sqlite3
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from scripts.store import Store
from tests.fakes import OPEN_TIME


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")

    def tearDown(self):
        self.store.close()

    def test_conversation_creates_an_empty_lead(self):
        conv_id = self.store.create_conversation("(555) 010-0187", OPEN_TIME, "note")
        lead = self.store.lead(conv_id)
        self.assertEqual(lead["caller_number"], "(555) 010-0187")
        self.assertEqual((lead["status"], lead["urgency"], lead["crm_sync_status"]), ("new", "unknown", "not_synced"))

    def test_older_database_gains_new_columns(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "old.db"
            old = sqlite3.connect(path)
            old.execute("CREATE TABLE leads (conversation_id INTEGER PRIMARY KEY, caller_number TEXT NOT NULL,"
                        " name TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)")
            old.commit()
            old.close()
            store = Store(path)
            columns = {r["name"] for r in store.db.execute("PRAGMA table_info(leads)")}
            store.close()
        self.assertTrue({"town", "callback_number"} <= columns)

    def test_updates_reject_unknown_columns(self):
        conv_id = self.store.create_conversation("x", OPEN_TIME, "note")
        with self.assertRaises(ValueError):
            self.store.update_lead(conv_id, OPEN_TIME, **{"name = 'x'; DROP TABLE leads; --": "1"})
        with self.assertRaises(ValueError):
            self.store.update_conversation(conv_id, caller_number="someone else")

    def test_leads_pin_open_emergencies_then_newest(self):
        old = self.store.create_conversation("a", OPEN_TIME, "n")
        emergency = self.store.create_conversation("b", OPEN_TIME + timedelta(minutes=1), "n")
        newest = self.store.create_conversation("c", OPEN_TIME + timedelta(minutes=2), "n")
        self.store.update_lead(emergency, OPEN_TIME, urgency="emergency")
        self.assertEqual([l["conversation_id"] for l in self.store.leads()], [emergency, newest, old])
        self.store.update_lead(emergency, OPEN_TIME, status="closed")
        self.assertEqual([l["conversation_id"] for l in self.store.leads()], [newest, emergency, old])
        self.assertEqual([l["conversation_id"] for l in self.store.leads(status="closed")], [emergency])

    def test_search_filters_and_counts(self):
        dana = self.store.create_conversation("(617) 555-0101", OPEN_TIME, "n")
        sam = self.store.create_conversation("(617) 555-0102", OPEN_TIME, "n")
        self.store.update_lead(dana, OPEN_TIME, name="Dana", problem="Burst pipe", town="Quincy", urgency="emergency")
        self.store.update_lead(sam, OPEN_TIME, name="Sam", problem="slow drain 100%", urgency="routine",
                               status="contacted", notes="left voicemail")
        ids = lambda **kw: [l["conversation_id"] for l in self.store.leads(**kw)]
        self.assertEqual(ids(query="quincy"), [dana])
        self.assertEqual(ids(query="VOICEMAIL"), [sam])
        self.assertEqual(ids(query="0102"), [sam])
        self.assertEqual(ids(query="100%"), [sam])
        self.assertEqual(ids(query="%"), [sam])  # % is just a character, not "match anything"
        self.assertEqual(ids(urgency="emergency"), [dana])
        self.assertEqual(ids(status="contacted", query="dana"), [])
        self.assertEqual(self.store.lead_counts(), {"new": 1, "contacted": 1, "closed": 0})

    def test_opt_outs_and_cost_totals(self):
        conv_id = self.store.create_conversation("a", OPEN_TIME, "n")
        self.assertFalse(self.store.is_opted_out("a"))
        self.store.add_opt_out("a", OPEN_TIME, None)
        self.store.add_opt_out("a", OPEN_TIME, None)  # repeat is harmless
        self.assertTrue(self.store.is_opted_out("a"))
        self.store.add_usage(conv_id, OPEN_TIME, 1000, 100, 0, 0, 0.00015)
        self.store.add_usage(conv_id, OPEN_TIME, 1200, 80, 900, 0, 0.00016)
        cost = self.store.conversation_cost(conv_id)
        self.assertEqual((cost["calls"], cost["input_tokens"], cost["output_tokens"]), (2, 2200, 180))
        self.assertAlmostEqual(cost["cost"], 0.00031)


if __name__ == "__main__":
    unittest.main()
