"""Business settings from config.toml, plus small helpers that depend on them."""
import tomllib
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.toml"
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
DAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
EMERGENCY_TYPES = ("gas", "carbon_monoxide", "fire", "water", "electrical", "other")
REQUIRED_SECTIONS = ("business", "services", "service_area", "assistant", "messages", "emergency_keywords")
REQUIRED_MESSAGES = ("greeting", "complete", "handoff", "opt_out_confirm", "cap_reached", "followup_ack")


def load_config(path: Path = CONFIG_PATH) -> dict:
    with open(path, "rb") as f:
        cfg = tomllib.load(f)
    validate(cfg)
    return cfg


def validate(cfg: dict) -> None:
    missing = [s for s in REQUIRED_SECTIONS if s not in cfg]
    missing += [f"messages.{m}" for m in REQUIRED_MESSAGES if m not in cfg.get("messages", {})]
    safety = cfg.get("messages", {}).get("safety", {})
    missing += [f"messages.safety.{t}" for t in EMERGENCY_TYPES if t not in safety]
    unknown = [k for k in cfg.get("emergency_keywords", {}) if k not in EMERGENCY_TYPES]
    if missing:
        raise ValueError(f"config.toml is missing: {', '.join(missing)}")
    if unknown:
        raise ValueError(f"config.toml has emergency keywords for unknown types: {', '.join(unknown)}")


class _KeepUnknown(dict):
    """Leaves {placeholders} it has no value for untouched instead of raising."""
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def fill(text: str, cfg: dict, **extra: str) -> str:
    values = {"business_name": cfg["business"]["name"], "phone": cfg["business"]["phone"],
              "trade": cfg["business"]["trade"], "tone": cfg["business"]["tone"]}
    values.update(extra)
    return text.format_map(_KeepUnknown(values))


def message(cfg: dict, key: str) -> str:
    return fill(cfg["messages"][key], cfg)


def safety_message(cfg: dict, category: str) -> str:
    return fill(cfg["messages"]["safety"][category], cfg)


def local_time(cfg: dict, when: datetime) -> datetime:
    return when.astimezone(ZoneInfo(cfg["business"]["timezone"]))


def office_open(cfg: dict, when: datetime) -> bool:
    local = local_time(cfg, when)
    hours = cfg["business"].get("hours", {}).get(DAYS[local.weekday()])
    if not hours:
        return False
    start, end = hours
    return start <= local.strftime("%H:%M") < end


def fmt_clock(hhmm: str) -> str:
    """'07:00' -> '7:00 AM', '17:30' -> '5:30 PM'."""
    t = datetime.strptime(hhmm, "%H:%M")
    return t.strftime("%I:%M %p").lstrip("0")


def hours_text(cfg: dict) -> str:
    """Office hours as one line, grouping days with the same hours: 'Mon-Fri 7:00 AM-5:00 PM; Sat ...; Sun closed'."""
    hours = cfg["business"].get("hours", {})
    groups: list[tuple[list[str], str]] = []
    for day, name in zip(DAYS, DAY_NAMES):
        span = f"{fmt_clock(hours[day][0])}-{fmt_clock(hours[day][1])}" if day in hours else "closed"
        if groups and groups[-1][1] == span:
            groups[-1][0].append(name)
        else:
            groups.append(([name], span))
    return "; ".join(f"{days[0]}-{days[-1]} {span}" if len(days) > 1 else f"{days[0]} {span}"
                     for days, span in groups)


def describe_call_time(cfg: dict, when: datetime) -> str:
    """'9:42 PM on Tuesday' in the business's time zone."""
    local = local_time(cfg, when)
    return f"{local.strftime('%I:%M %p').lstrip('0')} on {local.strftime('%A')}"
