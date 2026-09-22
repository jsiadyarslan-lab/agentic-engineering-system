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

  /* البطاقة الأم: المشروع + خط الزمن المرحلي الحي (§10) */
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

    // خط الزمن المرحلي (§10+§12): كل مؤشر مرتبط بحالة حقيقية
    card.appendChild(renderStages(state));
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

  function renderStages(state) {
    var seen = {};
    (state.events || []).forEach(function (e) { seen[e.kind] = true; });
    var approved = state.plan && state.plan.approved_by_owner;
    var blocked = state.status === "BLOCKED";
    var stages = [
      { label: "الهدف", done: true },
      { label: "تحليل المتطلبات", done: !!(state.plan || seen.PLAN_CREATED) },
      { label: "الخطة", done: !!(state.plan || seen.PLAN_CREATED) },
      { label: "اعتماد المالك", done: !!approved,
        waiting: state.status === "AWAITING_OWNER_APPROVAL" },
      { label: "فحص البيئة",
        done: !!(seen.PREFLIGHT_PASS || seen.ENVIRONMENT_READY),
        active: !!(seen.PREFLIGHT_STARTED && !seen.PREFLIGHT_PASS
                   && !blocked) },
      { label: "التنفيذ", done: !!(seen.PROJECT_COMPLETION_CANDIDATE),
        active: state.status === "RUNNING" },
      { label: "جمع الأدلة", done: !!(state.evidence || []).length,
        active: state.status === "RUNNING" },
      { label: "التدقيق", done: !!(state.audits || []).length },
      { label: "التحقق", done: state.status === "VERIFIED",
        waiting: state.status === "COMPLETED" },
    ];
    var wrap = el("div", "pl-stages");
    stages.forEach(function (stage) {
      var mark = stageMark(stage.done, stage.active);
      var item = el("div", "pl-stage " + mark.cls +
                    (stage.waiting && !stage.done ? " waiting" : ""));
      item.appendChild(el("span", "pl-stage-icon", mark.icon));
      item.appendChild(el("span", "pl-stage-label", stage.label));
      wrap.appendChild(item);
    });
    return wrap;
  }

  /* بطاقة الخطة (§11): المعلومات الجوهرية + تفاصيل مطوية */
  function renderPlanCard(plan) {
    if (!plan) return null;
    var wrap = msgRow("assistant");
    var card = el("div", "pl-card pl-plan");
    card.appendChild(el("div", "pl-title",
      "الخطة الرئيسية v" + plan.version));
    var meta = el("div", "pl-meta");
    meta.appendChild(el("span", null,
      (plan.phases || []).length + " مراحل"));
    if ((plan.assumptions || []).length) {
      meta.appendChild(el("span", null,
        plan.assumptions.length + " افتراضات"));
    }
    card.appendChild(meta);

    (plan.phases || []).slice(0, 3).forEach(function (phase) {
      var phaseEl = el("div", "pl-phase");
      phaseEl.appendChild(el("div", "pl-phase-title",
        phase.title || "مرحلة"));
      (phase.steps || []).slice(0, 3).forEach(function (step) {
        phaseEl.appendChild(el("div", "pl-step",
          "• " + (step.objective || "")));
      });
      if ((plan.phases || []).length > 3) {
        phaseEl.appendChild(el("div", "pl-more",
          "+" + (plan.phases.length - 3) + " مراحل إضافية في التفاصيل"));
      }
      card.appendChild(phaseEl);
    });

    card.appendChild(renderTechDetails({
      "plan_id": plan.id, "version": plan.version,
      "status": plan.status,
      "approved": plan.approved_by_owner ? "نعم" : "لا",
    }));
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
    var approve = el("button", "pl-btn primary", "اعتماد الخطة");
    if (gate.kind !== "PLAN_APPROVAL" && gate.kind !== "FINAL_VERIFICATION") {
      approve.textContent = "موافقة";
    }
    var reject = el("button", "pl-btn danger",
      gate.kind === "FINAL_VERIFICATION" ? "رفض" : "رفض / طلب تعديل");
    buttons.appendChild(approve); buttons.appendChild(reject);
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
      approve.disabled = true; reject.disabled = true;
      approve.textContent = text;
      feedback.hidden = false; feedback.className = "pl-feedback loading";
      feedback.textContent = text;
    }
    function setResult(ok, text, extra) {
      approve.disabled = false; reject.disabled = false;
      approve.textContent = "اعتماد الخطة";
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
        approve.disabled = false; reject.disabled = false;
      });
    });

    reject.addEventListener("click", function () {
      var note = window.prompt(
        "ما التعديل المطلوب؟ (يصل للنظام كتغذية راجعة لإعادة التخطيط)", "");
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
    });

    wrap.flow.appendChild(card);
    return { row: wrap.row, card: card, gate: gate };
  }

  /* بطاقة بيئة التنفيذ (013.1 §18) — عرض بسيط داخل تجربة المحادثة.
   *
   * ثلاث حالات صادقة فقط، لا رابعة:
   *   ⚙️ جاهزة   — الاسم والعزل والعامل ونبضته
   *   ⏳ تجهيز — تعرض أثناء التوفير (زر التجهيز يعمل فعليًا)
   *   ⚠️ غير جاهزة — المضيف المكتشف + المطلوب الحرفي + أزرار علاج
   * كل حقل من اللقطة الدائمة (state.environment) — لا تخمين محلي.
   */
  function renderEnvironmentCard(state, actions) {
    var env = state.environment;
    if (!env) return null;
    var wrap = msgRow("assistant");
    var card = el("div", "pl-card pl-env");
    var selected = env.selected;
    var job = state.job;

    if (selected && selected.status === "READY") {
      card.classList.add("ready");
      var head = el("div", "pl-title", "⚙ بيئة التنفيذ — جاهزة");
      card.appendChild(head);
      var rows = el("div", "pl-env-rows");
      rows.appendChild(envRow("البيئة", selected.name));
      rows.appendChild(envRow("العزل",
        selected.sandboxed ? "صارم (معزولة)" : "بلا عزل (معلن)"));
      rows.appendChild(envRow("الخلفية", selected.backend || "—"));
      if (job && job.worker_id) {
        rows.appendChild(envRow("العامل", job.worker_id +
          (job.heartbeat_age_s != null
            ? " — نبضة قبل " + Math.max(0, Math.round(job.heartbeat_age_s)) + "ث"
            : "")));
      }
      card.appendChild(rows);
    } else {
      card.classList.add("notready");
      var warn = el("div", "pl-title",
        "⚠ بيئة التنفيذ غير جاهزة");
      card.appendChild(warn);
      var reason = el("div", "pl-note");
      reason.dir = "auto";
      reason.textContent = env.requirement ||
        "لا بيئة تنفيذ جاهزة توافق سياسة المشروع.";
      card.appendChild(reason);
      var detected = el("div", "pl-env-detected");
      detected.appendChild(el("span", "pl-env-k", "المضيف المكتشف: "));
      detected.appendChild(el("span", "pl-env-v",
        (env.host && env.host.platform) || "—"));
      card.appendChild(detected);
      var policyLine = el("div", "pl-env-detected");
      policyLine.appendChild(el("span", "pl-env-k", "السياسة: "));
      policyLine.appendChild(el("span", "pl-env-v",
        env.policy_label || env.policy || "—"));
      card.appendChild(policyLine);

      var buttons = el("div", "pl-actions");
      var provision = el("button", "pl-btn primary", "تجهيز البيئة");
      var recheck = el("button", "pl-btn", "إعادة الفحص");
      buttons.appendChild(provision); buttons.appendChild(recheck);
      card.appendChild(buttons);
      var progress = el("div", "pl-feedback"); progress.hidden = true;
      card.appendChild(progress);

      provision.addEventListener("click", function () {
        provision.disabled = true;
        progress.hidden = false;
        progress.className = "pl-feedback loading";
        progress.textContent = "⏳ جاري تجهيز بيئة التنفيذ…";
        Hub.fetchJSON("/api/environment/provision", { method: "POST" })
          .then(function (out) {
            provision.disabled = false;
            if (!out.ok) {
              progress.className = "pl-feedback err";
              progress.textContent = "تعذر التجهيز: " +
                ((out.j && out.j.reason) || "");
              return;
            }
            var result = out.j || {};
            if (result.state === "READY") {
              progress.className = "pl-feedback ok";
              progress.textContent =
                "جاهزة — أعد الفحص لاستئناف التنفيذ بنفس الوظيفة";
            } else {
              progress.className = "pl-feedback err";
              progress.textContent = (result.reason || "تعذر التجهيز") +
                (result.requirement ? " — المطلوب: " + result.requirement : "");
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
              progress.textContent = "تعذر الفحص: " +
                ((out.j && out.j.detail) || "");
              return;
            }
            var j = out.j || {};
            if (j.preflight && j.preflight.verdict === "PASS") {
              progress.className = "pl-feedback ok";
              progress.textContent =
                "البيئة جاهزة — استؤنف التنفيذ تلقائيًا بنفس الوظيفة";
            } else {
              progress.className = "pl-feedback err";
              progress.textContent = "ما زالت غير جاهزة — " +
                (env.requirement || "راجع المتطلبات");
            }
          }, function () {
            recheck.disabled = false;
            progress.className = "pl-feedback err";
            progress.textContent = "تعذر الوصول — أعد المحاولة";
          });
      });
    }
    card.appendChild(renderTechDetails({
      policy: env.policy,
      satisfies_policy: env.satisfies_policy,
      host: env.host,
      selected: env.selected,
      requirement: env.requirement,
    }));
    wrap.flow.appendChild(card);
    return { row: wrap.row, card: card };
  }

  function envRow(key, value) {
    var row = el("div", "pl-env-row");
    row.appendChild(el("span", "pl-env-k", key + ": "));
    row.appendChild(el("span", "pl-env-v", value));
    return row;
  }

  /* بطاقة التنفيذ الحية (013.1 §21) — تتحدث تلقائيًا عبر المصالحات.
   *
   * ● التنفيذ جارٍ: الهدف/الحالة/البيئة/العامل/المرحلة/آخر نشاط
   * + [التفاصيل] [إيقاف التنفيذ] — الإيقاف صريح وحده يوقف (§19). */
  function renderExecutionCard(state, actions) {
    var job = state.job;
    var wrap = msgRow("assistant");
    var card = el("div", "pl-card pl-exec live");

    var head = el("div", "pl-title");
    var dot = el("span", "pl-exec-dot", "●");
    head.appendChild(dot);
    head.appendChild(el("span", null, " التنفيذ جارٍ"));
    card.appendChild(head);

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
    var envSel = env && env.selected;
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
      if (job.current_phase_id && (state.phases || []).length) {
        var phase = null;
        (state.phases || []).forEach(function (p) {
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
    if (job.status === "INTERRUPTED") {
      reason.textContent = "انقطع العامل (فقدان نبضة أو إعادة تشغيل) "
        + "— لا شيء ضاع؛ الاستئناف من آخر checkpoint بنفس الوظيفة."
        + (job.last_error ? " (" + job.last_error.slice(0, 140) + ")"
           : "");
    } else if (state.status === "PAUSED") {
      reason.textContent = "التنفيذ متوقف مؤقتًا بأمان — الاستئناف من "
        + "آخر checkpoint بقرارك.";
    } else {
      reason.textContent = gate.reason ||
        "بيئة التنفيذ غير جاهزة.";
    }
    card.appendChild(reason);

    /* (013.1 §22) الفشل منظم: ما فشل/لماذا/ما اكتُشف/ما يمكن فعله/
     * الحالة الحالية — كلها من اللقطة الدائمة لا من نص عام */
    var env = state.environment || {};
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
      Hub.fetchJSON("/api/environment/provision", { method: "POST" })
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
      var planCard = renderPlanCard(state.plan);
      container.appendChild(planCard.row);
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
    msgRow: msgRow,
    el: el,
  };
})();
