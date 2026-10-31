/* Agentic Engineering System — أرضية المصنع الحية (015).
 * الإطار ثلاثي الأعمدة على نمط DSH متوافقًا مع RTL وهوية 014:
 *   [يمين] الجلسات والوكلاء — قائمة حية من runs/active + projects.
 *   [وسط]  نافذة عمل الوكيل — تدفق الأحداث بعقود دلالية: هوية الدور،
 *          سرد النموذج الحي (استدعاء/تفكير/إنتاج)، عقد الأدوات بمراحلها
 *          (started→succeeded|failed)، أحكام الفحص، بوابات المالك.
 *   [يسار] اللوح — الملفات/المخرجات/الخطة/التنفيذ، قابل للسحب والطي.
 *
 * مبدأ صارم: كل ما يُعرض من مصادر الحقيقة الحالية حصرًا
 * (/api/projects/*، بث LiveEvents) — لا عنصر ديكوري ولا حالة مختلقة:
 * إن غاب الاتصال يظهر «—» وصف فشل صريح بإعادة محاولة.
 * صفر تعديلات بايثون: كل الحيوية من الواجهة فوق APIs القائمة.
 */
(function () {
  "use strict";

  var API = "/api";
  var MAX_NODES = 300;

  var S = {
    sel: null,
    runs: [],
    projects: [],
    detail: {},
    evLastId: 0,
    toolCards: {},
    modelCards: {},
    flowCount: 0,
    trimmed: 0,
    rateBuf: [],
    timers: [],
    stats: { tools: 0 },
    density: "standard",
    panel: { open: true, tab: "files", w: 45 },
    sessionsCollapsed: false,
    gateBusy: false,
    built: false,
    started: false,
  };

  /* ================= أدوات أساسية ================= */
  function $(sel, root) { return (root || document).querySelector(sel); }
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }
  function tech(parent, text, title) {
    var t = el("span", "tech", text);
    t.dir = "ltr";
    if (title) t.title = title;
    parent.appendChild(t);
    return t;
  }
  function rel(ts) {
    if (!ts) return "—";
    var d = Date.now() - new Date(ts).getTime();
    if (isNaN(d)) return "—";
    if (d < 0) d = 0;
    if (d < 5000) return "الآن";
    if (d < 60000) return "قبل " + Math.floor(d / 1000) + " ث";
    if (d < 3600000) return "قبل " + Math.floor(d / 60000) + " د";
    if (d < 86400000) return "قبل " + Math.floor(d / 3600000) + " س";
    return "قبل " + Math.floor(d / 86400000) + " يوم";
  }
  function fmtBytes(n) {
    if (n == null) return "—";
    if (n < 1024) return n + " B";
    if (n < 1048576) return (n / 1024).toFixed(1) + " KB";
    return (n / 1048576).toFixed(1) + " MB";
  }
  function fmtDur(ms) {
    if (ms == null) return "—";
    if (ms < 1000) return ms + "ms";
    return (ms / 1000).toFixed(ms < 10000 ? 1 : 0) + "s";
  }
  function stamp(node, ts) {
    node.dataset.ts = ts || "";
    node.textContent = rel(ts);
  }
  function apiGet(path) {
    return fetch(API + path, { headers: { accept: "application/json" } })
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status + " — " + path);
        return r.json();
      });
  }
  function apiPost(path, body) {
    return fetch(API + path, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body || {}),
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (j) {
        if (!r.ok) throw new Error(j.error || j.detail || ("HTTP " + r.status));
        return j;
      });
    });
  }

  /* ================= خرائط الهوية ================= */
  var ROLE = {
    thinker:     { label: "المفكر",  cls: "role-thinker" },
    implementer: { label: "المنفذ",  cls: "role-implementer" },
    reviewer:    { label: "المدقق",  cls: "role-reviewer" },
    verifier:    { label: "المراجع", cls: "role-verifier" },
    arbiter:     { label: "المحكَّم", cls: "role-arbiter" },
    coordinator: { label: "المنسق",  cls: "role-coordinator" },
  };
  function roleMeta(r) {
    return ROLE[r] || { label: r || "وكيل", cls: "role-coordinator" };
  }
  function statusMeta(run, project) {
    var st = (run && run.status) || (project && project.status) || "";
    switch (st) {
      case "RUNNING":   return { cls: "st-running",  label: "يعمل الآن", pulse: true };
      case "BLOCKED":   return { cls: "st-blocked",  label: "بانتظار اعتمادك", pulse: false };
      case "PAUSED":    return { cls: "st-paused",   label: "متوقف مؤقتًا", pulse: false };
      case "STOPPED":   return { cls: "st-stopped",  label: "موقوف", pulse: false };
      case "COMPLETED": return { cls: "st-candidate", label: "مرشح للتحقق", pulse: false };
      case "VERIFIED":  return { cls: "st-verified", label: "مُتحقق ✓", pulse: false };
      default:          return { cls: "st-idle",     label: st || "مسودة", pulse: false };
    }
  }
  var KIND_TITLES = {
    PLAN_CREATED: "خطة جديدة", PLAN_REVISED: "خطة منقحة",
    PLAN_APPROVAL_REQUIRED: "بانتظار اعتمادك", PLAN_APPROVED: "خطة معتمدة",
    PHASE_STARTED: "بدأت مرحلة", PHASE_COMPLETED: "اكتملت مرحلة",
    STEP_STARTED: "بدأت خطوة", STEP_COMPLETED: "اكتملت خطوة",
    EXECUTION_STARTED: "بدأ تنفيذ", EXECUTION_COMPLETED: "اكتمل تنفيذ",
    EXECUTION_FAILED: "فشل تنفيذ", EXECUTION_BLOCKED: "تنفيذ محجوز",
    ROLE_EXECUTING: "دور يعمل", TOOL_EXECUTION: "أداة",
    MODEL_CALL_STARTED: "استدعاء نموذج", MODEL_CALL_COMPLETED: "اكتمل استدعاء النموذج",
    EVIDENCE_CREATED: "أدلة جديدة", TEST_COMPLETED: "انتهى الفحص",
    REVIEW_COMPLETED: "حكم المراجعة", AUDIT_COMPLETED: "تدقيق",
    CHECKPOINT_CREATED: "نقطة حفظ", PREFLIGHT_PASS: "فحص التمهيد ناجح",
    PREFLIGHT_BLOCKED: "فحص التمهيد حاجب", ENVIRONMENT_READY: "البيئة جاهزة",
    OWNER_GATE_REQUIRED: "بانتظار اعتمادك", OWNER_GATE_RESOLVED: "بوابة مالك حُسمت",
    PROJECT_CREATED: "مشروع جديد", PROJECT_VERIFIED: "مشروع مُتحقق",
    JOB_STARTED: "بدأت الوظيفة", JOB_COMPLETED: "اكتملت الوظيفة",
    JOB_FAILED: "فشلت الوظيفة", STAGE_REVIEW: "مراجعة مرحلة",
    PLANNING_STARTED: "بدأ التخطيط", PLAN_GENERATING: "توليد الخطة",
  };

  /* ================= بناء الهيكل (مرة واحدة) ================= */
  function build() {
    if (S.built) return;
    S.built = true;
    var floor = el("section", "floor");
    floor.id = "floor";
    floor.hidden = true;

    /* ---------- العمود الأيمن: الجلسات ---------- */
    var sessions = el("aside", "floor-sessions");
    sessions.id = "floor-sessions";
    var sHead = el("header", "fs-head");
    var sBrand = el("div", "fs-brand");
    var sMark = el("span", "icon lg");
    sMark.innerHTML = '<svg><use href="#i-factory"/></svg>';
    var stw = el("span", "fs-brandtext");
    stw.appendChild(el("span", "fs-title", "أرضية المصنع"));
    stw.appendChild(el("span", "fs-sub", "…"));
    sBrand.appendChild(sMark);
    sBrand.appendChild(stw);
    var sLive = el("span", "chip agent fs-live");
    sLive.appendChild(el("span", "status-dot sm live"));
    sLive.appendChild(el("span", "fs-live-label", "جارٍ الاتصال…"));
    var sCollapse = el("button", "icon-btn fs-collapse");
    sCollapse.title = "طي عمود الجلسات";
    sCollapse.innerHTML = '<span class="icon"><svg><use href="#i-forward"/></svg></span>';
    sHead.appendChild(sBrand);
    sHead.appendChild(sLive);
    sHead.appendChild(sCollapse);
    var sSearch = el("div", "fs-search");
    var sInput = el("input");
    sInput.type = "search";
    sInput.placeholder = "ابحث في الجلسات…";
    sInput.setAttribute("aria-label", "ابحث في الجلسات");
    sSearch.appendChild(sInput);
    var sList = el("nav", "fs-list");
    sList.id = "floor-sessions-list";
    sList.setAttribute("aria-label", "الجلسات والوكلاء");
    var sFoot = el("footer", "fs-foot");
    var sExit = el("button", "btn-ghost fs-exit");
    sExit.innerHTML = '<span class="icon sm"><svg><use href="#i-back"/></svg></span><span>الواجهة الكلاسيكية</span>';
    sFoot.appendChild(sExit);
    sessions.appendChild(sHead);
    sessions.appendChild(sSearch);
    sessions.appendChild(sList);
    sessions.appendChild(sFoot);

    /* ---------- العمود الأوسط: نافذة الوكيل ---------- */
    var center = el("main", "floor-center");
    var cHead = el("header", "fc-head");
    var cHeadL = el("div", "fc-head-main");
    var cTitle = el("span", "fc-title", "اختر جلسة من العمود الأيمن");
    cTitle.id = "floor-c-title";
    var cMeta = el("div", "fc-meta");
    cMeta.id = "floor-c-meta";
    cHeadL.appendChild(cTitle);
    cHeadL.appendChild(cMeta);
    var cActs = el("div", "fc-actions");
    var cStop = el("button", "btn-ghost danger fc-stop");
    cStop.hidden = true;
    cStop.innerHTML = '<span class="icon sm"><svg><use href="#i-stop"/></svg></span><span class="fc-stop-label">إيقاف</span>';
    cActs.appendChild(cStop);
    cHead.appendChild(cHeadL);
    cHead.appendChild(cActs);

    var gate = el("div", "fc-gate");
    gate.id = "floor-gate";
    gate.hidden = true;

    var densityBar = el("div", "fc-density");
    densityBar.appendChild(el("span", "fc-density-label", "الكثافة:"));
    [["compact", "مضغوط"], ["standard", "قياسي"], ["detailed", "مفصّل"]].forEach(function (d) {
      var b = el("button", "fc-density-btn" + (d[0] === "standard" ? " on" : ""), d[1]);
      b.dataset.d = d[0];
      b.addEventListener("click", function () { setDensity(d[0]); });
      densityBar.appendChild(b);
    });

    var flow = el("div", "fc-flow");
    flow.id = "floor-flow";
    var trimmedNote = el("div", "fc-trimmed");
    trimmedNote.id = "floor-trimmed";
    trimmedNote.hidden = true;

    var follow = el("button", "fc-follow");
    follow.id = "floor-follow";
    follow.hidden = true;
    follow.innerHTML = '<span class="icon sm"><svg><use href="#i-chevron-d"/></svg></span><span>متابعة الحي</span>';

    var stats = el("footer", "fc-stats");
    stats.id = "floor-stats";
    [["pulse", "نبض"], ["agent", "الوكيل الحالي"], ["tools", "أدوات الجلسة"],
     ["steps", "خطوات"], ["progress", "التقدم"], ["elapsed", "الزمن"], ["rate", "الإنتاج"]]
      .forEach(function (d) {
        var c = el("div", "fc-stat fc-stat-" + d[0]);
        c.appendChild(el("span", "fc-stat-label", d[1]));
        var v = el("span", "fc-stat-value tech", "—");
        v.id = "floor-stat-" + d[0];
        c.appendChild(v);
        stats.appendChild(c);
      });

    center.appendChild(cHead);
    center.appendChild(gate);
    center.appendChild(densityBar);
    center.appendChild(flow);
    center.appendChild(trimmedNote);
    center.appendChild(follow);
    center.appendChild(stats);

    /* ---------- اللوح الأيسر ---------- */
    var panel = el("aside", "floor-panel");
    panel.id = "floor-panel";
    var pHead = el("header", "fp-head");
    var pTabs = el("nav", "fp-tabs");
    pTabs.setAttribute("aria-label", "أقسام اللوح");
    [["files", "الملفات"], ["outputs", "المخرجات"], ["plan", "الخطة"], ["execs", "التنفيذ"]]
      .forEach(function (t) {
        var b = el("button", "fp-tab" + (t[0] === "files" ? " on" : ""), t[1]);
        b.dataset.tab = t[0];
        b.addEventListener("click", function () { setPanelTab(t[0]); });
        pTabs.appendChild(b);
      });
    var pToggle = el("button", "icon-btn fp-toggle");
    pToggle.title = "طي/فتح اللوح";
    pToggle.innerHTML = '<span class="icon"><svg><use href="#i-collapse"/></svg></span>';
    pHead.appendChild(pTabs);
    pHead.appendChild(pToggle);
    var pBody = el("div", "fp-body");
    pBody.id = "floor-panel-body";
    var resizer = el("div", "fp-resizer");
    resizer.id = "floor-resizer";
    resizer.title = "اسحب لتغيير عرض اللوح";
    panel.appendChild(pHead);
    panel.appendChild(pBody);
    panel.appendChild(resizer);

    /* ---------- زر إعادة الفتح (خارج الأرضية) ---------- */
    var reopen = el("button", "floor-reopen");
    reopen.id = "floor-reopen";
    reopen.hidden = true;
    reopen.innerHTML = '<span class="icon sm"><svg><use href="#i-factory"/></svg></span><span>أرضية المصنع</span>';

    var app = $(".app") || document.body;
    app.appendChild(floor);
    document.body.appendChild(reopen);
    app.insertBefore(reopen, null);

    floor.appendChild(sessions);
    floor.appendChild(center);
    floor.appendChild(panel);

    /* ---------- الربط ---------- */
    sExit.addEventListener("click", closeFloor);
    sCollapse.addEventListener("click", toggleSessions);
    pToggle.addEventListener("click", togglePanel);
    sInput.addEventListener("input", function () { renderSessions(sInput.value.trim()); });
    cStop.addEventListener("click", armStop);
    follow.addEventListener("click", function () { followLive(true); });
    flow.addEventListener("scroll", onFlowScroll);
    bindResizer(resizer, panel);
    reopen.addEventListener("click", function () {
      try { sessionStorage.setItem("aes_floor_closed", "0"); } catch (err) {}
      openFloor();
    });
    var mb = $("#modal-backdrop");
    if (mb) mb.addEventListener("click", function (e) {
      if (e.target === mb) mb.hidden = true;
    });
    var mc = $("#modal-close");
    if (mc) mc.addEventListener("click", function () { mb.hidden = true; });

    floor.addEventListener("click", function (e) {
      var btn = e.target.closest("[data-json]");
      if (btn) {
        var data;
        try { data = JSON.parse(btn.getAttribute("data-json")); } catch (err) { return; }
        openJsonModal(btn.getAttribute("data-json-title") || "تفاصيل الحدث", data);
      }
    });

    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && !floor.hidden && !panel._resizing) {
        var modal = $("#modal-backdrop");
        if (modal && !modal.hidden) return;
        closeFloor();
      }
    });

    restorePanel();
    applyDensity();
  }

  /* ================= الجلسات ================= */
  function loadRuns() {
    var failA = null, failB = null;
    var a = apiGet("/projects/runs/active").catch(function (e) { failA = e; return { runs: [] }; });
    var b = apiGet("/projects").catch(function (e) { failB = e; return { projects: [] }; });
    return Promise.all([a, b]).then(function (res) {
      S.runs = (res[0] && res[0].runs) || [];
      var pj = res[1];
      S.projects = Array.isArray(pj) ? pj : (pj.projects || pj.items || []);
      if (failA && failB) {
        renderSessionsFail(failA);
      } else {
        renderSessions();
      }
      if (S.sel == null && (S.runs.length || S.projects.length)) autoSelect();
      updateStatsFromRuns();
    });
  }
  function renderSessionsFail(err) {
    var list = $("#floor-sessions-list");
    if (!list) return;
    list.textContent = "";
    var w = el("div", "fs-empty fail");
    w.appendChild(el("div", "", "تعذر تحميل الجلسات — مصدر الحقيقة لا يستجيب"));
    var m = el("div", "fs-empty-err");
    tech(m, String(err && err.message || err));
    w.appendChild(m);
    var btn = el("button", "btn-ghost sm", "إعادة المحاولة");
    btn.addEventListener("click", function () { loadRuns(); });
    w.appendChild(btn);
    list.appendChild(w);
  }
  function findRun(id) {
    for (var i = 0; i < S.runs.length; i++) if (S.runs[i].project_id === id) return S.runs[i];
    return null;
  }
  function findProject(id) {
    for (var i = 0; i < S.projects.length; i++) if (S.projects[i].id === id) return S.projects[i];
    return null;
  }
  function autoSelect() {
    var sorted = S.runs.slice().sort(function (a, b) {
      return (a.status === "RUNNING" ? 0 : 1) - (b.status === "RUNNING" ? 0 : 1);
    });
    if (sorted.length) { select(sorted[0].project_id); return; }
    if (S.projects.length) select(S.projects[0].id);
  }
  function renderSessions(query) {
    var list = $("#floor-sessions-list");
    if (!list) return;
    list.textContent = "";
    var items = [];
    S.projects.forEach(function (p) { items.push({ p: p, r: findRun(p.id) }); });
    if (query) {
      var q = query.toLowerCase();
      items = items.filter(function (it) {
        return String(it.p.name || "").toLowerCase().indexOf(q) >= 0;
      });
    }
    items.sort(function (a, b) {
      var ra = a.r && a.r.status === "RUNNING" ? 0 : 1;
      var rb = b.r && b.r.status === "RUNNING" ? 0 : 1;
      if (ra !== rb) return ra - rb;
      return new Date(b.p.updated_at || 0) - new Date(a.p.updated_at || 0);
    });
    if (!items.length) {
      list.appendChild(el("div", "fs-empty", query ? "لا جلسة تطابق البحث" : "لا جلسات بعد"));
      return;
    }
    items.forEach(function (it) { list.appendChild(sessionCard(it.p, it.r)); });
    var liveCount = S.runs.filter(function (r) { return r.status === "RUNNING"; }).length;
    var blocked = S.runs.filter(function (r) { return r.status === "BLOCKED"; }).length;
    var sub = $("#floor-sessions .fs-sub");
    if (sub) sub.textContent = liveCount + " يعمل · " + blocked + " بانتظار اعتماد · " + items.length + " جلسة";
  }
  function sessionCard(p, r) {
    var st = statusMeta(r, p);
    var card = el("button", "fs-item" + (p.id === S.sel ? " sel" : "") + (st.pulse ? " pulsing" : ""));
    card.dataset.pid = p.id;
    var top = el("div", "fs-item-top");
    top.appendChild(el("span", "status-dot sm " + (st.pulse ? "live" : (st.cls === "st-blocked" ? "off" : ""))));
    var name = el("span", "fs-item-name", p.name || ("مشروع " + p.id));
    name.title = name.textContent;
    top.appendChild(name);
    top.appendChild(el("span", "chip " + st.cls, st.label));
    card.appendChild(top);
    var prog = (r && r.progress) || null;
    if (prog && prog.steps_total) {
      var bar = el("div", "fs-item-bar");
      var fill = el("div", "fs-item-bar-fill");
      var pct = Math.max(0, Math.min(100, prog.percent || 0));
      fill.style.width = pct + "%";
      bar.appendChild(fill);
      card.appendChild(bar);
      var sub = el("div", "fs-item-sub");
      var cur = prog.current_step && prog.current_step.objective
        ? String(prog.current_step.objective) : "";
      if (cur.length > 64) cur = cur.slice(0, 64) + "…";
      sub.appendChild(el("span", "fs-item-step", cur || "…"));
      var nums = el("span", "fs-item-nums");
      tech(nums, Math.round(pct) + "%");
      sub.appendChild(nums);
      card.appendChild(sub);
    } else {
      var sub2 = el("div", "fs-item-sub");
      var dim = el("span", "fs-item-step dim");
      stamp(dim, p.updated_at);
      sub2.appendChild(dim);
      card.appendChild(sub2);
    }
    if (r && r.waiting_for && r.waiting_for.kind === "owner_gate") {
      var g = el("div", "fs-item-gate");
      g.appendChild(el("span", "icon sm", ""));
      g.appendChild(el("span", "", "بوابة مالك: " + ((r.waiting_for.gates || []).length || 1)));
      card.appendChild(g);
    }
    card.addEventListener("click", function () { select(p.id); });
    return card;
  }

  /* ================= التحديد والرأس ================= */
  function select(pid) {
    S.sel = pid;
    S.evLastId = 0;
    S.toolCards = {};
    S.modelCards = {};
    S.flowCount = 0;
    S.trimmed = 0;
    S.rateBuf = [];
    S.stats.tools = 0;
    S.detail = {};
    updateStat("tools", "0");
    document.querySelectorAll(".fs-item").forEach(function (n) {
      n.classList.toggle("sel", Number(n.dataset.pid) === Number(pid));
    });
    var flow = $("#floor-flow");
    if (flow) flow.textContent = "";
    var trimmed = $("#floor-trimmed");
    if (trimmed) trimmed.hidden = true;
    renderHeaderPlaceholder();
    loadHistory();
    loadDetail();
    renderSessions();
    setTimeout(refreshGateFromRuns, 900);
  }
  function renderHeaderPlaceholder() {
    var t = $("#floor-c-title");
    var m = $("#floor-c-meta");
    if (t) t.textContent = "تحميل الجلسة…";
    if (m) m.textContent = "";
    hideGate();
  }
  function renderHeader() {
    var p = findProject(S.sel);
    var r = findRun(S.sel);
    if (!p) return;
    var st = statusMeta(r, p);
    var t = $("#floor-c-title");
    if (t) t.textContent = p.name || ("مشروع " + p.id);
    var m = $("#floor-c-meta");
    if (!m) return;
    m.textContent = "";
    m.appendChild(el("span", "chip " + st.cls, st.label));
    var ex = latestExecution();
    if (ex) {
      var role = roleMeta(ex.agent_role);
      m.appendChild(el("span", "chip role-chip " + role.cls, role.label));
      var mk = el("span", "chip");
      mk.appendChild(el("span", "", "النموذج: "));
      tech(mk, ex.model || "—");
      m.appendChild(mk);
    }
    if (r && r.heartbeat_at) {
      var hb = el("span", "chip info");
      hb.appendChild(el("span", "status-dot sm live"));
      var hbl = el("span", "fc-hb", rel(r.heartbeat_at));
      hbl.dataset.ts = r.heartbeat_at;
      hb.appendChild(hbl);
      m.appendChild(hb);
    }
    var stop = $(".fc-stop");
    if (stop) {
      var canStop = !!(r && r.status === "RUNNING" && p.stop_requested !== true);
      stop.hidden = !canStop;
      if (canStop) disarmStop();
    }
  }
  function latestExecution() {
    if (!S.detail || !S.detail.executions || !S.detail.executions.length) return null;
    return S.detail.executions[0];
  }

  /* ================= تفاصيل الجلسة ================= */
  function loadDetail() {
    if (S.sel == null) return Promise.resolve();
    var pid = S.sel;
    return Promise.all([
      apiGet("/projects/" + pid + "/executions?limit=8").catch(function () { return { executions: [] }; }),
      apiGet("/projects/" + pid + "/artifacts").catch(function () { return { artifacts: [] }; }),
      apiGet("/projects/" + pid + "/phases").catch(function () { return { phases: [] }; }),
    ]).then(function (res) {
      if (S.sel !== pid) return;
      S.detail = {
        executions: (res[0] && res[0].executions) || [],
        artifacts: (res[1] && res[1].artifacts) || [],
        phases: (res[2] && res[2].phases) || [],
      };
      renderHeader();
      renderPanel();
      refreshGateFromRuns();
    });
  }

  /* ================= التدفق: التاريخ ثم البث ================= */
  function loadHistory() {
    if (S.sel == null) return;
    var pid = S.sel;
    apiGet("/projects/" + pid + "/events?limit=80").then(function (d) {
      if (S.sel !== pid) return;
      var evs = (d && d.events) || [];
      evs.sort(function (a, b) { return (a.id || 0) - (b.id || 0); });
      evs.forEach(function (e) { drawEvent(e); });
      var flow = $("#floor-flow");
      if (flow && !flow.children.length) flow.appendChild(emptyFlow());
    }).catch(function (err) {
      if (S.sel !== pid) return;
      var flow = $("#floor-flow");
      if (flow && !flow.children.length) flow.appendChild(failCard("تعذر تحميل تاريخ الأحداث", err, function () { loadHistory(); }));
    });
  }
  function emptyFlow() {
    var w = el("div", "empty-state");
    var mark = el("div", "empty-mark icon");
    mark.innerHTML = '<svg><use href="#i-runs"/></svg>';
    w.appendChild(mark);
    w.appendChild(el("div", "empty-title", "لا أحداث بعد لهذه الجلسة"));
    w.appendChild(el("div", "empty-hint", "عند بدء العمل سيظهر هنا كل ما يقوله الوكيل ويفعله لحظة بلحظة — من مصدر الحقيقة حصرًا."));
    return w;
  }
  function failCard(msg, err, retry) {
    var c = el("div", "evt evt-fail");
    var row = el("div", "evt-row");
    var ic = el("span", "icon sm evt-ic");
    ic.innerHTML = '<svg><use href="#i-alert"/></svg>';
    row.appendChild(ic);
    row.appendChild(el("span", "evt-title", msg));
    c.appendChild(row);
    var det = el("div", "evt-sub");
    tech(det, String(err && err.message || err || ""));
    c.appendChild(det);
    if (retry) {
      var b = el("button", "btn-ghost sm", "إعادة المحاولة");
      b.addEventListener("click", retry);
      c.appendChild(b);
    }
    return c;
  }
  function onLive(e) {
    var pid = e.project_id != null ? e.project_id : (e.payload && e.payload.project_id);
    if (S.sel != null && Number(pid) === Number(S.sel)) drawEvent(e);
    var card = document.querySelector('.fs-item[data-pid="' + pid + '"]');
    if (card) card.classList.add("ticked");
  }
  function pruneFlow() {
    var flow = $("#floor-flow");
    if (!flow) return;
    while (flow.children.length > MAX_NODES) {
      var removed = flow.removeChild(flow.firstChild);
      S.flowCount--;
      S.trimmed++;
      var k = removed.getAttribute("data-toolkey");
      if (k) delete S.toolCards[k];
      var m = removed.getAttribute("data-modelkey");
      if (m) delete S.modelCards[m];
    }
    if (S.trimmed) {
      var t = $("#floor-trimmed");
      if (t) { t.hidden = false; t.textContent = "أحداث أقدم مُختزلة: " + S.trimmed + " — التاريخ الكامل في تبويب التاريخ للجلسة"; }
    }
  }
  function addNode(node) {
    var flow = $("#floor-flow");
    if (!flow) return;
    var empty = flow.querySelector(".empty-state");
    if (empty) empty.remove();
    flow.appendChild(node);
    S.flowCount++;
    pruneFlow();
    if (nearBottom()) followLive(false);
  }
  function nearBottom() {
    var flow = $("#floor-flow");
    if (!flow) return true;
    return flow.scrollHeight - flow.scrollTop - flow.clientHeight < 140;
  }
  function followLive(smooth) {
    var flow = $("#floor-flow");
    if (!flow) return;
    flow.scrollTo({ top: flow.scrollHeight, behavior: smooth ? "smooth" : "auto" });
  }
  function onFlowScroll() {
    var f = $("#floor-follow");
    if (f) f.hidden = nearBottom();
  }
  function markJson(node, e) {
    node.setAttribute("data-json", JSON.stringify({ id: e.id, kind: e.kind, payload: e.payload, created_at: e.created_at }));
    node.setAttribute("data-json-title", (KIND_TITLES[e.kind] || e.kind) + " #" + (e.id || ""));
  }
  function kvRow(label, valueNode) {
    var r = el("div", "evt-kv");
    r.appendChild(el("span", "evt-kv-label", label));
    r.appendChild(valueNode);
    return r;
  }

  /* ---------- رسم الأحداث: عقود دلالية ---------- */
  function drawEvent(e) {
    var id = parseInt(e.id || e.event_id || 0, 10);
    if (id) {
      if (id <= S.evLastId) return;
      S.evLastId = id;
    }
    var p = e.payload || {};
    var kind = e.kind;
    var node = null;

    if (kind === "TOOL_EXECUTION") node = drawTool(p, e);
    else if (kind === "MODEL_CALL_STARTED" || kind === "MODEL_CALL_PROGRESS" ||
             kind === "MODEL_REASONING" || kind === "MODEL_CALL_COMPLETED") node = drawModel(kind, p, e);
    else if (kind === "STEP_STARTED" || kind === "STEP_COMPLETED") node = drawStep(kind, p, e);
    else if (kind === "EXECUTION_STARTED" || kind === "EXECUTION_COMPLETED" ||
             kind === "EXECUTION_FAILED" || kind === "EXECUTION_BLOCKED") node = drawExecution(kind, p, e);
    else if (kind === "ROLE_EXECUTING") node = drawRole(p, e);
    else if (kind === "EVIDENCE_CREATED") node = drawEvidence(p, e);
    else if (kind === "REVIEW_COMPLETED" || kind === "TEST_COMPLETED" ||
             kind === "AUDIT_COMPLETED" || kind === "PREFLIGHT_PASS" ||
             kind === "PREFLIGHT_BLOCKED") node = drawVerdict(kind, p, e);
    else if (kind === "PLAN_APPROVAL_REQUIRED" || kind === "OWNER_GATE_REQUIRED") node = drawGateEvent(p, e);
    else node = drawGeneric(kind, p, e);

    if (node) { markJson(node, e); addNode(node); }
  }
  function evtShell(cls, iconId) {
    var c = el("div", "evt " + cls);
    var row = el("div", "evt-row");
    if (iconId) {
      var ic = el("span", "icon sm evt-ic");
      ic.innerHTML = '<svg><use href="#' + iconId + '"/></svg>';
      row.appendChild(ic);
    }
    c.appendChild(row);
    var time = el("span", "evt-time");
    stamp(time, null);
    c.appendChild(time);
    c._row = row;
    return c;
  }
  function drawTool(p, e) {
    var key = (p.execution_id != null ? p.execution_id : (p.step_id || "?")) + "|" + (p.tool || "?");
    var phase = p.phase || "";
    var created = !S.toolCards[key];
    var card;
    if (created) {
      card = evtShell("evt-tool", "i-terminal");
      card.setAttribute("data-toolkey", key);
      var title = el("span", "evt-title");
      title.appendChild(el("span", "evt-kind", "أداة"));
      var nm = el("span", "evt-tool-name");
      tech(nm, p.tool || "?");
      title.appendChild(nm);
      card._row.appendChild(title);
      card._spin = el("span", "evt-spin");
      card._row.appendChild(card._spin);
      card._sub = el("div", "evt-sub");
      card.appendChild(card._sub);
      S.toolCards[key] = card;
      S.stats.tools++;
      updateStat("tools", String(S.stats.tools));
    } else {
      card = S.toolCards[key];
    }
    if (p.role) {
      var role = roleMeta(p.role);
      var old = card._row.querySelector(".role-chip");
      if (old) old.remove();
      card._row.appendChild(el("span", "role-chip " + role.cls, role.label));
    }
    if (phase === "succeeded" || phase === "failed") {
      card.classList.remove("evt-running");
      card.classList.add(phase === "failed" ? "evt-fail" : "evt-ok");
      if (card._spin) { card._spin.remove(); card._spin = null; }
      var mark = el("span", "evt-mark");
      mark.innerHTML = phase === "failed"
        ? '<svg><use href="#i-alert"/></svg>'
        : '<svg><use href="#i-check"/></svg>';
      card._row.appendChild(mark);
    } else {
      card.classList.add("evt-running");
    }
    var bits = [];
    if (p.duration_ms) bits.push("زمن " + fmtDur(p.duration_ms));
    if (p.execution_site) bits.push("موقع " + p.execution_site);
    if (p.error) bits.push("خطأ: " + p.error);
    var subTxt = p.summary ? String(p.summary) : "";
    if (subTxt.length > 180) subTxt = subTxt.slice(0, 180) + "…";
    var sub = card._sub;
    sub.textContent = "";
    if (subTxt) sub.appendChild(el("div", "evt-sub-line", subTxt));
    if (bits.length) {
      var meta = el("div", "evt-meta");
      bits.forEach(function (b) { tech(meta, b); });
      sub.appendChild(meta);
    }
    stamp(card.querySelector(".evt-time"), e.created_at);
    return created ? card : null;
  }
  function drawModel(kind, p, e) {
    var rid = p.request_id || ("session-" + p.session_id);
    var created = !S.modelCards[rid];
    var card;
    if (created) {
      card = evtShell("evt-model", "i-info");
      card.setAttribute("data-modelkey", rid);
      var title = el("span", "evt-title");
      title.appendChild(el("span", "evt-kind", "استدعاء نموذج"));
      if (p.purpose) tech(title, p.purpose);
      card._row.appendChild(title);
      card._spin = el("span", "evt-spin");
      card._row.appendChild(card._spin);
      card._sub = el("div", "evt-sub");
      card.appendChild(card._sub);
      S.modelCards[rid] = card;
    } else {
      card = S.modelCards[rid];
    }
    if (p.provider || p.model) {
      var oc = card._row.querySelector(".chip");
      if (oc) oc.remove();
      var chip = el("span", "chip");
      tech(chip, (p.provider || "") + (p.model ? " · " + p.model : ""));
      card._row.appendChild(chip);
    }
    if (kind === "MODEL_REASONING" || kind === "MODEL_CALL_PROGRESS") {
      if (p.chars) {
        S.rateBuf.push([Date.now(), Number(p.chars)]);
        var cut = Date.now() - 30000;
        while (S.rateBuf.length > 2 && S.rateBuf[0][0] < cut) S.rateBuf.shift();
      }
      card._chars = (card._chars || 0) + (Number(p.chars) || 0);
      card._sub.textContent = "";
      var prog = el("div", "evt-sub-line");
      prog.appendChild(el("span", "", kind === "MODEL_REASONING" ? "تفكير جارٍ — " : "إنتاج جارٍ — "));
      tech(prog, card._chars + " حرف");
      card._sub.appendChild(prog);
    }
    if (kind === "MODEL_CALL_COMPLETED") {
      card.classList.add("evt-ok");
      if (card._spin) { card._spin.remove(); card._spin = null; }
      card._sub.textContent = "";
      var done = el("div", "evt-meta");
      if (p.duration_ms) tech(done, "زمن " + fmtDur(p.duration_ms));
      if (p.retry_count) tech(done, "محاولات " + p.retry_count);
      if (p.error_class) tech(done, "خطأ " + p.error_class);
      card._sub.appendChild(done);
    }
    stamp(card.querySelector(".evt-time"), e.created_at);
    return created ? card : null;
  }
  function drawStep(kind, p, e) {
    var ok = kind === "STEP_COMPLETED";
    var c = evtShell("evt-step" + (ok ? " evt-ok" : ""), "i-task");
    var title = el("span", "evt-title");
    title.appendChild(el("span", "evt-kind", ok ? "اكتملت خطوة" : "بدأت خطوة"));
    if (p.step_id != null) tech(title, "#" + p.step_id);
    c._row.appendChild(title);
    if (p.objective) c._row.appendChild(el("span", "evt-obj", String(p.objective)));
    var sub = el("div", "evt-sub");
    if (p.status) tech(sub, p.status);
    if (p.attempts) tech(sub, "محاولات " + p.attempts);
    if (sub.children.length) c.appendChild(sub);
    stamp(c.querySelector(".evt-time"), e.created_at);
    return c;
  }
  function drawExecution(kind, p, e) {
    var map = { EXECUTION_STARTED: ["بدأ تنفيذ", ""], EXECUTION_COMPLETED: ["اكتمل تنفيذ", "evt-ok"],
                EXECUTION_FAILED: ["فشل تنفيذ", "evt-fail"], EXECUTION_BLOCKED: ["تنفيذ محجوز", "evt-warn"] };
    var m = map[kind] || ["تنفيذ", ""];
    var c = evtShell("evt-exec " + m[1], "i-runs");
    var title = el("span", "evt-title");
    title.appendChild(el("span", "evt-kind", m[0]));
    if (p.execution_id != null) tech(title, "#" + p.execution_id);
    if (p.attempt) tech(title, "محاولة " + p.attempt);
    c._row.appendChild(title);
    var sub = el("div", "evt-sub");
    if (p.error) sub.appendChild(el("div", "evt-sub-line danger-text", String(p.error)));
    else if (p.status) tech(sub, p.status);
    if (sub.children.length) c.appendChild(sub);
    stamp(c.querySelector(".evt-time"), e.created_at);
    return c;
  }
  function drawRole(p, e) {
    var role = roleMeta(p.role);
    var c = evtShell("evt-role", "i-chat");
    c._row.appendChild(el("span", "role-chip " + role.cls, role.label));
    if (p.objective) {
      var txt = String(p.objective);
      if (txt.length > 160) txt = txt.slice(0, 160) + "…";
      c._row.appendChild(el("span", "evt-obj", txt));
    }
    stamp(c.querySelector(".evt-time"), e.created_at);
    return c;
  }
  function drawEvidence(p, e) {
    var c = evtShell("evt-evidence", "i-file");
    var title = el("span", "evt-title");
    title.appendChild(el("span", "evt-kind", "أدلة جديدة"));
    if (p.evidence_id != null) tech(title, "#" + p.evidence_id);
    c._row.appendChild(title);
    var files = p.files || [];
    if (files.length) {
      var sub = el("div", "evt-files");
      files.slice(0, 6).forEach(function (f) {
        var fEl = el("span", "evt-file");
        tech(fEl, String(f));
        sub.appendChild(fEl);
      });
      if (files.length > 6) sub.appendChild(el("span", "evt-file more", "+" + (files.length - 6) + " ملفات"));
      c.appendChild(sub);
    }
    stamp(c.querySelector(".evt-time"), e.created_at);
    return c;
  }
  function drawVerdict(kind, p, e) {
    var verdict = p.verdict || p.final_state || "";
    var ok = /PASS|EVIDENCED|approve/i.test(verdict);
    var warn = /PENDING|BLOCK/i.test(verdict);
    var c = evtShell("evt-verdict " + (ok ? "evt-ok" : (warn ? "evt-warn" : "evt-fail")),
                     ok ? "i-check" : "i-alert");
    var title = el("span", "evt-title");
    title.appendChild(el("span", "evt-kind", KIND_TITLES[kind] || kind));
    if (verdict) title.appendChild(el("span", "evt-verdict-text", String(verdict)));
    if (p.step_id != null) tech(title, "#خطوة " + p.step_id);
    c._row.appendChild(title);
    stamp(c.querySelector(".evt-time"), e.created_at);
    return c;
  }
  function drawGeneric(kind, p, e) {
    var c = evtShell("evt-generic", "i-info");
    var title = el("span", "evt-title");
    title.appendChild(el("span", "evt-kind", KIND_TITLES[kind] || kind));
    c._row.appendChild(title);
    var keys = Object.keys(p || {}).slice(0, 4);
    if (keys.length) {
      var sub = el("div", "evt-sub");
      keys.forEach(function (k) {
        var v = typeof p[k] === "object" ? JSON.stringify(p[k]).slice(0, 60) : String(p[k]).slice(0, 80);
        var line = el("div", "evt-kv");
        line.appendChild(el("span", "evt-kv-label", k));
        tech(line, v);
        sub.appendChild(line);
      });
      c.appendChild(sub);
    }
    stamp(c.querySelector(".evt-time"), e.created_at);
    return c;
  }
  function drawGateEvent(p, e) {
    var c = evtShell("evt-gate", "i-alert");
    var title = el("span", "evt-title");
    title.appendChild(el("span", "evt-kind", "بانتظار اعتمادك"));
    if (p.phases) tech(title, p.phases + " مرحلة");
    c._row.appendChild(title);
    var sub = el("div", "evt-sub");
    sub.appendChild(el("div", "evt-sub-line", "خطة بانتظار قرار المالك — زر الاعتماد أعلى النافذة."));
    c.appendChild(sub);
    showGate();
    stamp(c.querySelector(".evt-time"), e.created_at);
    return c;
  }

  /* ---------- بوابة المالك (قرار حقيقي) ---------- */
  function showGate() {
    var g = $("#floor-gate");
    if (!g || S.gateBusy) return;
    g.hidden = false;
    g.textContent = "";
    var ic = el("span", "icon");
    ic.innerHTML = '<svg><use href="#i-alert"/></svg>';
    g.appendChild(ic);
    var txt = el("div", "fc-gate-text");
    txt.appendChild(el("div", "fc-gate-title", "خطة بانتظار اعتمادك"));
    txt.appendChild(el("div", "fc-gate-sub", "لا يبدأ التنفيذ إلا بقرارك — الاعتماد هنا قرار فعلي يُسجَّل في المصنع."));
    g.appendChild(txt);
    var btn = el("button", "btn-primary fc-gate-btn", "اعتماد الخطة");
    btn.addEventListener("click", function () {
      if (S.gateBusy) return;
      S.gateBusy = true;
      btn.disabled = true;
      btn.textContent = "جارٍ إرسال الاعتماد…";
      apiPost("/projects/" + S.sel + "/plan/approve", {}).then(function () {
        btn.textContent = "أُرسل الاعتماد ✓";
        btn.classList.add("done");
        setTimeout(function () { hideGate(); S.gateBusy = false; }, 2500);
        loadRuns();
      }).catch(function (err) {
        S.gateBusy = false;
        btn.disabled = false;
        btn.textContent = "فشل: " + (err.message || "أعد المحاولة");
        btn.classList.add("err");
        setTimeout(function () { btn.textContent = "اعتماد الخطة"; btn.classList.remove("err"); }, 4000);
      });
    });
    g.appendChild(btn);
  }
  function hideGate() {
    var g = $("#floor-gate");
    if (g) g.hidden = true;
  }
  function refreshGateFromRuns() {
    var r = findRun(S.sel);
    var need = !!(r && r.waiting_for && r.waiting_for.kind === "owner_gate");
    var g = $("#floor-gate");
    if (!g) return;
    if (need && g.hidden) showGate();
    if (!need && !g.hidden) hideGate();
  }

  /* ---------- الإيقاف (نقرتان — أثر صادق) ---------- */
  function armStop() {
    var b = $(".fc-stop");
    if (!b || b._armed) return;
    b._armed = true;
    b.classList.add("armed");
    b.querySelector(".fc-stop-label").textContent = "تأكيد الإيقاف؟";
    b._timer = setTimeout(function () { disarmStop(); }, 3500);
    if (!b._bound) {
      b._bound = true;
      b.addEventListener("click", function () {
        if (!b._armed) return;
        disarmStop();
        b.disabled = true;
        var l = b.querySelector(".fc-stop-label");
        l.textContent = "جارٍ الإرسال…";
        apiPost("/projects/" + S.sel + "/stop", {}).then(function () {
          l.textContent = "أُرسل الإيقاف ✓";
          loadRuns();
          setTimeout(function () { b.disabled = false; disarmStop(); }, 2500);
        }).catch(function (err) {
          b.disabled = false;
          l.textContent = "فشل الإيقاف: " + (err.message || "");
          setTimeout(function () { disarmStop(); }, 3000);
        });
      });
    }
  }
  function disarmStop() {
    var b = $(".fc-stop");
    if (!b) return;
    b._armed = false;
    b.classList.remove("armed");
    if (b._timer) { clearTimeout(b._timer); b._timer = null; }
    var l = b.querySelector(".fc-stop-label");
    if (l) l.textContent = "إيقاف";
  }

  /* ================= اللوح ================= */
  function setPanelTab(tab) {
    S.panel.tab = tab;
    document.querySelectorAll(".fp-tab").forEach(function (t) {
      t.classList.toggle("on", t.dataset.tab === tab);
    });
    renderPanel(true);
  }
  function renderPanel(force) {
    var body = $("#floor-panel-body");
    if (!body) return;
    var d = S.detail || {};
    var sig = [S.panel.tab,
      (d.artifacts || []).length,
      (d.artifacts || []).length ? String(d.artifacts[0].sha256 || "").slice(0, 10) : "",
      (d.executions || []).length,
      (d.executions || []).length ? String(d.executions[0].started_at || "") : "",
      (d.phases || []).length].join("|");
    if (!force && sig === panelSig) return;
    panelSig = sig;
    body.textContent = "";
    if (S.panel.tab === "files") renderFiles(body, d.artifacts || []);
    else if (S.panel.tab === "outputs") renderOutputs(body, d.artifacts || []);
    else if (S.panel.tab === "plan") renderPlan(body, d.phases || []);
    else renderExecs(body, d.executions || []);
  }
  var panelSig = "";
  function fileMeta(a) {
    var wrap = el("div", "fp-file");
    var top = el("div", "fp-file-top");
    var ic = el("span", "icon sm");
    ic.innerHTML = '<svg><use href="#i-file"/></svg>';
    top.appendChild(ic);
    var nm = el("span", "fp-file-name", a.name || "ملف");
    nm.title = nm.textContent;
    top.appendChild(nm);
    if (a.verdict) {
      var ok = a.verdict === "PASS";
      top.appendChild(el("span", "chip " + (ok ? "ok" : "danger"), a.verdict));
    }
    wrap.appendChild(top);
    var meta = el("div", "fp-file-meta");
    tech(meta, fmtBytes(a.bytes));
    if (a.sha256) tech(meta, String(a.sha256).slice(0, 10), a.sha256);
    var t = el("span", "fp-file-time");
    stamp(t, a.created_at);
    meta.appendChild(t);
    wrap.appendChild(meta);
    var detail = el("div", "fp-file-detail");
    detail.hidden = true;
    var dl = el("div", "fp-file-dl");
    dl.appendChild(kvRow("الاسم", tech(el("span"), a.name || "")));
    dl.appendChild(kvRow("SHA-256", tech(el("span"), a.sha256 || "—")));
    dl.appendChild(kvRow("الحجم", tech(el("span"), a.bytes != null ? a.bytes + " بايت" : "—")));
    dl.appendChild(kvRow("الحكم", tech(el("span"), a.verdict || "—")));
    dl.appendChild(kvRow("الخطوة", tech(el("span"), a.step_id != null ? "#" + a.step_id : "—")));
    dl.appendChild(kvRow("الدليل", tech(el("span"), a.evidence_id != null ? "#" + a.evidence_id : "—")));
    dl.appendChild(kvRow("أُنشئ", tech(el("span"), a.created_at || "—")));
    detail.appendChild(dl);
    var note = el("div", "fp-file-note");
    note.textContent = "بيانات الأدلة الدائمة — عرض المحتوى الكامل يُضاف بنقرة نشر معتمدة لاحقًا.";
    detail.appendChild(note);
    wrap.appendChild(detail);
    wrap.addEventListener("click", function (e) {
      if (e.target.closest(".fp-file-detail")) return; /* النسخ من التفاصيل لا يطوي */
      detail.hidden = !detail.hidden;
      wrap.classList.toggle("open", !detail.hidden);
    });
    return wrap;
  }
  /* سقف عرض صادق: قائمة مقتطعة معلنة مع «عرض المزيد» — كل صف بيانات حقيقية */
  var FILE_PAGE = 300;
  var fileShown = 0;
  function renderFiles(body, artifacts) {
    fileShown = Math.min(FILE_PAGE, artifacts.length);
    renderFilesChunk(body, artifacts);
  }
  function renderFilesChunk(body, artifacts) {
    var head = el("div", "fp-head-count");
    head.appendChild(el("span", "", "ملفات الأدلة الدائمة — "));
    tech(head, String(artifacts.length) + " ملف");
    var total = 0;
    artifacts.forEach(function (a) { total += a.bytes || 0; });
    tech(head, fmtBytes(total));
    if (artifacts.length > fileShown) {
      head.appendChild(el("span", "fp-trunc-note",
        "(عرض أول " + fileShown + " بالأحدث)"));
    }
    body.appendChild(head);
    if (!artifacts.length) {
      body.appendChild(emptyPanel("لا ملفات بعد", "تظهر ملفات الأدلة هنا فور إنتاجها مع hash وحكم الفحص."));
      return;
    }
    var list = artifacts.slice(0, fileShown);
    var groups = {};
    list.forEach(function (a) {
      var name = String(a.name || "ملف");
      var idx = name.lastIndexOf("/");
      var g = idx >= 0 ? name.slice(0, idx) : "";
      var f = idx >= 0 ? name.slice(idx + 1) : name;
      (groups[g] = groups[g] || []).push(Object.assign({}, a, { name: f }));
    });
    Object.keys(groups).sort().forEach(function (g) {
      var sec = el("div", "fp-group");
      var gh = el("div", "fp-group-head");
      gh.appendChild(el("span", "fp-group-name", g || "الجذر"));
      tech(gh, String(groups[g].length));
      sec.appendChild(gh);
      groups[g].sort(function (a, b) { return String(a.name).localeCompare(String(b.name)); })
        .forEach(function (a) { sec.appendChild(fileMeta(a)); });
      body.appendChild(sec);
    });
    if (artifacts.length > fileShown) {
      var more = el("button", "btn-ghost sm fp-more",
        "عرض المزيد (" + (artifacts.length - fileShown) + " ملف متبقٍ)");
      more.addEventListener("click", function () {
        fileShown = Math.min(fileShown + FILE_PAGE, artifacts.length);
        var body2 = $("#floor-panel-body");
        if (!body2) return;
        body2.textContent = "";
        renderFilesChunk(body2, artifacts);
      });
      body.appendChild(more);
    }
  }
  function renderOutputs(body, artifacts) {
    var list = artifacts.slice().sort(function (a, b) {
      return new Date(b.created_at || 0) - new Date(a.created_at || 0);
    }).filter(function (a) { return !/^(stdout-|stderr-)/.test(String(a.name)); });
    var head = el("div", "fp-head-count");
    head.appendChild(el("span", "", "المخرجات بالأحدث — "));
    tech(head, String(list.length));
    if (list.length > FILE_PAGE) {
      head.appendChild(el("span", "fp-trunc-note", "(عرض أول " + FILE_PAGE + ")"));
    }
    body.appendChild(head);
    if (!list.length) {
      body.appendChild(emptyPanel("لا مخرجات بعد", "كل مخرج يُدفع هنا مع حكم فحصه وبصمة الأدلة."));
      return;
    }
    list.slice(0, FILE_PAGE).forEach(function (a) { body.appendChild(fileMeta(a)); });
  }
  function renderPlan(body, phases) {
    var head = el("div", "fp-head-count");
    head.appendChild(el("span", "", "المراحل المعلنة — "));
    tech(head, String(phases.length));
    body.appendChild(head);
    if (!phases.length) {
      body.appendChild(emptyPanel("لا مراحل بعد", "الخطة تظهر هنا فور اعتمادها بمراحلها ومعاييرها."));
      return;
    }
    var done = 0;
    phases.forEach(function (ph) { if (ph.status === "COMPLETED") done++; });
    var bar = el("div", "fp-plan-bar");
    var fill = el("div", "fp-plan-bar-fill");
    fill.style.width = (phases.length ? Math.round(done / phases.length * 100) : 0) + "%";
    bar.appendChild(fill);
    body.appendChild(bar);
    phases.forEach(function (ph) {
      var c = el("div", "fp-phase");
      var top = el("div", "fp-phase-top");
      top.appendChild(el("span", "fp-phase-title", ph.title || ("مرحلة " + ph.ordinal)));
      top.appendChild(el("span", "chip " + (ph.status === "COMPLETED" ? "ok" : ph.status === "RUNNING" ? "agent" : ""), ph.status || "—"));
      c.appendChild(top);
      if (ph.objective) c.appendChild(el("div", "fp-phase-obj", String(ph.objective)));
      body.appendChild(c);
    });
  }
  function renderExecs(body, execs) {
    var head = el("div", "fp-head-count");
    head.appendChild(el("span", "", "التنفيذات — "));
    tech(head, String(execs.length));
    body.appendChild(head);
    if (!execs.length) {
      body.appendChild(emptyPanel("لا تنفيذات بعد", "كل تنفيذ يظهر بدوره ونموذجه ومزوده ومساحة عمله."));
      return;
    }
    execs.forEach(function (x) {
      var role = roleMeta(x.agent_role);
      var c = el("div", "fp-exec" + (x.status === "RUNNING" ? " running" : ""));
      var top = el("div", "fp-exec-top");
      top.appendChild(el("span", "role-chip " + role.cls, role.label));
      tech(top, "#" + x.id);
      top.appendChild(el("span", "chip " + (x.status === "RUNNING" ? "agent" : x.status === "COMPLETED" ? "ok" : x.status === "FAILED" ? "danger" : ""), x.status || "—"));
      c.appendChild(top);
      var dl = el("div", "fp-exec-dl");
      dl.appendChild(kvRow("النموذج", tech(el("span"), x.model || "—")));
      if (x.provider) dl.appendChild(kvRow("المزود", tech(el("span"), String(x.provider).slice(0, 60))));
      dl.appendChild(kvRow("مساحة العمل", tech(el("span"), x.workspace || "—")));
      dl.appendChild(kvRow("البداية", tech(el("span"), x.started_at || "—")));
      if (x.error) dl.appendChild(kvRow("خطأ", tech(el("span"), String(x.error))));
      c.appendChild(dl);
      body.appendChild(c);
    });
  }
  function emptyPanel(title, hint) {
    var w = el("div", "empty-state");
    w.appendChild(el("div", "empty-title", title));
    w.appendChild(el("div", "empty-hint", hint));
    return w;
  }

  /* ---------- هندسة اللوح: سحب + طي + تذكر ---------- */
  function restorePanel() {
    try {
      var pw = sessionStorage.getItem("aes_floor_panel_w");
      var po = sessionStorage.getItem("aes_floor_panel_open");
      if (pw) S.panel.w = Math.max(20, Math.min(70, Number(pw)));
      if (po != null) S.panel.open = po === "1";
    } catch (err) { /* التخزين اختياري */ }
    applyPanel();
  }
  function applyPanel() {
    var panel = $("#floor-panel");
    var floor = $("#floor");
    if (!panel || !floor) return;
    panel.style.setProperty("--fp-w", S.panel.w + "%");
    panel.classList.toggle("closed", !S.panel.open);
    floor.classList.toggle("panel-closed", !S.panel.open);
    var resizer = $("#floor-resizer");
    if (resizer) resizer.classList.toggle("hidden", !S.panel.open);
    try { sessionStorage.setItem("aes_floor_panel_open", S.panel.open ? "1" : "0"); } catch (err) {}
  }
  function togglePanel() {
    S.panel.open = !S.panel.open;
    applyPanel();
    if (S.panel.open) renderPanel(true);
  }
  function bindResizer(resizer, panel) {
    var dragging = false;
    panel._resizing = false;
    resizer.addEventListener("mousedown", function (e) {
      dragging = true;
      panel._resizing = true;
      document.body.classList.add("floor-resizing");
      e.preventDefault();
    });
    document.addEventListener("mousemove", function (e) {
      if (!dragging) return;
      var floor = $("#floor");
      if (!floor) return;
      var rect = floor.getBoundingClientRect();
      /* RTL: اللوح في أقصى اليسار — العرض يقاس من الحافة اليسرى */
      var pct = Math.max(20, Math.min(70, (e.clientX - rect.left) / rect.width * 100));
      S.panel.w = pct;
      panel.style.setProperty("--fp-w", pct + "%");
      try { sessionStorage.setItem("aes_floor_panel_w", String(Math.round(pct))); } catch (err) {}
    });
    document.addEventListener("mouseup", function () {
      if (!dragging) return;
      dragging = false;
      panel._resizing = false;
      document.body.classList.remove("floor-resizing");
    });
  }
  function toggleSessions() {
    S.sessionsCollapsed = !S.sessionsCollapsed;
    var floor = $("#floor");
    if (floor) floor.classList.toggle("sessions-collapsed", S.sessionsCollapsed);
  }

  /* ================= الكثافة ================= */
  function setDensity(d) {
    S.density = d;
    applyDensity();
    try { sessionStorage.setItem("aes_floor_density", d); } catch (err) {}
  }
  function applyDensity() {
    var floor = $("#floor");
    if (!floor) return;
    floor.classList.remove("density-compact", "density-standard", "density-detailed");
    floor.classList.add("density-" + S.density);
    document.querySelectorAll(".fc-density-btn").forEach(function (b) {
      b.classList.toggle("on", b.dataset.d === S.density);
    });
  }

  /* ================= الإحصاءات الحية ================= */
  function updateStat(name, val) {
    var n = $("#floor-stat-" + name);
    if (n) n.textContent = val;
  }
  function updateStatsFromRuns() {
    var r = findRun(S.sel);
    var p = findProject(S.sel);
    var st = statusMeta(r, p);
    var pulseEl = $("#floor-stat-pulse");
    if (pulseEl) {
      if (st.pulse && r && r.heartbeat_at) {
        var d = (Date.now() - new Date(r.heartbeat_at).getTime()) / 1000;
        pulseEl.textContent = isNaN(d) ? "—" : (d < 0 ? 0 : Math.floor(d)) + " ث";
      } else {
        pulseEl.textContent = st.pulse ? "—" : "خامل";
      }
    }
    var prog = r && r.progress;
    var stepsEl = $("#floor-stat-steps");
    if (stepsEl) {
      stepsEl.textContent = prog && prog.steps_total
        ? prog.steps_completed + "/" + prog.steps_total + " (فشل " + prog.steps_failed + ")"
        : "—";
    }
    var progEl = $("#floor-stat-progress");
    if (progEl) progEl.textContent = prog && prog.steps_total ? Math.round(prog.percent || 0) + "%" : "—";
    var el2 = $("#floor-stat-elapsed");
    if (el2) {
      if (r && r.elapsed_s != null) {
        var s = Number(r.elapsed_s);
        var h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
        el2.textContent = h ? h + "س " + m + "د" : m + "د " + Math.floor(s % 60) + "ث";
      } else el2.textContent = "—";
    }
    var agentEl = $("#floor-stat-agent");
    if (agentEl) {
      var ex = latestExecution();
      agentEl.textContent = ex && ex.status === "RUNNING" ? roleMeta(ex.agent_role).label : "—";
    }
    var rateEl = $("#floor-stat-rate");
    if (rateEl) {
      var cut = Date.now() - 30000;
      var win = S.rateBuf.filter(function (x) { return x[0] >= cut; });
      if (win.length >= 2) {
        var chars = win[win.length - 1][1] - win[0][1];
        var dt = (win[win.length - 1][0] - win[0][0]) / 1000;
        rateEl.textContent = dt > 0 && chars > 0 ? "≈" + Math.max(1, Math.round(chars / dt)) + " حرف/ث" : "—";
      } else rateEl.textContent = "—";
    }
    refreshGateFromRuns();
  }
  function relTimeLoop() {
    document.querySelectorAll("#floor .evt-time, #floor .fp-file-time, #floor .fc-hb, #floor .fs-item-sub .dim")
      .forEach(function (n) {
        if (n.dataset && n.dataset.ts) n.textContent = rel(n.dataset.ts);
      });
  }

  /* ================= دورة الحياة ================= */
  function start() {
    LiveBridge();
    loadRuns();
    S.timers.push(setInterval(loadRuns, 5000));
    S.timers.push(setInterval(loadDetail, 6000));
    S.timers.push(setInterval(updateStatsFromRuns, 3000));
    S.timers.push(setInterval(relTimeLoop, 15000));
  }
  function LiveBridge() {
    if (window.LiveEvents && window.LiveEvents.onEvent) {
      window.LiveEvents.onEvent(onLive);
      syncLiveBadge();
      setInterval(syncLiveBadge, 3000);
    } else {
      var label = $("#floor-sessions .fs-live-label");
      if (label) label.textContent = "استطلاع فقط";
    }
  }
  function syncLiveBadge() {
    var label = $("#floor-sessions .fs-live-label");
    var chip = $("#floor-sessions .fs-live");
    if (!label || !chip) return;
    var ok = window.LiveEvents && window.LiveEvents.isConnected && window.LiveEvents.isConnected();
    label.textContent = ok ? "بث حي" : "استطلاع فقط";
    chip.classList.toggle("ok", !!ok);
  }

  function openFloor() {
    build();
    var floor = $("#floor");
    var reopen = $("#floor-reopen");
    if (!floor) return;
    floor.hidden = false;
    if (reopen) reopen.hidden = true;
    if (!S.started) {
      S.started = true;
      start();
    }
  }
  function closeFloor() {
    var floor = $("#floor");
    var reopen = $("#floor-reopen");
    if (floor) floor.hidden = true;
    if (reopen) reopen.hidden = false;
  }
  function openJsonModal(title, data) {
    var backdrop = $("#modal-backdrop");
    var json = $("#modal-json");
    var mt = $("#modal-title");
    if (!backdrop || !json) return;
    if (mt) mt.textContent = title || "تفاصيل الحدث";
    json.textContent = typeof data === "string" ? data : JSON.stringify(data, null, 2);
    backdrop.hidden = false;
  }

  /* إقلاع افتراضي: أرضية المصنع هي الصفحة الرئيسية —
     العودة للكلاسيكية عبر «الواجهة الكلاسيكية» أو Esc، والعودة من الزر العائم. */
  function boot() {
    var closed = null;
    try { closed = sessionStorage.getItem("aes_floor_closed"); } catch (err) {}
    if (closed === "1") {
      closeFloor();
      S.started = true;
      start(); /* حي في الخلفية: الجلسات تبقى محدثة لزر العودة */
    } else {
      openFloor();
    }
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();

  window.Floor = {
    open: openFloor,
    close: closeFloor,
    select: select,
    reload: function () { loadRuns(); loadDetail(); loadHistory(); },
    state: S,
  };
})();
