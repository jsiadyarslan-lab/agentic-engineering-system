/* Agentic Engineering System — مزودو البحث (010 §24-§25 + 011 §12-§16).
 *
 * الإعدادات ← الأدوات والقدرات: بطاقة لكل مزود بحث بحالته المشتقة
 * الموحدة (effective_status) — مسبار READY قديم = STALE معلن، غير
 * المعد = NOT_CONFIGURED لا READY؛ حفظ التكوين = حفظ ← فحص حقيقي ←
 * جاهزية محدثة (011 §16). لا يمكن أن يقول المزود «جاهز» والقدرة
 * «منتهية» — الحالة واحدة من مصدر واحد.
 */
(function () {
  "use strict";

  if (!window.Hub) return;
  var Hub = window.Hub;
  var esc = Hub.esc;

  var STATUS_LABELS = {
    READY: "جاهز — مسبار حقيقي حديث", STALE: "منتهي الصلاحية — أعد الفحص",
    NOT_READY: "فحص فاشل — سبب معروف", NOT_CONFIGURED: "غير معد — عيّن تكوينه",
    UNKNOWN: "لم يُفحص بعد", DISABLED: "معطّل بقرار",
  };
  var STATUS_CLASSES = {
    READY: "ok", STALE: "wait", NOT_READY: "bad",
    NOT_CONFIGURED: "wait", UNKNOWN: "wait", DISABLED: "wait",
  };

  function root() { return document.getElementById("research-providers"); }

  function load() {
    var el = root();
    if (!el) return;
    el.innerHTML = '<div class="env-loading">جارٍ تحميل مزودي البحث…</div>';
    Hub.fetchJSON("/api/research/providers").then(function (out) {
      if (!out.ok) {
        el.innerHTML = '<div class="env-err">تعذر التحميل — ' +
          esc(out.j && out.j.detail || "") + "</div>";
        return;
      }
      render(out.j.providers || []);
    }, function () {
      el.innerHTML = '<div class="env-err">تعذر الوصول للخدمة</div>';
    });
  }

  function render(providers) {
    var el = root();
    var html = "";
    if (!providers.length) {
      html = '<div class="env-empty">لا مزودي بحث مسجلين</div>';
    }
    providers.forEach(function (p) {
      var config = p.config || {};
      var needsUrl = p.kind === "search_searx";
      var needsEndpoint = p.kind === "search_api";
      var status = p.effective_status || p.last_probe_status || "UNKNOWN";
      html += '<div class="rp-card" data-id="' + p.id + '">' +
        '<div class="rp-head">' +
        '<span class="rp-name">' + esc(p.name) + "</span>" +
        '<span class="rp-status ' + (STATUS_CLASSES[status] || "wait") + '">' +
        esc(STATUS_LABELS[status] || status) +
        "</span>" +
        (p.enabled ? "" : '<span class="rp-off">معطّل</span>') +
        "</div>" +
        (p.state_reason && status !== "READY"
          ? '<div class="env-reason">' + esc(String(p.state_reason).slice(0, 200)) + "</div>"
          : "") +
        '<div class="rp-config">' +
        (needsUrl
          ? '<label>رابط المثيل<input class="rp-url" dir="ltr" placeholder="https://searx.example.org" value="' +
            esc(config.base_url || "") + '"></label>' : "") +
        (needsEndpoint
          ? '<label>نقطة النهاية<input class="rp-endpoint" dir="ltr" placeholder="https://api.search.example/v1/search" value="' +
            esc(config.endpoint || "") + '"></label>' +
            '<label>النمط<select class="rp-style">' +
            ["generic_results", "tavily", "brave"].map(function (s) {
              return '<option value="' + s + '"' +
                (config.style === s ? " selected" : "") + ">" + s + "</option>";
            }).join("") + "</select></label>" +
            '<label>المفتاح (يُخزن محليًا)<input class="rp-key" type="password" dir="ltr" placeholder="لا يُعاد أبدًا بعد الحفظ"></label>'
          : "") +
        (needsUrl || needsEndpoint
          ? '<label class="rp-enabled"><input type="checkbox" class="rp-enabled-chk"' +
            (p.enabled ? " checked" : "") + "> مُفعّل</label>" : "") +
        "</div>" +
        '<div class="rp-actions">' +
        '<button class="pv-btn primary rp-probe" data-id="' + p.id +
        '">فحص حقيقي</button>' +
        (needsUrl || needsEndpoint
          ? '<button class="pv-btn rp-save" data-id="' + p.id + '">حفظ التكوين</button>'
          : "") +
        "</div>" +
        '<div class="rp-result" id="rp-result-' + p.id + '" hidden></div>' +
        "</div>";
    });
    el.innerHTML = html;
    wire();
  }

  function wire() {
    var el = root();
    el.querySelectorAll(".rp-probe").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var id = btn.getAttribute("data-id");
        btn.disabled = true;
        btn.textContent = "…يفحص فعليًا";
        Hub.fetchJSON("/api/research/providers/" + id + "/probe",
          { method: "POST" }).then(function (out) {
          btn.disabled = false;
          btn.textContent = "فحص حقيقي";
          showResult(id, out);
          load();
        }, function () {
          btn.disabled = false;
          btn.textContent = "فحص حقيقي";
        });
      });
    });
    el.querySelectorAll(".rp-save").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var card = btn.closest(".rp-card");
        var id = btn.getAttribute("data-id");
        var kind = card.getAttribute("data-kind") || "";
        var config = {};
        var urlInput = card.querySelector(".rp-url");
        var endpointInput = card.querySelector(".rp-endpoint");
        var styleSel = card.querySelector(".rp-style");
        if (urlInput) config.base_url = urlInput.value.trim();
        if (endpointInput) config.endpoint = endpointInput.value.trim();
        if (styleSel) config.style = styleSel.value;
        var enabledChk = card.querySelector(".rp-enabled-chk");
        var keyInput = card.querySelector(".rp-key");
        btn.disabled = true;
        btn.textContent = "…يحفظ";
        Hub.fetchJSON("/api/research/providers/" + id + "/configure", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            config: config,
            enabled: enabledChk ? enabledChk.checked : null,
            api_key: keyInput && keyInput.value ? keyInput.value : "",
          }),
        }).then(function (out) {
          btn.disabled = false;
          btn.textContent = "حفظ التكوين";
          if (out.ok) {
            if (keyInput) keyInput.value = "";
            // (011 §16) الخادم فحص فور الحفظ — اعرض نتيجة الفحص نفسها
            var eff = out.j.effective_status || "";
            showResult(id, {
              ok: true,
              j: {
                status: eff === "READY" ? "READY" : (eff || "UNKNOWN"),
                reason: out.j.state_reason ||
                  "حُفظ وفُحص فورًا — الحالة أعلاه من الفحص الحقيقي",
              },
            });
            load();
          } else {
            showResult(id, out);
          }
        });
      });
    });
  }

  function showResult(id, out) {
    var box = document.getElementById("rp-result-" + id);
    if (!box) return;
    box.hidden = false;
    if (!out.ok) {
      box.innerHTML = '<div class="env-err">' +
        esc(out.j && out.j.detail || "فشل") + "</div>";
      return;
    }
    var status = out.j.status || "";
    var reason = out.j.reason || "";
    box.innerHTML = '<div class="' + (status === "READY" ? "env-verify-head ok"
      : "env-err") + '">' +
      (status === "READY" ? "✓ " : "✕ ") + esc(status) +
      (reason ? " — " + esc(reason.slice(0, 160)) : "") + "</div>";
  }

  window.ResearchUI = { load: load };
})();
