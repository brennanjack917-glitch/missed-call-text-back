"""Shared light/dark theme for the web pages: color tokens plus the Auto/Light/Dark toggle.
Copied from the flight bot's pattern; the choice is remembered in the browser."""

LIGHT = """--bg: #f4f5f7; --surface: #ffffff; --surface-2: #eef0f3; --text: #1a1d23; --muted: #646b78;
  --border: #e1e4e9; --accent: #1d5fd1; --accent-text: #ffffff; --accent-bg: #dce8fc;
  --bubble-in: #e9ebef; --bubble-out: #1d5fd1; --bubble-out-text: #ffffff; --bubble-fixed: #0f6b5c;
  --emergency: #b42318; --emergency-bg: #fde8e6; --urgent: #a15c07; --urgent-bg: #fdf0d8;
  --routine: #1c7b4b; --routine-bg: #ddf3e6; --unknown: #646b78; --unknown-bg: #eef0f3;
  --phone-frame: #1a1d23; --shadow: 0 1px 3px rgba(16, 24, 40, .08), 0 8px 24px rgba(16, 24, 40, .06);"""

DARK = """--bg: #0e1014; --surface: #171a20; --surface-2: #1f232a; --text: #e6e8eb; --muted: #9aa1ac;
  --border: #2a2f37; --accent: #79a5ff; --accent-text: #0e1014; --accent-bg: #1c2944;
  --bubble-in: #262b33; --bubble-out: #2f63c9; --bubble-out-text: #ffffff; --bubble-fixed: #1b7a69;
  --emergency: #ff8a7a; --emergency-bg: #3d1714; --urgent: #f5b851; --urgent-bg: #3a2a0c;
  --routine: #5fd497; --routine-bg: #0f3322; --unknown: #9aa1ac; --unknown-bg: #1f232a;
  --phone-frame: #000000; --shadow: 0 1px 3px rgba(0, 0, 0, .4), 0 8px 24px rgba(0, 0, 0, .3);"""

CSS = f""":root {{ {LIGHT} color-scheme: light; }}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{ {DARK} color-scheme: dark; }} }}
:root[data-theme="dark"] {{ {DARK} color-scheme: dark; }}
.theme-toggle {{ font: inherit; font-size: 13px; color: var(--text); background: var(--surface);
  border: 1px solid var(--border); border-radius: 999px; padding: 5px 12px; cursor: pointer; white-space: nowrap; }}
.theme-toggle:hover {{ border-color: var(--accent); }}"""

STORAGE_KEY = "missed-call-theme"

# Goes in <head> so the saved theme applies before the page paints (no flash)
HEAD_SCRIPT = f"""<script>try {{ var t = localStorage.getItem("{STORAGE_KEY}");
  if (t === "light" || t === "dark") document.documentElement.dataset.theme = t; }} catch (e) {{}}</script>"""

BUTTON = '<button type="button" class="theme-toggle" id="theme-toggle">◐ Auto</button>'

TOGGLE_SCRIPT = f"""<script>(function () {{
  var button = document.getElementById("theme-toggle"), root = document.documentElement;
  var order = ["auto", "light", "dark"], labels = {{auto: "◐ Auto", light: "☀ Light", dark: "☾ Dark"}};
  function current() {{ return root.dataset.theme || "auto"; }}
  function show() {{ button.textContent = labels[current()]; button.title = "Theme: " + current() + " (click to change)"; }}
  button.addEventListener("click", function () {{
    var next = order[(order.indexOf(current()) + 1) % order.length];
    if (next === "auto") delete root.dataset.theme; else root.dataset.theme = next;
    try {{ localStorage.setItem("{STORAGE_KEY}", next); }} catch (e) {{}}
    show();
  }});
  show();
}})();</script>"""
