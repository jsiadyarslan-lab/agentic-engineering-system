/* Agentic Engineering System — طبقة الـHarness في الواجهة (012).
 * بطاقة الوظيفة الدائمة (نبضة/انتظار صادق/مؤشرات) + سلسلة القبول
 * (Owner → … → VERIFIED) + خط زمن مرحلي من الإسقاط — كلها قراءة من
 * نقاط /api/harness و /api/projects/{id}/job|timeline|chain.
 *
 * (القرار 2 محفوظ حتى هنا): لا شيء في هذه البطاقات يقرر — العرض
 * يقرأ الحقيقة الدائمة فقط؛ الأحداث تصل لحظيًا عبر تيار 011 العام
 * فتُعاد البطاقات رسمًا بلا refresh يدوي (REFRESH_KINDS في
 * projects.js يشمل JOB_*).
 */
(function () {
  "use strict";

  if (!window.Hub) return;
  var Hub = window.Hub;
  var $ = Hub.$;
  var esc = Hub.esc;

  var JOB_STATUS = {
    QUEUED: { label: "في الطابور", cls: "wait" },
    RUNNING: { label: "تعمل الآن", cls: "run" },
    WAITING_CAPABILITY: { label: "تنتظر قدرة", cls: "wait" },
    WAITING_WORKER: { label: "تنتظر بيئة تنفيذ", cls: "wait" },
    WAITING_GATE: { label: "تنتظر قرارك", cls: "wait" },
    RETRYING: { label: "تعيد المحاولة", cls: "run" },
    REVISING: { label: "تراجع الخطة", cls: "run" },
    PAUSED: { label: "موقوفة عند checkpoint", cls: "wait" },
    COMPLETED: { label: "اكتملت — VERIFIED", cls: "ok" },
    FAILED: { label: "فشلت", cls: "bad" },
    STOPPED: { label: "أوقفت", cls: "bad" },
    ESCALATED: { label: "مُصعَّدة", cls: "bad" },
    INTERRUPTED: { label: "انقطعت (وفاة العملية)", cls: "bad" },
  };

  var WAITING_LABEL = {
    CAPABILITY: "قدرة/مزود غير جاهز",
    WORKER: "بيئة تنفيذ/عامل مطلوب",
    GATE: "بوابة قرار مالك",
  };

  var STAGE_LABEL = {
    OBJECTIVE: "الهدف", PLAN: "الخطة", APPROVAL: "الاعتماد",
    PREFLIGHT: "الفحص", EXECUTION: "التنفيذ", EVIDENCE: "الأدلة",
    AUDIT: "التدقيق", VERIFICATION: "التحقق",
  };

  var STAGE_STATUS = {
    DONE: { ico: "✓", cls: "done" },
    ACTIVE: { ico: "◌", cls: "active" },
    WAITING: { ico: "⏸", cls: "waiting" },
    FAILED: { ico: "✕", cls: "failed" },
    PENDING: { ico: "○", cls: "" },
  };

  var ACTOR_LABEL = {
    owner: "المالك", coordinator: "المنسق", thinker: "المفكر",
    implementer: "المنفذ", verifier: "المراجع", arbiter: "المحكَّم",
    system: "النظام",
  };

  // ---------- بطاقة الوظيفة الدائمة ----------

  function jobCardHtml(job) {
    if (!job) return "";
    var st = JOB_STATUS[job.status] || { label: job.status, cls: "" };
    var boxCls = job.status === "RUNNING" || job.status === "RETRYING"
      || job.status === "REVISING" ? "running"
      : job.status.indexOf("WAITING") === 0 || job.status === "PAUSED"
      || job.status === "QUEUED" ? "waiting"
      : job.status === "COMPLETED" ? "done" : "bad";

    var html = '<div class="pj-job ' + boxCls + '" id="pj-job">' +
      '<div class="pj-job-head">' +
      '<div class="pj-job-title">⚙ الوظيفة الدائمة' +
      '<span class="pj-job-id">#' + job.id + "</span></div>" +
      '<span class="pj-job-status ' + st.cls + '">' +
      esc(st.label) + "</span></div>";

    // النبضة — برهان الحياة لا انطباع
    html += '<div class="pj-job-meta">';
    html += '<span class="pj-job-beat ' + beatClass(job) + '">' +
      '<span class="beat-dot"></span>' + beatText(job) + "</span>";
    html += "<span><b>" + job.tick_count + "</b> نبضة</span>";
    if (job.checkpoints) {
      html += "<span><b>" + job.checkpoints + "</b> checkpoint</span>";
    }
    if (job.retries) {
      html += "<span><b>" + job.retries + "</b> إعادة</span>";
    }
    if (job.current_step_id) {
      html += "<span>الخطوة <b>#" + job.current_step_id + "</b></span>";
    }
    html += "</div>";

    // الانتظار الصادق — النوع والسبب ومسار الرفع حرفيًا
    if (job.status.indexOf("WAITING") === 0) {
      var wk = WAITING_LABEL[job.waiting_kind] || job.waiting_kind;
      var detail = job.waiting_detail || {};
      html += '<div class="pj-job-wait">' +
        '<div class="wj-kind">⏸ تنتظر: ' + esc(wk) + "</div>";
      if (detail.summary) {
        html += '<div class="wj-summary">' + esc(detail.summary) + "</div>";
      }
      if (detail.owner_action) {
        html += '<div class="wj-summary"><b>الإجراء:</b> ' +
          esc(detail.owner_action) + "</div>";
      }
      if (detail.recovery) {
        html += '<div class="wj-summary">' + esc(detail.recovery) + "</div>";
      }
      if (job.unblock_path) {
        html += '<div class="wj-path">↻ ' + esc(job.unblock_path) + "</div>";
      }
      html += "</div>";
    }

    if (job.current_role) {
      html += '<div class="pj-job-role">الدور الحالي: <b>' +
        esc(ACTOR_LABEL[job.current_role] || job.current_role) + "</b></div>";
    }
    if (job.last_error) {
      html += '<div class="pj-job-role" style="color:#f87171">' +
        esc(job.last_error.slice(0, 200)) + "</div>";
    }
    html += "</div>";
    return html;
  }

  function beatClass(job) {
    if (job.status === "INTERRUPTED") return "dead";
    var age = job.heartbeat_age_s;
    if (age === null || age === undefined) return "dead";
    if (job.status !== "RUNNING" && job.status !== "RETRYING"
        && job.status !== "REVISING") return "stale";
    return age < 120 ? "" : "stale";
  }

  function beatText(job) {
    if (job.heartbeat_age_s === null
        || job.heartbeat_age_s === undefined) return "لم تنبض بعد";
    var s = Math.round(job.heartbeat_age_s);
    if (s < 60) return "نبضت قبل " + s + " ث";
    return "نبضت قبل " + Math.floor(s / 60) + " د " + (s % 60) + " ث";
  }

  // ---------- سلسلة القبول ----------

  function chainHtml(chain, job) {
    if (!chain || !chain.stages) return "";
    var html = '<div class="pj-chain"><h3>سلسلة القبول</h3>' +
      '<div class="pj-chain-steps">';
    chain.stages.forEach(function (stage, i) {
      if (i > 0) html += '<span class="pj-chain-arrow">→</span>';
      var st = STAGE_STATUS[stage.status] || STAGE_STATUS.PENDING;
      html += '<span class="pj-chain-step ' + st.cls + '">' +
        '<span class="st-ico">' + st.ico + "</span>" +
        esc(STAGE_LABEL[stage.stage] || stage.stage) + "</span>";
    });
    html += "</div>";
    // أين يقف المسار ولماذا — أول مرحلة منتظرة مع سببها
    var waiting = (chain.stages || []).filter(function (s) {
      return s.status === "WAITING" || s.status === "FAILED";
    })[0];
    if (waiting) {
      html += '<div class="pj-chain-note"><b>' +
        esc(STAGE_LABEL[waiting.stage] || waiting.stage) + ":</b> " +
        esc(waiting.waiting_reason || "توقف بأمان — عالج سببه ثم استأنف") +
        "</div>";
    } else if (job && job.status === "COMPLETED") {
      html += '<div class="pj-chain-note" style="color:#34d399">' +
        "اكتمل المسار كاملًا — تحقق المالك VERIFIED</div>";
    }
    html += "</div>";
    return html;
  }

  // ---------- خط الزمن المرحلي ----------

  function timelineHtml(timeline) {
    if (!timeline || !timeline.items || !timeline.items.length) return "";
    var items = timeline.items.slice().reverse();  // الأحدث أولًا
    var html = '<div class="pj-timeline"><h3>الخط الزمني المرحلي</h3>' +
      '<div class="pj-tl-list">';
    items.slice(0, 60).forEach(function (item) {
      html += '<div class="pj-tl-item">' +
        '<span class="pj-tl-stage">' + esc(item.stage) + "</span>" +
        '<span class="pj-tl-body">' +
        '<div class="pj-tl-title">' + esc(item.title) + "</div>" +
        (item.detail
          ? '<div class="pj-tl-detail">' + esc(item.detail) + "</div>" : "") +
        "</span>" +
        '<span class="pj-tl-actor ' + esc(item.actor) + '">' +
        esc(ACTOR_LABEL[item.actor] || item.actor) + "</span>" +
        "</div>";
    });
    html += "</div></div>";
    return html;
  }

  // ---------- تحميل الإسقاطات — قراءة فقط ----------

  function loadProjections(projectId) {
    var view = $("project-view");
    if (!view || !projectId) return;
    var chainBox = view.querySelector("#pj-chain-box");
    var tlBox = view.querySelector("#pj-timeline-box");
    if (!chainBox && !tlBox) return;

    Hub.fetchJSON("/api/projects/" + projectId + "/chain").then(
      function (out) {
        if (out.ok && chainBox) {
          chainBox.innerHTML = chainHtml(out.j, currentJob);
        }
      }
    );
    Hub.fetchJSON("/api/projects/" + projectId + "/timeline").then(
      function (out) {
        if (out.ok && tlBox) tlBox.innerHTML = timelineHtml(out.j);
      }
    );
  }

  var currentJob = null;

  // الواجهة العامة — يستهلكها projects.js عند رسم صفحة المشروع
  window.HubHarness = {
    jobCardHtml: function (job) {
      currentJob = job || null;
      return jobCardHtml(job);
    },
    renderSections: function (projectId) {
      // حاويتان فارغتان يملؤهما الإسقاط بعد الرسم
      var view = $("project-view");
      if (!view) return "";
      var html = '<div id="pj-chain-box"></div>' +
        '<div id="pj-timeline-box"></div>';
      // رفع التحميل بعد إدراج HTML في DOM
      setTimeout(function () { loadProjections(projectId); }, 0);
      return html;
    },
    JOB_STATUS: JOB_STATUS,
  };
})();
