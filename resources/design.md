# Design (Phase 2 draft)

Status: draft for approval. Nothing here is built yet. Research behind each choice is in [output/research.md](../output/research.md). Business settings are in [config.toml](../config.toml); the assistant's instructions are in [workflow/conversation-recipe.md](../workflow/conversation-recipe.md).

## 1. How the parts fit

```
  Provider (how texts arrive and leave)
  ┌──────────────────────┐        events         ┌─────────────────────────────┐
  │ SimulatedProvider    │ ───── missed_call ──▶ │ Engine (one function per    │
  │ (demo web page)      │ ───── customer_text ─▶│ event, no web code inside)  │
  │                      │ ◀──── send_text ───── │                             │
  │ TwilioProvider       │                       └──────┬───────────┬──────────┘
  │ (later, optional)    │                              │           │
  └──────────────────────┘                    asks Claude        saves + notifies
                                              (Haiku 5.5)         │
                                                 │          ┌─────▼─────┐   ┌────────────┐
                                                 ▼          │  SQLite   │   │ Owner page │
                                          Guard (code checks)│  store    │   │ + Gmail    │
                                                            └───────────┘   └────────────┘
```

- **The engine has no web or phone code.** It receives an event and returns texts to send. That is what lets the simulated demo and Twilio share everything else, and what makes it testable offline.
- **The AI is a function, not an agent.** It gets the conversation and returns one structured answer. It has no tools and cannot touch the database, email or phone system.

## 2. Files (built in Phase 3 and 4)

| File | Job |
|---|---|
| `scripts/config.py` | Loads `config.toml`, fills in `{business_name}` etc. |
| `scripts/env.py` | Loads secrets from `.env` (already done) |
| `scripts/store.py` | SQLite tables and queries (pattern from the flight bot) |
| `scripts/guard.py` | Opt-out detection, emergency keywords, reply checks |
| `scripts/llm.py` | The only file that talks to Claude; easy to replace with a fake in tests |
| `scripts/engine.py` | `handle_missed_call()` and `handle_customer_text()` |
| `scripts/provider.py` | Provider interface plus `SimulatedProvider` |
| `scripts/notify.py` | Lead email (pattern from the flight bot) |
| `scripts/web.py` | Demo web server and pages |
| `scripts/theme.py` | Light/dark toggle |
| `tests/` | Offline tests with a fake Claude |

## 3. The two events

| Event | Input | What the engine does |
|---|---|---|
| `missed_call` | caller number, time | Skip if opted out or texted within `dedupe_hours`. Otherwise create a conversation, log the event, send the fixed greeting. |
| `customer_text` | caller number, text, provider message ID | Run the turn pipeline below. |

## 4. The turn pipeline (`customer_text`)

Order matters: safety checks run in code before the AI is asked anything.

As built in Phase 3 (`scripts/engine.py`):

1. **Save** the inbound message, unless the same provider message ID arrived before (real phone companies sometimes deliver twice). A customer who texts without a missed call still gets a conversation.
2. **Opt-out check (code).** If the number already opted out, send nothing. A whole-message match on stop, stopall, unsubscribe, cancel, end, quit, revoke, optout, or a clear phrase ("stop texting me", "opt me out") records the opt-out, sends the fixed confirmation once, and ends the conversation. A word like "stop" inside a longer sentence ("I can't stop the leak") is not an opt-out.
3. **Emergency keywords (code)** are checked on every message.
4. **Finished conversations** (complete or handed off): a late reply gets a fixed "added that for our team" acknowledgement, plus the safety message and an owner alert if it contains an emergency keyword. The AI is not asked again.
5. **Cap checks.** After `max_customer_messages`, send the fixed cap message and hand off. Once the day's AI spend (business time zone) reaches `daily_budget_usd`, skip the AI: send any due safety message, then the fixed hand-off message. Customer texts longer than `max_customer_chars` are cut before they reach the AI.
6. **Ask Claude** (section 5). On an API error, a refusal, or a reply cut off by the token limit: send any due safety message, then the fixed handoff message, and hand off.
7. **Emergencies.** The keyword category wins; otherwise the AI's `emergency_type`. The matching pre-written safety message is sent **before** the AI's reply, once per category per conversation, the lead becomes an emergency, its best time is set to ASAP, and the owner is alerted. The AI's judgment triggers at most one safety message per conversation (a later change of mind would send one out of context); keywords the customer types always get theirs. Safety messages don't ask for the address; the AI's reply does.
8. **Merge the lead.** New non-empty values replace old ones; an empty value never erases something already known; an emergency is never downgraded.
9. **Person requests (code).** When a customer asks for a person or a callback ("real person", "call me back"), the AI gets one more turn to collect their name, number and what it's about; on the customer's next text the code hands off, whatever the AI says. Added after the red-team scorecard showed the AI kept collecting instead.
10. **Closing turns use fixed wording.** When the AI says "complete" or "handoff", the fixed closing message is sent instead of the AI's reply, so a closing can never promise a time.
11. **Guard the reply (code).** First, any sentence saying whether a town is in or out of the service area is removed, and in an emergency so is any sentence about office hours or timing ("first thing tomorrow"); the rest of the reply is still sent. Added after real test runs, where the AI said "Quincy is in our area" in every conversation. Then the reply is checked for length, dollar amounts, links, promised times, claims to be human, and any run of eight words copied from the AI's instructions (sample lines it is meant to use are exempt). A failing reply is replaced by the fixed handoff message and the conversation is handed off.
12. **Save** every sent text, the token usage and estimated cost, and notify the owner on emergency, complete or handoff.

