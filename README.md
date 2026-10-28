




# Missed-Call Text-Back

[![Tests](https://github.com/brennanjack917-glitch/missed-call-text-back/actions/workflows/tests.yml/badge.svg)](https://github.com/brennanjack917-glitch/missed-call-text-back/actions/workflows/tests.yml)

**When a plumber can't pick up, an AI assistant texts the caller back within seconds, collects the job details, and puts a ready-to-call lead in front of the owner.** Built as a portfolio prototype for small home-services businesses (plumbing, heating, electrical).

![The owner's view of one lead: the text conversation, the details the assistant collected, and what the code did behind the scenes](docs/screenshots/conversation-light.png)

*A real conversation with the assistant: water pouring through a ceiling. The safety message is pre-written and sent by code, the AI collects the address, name and number, and the owner gets an emergency lead with a tap-to-call button.*

## At a glance

- **The problem:** techs are on jobs and can't answer the phone, and callers phone the next company instead. Call-tracking vendors report that a quarter to a half of business calls never reach a person (CallRail: 28% unanswered across industries; Invoca: 52% of home-services calls reach a person). These are vendor figures, not independent studies; see the [research](output/research.md).
- **What it does:** texts back every missed caller, collects the problem, address, name, best number and best time, judges urgency, and flags emergencies.
- **Built with:** Python, Flask, SQLite and Claude Haiku 5.5 through the Anthropic API. Gmail for owner emails.
- **Safety by design:** the AI only writes replies. Code sends the safety messages, checks every reply, decides when a person takes over, and caps the spending. A [red-team scorecard](output/red-team-report.md) of 23 scripted customers checks it against the real AI: 23 of 23 pass.
- **Cost:** about a tenth of a cent per conversation, measured.
- **Status:** a working demo that runs on your own computer, with simulated texting (no phone bills). Real texting through Twilio is a planned later phase.

## Screenshots


| Demo page: you play the customer | Owner view: every lead, emergencies first |
|---|---|
| ![Demo page with a phone-style chat, the lead the owner gets, and a behind-the-scenes list](docs/screenshots/demo-light.png) | ![Owner view with lead cards, tap-to-call buttons, status and notes](docs/screenshots/owner-dark.png) |

Both pages have light and dark mode ([demo, dark](docs/screenshots/demo-dark.png) · [owner, light](docs/screenshots/owner-light.png)).

**Demo (30 seconds):** a missed call, water pouring through a ceiling, and the lead landing on the owner view.

https://github.com/user-attachments/assets/815d536a-8f61-4229-b9d9-c3a3f975d4c8

## How it works

```mermaid
flowchart LR
    A[Missed call] --> B[Greeting text<br/>pre-written]
    B --> C[Customer replies]
    C --> D{Code checks first<br/>STOP? emergency words?<br/>spending cap?}
    D -->|emergency| E[Pre-written<br/>safety message]
    D --> F[Claude writes a reply<br/>and fills in the lead]
    E --> F
    F --> G{Code checks the reply<br/>prices, links, promises,<br/>service-area claims}
    G -->|ok| H[Reply sent]
    G -->|not ok| I[Hand off to a person]
    H --> C
    F -->|done| J[Owner page + email<br/>emergencies flagged]
    I --> J
```

1. A call to the business goes unanswered, and the caller gets a text within seconds: "Hi, sorry we missed your call! This is Harbor Plumbing & Heating's automated assistant. What's going on, and is anyone in danger?"
2. Every customer text goes through checks in code before the AI sees it: opt-outs (STOP), emergency words such as "smell gas" or "flooding", and the daily spending cap.
3. Claude Haiku 5.5 answers in a fixed structure: the reply text plus the lead details it has learned so far. One call per customer message.
4. Code checks the reply before it's sent: no prices, links, promised arrival times, claims to be human, or copies of its own instructions, and it removes any sentence about whether the town is served (a person decides that).
5. When the lead is complete, or a person needs to take over, the customer gets a fixed closing message and the owner gets the lead on the owner page and by email, with emergencies first.

The business's name, services, hours, service area (50 miles around Boston for the fictional demo company) and tone all live in [config.toml](config.toml), so it can switch trades or regions without code changes. The assistant's instructions are plain English in [workflow/conversation-recipe.md](workflow/conversation-recipe.md).

## Safety rules the assistant follows

- Never quotes prices, promises arrival times, diagnoses problems or gives repair instructions.
- Never tells a customer whether their town is served; a fixed message and a person do that. Code removes any sentence that slips through.
- Emergencies get a pre-written safety message from code (gas, carbon monoxide, fire, flooding, electrical), and the AI never mentions office hours or when the team will see the message.
- Always says it is an automated assistant, and treats customer text as data, never as instructions.
- Hands off to a person when unsure, when a customer is angry or asks for a person (enforced in code one reply later), when the address is out of area, or after 12 customer messages.
- Never repeats its own instructions: code blocks any reply that copies them.
- Honors STOP and plain-language opt-outs immediately.
- Has a daily spending cap ($0.50 by default). Past it, customers get a fixed "someone will follow up" text and the owner still gets the lead.

## Running cost

| | Per conversation | Notes |
|---|---|---|
| AI (Claude Haiku 5.5) | about $0.0005 to $0.001 | Measured over real test conversations; about 5,000 conversations per $5 |
| Real texting (Twilio, later) | about $0.25 | Estimate from the [research](output/research.md), plus about $3 per month fixed |

## Texting rules

The demo sends no real texts, so these don't apply to it. Whether a business may text someone who only called is legally unsettled, and a real launch needs carrier registration (A2P 10DLC) and a review by a TCPA lawyer. This README is not legal advice.

## Project status

| Phase | What | Status |
|---|---|---|
| 0 | Project setup (venv, config, tests) | Done |
| 1 | Research (market, Claude API, texting rules, Twilio, safety) | Done; open items in [research](output/research.md) |
| 2 | Design (settings file, database tables, conversation recipe, page sketches) | Done: [design](resources/design.md), [config.toml](config.toml), [conversation recipe](workflow/conversation-recipe.md) |
| 3 | Core engine (conversation, lead extraction, SQLite, email, tests) | Done; two rounds of real-API tests, fixes confirmed |
| 4 | Demo web page (simulate call, phone chat, owner view with status, notes, search, tap-to-call, CSV export) | Done; checked in the browser in light and dark mode |
| 5 | Hardening (red-team tests, cost guard, failure handling) | Done: 101 offline tests, 23 of 23 on the [red-team scorecard](output/red-team-report.md) |
| 6 | Polish (screenshots, light/dark theme, CI) | Done: screenshots, demo video, README, tests run on GitHub on every push |
| 7 | Optional: real texting with Twilio, lead webhook and CRM integrations, calendar booking, multiple businesses | In progress: lead webhook done (117 offline tests); next, calendar booking |

## Setup

Developed on Windows with Python 3.15; the tests also run on Python 3.13 on GitHub.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env      # then fill in the values (never commit .env)
.\.venv\Scripts\python.exe -m unittest discover
```

`.env` needs an Anthropic API key and, for lead emails, a Gmail address with an app password. See [.env.example](.env.example). Without Gmail settings, owner emails are saved as preview files in `output/email-previews/`.

### Run the demo

```powershell
.\.venv\Scripts\python.exe -m scripts.web
```

Then open **http://127.0.0.1:5050** in your browser. It only runs on your own computer; other devices can't reach it.

- **Demo page:** press *Simulate missed call* and type as the customer. Beside the phone you see the lead the owner gets, filling in as you go, and a "behind the scenes" list of what the code did (safety messages, removed sentences, hand-offs) with the running cost.
- **Owner view** (`/owner`): every lead, emergencies first, with tap-to-call, status (new / contacted / closed), notes that save as you type, search and filters, the full conversation, the owner email, and Export CSV for a spreadsheet or CRM.
- Owner emails are saved as previews by default. A switch on the demo page sends real ones through Gmail, if `.env` has Gmail settings.

Each customer message is one Claude call, about $0.0002.

### Send leads to a CRM (webhook)

Each lead can also be sent as JSON to a web address you choose, so Zapier, Make or a CRM can pick it up. It's sent when an emergency is spotted, when the lead is complete, and when a person needs to take over. Set `LEAD_WEBHOOK_URL` in `.env` (it must start with `https://`) and restart the demo. Leave it blank to turn it off.

- **Try it for free:** run the test receiver in a second terminal, set `LEAD_WEBHOOK_URL=http://127.0.0.1:5051/`, restart the demo, and open **http://127.0.0.1:5051** to watch leads arrive.

  ```powershell
  .\.venv\Scripts\python.exe -m scripts.webhook_receiver
  ```

- **Signature:** set `LEAD_WEBHOOK_SECRET` to any long random text and every lead carries an `X-Signature-256` header (HMAC-SHA256 of the body, `sha256=<hex>`), so the receiver can check it really came from this app. The test receiver checks it when the same secret is in `.env`.
- **Results:** the owner view marks each lead *Sent to CRM* or *CRM send failed*. A failed send never stops the conversation or loses the lead, and Export CSV still works as a backup. There are no automatic retries yet.

### Run the red-team scorecard

```powershell
.\.venv\Scripts\python.exe -m scripts.red_team
```

Plays 23 scripted customers against the real assistant (ordinary jobs, small leaks, gas and CO emergencies, out-of-area, angry customers, price and prompt tricks, STOP, other languages, emoji, huge messages) and checks every reply against the rules automatically. Takes about two minutes and costs under a cent. Results go to [output/red-team-report.md](output/red-team-report.md). It uses a throwaway database, so your leads are untouched.

### Try the assistant in the terminal

You play the customer; the assistant replies through the real Claude API (well under a cent per conversation on Haiku 5.5), and the lead is saved to `data/leads.db`.

```powershell
.\.venv\Scripts\python.exe -m scripts.try_conversation
```

At the end it prints the saved lead, the token usage and the estimated cost.

## How the code is organized

| File | Job |
|---|---|
| [scripts/engine.py](scripts/engine.py) | The conversation pipeline: safety checks in code first, then the AI, then the reply guard |
| [scripts/llm.py](scripts/llm.py) | The only file that talks to Claude (structured answers, cost tracking) |
| [scripts/guard.py](scripts/guard.py) | Opt-outs, emergency keywords, reply checks, lead merging |
| [scripts/store.py](scripts/store.py) | SQLite tables and queries |
| [scripts/notify.py](scripts/notify.py) | Owner email (always saved as a preview; sent through Gmail when switched on) |
| [scripts/webhook.py](scripts/webhook.py) | Sends each lead as JSON to a CRM webhook (optional), with [a free test receiver](scripts/webhook_receiver.py) |
| [scripts/web.py](scripts/web.py) | The demo page and owner view (Flask), with [templates](scripts/templates/) and [styles and scripts](scripts/static/) |
| [scripts/provider.py](scripts/provider.py) | The simulated phone company; a real texting provider (Twilio) would plug in here |
| [scripts/theme.py](scripts/theme.py) | Light/dark theme colors and the toggle |
| [scripts/red_team.py](scripts/red_team.py) | The red-team scorecard (real AI, scripted customers, automatic checks) |
| [scripts/screenshots.py](scripts/screenshots.py) | Retakes the README screenshots (free; needs the tools in [requirements-dev.txt](requirements-dev.txt)) |
| [scripts/config.py](scripts/config.py) | Loads [config.toml](config.toml): business settings and fixed messages |
| [workflow/conversation-recipe.md](workflow/conversation-recipe.md) | The assistant's instructions; becomes the system prompt |

## Project layout

| Folder | Contents |
|---|---|
| `scripts/` | Application code |
| `tests/` | Offline unit tests |
| `workflow/` | Plain-English recipes the AI follows (system prompt design) |
| `output/` | Finished deliverables, including the [research report](output/research.md) |
| `resources/` | Reference docs and templates |
| `data/` | Local SQLite database (not committed) |
| `docs/screenshots/` | README screenshots |
| `.github/workflows/` | Runs the offline tests on GitHub after every push |

## Project log

- **2026-10-28:** Phase 7 started with a lead webhook. Each lead can now be sent as JSON to Zapier, Make or a CRM (`LEAD_WEBHOOK_URL`), with an optional signature, https-only addresses, no redirects, a 10-second timeout and a *Sent to CRM* / *CRM send failed* label on the owner view. A free test receiver (`scripts/webhook_receiver.py`, port 5051) shows leads as they arrive. 117 offline tests pass, a scripted conversation reached the real receiver, and a real-AI demo conversation arrived on the test receiver. The demo page shows whether the webhook is on. Not yet tried with a real Zapier account.
- **2026-10-28:** Added a [launch checklist](resources/launch-checklist.md): everything between this demo and a paying customer (call-forwarding test, Twilio, hosting, owner-page login, carrier registration, legal review, pilot).
- **2026-10-28:** Went public. Following the [going-public checklist](resources/going-public.md), the project was copied to a fresh folder without its Git history and published as a new public repo, so the old commits (and the personal notes in them) stay in the private original. Commits now use a private GitHub `noreply` email. The new repo took the `missed-call-text-back` name, so the Tests badge links still work. Demo video re-uploaded.
- **2026-10-27:** Demo video added to the README: a 30-second screen recording of an emergency conversation, recorded with Snipping Tool and shrunk with ffmpeg.
- **2026-10-27:** Phase 6 polish: README rewritten for portfolio readers with screenshots (taken by `scripts/screenshots.py`, which replays real conversations for free) and a how-it-works diagram; the offline tests now run on GitHub after every push, on Python 3.13 and 3.15.
- **2026-10-27:** Phase 5 hardening done. New: a red-team scorecard (23 scripted customers against the real AI, checked automatically), a daily spending cap, a check that blocks replies repeating the AI's instructions, more emergency wordings and typos ("smel gas", "rotten eggs", "gushing"), duplicate-text protection for real texting later, long-message trimming, an error log, and a "Clear demo data" button. The AI was taught with examples that most leaks are urgent, not emergencies. First scorecard run: 22 of 23 (the AI kept collecting details after a customer asked for a person); the hand-off is now enforced in code. Final run: 23 of 23 for under a cent. 101 offline tests pass.
- **2026-10-27:** Phase 4 built: Flask demo page (phone-style chat, live lead card, behind-the-scenes panel with cost) and owner view (emergencies first, tap-to-call, status, notes, search, filters, conversation page, email preview, CSV export), light/dark theme. Runs on this PC only and refuses requests from other websites. 82 offline tests pass; first run in a browser pending.
- **2026-10-26:** Four real-API test conversations (clogged drain, gas smell, a "quote me a price" trick, out of area). Passed: name, number and address collected every time, gas safety message first, no price quoted, out-of-area hand-off. Fixed what they found: the AI kept telling customers "Quincy is in our area" (code now removes those sentences), told a gas-leak customer the office would see it "first thing" (removed in emergencies; best time is set to ASAP), and a second safety message arrived late when the AI changed its mind about the emergency type. Tighter emergency definition; safety messages now say "emergency". Cost: about $0.0005 to $0.001 per conversation. 67 offline tests pass; re-run with the real API pending.
- **2026-10-26:** Re-ran the four real-API tests after the fixes. No service-area claims reached a customer (the code removed one, "Everett is within our service area"), no office-hours talk in the gas emergency, best time saved as ASAP, one safety message per conversation, no price quoted. Still open: the AI treats most leaks as emergencies, which sends the water safety message and an emergency alert. Kept for now (over-cautious is the safe direction; the water wording is due for a plumber's review). The assistant is now told not to re-ask the danger question or list hazards, which nudged customers into saying yes.
- **2026-10-26:** Service area moved to a 50-mile radius around Boston. The assistant now collects a name and confirms the best callback number before finishing or handing off, and out-of-area and out-of-scope hand-offs get their own messages. 59 offline tests pass.
- **2026-10-26:** First real-API run: a burst-pipe emergency from outside the service area. Keyword safety message, address capture, out-of-area hand-off and two owner emails all worked. Real cost for 2 AI calls: $0.0005 (prompt caching worked from the second call).
- **2026-10-26:** Phase 3 core engine built: conversation pipeline, Claude wrapper with structured answers and cost tracking, emergency and opt-out checks, reply guard, SQLite storage, owner email with preview fallback, terminal test script. 55 offline tests pass; real-API run pending.
- **2026-10-26:** Added lead organizing to the design: status, notes, search, tap-to-call and CSV export on the owner page, plus a notifier step and CRM columns so CRM integrations can come later (Phase 7).
- **2026-10-26:** Decided: Flask for the demo page, opt-out line hidden in the demo (required for real texting), AI-judged service area confirmed by a human.
- **2026-10-26:** Phase 2 design drafted: business settings, conversation recipe, architecture, database tables and page sketches. Nothing built yet.
- **2026-10-26:** Project started. Setup done. Research finished for all five topics, with a gap-closing round that corrected several earlier figures.
