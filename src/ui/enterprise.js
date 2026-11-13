/* ==========================================================================
   enterprise.js — AES-FACTORY-RECOVERY-AND-UI-001 §4+§5
   الوحدات المؤسسية الثماني فوق نواة V4: كل رقم من API المصنع الفعلي،
   بلا بيانات وهمية إطلاقًا، وبحالات صادقة (تحميل/فراغ/خطأ) لكل سطح.
   الحساب الحي: /health و/api/projects و/runs/active و/steps و/executions
   و/events و/artifacts و/models/config و/environment و/execution —
   وكل زر قرار يستدعي نقطة نهاية حقيقية (اعتماد/رفض/تحقق/فحص/أرشفة).
   ========================================================================== */
(function () {
  "use strict";

  var Hub = window.Hub;
  if (!Hub) return;
  var $ = function (id) { return document.getElementById(id); };
  function el(tag, cls, text) { return Hub.el(tag, cls, text); }

  /* ----------------------- مفردات الحالة الموحدة ----------------------- */
  var STATUS_LABELS = {
    DRAFT: "مسودة", PLANNING: "تخطيط جارٍ", READY: "جاهزة",
    AWAITING_OWNER_APPROVAL: "بانتظار اعتمادك", RUNNING: "قيد التنفيذ",
    REVISING: "مراجعة خطة", PAUSED: "متوقفة مؤقتًا", STOPPED: "متوقفة",
    BLOCKED: "محجوبة", COMPLETED: "مكتملة", VERIFIED: "معتمدة نهائيًا",
    ESCALATED: "مصعدة لك", FAILED: "فاشلة", PENDING: "منتظرة",
    IN_PROGRESS: "قيد العمل", ARCHIVED: "مؤرشفة"
  };
  var STATUS_CLASS = {
    VERIFIED: "ok", COMPLETED: "ok", RUNNING: "live", IN_PROGRESS: "live",
    PLANNING: "live", REVISING: "live", READY: "info",
    AWAITING_OWNER_APPROVAL: "warn", PAUSED: "paused", STOPPED: "paused",
    BLOCKED: "err", ESCALATED: "warn", FAILED: "err", DRAFT: "dim",
    PENDING: "dim", ARCHIVED: "dim"
  };
  function statusLabel(s) { return STATUS_LABELS[s] || s || "—"; }
  function statusClass(s) { return "st-" + (STATUS_CLASS[s] || "dim"); }

  function chip(status) {
    return el("span", "ent-chip " + statusClass(status), statusLabel(status));
  }

  /* ---------------------- هيكل الحالات الصادقة ---------------------- */
  function loading(body, msg) {
    body.textContent = "";
    body.appendChild(el("div", "cc-loading", msg || "جارٍ التحميل…"));
  }
  function errorBox(body, msg, retry) {
    body.textContent = "";
    var box = el("div", "ent-error");
    box.appendChild(el("div", "ent-error-title", "تعذر إكمال العملية"));
    box.appendChild(el("div", "ent-error-msg", msg || "خطأ غير متوقع"));
    if (retry) {
      var btn = el("button", "btn ghost small", "إعادة المحاولة");
      btn.addEventListener("click", retry);
      box.appendChild(btn);
    }
    body.appendChild(box);
  }
  function renderEmpty(body, title, hint) {
    var box = el("div", "ent-empty");
    box.appendChild(el("div", "ent-empty-title", title));
    if (hint) box.appendChild(el("div", "ent-empty-hint", hint));
    body.appendChild(box);
  }

  function flash(body, msg, cls) {
    var old = body.querySelector(".ent-flash");
    if (old) old.remove();
    var f = el("div", "ent-flash " + (cls || ""), msg);
    body.insertBefore(f, body.firstChild);
    setTimeout(function () { if (f.parentNode) f.remove(); }, 6000);
  }

  function fmtBytes(n) {
    if (n == null) return "—";
    if (n < 1024) return n + " B";
    if (n < 1048576) return (n / 1024).toFixed(1) + " KB";
    return (n / 1048576).toFixed(2) + " MB";
  }
  function fmtWhen(iso) {
    if (!iso) return "—";
    return String(iso).replace("T", " ").slice(0, 19);
  }
  function kindLabel(kind) {
    var K = {
      PROJECT_CREATED: "مشروع أُنشئ", PLANNING_STARTED: "بدء تخطيط",
      PLAN_GENERATING: "توليد خطة", PLAN_CREATED: "خطة أُنشئت",
      PLAN_APPROVED: "خطة اعتمدت", PLAN_APPROVAL_REQUIRED: "خطة بانتظارك",
      OWNER_GATE_RESOLVED: "بوابة حُلّت", JOB_CREATED: "مهمة أُنشئت",
      JOB_QUEUED: "مهمة في الطابور", JOB_STARTED: "مهمة بدأت",
      JOB_WAITING: "مهمة منتظرة", PREFLIGHT_STARTED: "فحص جاهزية",
      PREFLIGHT_PASS: "الجاهزية نجحت", PREFLIGHT_BLOCKED: "الجاهزية محجوبة",
      ENVIRONMENT_READY: "البيئة جاهزة", CAPABILITIES_EVALUATED: "قدرات قيست",
      EXECUTION_OPENED: "بدء تنفيذ", EXECUTION_STARTED: "خطوة بدأت",
      EXECUTION_COMPLETED: "خطوة اكتملت", PHASE_STARTED: "مرحلة بدأت",
      PHASE_COMPLETED: "مرحلة اكتملت", STEP_STARTED: "خطوة انطلقت",
      STEP_COMPLETED: "خطوة أنجزت", ROLE_EXECUTING: "وكيل يعمل",
      TOOL_EXECUTION: "أداة تُنفذ", MODEL_CALL_STARTED: "نداء نموذج",
      MODEL_CALL_COMPLETED: "نداء اكتمل", MODEL_CALL_FAILED: "نداء فشل",
      TEST_COMPLETED: "اختبار اكتمل", REVIEW_COMPLETED: "مراجعة اكتملت",
      AUDIT_COMPLETED: "تدقيق اكتمل", EVIDENCE_CREATED: "دليل أُنشئ",
      CHECKPOINT_CREATED: "نقطة حفظ", STAGE_REVIEW: "مراجعة مرحلة",
      PROJECT_COMPLETION_CANDIDATE: "اكتمال مرشح لاعتمادك",
      PROJECT_RESUMED: "استئناف", GATE_AUTO_RESOLVED: "بوابة آلية",
      run_start: "بث تشغيل", run_done: "انتهاء بث"
    };
    return K[kind] || kind;
  }
  function kindClass(kind) {
    if (/FAILED|BLOCKED|ERROR/.test(kind)) return "err";
    if (/COMPLETED|PASS|VERIFIED|CREATED|APPROVED/.test(kind)) return "ok";
    if (/STARTED|EXECUTING|RUNNING|GENERATING|CANDIDATE/.test(kind)) return "live";
    return "dim";
  }

  /* ================= 1) النظرة التنفيذية ================= */
  function renderOverview() {
    var body = $("overview-body");
    if (!body) return;
    loading(body, "جارٍ تجميع حالة المصنع من المصادر الحية…");
    Promise.all([
      Hub.fetchJSON("/health"),
      Hub.fetchJSON("/api/projects"),
      Hub.fetchJSON("/api/projects/runs/active")
    ]).then(function (out) {
      body.textContent = "";
      var health = out[0], projects = out[1], runs = out[2];
      if (!health.ok || !projects.ok) {
        errorBox(body, "تعذر جلب حالة المصنع من الـAPI", renderOverview);
        return;
      }
      var h = health.j || {};
      var pj = (projects.j && projects.j.projects) || [];
      var active = (runs.j && runs.j.runs) || [];

      /* شريط الصحة */
      var strip = el("div", "ent-health-strip");
      var sub = h.substrate || {};
      strip.appendChild(healthCard("التطبيق", (h.app || "—") + " · " + (h.version || "")));
      strip.appendChild(healthCard("الطور", h.phase || "—"));
      strip.appendChild(healthCard("ركيزة العزل",
        sub.available ? "معزولة — " + (sub.isolation || "namespaces+seccomp")
                      : "متوافقة بلا عزل (معلنة)",
        sub.available ? "ok" : "warn"));
      body.appendChild(strip);

      /* KPI: عدّ حسب الحالة من القائمة الحية */
      var counts = {};
      pj.forEach(function (p) { counts[p.status] = (counts[p.status] || 0) + 1; });
      var kpis = el("div", "ent-kpis");
      kpi(kpis, pj.length, "إجمالي المشاريع", "dim");
      kpi(kpis, active.length, "تشغيلات نشطة", active.length ? "live" : "dim");
      kpi(kpis, counts.VERIFIED || 0, "معتمدة نهائيًا", "ok");
      kpi(kpis, counts.AWAITING_OWNER_APPROVAL || 0, "بانتظار اعتمادك", "warn");
      kpi(kpis, counts.RUNNING || 0, "قيد التنفيذ", "live");
      kpi(kpis, counts.BLOCKED || 0, "محجوبة", "err");
      body.appendChild(kpis);

      /* قرارات منتظرة — نفس إجراءات وحدة المراجعات */
      var pending = pj.filter(function (p) {
        return p.status === "AWAITING_OWNER_APPROVAL"
          || (p.status === "COMPLETED" && p.completion_state === "CANDIDATE");
      });
      var sec = el("div", "ent-section");
      sec.appendChild(el("h3", "ent-section-title", "قرارات مالك منتظرة"));
      if (!pending.length) {
        sec.appendChild(el("div", "ent-empty-inline", "لا قرارات منتظرة — المصنع يعمل بلا معوقات."));
      } else {
        pending.forEach(function (p) {
          var row = el("div", "ent-row");
          var info = el("div", "ent-row-main");
          info.appendChild(el("span", "ent-row-title", "#" + p.id + " " + p.name));
          info.appendChild(chip(p.status));
          row.appendChild(info);
          row.appendChild(ReviewActions(p));
          sec.appendChild(row);
        });
      }
      body.appendChild(sec);

      /* أحدث المشاريع */
      var recent = pj.slice().sort(function (a, b) {
        return String(b.updated_at).localeCompare(String(a.updated_at));
      }).slice(0, 6);
      var sec2 = el("div", "ent-section");
      sec2.appendChild(el("h3", "ent-section-title", "أحدث المشاريع"));
      if (!recent.length) {
        sec2.appendChild(renderEmptyNote("لا مشاريع بعد — أنشئ أول مشروع من وحدة المشاريع."));
      } else {
        recent.forEach(function (p) {
          var row = el("div", "ent-row");
          var info = el("div", "ent-row-main");
          info.appendChild(el("span", "ent-row-title", "#" + p.id + " " + p.name));
          info.appendChild(chip(p.status));
          info.appendChild(el("span", "ent-when", fmtWhen(p.updated_at)));
          row.appendChild(info);
          var open = el("button", "btn ghost small", "فتح");
          open.addEventListener("click", function () {
            openProject(p.id);
          });
          row.appendChild(open);
          sec2.appendChild(row);
        });
      }
      body.appendChild(sec2);
    }).catch(function (e) {
      errorBox(body, "فشل الاتصال بالخادم: " + e, renderOverview);
    });
  }
  function healthCard(label, value, cls) {
    var c = el("div", "ent-health-card " + (cls || ""));
    c.appendChild(el("span", "ent-health-label", label));
    c.appendChild(el("span", "ent-health-value", value));
    return c;
  }
  function kpi(parent, n, label, cls) {
    var c = el("div", "ent-kpi");
    var num = el("div", "ent-kpi-num " + cls, String(n));
    num.style.fontFeatureSettings = '"tnum" 1';
    c.appendChild(num);
    c.appendChild(el("div", "ent-kpi-label", label));
    parent.appendChild(c);
  }
  function renderEmptyNote(msg) {
    return el("div", "ent-empty-inline", msg);
  }

  /* ================= 2) المشاريع والمساحات ================= */
  var projFilter = { q: "", status: "ALL" };
  function renderProjects() {
    var body = $("projects-body");
    if (!body) return;
    loading(body, "جارٍ تحميل المشاريع…");
    Hub.fetchJSON("/api/projects").then(function (out) {
      body.textContent = "";
      if (!out.ok) {
        errorBox(body, (out.j && out.j.detail) || "تعذر تحميل المشاريع", renderProjects);
        return;
      }
      var all = (out.j && out.j.projects) || [];

      /* شريط الأدوات: بحث + فلتر حالة + جديد */
      var bar = el("div", "ent-toolbar");
      var search = document.createElement("input");
      search.type = "search";
      search.className = "ent-search";
      search.placeholder = "ابحث بالاسم أو الهدف…";
      search.value = projFilter.q;
      search.setAttribute("aria-label", "بحث في المشاريع");
      search.addEventListener("input", function () {
        projFilter.q = search.value.trim();
        drawList();
      });
      bar.appendChild(search);
      var sel = document.createElement("select");
      sel.className = "ent-select";
      sel.setAttribute("aria-label", "تصفية بالحالة");
      var statuses = ["ALL"].concat(Object.keys(all.reduce(function (m, p) {
        m[p.status] = 1; return m;
      }, {})));
      statuses.forEach(function (s) {
        var o = document.createElement("option");
        o.value = s;
        o.textContent = s === "ALL" ? "كل الحالات" : statusLabel(s);
        if (projFilter.status === s) o.selected = true;
        sel.appendChild(o);
      });
      sel.addEventListener("change", function () {
        projFilter.status = sel.value;
        drawList();
      });
      bar.appendChild(sel);
      var newBtn = el("button", "btn primary small", "مشروع جديد");
      newBtn.addEventListener("click", function () {
        form.hidden = !form.hidden;
        if (!form.hidden) nameIn.focus();
      });
      bar.appendChild(newBtn);
      body.appendChild(bar);

      /* نموذج الإنشاء — POST حقيقي */
      var form = el("div", "ent-form");
      form.hidden = true;
      var nameIn = document.createElement("input");
      nameIn.className = "ent-input";
      nameIn.placeholder = "اسم المشروع";
      nameIn.maxLength = 200;
      var objIn = document.createElement("textarea");
      objIn.className = "ent-input ent-area";
      objIn.placeholder = "الهدف — ما الذي يجب أن ينتجه المصنع فعلًا؟";
      objIn.rows = 3;
      var polSel = document.createElement("select");
      polSel.className = "ent-select";
      polSel.setAttribute("aria-label", "سياسة التنفيذ");
      [["STRICT_ISOLATED", "عزل صارم (الافتراضي)"],
       ["COMPATIBLE_LOCAL", "محلي متوافق (معلن)"]].forEach(function (pair) {
        var o = document.createElement("option");
        o.value = pair[0]; o.textContent = pair[1];
        polSel.appendChild(o);
      });
      var createBtn = el("button", "btn primary small", "إنشاء المشروع");
      var formMsg = el("span", "ent-form-msg", "");
      createBtn.addEventListener("click", function () {
        if (!nameIn.value.trim() || objIn.value.trim().length < 3) {
          formMsg.textContent = "الاسم والهدف مطلوبان — لا إنشاء ناقص.";
          formMsg.className = "ent-form-msg err";
          return;
        }
        createBtn.disabled = true;
        formMsg.textContent = "جارٍ الإنشاء…";
        formMsg.className = "ent-form-msg";
        Hub.fetchJSON("/api/projects", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            name: nameIn.value.trim(),
            objective: objIn.value.trim(),
            execution_policy: polSel.value
          })
        }).then(function (r) {
          createBtn.disabled = false;
          if (r.ok && r.j && r.j.id) {
            formMsg.textContent = "أُنشئ المشروع #" + r.j.id + " — فتحه الآن…";
            formMsg.className = "ent-form-msg ok";
            setTimeout(function () {
              form.hidden = true;
              nameIn.value = ""; objIn.value = "";
              openProject(r.j.id);
            }, 500);
          } else {
            formMsg.textContent = "تعذر إنشاء المشروع — " +
              ((r.j && r.j.detail) || "خطأ غير معروف");
            formMsg.className = "ent-form-msg err";
          }
        }).catch(function (e) {
          createBtn.disabled = false;
          formMsg.textContent = "فشل الاتصال: " + e;
          formMsg.className = "ent-form-msg err";
        });
      });
      form.appendChild(nameIn);
      form.appendChild(objIn);
      var formRow = el("div", "ent-form-row");
      formRow.appendChild(polSel);
      formRow.appendChild(createBtn);
      formRow.appendChild(formMsg);
      form.appendChild(formRow);
      body.appendChild(form);

      /* القائمة */
      var list = el("div", "ent-list");
      body.appendChild(list);

      function drawList() {
        list.textContent = "";
        var q = projFilter.q.toLowerCase();
        var items = all.filter(function (p) {
          if (projFilter.status !== "ALL" && p.status !== projFilter.status) return false;
          if (!q) return true;
          return (String(p.name) + " " + String(p.objective)).toLowerCase().indexOf(q) >= 0;
        });
        if (!items.length) {
          list.appendChild(renderEmptyNote(all.length
            ? "لا نتائج مطابقة للبحث/التصفية الحالية."
            : "لا مشاريع بعد — أنشئ أول مشروع ليبدأ المصنع عمله."));
          return;
        }
        items.forEach(function (p) { list.appendChild(projectRow(p)); });
      }
      drawList();
    }).catch(function (e) {
      errorBox($("projects-body"), "فشل الاتصال: " + e, renderProjects);
    });
  }
  function projectRow(p) {
    var row = el("div", "ent-row");
    var main = el("div", "ent-row-main");
    var t = el("span", "ent-row-title", "#" + p.id + " " + p.name);
    main.appendChild(t);
    main.appendChild(chip(p.status));
    if (p.execution_policy) {
      main.appendChild(el("span", "ent-policy", p.execution_policy === "STRICT_ISOLATED"
        ? "عزل صارم" : "محلي متوافق"));
    }
    main.appendChild(el("span", "ent-when", fmtWhen(p.updated_at)));
    var objEl = el("div", "ent-row-obj", p.objective || "");
    main.appendChild(objEl);
    if (p.last_error) {
      main.appendChild(el("div", "ent-row-err", "آخر خطأ: " + p.last_error));
    }
    row.appendChild(main);
    var acts = el("div", "ent-row-actions");
    var open = el("button", "btn ghost small", "فتح");
    open.addEventListener("click", function () { openProject(p.id); });
    acts.appendChild(open);
    if (!p.archived_at) {
      var arch = el("button", "btn ghost small", "أرشفة");
      arch.addEventListener("click", function () {
        if (!window.confirm("أرشفة المشروع #" + p.id + "؟ يبقى كاملًا قابلًا للاسترجاع.")) return;
        arch.disabled = true;
        Hub.fetchJSON("/api/projects/" + p.id + "/archive", { method: "POST" })
          .then(function () { renderProjects(); })
          .catch(function () { arch.disabled = false; });
      });
      acts.appendChild(arch);
    }
    row.appendChild(acts);
    return row;
  }
  function openProject(id) {
    if (window.ControlCenter) window.ControlCenter.showView("chat");
    if (window.HubProjects) window.HubProjects.openProject(id);
  }

  /* ================= 3) المهام وطابور التنفيذ ================= */
  function renderTasks() {
    var body = $("tasks-body");
    if (!body) return;
    loading(body, "جارٍ جلب الطابور من التشغيلات الفعلية…");
    Hub.fetchJSON("/api/projects/runs/active").then(function (out) {
      body.textContent = "";
      if (!out.ok) {
        errorBox(body, "تعذر جلب التشغيلات النشطة", renderTasks);
        return;
      }
      var runs = (out.j && out.j.runs) || [];
      if (!runs.length) {
        renderEmpty(body, "لا تشغيل نشط الآن",
          "الطابور يعرض خطوات حقيقية من التشغيلات الجارية فقط — لا صفوف وهمية. ابدأ تشغيلًا من وحدة المشاريع، أو اكتب مهمة في المحادثة.");
        var toProjects = el("button", "btn primary small", "الذهاب إلى المشاريع");
        toProjects.addEventListener("click", function () {
          if (window.ControlCenter) window.ControlCenter.showView("projects");
        });
        body.appendChild(toProjects);
        return;
      }
      runs.forEach(function (run) {
        body.appendChild(taskRunCard(run));
      });
    }).catch(function (e) {
      errorBox($("tasks-body"), "فشل الاتصال: " + e, renderTasks);
    });
  }
  function taskRunCard(run) {
    var card = el("div", "ent-run-card");
    var head = el("div", "ent-run-head");
    var info = el("div", "ent-row-main");
    info.appendChild(el("span", "ent-row-title",
      "#" + run.project_id + " " + (run.project_name || "مشروع")));
    info.appendChild(chip(run.status));
    if (run.planning_active) info.appendChild(el("span", "ent-policy", "تخطيط جارٍ"));
    head.appendChild(info);
    var open = el("button", "btn ghost small", "فتح المشروع");
    open.addEventListener("click", function () { openProject(run.project_id); });
    head.appendChild(open);
    card.appendChild(head);
    var queue = el("div", "ent-queue");
    queue.appendChild(el("div", "cc-loading", "جارٍ تحميل خطوات المشروع…"));
    card.appendChild(queue);
    Hub.fetchJSON("/api/projects/" + run.project_id + "/steps")
      .then(function (r) {
        queue.textContent = "";
        var steps = (r.j && r.j.steps) || [];
        if (!steps.length) {
          queue.appendChild(renderEmptyNote("لا خطوات — المشروع لم يُعتمد بعد."));
          return;
        }
        steps.forEach(function (s) {
          var row = el("div", "ent-queue-row");
          row.appendChild(el("span", "ent-queue-ord", "خطوة " + s.ordinal));
          row.appendChild(el("span", "ent-queue-obj", s.objective || ""));
          row.appendChild(chip(s.status));
          if (s.attempts > 1) {
            row.appendChild(el("span", "ent-policy", "محاولة " + s.attempts));
          }
          if (s.current_execution_id) {
            row.appendChild(el("span", "ent-mono",
              "exec#" + s.current_execution_id));
          }
          row.title = (s.expected_output || "") +
            (s.last_error ? " — آخر خطأ: " + s.last_error : "");
          queue.appendChild(row);
        });
      }).catch(function () {
        queue.textContent = "";
        queue.appendChild(renderEmptyNote("تعذر تحميل الخطوات لهذا المشروع."));
      });
    return card;
  }

  /* ================= 4) الوكلاء والقدرات ================= */
  function renderAgents() {
    var body = $("agents-body");
    if (!body) return;
    loading(body, "جارٍ جلب الأدوار والمزودين والقدرات…");
    Promise.all([
      Hub.fetchJSON("/api/models/config"),
      Hub.fetchJSON("/health"),
      Hub.fetchJSON("/api/execution/host-truth").catch(function () { return { ok: false, j: null }; })
    ]).then(function (out) {
      body.textContent = "";
      var cfg = out[0], health = out[1], host = out[2];
      if (!cfg.ok) {
        errorBox(body, "تعذر جلب ربط الأدوار", renderAgents);
        return;
      }

      /* بطاقات الأدوار الست */
      var sec = el("div", "ent-section");
      sec.appendChild(el("h3", "ent-section-title", "أدوار الوكلاء ونماذجها — اختيار مستقل لكل دور"));
      var grid = el("div", "ent-role-grid");
      ((cfg.j && cfg.j.roles) || []).forEach(function (r) {
        var c = el("div", "ent-role-card");
        var head = el("div", "ent-role-head");
        head.appendChild(el("span", "ent-role-name", r.label || r.key));
        if (r.is_default) head.appendChild(el("span", "ent-chip dim", "افتراضي"));
        head.appendChild(el("button", "btn ghost small ent-edit", "تعديل"));
        c.appendChild(head);
        var s = r.selection || {};
        c.appendChild(el("div", "ent-role-model", (s.provider || "—") + " · " + (s.model || "—")));
        var editBtn = c.querySelector(".ent-edit");
        editBtn.addEventListener("click", function () {
          if (window.HubSettings) window.HubSettings.open("models");
        });
        grid.appendChild(c);
      });
      sec.appendChild(grid);
      body.appendChild(sec);

      /* جاهزية المزودين */
      var sec2 = el("div", "ent-section");
      sec2.appendChild(el("h3", "ent-section-title", "المزودون وجاهزيتهم — مسبار حقيقي لا ادعاء"));
      ((cfg.j && cfg.j.providers) || []).forEach(function (p) {
        var row = el("div", "ent-row");
        var main = el("div", "ent-row-main");
        main.appendChild(el("span", "ent-row-title", p.label || p.id));
        main.appendChild(el("span", "ent-mono", p.base_url || ""));
        if (p.requires_key) {
          main.appendChild(el("span", "ent-chip " + (p.has_key ? "ok" : "err"),
            p.has_key ? "مفتاح محفوظ" : "لا مفتاح"));
        } else {
          main.appendChild(el("span", "ent-chip ok", "مصادقة ملف تكوين الحاوية"));
        }
        (p.configurations || []).forEach(function (c) {
          main.appendChild(el("span", "ent-chip " +
            (c.readiness && c.readiness.status === "READY" ? "ok" : "dim"),
            (c.name || "default") + ": " +
            ((c.readiness && c.readiness.status) || "UNTESTED")));
        });
        row.appendChild(main);
        sec2.appendChild(row);
      });
      body.appendChild(sec2);

      /* الركيزة وقدرات المضيف */
      var sec3 = el("div", "ent-section");
      sec3.appendChild(el("h3", "ent-section-title", "القدرات المقيسة على هذا المضيف"));
      var h = health.j || {};
      var sub = h.substrate || {};
      var strip = el("div", "ent-health-strip");
      strip.appendChild(healthCard("ركيزة العزل",
        sub.available ? "متاحة — " + (sub.isolation || "") : "غير متاحة — وضع متوافق معلن",
        sub.available ? "ok" : "warn"));
      if (host.ok && host.j) {
        strip.appendChild(healthCard("حقيقة المضيف",
          (host.j.host_platform || "—") + " · عزل: " + (host.j.isolation || "—") +
          " · التنفيذ المحلي: " + (host.j.local_execution || "—")));
        var rt = host.j.runtime_truth || {};
        strip.appendChild(healthCard("المنصة",
          (rt.os || "—") + " · " + (rt.cpu_cores || "?") + " نواة · " +
          (rt.memory || "—") + " ذاكرة"));
      }
      strip.appendChild(healthCard("بيئة القدرات",
        sub.note ? "مقيسة فعليًا عند الإقلاع" : "غير مقيسة بعد"));
      sec3.appendChild(strip);
      var openEnv = el("button", "btn ghost small", "بيئات التنفيذ الكاملة (الإعدادات)");
      openEnv.addEventListener("click", function () {
        if (window.HubSettings) window.HubSettings.open("execution");
      });
      sec3.appendChild(openEnv);
      body.appendChild(sec3);
    }).catch(function (e) {
      errorBox($("agents-body"), "فشل الاتصال: " + e, renderAgents);
    });
  }

  /* ================= 5) التشغيلات الحية والنشاط ================= */
  var activitySource = null;
  function stopFeeds() {
    if (activitySource) { try { activitySource.close(); } catch (e) {} activitySource = null; }
    var dot = $("activity-live-dot");
    if (dot) dot.textContent = "العمل المستمر مرئي حتى بعد مغادرة المشروع";
  }
  function renderActivity() {
    var body = $("runs-body");
    if (!body) return;
    loading(body, "جارٍ ربط البث الحي وجلب التشغيلات…");
    Hub.fetchJSON("/api/projects/runs/active").then(function (out) {
      body.textContent = "";
      var runs = (out.j && out.j.runs) || [];
      var sec = el("div", "ent-section");
      sec.appendChild(el("h3", "ent-section-title", "تشغيلات نشطة"));
      if (!runs.length) {
        sec.appendChild(renderEmptyNote("لا تشغيل نشط الآن — أي تشغيل يبدأ سيظهر هنا لحظيًا عبر البث."));
      } else {
        runs.forEach(function (run) { sec.appendChild(taskRunCard(run)); });
      }
      body.appendChild(sec);

      var sec2 = el("div", "ent-section");
      sec2.appendChild(el("h3", "ent-section-title", "تيار النشاط اللحظي — أحداث دائمة من كل المشاريع"));
      var feed = el("div", "ent-feed");
      sec2.appendChild(feed);
      body.appendChild(sec2);

      if (activitySource) { try { activitySource.close(); } catch (e) {} }
      var events = [];
      function draw() {
        feed.textContent = "";
        if (!events.length) {
          feed.appendChild(renderEmptyNote("بانتظار أول حدث من البث الحي…"));
          return;
        }
        events.forEach(function (ev) {
          var row = el("div", "ent-feed-row");
          row.appendChild(el("span", "ent-mono ent-feed-time",
            String(ev.created_at || "").slice(11, 19)));
          row.appendChild(el("span", "ent-mono", "#" + ev.project_id));
          row.appendChild(el("span", "ent-chip " + kindClass(ev.kind), kindLabel(ev.kind)));
          var pay = ev.payload ? JSON.stringify(ev.payload) : "";
          row.appendChild(el("span", "ent-feed-payload",
            pay.length > 130 ? pay.slice(0, 130) + "…" : pay));
          feed.appendChild(row);
        });
      }
      activitySource = new EventSource("/api/projects/events/stream");
      activitySource.onmessage = function (m) {
        try {
          var ev = JSON.parse(m.data);
          if (ev.kind === "run.start" || ev.kind === "run.done") return;
          events.unshift(ev);
          if (events.length > 50) events.pop();
          draw();
        } catch (e) { /* جزء ناقص — تجاهل */ }
      };
      activitySource.onopen = function () {
        var dot = $("activity-live-dot");
        if (dot) dot.textContent = "● البث الحي متصل";
      };
      activitySource.onerror = function () {
        var dot = $("activity-live-dot");
        if (dot) dot.textContent = "البث مقطوع — يعيد الاتصال تلقائيًا…";
      };
      draw();
    }).catch(function (e) {
      errorBox($("runs-body"), "فشل الاتصال: " + e, renderActivity);
    });
  }

  /* ================= 6) المراجعات والاعتمادات ================= */
  function ReviewActions(p) {
    var acts = el("div", "ent-row-actions");
    if (p.status === "AWAITING_OWNER_APPROVAL") {
      var ap = el("button", "btn primary small", "اعتماد الخطة");
      ap.addEventListener("click", function () {
        ap.disabled = true;
        ap.textContent = "جاري الاعتماد…";
        Hub.fetchJSON("/api/projects/" + p.id + "/plan/approve", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ approved: true, feedback: "" })
        }).then(function (r) {
          if (r.ok) {
            flash($("reviews-body") || $("overview-body"),
              "اعتمدت خطة المشروع #" + p.id + " — الحلقة انطلقت.", "ok");
            refreshCurrent();
          } else {
            ap.disabled = false;
            ap.textContent = "اعتماد الخطة";
            flash($("reviews-body") || $("overview-body"),
              "تعذر اعتماد الخطة — " + ((r.j && r.j.detail) || "خطأ"), "err");
          }
        }).catch(function () {
          ap.disabled = false;
          ap.textContent = "اعتماد الخطة";
        });
      });
      acts.appendChild(ap);
    } else if (p.status === "COMPLETED" && p.completion_state === "CANDIDATE") {
      var vf = el("button", "btn primary small", "تحقق نهائي (اعتماد المالك)");
      vf.addEventListener("click", function () {
        vf.disabled = true;
        vf.textContent = "جارٍ التحقق…";
        Hub.fetchJSON("/api/projects/" + p.id + "/verify", { method: "POST" })
          .then(function (r) {
            if (r.ok) {
              flash($("reviews-body") || $("overview-body"),
                "المشروع #" + p.id + " معتمد نهائيًا (VERIFIED).", "ok");
              refreshCurrent();
            } else {
              vf.disabled = false;
              vf.textContent = "تحقق نهائي (اعتماد المالك)";
              flash($("reviews-body") || $("overview-body"),
                "تعذر التحقق — " + ((r.j && r.j.detail) || "خطأ"), "err");
            }
          }).catch(function () { vf.disabled = false; });
      });
      acts.appendChild(vf);
    }
    return acts;
  }
  function refreshCurrent() {
    if (currentView) {
      var v = VIEWS[currentView];
      if (v) v.render();
    }
  }
  function renderReviews() {
    var body = $("reviews-body");
    if (!body) return;
    loading(body, "جارٍ فحص كل المشاريع بحثًا عن قرارات منتظرة…");
    Hub.fetchJSON("/api/projects").then(function (out) {
      body.textContent = "";
      if (!out.ok) {
        errorBox(body, "تعذر تحميل المشاريع", renderReviews);
        return;
      }
      var all = (out.j && out.j.projects) || [];
      var planning = all.filter(function (p) { return p.status === "AWAITING_OWNER_APPROVAL"; });
      var candidates = all.filter(function (p) {
        return p.status === "COMPLETED" && p.completion_state === "CANDIDATE";
      });
      var blocked = all.filter(function (p) { return p.status === "BLOCKED"; });
      var running = all.filter(function (p) {
        return p.status === "RUNNING" || p.status === "PLANNING" || p.status === "REVISING";
      });

      var head = el("div", "ent-health-strip");
      head.appendChild(healthCard("خطط بانتظار اعتمادك", String(planning.length), planning.length ? "warn" : "dim"));
      head.appendChild(healthCard("اكتمال بانتظار تحققك", String(candidates.length), candidates.length ? "warn" : "dim"));
      head.appendChild(healthCard("محجوبة بحاجة فحص", String(blocked.length), blocked.length ? "err" : "dim"));
      head.appendChild(healthCard("قيد العمل الآن", String(running.length), "dim"));
      body.appendChild(head);

      var sec1 = el("div", "ent-section");
      sec1.appendChild(el("h3", "ent-section-title", "اعتمادات الخطط — الاعتماد قرار بشري وحده"));
      if (!planning.length) sec1.appendChild(renderEmptyNote("لا خطط بانتظار الاعتماد."));
      planning.forEach(function (p) { sec1.appendChild(reviewCard(p, "plan")); });
      body.appendChild(sec1);

      var sec2 = el("div", "ent-section");
      sec2.appendChild(el("h3", "ent-section-title", "تحقق نهائي — القناة الوحيدة إلى VERIFIED"));
      if (!candidates.length) sec2.appendChild(renderEmptyNote("لا اكتمال بانتظار التحقق."));
      candidates.forEach(function (p) { sec2.appendChild(reviewCard(p, "verify")); });
      body.appendChild(sec2);

      var sec3 = el("div", "ent-section");
      sec3.appendChild(el("h3", "ent-section-title", "مشاريع محجوبة — السبب الحقيقي والفحص"));
      if (!blocked.length) sec3.appendChild(renderEmptyNote("لا محجوبات."));
      blocked.forEach(function (p) { sec3.appendChild(blockedCard(p)); });
      body.appendChild(sec3);

      var sec4 = el("div", "ent-section");
      sec4.appendChild(el("h3", "ent-section-title", "قيد العمل — لا قرار مطلوب"));
      if (!running.length) sec4.appendChild(renderEmptyNote("لا شيء قيد العمل."));
      running.forEach(function (p) {
        var row = el("div", "ent-row");
        var main = el("div", "ent-row-main");
        main.appendChild(el("span", "ent-row-title", "#" + p.id + " " + p.name));
        main.appendChild(chip(p.status));
        row.appendChild(main);
        var open = el("button", "btn ghost small", "فتح");
        open.addEventListener("click", function () { openProject(p.id); });
        row.appendChild(open);
        sec4.appendChild(row);
      });
      body.appendChild(sec4);
    }).catch(function (e) {
      errorBox($("reviews-body"), "فشل الاتصال: " + e, renderReviews);
    });
  }
  function reviewCard(p, kind) {
    var card = el("div", "ent-run-card");
    var head = el("div", "ent-run-head");
    var main = el("div", "ent-row-main");
    main.appendChild(el("span", "ent-row-title", "#" + p.id + " " + p.name));
    main.appendChild(chip(p.status));
    main.appendChild(el("span", "ent-when", fmtWhen(p.updated_at)));
    head.appendChild(main);
    head.appendChild(ReviewActions(p));
    card.appendChild(head);
    var det = el("div", "ent-queue");
    det.appendChild(el("div", "cc-loading", "جارٍ جلب تفاصيل الخطة…"));
    card.appendChild(det);
    Hub.fetchJSON("/api/projects/" + p.id + "/plan").then(function (r) {
      det.textContent = "";
      var plan = (r.j && (r.j.plan || r.j)) || null;
      if (!plan || !plan.phases) {
        det.appendChild(renderEmptyNote("لا خطة متاحة بعد."));
        return;
      }
      det.appendChild(el("div", "ent-queue-obj", plan.objective || ""));
      (plan.phases || []).forEach(function (ph) {
        var row = el("div", "ent-queue-row");
        row.appendChild(el("span", "ent-queue-ord", "مرحلة: " + ph.title));
        row.appendChild(el("span", "ent-queue-obj",
          (ph.steps || []).length + " خطوة — " + (ph.objective || "")));
        det.appendChild(row);
      });
    }).catch(function () {
      det.textContent = "";
      det.appendChild(renderEmptyNote("تعذر جلب تفاصيل الخطة."));
    });
    return card;
  }
  function blockedCard(p) {
    var card = el("div", "ent-run-card");
    var head = el("div", "ent-run-head");
    var main = el("div", "ent-row-main");
    main.appendChild(el("span", "ent-row-title", "#" + p.id + " " + p.name));
    main.appendChild(chip(p.status));
    if (p.last_error) main.appendChild(el("div", "ent-row-err", p.last_error));
    head.appendChild(main);
    var acts = el("div", "ent-row-actions");
    var re = el("button", "btn ghost small", "إعادة الفحص");
    re.addEventListener("click", function () {
      re.disabled = true;
      re.textContent = "جارٍ الفحص…";
      Hub.fetchJSON("/api/projects/" + p.id + "/preflight", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({})
      }).then(function () { renderReviews(); })
        .catch(function () { re.disabled = false; re.textContent = "إعادة الفحص"; });
    });
    acts.appendChild(re);
    var open = el("button", "btn ghost small", "فتح");
    open.addEventListener("click", function () { openProject(p.id); });
    acts.appendChild(open);
    head.appendChild(acts);
    card.appendChild(head);
    return card;
  }

  /* ================= 7) المخرجات والتسليمات ================= */
  function renderArtifacts() {
    var body = $("artifacts-body");
    if (!body) return;
    loading(body, "جارٍ تحميل المشاريع للمخرجات…");
    Hub.fetchJSON("/api/projects").then(function (out) {
      body.textContent = "";
      if (!out.ok) { errorBox(body, "تعذر تحميل المشاريع", renderArtifacts); return; }
      var all = (out.j && out.j.projects) || [];
      if (!all.length) {
        renderEmpty(body, "لا مشاريع بعد", "المخرجات تأتي من تنفيذ حقيقي — أنشئ مشروعًا وشغّله أولًا.");
        return;
      }
      var bar = el("div", "ent-toolbar");
      var sel = document.createElement("select");
      sel.className = "ent-select";
      sel.setAttribute("aria-label", "اختر المشروع");
      all.slice().sort(function (a, b) { return b.id - a.id; }).forEach(function (p) {
        var o = document.createElement("option");
        o.value = p.id;
        o.textContent = "#" + p.id + " " + p.name + " (" + statusLabel(p.status) + ")";
        sel.appendChild(o);
      });
      bar.appendChild(sel);
      var refresh = el("button", "btn ghost small", "تحديث");
      bar.appendChild(refresh);
      body.appendChild(bar);

      var panel = el("div", "ent-list");
      body.appendChild(panel);

      function load() {
        var pid = parseInt(sel.value, 10);
        panel.textContent = "";
        panel.appendChild(el("div", "cc-loading", "جارٍ تحميل مخرجات المشروع #" + pid + "…"));
        Hub.fetchJSON("/api/projects/" + pid + "/artifacts").then(function (r) {
          panel.textContent = "";
          var raw = r.ok ? r.j : null;
          var arts = raw && raw.artifacts ? raw.artifacts
            : (Array.isArray(raw) ? raw : null);
          if (!arts || !arts.length) {
            renderEmpty(panel, "لا مخرجات لهذا المشروع بعد",
              "المخرجات تُسجل عند اكتمال الخطوات بأدلة — المشروع لم ينتج ملفات بعد.");
            return;
          }
          var tbl = el("table", "ent-table");
          var thead = el("thead");
          var hr = el("tr");
          ["الملف", "الحجم", "بصمة SHA-256", "الخطوة", "الحكم", ""].forEach(function (t) {
            hr.appendChild(el("th", "", t));
          });
          thead.appendChild(hr);
          tbl.appendChild(thead);
          var tb = el("tbody");
          arts.forEach(function (a) {
            var tr = el("tr");
            var tdName = el("td", "", a.name);
            tdName.className = "ent-mono ent-file";
            tr.appendChild(tdName);
            tr.appendChild(el("td", "", fmtBytes(a.bytes)));
            var tdSha = el("td", "ent-mono", (a.sha256 || "").slice(0, 16) + "…");
            tdSha.title = a.sha256 || "";
            tr.appendChild(tdSha);
            tr.appendChild(el("td", "ent-mono",
              a.step_id ? "خطوة " + a.step_id : "—"));
            tr.appendChild(el("td")).appendChild(chip(a.verdict || "PASS"));
            var tdAct = el("td");
            if (a.step_id) {
              var v = el("button", "btn ghost small", "معاينة");
              v.addEventListener("click", function () {
                showArtifact(pid, a);
              });
              tdAct.appendChild(v);
            }
            tr.appendChild(tdAct);
            tb.appendChild(tr);
          });
          tbl.appendChild(tb);
          panel.appendChild(tbl);
          panel.appendChild(el("div", "ent-note",
            "المخرجات من ملفات الأدلة الدائمة على القرص (قراءة حصرًا) — المعاينة نصية حتى 256KB."));
        }).catch(function (e) {
          panel.textContent = "";
          errorBox(panel, "فشل تحميل المخرجات: " + e, load);
        });
      }
      sel.addEventListener("change", load);
      refresh.addEventListener("click", load);
      load();
    }).catch(function (e) {
      errorBox($("artifacts-body"), "فشل الاتصال: " + e, renderArtifacts);
    });
  }
  function showArtifact(pid, art) {
    var viewer = $("artifact-viewer");
    if (!viewer) {
      viewer = el("div", "ent-viewer");
      viewer.id = "artifact-viewer";
      $("artifacts-body").appendChild(viewer);
    }
    viewer.textContent = "";
    viewer.hidden = false;
    var head = el("div", "ent-viewer-head");
    head.appendChild(el("span", "ent-mono", art.name));
    var close = el("button", "btn ghost small", "إغلاق المعاينة");
    close.addEventListener("click", function () { viewer.hidden = true; viewer.textContent = ""; });
    head.appendChild(close);
    viewer.appendChild(head);
    var pre = el("pre", "ent-viewer-pre", "جارٍ قراءة الملف من الأدلة…");
    pre.setAttribute("dir", "ltr");
    viewer.appendChild(pre);
    Hub.fetchJSON("/api/projects/" + pid + "/artifacts/content?step_id=" +
      art.step_id + "&name=" + encodeURIComponent(art.name))
      .then(function (r) {
        if (r.ok && typeof r.j === "string") {
          pre.textContent = r.j;
        } else {
          pre.textContent = "تعذر قراءة الملف — " +
            ((r.j && r.j.detail) || "غير نصي أو غير موجود (ثنائي/ناقص).");
        }
      }).catch(function (e) {
        pre.textContent = "فشل الاتصال: " + e;
      });
  }

  /* ================= 8) السجلات والأحداث والتشخيص ================= */
  function renderLogs() {
    var body = $("logs-body");
    if (!body) return;
    loading(body, "جارٍ تحميل المشاريع للسجلات…");
    Hub.fetchJSON("/api/projects").then(function (out) {
      body.textContent = "";
      if (!out.ok) { errorBox(body, "تعذر تحميل المشاريع", renderLogs); return; }
      var all = (out.j && out.j.projects) || [];
      if (!all.length) {
        renderEmpty(body, "لا مشاريع بعد", "السجلات أحداث دائمة مرتبطة بمعرفات المشاريع والخطوات.");
        return;
      }
      var bar = el("div", "ent-toolbar");
      var sel = document.createElement("select");
      sel.className = "ent-select";
      sel.setAttribute("aria-label", "اختر المشروع");
      all.slice().sort(function (a, b) { return b.id - a.id; }).forEach(function (p) {
        var o = document.createElement("option");
        o.value = p.id;
        o.textContent = "#" + p.id + " " + p.name;
        sel.appendChild(o);
      });
      bar.appendChild(sel);
      var kindIn = document.createElement("input");
      kindIn.type = "search";
      kindIn.className = "ent-search";
      kindIn.placeholder = "تصفية بنوع الحدث (مثال: STEP، MODEL، TOOL)…";
      kindIn.setAttribute("aria-label", "تصفية الأحداث");
      bar.appendChild(kindIn);
      var refresh = el("button", "btn ghost small", "تحديث");
      bar.appendChild(refresh);
      body.appendChild(bar);

      var panel = el("div", "ent-list");
      body.appendChild(panel);
      var rawEvents = [];

      function draw() {
        var q = kindIn.value.trim().toUpperCase();
        panel.textContent = "";
        var items = rawEvents.filter(function (ev) {
          return !q || String(ev.kind).toUpperCase().indexOf(q) >= 0;
        });
        if (!items.length) {
          renderEmpty(panel, q ? "لا أحداث مطابقة للتصفية." : "لا أحداث بعد لهذا المشروع.",
            q ? "وسّع التصفية أو امسحها." : "أي عملية مستقبلية ستُسجل هنا دائمًا.");
          return;
        }
        items.forEach(function (ev) {
          var row = el("div", "ent-log-row");
          var line = el("div", "ent-log-line");
          line.appendChild(el("span", "ent-mono ent-feed-time",
            String(ev.created_at || "").slice(11, 19)));
          line.appendChild(el("span", "ent-mono", "ev#" + ev.id));
          line.appendChild(el("span", "ent-chip " + kindClass(ev.kind), kindLabel(ev.kind)));
          line.appendChild(el("span", "ent-feed-payload",
            (ev.payload ? JSON.stringify(ev.payload) : "").slice(0, 150)));
          var exp = el("button", "btn ghost small", "JSON");
          exp.addEventListener("click", function () {
            var old = row.querySelector(".ent-log-json");
            if (old) { old.remove(); return; }
            var pre = el("pre", "ent-log-json", JSON.stringify(ev, null, 2));
            pre.setAttribute("dir", "ltr");
            row.appendChild(pre);
          });
          line.appendChild(exp);
          row.appendChild(line);
          panel.appendChild(row);
        });
        var cnt = el("div", "ent-note", "عدد الأحداث المعروضة: " + items.length +
          (rawEvents.length !== items.length ? " من " + rawEvents.length + " قبل التصفية" : ""));
        panel.appendChild(cnt);
      }
      kindIn.addEventListener("input", draw);

      function load() {
        var pid = parseInt(sel.value, 10);
        panel.textContent = "";
        panel.appendChild(el("div", "cc-loading", "جارٍ قراءة الأحداث الدائمة للمشروع #" + pid + "…"));
        Hub.fetchJSON("/api/projects/" + pid + "/events?limit=200").then(function (r) {
          rawEvents = (r.ok && r.j && r.j.events) || [];
          draw();
        }).catch(function (e) {
          rawEvents = [];
          panel.textContent = "";
          errorBox(panel, "فشل تحميل الأحداث: " + e, load);
        });
      }
      sel.addEventListener("change", load);
      refresh.addEventListener("click", load);
      load();
    }).catch(function (e) {
      errorBox($("logs-body"), "فشل الاتصال: " + e, renderLogs);
    });
  }

  /* ----------------------- التوجيه والتصدير ----------------------- */
  var VIEWS = {
    overview:  { id: "overview-view",  render: renderOverview },
    projects:  { id: "projects-view",  render: renderProjects },
    tasks:     { id: "tasks-view",     render: renderTasks },
    agents:    { id: "agents-view",    render: renderAgents },
    activity:  { id: "runs-view",      render: renderActivity },
    reviews:   { id: "reviews-view",   render: renderReviews },
    artifacts: { id: "artifacts-view", render: renderArtifacts },
    logs:      { id: "logs-view",      render: renderLogs }
  };
  var currentView = null;

  function hideAll() {
    Object.keys(VIEWS).forEach(function (k) {
      var v = $(VIEWS[k].id);
      if (v) v.hidden = true;
    });
    stopFeeds();
    currentView = null;
  }

  function show(name) {
    var v = VIEWS[name];
    if (!v) return;
    hideAll();
    currentView = name;
    var root = $(v.id);
    if (!root) return;
    root.hidden = false;
    if (location.hash !== "#/" + name) {
      try { history.replaceState(null, "", "#/" + name); } catch (e) { /* ignore */ }
    }
    try { v.render(); } catch (err) {
      errorBox($(v.id), "خطأ في العرض: " + err);
    }
  }

  /* توجيه دائم للوحدات المؤسسية: #/overview … #/logs */
  window.addEventListener("hashchange", function () {
    var m = (location.hash || "").match(
      /^#\/(overview|projects|tasks|agents|activity|reviews|artifacts|logs)$/);
    if (m && window.ControlCenter) window.ControlCenter.showView(m[1]);
  });
  /* أول دخول بمسار مؤسسي مباشر (refresh على #/reviews مثلًا) */
  (function bootRoute() {
    var m = (location.hash || "").match(
      /^#\/(overview|projects|tasks|agents|activity|reviews|artifacts|logs)$/);
    if (m) {
      setTimeout(function () {
        if (window.ControlCenter) window.ControlCenter.showView(m[1]);
      }, 300);
    }
  })();

  window.HubEnterprise = {
    show: show,
    handles: function (name) { return !!VIEWS[name]; },
    hideAll: hideAll,
    refresh: refreshCurrent
  };
})();
