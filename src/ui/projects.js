/* Agentic Engineering System — واجهة المشاريع (007 + 011).
 * المشروع كيان أول: خطة رئيسية تُعتمد، حلقة ذاتية تعمل وتُرى لحظيًا،
 * مراحل وخطوات بحالات صادقة، بوابات مالك تُحل، وتحقق نهائي للمالك.
 *
 * (011 §1-§3) بوابة التنفيذ مفصولة عن قرار الاعتماد: بطاقة حالة
 * مشتقة (OPEN / APPROVED_BUT_BLOCKED مع السبب والمطلوب وإجراء
 * المالك) — لا رسالة غامضة عن بوابة مغلقة أبدًا. (§19) إعادة الفحص بعد
 * التوفير تفتح التنفيذ بلا إعادة اعتماد. (§21) تيار أحداث عام
 * يزامن الشريط والصفحة بلا refresh يدوي. (§26) سياسة التنفيذ قرار
 * مالك ظاهر.
 */
(function () {
  "use strict";

  if (!window.Hub) return;
  var Hub = window.Hub;
  var $ = Hub.$;
  var esc = Hub.esc;

  var view = $("project-view");
  var projectsList = $("projects-list");
  if (!view || !projectsList) return;

  var state = {
    projectId: null,
    streaming: false,
    eventsBuffer: []
  };

  var GATE_STATUS_LABELS = {
    PENDING: "تنتظر قرارك", APPROVED: "معتمدة", REJECTED: "مرفوضة",
    BLOCKED: "محجوبة — تنتظر توفيرًا", CANCELLED: "ملغاة",
    EXPIRED: "منتهية",
  };

  var POLICY_LABELS = {
    STRICT_ISOLATED: "عزل صارم",
    COMPATIBLE_LOCAL: "توافق محلي (بلا عزل)",
  };

  var STATUS_LABELS = {
    DRAFT: "مسودة", PLANNING: "توليد الخطة",
    AWAITING_OWNER_APPROVAL: "بانتظار اعتمادك",
    READY: "جاهز", RUNNING: "يعمل الآن", PAUSED: "متوقف مؤقتًا",
    BLOCKED: "محجوب — قرار مطلوب", REVISING: "مراجعة الخطة",
    COMPLETED: "مرشح للتحقق", VERIFIED: "مُتحقق",
    STOPPED: "موقوف", ESCALATED: "مُصعَّد",
    PLANNED: "مخططة", REVIEWING: "تحت المراجعة", FAILED: "فاشلة",
    PENDING: "بالانتظار"
  };

  var STATUS_CLASSES = {
    DRAFT: "", PLANNING: "run", AWAITING_OWNER_APPROVAL: "wait",
    READY: "ok", RUNNING: "run", PAUSED: "wait", BLOCKED: "bad",
    REVISING: "run", COMPLETED: "ok", VERIFIED: "ok", STOPPED: "bad",
    ESCALATED: "bad"
  };

  function statusBadge(status) {
    return '<span class="pj-badge ' + (STATUS_CLASSES[status] || "") + '">' +
      esc(STATUS_LABELS[status] || status) + "</span>";
  }

  function stepIcon(status) {
    return { COMPLETED: "✓", RUNNING: "◌", FAILED: "✕", BLOCKED: "⊘",
             PENDING: "□", READY: "□" }[status] || "□";
  }

  // ---------- التنقل بين المحادثة وعرض المشروع ----------

  function enterProjectMode() {
    document.body.classList.add("mode-project");
    // (الأمر 010 §15) جذر الصفحة السوداء: #project-view يحمل hidden
    // في HTML وقاعدة [hidden]{display:none!important} تتغلب على
    // body.mode-project .project-view{display:flex} غير المهمة —
    // فكان كل المحتوى مخفيًا. الحل من المصدر: إزالة hidden عند الدخول.
    view.hidden = false;
  }

  function exitProjectMode() {
    document.body.classList.remove("mode-project");
    view.hidden = true;
    state.projectId = null;
    if ((location.hash || "").indexOf("#/project/") === 0) {
      location.hash = "";
    }
    loadProjects();
  }

  // ---------- قائمة المشاريع (الشريط الجانبي) ----------

  function loadProjects() {
    Hub.fetchJSON("/api/projects").then(function (out) {
      if (!out.ok) {
        projectsList.innerHTML =
          '<div class="pj-empty">تعذر تحميل المشاريع — ' +
          '<button class="pj-retry" id="pj-list-retry">إعادة</button></div>';
        var retryBtn = document.getElementById("pj-list-retry");
        if (retryBtn) retryBtn.addEventListener("click", loadProjects);
        return;
      }
      var projects = out.j.projects || [];
      var html = "";
      if (!projects.length) {
        html = '<div class="pj-empty">لا مشاريع بعد — ابدأ مشروعك الأول</div>';
      }
      projects.forEach(function (p) {
        html += '<button class="pj-item' +
          (p.id === state.projectId ? " active" : "") +
          '" data-id="' + p.id + '">' +
          '<span class="pj-item-name">' + esc(p.name) + "</span>" +
          statusBadge(p.status) + "</button>";
      });
      projectsList.innerHTML = html;
      projectsList.querySelectorAll(".pj-item").forEach(function (btn) {
        btn.addEventListener("click", function () {
          openProject(parseInt(btn.getAttribute("data-id"), 10));
        });
      });
      document.dispatchEvent(new Event("hub:projects-loaded"));
    });
  }

  // ---------- فتح مشروع ----------

  function openProject(id) {
    if (state.projectId === id && !view.hidden
        && view.querySelector(".pj-head")) {
      return;   // تراجعي: نفس المشروع معروض بالفعل
    }
    state.projectId = id;
    enterProjectMode();
    if ((location.hash || "") !== "#/project/" + id) {
      location.hash = "#/project/" + id;   // توجيه دائم (010 §14)
    }
    render("جارٍ تحميل المشروع…");
    Hub.fetchJSON("/api/projects/" + id).then(function (out) {
      if (!out.ok) {
        renderError("تعذر تحميل المشروع #" + id,
          out.j && out.j.detail, function () { openProject(id); });
        return;
      }
      renderProject(out.j);
      loadProjects();
    }, function () {
      renderError("تعذر الوصول للخدمة", "تحقق من اتصال الخادم ثم أعد المحاولة",
        function () { openProject(id); });
    });
  }

  /** حالة خطأ كاملة (010 §31): السبب + إعادة المحاولة + عودة آمنة. */
  function renderError(title, detail, retryFn) {
    view.innerHTML = "";
    var box = el("div", "pj-error");
    box.appendChild(el("div", "pj-error-title", "⚠ " + title));
    if (detail) box.appendChild(el("div", "pj-error-detail", String(detail).slice(0, 300)));
    var actions = el("div", "pj-error-actions");
    var retry = el("button", "pv-btn primary", "إعادة المحاولة");
    retry.addEventListener("click", retryFn);
    var back = el("button", "pv-btn", "عودة للمحادثة");
    back.addEventListener("click", exitProjectMode);
    actions.appendChild(retry);
    actions.appendChild(back);
    box.appendChild(actions);
    view.appendChild(box);
  }

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  window.HubProjects = {
    openProject: openProject,
    loadProjects: loadProjects,
    exitProjectMode: exitProjectMode,
  };

  function render(text) {
    view.innerHTML = '<div class="pj-loading">' + esc(text) + "</div>";
  }

  function renderProject(p) {
    var html = "";

    // رأس المشروع + الإجراءات
    html += '<div class="pj-head"><div class="pj-title-row">' +
      '<h2>' + esc(p.name) + "</h2>" + statusBadge(p.status) + "</div>" +
      '<div class="pj-objective">' + esc(p.objective) + "</div>" +
      '<div class="pj-actions">' + actionsHtml(p) + "</div></div>";

    // (011 §1-§3) بطاقة بوابة التنفيذ — الحالة المشتقة الصادقة:
    // «الخطة معتمدة ✓ / التنفيذ محجوب مؤقتًا + السبب + المطلوب +
    // الإجراء» — لا رسالة غامضة عن بوابة مغلقة أبدًا.
    if (p.execution_gate) {
      html += executionGateHtml(p);
    }

    // سياسة التنفيذ — قرار المالك الظاهر (011 §26)
    if (p.status !== "RUNNING") {
      html += policyHtml(p);
    }

    // بوابات المالك المفتوحة — القرار الجوهري هنا
    var openGates = (p.gates || []).filter(function (g) {
      return g.status === "PENDING" || g.status === "BLOCKED";
    });
    if (openGates.length) {
      html += '<div class="pj-gates"><h3>قرارات وبوابات تنتظرك</h3>';
      openGates.forEach(function (g) {
        var isDecision = g.status === "PENDING";
        html += '<div class="pj-gate' + (isDecision ? "" : " provisioning") +
          '" data-gate="' + g.id + '">' +
          '<div class="pj-gate-kind">' + gateLabel(g.kind) +
          ' <span class="pj-gate-status">(' +
          esc(GATE_STATUS_LABELS[g.status] || g.status) + ")</span></div>" +
          '<div class="pj-gate-reason">' + esc(g.reason) + "</div>";
        if (isDecision) {
          html += '<div class="pj-gate-actions">' +
            (g.kind === "PLAN_APPROVAL"
              ? '<button class="pv-btn primary gate-approve" data-gate="' + g.id +
                '">اعتماد الخطة</button>' +
                '<button class="pv-btn danger gate-reject" data-gate="' + g.id +
                '">رفض وإعادة التوليد</button>'
              : '<button class="pv-btn primary gate-approve" data-gate="' + g.id +
                '">موافقة ومتابعة</button>' +
                '<button class="pv-btn danger gate-reject" data-gate="' + g.id +
                '">رفض</button>') +
            "</div>";
        } else {
          // بوابة توفير: زر إعادة الفحص هو طريقها (011 §19) — لا قرار
          html += '<div class="pj-gate-actions">' +
            '<button class="pv-btn primary gate-recheck" data-gate="' + g.id +
            '">إعادة الفحص (بلا إعادة اعتماد)</button>' +
            '<button class="pv-btn gate-open-envs">بيئات التنفيذ</button>' +
            "</div>";
        }
        html += "</div>";
      });
      html += "</div>";
    }

    // الخطة الرئيسية
    if (p.plan) {
      var plan = p.plan;
      html += '<div class="pj-plan"><div class="pj-plan-head">' +
        '<h3>الخطة الرئيسية v' + plan.version + "</h3>" +
        '<span class="pj-plan-state">' +
        (plan.approved_by_owner ? "معتمدة" : "بانتظار الاعتماد") +
        (plan.supersedes_plan_id
          ? " · تحل محل v" + (plan.version - 1) : "") + "</span></div>";
      if (plan.revision_reason) {
        html += '<div class="pj-plan-rev">سبب المراجعة: ' +
          esc(plan.revision_reason) + "</div>";
      }
      html += listBlock("معايير القبول", plan.acceptance_criteria);
      html += listBlock("الافتراضات", plan.assumptions);
      if ((plan.risks || []).length) html += listBlock("المخاطر", plan.risks);
      html += "</div>";
    } else if (p.status === "DRAFT") {
      // (010 §13) مسودة ≠ صفحة فارغة: الهدف والحالة والإجراء التالي
      html += '<div class="pj-draft-card">' +
        '<h3>مشروع مسودة</h3>' +
        '<div class="pj-draft-row"><b>الهدف:</b> ' + esc(p.objective) + "</div>" +
        '<div class="pj-draft-row"><b>الخطة:</b> لا خطة بعد — لم تُعتمد بعد</div>' +
        '<div class="pj-draft-row"><b>الإجراء التالي:</b> ' +
        'ولّد الخطة الأولى (استدعاء حقيقي لنموذج المفكر) ثم اعتمدها</div>' +
        "</div>";
    }

    // المراحل والخطوات
    if ((p.phases || []).length) {
      html += '<div class="pj-phases">';
      p.phases.forEach(function (phase) {
        html += '<details class="pj-phase" data-phase="' + phase.id + '"' +
          ((phase.status === "RUNNING" || phase.status === "REVIEWING")
            ? " open" : "") + ">" +
          '<summary><span class="pj-phase-title">' +
          esc(phase.ordinal + ". " + phase.title) + "</span>" +
          statusBadge(phase.status) + "</summary>";
        html += '<div class="pj-steps" data-phase="' + phase.id + '">' +
          'جارٍ التحميل…</div></details>';
      });
      html += "</div>";
    }

    // أحداث المشروع
    html += '<div class="pj-events"><h3>سجل الأحداث الدائم</h3>' +
      '<div class="pj-events-list" id="pj-events-list">' +
      eventsHtml(p.events || []) + "</div></div>";

    view.innerHTML = html;
    wireActions(p);
    loadPhaseSteps(p);
  }

  function gateLabel(kind) {
    return {
      PLAN_APPROVAL: "اعتماد الخطة",
      PLAN_REVISION_APPROVAL: "مراجعة الخطة بعد فشل",
      PROVIDER_ACTION_REQUIRED: "مزود غير جاهز — إجراء مطلوب",
      PREFLIGHT_BLOCKED: "التنفيذ محجوب — توفير مطلوب (يُحل بإعادة الفحص)",
      ESCALATION: "تصعيد",
      FINAL_VERIFICATION: "التحقق النهائي",
      OBJECTIVE_CHANGE: "تغيير الهدف"
    }[kind] || kind;
  }

  /** بطاقة بوابة التنفيذ (011 §3) — النص المطلوب حرفيًا. */
  function executionGateHtml(p) {
    var gate = p.execution_gate || {};
    var plan = p.plan || {};
    var st = gate.state || "";
    var cls = st === "OPEN" ? "open"
      : st === "APPROVED_BUT_BLOCKED" ? "blocked" : "wait";
    var html = '<div class="pj-exec-gate ' + cls + '" id="pj-exec-gate">' +
      '<div class="pjeg-row plan">' +
      (plan.approved_by_owner
        ? "الخطة معتمدة ✓"
        : "الخطة بانتظار اعتمادك") +
      "</div>";
    if (st === "OPEN") {
      html += '<div class="pjeg-row state ok">التنفيذ مفتوح — ' +
        esc(gate.reason || "") + "</div>";
    } else if (st === "APPROVED_BUT_BLOCKED") {
      html += '<div class="pjeg-row state">التنفيذ محجوب مؤقتًا</div>' +
        '<div class="pjeg-block"><b>السبب:</b> ' +
        esc(gate.reason || "لا توجد بيئة تنفيذ متوافقة وجاهزة.") +
        "</div>" +
        '<div class="pjeg-block"><b>المطلوب:</b> ' +
        esc(gate.required || "Linux/x86_64 Execution Worker") + "</div>" +
        '<div class="pjeg-block"><b>الإجراء:</b> ' +
        esc(gate.owner_action ||
          ("إضافة بيئة تنفيذ ← التحقق منها ← إعادة الفحص ← " +
           "استئناف المهمة")) + "</div>" +
        '<div class="pjeg-actions">' +
        '<button class="pv-btn primary" id="pj-recheck">إعادة الفحص</button>' +
        '<button class="pv-btn" id="pj-open-envs">بيئات التنفيذ</button>' +
        "</div>";
    } else if (st === "PENDING_PREFLIGHT") {
      html += '<div class="pjeg-row state">' + esc(gate.reason || "") +
        "</div>" +
        '<div class="pjeg-actions">' +
        '<button class="pv-btn primary" id="pj-recheck">فحص ما قبل التنفيذ</button>' +
        "</div>";
    } else {
      html += '<div class="pjeg-row state">' + esc(gate.reason || "") +
        "</div>";
    }
    html += "</div>";
    return html;
  }

  /** سياسة التنفيذ (011 §26) — ظاهرة وقابلة للتغيير بقرار معلن. */
  function policyHtml(p) {
    var current = p.execution_policy || "STRICT_ISOLATED";
    return '<div class="pj-policy">' +
      '<span class="pj-policy-label">سياسة التنفيذ:</span>' +
      '<select id="pj-policy-select">' +
      Object.keys(POLICY_LABELS).map(function (k) {
        return '<option value="' + k + '"' +
          (k === current ? " selected" : "") + ">" +
          esc(POLICY_LABELS[k]) + "</option>";
      }).join("") + "</select>" +
      '<span class="pj-policy-hint">' +
      (current === "STRICT_ISOLATED"
        ? "المهام تنفذ في بيئة معزولة حصرًا"
        : "يقبل التنفيذ المحلي بلا عزل — معلن في كل نتيجة") + "</span>" +
      "</div>";
  }

  /** إعادة الفحص (011 §19) — بعد التوفير؛ نجاح = فتح بلا إعادة اعتماد. */
  function recheck(id) {
    var gate = document.getElementById("pj-exec-gate");
    if (gate) gate.classList.add("probing");
    var btn = document.getElementById("pj-recheck");
    if (btn) { btn.disabled = true; btn.textContent = "…إعادة فحص فعلية"; }
    Hub.fetchJSON("/api/projects/" + id + "/preflight", { method: "POST" })
      .then(function (out) {
        if (btn) { btn.disabled = false; btn.textContent = "إعادة الفحص"; }
        if (!out.ok) {
          alert(out.j && out.j.detail || "تعذر إعادة الفحص");
          return;
        }
        openProject(id);   // إعادة رسم كاملة بالحالة الجديدة
      }, function () {
        if (btn) { btn.disabled = false; btn.textContent = "إعادة الفحص"; }
        alert("تعذر الوصول للخدمة");
      });
  }

  function actionsHtml(p) {
    var actions = [];
    if (p.status === "DRAFT") {
      actions.push({ id: "pj-generate", label: "توليد الخطة", cls: "primary" });
    }
    if (p.status === "READY" || p.status === "PAUSED") {
      actions.push({ id: "pj-run", label: "تشغيل الحلقة الذاتية", cls: "primary" });
    }
    if (p.status === "RUNNING") {
      actions.push({ id: "pj-stop", label: "إيقاف (لقطة قابلة للاستئناف)", cls: "danger" });
    }
    if (p.status === "COMPLETED" && p.completion_state === "CANDIDATE") {
      actions.push({ id: "pj-verify", label: "التحقق النهائي — اعتمادي", cls: "primary" });
    }
    actions.push({ id: "pj-refresh", label: "تحديث", cls: "" });
    actions.push({ id: "pj-back", label: "عودة للمحادثة", cls: "" });
    return actions.map(function (a) {
      return '<button class="pv-btn ' + a.cls + '" id="' + a.id + '">' +
        esc(a.label) + "</button>";
    }).join("");
  }

  function listBlock(title, items) {
    if (!items || !items.length) return "";
    return '<div class="pj-list-block"><b>' + esc(title) + ":</b><ul>" +
      items.map(function (item) {
        return "<li>" + esc(item) + "</li>";
      }).join("") + "</ul></div>";
  }

  function eventsHtml(events) {
    if (!events.length) return '<div class="pj-ev-empty">لا أحداث بعد</div>';
    return events.slice(-40).reverse().map(function (e) {
      return '<div class="pj-ev"><span class="pj-ev-kind">' + esc(e.kind) +
        '</span><span class="pj-ev-payload" dir="auto">' +
        esc(eventSummary(e)) + "</span></div>";
    }).join("");
  }

  function eventSummary(e) {
    var p = e.payload || {};
    if (e.kind === "PHASE_STARTED") return p.title || "";
    if (e.kind === "STEP_STARTED") return p.objective || "";
    if (e.kind === "EVIDENCE_CREATED")
      return (p.files || []).join("، ") || "";
    if (e.kind === "AUDIT_COMPLETED")
      return "الحكم: " + (p.verdict || "—");
    if (e.kind === "RETRY_REQUESTED")
      return "محاولة " + (p.attempt || "؟") + " — " + (p.decision || "");
    if (e.kind === "EXECUTION_BLOCKED")
      return "الأدوار بلا نموذج: " + ((p.unready || []).map(function (u) {
        return u.role + "→" + u.provider;
      }).join("، "));
    return JSON.stringify(p).slice(0, 120);
  }

  // ---------- خطوات المراحل (تحميل فرعي) ----------

  function loadPhaseSteps(p) {
    Hub.fetchJSON("/api/projects/" + p.id + "/steps").then(function (out) {
      if (!out.ok) return;
      var byPhase = {};
      (out.j.steps || []).forEach(function (s) {
        (byPhase[s.phase_id] = byPhase[s.phase_id] || []).push(s);
      });
      view.querySelectorAll(".pj-steps").forEach(function (el) {
        var phaseId = parseInt(el.getAttribute("data-phase"), 10);
        var steps = byPhase[phaseId] || [];
        if (!steps.length) {
          el.innerHTML = '<div class="pj-ev-empty">لا خطوات</div>';
          return;
        }
        el.innerHTML = steps.map(function (s) {
          return '<div class="pj-step ' + s.status.toLowerCase() + '">' +
            '<span class="pj-step-icon">' + stepIcon(s.status) + "</span>" +
            '<span class="pj-step-body"><span class="pj-step-obj">' +
            esc(s.ordinal + ". " + s.objective) + "</span>" +
            '<span class="pj-step-meta">' +
            (s.attempts ? "المحاولات: " + s.attempts : "") +
            (s.evidence_id ? " · دليل #" + s.evidence_id : "") +
            (s.last_error ? " · آخر خطأ: " + esc(s.last_error.slice(0, 80)) : "") +
            "</span></span></div>";
        }).join("");
      });
    });
  }

  // ---------- الإجراءات ----------

  function wireActions(p) {
    var id = p.id;
    var on = function (btnId, fn) {
      var btn = $(btnId);
      if (btn) btn.addEventListener("click", fn);
    };

    on("pj-back", exitProjectMode);
    on("pj-refresh", function () { openProject(id); });
    on("pj-generate", function () {
      var btn = $("pj-generate");
      btn.disabled = true;
      btn.textContent = "…توليد الخطة (استدعاء حقيقي)";
      Hub.fetchJSON("/api/projects/" + id + "/plan/generate", { method: "POST" })
        .then(function (out) {
          if (!out.ok) alert(out.j.detail || "فشل توليد الخطة");
          openProject(id);
        });
    });
    on("pj-run", function () { runStream(id); });
    on("pj-stop", function () {
      Hub.fetchJSON("/api/projects/" + id + "/stop", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reason: "إيقاف من الواجهة" })
      }).then(function () { setTimeout(function () { openProject(id); }, 800); });
    });
    on("pj-verify", function () {
      Hub.fetchJSON("/api/projects/" + id + "/verify", { method: "POST" })
        .then(function (out) {
          if (!out.ok) alert(out.j.detail || "تعذر التحقق");
          openProject(id);
        });
    });

    view.querySelectorAll(".gate-approve").forEach(function (btn) {
      btn.addEventListener("click", function () {
        resolveGate(id, parseInt(btn.getAttribute("data-gate"), 10), true);
      });
    });
    view.querySelectorAll(".gate-reject").forEach(function (btn) {
      btn.addEventListener("click", function () {
        resolveGate(id, parseInt(btn.getAttribute("data-gate"), 10), false);
      });
    });
    // (011 §19) بوابات التوفير تُحل بإعادة الفحص — لا بقرار موافقة
    view.querySelectorAll(".gate-recheck").forEach(function (btn) {
      btn.addEventListener("click", function () { recheck(id); });
    });
    var openEnvs = function () {
      window.HubSettings && window.HubSettings.openTab("execution");
    };
    view.querySelectorAll(".gate-open-envs").forEach(function (btn) {
      btn.addEventListener("click", openEnvs);
    });
    var envsBtn = $("pj-open-envs");
    if (envsBtn) envsBtn.addEventListener("click", openEnvs);
    var recheckBtn = $("pj-recheck");
    if (recheckBtn) recheckBtn.addEventListener("click", function () {
      recheck(id);
    });
    var policySel = $("pj-policy-select");
    if (policySel) {
      policySel.addEventListener("change", function () {
        Hub.fetchJSON("/api/projects/" + id + "/execution-policy", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ policy: policySel.value }),
        }).then(function (out) {
          if (!out.ok) {
            alert(out.j && out.j.detail || "تعذر تغيير السياسة");
            openProject(id);
          }
        });
      });
    }
  }

  function resolveGate(projectId, gateId, approved) {
    Hub.fetchJSON("/api/projects/" + projectId + "/gates/" + gateId, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ approved: approved })
    }).then(function (out) {
      if (!out.ok) alert(out.j.detail || "تعذر حل البوابة");
      openProject(projectId);
    });
  }

  // ---------- تشغيل الحلقة الذاتية — بث لحظي ----------

  function appendEvent(event) {
    var list = $("pj-events-list");
    if (!list) return;
    var div = document.createElement("div");
    div.className = "pj-ev live";
    div.innerHTML = '<span class="pj-ev-kind">' + esc(event.kind) +
      '</span><span class="pj-ev-payload" dir="auto">' +
      esc(eventSummary(event)) + "</span>";
    list.insertBefore(div, list.firstChild);
  }

  function runStream(projectId) {
    if (state.streaming) return;
    state.streaming = true;
    var runBtn = $("pj-run");
    if (runBtn) { runBtn.disabled = true; runBtn.textContent = "…الحلقة تعمل"; }
    fetch("/api/projects/" + projectId + "/run/stream", { method: "POST" })
      .then(function (resp) {
        if (!resp.ok) {
          return resp.json().then(function (j) {
            alert((j && j.detail) || "فشل التشغيل");
          });
        }
        var reader = resp.body.getReader();
        var decoder = new TextDecoder();
        var buffer = "";

        function pump() {
          return reader.read().then(function (result) {
            if (result.done) { finish(); return; }
            buffer += decoder.decode(result.value, { stream: true });
            var parts = buffer.split("\n\n");
            buffer = parts.pop() || "";
            parts.forEach(function (part) {
              if (part.startsWith("data: ")) {
                try {
                  var event = JSON.parse(part.slice(6));
                  if (event.kind === "run.error") {
                    alert("خطأ التشغيل: " + (event.payload.error || ""));
                  } else if (event.kind && event.kind.indexOf(".") === -1
                             && event.kind !== "run.start"
                             && event.kind !== "run.done") {
                    appendEvent(event);
                    if (["PHASE_COMPLETED", "PROJECT_COMPLETION_CANDIDATE",
                         "PROJECT_PAUSED", "EXECUTION_BLOCKED",
                         "OWNER_GATE_REQUIRED", "PLAN_APPROVAL_REQUIRED",
                         "RETRY_REQUESTED"].indexOf(event.kind) !== -1) {
                      setTimeout(function () { openProject(projectId); }, 600);
                    }
                  }
                } catch (err) { /* تجاهل جزء ناقص */ }
              }
            });
            return pump();
          });
        }
        return pump();
      })
      .catch(function (err) { alert("انقطع البث: " + err); })
      .then(finish);

    function finish() {
      state.streaming = false;
      openProject(projectId);
    }
  }

  // ---------- مشروع جديد ----------

  $("project-new").addEventListener("click", function () {
    var name = prompt("اسم المشروع:");
    if (!name) return;
    var objective = prompt("الهدف — ماذا يجب أن ينجزه النظام؟");
    if (!objective) return;
    Hub.fetchJSON("/api/projects", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: name, objective: objective })
    }).then(function (out) {
      if (out.ok) openProject(out.j.id);
      else alert(out.j.detail || "فشل الإنشاء");
    });
  });

  // زر عودة عام داخل الواجهة عند وضع المشروع
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && document.body.classList.contains("mode-project")
        && !state.streaming) {
      exitProjectMode();
    }
  });

  // ---------- (011 §21) تيار أحداث عام — تزامن بلا refresh يدوي ----------
  // بعد أي انتقال مهم (اعتماد/تشغيل/حجب/توفير/استئناف) يصل الحدث
  // للشريط الجانبي وصفحة المشروع المفتوحة فورًا — الحالة المعروضة
  // لا تتخلف عن القاعدة أبدًا.

  var liveEvents = { source: null, sidebarTimer: null, projectTimer: null };
  var REFRESH_KINDS = [
    "PLAN_APPROVED", "PLAN_REJECTED", "PREFLIGHT_PASS",
    "PREFLIGHT_BLOCKED", "PREFLIGHT_RECHECKED", "GATE_AUTO_RESOLVED",
    "EXECUTION_BLOCKED", "OWNER_GATE_REQUIRED", "OWNER_GATE_RESOLVED",
    "WORKER_READY", "PROJECT_PAUSED", "PROJECT_STOPPED",
    "PROJECT_RESUMED", "PROJECT_COMPLETION_CANDIDATE",
    "PROJECT_VERIFIED", "EXECUTION_POLICY_CHANGED",
    "PHASE_STARTED", "PHASE_COMPLETED", "PROJECT_CREATED",
  ];

  function subscribeProjectEvents() {
    if (liveEvents.source) return;   // اشتراك واحد فقط
    try {
      liveEvents.source = new EventSource("/api/projects/events/stream");
    } catch (err) {
      return;   // متصفح بلا EventSource — الاستطلاع الدوري يبقى
    }
    liveEvents.source.onmessage = function (message) {
      var event;
      try { event = JSON.parse(message.data); }
      catch (err) { return; }
      if (!event || !event.kind || event.kind.indexOf("stream.") === 0) return;
      if (REFRESH_KINDS.indexOf(event.kind) === -1) return;
      // الشريط الجانبي: تحديث فوري مضبوط (لا عصفرة بكل حدث)
      if (liveEvents.sidebarTimer) clearTimeout(liveEvents.sidebarTimer);
      liveEvents.sidebarTimer = setTimeout(loadProjects, 250);
      // صفحة المشروع المفتوحة: أعِد رسمها إن كان الحدث لها
      if (state.projectId !== null && event.project_id === state.projectId
          && !state.streaming) {
        if (liveEvents.projectTimer) clearTimeout(liveEvents.projectTimer);
        liveEvents.projectTimer = setTimeout(function () {
          openProject(state.projectId);
        }, 400);
      }
    };
    liveEvents.source.onerror = function () {
      // انقطاع التيار: أعد الاشتراك بعد مهلة (الخادم مصدر الحقيقة)
      if (liveEvents.source) {
        liveEvents.source.close();
        liveEvents.source = null;
      }
      setTimeout(subscribeProjectEvents, 4000);
    };
  }

  loadProjects();
  setInterval(loadProjects, 15000);
  subscribeProjectEvents();
})();
