/* متصفح التطور اللحظي (016-E) — كل حيّ من بث الأحداث، وكل رقم من اللقطة.
   عقد: EventSource → /api/projects/events/stream (id + Last-Event-ID +
   keepalive من الخادم). الأرقام لا تُحسب هنا أبدًا — من /api/evolution/snapshot. */
"use strict";
(function () {
  const $ = (id) => document.getElementById(id);
  const state = {
    pid: null, snap: null, es: null, lastId: 0, seen: 0,
    conn: "connecting", since: null, tool: "", throttle: {},
    refetchTimer: null, hotTimers: [],
  };

  const ROLE_AR = { thinker: "المفكر", implementer: "المنفذ", reviewer: "المحكم" };
  const ROLE_CLASS = { thinker: "thinker", implementer: "implementer", reviewer: "reviewer" };

  function parseTs(s) {
    if (!s) return null;
    const t = Date.parse(String(s).includes("T") ? String(s) : String(s).replace(" ", "T") + "Z");
    return Number.isFinite(t) ? t : null;
  }
  function rel(s) {
    const t = parseTs(s);
    if (!t) return "—";
    const d = Math.max(0, Date.now() - t) / 1000;
    if (d < 3) return "الآن";
    if (d < 60) return "قبل " + Math.floor(d) + "ث";
    if (d < 3600) return "قبل " + Math.floor(d / 60) + " د";
    if (d < 86400) return "قبل " + Math.floor(d / 3600) + " س";
    return "قبل " + Math.floor(d / 86400) + " يوم";
  }
  function fmtBytes(n) {
    n = Number(n) || 0;
    if (n < 1024) return n + " B";
    if (n < 1048576) return (n / 1024).toFixed(1) + " KB";
    return (n / 1048576).toFixed(2) + " MB";
  }
  function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  }
  function escPath(p) { return String(p || ""); }

  /* ---------- السرد اللحظي: من الحدث إلى جملة عربية ---------- */
  function narrate(e) {
    const p = e.payload || {};
    const kind = String(e.kind || "");
    const role = ROLE_AR[p.role] || p.role || "";
    switch (kind) {
      case "STEP_STARTED": return { cls: "", text: "بدأت خطوة: " + (p.objective || ("#" + (p.step_id ?? "?"))) };
      case "STEP_COMPLETED": return { cls: "k-ok", text: "اكتملت خطوة #" + (p.step_id ?? "?") };
      case "EXECUTION_STARTED": return { cls: "", text: "انطلق تنفيذ #" + (p.execution_id ?? "?") + " للخطوة " + (p.step_id ?? "?") + (p.attempt > 1 ? " (محاولة " + p.attempt + ")" : "") };
      case "EXECUTION_COMPLETED": return { cls: "k-ok", text: "اكتمل التنفيذ #" + (p.execution_id ?? "?") };
      case "EXECUTION_FAILED": return { cls: "k-fail", text: "فشل التنفيذ #" + (p.execution_id ?? "?") + (p.error ? " — " + p.error : "") };
      case "EXECUTION_OPENED": return { cls: "", text: "فُتح التنفيذ #" + (p.execution_id ?? "?") };
      case "ROLE_EXECUTING": return { role: p.role, cls: "", text: (role ? role + " يعمل" : "دور يعمل") + " على الخطوة " + (p.step_id ?? "?") };
      case "TOOL_EXECUTION": {
        const ph = p.phase || "";
        let path = "";
        const m = /'path':\s*'([^']+)'/.exec(p.summary || "");
        if (m) path = m[1].split("/").pop();
        return { role: p.role, cls: "k-tool", tool: p.tool, phase: ph,
          text: "أداة " + (p.tool || "?") + (path ? " ← " + path : ""),
          extra: (p.duration_ms != null ? (p.duration_ms + "ms") : "") + (p.error ? " — " + p.error : "") };
      }
      case "MODEL_CALL_STARTED": return { role: p.role, throttle: "llm", text: "استدعاء نموذج بدأ" + (p.provider ? " عبر " + p.provider : "") };
      case "MODEL_CALL_PROGRESS": return { role: p.role, throttle: "llm", text: "تدفق توليد من النموذج…" };
      case "MODEL_CALL_COMPLETED": return { role: p.role, throttle: "llm", text: "اكتمل استدعاء النموذج" + (p.duration_ms != null ? " في " + p.duration_ms + "ms" : "") };
      case "MODEL_REASONING": return { role: p.role, throttle: "llm", text: "النموذج يستدل…" };
      case "REVIEW_COMPLETED": return { role: "reviewer", cls: p.verdict && String(p.verdict).toLowerCase().includes("reject") ? "k-fail" : "k-ok", text: "اكتملت المراجعة: " + (p.verdict || "—") + (p.score != null ? " (نتيجة " + p.score + ")" : "") };
      case "TEST_COMPLETED": return { cls: p.passed === false || p.status === "FAILED" ? "k-fail" : "k-ok", text: "اختبار اكتمل: " + (p.verdict || p.status || "—") };
      case "CHECKPOINT_CREATED": return { cls: "", text: "حفظ نقطة تفتيش #" + (p.checkpoint_id ?? p.id ?? "?") };
      case "EVIDENCE_CREATED": return { cls: "k-ok", text: "دليل جديد مُسجّل" + (p.files ? " (" + Object.keys(p.files).length + " ملف)" : "") };
      case "PREFLIGHT_STARTED": return { cls: "", text: "فحص مسبق بدأ" };
      case "PREFLIGHT_PASS": return { cls: "k-ok", text: "الفحص المسبق: ناجح" };
      case "PREFLIGHT_BLOCKED": return { cls: "k-fail", text: "الفحص المسبق: معيق" + (p.reason ? " — " + p.reason : "") };
      case "PREFLIGHT_RECHECKED": return { cls: "k-warn", text: "إعادة فحص مسبق" };
      case "ENVIRONMENT_READY": return { cls: "k-ok", text: "بيئة التنفيذ جاهزة" };
      case "JOB_STARTED": return { cls: "", text: "وظيفة بدأت #" + (p.job_id ?? "?") };
      case "JOB_QUEUED": return { cls: "", text: "وظيفة في الطابور" };
      case "JOB_WAITING": return { cls: "k-warn", text: "وظيفة تنتظر: " + (p.waiting_kind || "—") };
      case "JOB_RETRYING": return { cls: "k-warn", text: "إعادة محاولة وظيفة (محاولة " + (p.attempt ?? "?") + ")" };
      case "JOB_INTERRUPTED": return { cls: "k-fail", text: "وظيفة انقطعت" };
      case "JOB_RESUMED": return { cls: "k-ok", text: "وظيفة استُؤنفت" };
      case "JOB_RECOVERY_ASSESSED": case "RECOVERY_ASSESSED": return { cls: "k-warn", text: "تقييم استرداد: " + (p.decision || p.assessment || "—") };
      case "RETRY_REQUESTED": return { cls: "k-warn", text: "طلب إعادة محاولة" };
      case "OWNER_GATE_RESOLVED": return { cls: "k-ok", text: "بوابة مالك: حُلّت (" + (p.decision || "—") + ")" };
      case "GATE_AUTO_RESOLVED": return { cls: "k-ok", text: "بوابة حُلّت آليًا" };
      case "PLAN_CREATED": return { cls: "", text: "خطة جديدة: " + (p.title || "#" + (p.plan_id ?? "?")) };
      case "PLAN_REVISED": return { cls: "k-warn", text: "خطة مُعدّلة" };
      case "PLAN_APPROVED": return { cls: "k-ok", text: "اعتماد المالك: الخطة مصادَقة" };
      case "PLAN_APPROVAL_REQUIRED": return { cls: "k-warn", text: "بانتظار اعتماد المالك" };
      case "PLAN_GENERATING": return { cls: "", text: "توليد الخطة جارٍ…" };
      case "PLANNING_STARTED": return { cls: "", text: "تخطيط بدأ" };
      case "PHASE_STARTED": return { cls: "", text: "مرحلة بدأت: " + (p.title || "#" + (p.phase_id ?? "?")) };
      case "PHASE_COMPLETED": return { cls: "k-ok", text: "مرحلة اكتملت: " + (p.title || "#" + (p.phase_id ?? "?")) };
      case "STAGE_REVIEW": return { cls: "", text: "مراجعة مرحلة" };
      case "AUDIT_COMPLETED": return { cls: "k-ok", text: "تدقيق اكتمل" };
      case "CAPABILITIES_EVALUATED": return { cls: "", text: "تقييم القدرات" };
      case "WORKFLOW_DIAGNOSED": return { cls: "k-warn", text: "تشخيص سير العمل: " + (p.diagnosis || "—") };
      case "PROJECT_RESUMED": return { cls: "k-ok", text: "المشروع استُؤنف" };
      default: return { cls: "", text: kind.replace(/_/g, " ").toLowerCase() };
    }
  }

  /* ---------- البطاقات ---------- */
  function streamCard(e, n) {
    const card = el("div", "evo-card " + (n.cls || ""));
    if (n.role && ROLE_CLASS[n.role]) card.dataset.role = ROLE_CLASS[n.role];
    const head = el("div", "evo-head");
    head.appendChild(el("span", "evo-kind", n.role ? ROLE_AR[n.role] || n.role : (e.kind || "").replace(/_/g, " ")));
    if (n.phase) head.appendChild(el("span", "evo-phase-badge " + n.phase, n.phase));
    if (n.extra) head.appendChild(el("span", "evo-dur", n.extra));
    head.appendChild(el("span", "evo-ago")).dataset.ts = e.created_at || "";
    card.appendChild(head);
    card.appendChild(el("div", "evo-detail", n.text));
    card.dataset.ts = e.created_at || "";
    return card;
  }
  function prependCard(card) {
    const box = $("evo-stream");
    box.prepend(card);
    while (box.children.length > 140) box.removeChild(box.lastChild);
  }
  /* أنواع صاخبة: تُجمع في بطاقة واحدة بعدّاد بدل إغراق التدفق */
  function handleThrottled(e, n) {
    const key = n.throttle;
    const now = Date.now();
    const t = state.throttle[key];
    if (t && now - t.at < 2500 && t.el.isConnected) {
      t.count++; t.n = n; t.e = e;
      t.el.querySelector(".evo-detail").textContent = n.text + " ×" + t.count;
      t.el.querySelector(".evo-ago").dataset.ts = e.created_at || "";
      return true;
    }
    return false;
  }

  /* ---------- شريط «الآن» ---------- */
  function setNow(role, stepText) {
    const body = $("evo-now-body"), empty = $("evo-now-empty");
    body.hidden = false; empty.hidden = true;
    const r = $("evo-now-role");
    r.textContent = ROLE_AR[role] || role || "—";
    r.dataset.role = role || "";
    if (stepText) $("evo-now-step").textContent = stepText;
    if (!state.since) { state.since = Date.now(); }
  }
  function setNowTool(tool) {
    state.tool = tool || "";
    $("evo-now-tool").textContent = state.tool ? "أداة: " + state.tool : "";
    $("evo-now-tool").hidden = !state.tool;
  }
  function clearNow() { state.since = null; state.tool = "";
    $("evo-now-body").hidden = true; $("evo-now-empty").hidden = false;
    $("evo-now-tool").hidden = true; }

  /* ---------- معالجة الحدث ---------- */
  function handleEvent(e) {
    if (e.kind === "stream.start") return;
    if (state.pid != null && String(e.project_id) !== String(state.pid)) return;
    if (e.id) state.lastId = Math.max(state.lastId, Number(e.id));
    state.seen++;
    const n = narrate(e);
    const p = e.payload || {};

    switch (e.kind) {
      case "ROLE_EXECUTING": setNow(p.role, "خطوة " + (p.step_id ?? "")); break;
      case "TOOL_EXECUTION": setNow(p.role, "خطوة " + (p.step_id ?? "")); setNowTool(p.tool); break;
      case "EXECUTION_STARTED": setNow(null, "خطوة " + (p.step_id ?? "")); break;
      case "EXECUTION_COMPLETED": case "EXECUTION_FAILED": clearNow(); break;
      case "EVIDENCE_CREATED": markFilesHot(); break;
      case "STEP_COMPLETED": case "EXECUTION_COMPLETED": scheduleRefetch(1200); break;
    }
    if (n.throttle) {
      if (handleThrottled(e, n)) { updateStats(); return; }
      if (handleThrottled(e, n)) { updateStats(); return; }
    }
    const card = streamCard(e, n);
    if (n.throttle) { state.throttle[n.throttle] = { at: Date.now(), el: card, count: 1 }; }
    prependCard(card);
    updateStats();
  }

  /* ---------- اللقطة ---------- */
  async function fetchSnapshot() {
    const r = await fetch("/api/evolution/snapshot", { headers: { "Cache-Control": "no-cache" } });
    if (!r.ok) throw new Error("snapshot " + r.status);
    return r.json();
  }
  function renderSnapshot(s) {
    state.snap = s;
    state.pid = s.project.id;
    const sel = $("evo-project");
    sel.innerHTML = "";
    for (const p of s.projects) {
      const o = document.createElement("option");
      o.value = p.id;
      o.textContent = "#" + p.id + " — " + (p.name || "") + (p.status ? " · " + p.status : "");
      if (p.id === s.project.id) o.selected = true;
      sel.appendChild(o);
    }
    const pr = s.run.progress || {};
    const pct = Number(pr.percent ?? 0);
    $("evo-progress-bar").style.width = pct.toFixed(1) + "%";
    $("evo-progress-nums").textContent =
      (pr.steps_completed ?? 0) + " / " + (pr.steps_total ?? 0) + " خطوة · " + pct.toFixed(1) + "%" +
      ((pr.steps_failed ?? 0) ? " · فاشلة " + pr.steps_failed : "");

    const ol = $("evo-steps"); ol.innerHTML = "";
    const cur = pr.current_step ? pr.current_step.id : null;
    for (const st of (s.steps || []).slice(0, 60)) {
      const li = el("li");
      const stat = String(st.status || "").toUpperCase();
      if (st.id === cur || stat === "RUNNING" || stat === "IN_PROGRESS") li.classList.add("run");
      else if (stat === "DONE" || stat === "COMPLETED" || stat === "PASSED") li.classList.add("done");
      else if (stat === "FAILED" || stat === "ERROR") li.classList.add("fail");
      li.appendChild(el("span", "evo-step-status", stat === "PENDING" ? "منتظرة" : stat));
      const box = el("div", "evo-step-obj");
      box.appendChild(el("span", null, st.objective || ("#" + st.id)));
      if (st.phase) box.appendChild(el("span", "evo-step-phase", st.phase));
      if (st.last_error) box.appendChild(el("span", "evo-step-phase", st.last_error));
      li.appendChild(box);
      ol.appendChild(li);
    }

    const ul = $("evo-files"); ul.innerHTML = "";
    $("evo-files-count").textContent = s.files_total ? "(" + s.files_total + ")" : "";
    for (const f of (s.files || []).slice(0, 120)) {
      const li = el("li");
      li.dataset.name = f.name; li.dataset.step = f.step_id ?? "";
      const nm = el("bdi", "evo-fname mono", f.name); nm.dir = "ltr";
      li.appendChild(nm);
      li.appendChild(el("span", "evo-fverd " + (f.verdict || ""), (f.verdict || "—").toUpperCase()));
      if ((f.versions | 0) > 1) li.appendChild(el("span", "evo-fver", "×" + f.versions));
      li.appendChild(el("span", "evo-fsize", fmtBytes(f.bytes)));
      li.addEventListener("click", () => openPreview(f));
      ul.appendChild(li);
    }
    renderNowFromSnapshot(s);
    updateStats();
  }
  function renderNowFromSnapshot(s) {
    const r = s.run || {};
    const role = r.role && r.role.role ? r.role.role : (r.role || null);
    if (r.status && String(r.status).toUpperCase() === "RUNNING") {
      const cur = (r.progress || {}).current_step;
      setNow(typeof role === "string" ? role : (role && role.role) || null,
             cur ? "خطوة " + cur.id + ": " + (cur.objective || "") : "");
      if (r.tool && r.tool.tool) setNowTool(r.tool.tool);
      if (r.heartbeat_at) $("evo-heartbeat").dataset.ts = r.heartbeat_at;
    } else { clearNow(); }
  }
  function scheduleRefetch(ms) {
    clearTimeout(state.refetchTimer);
    state.refetchTimer = setTimeout(refetch, ms);
  }
  async function refetch() {
    try { renderSnapshot(await fetchSnapshot()); } catch (e) { /* البث يكمل */ }
  }
  function markFilesHot() { scheduleRefetch(1500); }

  /* ---------- معاينة ملف ---------- */
  async function openPreview(f) {
    $("evo-modal").hidden = false;
    $("evo-modal-title").textContent = f.name + " — خطوة " + (f.step_id ?? "?");
    $("evo-modal-pre").textContent = "جارٍ الجلب…";
    try {
      const u = "/api/projects/" + state.pid + "/artifacts/content?step_id=" +
        encodeURIComponent(f.step_id) + "&name=" + encodeURIComponent(f.name);
      const r = await fetch(u);
      if (!r.ok) { $("evo-modal-pre").textContent = "لا معاينة متاحة (HTTP " + r.status + ")"; return; }
      $("evo-modal-pre").textContent = await r.text();
    } catch (e) { $("evo-modal-pre").textContent = "فشل الجلب: " + e; }
  }

  /* ---------- الأرقام السفلية — من اللقطة حصرًا ---------- */
  function updateStats() {
    const s = state.snap; if (!s) return;
    const pr = s.run.progress || {};
    const box = $("evo-stats"); box.innerHTML = "";
    const item = (k, v) => { const d = el("span"); d.appendChild(el("b", "tnum", String(v))); d.appendChild(document.createTextNode(" " + k)); box.appendChild(d); };
    item("ملف مثبت بالأدلة", s.files_total);
    item("خطوة", (pr.steps_completed ?? 0) + "/" + (pr.steps_total ?? 0));
    item("إنجاز %", (Number(pr.percent ?? 0)).toFixed(1));
    item("أحداث شوهدت حيًا", state.seen);
    item("حالة", s.run.status || "—");
    const c = el("span", null, state.conn === "on" ? "● بث متصل" : state.conn === "retry" ? "● إعادة اتصال…" : "● اتصال…");
    box.appendChild(c);
  }

  /* ---------- البث ---------- */
  function connectSSE() {
    if (state.es) state.es.close();
    const es = new EventSource("/api/projects/events/stream" + (state.lastId ? "?after_id=" + state.lastId : ""));
    state.es = es;
    es.onopen = () => { state.conn = "on"; setConn(); };
    es.onerror = () => { state.conn = "retry"; setConn(); };
    es.onmessage = (m) => {
      let e; try { e = JSON.parse(m.data); } catch { return; }
      handleEvent(e);
    };
  }
  function setConn() {
    const dot = $("evo-conn-dot"), lab = $("evo-conn-label");
    dot.className = "evo-live-dot " + (state.conn === "on" ? "on" : state.conn === "retry" ? "retry" : "");
    lab.textContent = state.conn === "on" ? "بث لحظي متصل"
      : state.conn === "retry" ? "إعادة اتصال تلقائية…" : "جارٍ الاتصال…";
    updateStats();
  }

  /* ---------- النبض والساعة ---------- */
  setInterval(() => {
    document.querySelectorAll("[data-ts]").forEach((n) => {
      const v = rel(n.dataset.ts);
      if (n.classList.contains("evo-ago") || n.id === "evo-heartbeat") n.textContent = v;
    });
    if (state.since) {
      const d = Math.floor((Date.now() - state.since) / 1000);
      $("evo-now-since").textContent = "منذ " + (d < 60 ? d + "ث" : Math.floor(d / 60) + "د " + (d % 60) + "ث");
    }
  }, 1000);

  /* ---------- الإقلاع ---------- */
  async function boot() {
    $("evo-project").addEventListener("change", (ev) => {
      location.href = "/evolution?project=" + encodeURIComponent(ev.target.value);
    });
    $("evo-modal-close").addEventListener("click", () => { $("evo-modal").hidden = true; });
    $("evo-modal").addEventListener("click", (ev) => { if (ev.target.id === "evo-modal") $("evo-modal").hidden = true; });
    try {
      const url = new URL(location.href);
      const qp = url.searchParams.get("project");
      let s = await fetchSnapshot();
      if (qp && Number(qp) !== Number(s.project.id)) {
        s = await fetch("/api/evolution/snapshot?project_id=" + encodeURIComponent(qp)).then((r) => r.json());
      }
      renderSnapshot(s);
      const evs = (s.recent_events || []).slice().reverse();
      for (const e of evs) { if (e.id) state.lastId = Math.max(state.lastId, Number(e.id)); state.seen++; handleBootEvent(e); }
      updateStats();
    } catch (e) {
      $("evo-stream").appendChild(el("div", "evo-card k-fail", "فشل تحميل اللقطة: " + e.message));
    }
    connectSSE();
  }
  function handleBootEvent(e) {
    const n = narrate(e);
    if (n.throttle && n.throttle === "llm" && state.throttle.llm) return; /* أحدث تقدم يكفي */
    if (n.throttle) state.throttle[n.throttle] = { at: Date.now(), el: null, count: 1 };
    const card = streamCard(e, n);
    if (n.throttle) card.appendChild(el("i", "evo-aggr", " (مجمّع)"));
    prependCard(card);
  }
  boot();
})();
