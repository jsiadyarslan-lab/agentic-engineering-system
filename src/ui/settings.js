/* Agentic Engineering System — لوحة الإعدادات (الأمر 007.1).
 * نموذج لكل دور (مزود + تكوين + نموذج) من السجل الدائم، وإدارة مزودين
 * كاملة: إضافة/تعديل/حذف مزود وتكوينات Base URL واختبار جاهزية حقيقي
 * بتصنيف صادق (READY/NOT_FOUND/…) — والمفاتيح في مخزن الأسرار فقط.
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

  var providersCache = [];   // آخر قائمة مزودين من السجل الدائم
  var configCache = {};      // آخر إعدادات الأدوار

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

  // ---------- إعدادات النماذج: دور × مزود × تكوين × نموذج ----------

  function loadModelsConfig() {
    roleModelsEl.textContent = "جارٍ التحميل…";
    Hub.fetchJSON("/api/models/config").then(function (out) {
      if (!out.ok) {
        roleModelsEl.textContent = "تعذر تحميل الإعدادات";
        return;
      }
      configCache = out.j;
      Hub.state.modelsConfig = out.j;
      renderRoleModels(out.j);
      document.dispatchEvent(new Event("hub:refresh-task-settings"));
    });
  }

  function providerByName(name) {
    return providersCache.filter(function (p) { return p.name === name; })[0];
  }

  function readinessBadge(status) {
    var cls = status === "READY" ? "ok" : (status === "UNTESTED" ? "" : "bad");
    return '<span class="rd-badge ' + cls + '">' + Hub.esc(status || "UNTESTED") + "</span>";
  }

  function renderRoleModels(config) {
    roleModelsEl.textContent = "";
    config.roles.forEach(function (role) {
      var box = document.createElement("div");
      box.className = "role-config";
      box.setAttribute("data-role", role.key);

      var head = document.createElement("div");
      head.className = "role-config-head";
      var name = document.createElement("span");
      name.textContent = role.label;
      head.appendChild(name);
      if (role.is_default) {
        var badge = document.createElement("span");
        badge.className = "default-badge";
        badge.textContent = "افتراضي";
        head.appendChild(badge);
      }
      box.appendChild(head);

      var row = document.createElement("div");
      row.className = "role-config-row";

      var providerSel = document.createElement("select");
      providerSel.className = "sel-provider";
      config.providers.forEach(function (p) {
        var opt = document.createElement("option");
        opt.value = p.id;   // المعرف في الربط = اسم المزود
        opt.textContent = p.label;
        if (p.id === role.selection.provider) opt.selected = true;
        providerSel.appendChild(opt);
      });
      row.appendChild(providerSel);

      var configSel = document.createElement("select");
      configSel.className = "sel-config";
      row.appendChild(configSel);

      // منتقي النماذج الحقيقي (008 §7-§11): بحث + تمرير + لوحة مفاتيح
      // + اكتشاف حي — لا select من نموذجين أبدًا.
      var modelBtn = document.createElement("button");
      modelBtn.type = "button";
      modelBtn.className = "sel-model-btn";
      modelBtn.dir = "ltr";
      row.appendChild(modelBtn);
      var chosenModel = { value: role.selection.model || "" };

      box.appendChild(row);
      roleModelsEl.appendChild(box);

      function fillConfigs() {
        var provider = providerByName(providerSel.value) ||
          (config.providers.filter(function (p) {
            return p.id === providerSel.value;
          })[0] || { configurations: [] });
        var current = configSel.getAttribute("data-chosen") ||
          (role.selection.configuration || "");
        configSel.textContent = "";
        (provider.configurations || []).forEach(function (c) {
          var opt = document.createElement("option");
          opt.value = c.name;
          opt.textContent = c.is_primary ? (c.name + " · أساسي") : c.name;
          if ((c.name || "default") === (current || "default")) opt.selected = true;
          configSel.appendChild(opt);
        });
        fillModels(provider);
      }

      function fillModels(provider) {
        var cfgName = configSel.value || "default";
        var cfg = (provider.configurations || []).filter(function (c) {
          return c.name === cfgName;
        })[0] || (provider.configurations || [])[0] || {};
        if (!chosenModel.value) chosenModel.value = cfg.default_model || "";
        modelBtn.textContent = chosenModel.value || "اختر نموذجًا…";
        modelBtn.classList.toggle("empty", !chosenModel.value);
        modelBtn.onclick = function () {
          if (!window.ModelPicker) return;
          window.ModelPicker.open({
            anchor: modelBtn,
            current: chosenModel.value,
            provider: { id: provider.id, name: provider.name },
            configuration: { id: cfg.id, name: cfg.name },
            models: (cfg.models || []).slice(),
            onPick: function (model) {
              chosenModel.value = model;
              modelBtn.textContent = model;
              modelBtn.classList.remove("empty");
            },
            onManual: function (model) {
              // نموذج يدوي (§9): يُضاف للتكوين فورًا ليصبح معلنًا
              Hub.fetchJSON("/api/provider-configurations/" + cfg.id, {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ models: [].concat(cfg.models || [], [model]) })
              }).then(function () {
                chosenModel.value = model;
                modelBtn.textContent = model;
                loadModelsConfig();
              });
            },
          });
        };
      }

      providerSel.addEventListener("change", function () {
        configSel.removeAttribute("data-chosen");
        chosenModel.value = "";
        fillConfigs();
      });
      configSel.addEventListener("change", function () {
        configSel.setAttribute("data-chosen", configSel.value);
        chosenModel.value = "";
        fillConfigs();
      });

      fillConfigs();
    });
  }

  // ---------- حفظ الربط الدائم ----------

  $("models-save").addEventListener("click", function () {
    var btn = this;
    btn.disabled = true;
    saveResultEl.textContent = "جارٍ الحفظ…";
    var payload = {};
    var any = false;
    roleModelsEl.querySelectorAll(".role-config").forEach(function (box) {
      var role = box.getAttribute("data-role");
      var provider = box.querySelector(".sel-provider").value;
      var configuration = box.querySelector(".sel-config").value || "default";
      var model = box.querySelector(".sel-model-btn").textContent.trim();
      if (model === "اختر نموذجًا…") model = "";
      if (provider && model) {
        payload[role] = {
          provider: provider, configuration: configuration, model: model
        };
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
        saveResultEl.textContent = "✔ حُفظ في السجل الدائم — المهام القادمة تستخدمه";
        loadModelsConfig();
      } else {
        saveResultEl.textContent = "✕ " + (out.j.detail || "فشل الحفظ");
      }
    });
  });

  // ---------- إدارة المزودين: بطاقات من السجل الدائم ----------

  function esc(s) { return Hub.esc(s); }

  function configCardHtml(p, c) {
    var html = '<div class="cfg-card" data-cfg="' + c.id + '" data-provider="' + esc(p.name) + '">' +
      '<div class="cfg-head"><span class="cfg-name">' + esc(c.name) +
      (c.is_primary ? ' <span class="cfg-primary">أساسي</span>' : "") + "</span>" +
      readinessBadge(c.readiness && c.readiness.status) + "</div>" +
      '<div class="cfg-url" dir="ltr"><input class="cfg-url-input" value="' +
      esc(c.base_url) + '" dir="ltr" spellcheck="false">' +
      '<button class="pv-btn cfg-url-save" data-cfg="' + c.id + '">حفظ العنوان</button></div>' +
      '<div class="cfg-meta">النموذج الافتراضي: <b dir="ltr">' + esc(c.default_model || "—") +
      "</b> · النمط: " + esc(c.api_style) + (c.enabled ? "" : " · معطّل") + "</div>";

    html += '<div class="cfg-models">' +
      (c.models || []).map(function (m) {
        return '<span class="pv-chip' + (m === c.default_model ? " default" : "") +
          '">' + esc(m) + (m === c.default_model ? " · الافتراضي" : "") + "</span>";
      }).join("") + "</div>";

    html += '<div class="cfg-add-model">' +
      '<input class="pv-input new-model" placeholder="اسم نموذج جديد (يدويًا)">' +
      '<button class="pv-btn model-add" data-cfg="' + c.id + '">إضافة نموذج</button></div>';

    if (p.auth_type === "bearer") {
      html += '<div class="pv-row">' +
        '<input type="password" class="pv-input key-input" placeholder="' +
        (p.key_masked ? ("مفتاح جديد (المحفوظ: " + esc(p.key_masked) + ")")
          : "مفتاح API — يُخزَّن محليًا فقط") + '">' +
        '<button class="pv-btn primary key-save" data-name="' + esc(p.name) + '">حفظ المفتاح</button>' +
        '<button class="pv-btn danger key-delete" data-name="' + esc(p.name) + '">حذف المفتاح</button></div>';
    }

    html += '<div class="pv-row">' +
      '<button class="pv-btn primary cfg-test" data-cfg="' + c.id + '">اختبار الاتصال</button>' +
      '<button class="pv-btn cfg-refresh" data-provider="' + p.id + '">تحديث النماذج (جلب حي)</button>' +
      (c.is_primary ? "" : '<button class="pv-btn danger cfg-delete" data-cfg="' + c.id + '">حذف التكوين</button>') +
      "</div>" +
      '<div class="pv-result" data-cfg="' + c.id + '"></div>' +
      "</div>";
    return html;
  }

  function providerCardHtml(p) {
    var statusHtml = p.auth_type === "bearer"
      ? (p.has_key
        ? '<span class="pv-status ok">مفتاح محفوظ ' + esc(p.key_masked) + "</span>"
        : '<span class="pv-status none">بلا مفتاح</span>')
      : '<span class="pv-status ok">' + esc(p.auth_type === "config_file"
        ? "مصادقة منشأة معلنة" : "بلا مصادقة") + "</span>";
    var html = '<div class="pv-card" data-provider-id="' + p.id + '" data-name="' + esc(p.name) + '">' +
      '<div class="pv-head"><span class="pv-title">' + esc(p.display_name) + "</span>" + statusHtml + "</div>" +
      '<div class="pv-meta">المعرف: <code dir="ltr">' + esc(p.name) + "</code> · النوع: " +
      esc(p.type) + " · المصادقة: " + esc(p.auth_type) + "</div>";
    (p.configurations || []).forEach(function (c) {
      html += configCardHtml(p, c);
    });
    html += '<div class="pv-row">' +
      '<button class="pv-btn cfg-add" data-provider="' + p.id + '">+ تكوين (Base URL) جديد</button>' +
      '<button class="pv-btn danger prov-delete" data-provider="' + p.id + '">حذف المزود</button></div>' +
      '<div class="cfg-new-box" data-provider="' + p.id + '" hidden>' +
      '<input class="pv-input new-cfg-name" placeholder="اسم التكوين (مثل: production)">' +
      '<input class="pv-input new-cfg-url" dir="ltr" placeholder="https://…/v1">' +
      '<input class="pv-input new-cfg-model" dir="ltr" placeholder="النموذج الافتراضي">' +
      '<button class="pv-btn primary cfg-create" data-provider="' + p.id + '">إضافة التكوين</button></div>' +
      "</div>";
    return html;
  }

  function loadProviders() {
    if (!providersBody) return;
    providersBody.textContent = "جارٍ التحميل…";
    Hub.fetchJSON("/api/providers").then(function (out) {
      if (!out.ok) {
        providersBody.textContent = "تعذر تحميل المزودين";
        return;
      }
      var data = out.j;
      providersCache = data.providers || [];
      var store = data.store || {};
      var html = '<div class="pv-store"><b>المخزن المحلي:</b> ' +
        esc(store.warning || store.file || "") + " · التشفير: " +
        (store.encryption_available ? "DPAPI (Windows)" : "صلاحيات 600") +
        "</div>";
      html += '<button class="pv-btn primary" id="provider-add-open">+ إضافة مزود</button>' +
        '<div class="prov-new-box" id="prov-new-box" hidden>' +
        '<input class="pv-input" id="np-name" dir="ltr" placeholder="المعرّف: مثل my_provider (لاتيني صغير)">' +
        '<input class="pv-input" id="np-display" placeholder="الاسم المعروض">' +
        '<input class="pv-input" id="np-url" dir="ltr" placeholder="Base URL: https://…/v1">' +
        '<input class="pv-input" id="np-model" dir="ltr" placeholder="النموذج الافتراضي">' +
        '<input type="password" class="pv-input" id="np-key" placeholder="مفتاح API (اختياري — يُخزَّن محليًا فقط)">' +
        '<button class="pv-btn primary" id="np-create">إنشاء المزود</button></div>';
      providersCache.forEach(function (p) { html += providerCardHtml(p); });
      providersBody.innerHTML = html;
      wireProviderButtons();
    });
  }

  function showResult(el, ok, text, detail) {
    el.className = "pv-result " + (ok ? "ok" : "bad");
    el.innerHTML = (ok ? "✔ " : "✕ ") + esc(text) +
      (detail ? '<div class="rd-detail" dir="ltr">' + esc(detail) + "</div>" : "");
  }

  function wireProviderButtons() {
    var addOpen = $("provider-add-open");
    if (addOpen) {
      addOpen.addEventListener("click", function () {
        var box = $("prov-new-box");
        box.hidden = !box.hidden;
      });
    }
    var npCreate = $("np-create");
    if (npCreate) {
      npCreate.addEventListener("click", function () {
        var body = {
          name: $("np-name").value.trim(),
          display_name: $("np-display").value.trim(),
          base_url: $("np-url").value.trim(),
          default_model: $("np-model").value.trim(),
          api_key: $("np-key").value.trim()
        };
        if (!body.name || !body.base_url) {
          showResult(providersBody.querySelector(".prov-new-box"), false,
            "المعرّف وBase URL مطلوبان");
          return;
        }
        Hub.fetchJSON("/api/providers", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body)
        }).then(function (out) {
          if (out.ok) { loadProviders(); loadModelsConfig(); }
          else showResult(providersBody.querySelector(".prov-new-box"), false,
            out.j.detail || "فشل الإنشاء");
        });
      });
    }

    providersBody.querySelectorAll(".cfg-url-save").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var cid = btn.getAttribute("data-cfg");
        var card = btn.closest(".cfg-card");
        var url = card.querySelector(".cfg-url-input").value.trim();
        Hub.fetchJSON("/api/provider-configurations/" + cid, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ base_url: url })
        }).then(function (out) {
          var el = card.querySelector(".pv-result");
          if (out.ok) { showResult(el, true, "حُفظ العنوان الجديد"); loadProviders(); }
          else showResult(el, false, out.j.detail || "فشل الحفظ");
        });
      });
    });

    providersBody.querySelectorAll(".cfg-test").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var cid = btn.getAttribute("data-cfg");
        var card = btn.closest(".cfg-card");
        var el = card.querySelector(".pv-result");
        btn.disabled = true;
        el.textContent = "…اختبار الاتصال الحقيقي";
        Hub.fetchJSON("/api/provider-configurations/" + cid + "/test",
          { method: "POST" })
          .then(function (out) {
            var j = out.j || {};
            var ok = j.status === "READY";
            var d = j.diagnosis || {};
            var detail = [
              "endpoint: " + (j.endpoint || d.final_url || "—"),
              "http: " + (j.http_status || "—"),
              "problem: " + (d.problem || "none"),
              "latency: " + (j.latency_ms || 0) + "ms"
            ].join("  ·  ");
            showResult(el, ok,
              (j.status || "UNKNOWN") + " — " + (j.error_message ||
                "المسبار نجح: اتصال حقيقي") +
              (d.available_models_sample
                ? " (متاح: " + d.available_models_sample.slice(0, 4).join(", ") + "…)" : ""),
              detail);
            // إعادة الرسم مؤجلة كي تُقرأ النتيجة قبل تحديث الشارات
            if (out.ok) {
              setTimeout(function () { loadProviders(); }, 3500);
            }
          })
          .finally(function () { btn.disabled = false; });
      });
    });

    providersBody.querySelectorAll(".cfg-refresh").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var pid = btn.getAttribute("data-provider");
        btn.disabled = true;
        Hub.fetchJSON("/api/providers/" + pid + "/models/refresh",
          { method: "POST" })
          .then(function (out) {
            if (out.ok) { loadProviders(); loadModelsConfig(); }
          })
          .finally(function () { btn.disabled = false; });
      });
    });

    providersBody.querySelectorAll(".model-add").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var cid = btn.getAttribute("data-cfg");
        var card = btn.closest(".cfg-card");
        var input = card.querySelector(".new-model");
        var model = input.value.trim();
        if (!model) return;
        var chips = card.querySelectorAll(".pv-chip");
        var models = [];
        chips.forEach(function (chip) {
          var text = chip.textContent.replace(" · الافتراضي", "").trim();
          if (text) models.push(text);
        });
        if (models.indexOf(model) === -1) models.push(model);
        Hub.fetchJSON("/api/provider-configurations/" + cid, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ models: models, default_model: model })
        }).then(function (out) {
          var el = card.querySelector(".pv-result");
          if (out.ok) { showResult(el, true, "أُضيف النموذج " + model); loadProviders(); }
          else showResult(el, false, out.j.detail || "فشل الإضافة");
        });
      });
    });

    providersBody.querySelectorAll(".key-save").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var name = btn.getAttribute("data-name");
        var card = btn.closest(".pv-card");
        var input = card.querySelector(".key-input");
        var el = card.querySelector(".pv-result") ||
          document.createElement("div");
        Hub.fetchJSON("/api/providers/" + encodeURIComponent(name) + "/key", {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ key: input.value })
        }).then(function (out) {
          if (out.ok) {
            showResult(el, true, "حُفظ المفتاح (" + (out.j.key_masked || "") + ")");
            input.value = "";
            loadProviders(); loadModelsConfig();
          } else {
            showResult(el, false, out.j.detail || "فشل الحفظ");
          }
        });
      });
    });

    providersBody.querySelectorAll(".key-delete").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var name = btn.getAttribute("data-name");
        Hub.fetchJSON("/api/providers/" + encodeURIComponent(name) + "/key",
          { method: "DELETE" })
          .then(function () { loadProviders(); loadModelsConfig(); });
      });
    });

    providersBody.querySelectorAll(".cfg-add").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var box = providersBody.querySelector(
          '.cfg-new-box[data-provider="' + btn.getAttribute("data-provider") + '"]');
        if (box) box.hidden = !box.hidden;
      });
    });

    providersBody.querySelectorAll(".cfg-create").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var pid = btn.getAttribute("data-provider");
        var box = providersBody.querySelector(
          '.cfg-new-box[data-provider="' + pid + '"]');
        var body = {
          name: box.querySelector(".new-cfg-name").value.trim(),
          base_url: box.querySelector(".new-cfg-url").value.trim(),
          default_model: box.querySelector(".new-cfg-model").value.trim()
        };
        if (!body.name || !body.base_url) return;
        Hub.fetchJSON("/api/providers/" + pid + "/configurations", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body)
        }).then(function (out) {
          if (out.ok) loadProviders();
          else showResult(box, false, out.j.detail || "فشل الإضافة");
        });
      });
    });

    providersBody.querySelectorAll(".cfg-delete").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var cid = btn.getAttribute("data-cfg");
        Hub.fetchJSON("/api/provider-configurations/" + cid,
          { method: "DELETE" })
          .then(function (out) {
            if (out.ok) loadProviders();
            else alert(out.j.detail || "فشل الحذف");
          });
      });
    });

    providersBody.querySelectorAll(".prov-delete").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var pid = btn.getAttribute("data-provider");
        if (!confirm("حذف المزود وكل تكويناته؟ المحمي بربط الأدوار يُرفض حذفه."))
          return;
        Hub.fetchJSON("/api/providers/" + pid, { method: "DELETE" })
          .then(function (out) {
            if (out.ok) { loadProviders(); loadModelsConfig(); }
            else alert(out.j.detail || "فشل الحذف");
          });
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
