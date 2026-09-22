/* Agentic Engineering System — لوحة البيئة والجاهزية (الأمر 009 §22).
 *
 * قسم في الإعدادات: ملخص (READY/…) + بطاقة لكل قدرة (الحالة، آخر فحص،
 * السبب، المزود/التكوين) + زر فحص لكل قدرة + فحص كامل + جرد البيئة.
 * لا READY بلا مسبار حقيقي — الواجهة تعرض ما في القاعدة بلا تجميل.
 */
(function () {
  "use strict";

  if (!window.Hub) return;
  var Hub = window.Hub;

  var capsCache = [];

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function statusLabel(status) {
    return {
      READY: "جاهز", DEGRADED: "متدهور", NOT_READY: "غير جاهز",
      UNAVAILABLE: "غير متاح", DISABLED: "معطّل", STALE: "منتهي الصلاحية",
      NOT_CONFIGURED: "غير معد", UNKNOWN: "غير مفحوص",
    }[status] || status;
  }

  function refreshSummary(summary) {
    var box = document.getElementById("env-summary");
    if (!box) return;
    box.textContent = "";
    ["READY", "DEGRADED", "NOT_READY", "UNAVAILABLE", "STALE",
        "NOT_CONFIGURED", "UNKNOWN"]
      .forEach(function (key) {
        var value = summary[key] || 0;
        if (!value) return;
        var chip = el("span", "env-chip " +
          (key === "READY" ? "ok" : (key === "DEGRADED" || key === "STALE"
            || key === "NOT_CONFIGURED" || key === "UNKNOWN")
            ? "" : "bad"));
        chip.innerHTML = "<b>" + value + "</b> " + statusLabel(key);
        box.appendChild(chip);
      });
  }

  function renderCapabilities(caps) {
    capsCache = caps;
    var grid = document.getElementById("env-caps");
    if (!grid) return;
    grid.textContent = "";
    caps.forEach(function (cap) {
      var card = el("div", "cap-card");
      card.setAttribute("data-cap", cap.capability_id);

      var head = el("div", "cap-head");
      var dot = el("span", "cap-dot " + cap.readiness_status);
      head.appendChild(dot);
      head.appendChild(el("span", "cap-name", cap.name));
      head.appendChild(el("span", "cap-cat", cap.category));
      var status = el("span", "cap-status",
        statusLabel(cap.readiness_status) +
        (cap.required ? " · مطلوب" : ""));
      status.className = "cap-status " + cap.readiness_status;
      head.appendChild(status);
      card.appendChild(head);

      var meta = el("div", "cap-meta");
      var bits = [];
      if (cap.last_probe_at) {
        bits.push("آخر فحص: " + new Date(cap.last_probe_at)
          .toLocaleTimeString("ar", { hour12: false }));
      }
      if (cap.probe_latency_ms) bits.push(Hub.fmtTime(cap.probe_latency_ms));
      if (cap.provider_id) bits.push(cap.provider_id);
      meta.textContent = bits.join(" · ") || "لم يُفحص بعد";
      card.appendChild(meta);

      if (cap.failure_reason && cap.readiness_status !== "READY") {
        card.appendChild(el("div", "cap-meta cap-reason",
          "السبب: " + cap.failure_reason));
      }
      var detail = (cap.details || {}).reason;
      if (detail && cap.readiness_status === "READY") {
        card.appendChild(el("div", "cap-meta", detail));
      }

      var actions = el("div", "cap-actions");
      var probeBtn = el("button", "btn ghost small", "فحص");
      probeBtn.addEventListener("click", function () {
        probeBtn.disabled = true;
        probeBtn.textContent = "…يفحص فعليًا";
        Hub.fetchJSON("/api/environment/probe", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ capability_id: cap.capability_id })
        }).then(function (out) {
          probeBtn.disabled = false;
          probeBtn.textContent = "فحص";
          if (out.ok) loadReadiness();
        }, function () {
          probeBtn.disabled = false;
          probeBtn.textContent = "فحص";
        });
      });
      actions.appendChild(probeBtn);
      card.appendChild(actions);

      grid.appendChild(card);
    });
  }

  function loadReadiness() {
    var grid = document.getElementById("env-caps");
    if (!grid) return;
    if (!grid.children.length) {
      grid.textContent = "…تحميل حالة القدرات";
    }
    Hub.fetchJSON("/api/environment/readiness").then(function (out) {
      if (!out.ok) {
        grid.textContent = "تعذر تحميل حالة القدرات";
        return;
      }
      refreshSummary(out.j.summary || {});
      renderCapabilities(out.j.capabilities || []);
    });
  }

  function wireFullCheck() {
    var btn = document.getElementById("env-run-all");
    var note = document.getElementById("env-note");
    if (!btn) return;
    btn.addEventListener("click", function () {
      btn.disabled = true;
      note.textContent = "…فحص كامل حقيقي لكل قدرة (قد يستغرق لحظات)";
      Hub.fetchJSON("/api/environment/probe/all", { method: "POST" })
        .then(function (out) {
          btn.disabled = false;
          if (out.ok) {
            note.textContent = "اكتمل الفحص الكامل — " +
              JSON.stringify(out.j.summary);
            loadReadiness();
          } else {
            note.textContent = "تعذر الفحص الكامل";
          }
        }, function () {
          btn.disabled = false;
          note.textContent = "تعذر الفحص الكامل";
        });
    });
  }

  function wireInventory() {
    var btn = document.getElementById("env-inventory");
    var box = document.getElementById("env-inventory-body");
    if (!btn || !box) return;
    btn.addEventListener("click", function () {
      btn.disabled = true;
      box.hidden = false;
      box.textContent = "…جرد فعلي للبيئة";
      Hub.fetchJSON("/api/environment/inventory").then(function (out) {
        btn.disabled = false;
        if (!out.ok) {
          box.textContent = "تعذر الجرد";
          return;
        }
        box.textContent = "";
        var items = out.j.items || {};
        Object.keys(items).forEach(function (key) {
          var item = items[key];
          var row = el("div", "cap-meta");
          row.textContent = key + ": " + statusLabel(item.status) +
            (item.version ? " — " + item.version : "") +
            (item.reason && item.status !== "READY" ? " (" + item.reason + ")" : "");
          box.appendChild(row);
        });
      }, function () {
        btn.disabled = false;
        box.textContent = "تعذر الجرد";
      });
    });
  }

  document.addEventListener("hub:open-settings", function () {
    loadReadiness();
  });

  window.EnvironmentUI = {
    init: function () {
      wireFullCheck();
      wireInventory();
      loadReadiness();
    },
    refresh: loadReadiness,
  };

  if (document.getElementById("env-caps")) {
    window.EnvironmentUI.init();
  }
})();
