/* agent hub v2 — لوحة الإعدادات: نموذج لكل دور + المزودات والمفاتيح.
 * الأمر 006 §5: ليست modal بدائية — لوحة جانبية حقيقية: لكل دور
 * مزود + نموذج، وحالة المزود الصادقة (متاح/غير متصل/نماذج معلنة —
 * الاتصال غير متاح)، والحفظ عبر PUT /api/models/config.
 */
(function () {
  "use strict";

  if (!window.Hub) return;
  var Hub = window.Hub;
  var $ = Hub.$;

  var drawer = $("settings-drawer");
  var backdrop = $("drawer-backdrop");
  var roleModelsEl = $("role-models");
  var providersBody = $("providers-body");
  var saveResultEl = $("models-save-result");

  // نموذج خام للقوائم: known + default (والمزود الحي يُدمج عند الجلب)
  var providerModelCache = {};

  function openDrawer() {
    drawer.hidden = false;
    backdrop.hidden = false;
    loadModelsConfig();
    loadProviders();
  }

  function closeDrawer() {
    drawer.hidden = true;
    backdrop.hidden = true;
  }

  $("settings-open").addEventListener("click", openDrawer);
  $("settings-close").addEventListener("click", closeDrawer);
  backdrop.addEventListener("click", closeDrawer);
  document.addEventListener("hub:open-settings", openDrawer);

  // ---------- إعدادات النماذج: دور × مزود × نموذج ----------

  function loadModelsConfig() {
    roleModelsEl.textContent = "جارٍ التحميل…";
    Hub.fetchJSON("/api/models/config").then(function (out) {
      if (!out.ok) {
        roleModelsEl.textContent = "تعذر تحميل الإعدادات";
        return;
      }
      Hub.state.modelsConfig = out.j;
      renderRoleModels(out.j);
      Hub.state.mode === "task" && document.dispatchEvent(new Event("hub:refresh-task-settings"));
    });
  }

  // إعادة رسم ملخص إعدادات المهمة فوق الـcomposer عند تغيّر الإعدادات
  document.addEventListener("hub:refresh-task-settings", function () {
    // استدعاء داخلي عبر حدث مخصص — نفس منطق app.js
    var body = $("task-settings-body");
    var cfg = Hub.state.modelsConfig;
    if (!body || !cfg || !cfg.roles) return;
    var rows = cfg.roles
      .filter(function (r) { return r.key !== "chat"; })
      .map(function (r) {
        return '<div class="ts-row"><span>' + Hub.esc(r.label) + "</span>" +
          '<span class="ts-model" dir="ltr">' + Hub.esc(r.selection.provider) +
          " / " + Hub.esc(r.selection.model) + "</span></div>";
      }).join("");
    body.innerHTML = rows +
      '<div class="ts-hint">غيّر النماذج من ⚙ الإعدادات — لكل دور اختياره المستقل.</div>';
  });

  function providerLabel(id, providers) {
    var found = providers.filter(function (p) { return p.id === id; })[0];
    return found ? found.label : id;
  }

  function providerStateBadge(provider) {
    var av = provider.availability || {};
    if (av.available) return '<span class="pv-src live">متاح</span>';
    return '<span class="pv-src declared">غير متصل — ' +
      Hub.esc(av.reason || "بلا مفتاح") + "</span>";
  }

  function renderRoleModels(config) {
    roleModelsEl.textContent = "";
    if (config.warning) {
      roleModelsEl.appendChild((function () {
        var w = document.createElement("div");
        w.className = "drawer-warning";
        w.textContent = config.warning;
        return w;
      })());
    }
    config.roles.forEach(function (role) {
      var box = document.createElement("div");
      box.className = "role-config";
      box.setAttribute("data-role", role.key);

      var head = document.createElement("div");
      head.className = "role-config-head";
      head.appendChild((function () {
        var name = document.createElement("span");
        name.textContent = role.label;
        return name;
      })());
      if (role.is_default) {
        head.appendChild((function () {
          var badge = document.createElement("span");
          badge.className = "default-badge";
          badge.textContent = "افتراضي";
          return badge;
        })());
      }
      box.appendChild(head);

      var row = document.createElement("div");
      row.className = "role-config-row";

      var providerSel = document.createElement("select");
      providerSel.className = "sel-provider";
      config.providers.forEach(function (p) {
        var opt = document.createElement("option");
        opt.value = p.id;
        opt.textContent = p.label;
        if (p.id === role.selection.provider) opt.selected = true;
        providerSel.appendChild(opt);
      });
      row.appendChild(providerSel);

      var modelSel = document.createElement("select");
      modelSel.className = "sel-model";
      row.appendChild(modelSel);

      var stateBox = document.createElement("div");
      stateBox.className = "role-provider-state";
      row.appendChild(stateBox);

      box.appendChild(row);
      roleModelsEl.appendChild(box);

      function refreshProviderState() {
        var pid = providerSel.value;
        var provider = config.providers.filter(function (p) {
          return p.id === pid;
        })[0];
        stateBox.innerHTML = provider ? providerStateBadge(provider) : "";
      }

      function fillModels(models, source) {
        var current = modelSel.getAttribute("data-chosen") ||
          role.selection.model;
        modelSel.textContent = "";
        var seen = {};
        models.forEach(function (m) {
          if (seen[m]) return;
          seen[m] = true;
          var opt = document.createElement("option");
          opt.value = m;
          opt.textContent = m;
          if (m === current) opt.selected = true;
          modelSel.appendChild(opt);
        });
        if (source === "declared") {
          var note = document.createElement("option");
          note.disabled = true;
          note.textContent = "— نماذج معلنة (الاتصال غير متاح) —";
          modelSel.insertBefore(note, modelSel.firstChild);
        }
        modelSel.setAttribute("data-chosen", current);
      }

      function loadModelsFor(providerId) {
        var provider = config.providers.filter(function (p) {
          return p.id === providerId;
        })[0];
        var declared = (provider && provider.known_models &&
          provider.known_models.slice()) || [];
        if (provider && provider.default_model &&
            declared.indexOf(provider.default_model) === -1) {
          declared.unshift(provider.default_model);
        }
        fillModels(declared, "declared");
        refreshProviderState();
        // محاولة الجلب الحي — إن نجحت تُدمج القائمة الحية بوسمها
        Hub.fetchJSON("/api/providers/" + providerId + "/models")
          .then(function (out) {
            if (!out.ok) return;
            var j = out.j;
            var live = (j.source === "live" && j.model_ids) ? j.model_ids.slice() : [];
            var merged = live.length ? live.concat(declared) : declared;
            fillModels(merged, live.length ? "live" : "declared");
          });
      }

      providerSel.addEventListener("change", function () {
        modelSel.removeAttribute("data-chosen");
        loadModelsFor(providerSel.value);
      });
      modelSel.addEventListener("change", function () {
        modelSel.setAttribute("data-chosen", modelSel.value);
      });

      loadModelsFor(role.selection.provider);
    });
  }

  $("models-save").addEventListener("click", function () {
    var btn = this;
    btn.disabled = true;
    saveResultEl.textContent = "جارٍ الحفظ…";
    var payload = {};
    var boxes = roleModelsEl.querySelectorAll(".role-config");
    var any = false;
    boxes.forEach(function (box) {
      var role = box.getAttribute("data-role");
      var provider = box.querySelector(".sel-provider").value;
      var model = box.querySelector(".sel-model").value;
      if (provider && model) {
        payload[role] = { provider: provider, model: model };
        any = true;
      }
    });
    if (!any) {
      saveResultEl.textContent = "لا اختيارات للحفظ";
      btn.disabled = false;
      return;
    }
    Hub.fetchJSON("/api/models/config", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    }).then(function (out) {
      btn.disabled = false;
      if (out.ok) {
        saveResultEl.textContent = "✔ حُفظت — المهام القادمة تستخدمها";
        loadModelsConfig();
      } else {
        saveResultEl.textContent = "✕ " + (out.j.detail || "فشل الحفظ");
      }
    });
  });

  // ---------- المزودات والمفاتيح (منقول من الواجهة السابقة) ----------

  function pvModelsHtml(models, defaultModel, source) {
    if (!Array.isArray(models) || !models.length) return "";
    var chips = models.map(function (m) {
      return '<span class="pv-chip' + (m === defaultModel ? " default" : "") + '">' +
        Hub.esc(m) + (m === defaultModel ? " · الافتراضي" : "") + "</span>";
    }).join("");
    var srcLabel = source === "live"
      ? '<span class="pv-src live">● جُلبت حيًا الآن</span>'
      : '<span class="pv-src declared">◇ معلنة من البطاقة — الاتصال غير متاح</span>';
    return '<div class="pv-models">' + chips + srcLabel + "</div>";
  }

  function loadProviders() {
    if (!providersBody) return;
    providersBody.textContent = "جارٍ التحميل…";
    Hub.fetchJSON("/api/providers").then(function (out) {
      if (!out.ok) return;
      var data = out.j;
      var htmlParts = [];
      var store = data.store || {};
      htmlParts.push(
        '<div class="pv-store"><b>المخزن المحلي:</b> ' +
        Hub.esc(store.warning || store.file || "") +
        " · التشفير: " +
        (store.encryption_available ? "DPAPI (Windows)" : "صلاحيات 600") +
        "</div>"
      );
      (data.providers || []).forEach(function (p) {
        htmlParts.push(
          '<div class="pv-card" data-provider="' + Hub.esc(p.id) + '" data-default="' + Hub.esc(p.model) + '">' +
          '<div class="pv-head">' +
          '<span class="pv-title">' + Hub.esc(p.label) + "</span>" +
          '<span class="pv-status ' + (p.has_key ? "ok" : "none") + '">' +
          (p.has_key ? ("مفتاح محفوظ " + Hub.esc(p.key_masked)) : (p.requires_key ? "بلا مفتاح" : "بلا مفتاح مطلوب")) +
          "</span></div>" +
          '<div class="pv-meta">' + Hub.esc(p.base_url) +
          " · الافتراضي: " + Hub.esc(p.model) + "</div>" +
          '<div class="pv-note">' + Hub.esc(p.note || "") + "</div>"
        );
        if (p.requires_key) {
          htmlParts.push(
            '<div class="pv-row">' +
            '<input type="password" data-provider="' + Hub.esc(p.id) + '" class="pv-input" ' +
            'placeholder="مفتاح API — يُخزَّن مشفّرًا محليًا فقط">' +
            '<button class="pv-btn primary prov-save" data-provider="' + Hub.esc(p.id) + '">حفظ المفتاح</button>' +
            '<button class="pv-btn danger prov-delete" data-provider="' + Hub.esc(p.id) + '">حذف</button>' +
            "</div>"
          );
        }
        htmlParts.push(
          '<div class="pv-row">' +
          '<button class="pv-btn prov-test" data-provider="' + Hub.esc(p.id) + '">اختبار الاتصال</button>' +
          '<button class="pv-btn prov-models" data-provider="' + Hub.esc(p.id) + '">قائمة النماذج</button>' +
          "</div>" +
          '<div class="pv-result" data-provider="' + Hub.esc(p.id) + '"></div>' +
          '<div class="pv-models-box" data-provider="' + Hub.esc(p.id) + '">' +
          pvModelsHtml(p.known_models, p.model, "declared") +
          "</div></div>"
        );
      });
      providersBody.innerHTML = htmlParts.join("");
      wireProviderButtons();
    });
  }

  function wireProviderButtons() {
    providersBody.querySelectorAll(".prov-save").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var name = btn.getAttribute("data-provider");
        var input = providersBody.querySelector('.pv-input[data-provider="' + name + '"]');
        var result = providersBody.querySelector('.pv-result[data-provider="' + name + '"]');
        btn.disabled = true;
        Hub.fetchJSON("/api/providers/" + name + "/key", {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ key: input.value })
        }).then(function (out) {
          result.textContent = out.ok
            ? "✔ حُفظ (" + (out.j.key_masked || "") + ")"
            : "✕ " + (out.j.detail || "فشل الحفظ");
          if (out.ok) { input.value = ""; loadProviders(); loadModelsConfig(); }
        }).finally(function () { btn.disabled = false; });
      });
    });
    providersBody.querySelectorAll(".prov-delete").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var name = btn.getAttribute("data-provider");
        Hub.fetchJSON("/api/providers/" + name + "/key", { method: "DELETE" })
          .then(function () { loadProviders(); });
      });
    });
    providersBody.querySelectorAll(".prov-test").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var name = btn.getAttribute("data-provider");
        var result = providersBody.querySelector('.pv-result[data-provider="' + name + '"]');
        btn.disabled = true;
        result.textContent = "…اختبار الاتصال";
        Hub.fetchJSON("/api/providers/" + name + "/test", { method: "POST" })
          .then(function (out) {
            result.textContent = out.j.ok
              ? "✔ اتصال ناجح (" + out.j.models_count + " نموذج، " + out.j.latency_ms + "ms)"
              : "✕ " + (out.j.message || "فشل الاتصال");
          })
          .finally(function () { btn.disabled = false; });
      });
    });
    providersBody.querySelectorAll(".prov-models").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var name = btn.getAttribute("data-provider");
        var result = providersBody.querySelector('.pv-result[data-provider="' + name + '"]');
        result.textContent = "…جلب قائمة النماذج";
        btn.disabled = true;
        Hub.fetchJSON("/api/providers/" + name + "/models?refresh=1")
          .then(function (out) {
            var j = out.j;
            result.textContent = j.ok
              ? "اتصال ناجح — " + (j.models_count || 0) + " نموذج"
              : (j.message || "تعذر الجلب الحي — النماذج المعلنة معروضة");
            var modelsBox = providersBody.querySelector('.pv-models-box[data-provider="' + name + '"]');
            if (modelsBox) {
              var card = providersBody.querySelector('.pv-card[data-provider="' + name + '"]');
              var def = card ? (card.getAttribute("data-default") || "") : "";
              modelsBox.innerHTML = pvModelsHtml(j.model_ids, def, j.source || "declared");
            }
          })
          .finally(function () { btn.disabled = false; });
      });
    });
  }

  // ---------- الأدوات المتقدمة ----------
  $("eoe-run").addEventListener("click", function () {
    closeDrawer();
    Hub.runAdvanced("eoe");
  });
  $("router-demo").addEventListener("click", function () {
    closeDrawer();
    Hub.runAdvanced("router-demo");
  });
  $("mission-run").addEventListener("click", function () {
    closeDrawer();
    Hub.runAdvanced("mission");
  });
  $("build-run").addEventListener("click", function () {
    closeDrawer();
    Hub.runAdvanced("build");
  });
})();
