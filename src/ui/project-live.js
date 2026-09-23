/* Agentic Engineering System — المشروع كمحادثة حية (013 §8-§12+§27-§28).
 *
 * المنتج محادثة أولًا: الهدف رسالة من المالك، الخطة والاعتماد
 * والتنفيذ والأدلة بطاقات تتدفق في نفس المحادثة — حية كلحظة عبر
 * تيار الأحداث (لا refresh أبدًا)، والتفاصيل التقنية مطوية خلف
 * «التفاصيل التقنية» (progressive disclosure §9).
 *
 * عقد زر الاعتماد (§7): يظهر فقط عندما البوابة PENDING والنوع قرار
 * مالك؛ بعد الضغط: loading ← تعطيل مزدوج ← نجاح فوري ثم انتقال حي؛
 * فشل: السبب + معرف الطلب + إعادة المحاولة. ممنوع نجاح صامت.
 */
(function () {
  "use strict";

  if (!window.Hub) return;
  var Hub = window.Hub;
  var $ = Hub.$;
  var esc = Hub.esc;

  var STATUS_LABELS = {
    DRAFT: "مسودة", PLANNING: "جاري التخطيط",
    AWAITING_OWNER_APPROVAL: "بانتظار اعتمادك",
    READY: "معتمدة — جاري الفحص", RUNNING: "يعمل الآن",
    PAUSED: "متوقف مؤقتًا", BLOCKED: "التنفيذ متوقف",
    REVISING: "مراجعة الخطة", COMPLETED: "مرشح للتحقق",
    VERIFIED: "مُتحقق ✓", STOPPED: "موقوف", ESCALATED: "مُصعَّد",
  };
  var ROLE_LABELS = {
    thinker: "المفكر", reviewer: "المدقق", implementer: "المنفذ",
    verifier: "المراجع", arbiter: "المحكَّم", coordinator: "المنسق",
  };
  /* حالات البوابة (011 §2) — عرض صادق للبوابات المحلولة أيضًا */
  var GATE_STATUS_LABELS = {
    PENDING: "تنتظر قرارك", APPROVED: "معتمدة", REJECTED: "مرفوضة",
    BLOCKED: "محجوبة — تنتظر توفيرًا", CANCELLED: "ملغاة",
    EXPIRED: "منتهية",
  };

  var GATE_LABELS = {
    PLAN_APPROVAL: "اعتماد الخطة",
    PLAN_REVISION_APPROVAL: "مراجعة الخطة",
    PROVIDER_ACTION_REQUIRED: "إجراء مزود مطلوب",
    PREFLIGHT_BLOCKED: "توفير بيئة التنفيذ",
    ESCALATION: "تصعيد",
    FINAL_VERIFICATION: "التحقق النهائي",
    OBJECTIVE_CHANGE: "تغيير الهدف",
  };

  /* ---------- بناء البطاقات (كل DOM من هنا — لا HTML خارجي) ---------- */

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }

  function msgRow(who) {
    var row = el("div", "pl-row " + who);
    var avatar = el("div", "pl-avatar",
                    who === "owner" ? "أنت" : "النظام");
    var flow = el("div", "pl-flow");
    row.appendChild(avatar); row.appendChild(flow);
    return { row: row, flow: flow };
  }

  /* البطاقة الأم: المشروع + تدفق المستخدم الماكرو (013.2 §8) */
  function renderProjectCard(state) {
    var wrap = msgRow("assistant");
    var card = el("div", "pl-card pl-project");
    var head = el("div", "pl-head");
    var title = el("div", "pl-title", state.name || "مشروع");
    var status = el("span", "pl-status " + statusClass(state.status),
                    STATUS_LABELS[state.status] || state.status);
    head.appendChild(title); head.appendChild(status);
    card.appendChild(head);

    var objective = el("div", "pl-objective", state.objective || "");
    objective.dir = "auto";
    card.appendChild(objective);

    // (013.2 §8) تدفق المستخدم الماكرو — لا قائمة خطوات تقنية دائمة
    card.appendChild(renderMacroFlow(state));
    var failureLoop = renderFailureLoop(state);
    if (failureLoop) card.appendChild(failureLoop);

    // (013.2 §8) المسار التقني مطوي — للراغب في العمق فقط
    card.appendChild(renderTechDetails({
      technical_pipeline: renderTechnicalPipeline(state),
      project_status: state.status,
      plan_version: state.plan ? state.plan.version : null,
    }));
    wrap.flow.appendChild(card);
    return { row: wrap.row, card: card };
  }

  function statusClass(status) {
    return {
      VERIFIED: "ok", COMPLETED: "gold", RUNNING: "live",
      AWAITING_OWNER_APPROVAL: "gold", BLOCKED: "warn",
      PAUSED: "dim", STOPPED: "danger", ESCALATED: "danger",
      REVISING: "dim", PLANNING: "live",
    }[status] || "dim";
  }

  function stageMark(done, active) {
    if (done) return { cls: "done", icon: "✓" };
    if (active) return { cls: "active", icon: "⟳" };
    return { cls: "pending", icon: "○" };
  }

  /* (013.2 §8-§11) تدفق المستخدم الماكرو — سبع لحظات يفهمها أي
   * مالك: المحادثة ← الخطة ← الاعتماد ← تجهيز البيئة ← التنفيذ ←
   * المراجعة ← مكتمل. المسار التقني الداخلي (تحليل/أدلة/تدقيق/
   * تحقق) يبقى داخل «التفاصيل التقنية» — لا يحتل الواجهة الأساسية.
   * كل مؤشر مشتق من اللقطة والأحداث الفعلية — لا تخمين أمامي. */
  function macroFlowStep(state, seen) {
    var approved = state.plan && state.plan.approved_by_owner;
    var envReady = !!(seen.PREFLIGHT_PASS || seen.ENVIRONMENT_READY);
    var envState = state.environment
      && state.environment.runtime_state
      && state.environment.runtime_state.state;
    var executing = state.status === "RUNNING"
      || state.status === "REVISING";
    var reviewed = !!(state.audits || []).length;
    var done = state.status === "VERIFIED";
    var candidate = state.status === "COMPLETED" || done;
    var failed = state.status === "BLOCKED" || state.status === "ESCALATED"
      || (state.job && state.job.status === "FAILED");
    var preparing = !!(seen.PREFLIGHT_STARTED
      || (envState && ["DISCOVERING", "PROVISIONING", "BOOTING",
                       "HEALTH_CHECK"].indexOf(envState) !== -1));
    return [
      { label: "المحادثة", done: true },
      { label: "الخطة", done: !!(state.plan || seen.PLAN_CREATED),
        active: state.status === "PLANNING" },
      { label: "الاعتماد", done: !!approved,
        waiting: state.status === "AWAITING_OWNER_APPROVAL" },
      { label: "تجهيز البيئة", done: envReady,
        active: preparing && !envReady && !failed },
      { label: "التنفيذ", done: !!(seen.PROJECT_COMPLETION_CANDIDATE
        || candidate), active: executing },
      { label: "المراجعة", done: reviewed || done,
        active: candidate && !done },
      { label: "مكتمل", done: done,
        waiting: state.status === "COMPLETED" },
    ];
  }

  function renderMacroFlow(state) {
    var seen = {};
    (state.events || []).forEach(function (e) { seen[e.kind] = true; });
    var steps = macroFlowStep(state, seen);
    var wrap = el("div", "pl-flow");
    steps.forEach(function (step, index) {
      var item = el("div", "pl-flow-step "
        + (step.done ? "done" : step.active ? "active"
          : step.waiting ? "waiting" : "pending"));
      item.appendChild(el("span", "pl-flow-dot",
        step.done ? "✓" : step.active ? "●" : ""));
      item.appendChild(el("span", "pl-flow-label", step.label));
      wrap.appendChild(item);
      if (index < steps.length - 1) {
        wrap.appendChild(el("span", "pl-flow-arrow", "←"));
      }
    });
    return wrap;
  }

  /* (013.2 §11) حلقة الفشل المرئية — تظهر فقط عند الفشل فعليًا:
   * فشل ← تشخيص ← تعديل الخطة ← إعادة المحاولة */
  function renderFailureLoop(state) {
    var job = state.job || {};
    var failed = state.status === "BLOCKED"
      || job.status === "FAILED" || job.status === "INTERRUPTED";
    if (!failed) return null;
    var wrap = el("div", "pl-failloop");
    var steps = ["فشل/انقطاع", "تشخيص السبب", "تعديل", "إعادة المحاولة"];
    steps.forEach(function (label, index) {
      var cls = index === 0 ? "hit" : index === 1 ? "active" : "pending";
      wrap.appendChild(el("span", "pl-fail-step " + cls, label));
      if (index < steps.length - 1) {
        wrap.appendChild(el("span", "pl-fail-arrow", "←"));
      }
    });
    return wrap;
  }

  /* (013.2 §8) المسار التقني الكامل — مطوي داخل التفاصيل، لا مسارًا
   * أساسيًا: هذا للمهندس الذي يفتح «التفاصيل التقنية» بإرادته */
  function renderTechnicalPipeline(state) {
    var seen = {};
    (state.events || []).forEach(function (e) { seen[e.kind] = true; });
    var approved = state.plan && state.plan.approved_by_owner;
    return [
      { label: "الهدف", done: true },
      { label: "تحليل المتطلبات", done: !!(state.plan || seen.PLAN_CREATED) },
      { label: "الخطة", done: !!(state.plan || seen.PLAN_CREATED) },
      { label: "اعتماد المالك", done: !!approved },
      { label: "فحص البيئة",
        done: !!(seen.PREFLIGHT_PASS || seen.ENVIRONMENT_READY) },
      { label: "التنفيذ", done: !!seen.PROJECT_COMPLETION_CANDIDATE },
      { label: "جمع الأدلة", done: !!(state.evidence || []).length },
      { label: "التدقيق", done: !!(state.audits || []).length },
      { label: "التحقق", done: state.status === "VERIFIED" },
    ].map(function (stage) {
      return (stage.done ? "✓ " : "○ ") + stage.label;
    }).join(" · ");
  }

  /* ---------- (013.5 §N) تفاصيل الخطة: أقسام مسماة قابلة للطي ----------
   *
   * عطل التباين مُصلح من جذره: كانت أسطح الخطة تُبنى فاتحة (رموز
   * غير معرّفة في الثيم الداكن) تحت نص فاتح. هنا كل سطح من رموز
   * styles.css نفسها، والقسم المفتوح افتراضيًا واحد فقط (الخلاصة)،
   * والحالة/المراحل/الخطوات/الافتراضات/الاعتمادات/الاعتماد مطوية،
   * والخام خلف «JSON خام» — لا جدار JSON في المسار الأساسي. */

  function planSection(label, count, open) {
    var sec = el("div", "pl-sec" + (open ? " open" : ""));
    var toggle = el("button", "pl-sec-toggle");
    toggle.type = "button";
    var arrow = el("span", "pl-sec-arrow", open ? "▴" : "▾");
    toggle.appendChild(arrow);
    toggle.appendChild(el("span", "pl-sec-label", label));
    if (count != null) {
      toggle.appendChild(el("span", "pl-sec-count", String(count)));
    }
    var body = el("div", "pl-sec-body");
    body.hidden = !open;
    toggle.addEventListener("click", function () {
      body.hidden = !body.hidden;
      sec.className = body.hidden ? "pl-sec" : "pl-sec open";
      arrow.textContent = body.hidden ? "▾" : "▴";
    });
    sec.appendChild(toggle);
    sec.appendChild(body);
    return { root: sec, body: body };
  }

  /* سطر مفتاح/قيمة — يُقرأ كبطاقة لا كـJSON */
  function planRow(key, value) {
    var row = el("div", "pl-kv");
    row.appendChild(el("span", "pl-kv-k", key));
    var v = el("span", "pl-kv-v",
      value == null || value === "" ? "—" : String(value));
    v.dir = "auto";
    row.appendChild(v);
    return row;
  }

  /* نص بند قد يكون نصًا أو كائنًا — بلا تفريغ خام للخطة */
  function planItemText(item) {
    if (item == null) return "";
    if (typeof item === "string") return item;
    var fields = ["description", "statement", "text", "title",
                  "objective", "summary", "reason", "name", "need"];
    for (var i = 0; i < fields.length; i++) {
      if (item[fields[i]]) return String(item[fields[i]]);
    }
    return item.id ? String(item.id) : "";
  }

  function planItemList(items) {
    var list = el("div", "pl-list");
    (items || []).forEach(function (item) {
      var text = planItemText(item);
      if (!text) return;
      var line = el("div", "pl-list-item", text);
      line.dir = "auto";
      list.appendChild(line);
    });
    return list;
  }

  function planEmpty(text) {
    var note = el("div", "pl-empty", text);
    note.dir = "auto";
    return note;
  }

  /* بطاقة الخطة (§11 + 013.5 §N): إطار «الخطة» وسبعة أقسام مسماة
   * قابلة للطي بالترتيب المعلن — مستقرة من اللقطة وحدها (§8). */
  function renderPlanCard(plan, state) {
    if (!plan) return null;
    var snapshot = state || {};
    var phases = plan.phases || [];
    var assumptions = plan.assumptions || [];
    var dependencies = plan.dependencies
      || plan.external_dependencies || [];
    var gates = (snapshot.gates || []).filter(function (g) {
      return g.kind === "PLAN_APPROVAL"
        || g.kind === "PLAN_REVISION_APPROVAL";
    });
    var pendingGate = null;
    gates.forEach(function (g) {
      if (g.status === "PENDING" && !pendingGate) pendingGate = g;
    });
    var approved = !!plan.approved_by_owner;
    var stepList = [];
    phases.forEach(function (phase, pi) {
      (phase.steps || []).forEach(function (step, si) {
        stepList.push({
          number: (pi + 1) + "." + (si + 1),
          phase: phase.title || ("مرحلة " + (pi + 1)),
          step: step,
        });
      });
    });
    if (!stepList.length) {
      (plan.steps || []).forEach(function (step, si) {
        stepList.push({ number: String(si + 1), phase: "", step: step });
      });
    }

    var wrap = msgRow("assistant");
    var card = el("div", "pl-card pl-plan");

    var head = el("div", "pl-head");
    head.appendChild(el("div", "pl-title",
      "الخطة الرئيسية v" + (plan.version || "?")));
    head.appendChild(el("span", "pl-status " + (approved ? "ok"
      : plan.status === "REJECTED" ? "danger" : "gold"),
      approved ? "معتمدة" : "بانتظار اعتمادك"));
    card.appendChild(head);

    var meta = el("div", "pl-meta");
    meta.appendChild(el("span", null, phases.length + " مراحل"));
    meta.appendChild(el("span", null, stepList.length + " خطوة"));
    if (assumptions.length) {
      meta.appendChild(el("span", null,
        assumptions.length + " افتراضات"));
    }
    if (dependencies.length) {
      meta.appendChild(el("span", null,
        dependencies.length + " اعتمادات"));
    }
    card.appendChild(meta);

    // 1) الخلاصة — القسم المفتوح افتراضيًا
    var summary = planSection("الخلاصة", null, true);
    summary.body.appendChild(planRow("الهدف",
      plan.objective || plan.summary || snapshot.objective));
    summary.body.appendChild(planRow("الإصدار",
      "v" + (plan.version || "?")
      + (plan.status ? " · " + plan.status : "")));
    summary.body.appendChild(planRow("الحجم",
      phases.length + " مراحل · " + stepList.length + " خطوة"));
    summary.body.appendChild(planRow("الاعتماد",
      approved ? "معتمد من المالك"
        : pendingGate ? "بانتظار قرارك الآن" : "غير معتمد بعد"));
    card.appendChild(summary.root);

    // 2) الحالة الحالية — من اللقطة القانونية لا تخمينًا
    var current = planSection("الحالة الحالية", null, false);
    current.body.appendChild(planRow("حالة الخطة",
      plan.status || "—"));
    if (snapshot.status) {
      current.body.appendChild(planRow("حالة المشروع",
        STATUS_LABELS[snapshot.status] || snapshot.status));
    }
    current.body.appendChild(planRow("اعتماد المالك",
      approved ? "نعم" : "لا"));
    if (gates.length) {
      gates.slice(0, 4).forEach(function (g) {
        current.body.appendChild(planRow(
          GATE_LABELS[g.kind] || "بوابة الخطة",
          GATE_STATUS_LABELS[g.status] || g.status));
      });
    } else {
      current.body.appendChild(
        planEmpty("لا بوابة خطة مسجلة في اللقطة بعد."));
    }
    card.appendChild(current.root);

    // 3) المراحل — بطاقات مراحل لا أسطر خام
    var phasesSec = planSection("المراحل", phases.length, false);
    if (!phases.length) {
      phasesSec.body.appendChild(
        planEmpty("لا مراحل معلنة في الخطة بعد."));
    }
    phases.forEach(function (phase, index) {
      var box = el("div", "pl-phase-card");
      var boxHead = el("div", "pl-phase-head");
      var name = el("span", "pl-phase-name",
        (index + 1) + ". " + (phase.title || "مرحلة"));
      name.dir = "auto";
      boxHead.appendChild(name);
      boxHead.appendChild(el("span", "pl-phase-state",
        (phase.status || "PENDING")
        + " · " + (phase.steps || []).length + " خطوة"));
      box.appendChild(boxHead);
      var phaseText = planItemText(phase);
      if (phaseText && phaseText !== phase.title) {
        var sub = el("div", "pl-phase-sub", phaseText);
        sub.dir = "auto";
        box.appendChild(sub);
      }
      phasesSec.body.appendChild(box);
    });
    card.appendChild(phasesSec.root);

    // 4) الخطوات — مرقمة بالمرحلة، قابلة للطي ككتلة واحدة
    var stepsSec = planSection("الخطوات", stepList.length, false);
    if (!stepList.length) {
      stepsSec.body.appendChild(
        planEmpty("لا خطوات معلنة في الخطة بعد."));
    }
    var lastPhase = null;
    stepList.forEach(function (item) {
      if (item.phase && item.phase !== lastPhase) {
        lastPhase = item.phase;
        var groupTitle = el("div", "pl-steps-group-title", item.phase);
        groupTitle.dir = "auto";
        stepsSec.body.appendChild(groupTitle);
      }
      var row = el("div", "pl-step-row");
      var number = el("span", "pl-step-n", item.number);
      number.dir = "ltr";
      row.appendChild(number);
      var text = el("span", "pl-step-text",
        planItemText(item.step) || "خطوة بلا وصف");
      text.dir = "auto";
      row.appendChild(text);
      if (item.step && item.step.status) {
        row.appendChild(el("span", "pl-step-state", item.step.status));
      }
      stepsSec.body.appendChild(row);
    });
    card.appendChild(stepsSec.root);

    // 5) الافتراضات
    var assumeSec = planSection("الافتراضات", assumptions.length, false);
    assumeSec.body.appendChild(assumptions.length
      ? planItemList(assumptions)
      : planEmpty("لا افتراضات معلنة في الخطة."));
    card.appendChild(assumeSec.root);

    // 6) الاعتمادات — ما تتوقف عليه الخطة خارج نطاقها
    var depsSec = planSection("الاعتمادات", dependencies.length, false);
    depsSec.body.appendChild(dependencies.length
      ? planItemList(dependencies)
      : planEmpty("لا اعتمادات معلنة في الخطة."));
    card.appendChild(depsSec.root);

    // 7) الاعتماد — القرار نفسه يبقى في بطاقة الاعتماد (بلا تكرار أزرار)
    var approvalSec = planSection("الاعتماد", null, false);
    approvalSec.body.appendChild(planRow("اعتماد المالك",
      approved ? "نعم — معتمدة" : "لا — بانتظار قرارك"));
    if (plan.approved_at) {
      approvalSec.body.appendChild(planRow("وقت الاعتماد", plan.approved_at));
    }
    if (pendingGate) {
      approvalSec.body.appendChild(planRow("البوابة المعلقة",
        GATE_LABELS[pendingGate.kind] || "بوابة الخطة"));
      if (pendingGate.reason) {
        approvalSec.body.appendChild(planRow("السبب", pendingGate.reason));
      }
      approvalSec.body.appendChild(
        planEmpty("القرار يُتخذ من بطاقة الاعتماد في المحادثة — لا من هنا."));
    } else if (!approved) {
      approvalSec.body.appendChild(
        planEmpty("لا بوابة اعتماد معلقة في اللقطة الحالية."));
    }
    card.appendChild(approvalSec.root);

    // الخام خلف طيّ صريح مسمى — ليس في أي قسم افتراضي (013.5 §N)
    var rawSec = planSection("JSON خام", null, false);
    var raw = el("pre", "pl-tech-body pl-raw-body");
    raw.dir = "ltr";
    try { raw.textContent = JSON.stringify(plan, null, 1); }
    catch (e) { raw.textContent = String(plan); }
    rawSec.body.appendChild(raw);
    card.appendChild(rawSec.root);

    wrap.flow.appendChild(card);
    return { row: wrap.row, card: card };
  }

  /* بطاقة الاعتماد (§11 حرفيًا) + عقد الزر (§7) */
  function renderApprovalCard(state, actions) {
    var gate = null;
    (state.gates || []).forEach(function (g) {
      if (g.status === "PENDING" && !gate) gate = g;
    });
    if (!gate) return null;
    var wrap = msgRow("assistant");
    var card = el("div", "pl-card pl-approval");
    card.appendChild(el("div", "pl-title",
      GATE_LABELS[gate.kind] || "قرار مطلوب"));
    card.appendChild(el("div", "pl-note",
      gate.reason || "تم إعداد خطة التنفيذ وتحتاج اعتمادك."));

    var buttons = el("div", "pl-actions");
    if (gate.kind === "PLAN_APPROVAL" && state.plan) {
      var view = el("button", "pl-btn", "عرض الخطة");
      view.addEventListener("click", actions.viewPlan);
      buttons.appendChild(view);
    }
    /* (013.5 §N) فعل أساسي واحد ظاهر: «اعتماد الخطة» — والثانويان
     * «طلب تعديل» و«رفض» بنفس المسار والمعالج حرفيًا (بلا URL جديد) */
    var approveLabel = gate.kind === "PLAN_APPROVAL"
      || gate.kind === "FINAL_VERIFICATION"
      ? "اعتماد الخطة" : "موافقة";
    var approve = el("button", "pl-btn primary", approveLabel);
    var revise = el("button", "pl-btn", "طلب تعديل");
    var reject = el("button", "pl-btn danger", "رفض");
    buttons.appendChild(approve);
    buttons.appendChild(revise);
    buttons.appendChild(reject);
    card.appendChild(buttons);

    var feedback = el("div", "pl-feedback"); feedback.hidden = true;
    card.appendChild(feedback);

    // البوابات المحلولة سابقًا — تفاصيل تقنية صادقة لا حذف للتاريخ
    var resolved = (state.gates || []).filter(function (g) {
      return g.status !== "PENDING";
    }).slice(0, 4).map(function (g) {
      return {id: g.id, kind: g.kind, status: g.status,
              label: GATE_STATUS_LABELS[g.status] || g.status};
    });
    if (resolved.length) {
      card.appendChild(renderTechDetails({resolved_gates: resolved}));
    }

    function setBusy(text) {
      approve.disabled = true;
      revise.disabled = true;
      reject.disabled = true;
      approve.textContent = text;
      feedback.hidden = false; feedback.className = "pl-feedback loading";
      feedback.textContent = text;
    }
    function setResult(ok, text, extra) {
      approve.disabled = false;
      revise.disabled = false;
      reject.disabled = false;
      approve.textContent = approveLabel;
      feedback.hidden = false;
      feedback.className = "pl-feedback " + (ok ? "ok" : "err");
      feedback.textContent = text;
      if (extra) {
        var detail = el("div", "pl-feedback-detail", extra);
        feedback.appendChild(detail);
      }
    }

    approve.addEventListener("click", function () {
      setBusy("جاري الاعتماد…");
      var sentAt = Date.now();
      Hub.fetchJSON(actions.approveUrl(gate), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ approved: true, note: "" }),
      }).then(function (out) {
        if (out.ok) {
          setResult(true, "تم اعتماد الخطة — جاري الفحص…",
            "معرف الطلب: " + ((out.j || {}).correlation_id || sentAt));
          // الانتقال يصل حيًّا عبر التيار — لا refresh
        } else {
          var detail = (out.j && out.j.detail) || "سبب غير معروف";
          setResult(false, "تعذر اعتماد الخطة", detail +
            " · معرف الطلب: " + sentAt + " · الحالة الحالية: " +
            (STATUS_LABELS[state.status] || state.status));
        }
      }, function (err) {
        setResult(false, "تعذر الوصول للخدمة",
          String(err) + " · معرف الطلب: " + sentAt +
          " — أعد المحاولة");
      });
    });

    /* «طلب تعديل» و«رفض»: نفس المعالج ونفس المسار ونفس الجسم حرفيًا
     * (approved: false + ملاحظة المالك) — يختلف تسمية الحقل فقط */
    function sendRevision(promptText) {
      var note = window.prompt(promptText, "");
      if (note === null) return;
      setBusy("جاري تسجيل الرفض…");
      Hub.fetchJSON(actions.approveUrl(gate), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ approved: false, note: note }),
      }).then(function (out) {
        if (out.ok) setResult(true, "سُجل الرفض — سيُعاد التخطيط");
        else setResult(false, "تعذر تسجيل الرفض",
          (out.j && out.j.detail) || "");
      });
    }

    revise.addEventListener("click", function () {
      sendRevision(
        "ما التعديل المطلوب؟ (يصل للنظام كتغذية راجعة لإعادة التخطيط)");
    });

    reject.addEventListener("click", function () {
      sendRevision(
        "سبب الرفض؟ (يصل للنظام كتغذية راجعة لإعادة التخطيط)");
    });

    wrap.flow.appendChild(card);
    return { row: wrap.row, card: card, gate: gate };
  }

  /* بطاقة بيئة التنفيذ المتماسكة (013.2 §7+§2) — ثلاث حالات لا رابعة.
   *
   * المصدر حصريًا: state.environment.runtime_state.coherent من
   * الخادم (الحالة القانونية الواحدة) — الواجهة تقتبس النص ولا
   * تركّب حالة محلية أبدًا. المطلوب (REQUIRED) والفعلي (ACTUAL)
   * معروضان مفصولين حرفيًا — مستحيل اليوم قراءة «غير جاهزة» وتحتها
   * وصف يوحي بالجاهزية.
   *   ✓ جاهزة — الاسم والعزل والعامل ونبضته وبرهان الفحص
   *   ⏳ تجهيز — الخطوات والتقدم% من السجل الدائم
   *   ⚠️ غير متاحة — المضيف + المطلوب + الفجوات الحرفية + الأفعال
   */
  function renderEnvironmentCard(state, actions) {
    var env = state.environment;
    if (!env) return null;
    var wrap = msgRow("assistant");
    var card = el("div", "pl-card pl-env");
    var runtime = env.runtime_state || {};
    var coherent = runtime.coherent || {};
    var kind = coherent.kind
      || (env.selected && env.selected.status === "READY"
        ? "READY" : "UNAVAILABLE");
    var job = state.job;
    var policy = env.policy || "STRICT_ISOLATED";

    if (kind === "READY") {
      card.classList.add("ready");
      card.appendChild(el("div", "pl-title",
        coherent.label || "✓ بيئة التنفيذ جاهزة"));
      var readyRows = el("div", "pl-env-rows");
      var selected = runtime.selected || env.selected || {};
      readyRows.appendChild(envRow("البيئة", selected.name || "—"));
      readyRows.appendChild(envRow("العزل",
        selected.sandboxed ? "صارم (معزولة)" : "بلا عزل (معلن)"));
      readyRows.appendChild(envRow("الخلفية", selected.backend || "—"));
      var checks = (runtime.evidence || {}).checks || [];
      readyRows.appendChild(envRow("فحص الصحة",
        checks.length
          ? "نجحت " + checks.length + " فحوصًا حقيقية"
          : "تحقق حقيقي ناجح"));
      if (job && job.worker_id) {
        readyRows.appendChild(envRow("العامل", job.worker_id +
          (job.heartbeat_age_s != null
            ? " — نبضة قبل " + Math.max(0, Math.round(job.heartbeat_age_s))
              + "ث" : "")));
      }
      card.appendChild(readyRows);
      if (coherent.detail) {
        var readyNote = el("div", "pl-note");
        readyNote.dir = "auto";
        readyNote.textContent = coherent.detail;
        card.appendChild(readyNote);
      }
    } else if (kind === "PREPARING") {
      card.classList.add("preparing");
      card.appendChild(el("div", "pl-title",
        coherent.label || "⏳ تجهيز بيئة التنفيذ"));
      var progressValue = coherent.progress || runtime.progress || 0;
      var bar = el("div", "pl-env-progress");
      var fill = el("div", "pl-env-progress-fill");
      fill.style.width = Math.max(4, progressValue) + "%";
      bar.appendChild(fill);
      card.appendChild(bar);
      card.appendChild(el("div", "pl-env-progress-pct",
        progressValue > 0 ? "التقدم: " + progressValue + "٪" : ""));
      var prepNote = el("div", "pl-note");
      prepNote.dir = "auto";
      prepNote.textContent = coherent.detail
        || "جاري إنشاء بيئة التنفيذ…";
      card.appendChild(prepNote);
      card.appendChild(renderRequiredVsActual(env));
      var buttons = el("div", "pl-actions");
      var provision = el("button", "pl-btn primary", "تجهيز البيئة");
      var recheck = el("button", "pl-btn", "إعادة الفحص");
      buttons.appendChild(provision); buttons.appendChild(recheck);
      card.appendChild(buttons);
      var progress = el("div", "pl-feedback"); progress.hidden = true;
      card.appendChild(progress);
      wireProvisionButtons(card, provision, recheck, progress,
        state, actions, policy);
    } else {
      card.classList.add("notready");
      card.appendChild(el("div", "pl-title",
        coherent.label || "⚠️ بيئة التنفيذ غير متاحة"));
      var unavailableNote = el("div", "pl-note");
      unavailableNote.dir = "auto";
      unavailableNote.textContent = coherent.detail || env.requirement
        || "لم يُعثر على بيئة توافق السياسة على هذا المضيف.";
      card.appendChild(unavailableNote);
      card.appendChild(renderRequiredVsActual(env));
      var missingList = (runtime.missing || [])
        .concat(coherent.missing || []);
      if (missingList.length) {
        var gaps = el("div", "pl-env-missing");
        missingList.forEach(function (gap) {
          var gapRow = el("div", "pl-env-gap");
          gapRow.appendChild(el("div", "pl-env-gap-need",
            "• " + (gap.need || "متطلب")));
          if (gap.detected) {
            gapRow.appendChild(el("div", "pl-env-gap-detected",
              "المكتشف: " + gap.detected));
          }
          if (gap.action) {
            gapRow.appendChild(el("div", "pl-env-gap-action",
              "الإجراء: " + gap.action));
          }
          gaps.appendChild(gapRow);
        });
        card.appendChild(gaps);
      }
      var unButtons = el("div", "pl-actions");
      var unProvision = el("button", "pl-btn primary", "تجهيز البيئة");
      var unRecheck = el("button", "pl-btn", "إعادة الفحص");
      unButtons.appendChild(unProvision); unButtons.appendChild(unRecheck);
      card.appendChild(unButtons);
      var unProgress = el("div", "pl-feedback"); unProgress.hidden = true;
      card.appendChild(unProgress);
      wireProvisionButtons(card, unProvision, unRecheck, unProgress,
        state, actions, policy);
    }

    card.appendChild(renderTechDetails({
      policy: env.policy,
      runtime_state: runtime.state,
      satisfies_policy: env.satisfies_policy,
      host: env.host,
      selected: env.selected,
      environment_id: runtime.environment_id,
      worker_id: runtime.worker_id,
      requirement: env.requirement,
    }));
    wrap.flow.appendChild(card);
    return { row: wrap.row, card: card };
  }

  /* (013.2 §2) المطلوب مقابل الفعلي — سطران مفصولان حرفيًا لا خلط */
  function renderRequiredVsActual(env) {
    var runtime = env.runtime_state || {};
    var required = runtime.required || {};
    var actual = runtime.actual || {};
    var host = (actual.host && actual.host.platform)
      || (env.host && env.host.platform) || "—";
    var box = el("div", "pl-env-reqact");
    var reqRow = el("div", "pl-env-detected");
    reqRow.appendChild(el("span", "pl-env-k", "المطلوب: "));
    var reqText = el("span", "pl-env-v",
      (required.os || "—") + " · "
      + (required.isolation || ""));
    reqText.dir = "auto";
    reqRow.appendChild(reqText);
    box.appendChild(reqRow);
    var actRow = el("div", "pl-env-detected");
    actRow.appendChild(el("span", "pl-env-k", "المضيف الحالي: "));
    actRow.appendChild(el("span", "pl-env-v", host));
    box.appendChild(actRow);
    return box;
  }

  /* أزرار التجهيز/الفحص — نفس السلوك الحي، والسياسة تُمرَّر (013.2 §5) */
  function wireProvisionButtons(card, provision, recheck, progress,
                                state, actions, policy) {
    provision.addEventListener("click", function () {
      provision.disabled = true;
      progress.hidden = false;
      progress.className = "pl-feedback loading";
      progress.textContent = "⏳ جاري تجهيز بيئة التنفيذ…";
      Hub.fetchJSON("/api/environment/provision", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ policy: policy }),
      }).then(function (out) {
        provision.disabled = false;
        if (!out.ok) {
          progress.className = "pl-feedback err";
          progress.textContent = "تعذر التجهيز: "
            + ((out.j && out.j.reason) || "");
          return;
        }
        var result = out.j || {};
        if (result.state === "READY") {
          progress.className = "pl-feedback ok";
          progress.textContent = "جاهزة — أعد الفحص لاستئناف التنفيذ";
        } else {
          progress.className = "pl-feedback err";
          progress.textContent = (result.reason || "تعذر التجهيز")
            + (result.requirement
              ? " — " + result.requirement : "");
        }
      }, function () {
        provision.disabled = false;
        progress.className = "pl-feedback err";
        progress.textContent = "تعذر الوصول لخدمة التجهيز — أعد المحاولة";
      });
    });
    recheck.addEventListener("click", function () {
      recheck.disabled = true;
      progress.hidden = false;
      progress.className = "pl-feedback loading";
      progress.textContent = "جاري إعادة الفحص…";
      Hub.fetchJSON(actions.recheckUrl, { method: "POST" })
        .then(function (out) {
          recheck.disabled = false;
          if (!out.ok) {
            progress.className = "pl-feedback err";
            progress.textContent = "تعذر الفحص: "
              + ((out.j && out.j.detail) || "");
            return;
          }
          var j = out.j || {};
          if (j.preflight && j.preflight.verdict === "PASS") {
            progress.className = "pl-feedback ok";
            progress.textContent =
              "البيئة جاهزة — استؤنف التنفيذ تلقائيًا بنفس الوظيفة";
          } else {
            progress.className = "pl-feedback err";
            progress.textContent = "ما زالت غير جاهزة — "
              + ((state.environment || {}).requirement
                || "راجع المتطلبات");
          }
        }, function () {
          recheck.disabled = false;
          progress.className = "pl-feedback err";
          progress.textContent = "تعذر الوصول — أعد المحاولة";
        });
    });
  }

  function envRow(key, value) {
    var row = el("div", "pl-env-row");
    row.appendChild(el("span", "pl-env-k", key + ": "));
    row.appendChild(el("span", "pl-env-v", value));
    return row;
  }

  /* بطاقة التنفيذ الحية (013.1 §21 + 013.2 §12) — تتحدث تلقائيًا
   * عبر المصالحات. شريط تقدم المراحل + ملخصات تنفيذ آمنة فقط
   * (لا سلسلة تفكير خام §10): المرحلة/آخر نشاط/البيئة/العامل
   * + [التفاصيل] [إيقاف التنفيذ] — الإيقاف الصريح وحده يوقف (§19). */
  function renderExecutionCard(state, actions) {
    var job = state.job;
    var wrap = msgRow("assistant");
    var card = el("div", "pl-card pl-exec live");

    var head = el("div", "pl-title");
    var dot = el("span", "pl-exec-dot", "●");
    head.appendChild(dot);
    head.appendChild(el("span", null, " التنفيذ جارٍ"));
    card.appendChild(head);

    var phases = state.phases || [];
    var doneCount = 0;
    phases.forEach(function (p) {
      if (p.status === "COMPLETED" || p.status === "DONE") doneCount++;
    });
    if (phases.length) {
      var pct = Math.round((doneCount / phases.length) * 100);
      card.appendChild(el("div", "pl-env-progress-label",
        "التقدم: " + doneCount + "/" + phases.length + " مراحل (" + pct + "٪)"));
      var bar = el("div", "pl-env-progress");
      var fill = el("div", "pl-env-progress-fill");
      fill.style.width = Math.max(4, pct) + "%";
      bar.appendChild(fill);
      card.appendChild(bar);
    }

    var rows = el("div", "pl-env-rows");
    var objective = el("div", "pl-env-row");
    objective.appendChild(el("span", "pl-env-k", "الهدف: "));
    var objText = el("span", "pl-env-v",
      String(state.objective || "").slice(0, 120));
    objText.dir = "auto";
    objective.appendChild(objText);
    rows.appendChild(objective);

    rows.appendChild(envRow("الحالة",
      STATUS_LABELS[state.status] || state.status));

    var env = state.environment;
    var envSel = (env && env.runtime_state
      && env.runtime_state.selected) || (env && env.selected);
    rows.appendChild(envRow("البيئة",
      envSel ? (envSel.name + " — " +
        (envSel.sandboxed ? "عزل صارم" : "بلا عزل معلن"))
        : "غير محددة بعد"));

    if (job) {
      rows.appendChild(envRow("العامل",
        (job.worker_id || "—") +
        (job.heartbeat_age_s != null
          ? " — نبضة قبل " + Math.max(0, Math.round(job.heartbeat_age_s)) + "ث"
          : "")));
      if (job.current_phase_id && phases.length) {
        var phase = null;
        phases.forEach(function (p) {
          if (p.id === job.current_phase_id) phase = p;
        });
        if (phase) rows.appendChild(envRow("المرحلة", phase.title || "—"));
      }
    }

    var lastEvent = (state.events || []).filter(function (e) {
      return ["ROLE_EXECUTING", "TOOL_EXECUTION", "EVIDENCE_CREATED",
              "STEP_COMPLETED"].indexOf(e.kind) !== -1;
    }).pop();
    var lastActivity = "—";
    if (lastEvent) {
      var p = lastEvent.payload || {};
      lastActivity = ({
        ROLE_EXECUTING: (ROLE_LABELS[p.role] || p.role) + " يعمل",
        TOOL_EXECUTION: "أداة " + (p.tool || "؟"),
        EVIDENCE_CREATED: "دليل جديد",
        STEP_COMPLETED: "خطوة اكتملت",
      })[lastEvent.kind] || lastEvent.kind;
    }
    rows.appendChild(envRow("آخر نشاط", lastActivity));
    card.appendChild(rows);

    var buttons = el("div", "pl-actions");
    var details = el("button", "pl-btn", "التفاصيل");
    var stop = el("button", "pl-btn danger", "■ إيقاف التنفيذ");
    buttons.appendChild(details); buttons.appendChild(stop);
    card.appendChild(buttons);
    var feedback = el("div", "pl-feedback"); feedback.hidden = true;
    card.appendChild(feedback);

    details.addEventListener("click", function () {
      var tech = card.querySelector(".pl-tech-body");
      if (tech) tech.hidden = !tech.hidden;
    });
    stop.addEventListener("click", function () {
      stop.disabled = true;
      stop.textContent = "…جارٍ طلب الإيقاف";
      feedback.hidden = false;
      feedback.className = "pl-feedback loading";
      feedback.textContent = "طلب الإيقاف أُرسل — يُكرم عند أقرب حدّ آمن";
      Hub.fetchJSON("/api/projects/" + state.id + "/stop", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reason: "زر الإيقاف من بطاقة التنفيذ" }),
      }).then(function (out) {
        if (out.ok) {
          feedback.className = "pl-feedback ok";
          feedback.textContent = "قُبل الإيقاف — الحالة محفوظة والاستئناف متاح";
        } else {
          stop.disabled = false;
          stop.textContent = "■ إيقاف التنفيذ";
          feedback.className = "pl-feedback err";
          feedback.textContent = "تعذر الإيقاف: " +
            ((out.j && out.j.detail) || "");
        }
      }, function () {
        stop.disabled = false;
        stop.textContent = "■ إيقاف التنفيذ";
        feedback.className = "pl-feedback err";
        feedback.textContent = "تعذر الوصول — أعد المحاولة";
      });
    });

    card.appendChild(renderTechDetails({
      job: job ? {
        id: job.id, status: job.status, worker_id: job.worker_id,
        attempt: job.attempt, checkpoint_id: job.checkpoint_id,
        tick_count: job.tick_count,
      } : null,
      project_status: state.status,
    }));
    wrap.flow.appendChild(card);
    return { row: wrap.row, card: card };
  }

  /* بطاقة الحجب الصادقة (§27+§17): سبب مفهوم + أزرار علاج + تفاصيل */
  function renderBlockedCard(state, actions) {
    var wrap = msgRow("assistant");
    var card = el("div", "pl-card pl-blocked");
    var title = el("div", "pl-title", "التنفيذ متوقف");
    card.appendChild(title);

    var gate = state.execution_gate || {};
    var reason = el("div", "pl-note");
    reason.dir = "auto";
    /* (013.1 §22+§17) السبب من مصدره الفعلي: انقطاع عامل/إيقاف
     * مالك/بوابة توفير — لا نص عامًا يخفي الحقيقة */
    var job = state.job || {};
    var env = state.environment || {};
    if (job.status === "INTERRUPTED") {
      reason.textContent = "انقطع العامل (فقدان نبضة أو إعادة تشغيل) "
        + "— لا شيء ضاع؛ الاستئناف من آخر checkpoint بنفس الوظيفة."
        + (job.last_error ? " (" + job.last_error.slice(0, 140) + ")"
           : "");
    } else if (state.status === "PAUSED") {
      reason.textContent = "التنفيذ متوقف مؤقتًا بأمان — الاستئناف من "
        + "آخر checkpoint بقرارك.";
    } else {
      /* (013.2 §7) السبب من الحالة القانونية المتماسكة — لا نص
       * عام يحمل كلمة «جاهزة» تحت عنوان توقف */
      var runtime = env.runtime_state || {};
      var coherent = runtime.coherent || {};
      reason.textContent = gate.reason
        || coherent.detail
        || coherent.label
        || "التنفيذ متوقف — راجع بطاقة البيئة أعلاه للسبب والعلاج.";
    }
    card.appendChild(reason);

    /* (013.1 §22) الفشل منظم: ما فشل/لماذا/ما اكتُشف/ما يمكن فعله/
     * الحالة الحالية — كلها من اللقطة الدائمة لا من نص عام */
    var facts = el("div", "pl-env-rows");
    if (env.host && env.host.platform) {
      facts.appendChild(envRow("المضيف المكتشف", env.host.platform));
    }
    if (env.policy_label) {
      facts.appendChild(envRow("السياسة", env.policy_label));
    }
    if (env.requirement) {
      var reqRow = el("div", "pl-env-row");
      reqRow.appendChild(el("span", "pl-env-k", "المطلوب: "));
      var reqText = el("span", "pl-env-v", env.requirement);
      reqText.dir = "auto";
      reqRow.appendChild(reqText);
      facts.appendChild(reqRow);
    }
    facts.appendChild(envRow("الحالة الحالية",
      (STATUS_LABELS[state.status] || state.status) +
      " — التنفيذ متوقف بأمان، لا شيء ضاع"));
    card.appendChild(facts);

    var buttons = el("div", "pl-actions");
    /* (013.1 §17) الاستئناف قرار المالك الصريح من الواجهة — الوظيفة
     * المتوقفة (PAUSED/INTERRUPTED) تستأنف بنفس صفها من آخر
     * checkpoint؛ لا يظهر الزر إلا حيث الاستئناف مشروع فعلًا. */
    var resumable = state.status === "PAUSED"
      || (state.job && state.status !== "BLOCKED"
          && ["INTERRUPTED", "PAUSED"].indexOf(
              state.job.status) !== -1);
    if (resumable) {
      var resumeBtn = el("button", "pl-btn primary",
                         "▶ استئناف التنفيذ");
      resumeBtn.addEventListener("click", function () {
        resumeBtn.disabled = true;
        resumeBtn.textContent = "…جارٍ الاستئناف";
        Hub.fetchJSON("/api/projects/" + state.id + "/resume",
                      { method: "POST" })
          .then(function (out) {
            if (out.ok && (out.j || {}).launch) {
              resumeBtn.textContent = "استُؤنف — نفس الوظيفة تُكمل";
            } else {
              resumeBtn.disabled = false;
              resumeBtn.textContent = "▶ استئناف التنفيذ";
            }
          }, function () {
            resumeBtn.disabled = false;
            resumeBtn.textContent = "▶ استئناف التنفيذ";
          });
      });
      buttons.appendChild(resumeBtn);
    }
    var provision = el("button", "pl-btn primary",
      "تجهيز بيئة التنفيذ");
    var recheck = el("button", "pl-btn", "إعادة الفحص");
    buttons.appendChild(provision); buttons.appendChild(recheck);
    card.appendChild(buttons);

    var progress = el("div", "pl-progress"); progress.hidden = true;
    card.appendChild(progress);

    function runProvision() {
      provision.disabled = true;
      progress.hidden = false; progress.textContent = "جاري تجهيز البيئة…";
      Hub.fetchJSON("/api/environment/provision", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          policy: (state.environment || {}).policy
            || "STRICT_ISOLATED",
        }),
      })
        .then(function (out) {
          if (!out.ok) {
            progress.textContent = "تعذر تجهيز البيئة: " +
              ((out.j && out.j.reason) || out.j || "");
            provision.disabled = false;
            return;
          }
          var result = out.j || {};
          if (result.state === "READY") {
            progress.textContent = "جاري فحص العزل…";
            runRecheck("بيئة التنفيذ جاهزة");
          } else {
            var reasonText = result.reason ||
              "التجهيز غير متاح في هذه البيئة";
            var requirement = result.requirement
              ? " — المطلوب: " + result.requirement : "";
            progress.textContent = reasonText + requirement;
            provision.disabled = false;
          }
        }, function () {
          progress.textContent = "تعذر الوصول لخدمة التجهيز — أعد المحاولة";
          provision.disabled = false;
        });
    }

    function runRecheck(doneText) {
      recheck.disabled = true;
      progress.hidden = false;
      progress.textContent = doneText || "جاري اختبار التنفيذ…";
      Hub.fetchJSON(actions.recheckUrl, { method: "POST" })
        .then(function (out) {
          recheck.disabled = false;
          if (!out.ok) {
            progress.textContent = "تعذر إعادة الفحص: " +
              ((out.j && out.j.detail) || "");
            return;
          }
          var j = out.j || {};
          if (j.preflight && j.preflight.verdict === "PASS") {
            progress.textContent =
              "البيئة جاهزة — بدأ التنفيذ تلقائيًا (بلا إعادة اعتماد)";
            progress.classList.add("ok");
          } else {
            var blocked = (j.preflight && j.preflight.blocked) || [];
            progress.textContent = "ما زال التنفيذ متوقفًا: " +
              (blocked.map(function (b) { return b.capability_id; })
                .join("، ") || "أسباب غير معروفة");
          }
        }, function () {
          recheck.disabled = false;
          progress.textContent = "تعذر الوصول — أعد المحاولة";
        });
    }

    provision.addEventListener("click", runProvision);
    recheck.addEventListener("click", function () { runRecheck(null); });

    // التفاصيل التقنية (§27): النص الخام تحت الطي — ليس في المسار
    card.appendChild(renderTechDetails({
      gate_state: gate.state, reason: gate.reason,
      required: gate.required, owner_action: gate.owner_action,
      job_waiting: state.job && state.job.waiting_kind,
    }));
    wrap.flow.appendChild(card);
    return { row: wrap.row, card: card };
  }

  /* النشاط الحي: أدوار وأدوات ومتصفح (§22+§28) */
  function renderActivityCard() {
    var wrap = msgRow("assistant");
    var card = el("div", "pl-card pl-activity");
    card.appendChild(el("div", "pl-title", "النشاط الحي"));
    var list = el("div", "pl-activity-list");
    card.appendChild(list);
    card.appendChild(renderTechDetails({}, "pl-tech-activity"));
    wrap.flow.appendChild(card);
    return { row: wrap.row, card: card, list: list };
  }

  var ACTIVITY_LIMIT = 24;

  /* (013.5 §J) رموز الانتظار الصادقة — الواجهة تقول ما تنتظره فعلًا.
   * قبل هذا: «توليد الخطة جارٍ» بلا سقف ولا سبب ولا فرق بين «نتصل
   * بالمزود» و«المزود صامت» — فبقي المالك ‏17992ث أمام شاشة لا تفسّر
   * شيئًا. الآن كل حالة لها رمز ونص صادق وسقف معلن. */
  var WAIT_PHASE_LABELS = {
    QUEUED: "في الطابور — لم يبدأ الاستدعاء بعد",
    CONNECTING: "جارٍ الاتصال بالمزود وإرسال الطلب",
    /* 013.5 §D/§J: النموذج المُهيَّأ استدلالي — يبثّ reasoning_content
     * قبل أول حرف إجابة. هذا ليس صمتًا: المزود يعمل ويُقاس. */
    REASONING: "المزود يستدل الآن — وصل نشاط حقيقي ولم تبدأ الإجابة بعد",
    AWAITING_PROVIDER: "بانتظار رد المزود — الاستدعاء مُرسَل ولم يصل نشاط",
    PAUSED: "موقوف بقرار المالك",
    DONE: "اكتمل",
    FAILED: "فشل مصنَّف",
    INTERRUPTED: "انقطع العامل المولِّد",
    CANCELLED: "أُلغي",
  };

  function fmtSeconds(value) {
    var n = Number(value);
    if (!isFinite(n) || n < 0) return "—";
    if (n < 60) return n + " ث";
    var minutes = Math.floor(n / 60);
    var seconds = n % 60;
    if (minutes < 60) return minutes + " د " + seconds + " ث";
    return Math.floor(minutes / 60) + " س " + (minutes % 60) + " د";
  }

  function remaining(deadline) {
    if (!deadline) return null;
    var target = new Date(deadline).getTime();
    if (isNaN(target)) return null;
    return Math.max(0, Math.round((target - Date.now()) / 1000));
  }

  /* (013.4 §3+§36 + 013.5 §D/§J) بطاقة التخطيط الحي — ماذا ينتظر
   * حرفيًا، بنبضتين منفصلتين وسقف زمن جدار معلن. */
  function renderPlanningCard(state, actions) {
    var planning = state.planning || {};
    var detail = planning.detail || {};
    var waiting = planning.waiting_for || {};
    var wrap = msgRow("assistant");
    var card = el("div", "pl-card pl-plan-live");

    if (planning.active) {
      card.classList.add("live");
      var phase = planning.wait_phase || "CONNECTING";
      var head = el("div", "pl-title");
      head.appendChild(el("span", "pl-exec-dot", "●"));
      head.appendChild(el("span", null, " توليد الخطة جارٍ"));
      var badge = el("span", "pl-wait-phase", phase);
      head.appendChild(badge);
      card.appendChild(head);

      var phaseText = el("div", "pl-objective pl-wait-text");
      phaseText.dir = "auto";
      phaseText.textContent = WAIT_PHASE_LABELS[phase] ||
        "حالة انتظار معلنة: " + phase;
      card.appendChild(phaseText);

      var rows = el("div", "pl-env-rows");
      function prow(label, value) {
        if (value === null || value === undefined || value === "") return;
        var row = el("div", "pl-env-row");
        row.appendChild(el("span", "pl-env-k", label + ": "));
        var cell = el("span", "pl-env-v", String(value));
        cell.dir = "auto";
        row.appendChild(cell);
        rows.appendChild(row);
      }
      prow("المزود", waiting.provider || detail.provider);
      prow("النموذج", waiting.model || detail.model);
      prow("الطلب", waiting.request_id || detail.request_id);
      prow("المحاولة", waiting.attempt);
      prow("مضى على الجلسة", fmtSeconds(detail.elapsed_s));
      // (§D) النبضتان منفصلتان — لا خلط بين «العملية حيّة» و«المزود يعمل»
      prow("آخر نشاط مزود حقيقي",
        fmtSeconds(detail.silence_s) + " مضت");
      prow("آخر نبضة عملية",
        detail.heartbeat_at
          ? new Date(detail.heartbeat_at).toLocaleTimeString("ar")
          : "—");
      var left = remaining(detail.hard_deadline_at);
      prow("السقف الصلب المتبقي",
        left === null ? "غير معلن"
          : fmtSeconds(left) + " (حد " +
            fmtSeconds(detail.hard_timeout_s) + ")");
      card.appendChild(rows);

      var note = el("div", "pl-note",
        "قاعدة الصدق: نبضة العملية وحدها لا تُطيل الانتظار. إن صمت " +
        "المزود أو تجاوز السقف الصلب أو مات العامل، تُحسم الجلسة " +
        "بحالة مصنَّفة (MODEL_TIMEOUT / PLANNING_INTERRUPTED) وتظهر " +
        "هنا ببطاقة الفشل مع زر إعادة — لا انتظار أبدي.");
      card.appendChild(note);
    } else if (planning.state === "FAILED" ||
               planning.state === "INTERRUPTED") {
      card.classList.add("error");
      card.appendChild(el("div", "pl-title",
        "⚠ فشل توليد الخطة [" +
        (detail.error_class || planning.state) + "]"));
      var reason = el("div", "pl-objective");
      reason.dir = "auto";
      reason.textContent = detail.error_detail ||
        "انقطع التوليد — العملية المولّدة ماتت";
      card.appendChild(reason);
      var facts = el("div", "pl-env-rows");
      function frow(label, value) {
        if (value === null || value === undefined || value === "") return;
        var row = el("div", "pl-env-row");
        row.appendChild(el("span", "pl-env-k", label + ": "));
        var cell = el("span", "pl-env-v", String(value));
        cell.dir = "auto";
        row.appendChild(cell);
        facts.appendChild(row);
      }
      frow("المزود", detail.provider || waiting.provider);
      frow("النموذج", detail.model || waiting.model);
      frow("آخر طلب", detail.request_id);
      frow("المحاولات", detail.attempt);
      frow("انتهت", detail.finished_at
        ? new Date(detail.finished_at).toLocaleString("ar") : "");
      if (facts.children.length) card.appendChild(facts);
      if (actions && actions.retryUrl) {
        var retry = el("button", "pl-btn primary", "↻ إعادة المحاولة");
        retry.addEventListener("click", function () {
          retry.disabled = true;
          retry.textContent = "…جارٍ الطلب";
          Hub.fetchJSON(actions.retryUrl, { method: "POST" })
            .then(function (out) {
              if (!out.ok) {
                retry.disabled = false;
                retry.textContent = "تعذر — أعد المحاولة";
                return;
              }
              if (window.HubProjects) window.HubProjects.reconcile();
            });
        });
        card.appendChild(retry);
      }
    } else {
      return { row: null };
    }
    wrap.flow.appendChild(card);
    return { row: wrap.row };
  }

  function activityLine(kind, payload) {
    var line = el("div", "pl-act");
    var icon = el("span", "pl-act-icon");
    var text = el("span", "pl-act-text");
    text.dir = "auto";
    if (kind === "ROLE_EXECUTING") {
      icon.textContent = "●";
      line.className += " role";
      text.textContent = (ROLE_LABELS[payload.role] || payload.role) +
        " يعمل الآن" + (payload.objective
          ? " — " + String(payload.objective).slice(0, 90) : "");
    } else if (kind === "TOOL_EXECUTION") {
      var phase = { started: "بدء", succeeded: "نجح", failed: "فشل" }[
        payload.phase] || payload.phase;
      icon.textContent = payload.tool === "browser" ? "🌐" : "⚙";
      text.textContent = "أداة " + (payload.tool || "؟") + " — " + phase +
        (payload.summary ? " · " + String(payload.summary).slice(0, 90) : "");
      if (payload.phase === "failed") line.className += " err";
    } else if (kind.indexOf("BROWSER_") === 0) {
      icon.textContent = browserIcon(kind);
      text.textContent = browserText(kind, payload);
    } else if (kind === "EVIDENCE_CREATED") {
      icon.textContent = "📎";
      text.textContent = "دليل جديد" +
        (payload.files ? " — " + payload.files.slice(0, 3).join("، ") : "");
    } else if (kind === "AUDIT_COMPLETED") {
      icon.textContent = "🔍";
      text.textContent = "تدقيق — الحكم: " + (payload.verdict || "—");
    } else if (kind === "CHECKPOINT_CREATED") {
      icon.textContent = "💾";
      text.textContent = "نقطة حفظ — الاستئناف متاح من هنا";
    } else if (kind === "JOB_WAITING") {
      icon.textContent = "⏸";
      line.className += " waiting";
      text.textContent = "الوظيفة تنتظر بأمان: " +
        (payload.waiting_kind || "") +
        (payload.detail && payload.detail.summary
          ? " — " + String(payload.detail.summary).slice(0, 110) : "");
    } else if (kind === "RETRY_REQUESTED") {
      icon.textContent = "↻";
      text.textContent = "إعادة محاولة — " + (payload.decision || "");
    } else if (kind === "PLANNING_STARTED") {
      icon.textContent = "🧭";
      text.textContent = "بدأ توليد الخطة" +
        (payload.reason ? " — " + payload.reason : "");
    } else if (kind === "PLAN_GENERATING") {
      icon.textContent = "⏳";
      text.textContent = "استدعاء نموذج التخطيط" +
        (payload.model ? " — " + payload.model : "");
    } else if (kind === "MODEL_CALL_STARTED") {
      icon.textContent = "⏳";
      text.textContent = "طلب النموذج بدأ — " +
        (payload.request_id || "");
    } else if (kind === "MODEL_CALL_COMPLETED") {
      icon.textContent = "✓";
      text.textContent = "رد النموذج وصل" +
        (payload.duration_ms
          ? " (" + Math.round(payload.duration_ms / 100) / 10 + "ث)" : "");
    } else if (kind === "MODEL_CALL_FAILED") {
      icon.textContent = "⚠";
      line.className += " err";
      text.textContent = "فشل استدعاء النموذج [" +
        (payload.error_class || "؟") + "]";
    } else if (kind === "PLAN_CREATED") {
      icon.textContent = "📋";
      text.textContent = "وُلدت الخطة — " +
        (payload.phases || "؟") + " مرحلة، تنتظر اعتمادك";
    } else if (kind === "PLANNING_FAILED") {
      icon.textContent = "⚠";
      line.className += " err";
      text.textContent = "فشل توليد الخطة [" +
        (payload.error_class || "؟") + "] — الإعادة متاحة";
    } else if (kind === "PLANNING_INTERRUPTED") {
      icon.textContent = "⚠";
      line.className += " err";
      text.textContent = "انقطع توليد الخطة — ماتت العملية المولّدة";
    } else if (kind === "PLANNING_RETRY") {
      icon.textContent = "↻";
      text.textContent = "إعادة آلية للتوليد — جلسة جديدة";
    } else if (kind === "OWNER_STOP_REQUESTED") {
      icon.textContent = "■";
      text.textContent = "طلبت الإيقاف النهائي — يُكرَّم عند أقرب حدّ آمن";
    } else if (kind === "PROJECT_STOPPED") {
      icon.textContent = "■";
      text.textContent = "أُوقف المشروع نهائيًا — كل شيء محفوظ";
    } else if (kind === "PROJECT_ARCHIVED") {
      icon.textContent = "🗂";
      text.textContent = "أُرشف المشروع — قابل للاسترجاع دائمًا";
    } else if (kind === "PROJECT_RESTORED") {
      icon.textContent = "📂";
      text.textContent = "استُرجع المشروع من الأرشيف";
    } else if (kind === "WORKFLOW_DIAGNOSED") {
      icon.textContent = "🔍";
      text.textContent = "تشخيص سير العمل — " + (payload.kind || "");
    } else if (kind === "STEP_STARTED") {
      icon.textContent = "●";
      text.textContent = "بدأت خطوة" +
        (payload.objective
          ? ": " + String(payload.objective).slice(0, 80) : "");
    } else if (kind === "STEP_COMPLETED") {
      icon.textContent = "✓";
      text.textContent = "اكتملت خطوة" +
        (payload.attempts ? " (بعد " + payload.attempts + " محاولة)" : "");
    } else if (kind === "EXECUTION_COMPLETED") {
      icon.textContent = "✓";
      text.textContent = "اكتمل تنفيذ";
    } else if (kind === "EXECUTION_FAILED") {
      icon.textContent = "⚠";
      line.className += " err";
      text.textContent = "فشل تنفيذ" +
        (payload.reason
          ? " — " + String(payload.reason).slice(0, 90) : "");
    } else {
      return null;
    }
    line.appendChild(icon); line.appendChild(text);
    return line;
  }

  function browserIcon(kind) {
    if (kind === "BROWSER_NAVIGATE" || kind === "BROWSER_PAGE_LOADED")
      return "🌐";
    if (kind === "BROWSER_CLICK") return "🖱";
    if (kind === "BROWSER_TYPE") return "⌨";
    if (kind === "BROWSER_SCREENSHOT") return "📸";
    if (kind === "BROWSER_EXTRACT") return "📄";
    if (kind === "BROWSER_DOWNLOAD") return "⬇";
    if (kind === "BROWSER_SESSION_CREATED") return "🔓";
    if (kind === "BROWSER_SESSION_CLOSED") return "🔒";
    return "🌐";
  }

  function browserText(kind, payload) {
    var map = {
      BROWSER_SESSION_CREATED: "فتح جلسة متصفح",
      BROWSER_PAGE_LOADED: "تحميل الصفحة",
      BROWSER_CLICK: "نقر عنصر",
      BROWSER_TYPE: "إدخال نص",
      BROWSER_SCREENSHOT: "التقاط لقطة شاشة",
      BROWSER_EXTRACT: "استخلاص محتوى",
      BROWSER_DOWNLOAD: "تنزيل ملف",
      BROWSER_SESSION_CLOSED: "إغلاق جلسة المتصفح",
      BROWSER_SESSION_INTERRUPTED: "انقطاع جلسة المتصفح",
    };
    var base = map[kind] || kind;
    if (kind === "BROWSER_NAVIGATE" || kind === "BROWSER_PAGE_LOADED") {
      return base + (payload.url ? " ↳ " +
        String(payload.url).slice(0, 80) : "");
    }
    if (kind === "BROWSER_SCREENSHOT" && payload.bytes) {
      return base + " (" + payload.bytes + " بايت)";
    }
    return base + (payload.summary ? " — " +
      String(payload.summary).slice(0, 70) : "");
  }

  /* بطاقة الختام: مرشح ← تحقق المالك (§51) */
  function renderVerifyCard(state, actions) {
    var wrap = msgRow("assistant");
    var card = el("div", "pl-card pl-verify");
    if (state.status === "VERIFIED") {
      card.className += " done";
      card.appendChild(el("div", "pl-title",
        "المشروع مُتحقق — VERIFIED ✓"));
      card.appendChild(el("div", "pl-note",
        "قرار التحقق النهائي كان لك، وكل خطوة قبله بأدلة ميكانيكية."));
    } else {
      card.appendChild(el("div", "pl-title", "المشروع مرشح للإكمال"));
      card.appendChild(el("div", "pl-note",
        "اكتمل التنفيذ والتدقيق النهائي. التحقق النهائي قرار المالك وحده."));
      var verify = el("button", "pl-btn primary", "التحقق النهائي ✓");
      var feedback = el("div", "pl-feedback"); feedback.hidden = true;
      verify.addEventListener("click", function () {
        verify.disabled = true; verify.textContent = "جاري التحقق…";
        Hub.fetchJSON(actions.verifyUrl, { method: "POST" })
          .then(function (out) {
            if (out.ok) {
              feedback.hidden = false;
              feedback.className = "pl-feedback ok";
              feedback.textContent = "تم التحقق — VERIFIED";
            } else {
              verify.disabled = false;
              verify.textContent = "التحقق النهائي ✓";
              feedback.hidden = false;
              feedback.className = "pl-feedback err";
              feedback.textContent = "تعذر التحقق: " +
                ((out.j && out.j.detail) || "");
            }
          }, function () {
            verify.disabled = false;
            feedback.textContent = "تعذر الوصول — أعد المحاولة";
            feedback.hidden = false;
            feedback.className = "pl-feedback err";
          });
      });
      card.appendChild(verify);
      card.appendChild(feedback);
    }
    wrap.flow.appendChild(card);
    return { row: wrap.row, card: card };
  }

  /* التفاصيل التقنية المطوية (§9+§29): الخام ليس في المسار الرئيسي */
  function renderTechDetails(data, extraClass) {
    var wrap = el("div", "pl-tech " + (extraClass || ""));
    var toggle = el("button", "pl-tech-toggle", "التفاصيل التقنية ▾");
    var body = el("pre", "pl-tech-body");
    body.dir = "ltr";
    body.hidden = true;
    try { body.textContent = JSON.stringify(data, null, 1); }
    catch (e) { body.textContent = String(data); }
    toggle.addEventListener("click", function () {
      body.hidden = !body.hidden;
      toggle.textContent = body.hidden
        ? "التفاصيل التقنية ▾" : "التفاصيل التقنية ▴";
    });
    wrap.appendChild(toggle); wrap.appendChild(body);
    return wrap;
  }

  /* ---------- تركيب المشهد الكامل من اللقطة ---------- */

  function renderProjectScene(container, state, actions) {
    container.textContent = "";

    // الهدف رسالة المالك (§8: المحادثة أولًا)
    var objective = msgRow("owner");
    objective.flow.appendChild(el("div", "pl-objective-msg",
      state.objective || ""));
    container.appendChild(objective.row);

    // بطاقة المشروع (§10): الحالة الحية + خط المراحل — كل مؤشر
    // مرتبط بحالة حقيقية من اللقطة والأحداث
    container.appendChild(renderProjectCard(state).row);

    if (state.plan) {
      var planCard = renderPlanCard(state.plan, state);
      container.appendChild(planCard.row);
    }

    // (013.4 §3+§36) بطاقة التخطيط الحي — قبل أي اعتماد: ماذا ينتظر
    // حرفيًا (مزود/نموذج/طلب/مضي)، والفشل مصنّفه مع زر الإعادة
    var planningCard = renderPlanningCard(state, actions);
    if (planningCard && planningCard.row) {
      container.appendChild(planningCard.row);
    }

    if (state.status === "AWAITING_OWNER_APPROVAL" ||
        (state.gates || []).some(function (g) {
          return g.status === "PENDING";
        })) {
      var approval = renderApprovalCard(state, actions);
      if (approval) container.appendChild(approval.row);
    }

    // (013.1 §18) بطاقة بيئة التنفيذ — دائمًا بعد الاعتماد: جاهزة
    // أو غير جاهزة بالمتطلب الحرفي، لا صمت ولا وعود
    if (state.plan) {
      var envCard = renderEnvironmentCard(state, actions);
      if (envCard) container.appendChild(envCard.row);
    }

    // (013.1 §21) بطاقة التنفيذ الحية — أثناء العمل الفعلي فقط؛
    // وظيفة منقطعة/متوقفة ليست «جارٍ» أبدًا (لا حالة كاذبة §12)
    var jobHalted = state.job && ["INTERRUPTED", "PAUSED", "STOPPED",
                                  "FAILED"].indexOf(
        state.job.status) !== -1;
    var execRunning = !jobHalted && (
      ["RUNNING", "REVISING"].indexOf(state.status) !== -1
      || (state.job && ["RUNNING", "RETRYING"].indexOf(
          state.job.status) !== -1));
    if (execRunning && state.plan) {
      container.appendChild(renderExecutionCard(state, actions).row);
    }

    // (013.1 §17) بطاقة التوقف/الاستئناف: BLOCKED وPAUSED والوظيفة
    // المنقطعة (انقطاع عامل/إعادة تشغيل) — كلها تستأنف بنفس الصف
    if (state.status === "BLOCKED" || state.status === "PAUSED"
        || jobHalted) {
      container.appendChild(
        renderBlockedCard(state, actions).row);
    }

    if (["RUNNING", "REVISING"].indexOf(state.status) !== -1 ||
        (state.job && ["RUNNING", "RETRYING", "WAITING_CAPABILITY",
                       "WAITING_WORKER", "WAITING_GATE"]
          .indexOf(state.job.status) !== -1)) {
      var activity = renderActivityCard();
      container.appendChild(activity.row);
      (state.events || []).slice(-ACTIVITY_LIMIT).forEach(function (e) {
        var line = activityLine(e.kind, e.payload || {});
        if (line) activity.list.appendChild(line);
      });
    }

    if (state.status === "COMPLETED" || state.status === "VERIFIED") {
      container.appendChild(renderVerifyCard(state, actions).row);
    }

    var footer = el("div", "pl-footer");
    footer.appendChild(renderTechDetails(state.job || {
      project_id: state.id, status: state.status,
    }));
    footer.appendChild(el("div", "pl-footer-meta",
      "المعرف: #" + state.id + " · آخر حدث: " +
      (state.last_event_id || 0)));
    container.appendChild(footer);
  }

  /* ---------- التحديث الحي: حدث واحد يحدّث المشهد بلا إعادة بناء ---------- */

  var REFRESH_KINDS = [
    "PLAN_CREATED", "PLAN_APPROVAL_REQUIRED", "PLAN_APPROVED",
    "PREFLIGHT_STARTED", "PREFLIGHT_PASS", "PREFLIGHT_BLOCKED",
    "PREFLIGHT_RECHECKED", "ENVIRONMENT_READY", "EXECUTION_OPENED",
    "GATE_AUTO_RESOLVED", "OWNER_GATE_RESOLVED", "PROJECT_PAUSED",
    "PROJECT_RESUMED", "PROJECT_COMPLETION_CANDIDATE",
    "PROJECT_VERIFIED", "PROJECT_STOPPED", "EXECUTION_BLOCKED",
    "JOB_CREATED", "JOB_QUEUED", "JOB_STARTED", "JOB_WAITING",
    "JOB_PAUSED", "JOB_COMPLETED", "JOB_INTERRUPTED", "JOB_RESUMED",
    "JOB_RECOVERY_ASSESSED",
    // (013.2 §12) أحداث التجهيز والنبضة تحدّث بطاقة البيئة حيًّا
    "PROVISIONING_STARTED", "PROVISIONING_COMPLETED",
    "PROVISIONING_FAILED", "PROVISIONING_UNAVAILABLE",
    "ENVIRONMENT_HEARTBEAT", "WORKER_READY",
    // (013.4 §1) أحداث التخطيط الخلفي — كل انتقال يحدّث المشهد
    "PLANNING_STARTED", "PLAN_GENERATING", "PLANNING_FAILED",
    "PLANNING_INTERRUPTED", "PLANNING_RETRY", "STEP_STARTED",
    "STEP_COMPLETED", "PHASE_STARTED", "PHASE_COMPLETED",
    "EXECUTION_STARTED", "EXECUTION_COMPLETED", "EXECUTION_FAILED",
    "EVIDENCE_CREATED", "AUDIT_COMPLETED", "OWNER_STOP_REQUESTED",
    "PROJECT_ARCHIVED", "PROJECT_RESTORED", "WORKFLOW_DIAGNOSED",
  ];

  function isSceneChange(kind) {
    return REFRESH_KINDS.indexOf(kind) !== -1;
  }

  window.ProjectLive = {
    renderProjectScene: renderProjectScene,
    activityLine: activityLine,
    isSceneChange: isSceneChange,
    ACTIVITY_LIMIT: ACTIVITY_LIMIT,
    STATUS_LABELS: STATUS_LABELS,
    ROLE_LABELS: ROLE_LABELS,
    renderTechDetails: renderTechDetails,
    // (013.5 §N) تفاصيل الخطة المهيكلة قابلة لإعادة الاستخدام خارج المشهد
    renderPlanCard: renderPlanCard,
    planSection: planSection,
    msgRow: msgRow,
    el: el,
  };
})();