## 5. Asking Claude

**Request shape**
- Model and effort from `config.toml` (`claude-haiku-5-5`, effort low); no `temperature`, `top_p` or `top_k`; no prefill.
- `max_tokens` generous, because thinking counts toward it.
- System prompt = the conversation recipe filled in from the config. It does not change during a conversation, so the history stays append-only and the prompt is cacheable.
- Messages = our own text history from SQLite (we do not replay thinking blocks; to confirm in Phase 3).
- The first user message is written by our code, not the customer: "Call missed at 9:42 PM Tuesday. The office is currently closed." The system prompt says only that first message is trusted.
- The structured-output setting (`output_config.format`) enforces the answer shape below.

**Answer shape** (JSON, every field required, "unknown" values as null)

```json
{
  "reply": "string",
  "lead": {
    "name": "string or null",
    "problem": "string or null",
    "address": "string or null",
    "town": "string or null",
    "callback_number": "string or null",
    "urgency": "emergency | urgent | routine | unknown",
    "best_time": "string or null"
  },
  "status": "collecting | complete | handoff",
  "handoff_reason": "none | customer_requests_person | angry | out_of_area | out_of_scope | unsure | other",
  "emergency_type": "none | gas | carbon_monoxide | fire | water | electrical | other",
  "in_service_area": "yes | no | unclear"
}
```

Notes: structured outputs allow no length or numeric limits in the schema, so lengths are checked by the guard. Enum capitalization isn't guaranteed, so code compares case-insensitively. The output can be cut off or empty on a refusal, which is why step 5 checks the stop reason first.

## 6. Database (SQLite, `data/leads.db`)

| Table | Columns | Why |
|---|---|---|
| `conversations` | id, caller_number, started_at, last_message_at, status (active, complete, handed_off, opted_out), urgency, emergency_type, handoff_reason, customer_message_count | One row per missed call |
| `messages` | id, conversation_id, direction (in, out), source (customer, assistant, fixed), body, provider_message_id, created_at | Full transcript; `source` shows which texts were pre-written |
| `leads` | conversation_id (key), caller_number, name, problem, address, town, callback_number, urgency, best_time, in_service_area, summary, status (new, contacted, closed), notes, notified_at, crm_external_id, crm_sync_status (not_synced, synced, failed), created_at, updated_at | What the owner sees. The two `crm_` columns stay empty until a CRM integration exists (Phase 7); adding them now avoids a database change later. |
| `opt_outs` | caller_number (key), opted_out_at, message_id | Checked before any send |
| `events` | id, conversation_id, type, detail, created_at | Audit trail: missed_call, text_sent, opt_out, emergency_keyword, emergency_ai, reply_trimmed, guard_blocked, api_error, handoff, email_sent. Doubles as consent evidence. |
| `usage` | id, conversation_id, input_tokens, output_tokens, estimated_cost, created_at | Real cost per conversation, to replace the research estimates |

Demo phone numbers are fictional (555-01xx).

## 7. Emergencies

Two layers, either can trigger, and neither can be switched off by the AI:
- **Keywords in code** (lists in `config.toml`) catch the obvious words even if the AI is confused or manipulated.
- **The AI's `emergency_type`** catches danger described in words the keywords don't cover.

A trigger sends a fixed message from `config.toml`, marks the lead as an emergency (red badge, subject-line flag in the email), and emails the owner at once. The conversation then continues to collect the address. The category-to-message mapping:

| Category | Message | Source | Review status |
|---|---|---|---|
| gas | Leave, avoid ignition sources, call 911 from outside, then the gas utility | PG&E (read) | Confirmed |
| carbon_monoxide | Get outside to fresh air, call 911 | CPSC (read) | Confirmed |
| fire | Get out, call 911, don't go back in until cleared | Ready.gov (read) | Confirmed |
| water | Shut off the main valve if safe; 911 if water is near electrics | Fire-department pages via search | Likely; **needs tradesperson review** |
| electrical | Stay away; 911 if smoke or flames | NFPA and Ready.gov (read) | Confirmed |
| other | If anyone is in danger, call 911 | General | Plain wording; review |

False alarms (for example "fire" in "fireplace") send an unneeded safety message. That is annoying but safe, and the tests will list known cases.

## 8. Lead notifications and CRM readiness

Every finished or emergency lead goes through one `lead_created` / `lead_updated` step in the engine, which calls a list of **notifiers**. Each notifier is independent; one failing never stops the others or loses the lead.

