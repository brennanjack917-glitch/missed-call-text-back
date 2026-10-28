"""SQLite storage (data/leads.db): conversations, messages, leads, opt-outs, an event log and token usage."""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "leads.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY,
    caller_number TEXT NOT NULL,
    started_at TEXT NOT NULL,
    last_message_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',  -- active, complete, handed_off, opted_out
    urgency TEXT NOT NULL DEFAULT 'unknown',
    emergency_type TEXT,
    warned TEXT NOT NULL DEFAULT '',  -- safety-message categories already sent, comma-separated
    handoff_reason TEXT,
    customer_message_count INTEGER NOT NULL DEFAULT 0,
    context_note TEXT NOT NULL  -- the trusted first message the AI sees
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id),
    direction TEXT NOT NULL,  -- 'in' (customer) or 'out'
    source TEXT NOT NULL,  -- 'customer', 'assistant' (AI-written) or 'fixed' (pre-written)
    body TEXT NOT NULL,
    provider_message_id TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS leads (
    conversation_id INTEGER PRIMARY KEY REFERENCES conversations(id),
    caller_number TEXT NOT NULL,
    name TEXT,
    problem TEXT,
    address TEXT,
    town TEXT,
    callback_number TEXT,  -- the number the customer confirmed; empty = use caller_number
    urgency TEXT NOT NULL DEFAULT 'unknown',
    best_time TEXT,
    in_service_area TEXT NOT NULL DEFAULT 'unclear',
    summary TEXT,
    status TEXT NOT NULL DEFAULT 'new',  -- new, contacted, closed
    notes TEXT NOT NULL DEFAULT '',
    notified_at TEXT,
    crm_external_id TEXT,  -- for a future CRM integration (Phase 7)
    crm_sync_status TEXT NOT NULL DEFAULT 'not_synced',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS opt_outs (
    caller_number TEXT PRIMARY KEY,
    opted_out_at TEXT NOT NULL,
    message_id INTEGER
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    conversation_id INTEGER,
    type TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS usage (
    id INTEGER PRIMARY KEY,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id),
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    cache_read_tokens INTEGER NOT NULL DEFAULT 0,
    cache_write_tokens INTEGER NOT NULL DEFAULT 0,
    estimated_cost REAL NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_conversations_caller ON conversations(caller_number, started_at);
CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id, id);
"""

# Columns callers may update, so field names never come straight from outside into SQL
CONVERSATION_FIELDS = {"last_message_at", "status", "urgency", "emergency_type", "warned",
                       "handoff_reason", "customer_message_count"}
LEAD_FIELDS = {"name", "problem", "address", "town", "callback_number", "urgency", "best_time", "in_service_area", "summary",
               "status", "notes", "notified_at", "crm_external_id", "crm_sync_status"}
LEAD_STATUSES = ("new", "contacted", "closed")
SEARCHABLE = ("name", "problem", "address", "town", "caller_number", "callback_number", "notes")


def ts(when: datetime) -> str:
    return when.isoformat(timespec="seconds")


class Store:
    def __init__(self, path: Path | str = DB_PATH):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        # Add columns missing from databases created by earlier versions
        for table, column, ddl in [("leads", "town", "town TEXT"), ("leads", "callback_number", "callback_number TEXT")]:
            if column not in {r["name"] for r in self.db.execute(f"PRAGMA table_info({table})")}:
                self.db.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    # Conversations

    def create_conversation(self, caller: str, now: datetime, context_note: str) -> int:
        cur = self.db.execute(
            "INSERT INTO conversations (caller_number, started_at, last_message_at, context_note) VALUES (?, ?, ?, ?)",
            (caller, ts(now), ts(now), context_note))
        conv_id = cur.lastrowid
        self.db.execute("INSERT INTO leads (conversation_id, caller_number, created_at, updated_at) VALUES (?, ?, ?, ?)",
                        (conv_id, caller, ts(now), ts(now)))
        self.db.commit()
        return conv_id

    def conversation(self, conv_id: int) -> dict:
        return dict(self.db.execute("SELECT * FROM conversations WHERE id = ?", (conv_id,)).fetchone())

    def latest_conversation(self, caller: str) -> dict | None:
        row = self.db.execute("SELECT * FROM conversations WHERE caller_number = ? ORDER BY id DESC LIMIT 1",
                              (caller,)).fetchone()
        return dict(row) if row else None

    def update_conversation(self, conv_id: int, **fields) -> None:
        self._update("conversations", "id", conv_id, fields, CONVERSATION_FIELDS)

    # Messages

    def add_message(self, conv_id: int, direction: str, source: str, body: str, now: datetime,
                    provider_message_id: str | None = None) -> int:
        cur = self.db.execute(
            "INSERT INTO messages (conversation_id, direction, source, body, provider_message_id, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)", (conv_id, direction, source, body, provider_message_id, ts(now)))
        self.db.execute("UPDATE conversations SET last_message_at = ? WHERE id = ?", (ts(now), conv_id))
        self.db.commit()
        return cur.lastrowid

    def messages(self, conv_id: int) -> list[dict]:
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM messages WHERE conversation_id = ? ORDER BY id", (conv_id,))]

    # Leads

    def lead(self, conv_id: int) -> dict:
        return dict(self.db.execute("SELECT * FROM leads WHERE conversation_id = ?", (conv_id,)).fetchone())

    def update_lead(self, conv_id: int, now: datetime, **fields) -> None:
        fields["updated_at"] = ts(now)
        self._update("leads", "conversation_id", conv_id, fields, LEAD_FIELDS | {"updated_at"})

    def leads(self, status: str | None = None, urgency: str | None = None, query: str | None = None) -> list[dict]:
        """Newest first, with open emergencies pinned to the top. `query` matches any part of the
        name, problem, address, town, phone numbers or notes, ignoring case."""
        where, params = [], []
        if status:
            where.append("status = ?")
            params.append(status)
        if urgency:
            where.append("urgency = ?")
            params.append(urgency)
        if query and query.strip():
            # instr() rather than LIKE, so % and _ in a search are ordinary characters
            where.append("instr(lower(" + " || ' ' || ".join(f"coalesce({c}, '')" for c in SEARCHABLE) + "), lower(?)) > 0")
            params.append(query.strip())
        sql = "SELECT * FROM leads" + (" WHERE " + " AND ".join(where) if where else "")
        sql += " ORDER BY (urgency = 'emergency' AND status != 'closed') DESC, created_at DESC, conversation_id DESC"
        return [dict(r) for r in self.db.execute(sql, params)]

    def lead_counts(self) -> dict[str, int]:
        """How many leads are new, contacted and closed."""
        counts = {status: 0 for status in LEAD_STATUSES}
        for row in self.db.execute("SELECT status, COUNT(*) AS n FROM leads GROUP BY status"):
            counts[row["status"]] = row["n"]
        return counts

    # Opt-outs, events and usage

    def is_opted_out(self, caller: str) -> bool:
        return self.db.execute("SELECT 1 FROM opt_outs WHERE caller_number = ?", (caller,)).fetchone() is not None

    def add_opt_out(self, caller: str, now: datetime, message_id: int | None) -> None:
        self.db.execute("INSERT OR IGNORE INTO opt_outs (caller_number, opted_out_at, message_id) VALUES (?, ?, ?)",
                        (caller, ts(now), message_id))
        self.db.commit()

    def log_event(self, conv_id: int | None, kind: str, now: datetime, detail: str = "") -> None:
        self.db.execute("INSERT INTO events (conversation_id, type, detail, created_at) VALUES (?, ?, ?, ?)",
                        (conv_id, kind, detail, ts(now)))
        self.db.commit()

    def events(self, conv_id: int) -> list[dict]:
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM events WHERE conversation_id = ? ORDER BY id", (conv_id,))]

    def add_usage(self, conv_id: int, now: datetime, input_tokens: int, output_tokens: int,
                  cache_read_tokens: int, cache_write_tokens: int, estimated_cost: float) -> None:
        self.db.execute(
            "INSERT INTO usage (conversation_id, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens,"
            " estimated_cost, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (conv_id, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, estimated_cost, ts(now)))
        self.db.commit()

    def cost_since(self, start: datetime) -> float:
        """Total estimated AI spend from `start` on (timestamps are all saved in UTC, so they sort as text)."""
        row = self.db.execute("SELECT COALESCE(SUM(estimated_cost), 0) FROM usage WHERE created_at >= ?",
                              (ts(start.astimezone(timezone.utc)),)).fetchone()
        return row[0]

    def has_provider_message(self, provider_message_id: str) -> bool:
        return self.db.execute("SELECT 1 FROM messages WHERE provider_message_id = ?",
                               (provider_message_id,)).fetchone() is not None

    def clear_all(self) -> None:
        """Deletes every conversation, lead, opt-out, event and cost record (the demo's "Clear demo data")."""
        for table in ("usage", "events", "messages", "leads", "conversations", "opt_outs"):
            self.db.execute(f"DELETE FROM {table}")
        self.db.commit()

    def conversation_cost(self, conv_id: int) -> dict:
        row = self.db.execute(
            "SELECT COUNT(*) AS calls, COALESCE(SUM(input_tokens), 0) AS input_tokens,"
            " COALESCE(SUM(output_tokens), 0) AS output_tokens, COALESCE(SUM(cache_read_tokens), 0) AS cache_read_tokens,"
            " COALESCE(SUM(cache_write_tokens), 0) AS cache_write_tokens, COALESCE(SUM(estimated_cost), 0) AS cost"
            " FROM usage WHERE conversation_id = ?", (conv_id,)).fetchone()
        return dict(row)

    def _update(self, table: str, key: str, key_value: int, fields: dict, allowed: set[str]) -> None:
        bad = set(fields) - allowed
        if bad:
            raise ValueError(f"cannot update {table}: {', '.join(sorted(bad))}")
        if not fields:
            return
        assignments = ", ".join(f"{name} = ?" for name in fields)
        self.db.execute(f"UPDATE {table} SET {assignments} WHERE {key} = ?", (*fields.values(), key_value))
        self.db.commit()
