/* ==========================================================================
   command-center.js — AES-FACTORY-CONSOLE-REARCHITECTURE-001 §4
   غرفة القيادة: شريط الحالة العام (A) على كل سطح + الصفحة التنفيذية الكاملة:
   A شريط الحالة · B التشغيل الحالي · C طابور القرارات · D جدول المشاريع
   E صحة المصنع · F خط النشاط.
   قاعدة الصدق (§8): كل رقم من API حي؛ الغياب يُعرض «غير متاح/لا شيء بعد»
   ولا تُخترق قيمة أبدًا. اتصال الخادم منفصل عن الجاهزية التشغيلية:
   جاهزية الوكلاء تُثبت بمسبار readiness حقيقي لا بمجرد وجود إعدادات.
   سقف الملف <2000 سطر (عقد tests/contracts/test_thinness.py).
   ========================================================================== */
(function () {
  "use strict";

  var Hub = window.Hub;
  if (!Hub) return;
  var $ = function (id) { return document.getElementById(id); };
  function el(tag, cls, text) { return Hub.el(tag, cls, text); }
  function esc(s) { return Hub.esc(s); }

  /* ------------------- مفردات الحالة (مصدر واحد مع enterprise) ------------------- */
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
  function fmtDur(s) {
    if (s == null) return "—";
    s = Math.round(s);
    if (s < 60) return s + "s";
    if (s < 3600) return Math.floor(s / 60) + "m " + (s % 60) + "s";
    return Math.floor(s / 3600) + "h " + Math.floor((s % 3600) / 60) + "m";
  }

  var cache = {};   /* لقطات مشتركة بين الشريط والصفحة — تُجدد دوريًا */

  /* ================= A) شريط الحالة العام — على كل سطح ================= */
  function stripCell(opt) {
    var c = opt.nav
      ? el("button", "cmd-cell")
      : el("div", "cmd-cell");
    var dot = el("span", "cmd-dot " + (opt.dot || "idle"));
    dot.setAttribute("aria-hidden", "true");
    c.appendChild(dot);
    c.appendChild(el("span", "cmd-cell-label", opt.label));
    var v = el("span", "cmd-cell-value" + (opt.ar ? " ar" : ""), opt.value || "…");
    if (opt.title) v.title = opt.title;
    c.appendChild(v);
    if (opt.nav && window.ControlCenter) {
      c.addEventListener("click", function () {
        window.ControlCenter.showView(opt.nav);
      });
    }
    return c;
  }

  function renderStrip() {
    var strip = $("cmd-strip");
    if (!strip) return;
    var d = cache;
    strip.textContent = "";

    /* 1) اتصال الخادم — عن الاتصال حصرًا، لا عن الجاهزية */
    var connVal = "منقطع";
    var connDot = "err";
    if (d.healthOk) {
      connVal = "متصل";
      connDot = (window.LiveEvents && LiveEvents.isConnected()) ? "live" : "ok";
      if (connDot === "live") connVal = "متصل · بث حي";
    }
    strip.appendChild(stripCell({ label: "اتصال الخادم", value: connVal, dot: connDot, ar: true, nav: "logs" }));

    /* 2) صحة التشغيل — التطبيق والطور والركيزة */
    var h = d.health || {};
    var sub = h.substrate || {};
    var rt = h.app ? (h.app + " · " + (h.phase || "—")) : "غير متاح";
    strip.appendChild(stripCell({
      label: "صحة التشغيل", value: rt, ar: false,
      dot: d.healthOk ? (sub.available ? "ok" : "warn") : "err",
      title: "ركيزة العزل: " + (sub.available ? "معزولة" : "متوافقة بلا عزل (معلنة)"),
      nav: "agents"
    }));

    /* 3) تشغيلات نشطة */
    var runs = d.runs || [];
    var live = runs.filter(function (r) {
      return r.planning_active ||
        ["RUNNING", "REVISING", "PLANNING"].indexOf(r.status || "") !== -1;
    }).length;
    var waiting = runs.filter(function (r) {
      return r.status === "AWAITING_OWNER_APPROVAL" || r.status === "PAUSED";
    }).length;
    strip.appendChild(stripCell({
      label: "تشغيلات نشطة",
      value: String(runs.length) + (live ? " (" + live + " تعمل)" : ""),
      ar: true, dot: live ? "live" : (runs.length ? "warn" : "idle"),
      nav: "activity"
    }));

    /* 4) جاهزية الوكلاء — بمسبار readiness لا بمجرد إعدادات */
    var ready = d.rolesReady, total = d.rolesTotal;
    var agentsVal = (total ? ready + "/" + total + " جاهز بالفحص" : "غير متاح");
    var agentsDot = !total ? "idle" : (ready === total ? "ok" : (ready ? "warn" : "err"));
    strip.appendChild(stripCell({
      label: "الوكلاء الجاهزة", value: agentsVal, ar: true, dot: agentsDot,
      title: ready === total
        ? "كل الأدوار بمزود مُفحوص جاهزيته"
        : "الجاهزية تثبت بمسبار المزود الحي — وجود إعدادات وحده لا يكفي",
      nav: "agents"
    }));

    /* 5) قرارات بانتظارك */
    var pend = d.pendingDecisions || 0;
    strip.appendChild(stripCell({
      label: "قرارات بانتظارك", value: String(pend), ar: false,
      dot: pend ? "warn" : "ok", nav: "reviews"
    }));

    /* 6) فاشل/محجوب */
    var bad = d.failedBlocked || 0;
    strip.appendChild(stripCell({
      label: "فاشل/محجوب", value: String(bad), ar: false,
      dot: bad ? "err" : "idle", nav: "reviews"
    }));

    /* 7) أحدث مخرَج معتمد */
    var lv = d.lastVerified || null;
    strip.appendChild(stripCell({
      label: "أحدث مخرَج معتمد",
      value: lv ? (lv.project + " · " + lv.name) : "لا شيء بعد",
      ar: true, dot: lv ? "ok" : "idle",
      title: lv ? ("من " + fmtWhen(lv.at) + " — " + fmtBytes(lv.bytes)) : "لا مخرجات معتمدة بعد",
      nav: "artifacts"
    }));
  }

  /* ================= تجميع اللقطة الموحدة (مصدر واحد للشريط والصفحة) ================= */
  function gather() {
    return Promise.all([
      Hub.fetchJSON("/health"),
      Hub.fetchJSON("/api/projects"),
      Hub.fetchJSON("/api/projects/runs/active"),
      Hub.fetchJSON("/api/models/config").catch(function () { return { ok: false, j: null }; }),
      Hub.fetchJSON("/api/environment/readiness").catch(function () { return { ok: false, j: null }; }),
      Hub.fetchJSON("/api/execution/environments").catch(function () { return { ok: false, j: null }; }),
      Hub.fetchJSON("/api/execution/host-truth").catch(function () { return { ok: false, j: null }; })
    ]).then(function (out) {
      var health = out[0], projects = out[1], runs = out[2],
          cfg = out[3], caps = out[4], envs = out[5], host = out[6];
      var pj = (projects.ok && projects.j && projects.j.projects) || [];
      var act = (runs.ok && runs.j && runs.j.runs) || [];
      cache.healthOk = health.ok;
      cache.health = health.ok ? (health.j || {}) : {};
      cache.projects = pj;
      cache.runs = act;
      cache.cfg = cfg.ok ? (cfg.j || {}) : null;
      cache.caps = caps.ok ? (caps.j || {}) : null;
      cache.envs = envs.ok ? (envs.j || {}) : null;
      cache.host = host.ok ? (host.j || {}) : null;

      /* جاهزية الوكلاء الصادقة: دور جاهز فقط إذا مزوده بتكوين مُفحوص READY */
      var ready = 0, total = 0;
      if (cache.cfg && cache.cfg.roles) {
        var provReady = {};
        (cache.cfg.providers || []).forEach(function (p) {
          (p.configurations || []).forEach(function (c) {
            if (c.readiness && c.readiness.status === "READY") {
              provReady[p.id] = true;
            }
          });
        });
        cache.cfg.roles.forEach(function (r) {
          total += 1;
          var sel = r.selection || {};
          if (sel.provider && sel.model && provReady[sel.provider]) ready += 1;
        });
      }
      cache.rolesReady = ready;
      cache.rolesTotal = total;

      var pend = pj.filter(function (p) {
        return p.status === "AWAITING_OWNER_APPROVAL" ||
          (p.status === "COMPLETED" && p.completion_state === "CANDIDATE");
      }).length;
      cache.pendingDecisions = pend;
      cache.failedBlocked = pj.filter(function (p) {
        return ["BLOCKED", "FAILED", "ESCALATED"].indexOf(p.status || "") !== -1;
      }).length;
      return cache;
    });
  }

  /* أحدث مخرَج معتمد — من أحدث مشروع VERIFIED فعلًا */
  function refreshLastVerified() {
    var verified = (cache.projects || []).filter(function (p) {
      return p.status === "VERIFIED";
    }).sort(function (a, b) {
      return String(b.updated_at || "").localeCompare(String(a.updated_at || ""));
    });
    if (!verified.length) { cache.lastVerified = null; return Promise.resolve(); }
    var p = verified[0];
    return Hub.fetchJSON("/api/projects/" + p.id + "/artifacts").then(function (r) {
      var arts = r.ok && r.j && r.j.artifacts ? r.j.artifacts
        : (r.ok && Array.isArray(r.j) ? r.j : []);
      if (arts && arts.length) {
        var a = arts[0];
        cache.lastVerified = {
          project: "#" + p.id, name: a.name || "—",
          bytes: a.bytes, at: p.updated_at
        };
      } else {
        cache.lastVerified = null;
      }
    }).catch(function () { cache.lastVerified = null; });
  }

  var stripTimer = null;
  function startStrip() {
    if (stripTimer) return;
    var beat = function () {
      gather().then(function () {
        if (cache.projects.some(function (p) { return p.status === "VERIFIED"; })) {
          return refreshLastVerified();
        }
        cache.lastVerified = null;
      }).then(renderStrip).catch(function () { renderStrip(); });
    };
    beat();
    stripTimer = setInterval(beat, 20000);
    if (window.LiveEvents) {
      var t = null;
      LiveEvents.onEvent(function () {
        if (t) return;
        t = setTimeout(function () { t = null; beat(); }, 800);
      });
    }
  }

  /* ================= B) منطقة التشغيل الحالي ================= */
  function currentRunPanel(run) {
    var sec = el("div", "cmd-section");
    var head = el("div", "cmd-section-head");
    head.appendChild(el("span", "cmd-section-title", "التشغيل الحالي"));
    head.appendChild(el("span", "cmd-section-count", "#" + run.project_id));
    sec.appendChild(head);

    var grid = el("div", "cmd-current");
    var main = el("div", "cmd-current-main");
    main.appendChild(el("div", "cmd-current-title", run.name || run.project_name || "مشروع"));
    var stage = el("div", "cmd-current-stage");
    stage.appendChild(chip(run.status));
    if (run.planning_active) stage.appendChild(el("span", "ent-chip live", "تخطيط جارٍ"));
    if (run.stage) stage.appendChild(el("span", "ent-policy", run.stage));
    main.appendChild(stage);
    if (run.waiting_for && run.waiting_for.label) {
      main.appendChild(el("div", "cmd-current-sub",
        "سبب الانتظار: " + run.waiting_for.label));
    }
    var nextAction = nextRequiredAction(run);
    if (nextAction) {
      var na = el("div", "cmd-current-sub");
      na.appendChild(el("span", "ent-chip warn", nextAction));
      main.appendChild(na);
    }
    grid.appendChild(main);

    function cell(k, v, ar) {
      var c = el("div", "cmd-current-cell");
      c.appendChild(el("span", "cmd-cell-k", k));
      var val = el("span", "cmd-cell-v" + (ar ? " ar" : ""), v);
      c.appendChild(val);
      return c;
    }
    grid.appendChild(cell("الوكيل/الدور المنفذ", cache.currentRole || "غير متاح", true));
    grid.appendChild(cell("التقدم الفعلي",
      run.progress && run.progress.percent != null
        ? run.progress.percent + "%" : "غير متاح", false));
    grid.appendChild(cell("النبضة الأخيرة", cache.heartbeat || "—", false));
    grid.appendChild(cell("مدة التشغيل", fmtDur(run.elapsed_s), false));

    if (run.progress && run.progress.steps_total) {
      var pc = el("div", "cmd-current-cell");
      pc.style.gridColumn = "1 / -1";
      pc.appendChild(el("span", "cmd-cell-k",
        "التقدم: الخطوة " + (run.progress.steps_done != null ? run.progress.steps_done : "—") +
        " من " + run.progress.steps_total));
      var bar = el("div", "cmd-progress");
      var fill = el("i");
      fill.style.width = (run.progress.percent || 0) + "%";
      bar.appendChild(fill);
      pc.appendChild(bar);
      grid.appendChild(pc);
    }
    sec.appendChild(grid);
    return sec;
  }

  function nextRequiredAction(run) {
    if (run.status === "AWAITING_OWNER_APPROVAL") return "الإجراء المطلوب: اعتماد الخطة";
    if (run.status === "PAUSED") return "الإجراء المطلوب: استئناف أو إيقاف";
    if (run.status === "BLOCKED") return "الإجراء المطلوب: فحص السبب وإعادة الجاهزية";
    if (run.status === "COMPLETED" || run.completion_state === "CANDIDATE") {
      return "الإجراء المطلوب: التحقق النهائي";
    }
    return null;
  }

  /* تفصيل التشغيل الحي: الخطوة الحالية + الدور المنفذ + النبضة من أحداث حية */
  function enrichRun(run) {
    var pid = run.project_id;
    return Promise.all([
      Hub.fetchJSON("/api/projects/" + pid + "/steps")
        .catch(function () { return { ok: false }; }),
      Hub.fetchJSON("/api/projects/" + pid + "/events?limit=30")
        .catch(function () { return { ok: false }; })
    ]).then(function (out) {
      var steps = (out[0].ok && out[0].j && out[0].j.steps) || [];
      var stepNow = steps.filter(function (s) {
        return ["IN_PROGRESS", "RUNNING"].indexOf(s.status || "") !== -1;
      })[0] || steps.filter(function (s) { return s.status === "PENDING"; })[0];
      cache.currentStep = stepNow
        ? ("خطوة " + stepNow.ordinal + " — " + (stepNow.objective || ""))
        : (steps.length ? "—" : "غير متاح");
      var evs = (out[1].ok && out[1].j && out[1].j.events) || [];
      var roleEv = evs.filter(function (e) { return e.kind === "ROLE_EXECUTING"; })[0];
      cache.currentRole = roleEv && roleEv.payload && (roleEv.payload.role || roleEv.payload.agent)
        ? String(roleEv.payload.role || roleEv.payload.agent) : "غير متاح";
      cache.heartbeat = evs.length
        ? String(evs[0].created_at || "").slice(11, 19) : "—";
      cache.currentStepText = cache.currentStep;
    });
  }

  /* ================= C) طابور القرارات ================= */
  function decisionRow(p, kind, why) {
    var row = el("div", "cmd-decision");
    var dot = el("span", "cmd-kind-dot " + kind);
    dot.setAttribute("aria-hidden", "true");
    row.appendChild(dot);
    var main = el("div", "cmd-decision-main");
    var title = el("div", "cmd-decision-title", "#" + p.id + " " + (p.name || "مشروع"));
    main.appendChild(title);
    main.appendChild(el("div", "cmd-decision-why", why));
    var meta = el("div", "cmd-decision-meta");
    meta.appendChild(chip(p.status));
    meta.appendChild(el("span", "ent-when", fmtWhen(p.updated_at)));
    main.appendChild(meta);
    row.appendChild(main);
    var acts = el("div", "cmd-decision-actions");
    /* (REARCH-001 §4-C) معالجة المتعطل: إعادة المحاولة من الطابور نفسه —
       نفس نقطة النهاية ونفس عقد زر «↻ إعادة» في واجهة المشروع. */
    if (p.status === "BLOCKED" || p.status === "ESCALATED" || p.status === "FAILED") {
      var re = el("button", "btn ghost small", "إعادة المحاولة");
      re.title = "إعادة آخر فشل (تخطيط أو خطوة) — عقد زر ↻ إعادة في المشروع";
      re.addEventListener("click", function () {
        re.disabled = true;
        re.textContent = "…جارٍ الإعادة";
        Hub.fetchJSON("/api/projects/" + p.id + "/retry", { method: "POST" })
          .then(function () {
            re.disabled = false;
            re.textContent = "إعادة المحاولة";
            render();
          }).catch(function () {
            re.disabled = false;
            re.textContent = "إعادة المحاولة";
          });
      });
      acts.appendChild(re);
    }
    if (window.HubEnterprise && HubEnterprise.actionsFor) {
      acts.appendChild(HubEnterprise.actionsFor(p));
    }
    var open = el("button", "btn ghost small", "فتح");
    open.addEventListener("click", function () {
      if (window.HubEnterprise) HubEnterprise.openProject(p.id);
    });
    acts.appendChild(open);
    row.appendChild(acts);
    return row;
  }

  function decisionSection(pending) {
    var sec = el("div", "cmd-section");
    var head = el("div", "cmd-section-head");
    head.appendChild(el("span", "cmd-section-title", "طابور القرارات — ما ينتظر قرارك"));
    head.appendChild(el("span", "cmd-section-count", String(pending.length)));
    sec.appendChild(head);
    if (!pending.length) {
      var b = el("div", "cmd-section-body");
      b.appendChild(el("div", "cmd-empty",
        el("div", "cmd-empty-title", "لا قرارات منتظرة")));
      b.lastChild && (b.textContent = "");
      var em = el("div", "cmd-empty");
      em.appendChild(el("div", "cmd-empty-title", "لا قرارات منتظرة"));
      em.appendChild(el("div", "cmd-empty-hint",
        "المصنع يعمل بلا معوقات — أي خطة أو اكتمال يحتاج قرارك سيظهر هنا أولًا."));
      b.appendChild(em);
      sec.appendChild(b);
      return sec;
    }
    pending.forEach(function (item) {
      sec.appendChild(decisionRow(item.p, item.kind, item.why));
    });
    return sec;
  }

  /* ================= D) جدول المشاريع المؤسسي ================= */
  var projSort = { key: "updated_at", dir: -1 };
  var projQuery = { q: "", status: "ALL" };
  var stepsCache = {};    /* pid → {steps, when} */

  function progressOf(pid, cb) {
    if (stepsCache[pid]) { cb(stepsCache[pid]); return; }
    Hub.fetchJSON("/api/projects/" + pid + "/steps").then(function (r) {
      var steps = (r.ok && r.j && r.j.steps) || [];
      stepsCache[pid] = steps;
      cb(steps);
    }).catch(function () { cb([]); });
  }

  function renderProjectsTable(body) {
    var pj = (cache.projects || []).filter(function (p) { return !p.archived_at; });
    var sec = el("div", "cmd-section");
    var head = el("div", "cmd-section-head");
    head.appendChild(el("span", "cmd-section-title", "المشاريع"));
    head.appendChild(el("span", "cmd-section-count", String(pj.length)));
    sec.appendChild(head);

    var tools = el("div", "ent-toolbar");
    tools.style.padding = "10px 14px";
    var search = document.createElement("input");
    search.type = "search";
    search.className = "ent-search";
    search.placeholder = "ابحث بالاسم أو الهدف…";
    search.value = projQuery.q;
    search.setAttribute("aria-label", "بحث في المشاريع");
    search.addEventListener("input", function () {
      projQuery.q = search.value.trim(); drawTable();
    });
    tools.appendChild(search);
    var sel = document.createElement("select");
    sel.className = "ent-select";
    sel.setAttribute("aria-label", "تصفية بالحالة");
    var statuses = ["ALL"].concat(Object.keys((cache.projects || []).reduce(function (m, p) {
      m[p.status] = 1; return m;
    }, {})));
    statuses.forEach(function (s) {
      var o = document.createElement("option");
      o.value = s;
      o.textContent = s === "ALL" ? "كل الحالات" : statusLabel(s);
      if (projQuery.status === s) o.selected = true;
      sel.appendChild(o);
    });
    sel.addEventListener("change", function () {
      projQuery.status = sel.value; drawTable();
    });
    tools.appendChild(sel);
    var newBtn = el("button", "btn primary small", "مشروع جديد");
    newBtn.addEventListener("click", function () {
      if (window.HubEnterprise) HubEnterprise.goProjectsNew();
    });
    tools.appendChild(newBtn);
    sec.appendChild(tools);

    var wrap = el("div", "cmd-table-wrap");
    sec.appendChild(wrap);

    function drawTable() {
      wrap.textContent = "";
      var q = projQuery.q.toLowerCase();
      var items = pj.filter(function (p) {
        if (projQuery.status !== "ALL" && p.status !== projQuery.status) return false;
        if (!q) return true;
        return (String(p.name) + " " + String(p.objective || "")).toLowerCase().indexOf(q) >= 0;
      }).sort(function (a, b) {
        var va = a[projSort.key], vb = b[projSort.key];
        if (projSort.key === "id") return (a.id - b.id) * projSort.dir;
        return String(va == null ? "" : va).localeCompare(String(vb == null ? "" : vb)) * projSort.dir;
      });
      if (!items.length) {
        var em = el("div", "cmd-empty");
        em.appendChild(el("div", "cmd-empty-title",
          pj.length ? "لا نتائج مطابقة" : "لا مشاريع بعد"));
        em.appendChild(el("div", "cmd-empty-hint", pj.length
          ? "عدّل البحث أو التصفية."
          : "أنشئ أول مشروع ليبدأ المصنع عمله — الهدف ← خطة ← اعتمادك ← تنفيذ بأدلة."));
        wrap.appendChild(em);
        return;
      }
      var tbl = el("table", "ent-table");
      var thead = el("thead");
      var hr = el("tr");
      function th(label, key) {
        var h = el("th", "cmd-th-sort", label + " ");
        if (key) {
          var dir = el("span", "dir", projSort.key === key ? (projSort.dir < 0 ? "▾" : "▴") : "");
          h.appendChild(dir);
          h.addEventListener("click", function () {
            if (projSort.key === key) projSort.dir *= -1;
            else { projSort.key = key; projSort.dir = -1; }
            drawTable();
          });
        } else {
          h.classList.remove("cmd-th-sort");
        }
        return h;
      }
      ["المشروع", "الحالة", "التقدم", "المرحلة الحالية", "البوابة التالية",
       "المخرجات", "آخر نشاط"].forEach(function (t, i) {
        var keys = [null, "status", null, null, null, null, "updated_at"];
        hr.appendChild(th(t, keys[i]));
      });
      thead.appendChild(hr);
      tbl.appendChild(thead);
      var tb = el("tbody");
      items.forEach(function (p) {
        var tr = el("tr");
        var tdName = el("td");
        var nm = el("span", "ent-row-title", "#" + p.id + " " + (p.name || "مشروع"));
        tdName.appendChild(nm);
        if (p.objective) {
          var ob = el("div", "cmd-obj-cell ent-when", p.objective);
          ob.title = p.objective;
          tdName.appendChild(ob);
        }
        tr.appendChild(tdName);
        var tdSt = el("td"); tdSt.appendChild(chip(p.status)); tr.appendChild(tdSt);

        var tdProg = el("td", "", "…");
        tdProg.setAttribute("data-k", "التقدم");
        tr.appendChild(tdProg);
        progressOf(p.id, function (steps) {
          var done = steps.filter(function (s) {
            return ["COMPLETED", "VERIFIED", "PASS"].indexOf(s.status || "") !== -1;
          }).length;
          tdProg.textContent = steps.length
            ? done + "/" + steps.length + " خطوة"
            : "لا خطوات بعد";
          tdProg.classList.add("ent-mono");
        });

        var run = (cache.runs || []).filter(function (r) {
          return r.project_id === p.id;
        })[0];
        var stageTxt = run ? (run.stage || statusLabel(run.status))
          : (p.current_phase_id ? "مرحلة #" + p.current_phase_id : "—");
        tr.appendChild(el("td", "", stageTxt));

        var gateTxt = "—";
        if (p.status === "AWAITING_OWNER_APPROVAL") gateTxt = "بوابة المالك: اعتماد الخطة";
        else if (p.status === "COMPLETED" && p.completion_state === "CANDIDATE") {
          gateTxt = "بوابة المالك: التحقق النهائي";
        } else if (run && run.waiting_for && run.waiting_for.label) {
          gateTxt = "ينتظر: " + run.waiting_for.label;
        } else if (p.status === "BLOCKED") gateTxt = "محجوبة — فحص الجاهزية";
        tr.appendChild(el("td", "", gateTxt));

        var tdArt = el("td");
        var artBtn = el("button", "btn ghost small", "عرض");
        artBtn.addEventListener("click", function () {
          if (window.HubEnterprise) HubEnterprise.goArtifacts(p.id);
        });
        tdArt.appendChild(artBtn);
        tr.appendChild(tdArt);

        tr.appendChild(el("td", "ent-when", fmtWhen(p.updated_at)));
        tr.addEventListener("click", function (e) {
          if (e.target.closest("button")) return;
          if (window.HubEnterprise) HubEnterprise.openProject(p.id);
        });
        tb.appendChild(tr);
      });
      tbl.appendChild(tb);
      wrap.appendChild(tbl);
    }
    drawTable();
    return sec;
  }

  /* ================= E) صحة المصنع ================= */
  function healthBoard() {
    var sec = el("div", "cmd-section");
    var head = el("div", "cmd-section-head");
    head.appendChild(el("span", "cmd-section-title", "صحة المصنع — الجاهزية الحقيقية"));
    sec.appendChild(head);
    var grid = el("div", "cmd-health-grid");

    function card(title, lines) {
      var c = el("div", "cmd-health-card");
      var h = el("div", "cmd-health-head");
      h.appendChild(el("span", "cmd-health-title", title));
      c.appendChild(h);
      var ls = el("div", "cmd-health-lines");
      (lines || []).forEach(function (ln) {
        var row = el("div", "cmd-health-line");
        row.appendChild(el("span", "k", ln.k));
        var v = el("span", "v" + (ln.ar ? " ar" : ""), ln.v);
        if (ln.title) v.title = ln.title;
        row.appendChild(v);
        ls.appendChild(row);
      });
      c.appendChild(ls);
      return c;
    }

    /* الوكلاء والأدوار — الدور → نموذجه → مزوده → جاهزيته المُفحوصة */
    var roleLines = [];
    if (cache.cfg && cache.cfg.roles) {
      var provMap = {};
      (cache.cfg.providers || []).forEach(function (p) {
        (p.configurations || []).forEach(function (c) {
          if (c.readiness && c.readiness.status === "READY") provMap[p.id] = true;
        });
      });
      cache.cfg.roles.forEach(function (r) {
        var sel = r.selection || {};
        var okr = sel.provider && sel.model && provMap[sel.provider];
        roleLines.push({
          k: r.label || r.key,
          v: okr ? ((sel.provider || "—") + " · " + sel.model + " · READY")
                 : ((sel.provider || sel.model) ? ((sel.provider || "—") + " · " + (sel.model || "—") + " · UNTESTED")
                                              : "غير مهيأ"),
          title: okr ? "جاهز بمسبار مزود ناجح" : "الجاهزية غير مثبتة بفحص حي بعد"
        });
      });
    }
    if (!roleLines.length) {
      roleLines.push({ k: "الأدوار", v: "غير متاح", ar: true });
    }
    grid.appendChild(card("الوكلاء والأدوار", roleLines));

    /* المزودون */
    var provLines = [];
    (cache.cfg && cache.cfg.providers || []).forEach(function (p) {
      var rd = (p.configurations || []).map(function (c) {
        return (c.name || "default") + ":" + ((c.readiness && c.readiness.status) || "UNTESTED");
      }).join(" · ");
      provLines.push({
        k: (p.label || p.id) + (p.requires_key ? (p.has_key ? " (مفتاح محفوظ)" : " (لا مفتاح)") : ""),
        v: rd || "بلا تكوينات", ar: false,
        title: p.base_url || ""
      });
    });
    if (!provLines.length) provLines.push({ k: "المزودون", v: "غير متاح", ar: true });
    grid.appendChild(card("مزودو النماذج", provLines));

    /* بيئة التنفيذ والعزل */
    var h = cache.health || {};
    var sub = h.substrate || {};
    var envList = (cache.envs && cache.envs.environments) || [];
    var envLines = [
      { k: "ركيزة العزل", ar: true, v: sub.available ? "معزولة — " + (sub.isolation || "namespaces+seccomp") : "متوافقة بلا عزل (معلنة)" },
      { k: "بيئات التنفيذ", ar: true, v: envList.length ? String(envList.length) + " بيئة مسجلة" : "لا بيئات مسجلة" }
    ];
    if (cache.host && cache.host.runtime_truth) {
      var rt = cache.host.runtime_truth;
      envLines.push({ k: "المضيف", v: (rt.os || "—") + " · " + (rt.cpu_cores || "?") + " cores · " + (rt.memory || "—") });
    }
    grid.appendChild(card("بيئة التنفيذ والعزل", envLines));

    /* آخر اختبار صلاحية — من سجل القدرات المشتق الموحد */
    var capLines = [];
    var sum = cache.caps && cache.caps.summary;
    if (sum) {
      capLines.push({ k: "القدرات المشتقة", ar: true, v: "READY: " + (sum.READY || 0) + " · DEGRADED: " + (sum.DEGRADED || 0) + " · NOT_READY: " + (sum.NOT_READY || 0) });
    } else {
      capLines.push({ k: "القدرات", ar: true, v: "غير متاح" });
    }
    capLines.push({ k: "القاعدة", ar: true, v: "READY بمسبار حقيقي فقط — لا استنتاج من الإعدادات" });
    grid.appendChild(card("آخر فحص صلاحية", capLines));

    sec.appendChild(grid);
    return sec;
  }

  /* ================= F) خط النشاط ================= */
  var tlSource = null;
  function timelineSection() {
    var sec = el("div", "cmd-section");
    var head = el("div", "cmd-section-head");
    head.appendChild(el("span", "cmd-section-title", "النشاط الأخير — أحداث المصنع"));
    head.appendChild(el("span", "cmd-section-count", "حية"));
    sec.appendChild(head);
    var bodyB = el("div", "cmd-section-body flush");
    var tl = el("div", "cmd-tl");
    tl.style.padding = "6px 18px 10px";
    bodyB.appendChild(tl);
    sec.appendChild(bodyB);

    var events = [];
    function draw() {
      tl.textContent = "";
      if (!events.length) {
        var em = el("div", "cmd-empty");
        em.appendChild(el("div", "cmd-empty-title", "لا أحداث بعد"));
        em.appendChild(el("div", "cmd-empty-hint",
          "كل عملية في المصنع تُسجل حدثًا دائمًا — أول تشغيل سيظهر هنا لحظيًا."));
        tl.appendChild(em);
        return;
      }
      events.slice(0, 40).forEach(function (ev) {
        var row = el("div", "cmd-tl-row " + kindClass(ev.kind));
        row.appendChild(el("span", "cmd-tl-time",
          String(ev.created_at || "").slice(11, 19)));
        var what = el("span", "cmd-tl-what");
        what.appendChild(el("span", "ent-chip " + kindClass(ev.kind), kindLabel(ev.kind)));
        var txt = ev.payload ? humanPayload(ev) : "";
        if (txt) what.appendChild(document.createTextNode(" " + txt));
        row.appendChild(what);
        row.appendChild(el("span", "cmd-tl-proj",
          ev.project_id != null ? "مشروع #" + ev.project_id : "—"));
        row.title = "افتح تفاصيل الحدث (JSON الخام)";
        row.addEventListener("click", function () {
          if (window.Hub && Hub.openModal) Hub.openModal(ev);
        });
        tl.appendChild(row);
      });
    }
    /* لا JSON خام في القائمة التنفيذية — وصف بشري مختصر */
    function humanPayload(ev) {
      var p = ev.payload || {};
      if (p.objective) return String(p.objective).slice(0, 90);
      if (p.name) return String(p.name).slice(0, 90);
      if (p.role) return "الدور: " + p.role;
      if (p.tool) return "أداة: " + p.tool;
      if (p.gate_id != null) return "بوابة #" + p.gate_id;
      if (p.step_id != null) return "خطوة #" + p.step_id;
      return "";
    }

    /* تاريخ أولي: آخر أحداث المشاريع القائمة ثم البث الحي يلحق فوقها */
    var recent = (cache.projects || []).slice().sort(function (a, b) {
      return String(b.updated_at || "").localeCompare(String(a.updated_at || ""));
    }).slice(0, 6);
    Promise.all(recent.map(function (p) {
      return Hub.fetchJSON("/api/projects/" + p.id + "/events?limit=12")
        .catch(function () { return { ok: false }; });
    })).then(function (outs) {
      outs.forEach(function (o) {
        ((o.ok && o.j && o.j.events) || []).forEach(function (ev) { events.push(ev); });
      });
      events.sort(function (a, b) {
        return String(b.created_at || "").localeCompare(String(a.created_at || ""));
      });
      draw();
    });

    if (tlSource) { try { tlSource.close(); } catch (e) {} }
    tlSource = new EventSource("/api/projects/events/stream");
    tlSource.onmessage = function (m) {
      try {
        var ev = JSON.parse(m.data);
        if (ev.kind === "run.start" || ev.kind === "run.done") return;
        events.unshift(ev);
        if (events.length > 120) events.pop();
        draw();
      } catch (e) { /* جزء ناقص */ }
    };
    return sec;
  }

  /* ================= الصفحة التنفيذية الكاملة (A–F) ================= */
  function render() {
    var body = $("overview-body");
    if (!body) return;
    body.textContent = "";
    body.appendChild(el("div", "cmd-loading", "جارٍ تجميع حالة المصنع من المصادر الحية…"));

    gather().then(function () {
      var pj = cache.projects || [];
      var runs = cache.runs || [];
      body.textContent = "";
      var page = el("div", "cmd-page");

      /* B — التشغيل الحالي (تشغيل واحد يُثرى بأحداثه؛ أكثر تُختصر) */
      if (runs.length) {
        var main = runs[0];
        enrichRun(main).then(function () {
          var old = page.querySelector(".cmd-current");
          if (old && old.parentNode) {
            old.parentNode.parentNode.replaceChild(currentRunPanel(main), old.parentNode);
          }
        });
        page.appendChild(currentRunPanel(main));
        if (runs.length > 1) {
          var more = el("div", "ent-note");
          more.style.padding = "6px 14px";
          more.textContent = "تشغيلات إضافية نشطة: " + (runs.length - 1) +
            " — تفصيلها في وحدة التشغيلات الحية.";
          page.appendChild(more);
        }
      }

      /* C — طابور القرارات */
      var pending = [];
      pj.forEach(function (p) {
        if (p.status === "AWAITING_OWNER_APPROVAL") {
          pending.push({ p: p, kind: "plan",
            why: "خطة جاهزة بانتظار اعتمادك — الاعتماد قرار بشري وحده." });
        }
        if (p.status === "COMPLETED" && p.completion_state === "CANDIDATE") {
          pending.push({ p: p, kind: "verify",
            why: "اكتمل التنفيذ والتدقيق النهائي — القناة الوحيدة إلى VERIFIED هي تحققك." });
        }
        if (p.status === "BLOCKED") {
          pending.push({ p: p, kind: "blocked",
            why: "محجوبة: " + (p.last_error || "سبب غير معلن — أعد فحص الجاهزية.") });
        }
        if (p.status === "ESCALATED") {
          pending.push({ p: p, kind: "blocked", why: "مصعدة لك بحاجة تدخل." });
        }
      });
      page.appendChild(decisionSection(pending));

      /* D — جدول المشاريع */
      page.appendChild(renderProjectsTable(body));

      /* E — صحة المصنع */
      page.appendChild(healthBoard());

      /* F — النشاط الأخير */
      page.appendChild(timelineSection());

      body.textContent = "";
      body.appendChild(page);
      renderStrip();
    }).catch(function (e) {
      body.textContent = "";
      var box = el("div", "ent-error");
      box.appendChild(el("div", "ent-error-title", "تعذر جلب حالة المصنع"));
      box.appendChild(el("div", "ent-error-msg", "فشل الاتصال بالخادم: " + e));
      var btn = el("button", "btn ghost small", "إعادة المحاولة");
      btn.addEventListener("click", render);
      box.appendChild(btn);
      body.appendChild(box);
    });
  }

  window.CommandCenter = {
    render: render,
    renderStrip: renderStrip,
    startStrip: startStrip,
    wake: function () { /* الأحداث توقظ الشريط عبر startStrip */ }
  };
  startStrip();
})();
