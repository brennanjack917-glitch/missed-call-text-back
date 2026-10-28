// Owner view: status changes save right away, notes save a moment after you stop typing.
(function () {
  function save(card, data) {
    var saved = card.querySelector(".saved");
    saved.textContent = "Saving…";
    return fetch("/api/leads/" + card.dataset.id, {
      method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(data)
    }).then(function (r) {
      if (!r.ok) throw new Error();
      return r.json();
    }).then(function (body) {
      saved.textContent = "Saved";
      Object.keys(body.counts).forEach(function (status) {
        var el = document.querySelector('[data-count="' + status + '"]');
        if (el) el.textContent = body.counts[status];
      });
    }).catch(function () { saved.textContent = "Couldn't save. Is the demo server still running?"; });
  }

  document.querySelectorAll(".lead").forEach(function (card) {
    card.querySelector(".lead-status").addEventListener("change", function (event) {
      save(card, {status: event.target.value}).then(function () {
        card.classList.toggle("lead-emergency", event.target.value !== "closed" &&
                              card.querySelector(".badge-emergency") !== null);
      });
    });
    var timer = null, notes = card.querySelector("textarea");
    notes.addEventListener("input", function () {
      clearTimeout(timer);
      card.querySelector(".saved").textContent = "";
      timer = setTimeout(function () { save(card, {notes: notes.value}); }, 600);
    });
  });

  var clear = document.getElementById("clear-data");
  clear.addEventListener("click", function () {
    if (!confirm("Delete every lead, conversation and saved email? This can't be undone.")) return;
    fetch("/api/clear", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({confirm: true})})
      .then(function (r) { if (!r.ok) throw new Error(); window.location = "/owner"; })
      .catch(function () { alert("Couldn't clear the data. Is the demo server still running?"); });
  });

  // Changing a filter applies it straight away
  document.querySelectorAll(".filters select").forEach(function (select) {
    select.addEventListener("change", function () { select.form.submit(); });
  });
})();
