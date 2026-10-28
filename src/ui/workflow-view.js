/* عرض سير العمل (013.4 §19-§23+§43+§47-§48) — سطح التحكم الحقيقي.
 *
 * المصدر الوحيد: لقطة زمن التشغيل القانونية /api/projects/{id}/runtime
 * (§8) — لا اشتقاقًا موازيًا هنا أبدًا. يعرض:
 * - خط الأنابيب GOAL→PLAN→APPROVAL→PREPARE→EXECUTE→TEST→REVIEW→AUDIT→DONE
 *   (المرحلة الحالية بارزة، المكتمل مضغوط، القادم خافت، المحجوب بسببه)
 * - تفاصيل المرحلة عند النقر (§20): العملية الجارية/الدور/الأدوات
 * - خط النشاط الحي (§21): سطور مفهومة لا JSON خام
 * - الأدوار الحية (§23): دور واحد نشط + تاريخ مضغوط — لا خمسة روبوتات
 * - التاريخ الطويل صفحات (§43): مؤشر رجوع لا غرق DOM
 * - الأدلة (§48) والمخرجات (§47) من السجل الدائم حصرًا
 */
(function () {
  "use strict";

  var Hub = window.Hub;
  var STATUS_LABELS = {
    DRAFT: "مسودة", PLANNING: "توليد الخطة",
    AWAITING_OWNER_APPROVAL: "ينتظر اعتمادك",
    READY: "جاهز", RUNNING: "يعمل الآن", PAUSED: "متوقف مؤقتًا",
    BLOCKED: "محجوب", REVISING: "مراجعة", VERIFIED: "مُتحقق",
    COMPLETED: "مكتمل", STOPPED: "متوقف", ESCALATED: "مُصعَّد",
  };
  var STAGE_ORDER = ["GOAL", "PLAN", "APPROVAL", "PREPARE", "EXECUTE",
    "TEST", "REVIEW", "AUDIT", "DONE"];

  function esc(s) { return Hub.esc(s); }
  function el(tag, cls, text) { return Hub.el(tag, cls, text); }

  /** خط الأنابيب — المرحلة الحالية بارزة والمحجوب يشرح سببه (§19). */
  function renderPipeline(container, snap) {
    var pipe = el("div", "wf-pipeline");
    var current = snap.stage || "GOAL";
    var currentIdx = STAGE_ORDER.indexOf(current);
    STAGE_ORDER.forEach(function (key, index) {
      var label = ((snap.stage_labels || {})[key]) || key;
      var item = el("div", "wf-stage");
      if (index < currentIdx) item.classList.add("done");
      else if (index === currentIdx) item.classList.add("current");
      else item.classList.add("future");
      var dot = el("span", "wf-stage-dot");
      dot.textContent = index < currentIdx ? "✓"
        : index === currentIdx ? "●" : "○";
      item.appendChild(dot);
      item.appendChild(el("span", "wf-stage-label", label));
      item.addEventListener("click", function () {
        renderStageDetails(container, snap, key);
      });
      pipe.appendChild(item);
      if (index < STAGE_ORDER.length - 1) {
        pipe.appendChild(el("span", "wf-stage-arrow",
                            index < currentIdx ? "—" : "·"));
      }
    });
    return pipe;
  }

  /** المحجوب يشرح سببه حرفيًا (§19) — من اللقطة لا تخمين. */
  function renderBlocking(container, snap) {
    if (!snap.blocking_reason) return null;
    var box = el("div", "wf-blocking");
    box.appendChild(el("div", "wf-blocking-title", "⚠ عائق يحتاج انتباهك"));
    box.appendChild(el("div", "wf-blocking-reason",
                       snap.blocking_reason));
    var waiting = snap.waiting_for || {};
    if (waiting.kind === "owner_approval" || waiting.kind === "owner_gate") {
      box.appendChild(el("div", "wf-blocking-hint",
        "القرار لك — عالج البوابة من تبويب «المحادثة»"));
    }
    return box;
  }

  /* (013.5 §J) رموز الانتظار الصادقة — نفس مفردات project-live.js.
   * «توليد الخطة جارٍ» لم تكن كافية: المالك بقي ‏17992ث أمام شاشة
   * لا تقول إن كان الاستدعاء وصل للمزود أصلًا ولا كم بقي للسقف. */
  var WAIT_PHASE_TEXT = {
    QUEUED: "في الطابور — لم يبدأ الاستدعاء بعد",
    CONNECTING: "جارٍ الاتصال بالمزود وإرسال الطلب",
    /* 013.5 §D/§J: استدلال حيّ ≠ صمت — المزود يعمل ويُقاس عدّاده. */
    REASONING: "المزود يستدل الآن — نشاط حقيقي وصل، والإجابة لم تبدأ بعد",
    AWAITING_PROVIDER: "بانتظار رد المزود — الطلب مُرسَل ولم يصل نشاط",
    PAUSED: "موقوف بقرار المالك",
    DONE: "اكتمل",
    FAILED: "فشل مصنَّف",
    INTERRUPTED: "انقطع العامل المولِّد",
    CANCELLED: "أُلغي",
  };

  function wfSeconds(value) {
    var n = Number(value);
    if (!isFinite(n) || n < 0) return "—";
    if (n < 60) return n + " ث";
    var minutes = Math.floor(n / 60);
    if (minutes < 60) return minutes + " د " + (n % 60) + " ث";
    return Math.floor(minutes / 60) + " س " + (minutes % 60) + " د";
  }

  function wfRemaining(deadline) {
    if (!deadline) return null;
    var target = new Date(deadline).getTime();
    if (isNaN(target)) return null;
    return Math.max(0, Math.round((target - Date.now()) / 1000));
  }

  /** بطاقة التخطيط الحي (§36 + §D/§J): ماذا ينتظر حرفيًا وسقفه. */
  function renderPlanningLive(snap) {
    var planning = snap.planning || {};
    if (!planning.active) return null;
    var detail = planning.detail || {};
    var waiting = planning.waiting_for || {};
    var phase = planning.wait_phase || "CONNECTING";
    var card = el("div", "wf-planning-live");
    var title = el("div", "wf-planning-title");
    title.appendChild(el("span", null, "⏳ توليد الخطة جارٍ — "));
    title.appendChild(el("span", "wf-wait-phase", phase));
    card.appendChild(title);
    card.appendChild(el("div", "wf-planning-wait",
      WAIT_PHASE_TEXT[phase] || ("حالة انتظار معلنة: " + phase)));
    var rows = el("div", "wf-planning-rows");
    function row(label, value) {
      if (value === null || value === undefined || value === "") return;
      var r = el("div", "wf-planning-row");
      r.appendChild(el("span", "wf-pl-k", label));
      var v = el("span", "wf-pl-v", String(value));
      v.dir = "auto";
      r.appendChild(v);
      rows.appendChild(r);
    }
    row("المزود", waiting.provider || detail.provider);
    row("النموذج", waiting.model || detail.model);
    row("الطلب", waiting.request_id || detail.request_id);
    row("المحاولة", waiting.attempt);
    row("مضى على الجلسة", wfSeconds(detail.elapsed_s));
    row("آخر نشاط مزود حقيقي", wfSeconds(detail.silence_s) + " مضت");
    row("آخر نبضة عملية", detail.heartbeat_at
      ? new Date(detail.heartbeat_at).toLocaleTimeString("ar") : "—");
    var left = wfRemaining(detail.hard_deadline_at);
    row("السقف الصلب المتبقي", left === null ? "غير معلن"
      : wfSeconds(left) + " (حد " + wfSeconds(detail.hard_timeout_s) + ")");
    card.appendChild(rows);
    return card;
  }

  /** الأدوار الحية (§23): دور واحد نشط + تاريخ مضغوط. */
  function renderRoles(snap) {
    var role = (snap.activity || {}).role || "";
    if (!role) return null;
    var ROLE_LABELS = {
      thinker: "المفكر", implementer: "المنفذ",
      verifier: "المتحقق", reviewer: "المراجع",
      arbiter: "المحكَّم", coordinator: "المنسق",
    };
    var order = ["thinker", "implementer", "verifier", "reviewer",
                 "arbiter"];
    var box = el("div", "wf-roles");
    var seen = {};
    if (role && order.indexOf(role) === -1) role = "coordinator";
    seen[role] = true;
    box.appendChild(el("span", "wf-role current",
      "● " + (ROLE_LABELS[role] || role) + " نشط"));
    var trail = el("span", "wf-roles-trail");
    order.forEach(function (key) {
      if (key === role) return;
      var chip = el("span", "wf-role muted",
        "✓ " + (ROLE_LABELS[key] || key));
      chip.title = "دورة الأدوار الخمسة — الدور النشط واحد فقط";
      trail.appendChild(chip);
    });
    box.appendChild(trail);
    return box;
  }

  /** تقدم حقيقي (§50): خطوات مكتملة/كلية من الأحداث — لا نسب مخترعة. */
  function renderProgress(snap) {
    var p = snap.progress || {};
    if (!p.steps_total) return null;
    var box = el("div", "wf-progress");
    var bar = el("div", "wf-progress-bar");
    var fill = el("div", "wf-progress-fill");
    fill.style.width = (p.percent || 0) + "%";
    bar.appendChild(fill);
    box.appendChild(bar);
    box.appendChild(el("span", "wf-progress-text",
      p.steps_completed + " / " + p.steps_total + " خطوة" +
      (p.steps_failed ? " · فشلت " + p.steps_failed : "")));
    return box;
  }

  /** تفاصيل مرحلة (§20) — نقرة تفتح العملية الجارية والأدوات والدور.
   * تنشئ اللوحة وتعيدها؛ النقر على مرحلة يملأها ببياناتها. */
  function renderStageDetails(container, snap, stageKey) {
    var panel = container.querySelector(".wf-details");
    if (!panel) {
      panel = el("div", "wf-details");
      panel.hidden = true;
    }
    if (stageKey == null) {
      return panel;   // الإطار فقط — يُخفى حتى تنقر مرحلة
    }
    panel.textContent = "";
    panel.hidden = false;
    var head = el("div", "wf-details-head");
    head.appendChild(el("span", "wf-details-title",
      "المرحلة: " + ((snap.stage_labels || {})[stageKey] || stageKey)));
    var close = el("button", "wf-details-close", "✕");
    close.addEventListener("click", function () { panel.hidden = true; });
    head.appendChild(close);
    panel.appendChild(head);

    var rows = el("div", "wf-details-rows");
    function row(label, value) {
      if (value === undefined || value === null || value === "") return;
      var r = el("div", "wf-details-row");
      r.appendChild(el("span", "wf-pl-k", label));
      r.appendChild(el("span", "wf-pl-v", String(value)));
      rows.appendChild(r);
    }
    var waiting = snap.waiting_for || {};
    var activity = snap.activity || {};
    row("الحالة", STATUS_LABELS[snap.status] || snap.status);
    row("ينتظر", waiting.label || "—");
    if (stageKey === "EXECUTE" && snap.progress &&
        snap.progress.current_step) {
      row("العملية الجارية", snap.progress.current_step.objective);
    }
    row("الدور النشط", activity.role || "—");
    row("الأداة الأخيرة", activity.tool || "—");
    row("المزود", activity.provider || "");
    if (snap.environment && snap.environment.state) {
      row("بيئة التنفيذ", snap.environment.state === "READY"
        ? "✓ جاهزة" : snap.environment.state);
    }
    row("العامل", snap.worker ? "✓ متصل" : "—");
    if (snap.elapsed_s != null) {
      row("مضى", Math.round(snap.elapsed_s) + " ثانية");
    }
    panel.appendChild(rows);
  }

  /** تبويب سير العمل — الأنابيب + العوائق + التخطيط الحي + الأدوار. */
  function renderWorkflowTab(body, snap) {
    body.textContent = "";
    var card = el("div", "wf-card");
    card.appendChild(renderPipeline(card, snap));
    var blocking = renderBlocking(card, snap);
    if (blocking) card.appendChild(blocking);
    var planning = renderPlanningLive(snap);
    if (planning) card.appendChild(planning);
    card.appendChild(renderStageDetails(card, snap, null));
    var roles = renderRoles(snap);
    if (roles) card.appendChild(roles);
    var progress = renderProgress(snap);
    if (progress) card.appendChild(progress);
    body.appendChild(card);
  }

  /** تبويب النظرة العامة — الهدف والخطة والبيئة بإيجاز هادئ. */
  function renderOverviewTab(body, snap, snapshot) {
    body.textContent = "";
    var card = el("div", "wf-card wf-overview");
    card.appendChild(el("h3", "wf-section-title", "الهدف"));
    var objective = el("div", "wf-objective");
    objective.dir = "auto";
    objective.textContent = snap.objective || "";
    card.appendChild(objective);

    var plan = snapshot && snapshot.plan;
    if (plan) {
      card.appendChild(el("h3", "wf-section-title",
        "الخطة v" + plan.version +
        (plan.approved ? " — معتمدة" : " — بانتظار اعتمادك")));
      var phases = el("div", "wf-phases");
      ((plan.phases || []).length ? plan.phases :
        (snapshot.phases || [])).forEach(function (phase, i) {
        var line = el("div", "wf-phase-line");
        line.textContent = (i + 1) + ". " + (phase.title || "") +
          " (" + ((phase.steps || []).length) + " خطوة)";
        phases.appendChild(line);
      });
      card.appendChild(phases);
    }

    if (snap.last_error) {
      var errBox = el("div", "wf-blocking");
      errBox.appendChild(el("div", "wf-blocking-title", "آخر خطأ معلن"));
      errBox.appendChild(el("div", "wf-blocking-reason",
                            snap.last_error));
      card.appendChild(errBox);
    }
    body.appendChild(card);
  }

  /** تبويب الأدلة (§48) — نوع/طابع/مصدر/حالة لكل بند. */
  function renderEvidenceTab(body, projectId) {
    body.textContent = "";
    var card = el("div", "wf-card");
    card.appendChild(el("h3", "wf-section-title", "الأدلة"));
    Hub.fetchJSON("/api/projects/" + projectId + "/evidence")
      .then(function (out) {
        if (!out.ok) {
          card.appendChild(el("div", "wf-empty",
            "تعذر تحميل الأدلة — " + (out.j && out.j.detail)));
          return;
        }
        var items = out.j.evidence || [];
        if (!items.length) {
          card.appendChild(el("div", "wf-empty",
            "لا أدلة بعد — تُنتج مع كل خطوة تنفيذ مكتملة"));
          return;
        }
        items.forEach(function (item) {
          var row = el("div", "wf-evidence-row");
          row.appendChild(el("span", "wf-evidence-badge",
            item.verdict === "PASS" ? "✓" : "·"));
          var text = el("div", "wf-evidence-text");
          text.appendChild(el("div", "wf-evidence-line",
            "خطوة #" + (item.step_id || "—") + " · " +
            (item.verdict || "")));
          var files = Object.keys(item.files || {});
          if (files.length) {
            text.appendChild(el("div", "wf-evidence-sub",
              "ملفات: " + files.join("، ")));
          }
          row.appendChild(text);
          row.appendChild(el("span", "wf-evidence-time",
            (item.created_at || "").slice(11, 19)));
          card.appendChild(row);
        });
      });
    body.appendChild(card);
  }

  /** تبويب المخرجات (§47) — من الأدلة الدائمة حصرًا. */
  function renderArtifactsTab(body, projectId) {
    body.textContent = "";
    var card = el("div", "wf-card");
    card.appendChild(el("h3", "wf-section-title", "المخرجات"));
    Hub.fetchJSON("/api/projects/" + projectId + "/artifacts")
      .then(function (out) {
        if (!out.ok) return;
        var items = out.j.artifacts || [];
        if (!items.length) {
          card.appendChild(el("div", "wf-empty",
            "لا مخرجات بعد — ما لم يُثبت لا يُعرض"));
          return;
        }
        items.forEach(function (a) {
          var row = el("div", "wf-artifact-row");
          row.appendChild(el("span", "wf-artifact-icon",
            a.kind === "file" ? "📄" : "📦"));
          var text = el("div", "wf-evidence-text");
          text.appendChild(el("div", "wf-evidence-line", a.name));
          if (a.bytes) {
            text.appendChild(el("div", "wf-evidence-sub",
              (a.bytes / 1024).toFixed(1) + " كيلوبايت"));
          }
          row.appendChild(text);
          var sha = el("button", "wf-artifact-sha", "sha256");
          sha.title = a.sha256 || "";
          sha.addEventListener("click", function () {
            if (navigator.clipboard && a.sha256) {
              navigator.clipboard.writeText(a.sha256);
              sha.textContent = "نُسخ ✓";
              setTimeout(function () { sha.textContent = "sha256"; },
                1200);
            }
          });
          row.appendChild(sha);
          card.appendChild(row);
        });
      });
    body.appendChild(card);
  }

  /** تبويب التاريخ (§16+§43) — صفحات بمؤشر رجوع لا غرق DOM. */
  function renderHistoryTab(body, projectId) {
    body.textContent = "";
    var card = el("div", "wf-card");
    card.appendChild(el("h3", "wf-section-title",
      "التاريخ — كل ما حدث، صفحة صفحة"));
    var list = el("div", "wf-history-list");
    card.appendChild(list);
    var more = el("button", "wf-history-more", "تحميل الأقدم");
    var state = { before: 0 };

    function loadPage() {
      var url = "/api/projects/" + projectId +
        "/history?limit=60" +
        (state.before ? "&before_id=" + state.before : "");
      Hub.fetchJSON(url).then(function (out) {
        if (!out.ok) return;
        var events = out.j.events || [];
        events.forEach(function (event) {
          list.appendChild(historyLine(event));
        });
        more.hidden = !out.j.has_more;
        if (out.j.has_more) state.before = out.j.next_before;
        if (!events.length && !list.children.length) {
          list.appendChild(el("div", "wf-empty", "لا أحداث بعد"));
        }
      });
    }
    more.addEventListener("click", loadPage);
    card.appendChild(more);
    body.appendChild(card);
    loadPage();
  }

  /** سطر تاريخ مفهوم (§16) — انتقالات/قرارات/إعادات/فشل/أدلة. */
  function historyLine(event) {
    var line = el("div", "wf-history-line");
    var time = (event.created_at || "").slice(11, 19);
    line.appendChild(el("span", "wf-history-time", time || "·"));
    line.appendChild(el("span", "wf-history-dot",
      eventKindDot(event.kind)));
    var text = el("span", "wf-history-text");
    text.dir = "auto";
    text.textContent = historyText(event);
    line.appendChild(text);
    var details = el("button", "wf-history-json", "{…}");
    details.title = "التفاصيل التقنية";
    details.addEventListener("click", function () {
      Hub.openModal({
        role: "workflow", kind: event.kind, payload: event.payload,
      });
    });
    line.appendChild(details);
    return line;
  }

  function eventKindDot(kind) {
    if (/(FAIL|BLOCKED|INTERRUPTED|ERROR)/.test(kind)) return "⚠";
    if (/(COMPLETED|PASS|READY|APPROVED|VERIFIED)/.test(kind)) return "✓";
    if (/(STARTED|OPENED|RESUMED)/.test(kind)) return "●";
    return "·";
  }

  var HISTORY_LABELS = {
    PROJECT_CREATED: "أُنشئ المشروع",
    PLANNING_STARTED: "بدأ توليد الخطة",
    PLAN_GENERATING: "التوليد يستدعي النموذج",
    PLAN_CREATED: "وُلدت الخطة",
    PLAN_APPROVAL_REQUIRED: "الخطة تنتظر اعتمادك",
    PLAN_APPROVED: "اعتمدت الخطة",
    PLANNING_FAILED: "فشل توليد الخطة",
    PLANNING_INTERRUPTED: "انقطع توليد الخطة",
    PLANNING_RETRY: "أُعيدت محاولة التوليد",
    PREFLIGHT_STARTED: "بدأ فحص الجاهزية",
    PREFLIGHT_PASS: "الفحص نجح",
    PREFLIGHT_BLOCKED: "الفحص محجوب",
    EXECUTION_OPENED: "فُتح التنفيذ",
    PHASE_STARTED: "بدأت مرحلة",
    PHASE_COMPLETED: "اكتملت مرحلة",
    STEP_STARTED: "بدأت خطوة",
    STEP_COMPLETED: "اكتملت خطوة",
    EXECUTION_STARTED: "بدأ تنفيذ",
    EXECUTION_COMPLETED: "اكتمل تنفيذ",
    EXECUTION_FAILED: "فشل تنفيذ",
    EXECUTION_BLOCKED: "التنفيذ محجوب — مزود غير جاهز",
    EVIDENCE_CREATED: "دليل جديد",
    AUDIT_COMPLETED: "تدقيق",
    REVIEW_COMPLETED: "مراجعة اكتملت",
    TEST_COMPLETED: "اختبار اكتمل",
    RETRY_REQUESTED: "إعادة محاولة",
    OWNER_GATE_RESOLVED: "قرار مالك",
    JOB_CREATED: "وظيفة جديدة",
    JOB_STARTED: "بدأت الوظيفة",
    JOB_WAITING: "الوظيفة تنتظر",
    JOB_FAILED: "فشلت الوظيفة",
    JOB_PAUSED: "الوظيفة متوقفة مؤقتًا",
    PROJECT_PAUSED: "المشروع متوقف مؤقتًا",
    PROJECT_STOPPED: "أُوقف المشروع نهائيًا",
    PROJECT_RESUMED: "استؤنف المشروع",
    PROJECT_ARCHIVED: "أُرشف المشروع",
    PROJECT_RESTORED: "استُرجع المشروع",
    PROJECT_RENAMED: "أُعيدت التسمية",
    PROJECT_DUPLICATED: "نسخة من مشروع",
    PROJECT_VERIFIED: "تحقق نهائي",
    OWNER_STOP_REQUESTED: "طلبت الإيقاف",
    WORKFLOW_DIAGNOSED: "تشخيص سير العمل",
    MODEL_CALL_STARTED: "استدعاء نموذج بدأ",
    MODEL_CALL_COMPLETED: "استدعاء نموذج اكتمل",
    MODEL_CALL_FAILED: "استدعاء نموذج فشل",
    CHECKPOINT_CREATED: "نقطة حفظ",
    STAGE_REVIEW: "مراجعة مرحلة",
    ROLE_EXECUTING: "دور يعمل",
    TOOL_EXECUTION: "أداة",
    GATE_AUTO_RESOLVED: "بوابة حُلَّت آليًا",
    GATE_KEPT_BLOCKED: "الحاجز باقٍ — الفجوة قائمة",
  };

  function historyText(event) {
    var label = HISTORY_LABELS[event.kind] || event.kind;
    var payload = event.payload || {};
    var extra = "";
    if (event.kind === "PLANNING_FAILED" && payload.error_class) {
      extra = " [" + payload.error_class + "]";
    }
    if (event.kind === "MODEL_CALL_FAILED" && payload.error_class) {
      extra = " [" + payload.error_class + "]";
    }
    if (event.kind === "PHASE_STARTED" && payload.title) {
      extra = ": " + payload.title;
    }
    if (event.kind === "STEP_STARTED" && payload.objective) {
      extra = ": " + String(payload.objective).slice(0, 60);
    }
    if (event.kind === "TOOL_EXECUTION" && payload.tool) {
      extra = ": " + payload.tool + " " + (payload.phase || "");
    }
    return label + extra;
  }

  window.WorkflowView = {
    renderWorkflowTab: renderWorkflowTab,
    renderOverviewTab: renderOverviewTab,
    renderEvidenceTab: renderEvidenceTab,
    renderArtifactsTab: renderArtifactsTab,
    renderHistoryTab: renderHistoryTab,
    STATUS_LABELS: STATUS_LABELS,
  };
})();
