/* مركز التحكم (013.4 §9-§10+§32-§33+§45) — سطح إدارة العمل الموازي للمحادثة.
 *
 * - التنقل الأساسي: محادثة / تشغيلات / أرشيف (الشريط الجانبي)
 * - التشغيلات النشطة: مؤشر حي (● يعمل · ⏸ متوقف · ◷ ينتظرك · ⚠ محجوب
 *   · × فشل · ✓ اكتمل) يبقى مرئيًا حتى بعد مغادرة المشروع (§32)
 * - الأرشيف: مشاريع قابلة للاسترجاع — الأرشفة ليست حذفًا (§45)
 * - أيقونة النقر تعيد إلى صف تشغيل المشروع (§33)
 * لا تنفيذًا هنا: الأزرار أوامر API دائمة فقط (§11) — التنفيذ
 * ملك الوظيفة الدائمة، والصفحة عميل (§34).
 */
(function () {
  "use strict";

  var Hub = window.Hub;
  var state = {
    view: "chat",           // chat | runs | archive
    pollTimer: null,
    runs: [],
  };

  function el(tag, cls, text) { return Hub.el(tag, cls, text); }
  function esc(s) { return Hub.esc(s); }

  function runsView() { return document.getElementById("runs-view"); }
  function archiveView() { return document.getElementById("archive-view"); }

  /** إخفاء أسطح مركز التحكم فقط — بلا مساس بوضع المشروع (يستدعيه openProject). */
  function hideSurfaces() {
    if (runsView()) runsView().hidden = true;
    if (archiveView()) archiveView().hidden = true;
  }

  /** تبديل العرض: المحادثة أساسًا والتشغيلات/الأرشيف أسطح موازية. */
  function showView(name) {
    state.view = name;
    var chatHead = document.querySelector(".chat-head");
    var chatScroll = document.getElementById("chat-scroll");
    var composer = document.querySelector(".composer");
    var taskSettings = document.getElementById("task-settings");
    var isChat = name === "chat";
    hideSurfaces();
    // (AES-UI-PREMIUM-REDESIGN-001) إصلاح خلل قديم منذ إنشاء الملف: النقر
    // على «التشغيلات» أو «الأرشيف» كان يخفي المحادثة دون إظهار السطح
    // المستهدف (لا يوجد أي موضع يرفع hidden عنهما) — فتبقى الشاشة
    // فارغة. السطح المستهدف يُظهر صراحة هنا.
    if (name === "runs" && runsView()) runsView().hidden = false;
    if (name === "archive" && archiveView()) archiveView().hidden = false;
    // والعودة للمحادثة من وضع المصنع تُخلي سطح المصنع أيضاً
    if (isChat && window.FactoryControl &&
        document.body.classList.contains("mode-factory")) {
      window.FactoryControl.hide();
    }
    if (!isChat) {
      // فتح سطح التحكم يخرج من وضع المشروع أولاً (المشهد قابه للعودة)
      if (document.body.classList.contains("mode-project") &&
          window.HubProjects) {
        window.HubProjects.exitProjectMode();
      }
      if (chatHead) chatHead.style.display = "none";
      if (chatScroll) chatScroll.style.display = "none";
      if (composer) composer.style.display = "none";
    } else {
      if (chatHead) chatHead.style.display = "";
      if (chatScroll) chatScroll.style.display = "";
      if (composer) composer.style.display = "";
    }
    if (taskSettings) taskSettings.hidden = true;
    document.querySelectorAll(".side-nav-item").forEach(function (btn) {
      btn.classList.toggle("active",
        btn.getAttribute("data-nav") === name);
    });
    if (name === "runs") renderRuns();
    if (name === "archive") renderArchive();
  }

  /* ---------------- التشغيلات النشطة (§32-§33) ---------------- */

  function runDot(run) {
    var status = run.status || "";
    if (run.planning_active || status === "RUNNING" ||
        status === "REVISING" || status === "PLANNING") return "●";
    if (status === "PAUSED") return "⏸";
    if (status === "AWAITING_OWNER_APPROVAL" || status === "BLOCKED") {
      return status === "BLOCKED" ? "⚠" : "◷";
    }
    if (status === "VERIFIED" || status === "COMPLETED") return "✓";
    if (status === "ESCALATED") return "⚠";
    return "·";
  }

  function runDotClass(run) {
    var dot = runDot(run);
    return { "●": "live", "⏸": "paused", "◷": "waiting",
             "⚠": "warn", "✓": "ok", "×": "err", "·": "" }[dot] || "";
  }

  function renderRuns() {
    var body = document.getElementById("runs-body");
    if (!body) return;
    body.textContent = "";
    var loading = el("div", "cc-loading", "جارٍ تحميل التشغيلات…");
    body.appendChild(loading);
    Hub.fetchJSON("/api/projects/runs/active").then(function (out) {
      loading.remove();
      if (!out.ok) {
        body.appendChild(el("div", "cc-empty",
          "تعذر تحميل التشغيلات — " +
          ((out.j && out.j.detail) || "")));
        return;
      }
      var runs = out.j.runs || [];
      state.runs = runs;
      updateBadge(runs.length);
      if (!runs.length) {
        body.appendChild(el("div", "cc-empty",
          "لا تشغيلات نشطة الآن — أنشئ مشروعًا أو شغّل خطة معتمدة"));
        return;
      }
      runs.forEach(function (run) {
        body.appendChild(runCard(run));
      });
    });
  }

  function runCard(run) {
    var card = el("button", "cc-run-card");
    var statusLabels = (window.WorkflowView &&
      window.WorkflowView.STATUS_LABELS) || {};
    var dot = el("span", "cc-run-dot " + runDotClass(run));
    dot.textContent = runDot(run);
    card.appendChild(dot);
    var text = el("div", "cc-run-text");
    text.appendChild(el("div", "cc-run-title", run.name || "مشروع"));
    var sub = [];
    sub.push(statusLabels[run.status] || run.status || "");
    if (run.stage) sub.push("المرحلة: " + run.stage);
    if (run.waiting_for && run.waiting_for.label) {
      sub.push("ينتظر: " + run.waiting_for.label);
    }
    if (run.elapsed_s != null) {
      sub.push("مضى " + Math.round(run.elapsed_s) + "ث");
    }
    text.appendChild(el("div", "cc-run-sub", sub.join(" · ")));
    var progress = run.progress;
    if (progress && progress.steps_total) {
      var bar = el("div", "cc-run-bar");
      var fill = el("div", "cc-run-fill");
      fill.style.width = (progress.percent || 0) + "%";
      bar.appendChild(fill);
      text.appendChild(bar);
    }
    card.appendChild(text);
    card.appendChild(el("span", "cc-run-open", "فتح ←"));
    card.addEventListener("click", function () {
      showView("chat");
      if (window.HubProjects) {
        window.HubProjects.openProject(run.project_id);
      }
    });
    return card;
  }

  /* ------------------------ الأرشيف (§45) ----------------------- */

  function renderArchive() {
    var body = document.getElementById("archive-body");
    if (!body) return;
    body.textContent = "";
    body.appendChild(el("div", "cc-loading", "جارٍ تحميل الأرشيف…"));
    Hub.fetchJSON("/api/projects/archived/list").then(function (out) {
      body.textContent = "";
      if (!out.ok) {
        body.appendChild(el("div", "cc-empty", "تعذر تحميل الأرشيف"));
        return;
      }
      var projects = out.j.projects || [];
      if (!projects.length) {
        body.appendChild(el("div", "cc-empty",
          "الأرشيف فارغ — الأرشفة من قائمة ⋯ في أي مشروع"));
        return;
      }
      projects.forEach(function (project) {
        body.appendChild(archiveCard(project));
      });
    });
  }

  function archiveCard(project) {
    var card = el("div", "cc-archive-card");
    var text = el("div", "cc-run-text");
    text.appendChild(el("div", "cc-run-title", project.name || "مشروع"));
    text.appendChild(el("div", "cc-run-sub",
      "أُرشف " + (project.archived_at || "").slice(0, 10) +
      " · حالته الأخيرة: " + (project.status || "")));
    card.appendChild(text);
    var restore = el("button", "cc-restore-btn", "استرجاع");
    restore.addEventListener("click", function () {
      restore.disabled = true;
      restore.textContent = "…جارٍ الاسترجاع";
      Hub.fetchJSON("/api/projects/" + project.id + "/restore",
        { method: "POST" }).then(function (out) {
        if (!out.ok) {
          restore.disabled = false;
          restore.textContent = "تعذر — أعد المحاولة";
          return;
        }
        card.remove();
        if (window.HubProjects) window.HubProjects.loadProjects();
      });
    });
    card.appendChild(restore);
    return card;
  }

  /* -------------- مؤشر الشريط الجانبي (§32 دوري) ---------------- */

  function updateBadge(count) {
    var badge = document.getElementById("runs-badge");
    if (!badge) return;
    badge.hidden = !count;
    badge.textContent = String(count);
  }

  function pollActiveRuns() {
    Hub.fetchJSON("/api/projects/runs/active").then(function (out) {
      if (out.ok) {
        var runs = out.j.runs || [];
        state.runs = runs;
        updateBadge(runs.length);
        if (state.view === "runs") refreshRunCards(runs);
        updateProjectDots(runs);
      }
    }, function () { /* الشبكة انقطعت — الدورة القادمة تعيد */ });
  }

  function refreshRunCards(runs) {
    var body = document.getElementById("runs-body");
    if (!body || state.view !== "runs") return;
    // بطاقات جديدة فقط عند تغير العدد — لا إعادة بناء مع كل نبضة
    if (body.querySelectorAll(".cc-run-card").length !== runs.length) {
      renderRuns();
    }
  }

  /** نقاط حالة المشاريع في الشريط الجانبي — مرئية دائمًا (§32). */
  function updateProjectDots(runs) {
    var list = document.getElementById("projects-list");
    if (!list || !window.HubProjects) return;
    var byId = {};
    runs.forEach(function (run) { byId[run.project_id] = run; });
    list.querySelectorAll(".proj-item").forEach(function (item) {
      var pid = parseInt(item.getAttribute("data-project-id") || "0", 10);
      var run = byId[pid];
      var existing = item.querySelector(".proj-run-dot");
      if (!run) {
        if (existing) existing.remove();
        return;
      }
      if (!existing) {
        existing = el("span", "proj-run-dot");
        item.insertBefore(existing, item.firstChild);
      }
      existing.textContent = runDot(run);
      existing.className = "proj-run-dot " + runDotClass(run);
      existing.title = "تشغيل نشط — انقر للعودة إليه";
    });
  }

  /* --------------------------- الربط ---------------------------- */

  document.querySelectorAll(".side-nav-item").forEach(function (btn) {
    btn.addEventListener("click", function () {
      showView(btn.getAttribute("data-nav"));
    });
  });
  var runsBack = document.getElementById("runs-back");
  if (runsBack) runsBack.addEventListener("click", function () {
    showView("chat");
  });
  var archiveBack = document.getElementById("archive-back");
  if (archiveBack) archiveBack.addEventListener("click", function () {
    showView("chat");
  });

  // أول تحميل + دور كل 5ث — مؤشر التشغيل حي بلا refresh (§32)
  pollActiveRuns();
  state.pollTimer = setInterval(pollActiveRuns, 5000);

  window.ControlCenter = {
    showView: showView,
    hideSurfaces: hideSurfaces,
    refreshRuns: pollActiveRuns,
    runDot: runDot,
  };
})();
