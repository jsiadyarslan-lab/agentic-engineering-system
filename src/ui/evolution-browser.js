/* متصفح التطور اللحظي (016-F «قمرة الوكيل») — قابل للدمج بلا iframe.
   window.EvoBrowser.mount(root, {projectId, embedded, height, onChangeProject})
   العقد: كل حيّ من بث الأحداث (SSE + Last-Event-ID)، وكل رقم من اللقطة حصرًا.
   القمرة تعرض: قرارات الأدوار بنصها الكامل (ماذا يفكر)، رقاقات أدوات بعقد
   started→succeeded/failed (ماذا يفعل)، ورقاقات مخرجات الأدلة (ماذا يُنتج). */
"use strict";
window.EvoBrowser = (function () {
  const ROLE_AR = {
    thinker: "المفكّر", implementer: "المنفّذ", reviewer: "المحكّم",
    arbiter: "الحَكَم", verifier: "المحقّق", critic: "الناقد",
  };
  const ROLE_CLASS = {
    thinker: "thinker", implementer: "implementer", reviewer: "reviewer",
    arbiter: "arbiter", verifier: "verifier", critic: "verifier",
  };
  function roleHead(role) {
    switch (role) {
      case "arbiter": return "قرار الحَكَم";
      case "verifier": return "حكم المحقّق";
      case "thinker": return "توجيه المفكّر";
      case "implementer": return "عمل المنفّذ";
      case "reviewer": return "مراجعة المحكّم";
      default: return (ROLE_AR[role] || role || "دور") + " يعمل";
    }
  }

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

  const SKELETON =
    '<header class="evo-top">' +
      '<div class="evo-brand"><span class="evo-live-dot" id="evo-conn-dot"></span>' +
      '<strong>متصفح التطور</strong><span class="evo-conn-label" id="evo-conn-label">جارٍ الاتصال…</span></div>' +
      '<select id="evo-project" class="evo-picker" title="اختيار المشروع"></select>' +
      '<div class="evo-heartbeat" id="evo-heartbeat">—</div>' +
    '</header>' +
    '<main class="evo-grid">' +
      '<aside class="evo-rail evo-rail-plan">' +
        '<h2>الخطة الحية</h2>' +
        '<div class="evo-progress"><div class="evo-progress-bar" id="evo-progress-bar"></div></div>' +
        '<div class="evo-progress-nums tnum" id="evo-progress-nums">—</div>' +
        '<ol id="evo-steps" class="evo-steps"></ol>' +
      '</aside>' +
      '<section class="evo-center">' +
        '<div class="evo-now" id="evo-now">' +
          '<div class="evo-now-empty" id="evo-now-empty">لا تنفيذ جاري الآن</div>' +
          '<div class="evo-now-body" id="evo-now-body" hidden>' +
            '<span class="evo-now-pulse"></span>' +
            '<span class="evo-now-role" id="evo-now-role">—</span>' +
            '<span class="evo-now-tool" id="evo-now-tool"></span>' +
            '<span class="evo-now-step" id="evo-now-step"></span>' +
            '<span class="evo-now-since tnum" id="evo-now-since"></span>' +
          '</div>' +
        '</div>' +
        '<div class="evo-mind tnum" id="evo-mind" hidden></div>' +
        '<div class="evo-brief" id="evo-brief"></div>' +
        '<div class="evo-stream" id="evo-stream"></div>' +
      '</section>' +
      '<aside class="evo-rail evo-rail-files">' +
        '<h2>ملفات المشروع <span class="evo-count tnum" id="evo-files-count"></span></h2>' +
        '<ul id="evo-files" class="evo-files"></ul>' +
      '</aside>' +
    '</main>' +
    '<footer class="evo-stats tnum" id="evo-stats"></footer>' +
    '<div class="evo-modal" id="evo-modal" hidden>' +
      '<div class="evo-modal-box">' +
        '<header><strong id="evo-modal-title"></strong><button id="evo-modal-close" class="evo-btn">إغلاق</button></header>' +
        '<pre id="evo-modal-pre" dir="ltr"></pre>' +
      '</div>' +
    '</div>';

  let cssDone = false;
  function injectCss() {
    if (cssDone) return;
    if (!document.getElementById("evo-browser-css")) {
      const l = document.createElement("link");
      l.id = "evo-browser-css";
      l.rel = "stylesheet";
      l.href = "/static/evolution-browser.css?v=2";
      document.head.appendChild(l);
    }
    cssDone = true;
  }

  function mount(root, opts) {
    opts = opts || {};
    injectCss();
    if (root._evoInstance) { try { root._evoInstance.destroy(); } catch (e) {} root._evoInstance = null; }
    root.classList.add("evo-app");
    root.classList.toggle("evo-standalone", !opts.embedded);
    root.innerHTML = SKELETON;
    if (opts.embedded) {
      root.style.height = opts.height || "calc(100vh - 200px)";
      root.style.border = "1px solid #2A3340";
      root.style.borderRadius = "12px";
      root.style.overflow = "hidden";
    }
    const inst = createInstance(root, opts);
    root._evoInstance = inst;
    inst.boot();
    return inst;
  }
  function unmount(root) {
    if (root && root._evoInstance) {
      try { root._evoInstance.destroy(); } catch (e) {}
      root._evoInstance = null;
    }
  }

  function createInstance(root, opts) {
    const $ = (id) => root.querySelector("#" + id);
    const state = {
      pid: opts.projectId != null ? Number(opts.projectId) : null,
      snap: null, es: null, lastId: 0, seen: 0, conn: "connecting",
      since: null, tool: "", throttle: {}, refetchTimer: null,
      toolChips: new Map(), tick: null,
    };
    const mind = { req: null, reasoning: 0, content: 0, purpose: "", done: 0 };

    /* ---------- السرد: من الحدث إلى بطاقة غنية ---------- */
    function narrate(e) {
      const p = e.payload || {};
      const kind = String(e.kind || "");
      const role = ROLE_AR[p.role] ? p.role : (p.role || "");
      switch (kind) {
        case "STEP_STARTED":
          return { cls: "", text: "بدأت خطوة: " + (p.objective || ("#" + (p.step_id ?? "?"))) };
        case "STEP_COMPLETED":
          return { cls: "k-ok", text: "اكتملت خطوة #" + (p.step_id ?? "?") };
        case "EXECUTION_STARTED":
          return { cls: "", text: "انطلق تنفيذ #" + (p.execution_id ?? "?") + " للخطوة " + (p.step_id ?? "?") + (p.attempt > 1 ? " (محاولة " + p.attempt + ")" : "") };
        case "EXECUTION_COMPLETED":
          return { cls: "k-ok", text: "اكتمل التنفيذ #" + (p.execution_id ?? "?") };
        case "EXECUTION_FAILED":
          return { cls: "k-fail", text: "فشل التنفيذ #" + (p.execution_id ?? "?") + (p.error ? " — " + p.error : "") };
        case "EXECUTION_OPENED":
          return { cls: "", text: "فُتح التنفيذ #" + (p.execution_id ?? "?") };
        case "ROLE_EXECUTING": {
          const obj = String(p.objective || "").trim();
          return { role, cls: obj ? "k-decision" : "", decision: obj,
            text: obj ? "" : roleHead(p.role) + " — خطوة " + (p.step_id ?? "?") };
        }
        case "TOOL_EXECUTION": {
          const ph = String(p.phase || "");
          const su = String(p.summary || "");
          let target = "", mono = false;
          if (/(write|read|edit|patch)_file|apply_patch|run_cmd|shell/.test(p.tool || "")) {
            const m = /'path':\s*'([^']+)'/.exec(su) || /'command':\s*'([^']+)'/.exec(su);
            if (m) { target = m[1].length > 70 ? m[1].slice(0, 70) + "…" : m[1]; mono = true; }
            else if (su && !su.startsWith("{'")) { target = su; mono = true; }
          } else if (su && !su.startsWith("{'")) { target = su; mono = true; }
          const running = ph === "started" || ph === "preparing" || ph === "dispatched";
          return { role, cls: "k-tool", tool: p.tool, phase: ph, mono, running,
            err: p.error || "",
            text: (running ? "ينفّذ أداة " : ph === "failed" ? "أفشلت أداة " : "أداة ") +
                  (p.tool || "?") + (target ? " ← " + target : ""),
            extra: p.duration_ms ? (p.duration_ms + "ms") : (running ? "قيد التنفيذ" : ""),
            chipKey: (p.execution_id ?? "?") + "|" + (p.tool ?? "?") + "|" + (p.step_id ?? "?") };
        }
        case "MODEL_CALL_STARTED":
          return { role, throttle: "llm", text: "استدعاء نموذج — " + (p.purpose || "توليد") };
        case "MODEL_CALL_PROGRESS":
          return { role, throttle: "llm", text: "تدفق توليد من النموذج…" };
        case "MODEL_CALL_COMPLETED":
          return { role, throttle: "llm", text: "اكتمل استدعاء النموذج" + (p.duration_ms != null ? " في " + p.duration_ms + "ms" : "") };
        case "MODEL_REASONING":
          return { role, throttle: "llm", text: "النموذج يستدل…" };
        case "REVIEW_COMPLETED": {
          const v = String(p.verdict || "—").toUpperCase();
          const bad = v.includes("REJECT") || v.includes("FAIL");
          return { role: "reviewer", cls: bad ? "k-fail" : "k-ok", verdict: v,
            text: "اكتملت مراجعة الخطوة " + (p.step_id ?? "?") + (p.score != null ? " — نتيجة " + p.score : "") };
        }
        case "TEST_COMPLETED":
          return { cls: p.passed === false || String(p.status || "").toUpperCase() === "FAILED" ? "k-fail" : "k-ok",
            text: "اختبار اكتمل: " + (p.verdict || p.status || "—") };
        case "CHECKPOINT_CREATED":
          return { cls: "", text: "حفظ نقطة تفتيش #" + (p.checkpoint_id ?? p.id ?? "?") };
        case "EVIDENCE_CREATED": {
          const fl = p.files;
          const names = Array.isArray(fl) ? fl.map(String)
            : (fl && typeof fl === "object") ? Object.keys(fl) : [];
          return { cls: "k-ok", kindLabel: "أدلة جديدة", text: "سُجّل دليل للخطوة " + (p.step_id ?? "?") + " — " + names.length + " ملف",
            files: names, stepId: p.step_id };
        }
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
        case "JOB_RECOVERY_ASSESSED": case "RECOVERY_ASSESSED":
          return { cls: "k-warn", text: "تقييم استرداد: " + (p.decision || p.assessment || "—") };
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
    function toggleRaw(card) {
      let pre = card.querySelector(":scope > .evo-raw");
      if (!pre) {
        pre = el("pre", "evo-raw");
        pre.dir = "ltr";
        try { pre.textContent = JSON.stringify(card._evoPayload ?? {}, null, 1); }
        catch (e) { pre.textContent = String(card._evoPayload); }
        card.appendChild(pre);
      } else pre.remove();
    }
    function streamCard(e, n) {
      const card = el("div", "evo-card " + (n.cls || ""));
      const rc = ROLE_CLASS[n.role];
      if (n.role && rc) card.dataset.role = rc;
      card._evoPayload = e.payload || {};
      const head = el("div", "evo-head");
      head.appendChild(el("span", "evo-kind",
        n.kindLabel || (n.role ? roleHead(n.role) : (e.kind || "").replace(/_/g, " "))));
      if (n.verdict) head.appendChild(el("span", "evo-verdict " + (n.cls === "k-fail" ? "bad" : "good"), n.verdict));
      if (n.phase) head.appendChild(el("span", "evo-phase-badge " + n.phase + (n.running ? " running" : ""), n.phase));
      if (n.extra) head.appendChild(el("span", "evo-dur", n.extra));
      head.appendChild(el("span", "evo-ago")).dataset.ts = e.created_at || "";
      card.appendChild(head);
      if (n.decision) {
        const t = el("div", "evo-decision-text", n.decision);
        t.title = "انقر لتوسيع/طي النص";
        t.addEventListener("click", (ev) => { ev.stopPropagation(); t.classList.toggle("open"); });
        card.appendChild(t);
      } else {
        card.appendChild(el("div", "evo-detail" + (n.mono ? " mono-ltr" : ""), n.text));
      }
      if (n.files && n.files.length) {
        const wrap = el("div", "evo-filechips");
        n.files.forEach((fn, i) => {
          const c = el("button", "evo-chip mono" + (i >= 6 ? " extra" : ""), fn);
          c.dir = "ltr"; c.type = "button";
          c.title = "معاينة " + fn;
          c.addEventListener("click", (ev) => { ev.stopPropagation(); openPreview({ name: fn, step_id: n.stepId }); });
          wrap.appendChild(c);
        });
        if (n.files.length > 6) {
          const more = el("button", "evo-chip more", "+" + (n.files.length - 6));
          more.type = "button";
          more.addEventListener("click", (ev) => { ev.stopPropagation(); wrap.classList.add("all"); more.remove(); });
          wrap.appendChild(more);
        }
        card.appendChild(wrap);
      }
      if (n.err) card.appendChild(el("div", "evo-err", n.err));
      card.classList.add("has-raw");
      card.title = "انقر لعرض/إخفاء الحمولة الخام";
      card.addEventListener("click", () => toggleRaw(card));
      card.dataset.ts = e.created_at || "";
      return card;
    }
    function prependCard(card) {
      const box = $("evo-stream");
      box.prepend(card);
      while (box.children.length > 140) box.removeChild(box.lastChild);
      if (state.toolChips.size) {
        for (const [k, v] of state.toolChips) if (!v.el.isConnected) state.toolChips.delete(k);
      }
    }
    function updateToolChip(card, n, e) {
      const badge = card.querySelector(".evo-phase-badge");
      if (badge) { badge.className = "evo-phase-badge " + n.phase; badge.textContent = n.phase; }
      const dur = card.querySelector(".evo-dur");
      if (dur) dur.textContent = n.extra || "";
      const det = card.querySelector(".evo-detail");
      if (det) det.textContent = n.text;
      let err = card.querySelector(":scope > .evo-err");
      if (n.err) { if (err) err.textContent = n.err; else card.appendChild(el("div", "evo-err", n.err)); }
      else if (err) err.remove();
      card.classList.toggle("k-fail", n.phase === "failed");
      card._evoPayload = e.payload || {};
    }
    function handleThrottled(e, n) {
      const key = n.throttle;
      const now = Date.now();
      const t = state.throttle[key];
      if (t && now - t.at < 2500 && t.el && t.el.isConnected) {
        t.count++;
        const det = t.el.querySelector(".evo-detail");
        if (det) det.textContent = n.text + " ×" + t.count;
        const ago = t.el.querySelector(".evo-ago");
        if (ago) ago.dataset.ts = e.created_at || "";
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
      if (!state.since) state.since = Date.now();
    }
    function setNowTool(tool) {
      state.tool = tool || "";
      $("evo-now-tool").textContent = state.tool ? "أداة: " + state.tool : "";
      $("evo-now-tool").hidden = !state.tool;
    }
    function clearNow() {
      state.since = null; state.tool = "";
      $("evo-now-body").hidden = true; $("evo-now-empty").hidden = false;
      $("evo-now-tool").hidden = true;
    }

    /* ---------- عقل الوكيل ---------- */
    function mindStart(p) {
      if (mind.req !== p.request_id) {
        mind.req = p.request_id || null;
        mind.reasoning = 0; mind.content = 0;
      }
      mind.purpose = p.purpose || mind.purpose || "";
      mind.done = 0;
      $("evo-mind").hidden = false;
      renderMind();
    }
    function bumpMind(p, which) {
      if (p.request_id !== mind.req) {
        mind.req = p.request_id || mind.req;
        mind.reasoning = 0; mind.content = 0; mind.done = 0; mind.purpose = "";
        $("evo-mind").hidden = false;
      }
      const n = Number(p.chars) || 0;
      if (which === "r") mind.reasoning += n; else mind.content += n;
      renderMind();
    }
    function setMindDone(p) {
      mind.done = Date.now();
      if (p.purpose) mind.purpose = p.purpose;
      renderMind();
    }
    function renderMind() {
      const m = $("evo-mind");
      if (!m) return;
      m.classList.toggle("live", !mind.done && (mind.reasoning || mind.content || mind.purpose));
      m.innerHTML = "";
      const put = (cls, txt) => { const sp = el("span", cls); sp.textContent = txt; m.appendChild(sp); };
      const dot = () => { const sp = el("span", "m-dim"); sp.textContent = "·"; m.appendChild(sp); };
      if (mind.reasoning) {
        const sp = el("span", "m-think");
        sp.appendChild(el("b", null, "يفكّر… "));
        sp.appendChild(document.createTextNode(mind.reasoning.toLocaleString("ar-EG") + " حرفًا"));
        m.appendChild(sp);
      }
      if (mind.content) {
        if (m.children.length) dot();
        const sp = el("span", "m-write");
        sp.appendChild(el("b", null, "يكتب… "));
        sp.appendChild(document.createTextNode(mind.content.toLocaleString("ar-EG") + " حرفًا"));
        m.appendChild(sp);
      }
      if (mind.purpose) { if (m.children.length) dot(); put("m-dim", "الغرض: " + mind.purpose); }
      if (mind.req) { if (m.children.length) dot(); put("m-dim mono", String(mind.req).replace("req-", "№")); }
      if (mind.done && Date.now() - mind.done > 30000) { if (m.children.length) dot(); put("m-dim", "انتهى الاستدعاء"); }
      const prov = (state.snap && state.snap.run && state.snap.run.provider) || "";
      if (prov) { if (m.children.length) dot(); put("m-dim", typeof prov === "string" ? prov : JSON.stringify(prov)); }
      if (!m.children.length) put("m-dim", "لا تدفق نشط الآن — بانتظار دور النموذج التالي");
    }

    /* ---------- الأمر المرسوم + خطاب المفكر + الأدوات ---------- */
    function renderBrief(s) {
      const box = $("evo-brief"); box.innerHTML = "";
      const cc = s.current_command;
      if (cc && cc.command) {
        const d = el("div", "evo-cmd");
        const h = el("h3", null, "الأمر المرسوم إلى " + (ROLE_AR[cc.role] || cc.role || "الوكيل"));
        h.appendChild(el("span", "cmd-status " + String(cc.status || ""), String(cc.status || "")));
        d.appendChild(h);
        const pre = el("pre", null, cc.command);
        pre.title = "انقر للتوسيع/الطي";
        pre.addEventListener("click", () => pre.classList.toggle("open"));
        d.appendChild(pre);
        box.appendChild(d);
      }
      const t = s.thinker;
      if (t && t.objective) {
        const d = el("div", "evo-think");
        const det = document.createElement("details");
        det.appendChild(el("summary", null,
          "خطاب المفكّر — الخطة v" + (t.version ?? "?") + (t.status ? " · " + t.status : "")));
        det.appendChild(el("div", "tk-obj", t.objective));
        const ul = el("ul");
        (t.assumptions || []).forEach((x) => ul.appendChild(el("li", null, "افتراض: " + x)));
        (t.risks || []).forEach((x) => ul.appendChild(el("li", null, "خطر: " + x)));
        (t.owner_decisions || []).forEach((x) => ul.appendChild(el("li", null, "قرار مطلوب منك: " + x)));
        if (t.revision_reason) ul.appendChild(el("li", null, "سبب آخر تعديل: " + t.revision_reason));
        det.appendChild(ul);
        d.appendChild(det);
        box.appendChild(d);
      }
      const ts = s.tools_summary || {};
      const keys = Object.keys(ts);
      if (keys.length) {
        const d = el("div", "evo-tools");
        d.appendChild(el("span", null, "الأدوات (آخر 400 حدث):"));
        keys.sort((a, b) => ts[b].n - ts[a].n).slice(0, 8).forEach((k) => {
          const sp = el("span");
          sp.appendChild(document.createTextNode(k + " "));
          sp.appendChild(el("b", "tnum", String(ts[k].ok) + "✓"));
          if (ts[k].fail) sp.appendChild(el("b", "t-fail tnum", " " + String(ts[k].fail) + "✗"));
          d.appendChild(sp);
        });
        box.appendChild(d);
      }
    }

    /* ---------- اللقطة ---------- */
    async function fetchSnapshot() {
      let u = "/api/evolution/snapshot";
      if (state.pid != null) u += "?project_id=" + encodeURIComponent(state.pid);
      const r = await fetch(u, { headers: { "Cache-Control": "no-cache" } });
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
      const pr = (s.run && s.run.progress) || {};
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
      renderBrief(s);
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
      const pr = (s.run && s.run.progress) || {};
      const box = $("evo-stats"); box.innerHTML = "";
      const item = (k, v) => { const d = el("span"); d.appendChild(el("b", "tnum", String(v))); d.appendChild(document.createTextNode(" " + k)); box.appendChild(d); };
      item("ملف مثبت بالأدلة", s.files_total);
      item("خطوة", (pr.steps_completed ?? 0) + "/" + (pr.steps_total ?? 0));
      item("إنجاز %", (Number(pr.percent ?? 0)).toFixed(1));
      item("أحداث شوهدت حيًا", state.seen);
      item("حالة", (s.run && s.run.status) || "—");
      const c = el("span", null, state.conn === "on" ? "● بث متصل" : state.conn === "retry" ? "● إعادة اتصال…" : "● اتصال…");
      box.appendChild(c);
    }

    /* ---------- معالجة الحدث ---------- */
    function handleEvent(e) {
      if (e.kind === "stream.start") return;
      if (state.pid != null && String(e.project_id) !== String(state.pid)) return;
      if (e.id) state.lastId = Math.max(state.lastId, Number(e.id));
      state.seen++;
      const p = e.payload || {};
      const n = narrate(e);
      switch (e.kind) {
        case "ROLE_EXECUTING":
          setNow(p.role, p.objective
            ? "خطوة " + (p.step_id ?? "") + " · " + (String(p.objective).length > 90 ? String(p.objective).slice(0, 90) + "…" : p.objective)
            : "خطوة " + (p.step_id ?? ""));
          break;
        case "TOOL_EXECUTION": {
          setNow(p.role, "خطوة " + (p.step_id ?? ""));
          setNowTool(p.tool);
          const ex = state.toolChips.get(n.chipKey);
          if (ex && ex.el.isConnected) updateToolChip(ex.el, n, e);
          else {
            const card = streamCard(e, n);
            state.toolChips.set(n.chipKey, { el: card });
            prependCard(card);
          }
          updateStats();
          return;
        }
        case "EXECUTION_STARTED": setNow(null, "خطوة " + (p.step_id ?? "")); break;
        case "EXECUTION_COMPLETED": case "EXECUTION_FAILED": clearNow(); break;
        case "EVIDENCE_CREATED": scheduleRefetch(1500); break;
        case "MODEL_CALL_STARTED": mindStart(p); break;
        case "MODEL_REASONING": bumpMind(p, "r"); break;
        case "MODEL_CALL_PROGRESS": bumpMind(p, "c"); break;
        case "MODEL_CALL_COMPLETED": setMindDone(p); break;
        case "STEP_COMPLETED": case "EXECUTION_COMPLETED": scheduleRefetch(1200); break;
      }
      if (e.kind === "MODEL_REASONING" || e.kind === "MODEL_CALL_PROGRESS") { updateStats(); return; }
      if (n.throttle) {
        if (handleThrottled(e, n)) { updateStats(); return; }
      }
      const card = streamCard(e, n);
      if (n.throttle) { state.throttle[n.throttle] = { at: Date.now(), el: card, count: 1 }; }
      prependCard(card);
      updateStats();
    }

    /* ---------- البث ---------- */
    function connectSSE() {
      if (state.es) state.es.close();
      const es = new EventSource("/api/projects/events/stream" + (state.lastId ? "?after_id=" + state.lastId : ""));
      state.es = es;
      es.onopen = () => { state.conn = "on"; setConn(); };
      es.onerror = () => { state.conn = "retry"; setConn(); };
      es.onmessage = (m) => {
        let e; try { e = JSON.parse(m.data); } catch (err) { return; }
        handleEvent(e);
      };
    }
    function setConn() {
      const dot = $("evo-conn-dot"), lab = $("evo-conn-label");
      if (dot) dot.className = "evo-live-dot " + (state.conn === "on" ? "on" : state.conn === "retry" ? "retry" : "");
      if (lab) lab.textContent = state.conn === "on" ? "بث لحظي متصل"
        : state.conn === "retry" ? "إعادة اتصال تلقائية…" : "جارٍ الاتصال…";
      updateStats();
    }

    /* ---------- النبض والساعة ---------- */
    state.tick = setInterval(() => {
      root.querySelectorAll("[data-ts]").forEach((nd) => {
        const v = rel(nd.dataset.ts);
        if (nd.classList.contains("evo-ago") || nd.id === "evo-heartbeat") nd.textContent = v;
      });
      if (state.since) {
        const d = Math.floor((Date.now() - state.since) / 1000);
        const ns = $("evo-now-since");
        if (ns) ns.textContent = "منذ " + (d < 60 ? d + "ث" : Math.floor(d / 60) + "د " + (d % 60) + "ث");
      }
    }, 1000);

    /* ---------- الإقلاع ---------- */
    async function boot() {
      $("evo-project").addEventListener("change", (ev) => {
        const v = ev.target.value;
        if (opts.embedded && typeof opts.onChangeProject === "function") opts.onChangeProject(Number(v));
        else location.href = "/evolution?project=" + encodeURIComponent(v);
      });
      $("evo-modal-close").addEventListener("click", () => { $("evo-modal").hidden = true; });
      $("evo-modal").addEventListener("click", (ev) => { if (ev.target.id === "evo-modal") $("evo-modal").hidden = true; });
      try {
        const s = await fetchSnapshot();
        renderSnapshot(s);
        const evs = (s.recent_events || []).slice().reverse();
        for (const e of evs) {
          if (e.id) state.lastId = Math.max(state.lastId, Number(e.id));
          state.seen++;
          handleBootEvent(e);
        }
        updateStats();
      } catch (e) {
        const box = $("evo-stream");
        if (box) box.appendChild(el("div", "evo-card k-fail", "فشل تحميل اللقطة: " + (e && e.message)));
      }
      connectSSE();
    }
    function handleBootEvent(e) {
      if (e.kind === "MODEL_REASONING" || e.kind === "MODEL_CALL_PROGRESS") return;
      const n = narrate(e);
      if (n.throttle && n.throttle === "llm" && state.throttle.llm) return;
      if (n.throttle) state.throttle[n.throttle] = { at: Date.now(), el: null, count: 1 };
      const card = streamCard(e, n);
      if (n.throttle) card.appendChild(el("i", "evo-aggr", " (مجمّع)"));
      prependCard(card);
    }

    function destroy() {
      if (state.es) { try { state.es.close(); } catch (e) {} state.es = null; }
      if (state.tick) { clearInterval(state.tick); state.tick = null; }
      clearTimeout(state.refetchTimer);
      state.toolChips.clear();
    }

    return { boot, destroy };
  }

  return { mount, unmount };
})();
