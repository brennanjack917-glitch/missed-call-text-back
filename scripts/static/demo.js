// Demo page: you play the customer. Every text is shown with textContent, never as HTML,
// so whatever a customer (or the AI) types can't run as code on the page.
(function () {
  var SOURCES = window.DEMO.sources;
  var STORAGE_KEY = "missed-call-demo-caller";
  var $ = function (id) { return document.getElementById(id); };
  var chat = $("chat"), input = $("message"), send = $("send");
  var caller = null, busy = false;

  function remember(value) {
    try { value ? localStorage.setItem(STORAGE_KEY, value) : localStorage.removeItem(STORAGE_KEY); } catch (e) {}
  }

  function post(url, data) {
    return fetch(url, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(data)})
      .then(function (r) { return r.json().catch(function () { return {}; }).then(function (body) {
        if (!r.ok) throw new Error(body.error || "Something went wrong (" + r.status + ").");
        return body;
      }); });
  }

  function bubble(from, text, meta) {
    var row = document.createElement("div");
    row.className = "bubble-row " + (from === "customer" ? "from-customer" : "from-business");
    var b = document.createElement("div");
    b.className = "bubble" + (from === "fixed" ? " bubble-fixed" : "");
    b.textContent = text;
    row.appendChild(b);
    if (meta) {
      var m = document.createElement("div");
      m.className = "bubble-meta";
      m.textContent = meta;
      row.appendChild(m);
    }
    chat.appendChild(row);
    return row;
  }

  function note(text) {
    var n = document.createElement("div");
    n.className = "chat-note";
    n.textContent = text;
    chat.appendChild(n);
  }

  function typing() {
    var row = bubble("assistant", "");
    row.classList.add("typing");
    row.firstChild.innerHTML = "<span>●</span><span>●</span><span>●</span>";  // fixed markup, no user text
    chat.scrollTop = chat.scrollHeight;
    return row;
  }

  function render(state) {
    caller = state.caller;
    $("caller").textContent = caller || "none yet";
    var conv = state.conversation;
    chat.textContent = "";
    if (!conv) { chat.appendChild(emptyMessage); return setInput(false); }
    note("Missed call from " + caller);
    state.messages.forEach(function (m) {
      bubble(m.from, m.body, m.from === "customer" ? "" : SOURCES[m.from]);
    });
    var active = conv.status === "active";
    if (!active) note(conv.status === "opted_out" ? "Opted out: no more texts." : "Conversation finished.");
    chat.scrollTop = chat.scrollHeight;
    setInput(active);

    var lead = state.lead;
    document.querySelectorAll("#lead-fields [data-field]").forEach(function (dd) {
      dd.textContent = lead[dd.dataset.field] || "—";
    });
    var badge = $("urgency-badge");
    badge.hidden = !lead.urgency || lead.urgency === "unknown";
    badge.className = "badge badge-" + lead.urgency;
    badge.textContent = lead.urgency === "emergency" ? "🚨 Emergency" : lead.urgency;
    $("status-line").textContent = {
      active: "Collecting details…",
      complete: "Complete: the lead is on the owner page.",
      handed_off: "Handed to a person: " + (conv.handoff_reason || "see conversation") + ".",
      opted_out: "The customer opted out."
    }[conv.status] || conv.status;

    var link = $("email-link");
    link.hidden = !state.email_preview;
    if (state.email_preview) link.href = state.email_preview;

    var events = $("events");
    events.textContent = "";
    state.events.forEach(function (line) {
      var li = document.createElement("li");
      li.textContent = line;
      events.appendChild(li);
    });
    $("cost").textContent = state.cost.calls
      ? state.cost.calls + " AI call" + (state.cost.calls === 1 ? "" : "s") + " · about $" + state.cost.dollars.toFixed(4)
      : "";
    $("reset").hidden = false;
  }

  function setInput(enabled) {
    input.disabled = send.disabled = !enabled || busy;
    input.placeholder = enabled ? "Type as the customer…" : (caller ? "Conversation finished" : "Simulate a missed call first");
    if (enabled && !busy) input.focus();
  }

  function fail(error) {
    note(error.message);
    busy = false;
    setInput(true);
  }

  var emptyMessage = $("chat-empty");

  $("call").addEventListener("click", function () {
    $("call").disabled = true;
    post("/api/call", {}).then(function (state) { remember(state.caller); render(state); })
      .catch(function (e) { note(e.message); })
      .finally(function () { $("call").disabled = false; });
  });

  $("reset").addEventListener("click", function () {
    remember(null);
    render({caller: null, conversation: null});
    $("reset").hidden = true;
    ["urgency-badge", "email-link"].forEach(function (id) { $(id).hidden = true; });
    $("status-line").textContent = "No lead yet.";
    document.querySelectorAll("#lead-fields [data-field]").forEach(function (dd) { dd.textContent = "—"; });
    $("events").textContent = "";
    $("cost").textContent = "";
  });

  $("composer").addEventListener("submit", function (event) {
    event.preventDefault();
    var text = input.value.trim();
    if (!text || busy || !caller) return;
    busy = true;
    input.value = "";
    bubble("customer", text);
    setInput(false);
    var dots = typing();
    post("/api/text", {caller: caller, text: text})
      .then(function (state) { busy = false; render(state); })
      .catch(function (e) { dots.remove(); fail(e); });
  });

  $("send-email").addEventListener("change", function (event) {
    post("/api/settings", {send_email: event.target.checked})
      .then(function (r) { event.target.checked = r.send_email; })
      .catch(function () { event.target.checked = !event.target.checked; });
  });

  // Pick up where you left off after a page reload
  var saved = null;
  try { saved = localStorage.getItem(STORAGE_KEY); } catch (e) {}
  if (saved) {
    fetch("/api/state?caller=" + encodeURIComponent(saved)).then(function (r) { return r.ok ? r.json() : null; })
      .then(function (state) { if (state && state.conversation) render(state); else remember(null); });
  }
})();
