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

  var state = { projectId: null, streaming: false, snapshot: null,
                runtime: null, activeTab: "conversation",
                runtimeTimer: null };
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
      item.setAttribute("data-project-id", String(p.id));
      /* (W2-T11) النقطة الدلالية لا تنفصل عن نصها: صفّان كنمط الجلسات —
         الاسم فوق، والنقطة + نص الحالة تحته. النقطة aria-hidden (النص يحمل
         المعنى)، والنص يقرأه قارئ الشاشة بدل العنوان المنفرد. */
      var text = document.createElement("span");
      text.className = "pj-text";
      var name = document.createElement("span");
      name.className = "pj-name";
      name.textContent = p.name;
      text.appendChild(name);
      var meta = document.createElement("span");
      meta.className = "pj-meta";
      var status = document.createElement("span");
      status.className = "pj-dot " + dotClass(p.status);
      status.title = STATUS_LABELS[p.status] || p.status;
      status.setAttribute("aria-hidden", "true");
      meta.appendChild(status);
      var statusText = document.createElement("span");
      statusText.className = "pj-status";
      statusText.textContent = STATUS_LABELS[p.status] || p.status;
      meta.appendChild(statusText);
      text.appendChild(meta);
      item.appendChild(text);
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
    // (013.4 §9) إخفاء أسطح مركز التحكم داخل وضع المشروع — بلا
    // استدعاء showView (كان يخرج من وضع المشروع فورًا = دوران)
    if (window.ControlCenter) ControlCenter.hideSurfaces();
    setHashQuietly("#/project/" + projectId);
    attachLive();            // (013.1 §2) مستهلك فقط — البث على مستوى التطبيق
    setActiveTab(state.activeTab || "conversation");
    reconcile();
    startRuntimePolling();   // (013.4 §8) اللقطة القانونية حيّة
    loadProjects();
    if (window.LiveEvents) LiveEvents.connect();
  }

  function exitProjectMode() {
    state.projectId = null;
    state.snapshot = null;
    stopRuntimePolling();
    document.body.classList.remove("mode-project");
    view.hidden = true;
    var chat = document.querySelector(".chat-scroll");
    if (chat) chat.style.display = "";
    var composer = document.querySelector(".composer");
    if (composer) composer.style.display = "";
    setHashQuietly("");
    /* (013.1 §2+§6) لا نفصل معالج الأحداث الحية هنا أبدًا: الخروج
     * من الصفحة ليس إيقافًا ولا فقدانًا للبث. المعالج مفرد على مستوى
     * التطبيق (مسجّل مرة عند التحميل) ويحرس نفسه بنفسه — مغادرة
     * المشروع ثم العودة تجد البث حيًّا والمشهد يتحدث بلا refresh.
     * الفصل القديم هنا كان جذر فشل بوابة §6 (عودة لمشهد مجمّد). */
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
    // (013.4 §3) اللقطة القانونية تُغذي بطاقة التخطيط الحي — نفس
    // المصدر الذي تقرأه كل الواجهة (§8) لا اشتقاقًا موازيًا
    if (state.runtime && state.runtime.planning) {
      snapshot.planning = state.runtime.planning;
    }
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
      retryUrl: "/api/projects/" + snapshot.id + "/retry",
      viewPlan: function () {
        togglePlanDetails(snapshot);
      },
    });
    if (running && !state.streaming) attachRun(snapshot.id, 0);
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
      generate.textContent = "…بدأ التوليد (خلفي محدود)";
      Hub.fetchJSON("/api/projects/" + snapshot.id + "/plan/generate",
                     { method: "POST" })
        .then(function (out) {
          if (!out.ok) {
            generate.disabled = false;
            generate.textContent = "توليد الخطة";
            Hub.showErrorCard({
              kind: "planning.error", role: "system",
              text: "فشل بدء التوليد — " +
                ((out.j && out.j.detail) || ""),
              details: out.j || {},
            });
            return;
          }
          // (013.4 §1) الأمر خلفي — البطاقة الحية واللقطة يتكفلان
          reconcile();
          fetchRuntime();
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
    // تغيّر المشهد (بوابة/حالة/وظيفة) ← مصالحة خفيفة مضبوطة +
    // (W1-T02) تجديد اللقطة القانونية (الرأس والأزرار) معها — من
    // الأحداث لا من مؤقّت أعمى؛ ذاك المصدر نفسه يشغّل الدورة عند اللزوم
    if (window.ProjectLive && ProjectLive.isSceneChange(kind)) {
      if (reconcileTimer) clearTimeout(reconcileTimer);
      reconcileTimer = setTimeout(function () {
        reconcile();
        fetchRuntime();
      }, 250);
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
        Hub.showErrorCard({
          kind: "project.error", role: "system",
          text: "فشل إنشاء المشروع — " +
            ((out.j && out.j.detail) || ""),
          details: out.j || {},
        });
        return;
      }
      openProject(out.j.id);
      // (013.4 §1) التوليد أمر خلفي: يعيد فورًا وصف الجلسة — الخطة
      // تصل عبر التيار (PLANNING_* ← PLAN_CREATED) واللقطة الحية
      // تجدد المشهد بلا refresh؛ الفشل مصنّف يظهر ببطاقته الصادقة.
      Hub.fetchJSON("/api/projects/" + out.j.id + "/plan/generate",
                     { method: "POST" })
        .then(function (gen) {
          if (!gen.ok) {
            Hub.showErrorCard({
              kind: "planning.error", role: "system",
              text: "فشل بدء توليد الخطة — " +
                ((gen.j && gen.j.detail) || ""),
              details: gen.j || {},
            });
          }
          reconcile();
          fetchRuntime();
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

  /* (013.1 §5) زر «عودة للمحادثة» — كان في HTML بلا معالج أبدًا
   * (زر ميت): التنقل خارج المشروع كان Escape وحدها. الآن عودة
   * فورية — والخروج لا يوقف الوظيفة أبدًا (§1: مغادرة ≠ إيقاف). */
  var backBtn = $("pl-back");
  if (backBtn) {
    backBtn.addEventListener("click", function () {
      exitProjectMode();
    });
  }

  document.addEventListener("keydown", function (e) {
    /* (013.1 §6) الغياب أثناء التنفيذ مسموح دائمًا — الحارس القديم
     * (!state.streaming) كان يحبس المستخدم داخل المشروع أثناء
     * التنفيذ: عكس القاعدة الذهبية (المغادرة لا توقف شيئًا). */
    if (e.key === "Escape" &&
        document.body.classList.contains("mode-project")) {
      exitProjectMode();
    }
  });

  /* ---------- (013.4 §8+§10) اللقطة القانونية حيّة + رأس المشروع ---------- */

  function startRuntimePolling() {
    stopRuntimePolling();
    // (W1-T02) نبضة أولى واحدة — لا دورة عمياء بعدها؛
    // syncRuntimePolling (داخل fetchRuntime) يشغّل الدورة فقط
    // عندما تقول اللقطة إن المشروع يتقدم فعليًا.
    fetchRuntime();
  }

  function stopRuntimePolling() {
    if (state.runtimeTimer) {
      clearInterval(state.runtimeTimer);
      state.runtimeTimer = null;
    }
  }

  /* (W1-T02) دورة 3ث مشروطة: تعمل فقط واللقطة القانونية تقول إن
   * المشروع يتقدم (RUNNING/PLANNING/REVISING أو تخطيط خلفي نشط)
   * وتتوقف وحدها عند الخمول. الانتظار (موافقة/حجب/إيقاف مؤقت)
   * يعتمد الأحداث — لا دورة أبدية فوق مشروع ينتظر قرارًا أيامًا. */
  function syncRuntimePolling(runtime) {
    if (!runtime) return;
    var active = ["RUNNING", "PLANNING", "REVISING"]
      .indexOf(runtime.status || "") !== -1 ||
      (runtime.planning && runtime.planning.active);
    if (active && !state.runtimeTimer) {
      state.runtimeTimer = setInterval(fetchRuntime, 3000);
    } else if (!active && state.runtimeTimer) {
      clearInterval(state.runtimeTimer);
      state.runtimeTimer = null;
    }
  }

  function fetchRuntime() {
    if (state.projectId == null) return;
    Hub.fetchJSON("/api/projects/" + state.projectId + "/runtime")
      .then(function (out) {
        if (state.projectId == null) return;
        if (!out.ok) return;
        var previousPlanning = (state.runtime || {}).planning || {};
        var nextPlanning = out.j.planning || {};
        state.runtime = out.j;
        syncRuntimePolling(out.j);   // (W1-T02) الدورة مشروطة بالتقدم
        updateHeader(out.j);
        renderActiveTabContent();
        if (window.ControlCenter) ControlCenter.refreshRuns();
        // (013.4 §3) تغيّر حالة التخطيط (بدأ/انتهى/فشل) يُجدّد مشهد
        // المحادثة فورًا — بطاقة التخطيط الحي تظهر من اللقطة لا من
        // توقيت الأحداث وحده (لا سباق يخفيها)
        var changed = previousPlanning.state !== nextPlanning.state ||
          previousPlanning.active !== nextPlanning.active;
        if (changed && state.activeTab === "conversation") {
          reconcile();
        }
      });
  }

  /** رأس المشروع (§10): الحالة + المرحلة/الخطوة/البيئة/العامل + أزرار. */
  function updateHeader(runtime) {
    var meta = $("pl-head-meta");
    if (meta) {
      var parts = [];
      if (runtime.stage) {
        parts.push("المرحلة: " + (runtime.stage_labels
          ? (runtime.stage_labels[runtime.stage] || runtime.stage)
          : runtime.stage));
      }
      if (runtime.progress && runtime.progress.current_step) {
        parts.push("الخطوة: " +
          String(runtime.progress.current_step.objective || "")
            .slice(0, 40));
      }
      if (runtime.environment && runtime.environment.state === "READY") {
        parts.push("البيئة ✓");
      }
      if (runtime.worker) parts.push("العامل ✓");
      if (runtime.elapsed_s != null &&
          ["RUNNING", "PLANNING", "REVISING"].indexOf(
            runtime.status) !== -1) {
        parts.push("مضى " + Math.round(runtime.elapsed_s) + "ث");
      }
      meta.textContent = parts.join(" · ");
    }
    renderActions(runtime);
  }

  /** الأزرار الحقيقية (§11): كل زر أمر API دائم — لا زر يغير الواجهة فقط.
   * يُعاد البناء عند تغيّر الأفعال المتاحة فقط — لا تمزيق DOM كل نبضة
   * (النقرة قد تقع على زر فُصل للتو = سباق حي حقيقي). */
  var _lastActionsKey = "";

  function renderActions(runtime) {
    var bar = $("pl-actions");
    if (!bar) return;
    var available = runtime.available_actions || [];
    var key = state.projectId + "|" + available.join(",");
    if (key === _lastActionsKey && bar.children.length) return;
    _lastActionsKey = key;
    bar.textContent = "";

    function actionBtn(label, title, cls, onClick, confirmText) {
      var btn = document.createElement("button");
      btn.className = "pl-act-btn " + (cls || "");
      btn.textContent = label;
      btn.title = title;
      btn.addEventListener("click", function () {
        if (confirmText && !window.confirm(confirmText)) return;
        btn.disabled = true;
        btn.textContent = "…";
        onClick(function ok() {
          btn.disabled = false;
          btn.textContent = label;
          reconcile();
          fetchRuntime();
          loadProjects();
        });
      });
      return btn;
    }

    function post(url, body) {
      return function (done) {
        Hub.fetchJSON(url, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body || {}),
        }).then(function (out) {
          done();
          if (!out.ok && window.Hub) {
            Hub.showErrorCard({
              kind: "action.error", role: "system",
              text: "تعذر الأمر: " +
                ((out.j && out.j.detail) || url),
              details: out.j || {},
            });
          }
        }, done);
      };
    }

    if (available.indexOf("pause") !== -1) {
      bar.appendChild(actionBtn("⏸ إيقاف مؤقت",
        "إيقاف مؤقت قابل للاستئناف من نفس الوظيفة (013.4 §13)",
        "", post("/api/projects/" + state.projectId + "/pause",
                 { reason: "زر الإيقاف المؤقت" })));
    }
    if (available.indexOf("resume") !== -1) {
      bar.appendChild(actionBtn("▶ استئناف",
        "استئناف من آخر نقطة حفظ — نفس الوظيفة الدائمة",
        "primary", post("/api/projects/" + state.projectId +
                         "/resume", {})));
    }
    if (available.indexOf("run") !== -1) {
      bar.appendChild(actionBtn("▶ تشغيل",
        "تشغيل الحلقة الذاتية للخطة", "primary",
        post("/api/projects/" + state.projectId +
             "/preflight", {})));
    }
    if (available.indexOf("stop") !== -1) {
      bar.appendChild(actionBtn("■ إيقاف",
        "إيقاف نهائي دائم — كل الأحداث والأدلة تبقى محفوظة (§12)",
        "danger",
        post("/api/projects/" + state.projectId + "/stop",
             { reason: "زر الإيقاف", final: true }),
        "إيقاف نهائي؟ كل الأدلة والتاريخ تبقى محفوظة — والاستئناف غير متاح بعد الإيقاف النهائي."));
    }
    if (available.indexOf("retry") !== -1) {
      bar.appendChild(actionBtn("↻ إعادة",
        "إعادة آخر فشل — التخطيط أو الخطوة (§11)", "",
        post("/api/projects/" + state.projectId + "/retry", {})));
    }
    // قائمة ⋯: أفعال ثانوية (§31: الفعل الواحد أساسي والبقية في قائمة)
    var more = document.createElement("button");
    more.className = "pl-act-btn more";
    more.textContent = "⋯";
    more.title = "أفعال إضافية";
    var menu = document.createElement("div");
    menu.className = "pl-more-menu";
    menu.hidden = true;
    more.addEventListener("click", function (e) {
      e.stopPropagation();
      menu.hidden = !menu.hidden;
    });
    document.addEventListener("click", function () {
      menu.hidden = true;
    });

    function menuItem(label, onClick) {
      var item = document.createElement("button");
      item.textContent = label;
      item.addEventListener("click", function () {
        menu.hidden = true;
        onClick();
      });
      menu.appendChild(item);
      return item;
    }

    menuItem("نسخة جديدة (Duplicate)", function () {
      Hub.fetchJSON("/api/projects/" + state.projectId + "/duplicate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      }).then(function (out) {
        if (out.ok) openProject(out.j.id);
      });
    });
    menuItem("إعادة تسمية", function () {
      var name = window.prompt("الاسم الجديد:", runtime.name || "");
      if (!name) return;
      Hub.fetchJSON("/api/projects/" + state.projectId + "/rename", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: name }),
      }).then(function () {
        reconcile();
        loadProjects();
      });
    });
    if (available.indexOf("archive") !== -1) {
      menuItem("أرشفة (قابلة للاسترجاع)", function () {
        Hub.fetchJSON("/api/projects/" + state.projectId + "/archive", {
          method: "POST",
        }).then(function (out) {
          if (out.ok) {
            exitProjectMode();
            loadProjects();
          }
        });
      });
    }
    var moreWrap = document.createElement("span");
    moreWrap.className = "pl-more-wrap";
    moreWrap.appendChild(more);
    moreWrap.appendChild(menu);
    bar.appendChild(moreWrap);
  }

  /* ---------- (013.4 §9) تبويبات المشروع ---------- */

  function setActiveTab(tab) {
    state.activeTab = tab;
    document.querySelectorAll(".pl-tab").forEach(function (btn) {
      btn.classList.toggle("active",
        btn.getAttribute("data-tab") === tab);
    });
    var scene = $("pl-scene");
    var body = $("pl-tab-body");
    var isConversation = tab === "conversation";
    if (scene) scene.hidden = !isConversation;
    if (body) body.hidden = isConversation;
    renderActiveTabContent();
  }

  function renderActiveTabContent() {
    if (state.projectId == null) return;
    var body = $("pl-tab-body");
    if (!body || state.activeTab === "conversation") return;
    if (!window.WorkflowView || !state.runtime) return;
    var wv = window.WorkflowView;
    var tab = state.activeTab;
    // لا نعيد بناء المحتوى كل نبضة إلا لسير العمل والنظرة (بيانات حية)
    if (tab === "workflow") {
      wv.renderWorkflowTab(body, state.runtime);
    } else if (tab === "overview") {
      wv.renderOverviewTab(body, state.runtime, state.snapshot);
    } else if (body.getAttribute("data-rendered") !==
               tab + ":" + state.projectId) {
      // تبويبات القراءة (الأدلة/المخرجات/التاريخ) تُبنى مرة عند الفتح
      body.setAttribute("data-rendered", tab + ":" + state.projectId);
      if (tab === "evidence") {
        wv.renderEvidenceTab(body, state.projectId);
      } else if (tab === "artifacts") {
        wv.renderArtifactsTab(body, state.projectId);
      } else if (tab === "history") {
        wv.renderHistoryTab(body, state.projectId);
      }
    }
  }

  document.querySelectorAll(".pl-tab").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var body = $("pl-tab-body");
      if (body) body.setAttribute("data-rendered", "");
      setActiveTab(btn.getAttribute("data-tab"));
    });
  });

  window.HubProjects = {
    openProject: openProject,
    exitProjectMode: exitProjectMode,
    reconcile: reconcile,
    createProjectFromObjective: createProjectFromObjective,
    loadProjects: loadProjects,
    fetchRuntime: fetchRuntime,
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
