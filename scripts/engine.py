"""The conversation engine: turns 'missed call' and 'customer text' events into texts to send.
It has no web or phone code, so the simulated demo and a future Twilio version share it unchanged.
Safety checks run in code before the AI is asked anything; see resources/design.md, section 4."""
from datetime import datetime, timedelta
from typing import Callable

from scripts import guard
from scripts.config import describe_call_time, fill, local_time, message, office_open, safety_message
from scripts.llm import LLMResult, build_system_prompt, estimate_cost
from scripts.store import Store, ts

# A notifier gets (lead, recent messages, reason) and returns True if the owner was reached.
Notifier = Callable[[dict, list[dict], str], bool]

FINISHED = ("complete", "handed_off", "opted_out")


class Engine:
    def __init__(self, cfg: dict, store: Store, llm, notifiers: list[Notifier] | None = None):
        self.cfg = cfg
        self.store = store
        self.llm = llm
        self.notifiers = notifiers or []
        self.keywords = guard.compile_keywords(cfg["emergency_keywords"])
        self.system_prompt = build_system_prompt(cfg)
        self.instruction_phrases = guard.instruction_phrases(self.system_prompt)

    # Events

    def handle_missed_call(self, caller: str, now: datetime) -> list[str]:
        """Start a conversation and return the greeting, unless the caller opted out or was texted recently."""
        if self.store.is_opted_out(caller):
            self.store.log_event(None, "missed_call_opted_out", now, caller)
            return []
        latest = self.store.latest_conversation(caller)
        window = timedelta(hours=self.cfg["assistant"]["dedupe_hours"])
        if latest and datetime.fromisoformat(latest["started_at"]) > now - window:
            self.store.log_event(latest["id"], "missed_call_deduped", now)
            return []
        status = "open" if office_open(self.cfg, now) else "closed"
        note = (f"[Note from our system] Call missed at {describe_call_time(self.cfg, now)} from {caller}. "
                f"The office is {status} right now.")
        conv_id = self.store.create_conversation(caller, now, note)
        self.store.log_event(conv_id, "missed_call", now)
        greeting = message(self.cfg, "greeting")
        if self.cfg["assistant"].get("include_opt_out_notice"):
            greeting += " Reply STOP to opt out."
        return self._send(conv_id, [("fixed", greeting)], now)

    def handle_customer_text(self, caller: str, text: str, now: datetime,
                             provider_message_id: str | None = None) -> list[str]:
        conv = self.store.latest_conversation(caller)
        # Phone companies sometimes deliver the same text twice; answer it once
        if provider_message_id and self.store.has_provider_message(provider_message_id):
            self.store.log_event(conv["id"] if conv else None, "duplicate_ignored", now, provider_message_id)
            return []
        if conv is None:
            note = (f"[Note from our system] The customer texted us directly at "
                    f"{describe_call_time(self.cfg, now)} from {caller}; there was no missed call.")
            conv = self.store.conversation(self.store.create_conversation(caller, now, note))
        conv_id = conv["id"]
        message_id = self.store.add_message(conv_id, "in", "customer", text, now, provider_message_id)

        # 1. Opt-outs come first and are final
        if self.store.is_opted_out(caller):
            self.store.log_event(conv_id, "text_after_opt_out", now)
            return []
        if guard.is_opt_out(text):
            self.store.add_opt_out(caller, now, message_id)
            self.store.update_conversation(conv_id, status="opted_out")
            self.store.log_event(conv_id, "opt_out", now, text)
            return self._send(conv_id, [("fixed", message(self.cfg, "opt_out_confirm"))], now)

        keyword_category = guard.emergency_category(text, self.keywords)
        person_asked_before = any(e["type"] == "person_requested" for e in self.store.events(conv_id))
        if not person_asked_before and conv["status"] not in FINISHED and guard.is_person_request(text):
            self.store.log_event(conv_id, "person_requested", now, text[:200])

        # 2. The lead is already finished: acknowledge, but still run the safety check
        if conv["status"] in FINISHED:
            out = self._safety_messages(conv, keyword_category, "emergency_keyword", now)
            self.store.log_event(conv_id, "late_reply", now)
            self.store.update_lead(conv_id, now)
            sent = self._send(conv_id, out + [("fixed", message(self.cfg, "followup_ack"))], now)
            if out:
                self._notify(conv_id, "emergency", now)
            return sent

        # 3. Cap on customer messages (cost and safety)
        count = conv["customer_message_count"] + 1
        self.store.update_conversation(conv_id, customer_message_count=count)
        if count > self.cfg["assistant"]["max_customer_messages"]:
            out = self._safety_messages(conv, keyword_category, "emergency_keyword", now)
            return self._finish(conv_id, out + [("fixed", message(self.cfg, "cap_reached"))],
                                "handed_off", "message_cap", now)

        # 4. Daily spending cap: past it, the AI is skipped and a person follows up
        if self.spent_today(now) >= self.cfg["assistant"]["daily_budget_usd"]:
            self.store.log_event(conv_id, "budget_reached", now)
            out = self._safety_messages(conv, keyword_category, "emergency_keyword", now)
            return self._finish(conv_id, out + [("fixed", message(self.cfg, "handoff"))],
                                "handed_off", "daily_budget", now)

        # 5. Ask Claude, with a history that always ends on the customer's message
        result = self.llm.ask(self.system_prompt, self.history(conv_id))
        self._record_usage(conv_id, result, now)
        if result.answer is None:
            self.store.log_event(conv_id, "api_error", now, result.error or "")
            out = self._safety_messages(conv, keyword_category, "emergency_keyword", now)
            return self._finish(conv_id, out + [("fixed", message(self.cfg, "handoff"))],
                                "handed_off", "ai_unavailable", now)
        answer = result.answer

        # 6. Emergencies: keywords win; otherwise the AI's judgment. Safety text is always pre-written.
        ai_category = answer["emergency_type"] if answer["emergency_type"] != "none" else None
        if keyword_category:
            out = self._safety_messages(conv, keyword_category, "emergency_keyword", now)
        else:
            out = self._safety_messages(conv, ai_category, "emergency_ai", now)

        # 7. Merge what the AI learned into the lead
        lead = self.store.lead(conv_id)
        merged = guard.merge_lead(lead, answer["lead"])
        if keyword_category or ai_category:
            merged["urgency"] = "emergency"
        emergency = merged.get("urgency") == "emergency"
        if emergency and not merged.get("best_time"):
            merged["best_time"] = "ASAP"  # the AI is told not to ask during an emergency
        changes = {f: merged[f] for f in guard.LEAD_FIELDS if merged.get(f) != lead.get(f)}
        if answer["in_service_area"] != "unclear":
            changes["in_service_area"] = answer["in_service_area"]
        self.store.update_lead(conv_id, now, **changes)
        if merged.get("urgency") and merged["urgency"] != "unknown":
            self.store.update_conversation(conv_id, urgency=merged["urgency"])

        # 8. Closing turns use fixed wording; otherwise the AI's reply, if it passes the guard.
        # A customer who asked for a person got one turn to give their details; now a person takes over.
        if person_asked_before and answer["status"] == "collecting":
            answer = {**answer, "status": "handoff", "handoff_reason": "customer_requests_person"}
        if answer["status"] == "complete":
            return self._finish(conv_id, out + [("fixed", message(self.cfg, "complete"))], "complete", None, now)
        if answer["status"] == "handoff":
            return self._finish(conv_id, out + [("fixed", self._handoff_message(conv_id, answer["handoff_reason"]))],
                                "handed_off", answer["handoff_reason"], now)
        reply, removed = guard.trim_reply(answer["reply"], emergency)
        if removed:
            self.store.log_event(conv_id, "reply_trimmed", now, " | ".join(removed))
        problems = guard.check_reply(reply, self.cfg["assistant"]["max_reply_chars"])
        if guard.leaks_instructions(reply, self.instruction_phrases):
            problems.append("instructions")
        if problems:
            self.store.log_event(conv_id, "guard_blocked", now, f"{','.join(problems)}: {answer['reply']}")
            return self._finish(conv_id, out + [("fixed", message(self.cfg, "handoff"))],
                                "handed_off", "reply_blocked", now)
        sent = self._send(conv_id, out + [("assistant", reply)], now)
        if out:
            self._notify(conv_id, "emergency", now)
        return sent

    # Helpers

    def spent_today(self, now: datetime) -> float:
        midnight = local_time(self.cfg, now).replace(hour=0, minute=0, second=0, microsecond=0)
        return self.store.cost_since(midnight)

    def history(self, conv_id: int) -> list[dict]:
        """The trusted context note, then the text history as alternating turns.
        Consecutive messages from the same side are joined, as the API would. Very long customer
        texts are cut, so one message can't run up the cost."""
        limit = self.cfg["assistant"]["max_customer_chars"]
        turns = [{"role": "user", "content": self.store.conversation(conv_id)["context_note"]}]
        for m in self.store.messages(conv_id):
            role = "user" if m["direction"] == "in" else "assistant"
            body = m["body"] if role == "assistant" or len(m["body"]) <= limit else m["body"][:limit] + " [cut]"
            if turns[-1]["role"] == role:
                turns[-1]["content"] += "\n\n" + body
            else:
                turns.append({"role": role, "content": body})
        return turns

    def _handoff_message(self, conv_id: int, reason: str) -> str:
        """The reason's own hand-off message if config.toml has one (e.g. out of area), else the general one."""
        key = f"handoff_{reason}" if f"handoff_{reason}" in self.cfg["messages"] else "handoff"
        town = self.store.lead(conv_id).get("town") or "That area"
        return fill(self.cfg["messages"][key], self.cfg, town=town)

    def _safety_messages(self, conv: dict, category: str | None, event: str, now: datetime) -> list[tuple[str, str]]:
        """The pre-written safety message for a category, once per conversation per category.
        The AI's judgment triggers at most one: if it changes its mind about the kind of emergency later,
        a second message would arrive out of context. Keywords the customer typed always count."""
        if not category:
            return []
        conv = self.store.conversation(conv["id"])
        warned = [c for c in conv["warned"].split(",") if c]
        if category in warned or (event == "emergency_ai" and warned):
            return []
        warned.append(category)
        self.store.update_conversation(conv["id"], warned=",".join(warned), urgency="emergency",
                                       emergency_type=conv["emergency_type"] or category)
        self.store.update_lead(conv["id"], now, urgency="emergency")
        self.store.log_event(conv["id"], event, now, category)
        return [("fixed", safety_message(self.cfg, category))]

    def _finish(self, conv_id: int, out: list[tuple[str, str]], status: str, reason: str | None,
                now: datetime) -> list[str]:
        self.store.update_conversation(conv_id, status=status, handoff_reason=reason)
        if status == "handed_off":
            self.store.log_event(conv_id, "handoff", now, reason or "")
        sent = self._send(conv_id, out, now)
        self._notify(conv_id, "handoff" if status == "handed_off" else "complete", now)
        return sent

    def _send(self, conv_id: int, out: list[tuple[str, str]], now: datetime) -> list[str]:
        for source, body in out:
            self.store.add_message(conv_id, "out", source, body, now)
        self.store.log_event(conv_id, "text_sent", now, str(len(out)))
        return [body for _, body in out]

    def _record_usage(self, conv_id: int, result: LLMResult, now: datetime) -> None:
        self.store.add_usage(conv_id, now, result.input_tokens, result.output_tokens, result.cache_read_tokens,
                             result.cache_write_tokens, estimate_cost(self.cfg, result))

    def _notify(self, conv_id: int, reason: str, now: datetime) -> None:
        """Every notifier runs; one failing never stops the others or loses the lead (it's already saved)."""
        lead = {**self.store.lead(conv_id), "handoff_reason": self.store.conversation(conv_id)["handoff_reason"]}
        recent = self.store.messages(conv_id)[-10:]
        self.store.log_event(conv_id, "owner_alert", now, reason)  # the lead is on the owner page from here
        reached = False
        for notifier in self.notifiers:
            try:
                reached = notifier(lead, recent, reason) or reached
            except Exception as e:  # a notifier must never break the conversation
                self.store.log_event(conv_id, "notify_failed", now, f"{type(e).__name__}: {e}")
        if reached:
            self.store.update_lead(conv_id, now, notified_at=ts(now))
            self.store.log_event(conv_id, "owner_notified", now, reason)
