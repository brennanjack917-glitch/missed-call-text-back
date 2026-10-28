# Launch checklist: from portfolio demo to a paying customer

What it would take for a real business to use this on their real phone line. Written 2026-10-28. For making the GitHub repo public, see [going-public.md](going-public.md).

## Where things stand

- **Portfolio launch: done.** Public repo with screenshots, demo video, passing tests and a 23 of 23 red-team scorecard.
- **Product launch: not ready.** The conversation engine, safety checks, owner page and email alerts work and are tested, but texting is simulated, the app runs only on this PC, and there's no login.

## 1. Prove call forwarding works (do this first)

Most businesses will want to keep their existing number and forward unanswered calls to Twilio. Nobody has tested whether that works, and the whole approach depends on it. Details: [research, topic 4](../output/research.md).

- [ ] Open a paid Twilio account (a free trial can't send AI-written texts) and buy a local number (about $1.15/month).
- [ ] Turn on "forward when unanswered" on a real phone and call it from another phone.
- [ ] Check: does the **caller's** number reach Twilio? If not, we can't text them back, and option A (Twilio number as the business line) is the fallback.
- [ ] Check: does voicemail (or iPhone Live Voicemail) answer before the call is forwarded?
- [ ] Test on the carrier the pilot business uses (Verizon's forwarding codes differ from AT&T and T-Mobile).

## 2. Connect real texting (Phase 7)

- [ ] Write a Twilio version of the texting code in [scripts/provider.py](../scripts/provider.py) (the AI, leads and owner page don't change).
- [ ] Check every incoming request really came from Twilio (`RequestValidator` in the `twilio` library).
- [ ] Optional: text the owner about each new lead (especially emergencies) as well as emailing them.
- [ ] Re-run the red-team scorecard and a few real conversations over real texts.

## 3. Host it online

- [ ] Choose a small cloud server (estimated $5–10/month) so it runs 24/7 with a public HTTPS address.
- [ ] Keep keys in the server's settings, never in the code (same `.env` rule as now).
- [ ] Back up the database regularly, and get an alert if the app stops running.

## 4. Lock down the owner page

The owner page has **no login** right now. That's only safe because the demo server accepts connections from this PC alone (`127.0.0.1` in [scripts/web.py](../scripts/web.py)). Online, anyone with the link would see customers' names, addresses and phone numbers.

- [ ] Add a login (or at least a password) to the owner page and CSV export.
- [ ] Turn off or protect the demo-only pages ("simulate a call", "Clear demo data").

## 5. Carrier registration

- [ ] Register for A2P 10DLC through Twilio: a brand (the business) and a campaign (what gets texted and how people opt out). Roughly $20 to start plus $2/month (fees not confirmed on Twilio's own pages).
- [ ] Allow a few weeks for approval.

## 6. Legal

- [ ] Have a TCPA lawyer review it: whether a business may text someone who only called is legally unsettled.
- [ ] Confirm the wording of the opt-out text (STOP/HELP) and the "automated assistant" notice in the first message.
- [ ] Decide quiet hours (a conservative rule from the research: never start a conversation outside 9 a.m.-8 p.m. local time).
- [ ] A short privacy note for customers: what's kept and for how long.

## 7. Set it up for the real business

- [ ] Fill in `config.toml` with their name, service area, hours, emergency list and tone.
- [ ] Have the owner (a real plumber, HVAC tech or electrician) review the emergency list and the safety messages.
- [ ] Walk the owner through the owner page and agree how fast they'll call leads back.

## 8. Business basics

- [ ] Pricing (competitors charge roughly $30–$300/month; see [research, topic 1](../output/research.md)).
- [ ] A simple written agreement: what it does, what it costs, who pays the Twilio and AI costs.
- [ ] A plan for support: who they call when it breaks, and how you'll find out first.

## 9. Pilot

- [ ] Find one friendly local business willing to try it.
- [ ] Run a supervised trial for a few weeks: read every conversation, fix what goes wrong.
- [ ] Ask for a testimonial if it goes well.

## Later (not needed for the first customer)

- Lead webhook and CRM links (Jobber, Housecall Pro, HubSpot, Google Sheets)
- Calendar booking
- Several businesses on one system (needed to sell it as a service at scale)

## Monthly running cost per business (estimates)

| Item | Cost |
|---|---|
| Twilio number and carrier registration | about $3 |
| Texts | about 25¢ per conversation |
| AI (Claude Haiku 5.5) | under a tenth of a cent per conversation |
| Server (can be shared across businesses) | $5–10 |
