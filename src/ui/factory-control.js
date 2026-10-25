/* FACTORY CONTROL ROOM — غرفة التحكم بالمصنع (E2-UI).
 * واجهة تشغيل حقيقية فوق الـ Orchestrator والـ Agent Runtime.
 * لا Mock — كل عنصر له مصدر حقيقي من النظام.
 */
(function () {
  "use strict";

  if (!window.Hub) return;
  var Hub = window.Hub;
  var $ = Hub.$;
  var esc = Hub.esc;
  var fmtTime = Hub.fmtTime;
  var fetchJSON = Hub.fetchJSON;
  var getStream = Hub.getStream;

  var factoryView = $("factory-view");
  var factoryBody = $("factory-body");
  var factoryBack = $("factory-back");
  var factorySystemStatus = $("factory-system-status");
  var factoryNav = document.querySelector('[data-nav="factory"]');

  var state = {
    mode: "overview",           // overview | create-mission | mission-view | run-view
    activeMissionId: null,
    activeRunId: null,
    sseController: null,
    eventBuffer: [],
    missions: [],
    runs: [],
    agents: [],
    tasks: [],
    artifacts: [],
    events: [],
    verifications: [],
    humanGates: [],
    systemConnected: false,
  };

  // ---------- Navigation ----------
  function showFactoryView() {
    document.body.classList.add("mode-factory");
    factoryView.hidden = false;
    renderFactory();
    checkSystemConnection();
    // التحميل يُطلق من هنا فقط — كان داخل renderOverview فيصل حلقة
    // لا نهائية (رسم ← تحميل ← رسم...) بعاصفة طلبات؛ انظر queueOverviewRender.
    if (state.mode === "overview") loadOverviewData();
  }

  function hideFactoryView() {
    factoryView.hidden = true;
    document.body.classList.remove("mode-factory");
    stopSSE();
  }

  factoryBack.addEventListener("click", function () {
    if (window.HubProjects && document.body.classList.contains("mode-project")) {
      window.HubProjects.exitProjectMode();
    }
    hideFactoryView();
    if (window.Hub) window.Hub.setMode("chat");
  });

  factoryNav.addEventListener("click", function () {
    if (factoryView.hidden) {
      showFactoryView();
    } else {
      hideFactoryView();
    }
  });

  // ---------- System Connection Check ----------
  function checkSystemConnection() {
    fetchJSON("/health").then(function (out) {
      if (out.ok && out.j) {
        state.systemConnected = true;
        factorySystemStatus.textContent = "SYSTEM: CONNECTED";
        factorySystemStatus.classList.remove("bad");
      } else {
        state.systemConnected = false;
        factorySystemStatus.textContent = "SYSTEM: DISCONNECTED";
        factorySystemStatus.classList.add("bad");
      }
    }, function () {
      state.systemConnected = false;
      factorySystemStatus.textContent = "SYSTEM: DISCONNECTED";
      factorySystemStatus.classList.add("bad");
    });
  }

  // ---------- Main Render ----------
  function renderFactory() {
    factoryBody.innerHTML = "";
    switch (state.mode) {
      case "overview":
        renderOverview();
        break;
      case "create-mission":
        renderCreateMission();
        break;
      case "mission-view":
        renderMissionView();
        break;
      case "run-view":
        renderRunView();
        break;
    }
  }

  // ---------- Overview Panel ----------
  function renderOverview() {
    var html = '<div class="factory-overview">';

    // System Status Card
    html += '<div class="fc-card fc-system-card">';
    html += '<h3>نظام المصنع</h3>';
    html += '<div class="fc-grid-2">';
    html += '<div class="fc-stat">';
    html += '<span class="fc-stat-label">حالة الاتصال</span>';
    html += '<span class="fc-stat-value ' + (state.systemConnected ? "ok" : "bad") + '">' +
      (state.systemConnected ? "متصل" : "منقطع") + "</span>";
    html += '</div>';
    html += '<div class="fc-stat">';
    html += '<span class="fc-stat-label">المهام الكلية</span>';
    html += '<span class="fc-stat-value">' + state.missions.length + "</span>";
    html += '</div>';
    html += '<div class="fc-stat">';
    html += '<span class="fc-stat-label">التشغيلات النشطة</span>';
    html += '<span class="fc-stat-value">' + state.runs.filter(function (r) { return r.status === "RUNNING"; }).length + "</span>";
    html += '</div>';
    html += '<div class="fc-stat">';
    html += '<span class="fc-stat-label">الوكلاء المتاحون</span>';
    html += '<span class="fc-stat-value">' + state.agents.filter(function (a) { return a.status === "AVAILABLE"; }).length + "</span>";
    html += '</div>';
    html += '</div>';
    html += '</div>';

    // Quick Actions
    html += '<div class="fc-card">';
    html += '<h3>إجراءات سريعة</h3>';
    html += '<div class="fc-actions">';
    html += '<button class="btn primary" id="fc-new-mission">+ مهمة جديدة</button>';
    html += '<button class="btn" id="fc-refresh-missions">تحديث المهام</button>';
    html += '<button class="btn" id="fc-refresh-runs">تحديث التشغيلات</button>';
    html += '<button class="btn" id="fc-refresh-agents">تحديث الوكلاء</button>';
    html += '</div>';
    html += '</div>';

    // Active Runs Summary
    html += '<div class="fc-card">';
    html += '<h3>التشغيلات الحديثة</h3>';
    if (state.runs.length === 0) {
      html += '<div class="fc-empty">لا توجد تشغيلات — ابدأ مهمة جديدة</div>';
    } else {
      html += '<div class="fc-runs-list">';
      state.runs.slice(0, 10).forEach(function (run) {
        html += renderRunSummary(run);
      });
      html += '</div>';
    }
    html += '</div>';

    // Active Missions Summary
    html += '<div class="fc-card">';
    html += '<h3>المهام الحديثة</h3>';
    if (state.missions.length === 0) {
      html += '<div class="fc-empty">لا توجد مهام</div>';
    } else {
      html += '<div class="fc-missions-list">';
      state.missions.slice(0, 10).forEach(function (mission) {
        html += renderMissionSummary(mission);
      });
      html += '</div>';
    }
    html += '</div>';

    html += '</div>';
    factoryBody.innerHTML = html;
    wireOverviewButtons();
    // لا استدعاء لـ loadOverviewData هنا — المحفّز الوحيد showFactoryView
    // وأزرار التحديث؛ وضعه هنا كان يسبب حلقة رسم/تحميل لا نهائية.
  }

  function renderRunSummary(run) {
    var statusClass = run.status === "RUNNING" ? "ok" : (run.status === "COMPLETED" ? "ok" : (run.status === "FAILED" ? "bad" : "warn"));
    var statusText = {
      "RUNNING": "تشغيل",
      "COMPLETED": "مكتمل",
      "FAILED": "فاشل",
      "STOPPED": "متوقف",
      "PAUSED": "موقوف",
    }[run.status] || run.status;
    return '<div class="fc-run-row" data-run-id="' + esc(run.run_id) + '">' +
      '<div class="fc-run-info">' +
      '<span class="fc-run-id">' + esc(run.run_id) + '</span>' +
      '<span class="fc-run-mission">مهمة: ' + esc(run.mission_id || "—") + '</span>' +
      '</div>' +
      '<span class="fc-run-status ' + statusClass + '">' + statusText + '</span>' +
      '</div>';
  }

  function renderMissionSummary(mission) {
    var state = mission.state || mission.status || "";
    var statusClass = state === "EXECUTING" ? "ok" : (state === "EVIDENCED" || state === "VERIFIED" ? "ok" : (state === "FAILED" ? "bad" : "warn"));
    var statusText = {
      "DRAFT": "مسودة",
      "RECEIVED": "مستلمة",
      "ANALYZING": "تحليل",
      "PLANNING": "تخطيط",
      "DESIGNING": "تصميم",
      "REVIEWING": "مراجعة",
      "APPROVED": "معتمدة",
      "AWAITING_APPROVAL": "بانتظار الاعتماد",
      "EXECUTING": "تنفيذ",
      "EXECUTED": "منفذة",
      "VERIFYING": "تحقق",
      "EVIDENCED": "مثبتة",
      "VERIFIED": "موثقة",
      "FAILED": "فاشلة",
      "STOPPED": "متوقفة",
      "ARCHIVED": "مؤرشفة",
    }[state] || state || "غير محدد";
    return '<div class="fc-mission-row" data-mission-id="' + esc(mission.mission_id || mission.id || "—") + '">' +
      '<div class="fc-mission-info">' +
      '<span class="fc-mission-id">' + esc(mission.mission_id || mission.id || "—") + '</span>' +
      '<span class="fc-mission-title">' + esc(mission.user_request || mission.name || mission.objective || "بدون عنوان") + '</span>' +
      '</div>' +
      '<span class="fc-mission-status ' + statusClass + '">' + esc(statusText) + '</span>' +
      '</div>';
  }

  function wireOverviewButtons() {
    $("fc-new-mission")?.addEventListener("click", function () {
      state.mode = "create-mission";
      renderFactory();
    });
    $("fc-refresh-missions")?.addEventListener("click", loadMissions);
    $("fc-refresh-runs")?.addEventListener("click", loadRuns);
    $("fc-refresh-agents")?.addEventListener("click", loadAgents);

    factoryBody.querySelectorAll(".fc-run-row").forEach(function (row) {
      row.addEventListener("click", function () {
        var runId = row.getAttribute("data-run-id");
        openRunView(runId);
      });
    });

    factoryBody.querySelectorAll(".fc-mission-row").forEach(function (row) {
      row.addEventListener("click", function () {
        var missionId = row.getAttribute("data-mission-id");
        openMissionView(missionId);
      });
    });
  }

  // ---------- Create Mission ----------
  function renderCreateMission() {
    var html = '<div class="factory-create-mission">';
    html += '<div class="fc-card">';
    html += '<h3>مهمة جديدة</h3>';
    html += '<div class="fc-form">';
    html += '<div class="fc-field">';
    html += '<label>عنوان المهمة</label>';
    html += '<input type="text" id="fc-mission-title" placeholder="مثال: إصلاح خطأ في الوحدة X">';
    html += '</div>';
    html += '<div class="fc-field">';
    html += '<label>الهدف</label>';
    html += '<textarea id="fc-mission-objective" rows="4" placeholder="صف الهدف بوضوح..."></textarea>';
    html += '</div>';
    html += '<div class="fc-field">';
    html += '<label>المستودع / مساحة العمل</label>';
    html += '<input type="text" id="fc-mission-repo" placeholder="مسار محلي أو URL">';
    html += '</div>';
    html += '<div class="fc-field">';
    html += '<label>القيود (اختياري)</label>';
    html += '<textarea id="fc-mission-constraints" rows="3" placeholder="قيود تقنية، ميزانية، نماذج محددة..."></textarea>';
    html += '</div>';
    html += '<div class="fc-field">';
    html += '<label>معايير القبول (سطر لكل معيار)</label>';
    html += '<textarea id="fc-mission-criteria" rows="4" placeholder="معيار 1\nمعيار 2\n..."></textarea>';
    html += '</div>';
    html += '<div class="fc-field">';
    html += '<label>سياسة موافقة المالك</label>';
    html += '<select id="fc-mission-approval">';
    html += '<option value="required">مطلوبة (افتراضي)</option>';
    html += '<option value="optional">اختيارية</option>';
    html += '<option value="auto">تلقائية بعد التحقق</option>';
    html += '</select>';
    html += '</div>';
    html += '<div class="fc-field">';
    html += '<label>ميزانية التنفيذ (اختياري)</label>';
    html += '<input type="text" id="fc-mission-budget" placeholder="مثال: 100000 tokens, 30 دقيقة">';
    html += '</div>';
    html += '</div>';
    html += '<div class="fc-actions">';
    html += '<button class="btn primary" id="fc-launch-mission">إطلاق المهمة</button>';
    html += '<button class="btn" id="fc-cancel-create">إلغاء</button>';
    html += '</div>';
    html += '</div>';
    html += '</div>';
    factoryBody.innerHTML = html;
    wireCreateMissionButtons();
  }

  function wireCreateMissionButtons() {
    $("fc-launch-mission")?.addEventListener("click", launchMission);
    $("fc-cancel-create")?.addEventListener("click", function () {
      state.mode = "overview";
      renderFactory();
    });
  }

  function launchMission() {
    var title = $("fc-mission-title").value.trim();
    var objective = $("fc-mission-objective").value.trim();
    var repo = $("fc-mission-repo").value.trim();
    var constraints = $("fc-mission-constraints").value.trim();
    var criteriaText = $("fc-mission-criteria").value.trim();
    var approval = $("fc-mission-approval").value;
    var budget = $("fc-mission-budget").value.trim();

    if (!title || !objective) {
      alert("العنوان والهدف مطلوبان");
      return;
    }

    var criteria = criteriaText.split("\n").filter(function (c) { return c.trim(); });

    var btn = $("fc-launch-mission");
    btn.disabled = true;
    btn.textContent = "جاري الإطلاق...";

    // Build mission spec
    var goal = objective + (repo ? "\n\nRepository: " + repo : "") +
      (constraints ? "\n\nConstraints: " + constraints : "") +
      (budget ? "\n\nBudget: " + budget : "");

    fetchJSON("/api/mission/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ goal: goal })
    }).then(function (resp) {
      btn.disabled = false;
      btn.textContent = "إطلاق المهمة";
      if (!resp.ok) {
        alert("فشل الإطلاق: " + (resp.j?.detail || "خطأ غير معروف"));
        return;
      }
      // The SSE stream will emit events - we need to capture the mission/run IDs
      // For now, switch to run view and connect SSE
      state.mode = "run-view";
      renderFactory();
      connectMissionSSE();
    }, function (err) {
      btn.disabled = false;
      btn.textContent = "إطلاق المهمة";
      alert("فشل الإطلاق: " + err.message);
    });
  }

  // ---------- Mission View ----------
  function openMissionView(missionId) {
    state.activeMissionId = missionId;
    state.mode = "mission-view";
    renderFactory();
    loadMissionData(missionId);
  }

  function renderMissionView() {
    var html = '<div class="factory-mission-view">';
    html += '<div class="fc-card">';
    html += '<h3>المهمة: ' + esc(state.activeMissionId) + '</h3>';
    html += '<div class="fc-mission-tabs">';
    html += '<button class="fc-tab' + (state.missionTab === "overview" ? " active" : "") + '" data-tab="overview">نظرة عامة</button>';
    html += '<button class="fc-tab' + (state.missionTab === "plan" ? " active" : "") + '" data-tab="plan">الخطة</button>';
    html += '<button class="fc-tab' + (state.missionTab === "runs" ? " active" : "") + '" data-tab="runs">التشغيلات</button>';
    html += '<button class="fc-tab' + (state.missionTab === "tasks" ? " active" : "") + '" data-tab="tasks">المهام</button>';
    html += '<button class="fc-tab' + (state.missionTab === "agents" ? " active" : "") + '" data-tab="agents">الوكلاء</button>';
    html += '<button class="fc-tab' + (state.missionTab === "artifacts" ? " active" : "") + '" data-tab="artifacts">المخرجات</button>';
    html += '<button class="fc-tab' + (state.missionTab === "evidence" ? " active" : "") + '" data-tab="evidence">الأدلة</button>';
    html += '<button class="fc-tab' + (state.missionTab === "verification" ? " active" : "") + '" data-tab="verification">التحقق</button>';
    html += '<button class="fc-tab' + (state.missionTab === "events" ? " active" : "") + '" data-tab="events">الأحداث</button>';
    html += '</div>';
    html += '<div id="fc-mission-tab-body"></div>';
    html += '</div>';
    html += '</div>';
    factoryBody.innerHTML = html;

    state.missionTab = state.missionTab || "overview";
    wireMissionTabs();
    renderMissionTab();
  }

  function wireMissionTabs() {
    factoryBody.querySelectorAll(".fc-tab").forEach(function (tab) {
      tab.addEventListener("click", function () {
        state.missionTab = tab.getAttribute("data-tab");
        renderMissionView();
      });
    });
  }

  function renderMissionTab() {
    var body = $("fc-mission-tab-body");
    if (!body) return;
    switch (state.missionTab) {
      case "overview":
        renderMissionOverview(body);
        break;
      case "plan":
        renderMissionPlan(body);
        break;
      case "runs":
        renderMissionRuns(body);
        break;
      case "tasks":
        renderMissionTasks(body);
        break;
      case "agents":
        renderMissionAgents(body);
        break;
      case "artifacts":
        renderMissionArtifacts(body);
        break;
      case "evidence":
        renderMissionEvidence(body);
        break;
      case "verification":
        renderMissionVerification(body);
        break;
      case "events":
        renderMissionEvents(body);
        break;
    }
  }

  function renderMissionOverview(body) {
    fetchJSON("/api/mission/status").then(function (out) {
      if (!out.ok) {
        body.innerHTML = '<div class="fc-error">تعذر تحميل حالة المهمة</div>';
        return;
      }
      var data = out.j;
      var html = '<div class="fc-grid-2">';
      html += '<div><strong>Cycle ID:</strong> ' + esc(data.cycle_id || "—") + '</div>';
      html += '<div><strong>الحالة:</strong> <span class="' + (data.running ? "ok" : "bad") + '">' + (data.running ? "تشغيل" : "متوقفة") + '</span></div>';
      html += '<div><strong>آخر حالة:</strong> ' + esc(data.last_state || "—") + '</div>';
      html += '<div><strong>Stop Requested:</strong> ' + (data.stop_requested ? "نعم" : "لا") + '</div>';
      html += '</div>';
      if (data.last_result) {
        html += '<h4>النتيجة الأخيرة</h4>';
        html += '<pre class="fc-json">' + esc(JSON.stringify(data.last_result, null, 2)) + '</pre>';
      }
      body.innerHTML = html;
    });
  }

  function renderMissionPlan(body) {
    body.innerHTML = '<div class="fc-loading">جاري تحميل الخطة...</div>';
    fetchJSON("/api/projects/" + state.activeMissionId + "/plan").then(function (out) {
      if (!out.ok) {
        body.innerHTML = '<div class="fc-error">تعذر تحميل الخطة</div>';
        return;
      }
      var plan = out.j;
      var html = '<pre class="fc-json">' + esc(JSON.stringify(plan, null, 2)) + '</pre>';
      body.innerHTML = html;
    });
  }

  function renderMissionRuns(body) {
    body.innerHTML = '<div class="fc-loading">جاري تحميل التشغيلات...</div>';
    fetchJSON("/api/projects/" + state.activeMissionId).then(function (out) {
      if (!out.ok) {
        body.innerHTML = '<div class="fc-error">تعذر تحميل المشروع</div>';
        return;
      }
      var project = out.j;
      var html = '<div class="fc-runs-list">';
      (project.runs || []).forEach(function (run) {
        html += renderRunDetail(run);
      });
      html += '</div>';
      body.innerHTML = html;
      body.querySelectorAll(".fc-run-detail").forEach(function (el) {
        el.addEventListener("click", function () {
          openRunView(el.getAttribute("data-run-id"));
        });
      });
    });
  }

  function renderRunDetail(run) {
    var statusClass = run.status === "RUNNING" ? "ok" : (run.status === "COMPLETED" ? "ok" : (run.status === "FAILED" ? "bad" : "warn"));
    return '<div class="fc-run-detail" data-run-id="' + esc(run.run_id) + '">' +
      '<div class="fc-run-header">' +
      '<span class="fc-run-id">' + esc(run.run_id) + '</span>' +
      '<span class="fc-run-status ' + statusClass + '">' + run.status + '</span>' +
      '</div>' +
      '<div class="fc-run-meta">بدأ: ' + esc(run.started_at || "—") + ' |phase: ' + esc(run.current_phase || "—") + '</div>' +
      '</div>';
  }

  function renderMissionTasks(body) {
    body.innerHTML = '<div class="fc-loading">جاري تحميل المهام...</div>';
    fetchJSON("/api/projects/" + state.activeMissionId + "/steps").then(function (out) {
      if (!out.ok) {
        body.innerHTML = '<div class="fc-error">تعذر تحميل المهام</div>';
        return;
      }
      var steps = out.j.steps || [];
      var html = '<div class="fc-tasks-tree">';
      steps.forEach(function (step) {
        html += renderTaskNode(step, 0);
      });
      html += '</div>';
      body.innerHTML = html;
    });
  }

  function renderTaskNode(step, depth) {
    var statusClass = step.status === "COMPLETED" ? "ok" : (step.status === "RUNNING" ? "warn" : (step.status === "FAILED" ? "bad" : ""));
    var indent = depth * 20;
    var html = '<div class="fc-task-node" style="padding-inline-start:' + indent + 'px" data-task-id="' + esc(step.step_id) + '">';
    html += '<span class="fc-task-status ' + statusClass + '">●</span>';
    html += '<span class="fc-task-name">' + esc(step.name || step.step_id) + '</span>';
    html += '<span class="fc-task-state">' + esc(step.status) + '</span>';
    if (step.agent_id) html += '<span class="fc-task-agent">@' + esc(step.agent_id) + '</span>';
    html += '</div>';
    (step.sub_steps || []).forEach(function (sub) {
      html += renderTaskNode(sub, depth + 1);
    });
    return html;
  }

  function renderMissionAgents(body) {
    body.innerHTML = '<div class="fc-loading">جاري تحميل الوكلاء...</div>';
    fetchJSON("/api/harness/roles").then(function (out) {
      if (!out.ok) {
        body.innerHTML = '<div class="fc-error">تعذر تحميل الوكلاء</div>';
        return;
      }
      var roles = out.j.roles || [];
      var html = '<div class="fc-agents-grid">';
      roles.forEach(function (role) {
        var sel = role.live_selection || role.selection || {};
        var ready = sel.ready;
        html += '<div class="fc-agent-card">';
        html += '<h4>' + esc(role.display || role.label || "—") +
          ' <span class="fc-agent-key" dir="ltr">(' + esc(role.role || role.key || "—") + ')</span></h4>';
        if (typeof ready === "boolean") {
          html += '<div class="fc-agent-ready">حالة التهيئة: <span class="' + (ready ? "ok" : "bad") + '">' + (ready ? "جاهز" : "غير مهيأ") + '</span></div>';
        }
        html += '<div class="fc-agent-meta">';
        html += '<div>مزود: ' + esc(sel.provider || "—") + '</div>';
        html += '<div>نموذج: ' + esc(sel.model || "—") + '</div>';
        html += '<div>تكوين: ' + esc(sel.configuration || "—") + '</div>';
        html += '</div>';
        html += '</div>';
      });
      html += '</div>';
      body.innerHTML = html;
    });
  }

  function renderMissionArtifacts(body) {
    body.innerHTML = '<div class="fc-loading">جاري تحميل المخرجات...</div>';
    fetchJSON("/api/projects/" + state.activeMissionId + "/artifacts").then(function (out) {
      if (!out.ok) {
        body.innerHTML = '<div class="fc-error">تعذر تحميل المخرجات</div>';
        return;
      }
      var artifacts = out.j.artifacts || [];
      var html = '<div class="fc-artifacts-list">';
      artifacts.forEach(function (art) {
        html += '<div class="fc-artifact-row" data-artifact-id="' + esc(art.artifact_id) + '">';
        html += '<span class="fc-artifact-type">' + esc(art.type || "file") + '</span>';
        html += '<span class="fc-artifact-name">' + esc(art.name || art.path) + '</span>';
        html += '<span class="fc-artifact-sha" dir="ltr">' + esc(art.sha256?.slice(0, 16) + "…" || "—") + '</span>';
        html += '<span class="fc-artifact-task">مهمة: ' + esc(art.task_id || "—") + '</span>';
        html += '</div>';
      });
      html += '</div>';
      body.innerHTML = html;
    });
  }

  function renderMissionEvidence(body) {
    body.innerHTML = '<div class="fc-loading">جاري تحميل الأدلة...</div>';
    fetchJSON("/api/projects/" + state.activeMissionId + "/evidence").then(function (out) {
      if (!out.ok) {
        body.innerHTML = '<div class="fc-error">تعذر تحميل الأدلة</div>';
        return;
      }
      var evidence = out.j.evidence || [];
      var html = '<div class="fc-evidence-list">';
      evidence.forEach(function (ev) {
        html += '<div class="fc-evidence-row">';
        html += '<span class="fc-evidence-id" dir="ltr">' + esc(ev.evidence_id) + '</span>';
        html += '<span class="fc-evidence-type">' + esc(ev.content_type) + '</span>';
        html += '<span class="fc-evidence-hash" dir="ltr">' + esc(ev.evidence_hash.slice(0, 16) + "…") + '</span>';
        html += '<span class="fc-evidence-task">مهمة: ' + esc(ev.task_id || "—") + '</span>';
        html += '</div>';
      });
      html += '</div>';
      body.innerHTML = html;
    });
  }

  function renderMissionVerification(body) {
    body.innerHTML = '<div class="fc-loading">جاري تحميل التحقق...</div>';
    fetchJSON("/api/projects/" + state.activeMissionId + "/verify").then(function (out) {
      if (!out.ok) {
        body.innerHTML = '<div class="fc-error">تعذر تحميل التحقق</div>';
        return;
      }
      var html = '<pre class="fc-json">' + esc(JSON.stringify(out.j, null, 2)) + '</pre>';
      body.innerHTML = html;
    });
  }

  function renderEventRow(ev) {
    var time = ev.timestamp ? new Date(ev.timestamp).toLocaleTimeString() : "—";
    var kind = ev.kind || ev.event_type || "event";
    var taskId = ev.correlation_id || ev.payload?.task_id || ev.payload?.step_id || "—";
    var agentId = ev.payload?.agent_id || "—";
    return '<div class="fc-event-row">' +
      '<span class="fc-event-time">' + esc(time) + '</span>' +
      '<span class="fc-event-type">' + esc(kind) + '</span>' +
      '<span class="fc-event-task">' + esc(taskId) + '</span>' +
      '<span class="fc-event-agent">' + esc(agentId) + '</span>' +
      '</div>';
  }

  function renderMissionEvents(body) {
    body.innerHTML = '<div class="fc-loading">جاري تحميل الأحداث...</div>';
    fetchJSON("/api/projects/" + state.activeMissionId + "/events").then(function (out) {
      if (!out.ok) {
        body.innerHTML = '<div class="fc-error">تعذر تحميل الأحداث</div>';
        return;
      }
      var events = out.j.events || [];
      var html = '<div class="fc-events-stream">';
      events.slice(-100).forEach(function (ev) {
        html += renderEventRow(ev);
      });
      html += '</div>';
      body.innerHTML = html;
    });
  }

  // ---------- Run View ----------
  function openRunView(runId) {
    state.activeRunId = runId;
    state.mode = "run-view";
    renderFactory();
    loadRunData(runId);
    connectRunSSE(runId);
  }

  function renderRunView() {
    var html = '<div class="factory-run-view">';
    html += '<div class="fc-run-header">';
    html += '<h3>تشغيل: ' + esc(state.activeRunId) + '</h3>';
    html += '<span class="fc-run-live-badge" id="fc-run-status">CONNECTING...</span>';
    html += '</div>';

    html += '<div class="fc-grid-3">';
    // Left: Timeline
    html += '<div class="fc-panel">';
    html += '<h4>التسلسل الزمني</h4>';
    html += '<div id="fc-timeline" class="fc-timeline"></div>';
    html += '</div>';

    // Center: Task Graph
    html += '<div class="fc-panel">';
    html += '<h4>رسم المهام</h4>';
    html += '<div id="fc-task-graph" class="fc-task-graph"></div>';
    html += '</div>';

    // Right: Current Agent/Action
    html += '<div class="fc-panel">';
    html += '<h4>الوكيل الحالي</h4>';
    html += '<div id="fc-current-agent" class="fc-current-agent"></div>';
    html += '<h4>الإجراء الحالي</h4>';
    html += '<div id="fc-current-action" class="fc-current-action"></div>';
    html += '</div>';
    html += '</div>';

    // Bottom: Event Stream
    html += '<div class="fc-panel fc-full-width">';
    html += '<h4>تدفق الأحداث المباشر</h4>';
    html += '<div id="fc-event-stream" class="fc-event-stream"></div>';
    html += '</div>';

    html += '</div>';
    factoryBody.innerHTML = html;
  }

  function connectRunSSE(runId) {
    stopSSE();
    var statusEl = $("fc-run-status");
    state.sseController = getStream("/api/projects/" + runId + "/run/stream");
    state.sseController.then(function () {
      if (statusEl) statusEl.textContent = "DISCONNECTED";
      statusEl?.classList.remove("live");
      statusEl?.classList.add("disconnected");
    }).catch(function () {
      if (statusEl) statusEl.textContent = "ERROR";
      statusEl?.classList.remove("live");
      statusEl?.classList.add("disconnected");
    });

    // Listen for events via the global renderEvent
    // (007 BUG-02) كان الأصل يُلتقط من Hub.renderEvent المُغلَّف نفسه عند
    // كل زيارة لعرض تشغيل فتتكدس الأغلفة بلا نهاية. يُحفظ الأصل مرة واحدة.
    if (!Hub.__factoryOriginalRenderEvent) {
      Hub.__factoryOriginalRenderEvent = Hub.renderEvent;
    }
    Hub.renderEvent = function (event) {
      if (state.mode === "run-view" && state.activeRunId === runId) {
        appendEventToStream(event);
        updateTimeline(event);
        updateTaskGraph(event);
        updateCurrentAgent(event);
        updateCurrentAction(event);
      }
      Hub.__factoryOriginalRenderEvent(event);
    };
    if (statusEl) {
      statusEl.textContent = "LIVE";
      statusEl.classList.add("live");
      statusEl.classList.remove("disconnected");
    }
  }

  function connectMissionSSE() {
    stopSSE();
    state.sseController = getStream("/api/mission/stream");
  }

  function stopSSE() {
    if (state.sseController) {
      // The getStream returns a promise, we can't easily cancel it
      // but we can stop listening
      state.sseController = null;
    }
    // (007 BUG-02) استرجاع حقيقي للأصل المحفوظ مرة واحدة — لا no-op
    if (Hub.__factoryOriginalRenderEvent) {
      Hub.renderEvent = Hub.__factoryOriginalRenderEvent;
      Hub.__factoryOriginalRenderEvent = null;
    }
  }

  function appendEventToStream(event) {
    var stream = $("fc-event-stream");
    if (!stream) return;
    var row = document.createElement("div");
    row.className = "fc-event-row";
    var time = event.timestamp ? new Date(event.timestamp).toLocaleTimeString() : "—";
    row.innerHTML = '<span class="fc-event-time">' + esc(time) + '</span>' +
      '<span class="fc-event-type">' + esc(event.kind || event.event_type) + '</span>' +
      '<span class="fc-event-task">' + esc(event.correlation_id || "—") + '</span>' +
      '<span class="fc-event-agent">' + esc(event.payload?.agent_id || "—") + '</span>';
    row.addEventListener("click", function () {
      Hub.openModal(event);
    });
    stream.insertBefore(row, stream.firstChild);
    // Keep only last 200 events
    while (stream.children.length > 200) {
      stream.removeChild(stream.lastChild);
    }
  }

  function updateTimeline(event) {
    var timeline = $("fc-timeline");
    if (!timeline) return;
    // Add event to timeline
    var item = document.createElement("div");
    item.className = "fc-timeline-item";
    var time = event.timestamp ? new Date(event.timestamp).toLocaleTimeString() : "—";
    item.innerHTML = '<span class="fc-tl-time">' + esc(time) + '</span>' +
      '<span class="fc-tl-type">' + esc(event.kind || event.event_type) + '</span>' +
      '<span class="fc-tl-detail">' + esc(JSON.stringify(event.payload || {}).slice(0, 80)) + '</span>';
    timeline.insertBefore(item, timeline.firstChild);
    while (timeline.children.length > 50) {
      timeline.removeChild(timeline.lastChild);
    }
  }

  function updateTaskGraph(event) {
    // Update task graph visualization based on events
    var graph = $("fc-task-graph");
    if (!graph) return;
    // For now, just show a placeholder - real implementation would track task states
    if (event.kind === "task.created" || event.kind === "TASK_CREATED") {
      var taskId = event.payload?.task_id || event.correlation_id;
      var name = event.payload?.name || event.payload?.task_key || taskId;
      var node = document.createElement("div");
      node.className = "fc-task-graph-node pending";
      node.setAttribute("data-task-id", taskId);
      node.textContent = name;
      graph.appendChild(node);
    } else if (event.kind === "task.completed" || event.kind === "TASK_COMPLETED") {
      var taskId = event.payload?.task_id || event.correlation_id;
      var node = graph.querySelector('[data-task-id="' + taskId + '"]');
      if (node) {
        node.className = "fc-task-graph-node completed";
      }
    } else if (event.kind === "task.failed" || event.kind === "TASK_FAILED") {
      var taskId = event.payload?.task_id || event.correlation_id;
      var node = graph.querySelector('[data-task-id="' + taskId + '"]');
      if (node) {
        node.className = "fc-task-graph-node failed";
      }
    } else if (event.kind === "task.running" || event.kind === "TASK_RUNNING") {
      var taskId = event.payload?.task_id || event.correlation_id;
      var node = graph.querySelector('[data-task-id="' + taskId + '"]');
      if (node) {
        node.className = "fc-task-graph-node running";
      }
    }
  }

  function updateCurrentAgent(event) {
    var container = $("fc-current-agent");
    if (!container) return;
    if (event.kind === "agent.assigned" || event.kind === "TASK_ASSIGNED") {
      var agentId = event.payload?.agent_id;
      var taskId = event.payload?.task_id;
      container.innerHTML = '<div class="fc-agent-info">' +
        '<div>الوكيل: <strong>' + esc(agentId) + '</strong></div>' +
        '<div>المهمة: <strong>' + esc(taskId) + '</strong></div>' +
        '</div>';
    }
  }

  function updateCurrentAction(event) {
    var container = $("fc-current-action");
    if (!container) return;
    if (event.kind === "tool.started" || event.kind === "TOOL_STARTED") {
      var tool = event.payload?.tool || event.payload?.name;
      var input = event.payload?.input;
      container.innerHTML = '<div class="fc-action-info">' +
        '<div>الأداة: <strong>' + esc(tool) + '</strong></div>' +
        '<div>المدخلات: <pre class="fc-json-small">' + esc(JSON.stringify(input || {}).slice(0, 200)) + '</pre></div>' +
        '</div>';
    } else if (event.kind === "tool.completed" || event.kind === "TOOL_COMPLETED") {
      var tool = event.payload?.tool || event.payload?.name;
      var output = event.payload?.output;
      var exitCode = event.payload?.exit_code;
      container.innerHTML = '<div class="fc-action-info">' +
        '<div>الأداة: <strong>' + esc(tool) + '</strong></div>' +
        '<div>رمز الخروج: <span class="' + (exitCode === 0 ? "ok" : "bad") + '">' + esc(exitCode) + '</span></div>' +
        '<div>المخرجات: <pre class="fc-json-small">' + esc(JSON.stringify(output || {}).slice(0, 300)) + '</pre></div>' +
        '</div>';
    }
  }

  // ---------- Data Loading ----------
  /* دمج رَسَمات إكمال المحمّلات الثلاثة في رسمة واحدة لكل دورة —
     يمنع تكرار innerHTML ويحفظ الحلقة مغلقة (الدخول هو المحفّز الوحيد). */
  var overviewRenderPending = false;
  function queueOverviewRender() {
    if (overviewRenderPending) return;
    overviewRenderPending = true;
    setTimeout(function () {
      overviewRenderPending = false;
      if (state.mode === "overview") renderFactory();
    }, 0);
  }

  function loadOverviewData() {
    loadMissions();
    loadRuns();
    loadAgents();
  }

  function loadMissions() {
    fetchJSON("/api/projects").then(function (out) {
      if (out.ok) {
        state.missions = out.j.projects || [];
        queueOverviewRender();
      }
    });
  }

  function loadRuns() {
    // We need to get runs from active missions or a global runs endpoint
    // For now, fetch from the mission status
    fetchJSON("/api/mission/status").then(function (out) {
      if (out.ok && out.j.cycle_id) {
        state.runs = [{
          run_id: out.j.cycle_id,
          mission_id: "default",
          status: out.j.running ? "RUNNING" : "STOPPED",
          started_at: out.j.started_at,
          current_phase: out.j.last_state,
        }];
        queueOverviewRender();
      }
    });
  }

  function loadAgents() {
    fetchJSON("/api/harness/roles").then(function (out) {
      if (out.ok) {
        state.agents = (out.j.roles || []).map(function (r) {
          var sel = r.live_selection || r.selection || {};
          return {
            agent_id: r.role || r.key,
            role: r.display || r.label,
            status: sel.ready === false ? "NOT_READY" : "AVAILABLE",
            model: sel.model,
            provider: sel.provider,
          };
        });
        queueOverviewRender();
      }
    });
  }

  function loadMissionData(missionId) {
    fetchJSON("/api/projects/" + missionId).then(function (out) {
      if (out.ok) {
        // Update mission data
      }
    });
  }

  function loadRunData(runId) {
    fetchJSON("/api/cycle/status/" + runId).then(function (out) {
      if (out.ok) {
        // Update run data
      }
    });
  }

  // ---------- Expose to Hub ----------
  window.FactoryControl = {
    show: showFactoryView,
    hide: hideFactoryView,
    openMission: openMissionView,
    openRun: openRunView,
    state: state,
  };

  // Initialize: check if hash has factory
  if (location.hash === "#/factory") {
    showFactoryView();
  }

  window.addEventListener("hashchange", function () {
    if (location.hash === "#/factory") {
      showFactoryView();
    } else if (!factoryView.hidden) {
      hideFactoryView();
    }
  });

})();