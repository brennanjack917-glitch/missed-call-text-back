# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# Project context

A **portfolio prototype**: an AI "missed-call text-back" assistant for small home-services businesses (plumbers, HVAC, electricians). When a call goes unanswered, the caller gets a text within seconds; Claude texts back and forth to collect the problem, address, name, best number and best time, judges urgency, and the owner gets the lead on an owner page and by email, with emergencies flagged.

It should look polished, be easy for others to understand and be easy to demo. See `README.md` for the full picture and phase table, `resources/design.md` for the design, and `output/research.md` for the research behind it.

**Decisions:**
- **Texting is simulated.** A local demo web page fakes the missed call and shows the conversation; no phone costs or carrier registration. Real texting (Twilio) is optional Phase 7: it costs money and needs US A2P 10DLC registration.
- **Demo business:** the fictional "Harbor Plumbing & Heating", within about 50 miles of Boston. Everything business-specific lives in `config.toml`.
- **Model:** Claude Haiku 5.5, effort low, about $5/month budget. Friendly and casual tone. Runs on the PC only (demo on port 5050).
- **GitHub repo:** private until polished, then public. Treat it as public: never commit secrets. See `resources/going-public.md` before making it public.

**Status (2026-10-28):** Phases 0 to 6 are done (setup, research, design, core engine, demo page and owner view, hardening, polish) and the repo is public. Phase 7 is in progress: the lead webhook is done (`scripts/webhook.py`, test receiver on port 5051); next is calendar booking with simple time slots in `config.toml`, then Twilio and multiple businesses. See `resources/launch-checklist.md`.

# How the code works (keep these rules)
- **The AI only writes replies.** Code sends safety messages, checks every reply (`scripts/guard.py`), decides hand-offs and enforces the spending cap (`scripts/engine.py`). When a prompt instruction doesn't stick in real tests, enforce it in code.
- **Tests never call the paid API:** `python -m unittest discover` uses a fake Claude (`tests/fakes.py`). The red-team scorecard (`python -m scripts.red_team`) and `scripts/try_conversation.py` do cost money (under a cent a run); ask before running them.
- **The demo server** (`python -m scripts.web`) must be restarted after Python changes; template and CSS changes show on refresh.
- **Screenshots:** `python -m scripts.screenshots` (free, needs `requirements-dev.txt`).

# Rules
- Always ask clarifying questions before starting new tasks
- Show your plan and steps before executing
- Keep reports and summaries concise - bullet points over paragraphs
- Save all output files to an output folder that you create
- Cite sources when doing research
- Keep README.md up to date as we go: update the status table and project log at the end of each phase or meaningful step, and never claim something works until it has been run

# Project structure
- `scripts/` - application code; `tests/` - offline tests
- `workflow/` - workflow instruction files (plain English recipes the agent follows, including the assistant's system prompt)
- `output/` - finished deliverables (reports, drafts, analysis)
- `resources/` - reference docs and templates
- `docs/screenshots/` - README screenshots
