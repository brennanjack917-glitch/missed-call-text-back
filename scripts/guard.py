"""Checks that run in code, independent of the AI: opt-outs, emergency keywords and reply rules.
The AI cannot switch these off, which is the point."""
import re

# Whole-message opt-outs (after lowercasing and removing punctuation). Includes the FCC's listed words
# (47 CFR 64.1200(a)(10)) and plain-language versions, per CTIA's guidance. "stop" inside a longer
# sentence ("I can't stop the leak") is deliberately not an opt-out.
OPT_OUT_MESSAGES = {
    "stop", "stopall", "stop all", "unsubscribe", "cancel", "end", "quit", "revoke", "optout", "opt out",
    "stop texting", "stop texting me", "stop messaging me", "dont text me", "do not text me",
    "dont text me again", "do not text me again", "opt me out", "please opt me out", "unsubscribe me",
    "remove me", "please stop", "stop please", "no more texts",
}

URGENCIES = ("emergency", "urgent", "routine", "unknown")
LEAD_FIELDS = ("name", "problem", "address", "town", "callback_number", "urgency", "best_time")

PRICE = re.compile(r"\$\s?\d|\b\d+(?:\.\d+)?\s?(?:dollars|bucks|usd)\b", re.I)
LINK = re.compile(r"https?://|www\.|\b[\w-]+\.(?:com|net|org|io|co|us|biz|info)\b", re.I)
PROMISED_TIME = (
    re.compile(r"\bwithin\s+(?:an?|\d+|a few|the next)\s*(?:\w+\s+)?(?:mins?|minutes?|hours?|hrs?)\b", re.I),
    re.compile(r"\bin\s+(?:\d+|an?|a few)\s*(?:mins?|minutes?|hours?|hrs?)\b", re.I),
    re.compile(r"\b(?:arrive|be there|be over|come out|send someone|have someone there|on (?:our|the|their) way)\b"
               r"[^.?!]*\b(?:today|tonight|tomorrow|\d{1,2}(?::\d\d)?\s?(?:am|pm)|minutes?|hours?)\b", re.I),
)
HUMAN_CLAIM = re.compile(r"\bi(?:'m|’m| am)\s+(?:a\s+)?(?:real\s+)?(?:human|person)\b", re.I)

# Sentences removed from a reply rather than blocking it: the rest of the reply is still fine to send.
# Whether a town is served is for our fixed message and a person to say ("Quincy is in our area" was
# the AI's most common slip in real runs).
AREA_CLAIM = re.compile(r"\b(?:service area|our (?:usual )?area|we (?:do(?:n'?t| not) )?(?:serve|cover)\b"
                        r"|(?:in|within|outside|out of) (?:our )?(?:range|territory))", re.I)
# In an emergency, nothing that could make someone wait ("the office is closed, we'll see it first thing").
EMERGENCY_TIMING = re.compile(r"\b(?:office|closed|business hours|(?:re)?opens?|first thing|tomorrow|tonight"
                              r"|in the morning|next business day)\b", re.I)
SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
# A customer asking for a human. The AI was told to hand off one turn later but kept collecting, so the
# engine enforces it (see engine.py, step 8).
PERSON_REQUEST = re.compile(
    r"\b(?:real|actual|live) (?:person|human)\b"
    r"|\b(?:talk|speak) (?:to|with) (?:a |an |the |some(?:one|body)? ?)?(?:person|human|someone|somebody|manager|owner|plumber)\b"
    r"|\b(?:someone|somebody|you|a person|a human) (?:to )?(?:just )?call me\b|\bcall me back\b|\bhave someone call\b", re.I)


def is_person_request(text: str) -> bool:
    return bool(PERSON_REQUEST.search(text))


def _normalize(text: str) -> str:
    text = text.lower().replace("’", "'").replace("'", "")
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    return " ".join(text.split())


def is_opt_out(text: str) -> bool:
    return _normalize(text) in OPT_OUT_MESSAGES


def compile_keywords(keywords: dict[str, list[str]]) -> list[tuple[str, re.Pattern]]:
    """One case-insensitive whole-word pattern per category, in config order."""
    compiled = []
    for category, phrases in keywords.items():
        alternatives = "|".join(re.escape(p) for p in sorted(phrases, key=len, reverse=True))
        compiled.append((category, re.compile(rf"(?<![\w])(?:{alternatives})(?![\w])", re.I)))
    return compiled


def emergency_category(text: str, compiled: list[tuple[str, re.Pattern]]) -> str | None:
    """The first category whose keywords appear in the text, or None."""
    for category, pattern in compiled:
        if pattern.search(text):
            return category
    return None


def check_reply(reply: str, max_chars: int) -> list[str]:
    """Problems that make an AI reply unsafe to send. Empty list = OK."""
    problems = []
    if not reply.strip():
        problems.append("empty")
    if len(reply) > max_chars:
        problems.append("too_long")
    if PRICE.search(reply):
        problems.append("price")
    if LINK.search(reply):
        problems.append("link")
    if any(p.search(reply) for p in PROMISED_TIME):
        problems.append("promised_time")
    if HUMAN_CLAIM.search(reply):
        problems.append("claims_human")
    return problems


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.lower().replace("’", "'"))


def instruction_phrases(system_prompt: str, n: int = 8) -> set[tuple[str, ...]]:
    """Every run of n words in the AI's instructions, minus the quoted sample lines it is meant to use."""
    words = _words(re.sub(r'"[^"]*"', " ", system_prompt))
    return {tuple(words[i:i + n]) for i in range(len(words) - n + 1)}


def leaks_instructions(reply: str, phrases: set[tuple[str, ...]], n: int = 8) -> bool:
    """True if the reply repeats n words in a row from the instructions (someone talked it into revealing them)."""
    words = _words(reply)
    return any(tuple(words[i:i + n]) in phrases for i in range(len(words) - n + 1))


def trim_reply(reply: str, emergency: bool) -> tuple[str, list[str]]:
    """The reply without sentences about the service area (and, in an emergency, about office hours
    or timing), plus the removed sentences. An empty result means nothing safe was left."""
    patterns = [AREA_CLAIM] + ([EMERGENCY_TIMING] if emergency else [])
    kept, removed = [], []
    for sentence in SENTENCE_END.split(reply.strip()):
        (removed if any(p.search(sentence) for p in patterns) else kept).append(sentence)
    return " ".join(kept), removed


def merge_lead(old: dict, new: dict) -> dict:
    """New non-empty values replace old ones; empty values never erase what we know,
    'unknown' never replaces a real urgency, and an emergency is never downgraded."""
    merged = dict(old)
    for field in LEAD_FIELDS:
        value = new.get(field)
        value = value.strip() if isinstance(value, str) else value
        if not value:
            continue
        if field == "urgency":
            value = value.lower()
            if value not in URGENCIES or value == "unknown" or old.get("urgency") == "emergency":
                continue
        merged[field] = value
    return merged
