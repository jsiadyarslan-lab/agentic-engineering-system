/* Agentic Engineering System — واجهة المشاريع الحية (007+011+013).
 * (013 §8-§12) المشروع تجربة محادثة: الهدف رسالة، الخطة والاعتماد
 * والتنفيذ بطاقات حية تتدفق بلا refresh — الصورة من /state (لقطة
 * المصالحة §6) والحركة من تيار الأحداث (§5). عقد زر الاعتماد §7
 * والتجهيز §17 والفشل المفهوم §27 — كلها هنا.
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

  var state = { projectId: null, streaming: false, snapshot: null };
  var liveOff = null;

  /* توجيه هادئ: يغير الـhash دون إطلاق hashchange (استيراد دوري مع
   * app.js ممنوع — تطبيق محلي آمن بنفس العقد) */
  function setHashQuietly(hash) {
    if (window.Hub && typeof Hub.setHashQuietly === "function") {
      Hub.setHashQuietly(hash);
      return;
    }
    try {
      history.replaceState(null, "", hash || location.pathname);
    } catch (err) { /* تجاهل — التوجيه ليس حرجًا */ }
  }

  /* ---------- الشريط الجانبي: قائمة المشاريع ---------- */

  var STATUS_LABELS = (window.ProjectLive && ProjectLive.STATUS_LABELS) || {};

  function loadProjects() {
    Hub.fetchJSON("/api/projects").then(function (out) {
      if (!out.ok) return;
      renderProjects(out.j.projects || [], out.j.recovery || []);
    });
  }

  function renderProjects(projects, recovery) {
    projectsList.textContent = "";
    if (!projects.length) {
      var empty = document.createElement("div");
      empty.className = "pj-list-empty";
      empty.textContent = "لا مشاريع بعد — أرسل هدفًا من وضع «مشروع»";
      projectsList.appendChild(empty);
      return;
    }
    projects.forEach(function (p) {
      var item = document.createElement("button");
      item.className = "pj-item" +
        (p.id === state.projectId ? " active" : "");
      var status = document.createElement("span");
      status.className = "pj-dot " + dotClass(p.status);
      status.title = STATUS_LABELS[p.status] || p.status;
      var name = document.createElement("span");
      name.className = "pj-name";
      name.textContent = p.name;
      item.appendChild(status); item.appendChild(name);
      item.addEventListener("click", function () {
        openProject(p.id);
      });
      projectsList.appendChild(item);
    });
  }

  function dotClass(status) {
    return {
      RUNNING: "live", VERIFIED: "ok", COMPLETED: "gold",
      AWAITING_OWNER_APPROVAL: "gold", BLOCKED: "warn",
      PAUSED: "dim", STOPPED: "danger", ESCALATED: "danger",
    }[status] || "dim";
  }

  /* ---------- فتح المشروع: لقطة ثم حي (§6 initial snapshot + stream) ---------- */

  function openProject(projectId, opts) {
    state.projectId = projectId;
    document.body.classList.add("mode-project");
    view.hidden = false;
    var chat = document.querySelector(".chat-scroll");
    if (chat) chat.style.display = "none";
    var composer = document.querySelector(".composer");
    if (composer) composer.style.display = "none";
    setHashQuietly("#/project/" + projectId);
    reconcile();
    loadProjects();
    if (window.LiveEvents) LiveEvents.connect();
  }

  function exitProjectMode() {
    state.projectId = null;
    state.snapshot = null;
    document.body.classList.remove("mode-project");
    view.hidden = true;
    var chat = document.querySelector(".chat-scroll");
    if (chat) chat.style.display = "";
    var composer = document.querySelector(".composer");
    if (composer) composer.style.display = "";
    setHashQuietly("");
    if (liveOff) { liveOff(); liveOff = null; }
    loadProjects();
  }

  /* المصالحة: إعادة بناء المشهد كاملًا من اللقطة (أول مرة وبعد انقطاع) */
  function reconcile() {
    if (state.projectId == null) return;
    var firstLoad = !state.snapshot;
    if (firstLoad) renderLoading();
    Hub.fetchJSON("/api/projects/" + state.projectId + "/state")
      .then(function (out) {
        if (state.projectId == null) return;
        if (!out.ok) {
          renderError((out.j && out.j.detail) || "تعذر تحميل المشروع");
          return;
        }
        state.snapshot = out.j;
        renderScene(out.j);
      }, function (err) {
        if (state.projectId == null) return;
        renderError("تعذر الوصول للخدمة — " + err);
      });
  }

  /* (010 §31 + 013) حالات معلنة: تحميل وخطأ وفراغ — لا شاشة سوداء
   * ولا صمت أبدًا. (درس §15 جذر الصفحة السوداء موثق: enter يزيل
   * hidden صراحةً view.hidden = false والخروج يعيده view.hidden = true) */
  function renderLoading() {
    var scene = $("pl-scene");
    if (!scene) return;
    scene.textContent = "";
    var loading = document.createElement("div");
    loading.className = "pl-state-card";
    loading.textContent = "جارٍ تحميل المشروع…";
    scene.appendChild(loading);
  }

  function renderError(detail) {
    var scene = $("pl-scene");
    if (!scene) return;
    scene.textContent = "";
    var card = document.createElement("div");
    card.className = "pl-state-card error";
    var text = document.createElement("div");
    text.textContent = "تعذر تحميل المشروع";
    var why = document.createElement("div");
    why.className = "pl-state-detail";
    why.dir = "auto";
    why.textContent = String(detail || "").slice(0, 200);
    var retry = document.createElement("button");
    retry.className = "pl-btn";
    retry.textContent = "إعادة المحاولة";
    retry.addEventListener("click", reconcile);
    card.appendChild(text); card.appendChild(why);
    card.appendChild(retry);
    scene.appendChild(card);
  }

  function renderScene(snapshot) {
    if (!window.ProjectLive) return;
    var container = $("pl-scene");
    if (!container) return;
    if (!snapshot.plan && snapshot.status === "DRAFT") {
      renderDraftCard(snapshot, container);
      return;
    }
    var running = snapshot.status === "RUNNING" ||
      (snapshot.job && ["RUNNING", "RETRYING"].indexOf(
        snapshot.job.status) !== -1);
    ProjectLive.renderProjectScene(container, snapshot, {
      approveUrl: function (gate) {
        return gate.kind === "PLAN_APPROVAL"
          ? "/api/projects/" + snapshot.id + "/plan/approve"
          : "/api/projects/" + snapshot.id + "/gates/" + gate.id;
      },
      recheckUrl: "/api/projects/" + snapshot.id + "/preflight",
      verifyUrl: "/api/projects/" + snapshot.id + "/verify",
      viewPlan: function () {
        togglePlanDetails(snapshot);
      },
    });
    if (running && !state.streaming) attachRun(snapshot.id, 0);
    updateHeader(snapshot);
  }

  /* (010 §13) المسودة ليست صفحة فارغة: الهدف والإجراء التالي ظاهران */
  function renderDraftCard(snapshot, container) {
    container.textContent = "";
    var card = document.createElement("div");
    card.className = "pl-state-card pj-draft-card";
    var title = document.createElement("div");
    title.className = "pl-title";
    title.textContent = "مشروع مسودة";
    var objective = document.createElement("div");
    objective.className = "pl-objective";
    objective.dir = "auto";
    objective.textContent = snapshot.objective || "";
    var next = document.createElement("div");
    next.className = "pl-note";
    next.textContent = "الإجراء التالي: توليد الخطة الرئيسية من الهدف.";
    var generate = document.createElement("button");
    generate.className = "pl-btn primary";
    generate.textContent = "توليد الخطة";
    generate.addEventListener("click", function () {
      generate.disabled = true;
      generate.textContent = "…جاري التوليد (استدعاء حقيقي)";
      Hub.fetchJSON("/api/projects/" + snapshot.id + "/plan/generate",
                     { method: "POST" })
        .then(function (out) {
          if (!out.ok) {
            generate.disabled = false;
            generate.textContent = "توليد الخطة";
            alert((out.j && out.j.detail) || "فشل توليد الخطة");
            return;
          }
          reconcile();
        });
    });
    card.appendChild(title); card.appendChild(objective);
    card.appendChild(next); card.appendChild(generate);
    container.appendChild(card);
  }

  function updateHeader(snapshot) {
    var head = $("pl-head-bar");
    if (!head) return;
    var title = $("pl-head-title");
    var status = $("pl-head-status");
    if (title) title.textContent = snapshot.name || "مشروع";
    if (status) {
      status.textContent = (STATUS_LABELS[snapshot.status] ||
                            snapshot.status);
      status.className = "pl-head-status " +
        (snapshot.status === "RUNNING" ? "live"
         : snapshot.status === "VERIFIED" ? "ok"
         : snapshot.status === "BLOCKED" ? "warn" : "dim");
    }
  }

  function togglePlanDetails(snapshot) {
    var existing = document.getElementById("pl-plan-modal");
    if (existing) { existing.remove(); return; }
    var backdrop = document.createElement("div");
    backdrop.id = "pl-plan-modal";
    backdrop.className = "pl-plan-modal";
    var modal = document.createElement("div");
    modal.className = "pl-plan-modal-card";
    var plan = snapshot.plan || {};
    var head = document.createElement("div");
    head.className = "pl-plan-modal-head";
    head.textContent = "الخطة الرئيسية v" + (plan.version || "?");
    var close = document.createElement("button");
    close.className = "pl-btn";
    close.textContent = "✕";
    close.addEventListener("click", function () { backdrop.remove(); });
    head.appendChild(close);
    modal.appendChild(head);

    var body = document.createElement("div");
    body.className = "pl-plan-modal-body";
    var sections = [
      ["الافتراضات", plan.assumptions],
      ["معايير القبول", (snapshot.acceptance_criteria || []).map(
        function (c) {
          return (c.criterion_id || "") + " — " + c.description +
            " [" + (c.status || "PENDING") + "]";
        }) || plan.acceptance_criteria],
      ["المخاطر", plan.risks],
      ["قرارات المالك المطلوبة", plan.required_owner_decisions],
    ];
    sections.forEach(function (pair) {
      if (!pair[1] || !pair[1].length) return;
      var h = document.createElement("h4");
      h.textContent = pair[0];
      body.appendChild(h);
      pair[1].forEach(function (item) {
        var line = document.createElement("div");
        line.className = "pl-plan-modal-line";
        line.dir = "auto";
        line.textContent = typeof item === "string" ? item
          : JSON.stringify(item);
        body.appendChild(line);
      });
    });
    (plan.phases || []).forEach(function (phase, index) {
      var h = document.createElement("h4");
      h.textContent = "المرحلة " + (index + 1) + ": " +
        (phase.title || "");
      body.appendChild(h);
      (phase.steps || []).forEach(function (step, i) {
        var line = document.createElement("div");
        line.className = "pl-plan-modal-line";
        line.dir = "auto";
        line.textContent = (i + 1) + ". " + (step.objective || "");
        body.appendChild(line);
      });
    });
    modal.appendChild(body);
    backdrop.appendChild(modal);
    backdrop.addEventListener("click", function (e) {
      if (e.target === backdrop) backdrop.remove();
    });
    document.body.appendChild(backdrop);
  }

  /* ---------- الحي: التيار العام يغذي المشهد (§5 بلا refresh) ---------- */

  function attachLive() {
    if (liveOff || !window.LiveEvents) return;
    liveOff = LiveEvents.onEvent(function (event) {
      if (state.projectId == null) return;
      if (event.project_id !== state.projectId) {
        // مشروع آخر تحرك — حدّث الشريط فقط
        loadProjects();
        return;
      }
      onProjectEvent(event);
    });
  }

  var reconcileTimer = null;

  function onProjectEvent(event) {
    var kind = event.kind;
    // أحداث النشاط تُضاف سطرًا سطرًا بلا إعادة بناء (§28 live)
    var list = view.querySelector(".pl-activity-list");
    if (list && window.ProjectLive) {
      var line = ProjectLive.activityLine(
        kind, event.payload || {});
      if (line) {
        list.appendChild(line);
        while (list.children.length > ProjectLive.ACTIVITY_LIMIT) {
          list.removeChild(list.firstChild);
        }
        list.closest(".pl-card").hidden = false;
      }
    }
    // تغيّر المشهد (بوابة/حالة/وظيفة) ← مصالحة خفيفة مضبوطة
    if (window.ProjectLive && ProjectLive.isSceneChange(kind)) {
      if (reconcileTimer) clearTimeout(reconcileTimer);
      reconcileTimer = setTimeout(reconcile, 250);
    }
    loadProjectsThrottled();
  }

  var sidebarTimer = null;
  function loadProjectsThrottled() {
    if (sidebarTimer) return;
    sidebarTimer = setTimeout(function () {
      sidebarTimer = null;
      loadProjects();
    }, 600);
  }

  /* ---------- إرفاق بث التشغيل (تشغيل يدوي/استئناف حي) ---------- */

  function attachRun(projectId, after) {
    if (state.streaming) return;
    state.streaming = true;
    fetch("/api/projects/" + projectId + "/run/stream?after=" + (after || 0),
          { method: "POST" })
      .then(function (resp) {
        if (!resp.ok) { state.streaming = false; return; }
        pumpRun(resp);
      })
      .catch(function () { state.streaming = false; });
  }

  function pumpRun(resp) {
    var reader = resp.body.getReader();
    var decoder = new TextDecoder();
    var buffer = "";
    (function pump() {
      reader.read().then(function (result) {
        if (result.done) { state.streaming = false; return; }
        buffer += decoder.decode(result.value, { stream: true });
        var parts = buffer.split("\n\n");
        buffer = parts.pop() || "";
        parts.forEach(function (part) {
          if (part.indexOf("data: ") !== 0) return;
          try {
            var event = JSON.parse(part.slice(6));
            if (event.kind === "run.done") {
              state.streaming = false;
              reconcile();
            }
          } catch (err) { /* جزء ناقص */ }
        });
        pump();
      }, function () { state.streaming = false; });
    })();
  }

  /* ---------- مشروع جديد من المحادثة (وضع المشروع §8) ---------- */

  function createProjectFromObjective(objective, name) {
    Hub.fetchJSON("/api/projects", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: name || objective.slice(0, 60),
        objective: objective,
      }),
    }).then(function (out) {
      if (!out.ok) {
        alert((out.j && out.j.detail) || "فشل إنشاء المشروع");
        return;
      }
      openProject(out.j.id);
      // توليد الخطة تلقائيًا — ثم البث يحمل البطاقات بلا refresh
      Hub.fetchJSON("/api/projects/" + out.j.id + "/plan/generate",
                     { method: "POST" })
        .then(function (gen) {
          if (!gen.ok) {
            alert((gen.j && gen.j.detail) || "فشل توليد الخطة");
          }
          reconcile();
        });
    });
  }

  /* ---------- الربط ---------- */

  var newProjectBtn = $("project-new");
  if (newProjectBtn) {
    newProjectBtn.addEventListener("click", function () {
      var objective = window.prompt(
        "اكتب هدف المشروع — سيُحوَّل إلى خطة تعتمدها ثم يُنفَّذ ذاتيًا:");
      if (!objective) return;
      createProjectFromObjective(objective);
    });
  }

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" &&
        document.body.classList.contains("mode-project") &&
        !state.streaming) {
      exitProjectMode();
    }
  });

  window.HubProjects = {
    openProject: openProject,
    exitProjectMode: exitProjectMode,
    reconcile: reconcile,
    createProjectFromObjective: createProjectFromObjective,
    loadProjects: loadProjects,
  };

  attachLive();
  loadProjects();

  // فتح مشروع من التوجيه الدائم #/project/{id}
  if (window.location.hash.indexOf("#/project/") === 0) {
    var routeId = parseInt(
      window.location.hash.slice("#/project/".length), 10);
    if (routeId) openProject(routeId);
  }
})();