| Notifier | When | Status |
|---|---|---|
| Owner page | Always (it reads the database) | Phase 4 |
| Gmail email | Emergencies at once; other leads when complete or handed off | Phase 3 |
| CSV export | On demand, a button on the owner page; columns match the lead table so any spreadsheet or CRM can import it | Phase 4 |
| Webhook (send the lead as JSON to a URL the owner sets, for Zapier, Make or a CRM) | Later | Phase 7; research which tools accept it first |
| Native CRM integrations (e.g. Jobber, Housecall Pro, HubSpot, Google Sheets) | Later | Phase 7; pick the first one after learning which tools tradespeople actually use |

### The lead email

- **Subject:** `🚨 EMERGENCY: Harbor Plumbing & Heating lead, water, 12 Elm St` or `New lead: water heater leak, Millbrook`.
- **Body:** name, phone, problem, address, urgency, best time, in-service-area flag, "needs a human because..." if handed off, and the last few messages.
- All customer text is HTML-escaped before it goes in the email.
- Email failure never loses a lead: the lead is saved first, `notified_at` stays empty, and the owner page shows "not emailed" so it can be retried.

## 9. Pages (sketches)

**Demo page**: left, a phone-style chat; right, controls.

```
┌──────────────────────────────┬──────────────────────────────────┐
│  ◀  Harbor Plumbing & Heating│  DEMO CONTROLS            ◐ Auto │
│  ─────────────────────────── │  Pretend caller: (555) 010-0187 ▾│
│  Hi, sorry we missed your    │  [ Simulate missed call ]        │
│  call! This is Harbor...     │  [ Reset ]                       │
│            I have a leaking  │                                  │
│            water heater      │  What the owner would get:       │
│  Oh no, that sounds ...      │  ▸ Lead card updates live        │
│  ─────────────────────────── │  ▸ Emergency badge when flagged  │
│  [ Type as the customer… ] ▶ │  [ Open owner view ]             │
└──────────────────────────────┴──────────────────────────────────┘
```

**Owner view**: open emergencies pinned to the top, then newest first.

```
┌──────────────────────────────────────────────────────────────────────┐
│ Leads   New 2 · Contacted 1 · Closed 4        [ Export CSV ]   ◐     │
│ [ Search name, address, problem… ]  Status: New ▾  Urgency: All ▾    │
│ ┌──────────────────────────────────────────────────────────────────┐ │
│ │ 🚨 EMERGENCY · NEW   Dana R. · 12 Elm St, Millbrook              │ │
│ │ Water heater leaking in basement · Best time: now                │ │
│ │ [ 📞 Call (555) 010-0187 ]  [ Mark contacted ▾ ]  [ Conversation ]│ │
│ │ Notes: ______________________________________   not emailed ⚠   │ │
│ └──────────────────────────────────────────────────────────────────┘ │
│ ┌ ROUTINE · NEW   Sam K. · clogged kitchen drain · weekday mornings ┐│
└──────────────────────────────────────────────────────────────────────┘
```

- **Call button** is a `tel:` link, so on a phone one tap starts the call.
- **Status** moves new → contacted → closed; the counts at the top show what's waiting.
- **Notes** save as you type, for things like "left voicemail" or "booked Tue 9am".
- **Search and filters** cover name, address, problem, status and urgency.

Light/dark theme on both pages, using the flight bot's toggle pattern.

## 10. Test plan

- **Unit tests, no AI:** opt-out matching, emergency keywords (including the false-alarm list), reply guard, lead merge, dedupe, cap.
- **Engine tests with a fake Claude:** scripted answers drive full conversations: normal lead, emergency, hand-off, refusal, API error, guard block, opt-out mid-conversation.
- **Never a paid call in tests.** Real-model checks are a separate manual script that prints token usage.
- **Phase 5 red-team list** is in the research, topic 5.

## 11. Decisions

Decided 2026-10-26:
1. **Web framework: Flask.** Common for small Python apps, easy to read, and what a later Twilio webhook would use. Adds one pinned dependency in Phase 3/4.
2. **Opt-out line:** hidden in the demo (`include_opt_out_notice = false`), required for real texting.
3. **Service area:** within 50 miles of Boston (the user is based near Boston). The AI judges the town against the radius, anchored by example towns inside and outside it in `config.toml`; the lead says yes, no or unclear, and a human confirms. Out-of-area and out-of-scope hand-offs get their own fixed messages ("{town} may be outside our usual service area..."). A later option is a code check using ZIP-code coordinates.
3a. **Contact details:** the assistant collects a name and confirms the best callback number (it is told the number they called from) before completing, and before any hand-off except for an angry customer.

4. **Lead organizing and CRMs:** build the owner-view tools (status, notes, search, filters, tap-to-call), CSV export, a notifier step and two CRM columns now; webhooks and native CRM integrations in Phase 7, after discovery shows which tools tradespeople use.

Still open:
5. **Emergency wording** for water and "other" needs review by a tradesperson, to be done at the discovery conversation you parked.
6. **Overall design approval** before Phase 3 starts.
