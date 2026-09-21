/* Agentic Engineering System — النشاط الحي للمهمة داخل المحادثة.
 * الأمر 008 §12-§27: بطاقة مهمة بمراحلها وأزمنتها، بطاقة حية لكل دور
 * (المزود/النموذج/المحاولة/الأداة الحالية)، نشاط أدوات مصنَّف
 * (بدء/نجاح/فشل مع الاستعلام والتصنيف §14-§15)، قرارات تعافٍ (§12)，
 * خط زمني قابل للطي (§20)، أخطاء مفهومة وHARD STOP منظّم (§22-§24)،
 * درج تفاصيل الدور (§25)، والخلاصة مولَّدة من حالة الدورة (§27).
 * كل شيء قابل لإعادة البناء من الأرشيف (§34) — الأحداث وحدها المصدر.
 */
(function () {
  "use strict";

  if (!window.Hub) return;
  var Hub = window.Hub;
  var H = Hub.handlers;
  var MD = window.MD;

  var STEP_DEFS = [
    { key: "thinker", label: "التخطيط" },
    { key: "reviewer", label: "المراجعة" },
    { key: "implementer", label: "التنفيذ" },
    { key: "verifier", label: "التحقق" },
    { key: "arbiter", label: "التحكيم" },
  ];

  var ROLE_LABELS = {
    thinker: "المفكر", reviewer: "المدقق", implementer: "المنفذ",
    verifier: "المراجع", arbiter: "المحكَّم", coordinator: "المنسق",
    router: "الموجّه", eoe: "محرك الأوامر", mission: "المهمة",
    user: "أنت", chat: "المحادثة"
  };

  var TOOL_LABELS = {
    web_search: "بحث ويب", fetch_page: "جلب صفحة",
    write_file: "كتابة ملف", read_file: "قراءة ملف",
    generate_pdf_arabic: "توليد PDF عربي", verify_pdf_pages: "عدّ صفحات PDF",
    http_get_text: "جلب نص", http_get_json: "جلب JSON",
    page_to_text: "صفحة ← نص", fred_csv: "سلسلة FRED",
    worldbank_indicator: "مؤشر البنك الدولي",
  };

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function clockOf(event) {
    var stamp = event.timestamp ? new Date(event.timestamp) : new Date();
    try {
      return stamp.toLocaleTimeString("ar", { hour12: false });
    } catch (e) { return stamp.toTimeString().slice(0, 8); }
  }

  // ---------- حالة البطاقة (قابلة لإعادة البناء من أي نقطة §34) ----------
  var card = null;

  function beginTask() {
    card = null;
  }

  function ensureCard(event) {
    if (card) return card;
    var root = el("div", "task-card");
    root.id = "task-card-live";

    var head = el("div", "task-head");
    var spinner = el("span", "task-spinner");
    var title = el("span", "task-title", "المهمة قيد التنفيذ");
    head.appendChild(spinner);
    head.appendChild(title);
    root.appendChild(head);

    var steps = el("div", "task-steps");
    STEP_DEFS.forEach(function (def, i) {
      var step = el("div", "step" + (i === 0 ? " active" : " pending"));
      step.setAttribute("data-step", def.key);
      step.appendChild(el("span", "step-mark", i === 0 ? "●" : "○"));
      step.appendChild(el("span", "step-label", def.label));
      step.appendChild(el("span", "step-note", i === 0 ? "جارٍ…" : "بانتظار"));
      steps.appendChild(step);
    });
    root.appendChild(steps);

    var roles = el("div", "task-roles-live");
    root.appendChild(roles);

    var tools = el("div", "task-tools");
    var toolsToggle = el("button", "task-fold", "الأدوات ▾");
    var toolsList = el("div", "task-tools-list");
    toolsList.hidden = true;
    toolsToggle.addEventListener("click", function () {
      toolsList.hidden = !toolsList.hidden;
      toolsToggle.textContent = toolsList.hidden ? "الأدوات ▾" : "الأدوات ▴";
    });
    tools.appendChild(toolsToggle);
    tools.appendChild(toolsList);
    root.appendChild(tools);

    var tl = el("div", "task-timeline");
    var tlToggle = el("button", "task-fold", "الخط الزمني ▾");
    var tlList = el("div", "timeline-list");
    tlList.hidden = true;
    tlToggle.addEventListener("click", function () {
      tlList.hidden = !tlList.hidden;
      tlToggle.textContent = tlList.hidden ? "الخط الزمني ▾" : "الخط الزمني ▴";
    });
    tl.appendChild(tlToggle);
    tl.appendChild(tlList);
    root.appendChild(tl);

    var actions = el("div", "task-actions");
    root.appendChild(actions);

    card = {
      root: root, title: title, spinner: spinner, steps: steps,
      roles: roles, toolsList: toolsList, tlList: tlList, actions: actions,
      cycleId: event && event.cycle_id,
      roleModels: {}, roleCards: {}, toolRows: {},
      roleTimeline: {},
    };
    Hub.insertAtEnd(root);
    Hub.scrollDown();
    return card;
  }

  function timelineLine(event, mark, text) {
    if (!card) return;
    var line = el("div", "tl-line");
    line.appendChild(el("span", "tl-time", clockOf(event)));
    line.appendChild(el("span", "tl-mark", mark));
    line.appendChild(el("span", "tl-text", text));
    card.tlList.appendChild(line);
    if (card.tlList.children.length > 400) {
      card.tlList.removeChild(card.tlList.firstChild);  // سقف DOM (§32)
    }
  }

  // ---------- المراحل ----------
  function stepNode(key) {
    return card && card.steps.querySelector('[data-step="' + key + '"]');
  }

  function setStep(key, mark, note, cls) {
    var node = stepNode(key);
    if (!node) return;
    node.className = "step " + cls;
    node.querySelector(".step-mark").textContent = mark;
    node.querySelector(".step-note").textContent = note;
  }

  function stepDone(key, note) { setStep(key, "✓", note || "اكتمل", "done"); }
  function stepActive(key, note) { setStep(key, "●", note || "جارٍ…", "active"); }
  function stepPending(key) { setStep(key, "○", "بانتظار", "pending"); }

  function activateNextAfter(key) {
    var order = STEP_DEFS.map(function (d) { return d.key; });
    var idx = order.indexOf(key);
    for (var i = idx + 1; i < order.length; i++) {
      var node = stepNode(order[i]);
      if (node && node.classList.contains("pending")) {
        stepActive(order[i]);
        break;
      }
    }
  }

  // ---------- بطاقة الدور الحية (§13) ----------
  function roleCard(roleKey) {
    if (!card) return null;
    if (card.roleCards[roleKey]) return card.roleCards[roleKey];
    var meta = STEP_DEFS.filter(function (d) { return d.key === roleKey; })[0];
    var box = el("div", "role-live");
    box.setAttribute("data-role", roleKey);
    var head = el("div", "rl-head");
    var name = el("span", "rl-name", (meta ? meta.label : ROLE_LABELS[roleKey] || roleKey));
    head.appendChild(name);
    var modelLine = el("span", "rl-model");
    head.appendChild(modelLine);
    var status = el("span", "rl-status", "بانتظار");
    head.appendChild(status);
    var more = el("span", "details-link", "التفاصيل");
    head.appendChild(more);
    box.appendChild(head);
    var body = el("div", "rl-body");
    box.appendChild(body);
    card.roles.appendChild(box);
    var entry = {
      box: box, head: head, name: name, model: modelLine, status: status,
      body: body, state: {
        attempts: 0, tools: 0, artifacts: 0, duration: 0,
        lastNote: "", events: [],
      },
    };
    more.addEventListener("click", function () { openRoleDrawer(roleKey, entry); });
    card.roleCards[roleKey] = entry;
    return entry;
  }

  function setRoleModel(roleKey) {
    var entry = roleCard(roleKey);
    if (!entry) return;
    var found = card.roleModels[roleKey];
    if (found) {
      entry.model.textContent = found.provider + " / " + found.model;
      entry.model.dir = "ltr";
    }
  }

  function roleNote(roleKey, text, cls) {
    var entry = roleCard(roleKey);
    if (!entry) return;
    var note = el("div", "rl-note" + (cls ? " " + cls : ""), text);
    entry.body.appendChild(note);
    if (entry.body.children.length > 12) entry.body.removeChild(entry.body.firstChild);
    Hub.onLiveContent();
  }

  function openRoleDrawer(roleKey, entry) {
    var drawer = document.createElement("div");
    drawer.className = "drawer role-drawer";
    drawer.hidden = false;
    var head = el("div", "drawer-head");
    head.appendChild(el("span", null, (ROLE_LABELS[roleKey] || roleKey) + " — التفاصيل"));
    var close = el("button", "icon-btn", "✕");
    head.appendChild(close);
    drawer.appendChild(head);
    var body = el("div", "drawer-body");
    var s = entry.state;
    var rows = [
      ["المزود / النموذج", (card.roleModels[roleKey] || {}).provider
        ? ((card.roleModels[roleKey] || {}).provider + " / " +
           (card.roleModels[roleKey] || {}).model) : "—"],
      ["الحالة", entry.status.textContent || "—"],
      ["المحاولات", String(s.attempts || "—")],
      ["الأدوات", String(s.tools)],
      ["Artifacts", String(s.artifacts)],
      ["المدة", Hub.fmtTime(s.duration || 0)],
    ];
    rows.forEach(function (pair) {
      var row = el("div", "rd-row");
      row.appendChild(el("span", "rd-k", pair[0]));
      var v = el("span", "rd-v");
      v.dir = "auto";
      v.textContent = pair[1];
      row.appendChild(v);
      body.appendChild(row);
    });
    if (s.lastNote) body.appendChild(el("div", "rd-note", s.lastNote));
    drawer.appendChild(body);
    var backdrop = el("div", "drawer-backdrop open");
    backdrop.hidden = false;
    document.body.appendChild(backdrop);
    document.body.appendChild(drawer);
    function shut() { drawer.remove(); backdrop.remove(); }
    close.addEventListener("click", shut);
    backdrop.addEventListener("click", shut);
  }

  // ---------- صف الأداة (§14-§15+§21) ----------
  function toolRow(event) {
    if (!card) return null;
    var id = event.tool_call_id || (event.tool + ":" + (event.query || ""));
    if (card.toolRows[id]) return card.toolRows[id];
    var row = el("div", "tool-row running");
    var head = el("div", "tool-head");
    var mark = el("span", "tool-mark", "●");
    var name = el("span", "tool-name",
      TOOL_LABELS[event.tool] || event.tool || event.kind);
    head.appendChild(mark);
    head.appendChild(name);
    var site = el("span", "tool-site",
      event.execution_site === "substrate" ? "داخل الركيزة" : "معلن خارجها");
    head.appendChild(site);
    var time = el("span", "tool-time");
    head.appendChild(time);
    var link = el("span", "details-link", "التفاصيل");
    link.addEventListener("click", function () { Hub.openModal(event); });
    head.appendChild(link);
    row.appendChild(head);
    var note = el("div", "tool-note");
    row.appendChild(note);
    card.toolsList.appendChild(row);
    card.toolRows[id] = { row: row, mark: mark, note: note, time: time, id: id };
    Hub.onLiveContent();
    return card.toolRows[id];
  }

  function toolNoteText(event) {
    var a = event.args_summary || {};
    if (a.results !== undefined) {
      return a.results + " نتيجة" + (a.first ? " — " + a.first : "");
    }
    if (a.pages !== undefined) return "صفحات: " + a.pages;
    if (a.chars !== undefined) return a.chars + " حرفًا";
    return a.path || "";
  }

  // ---------- أحداث المهمة ----------
  H["task.start"] = function (event) {
    ensureCard(event);
    card.roleModels = (event.role_models || event.details?.role_models) || {};
    STEP_DEFS.forEach(function (d) { setRoleModel(d.key); });
    timelineLine(event, "▶", "بدأت المهمة");
  };

  var ROLE_STEP_EVENTS = {
    plan: "thinker",
    plan_revised: "thinker",
    review_verdict: "reviewer",
    task_execution: "implementer",
    task_verification: "verifier",
    verification_rollup: "verifier",
    arbiter_decision: "arbiter",
  };

  Object.keys(ROLE_STEP_EVENTS).forEach(function (kind) {
    H[kind] = function (event) {
      ensureCard(event);
      var stepKey = ROLE_STEP_EVENTS[kind];
      var d = event.details || {};
      var entry = roleCard(stepKey);
      if (entry) {
        if (d.attempt) entry.state.attempts = d.attempt;
        if (d.artifacts) entry.state.artifacts = d.artifacts.length;
        if (event.duration_ms) entry.state.duration += event.duration_ms;
        entry.state.lastNote = event.text || "";
        entry.status.textContent = d.status === "failed" ? "فشل" : "اكتمل";
        if (d.attempt > 1) {
          entry.status.textContent += " (محاولة " + d.attempt + ")";
        }
      }
      var failed = d.status === "failed";
      if (failed) {
        setStep(stepKey, "✕", "فشل", "failed");
      } else {
        stepDone(stepKey, kind === "review_verdict" ? "تمت الموافقة" : "اكتمل");
        activateNextAfter(stepKey);
      }
      if (event.text) roleNote(stepKey, event.text, failed ? "bad" : "");
      timelineLine(event, failed ? "✕" : "✓",
        (ROLE_LABELS[stepKey] || stepKey) + ": " + (event.text || kind).slice(0, 90));
      Hub.onLiveContent();
    };
  });

  H["state_change"] = function (event) {
    ensureCard(event);
    var to = (event.details || {}).to || event.state;
    if (!to) return;
    timelineLine(event, "→", to);
  };

  H["tool.started"] = function (event) {
    ensureCard(event);
    var row = toolRow(event);
    if (!row) return;
    row.mark.textContent = "●";
    row.mark.className = "tool-mark run";
    row.row.className = "tool-row running";
    if (event.query) {
      row.note.textContent = "الاستعلام: " + String(event.query).slice(0, 120);
    }
    timelineLine(event, "●", (TOOL_LABELS[event.tool] || event.tool) +
      (event.query ? " — " + String(event.query).slice(0, 60) : ""));
    Hub.onLiveContent();
  };

  H["tool.call"] = function (event) {
    ensureCard(event);
    var row = toolRow(event) || toolRow({ ...event, tool_call_id: "" });
    if (row) {
      row.mark.textContent = "✓";
      row.mark.className = "tool-mark ok";
      row.row.className = "tool-row done";
      row.note.textContent = toolNoteText(event) +
        (event.result_count !== undefined && event.tool === "web_search"
          ? "" : "");
      if (event.duration_ms) row.time.textContent = Hub.fmtTime(event.duration_ms);
    }
    var entry = roleCard("implementer");
    if (entry) entry.state.tools += 1;
    timelineLine(event, "✓", (TOOL_LABELS[event.tool] || event.tool) +
      " — " + toolNoteText(event));
  };

  H["tool.failed"] = function (event) {
    ensureCard(event);
    var row = toolRow(event);
    if (row) {
      row.mark.textContent = "⚠";
      row.mark.className = "tool-mark bad";
      row.row.className = "tool-row failed";
      row.note.textContent = (event.human || event.error || "فشلت") +
        (event.failure_reason ? " · التصنيف: " + event.failure_class +
          " / " + event.failure_reason : "") +
        (event.attempt ? " · المحاولة " + event.attempt : "");
    }
    timelineLine(event, "⚠", (TOOL_LABELS[event.tool] || event.tool) +
      " فشل — " + (event.failure_reason || event.error || "").toString().slice(0, 70));
    Hub.onLiveContent();
  };

  H["tool.recovery"] = function (event) {
    ensureCard(event);
    var entry = roleCard("implementer");
    if (entry) roleNote("implementer",
      (event.action === "REVISE_QUERY" ? "↻ " : "⇄ ") + (event.reason || event.action));
    timelineLine(event, "↻", (event.action || "") + " — " +
      (event.reason || "").slice(0, 80));
    Hub.onLiveContent();
  };

  H["tool.site_declared"] = function (event) {
    ensureCard(event);
    timelineLine(event, "·", (event.reason || "تنفيذ معلن خارج الركيزة"));
  };

  // أحداث الموجّه — أسطر رفيعة
  H["router.call.logged"] = function (event) {
    if (!card) return;
    var d = event.details || event;
    timelineLine(event, "·", "استدعاء: " + (d.provider || "?") + " / " +
      (d.model || "?") + " · " + Hub.fmtTime(d.duration_ms || 0));
  };
  H["rate_limit.wait"] = function (event) {
    timelineLine(event, "⏳", "انتظار حد المعدل: " +
      ((event.details || {}).wait_s || event.wait_seconds) + " ث");
  };
  H["cooling.cooldown"] = function (event) {
    timelineLine(event, "🧊", "تبريد اختناق…");
  };
  H["failover.logged"] = function (event) {
    var d = event.details || {};
    timelineLine(event, "🔄", "تبدّل المزود: " + (d.from || "?") + " ← " + (d.to || "?"));
  };
  H["router.event"] = function (event) {
    var inner = { kind: event.kind, role: "router", details: event,
                  text: "", timestamp: event.timestamp };
    if (event.kind === "router.call.logged" && H["router.call.logged"]) {
      H["router.call.logged"](inner);
    }
  };

  // ---------- (010 §29) شاشة جاهزية المهمة: مصفوفة القدرات قبل البدء ----------

  function matrixRow(entry) {
    var row = el("div", "mx-row" + (entry.decision === "BLOCK" ? " bad" : ""));
    row.appendChild(el("span", "mx-cap", entry.capability));
    var status = el("span", "mx-status");
    status.textContent = entry.available;
    row.appendChild(status);
    var decision = el("span", "mx-decision",
      entry.decision === "PROCEED" ? "✓" : "⛔ حجب");
    row.appendChild(decision);
    return row;
  }

  function renderReadinessCard(kind, text, details) {
    Hub.removeWorking();
    var box = el("div", "readiness-card");
    var titleMap = {
      "preflight.started": "فحص البيئة قبل البدء…",
      "preflight.passed": "كل القدرات المطلوبة جاهزة — بدء التنفيذ",
      "preflight.blocked": "فحص البيئة منع البدء — مصفوفة القدرات",
    };
    box.appendChild(el("div", "rd-title",
      titleMap[kind] || "جاهزية المهمة"));
    if (text) {
      var why = el("div", "rd-text");
      why.dir = "auto";
      why.textContent = text;
      box.appendChild(why);
    }
    var matrix = (details && details.matrix) || [];
    if (matrix.length) {
      var table = el("div", "mx-table");
      table.appendChild(el("div", "mx-head",
        "المطلوبة · المتاحة · القرار"));
      matrix.forEach(function (entry) { table.appendChild(matrixRow(entry)); });
      box.appendChild(table);
    }
    var env = details && details.environment;
    if (env) {
      box.appendChild(el("div", "rd-env",
        "بيئة التنفيذ المختارة: " + env.name + " (" + env.backend +
        (env.sandboxed ? " · معزولة" : " · بلا عزل معلنة") + ")"));
    } else if (kind === "preflight.blocked") {
      var noEnv = el("div", "rd-env warn");
      noEnv.textContent = "لا بيئة تنفيذ جاهزة مختارة";
      box.appendChild(noEnv);
    }
    // إجراء المالك: أزرار تفتح التبويب الصحيح مباشرة (§30)
    var blocked = (details && details.blocked) || [];
    var seen = {};
    blocked.forEach(function (b) {
      if (!b.owner_action) return;
      var key = b.capability_id;
      if (seen[key]) return;
      seen[key] = true;
      var action = el("div", "owner-action");
      action.appendChild(el("div", "owner-action-title",
        "OWNER ACTION REQUIRED — " + (b.name || key)));
      var bodyEl = el("div", "owner-action-body");
      bodyEl.dir = "auto";
      bodyEl.textContent = b.owner_action;
      action.appendChild(bodyEl);
      var btn = el("button", "btn primary small", "افتح الإعدادات");
      btn.addEventListener("click", function () {
        var tab = (key === "sandbox") ? "execution"
          : (key === "web_search") ? "tools"
          : (key === "llm") ? "providers" : "tools";
        if (window.HubSettings) window.HubSettings.openTab(tab);
        else document.dispatchEvent(new Event("hub:open-settings"));
      });
      action.appendChild(btn);
      box.appendChild(action);
    });
    Hub.insertAtEnd(box);
    Hub.scrollDown();
    if (kind === "preflight.blocked") Hub.onTaskFinished();
  }

  ["preflight.started", "preflight.passed", "preflight.blocked"].forEach(
    function (kind) {
      H[kind] = function (event) {
        renderReadinessCard(kind, event.text, event.details);
      };
    }
  );

  // ---------- إعداد ناقص ----------
  H["CONFIGURATION_REQUIRED"] = function (event) {
    Hub.removeWorking();
    var d = event.details || {};
    // (010 §29) حاجز preflight له بطاقته الكاملة (مصفوفة + إجراء مالك)
    // في معالج preflight.blocked — لا تكرار هنا.
    if (d.preflight) {
      Hub.onTaskFinished();
      return;
    }
    var box = el("div", "config-card");
    box.appendChild(el("div", "config-title",
      "لم تبدأ المهمة — إعداد المزودات مطلوب"));
    var why = el("div", "config-why");
    why.textContent = event.text || "";
    box.appendChild(why);
    var available = d.available_providers || [];
    if (available.length) {
      box.appendChild(el("div", "config-note",
        "المزودات المتاحة الآن: " + available.join("، ")));
    }
    var btn = el("button", "btn primary", "افتح الإعدادات ← المزودون");
    btn.addEventListener("click", function () {
      if (window.HubSettings) window.HubSettings.openTab("providers");
      else document.dispatchEvent(new Event("hub:open-settings"));
    });
    box.appendChild(btn);
    Hub.insertAtEnd(box);
    Hub.scrollDown();
    Hub.onTaskFinished();
  };

  H["cycle_error"] = function (event) {
    Hub.removeWorking();
    Hub.showErrorCard(event);
    Hub.onTaskFinished();
  };

  // ---------- إيقاف باستئناف ----------
  H["cycle.stopped"] = function (event) {
    if (card) {
      card.title.textContent = "أُوقفت المهمة بأمر";
      card.spinner.className = "task-spinner stopped";
    }
    Hub.removeWorking();
    var d = event.details || {};
    var syscard = Hub.makeSystemCard(event);
    syscard.classList.add("stop-card");
    Hub.insertAtEnd(syscard);
    if (d.snapshot_path) {
      var resume = el("button", "btn ghost", "استئناف من نقطة الإيقاف");
      resume.addEventListener("click", function () {
        resume.disabled = true;
        Hub.setBusy(true);
        resumeRun(event.cycle_id);
      });
      syscard.appendChild(resume);
    }
    Hub.onTaskFinished();
  };

  function resumeRun(cycleId) {
    Hub.state.activeRun = { kind: "task", cycleId: cycleId };
    Hub.addWorking("استئناف المهمة…");
    beginTask();
    Hub.postStream("/api/cycle/resume", { cycle_id: cycleId })
      .then(Hub.onTaskFinished, function (err) {
        Hub.showErrorCard({
          kind: "cycle_error", role: "coordinator",
          text: "تعذر الاستئناف: " + err.message
        });
        Hub.onTaskFinished();
      });
  }

  // ---------- الخاتمة (§24+§27): خلاصة مولَّدة + فشل منظّم ----------
  H["task_done"] = function (event) {
    Hub.removeWorking();
    ensureCard(event);
    var d = event.details || {};
    var pass = event.verdict === "PASS";
    var stopped = event.verdict === "STOPPED";

    card.spinner.className = "task-spinner " +
      (pass ? "pass" : stopped ? "stopped" : "fail");
    card.title.textContent =
      pass ? "اكتملت المهمة بنجاح" :
      stopped ? "أُوقفت المهمة" :
      "توقفت المهمة عند حدّ صلب";
    STEP_DEFS.forEach(function (def) {
      var node = stepNode(def.key);
      if (node && node.classList.contains("active")) {
        setStep(def.key, pass ? "✓" : "✕", pass ? "اكتمل" : "انتهى", pass ? "done" : "failed");
      }
    });
    timelineLine(event, pass ? "✓" : "⛔", "الحكم: " + event.verdict);

    // HARD STOP منظّم (§24): السبب/المرحلة/المحاولات/الأدلة/الإجراء
    if (!pass && !stopped && d.failure) {
      var f = d.failure;
      var box = el("div", "hardstop-card");
      box.appendChild(el("div", "hs-title", "⛔ توقفت المهمة"));
      var rows = [
        ["السبب المباشر", (f.tool ? (TOOL_LABELS[f.tool] || f.tool) + " — " : "") +
          (f.reason || "")],
        ["التصنيف", (f.class || "") + " / " + (f.stage || "")],
        ["المحاولات", f.attempt ? (f.attempt + (f.max_attempts ? " / " + f.max_attempts : "")) : "—"],
        ["Artifacts", String(f.artifacts !== undefined ? f.artifacts : (d.files_count || 0))],
        ["الأدلة", d.evidence_quality === "NO_EVIDENCE" ? "لا أدلة تنفيذية" : (d.evidence_path || "—")],
        ["الإجراء التالي", "مراجعة الخطة أو إعدادات الأدوات/المزودات"],
      ];
      rows.forEach(function (pair) {
        var row = el("div", "hs-row");
        row.appendChild(el("span", "hs-k", pair[0]));
        var v = el("span", "hs-v");
        v.dir = "auto";
        v.textContent = pair[1];
        row.appendChild(v);
        box.appendChild(row);
      });
      if (f.queries && f.queries.length) {
        var q = el("div", "hs-queries");
        q.appendChild(el("div", "hs-k", "الاستعلامات المجربة:"));
        f.queries.forEach(function (text) {
          if (text) q.appendChild(el("div", "hs-query", text));
        });
        box.appendChild(q);
      }
      var details = document.createElement("details");
      details.className = "he-tech";
      details.innerHTML = "<summary>التفاصيل التقنية</summary>";
      var pre = el("pre");
      pre.dir = "ltr";
      pre.textContent = JSON.stringify(f, null, 2);
      details.appendChild(pre);
      box.appendChild(details);
      card.actions.appendChild(box);
    }

    // خلاصة المساعد المولَّدة من حالة الدورة (§27) — Markdown حقيقي
    var summaryText = d.human_summary || "";
    if (summaryText) {
      var wrap = el("div", "bubble assistant task-summary");
      var body = el("div", "bubble-body md-body");
      body.innerHTML = MD ? MD.render(summaryText) : Hub.esc(summaryText);
      wrap.appendChild(body);
      card.actions.appendChild(wrap);
    }

    var facts = el("div", "task-facts");
    facts.textContent =
      "الحالة النهائية: " + (d.final_state || "—") +
      " · أدوات: " + (d.tool_invocations_count !== undefined
        ? d.tool_invocations_count + (d.failed_tool_calls
          ? " (فشل " + d.failed_tool_calls + ")" : "")
        : (d.tool_calls_count !== undefined ? d.tool_calls_count : "—")) +
      (d.recovery_attempts ? " · تعافٍ: " + d.recovery_attempts : "") +
      " · ملفات: " + (d.files_count !== undefined ? d.files_count : "—") +
      " · المدة: " + Hub.fmtTime(d.duration_ms || 0);
    card.actions.appendChild(facts);

    if (pass && d.cycle_id) {
      var verify = el("button", "btn primary", "أوافق على النتيجة");
      verify.addEventListener("click", function () {
        verify.disabled = true;
        Hub.fetchJSON("/api/cycle/verify", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ cycle_id: d.cycle_id })
        }).then(function (out) {
          verify.replaceWith(el("span", "verified-note",
            out.ok ? "✔ VERIFIED — موافقتك سُجّلت" : "تعذّرت الموافقة"));
        });
      });
      card.actions.appendChild(verify);
    }
    if (d.evidence_path) {
      var note = el("div", "task-evidence");
      note.textContent = "الأدلة: " + d.evidence_path +
        (d.evidence_sha256 ? " · sha256: " + String(d.evidence_sha256).slice(0, 16) + "…" : "");
      card.actions.appendChild(note);
    }
    Hub.scrollDown();
    Hub.onTaskFinished();
  };

  // ---------- المسارات المتقدمة (قسم تقني) ----------
  H["role:mission"] = function (event) {
    if (event.kind === "mission.start") {
      Hub.addWorking("المهمة الحية المتخصصة تعمل…");
      return;
    }
    if (event.kind === "mission_done") {
      Hub.removeWorking();
      var syscard = Hub.makeSystemCard({
        kind: "mission.done", role: "mission",
        text: "الحكم: " + event.verdict + " — " + (event.text || ""),
        details: event.details
      });
      Hub.insertAtEnd(syscard);
      Hub.scrollDown();
      Hub.onTaskFinished();
      return;
    }
    if (event.kind === "mission_error") {
      Hub.removeWorking();
      Hub.showErrorCard(event);
      Hub.onTaskFinished();
      return;
    }
    Hub.insertAtEnd(Hub.makeSystemCard(event));
  };

  H["role:eoe"] = function (event) {
    var labels = {
      "order.parsed": "الأمر حُلّل",
      "grant.awaiting_owner": "بطاقة موافقة المنح",
      "push.awaiting_owner": "بطاقة موافقة الدفع",
      "hard_stop.fired": "توقف صلب",
      "eoe.finished": "انتهى التنفيذ",
      "eoe.error": "خطأ تنفيذ"
    };
    var syscard = Hub.makeSystemCard({
      kind: event.kind, role: "eoe",
      text: labels[event.kind] || event.kind,
      details: event.details, duration_ms: event.duration_ms
    });
    syscard.classList.add("eoe-card");
    if (event.kind === "hard_stop.fired") syscard.classList.add("error");
    Hub.insertAtEnd(syscard);

    if (event.kind === "grant.awaiting_owner" ||
        event.kind === "push.awaiting_owner") {
      syscard.appendChild(makeApprovalCard(event));
    }
    if (event.kind === "eoe.finished" || event.kind === "eoe.error") {
      Hub.onTaskFinished();
    }
  };

  function makeApprovalCard(event) {
    var kind = event.kind === "grant.awaiting_owner" ? "grants" : "push";
    var box = el("div", "approval-card");
    box.appendChild(el("div", "approval-title",
      kind === "grants" ? "بلا موافقتك لا وصول" : "موافقة دفع موقعة أحادية الاستخدام"));
    var actions = el("div", "approval-actions");
    var ok = el("button", "btn primary", "أوافق");
    var no = el("button", "btn danger", "أرفض");
    actions.appendChild(ok); actions.appendChild(no);
    box.appendChild(actions);
    var result = el("div", "approval-result");
    box.appendChild(result);
    function decide(approved) {
      ok.disabled = true; no.disabled = true;
      Hub.fetchJSON("/api/eoe/approve", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ run_id: event.cycle_id, kind: kind, approved: approved })
      }).then(function (out) {
        result.textContent = approved
          ? (out.ok ? "✔ وُافقت — استؤنف التنفيذ" : "تعذرت الموافقة")
          : "✕ رُفضت — لا وصول (fail-closed)";
      });
    }
    ok.addEventListener("click", function () { decide(true); });
    no.addEventListener("click", function () { decide(false); });
    return box;
  }

  H["router.demo.start"] = H["router.demo.phase"] = function (event) {
    Hub.insertAtEnd(Hub.makeSystemCard(event));
  };
  H["router.demo.done"] = H["router.demo.error"] = function (event) {
    Hub.removeWorking();
    Hub.insertAtEnd(Hub.makeSystemCard(event));
    Hub.scrollDown();
    Hub.onTaskFinished();
  };

  H["approval.card"] = function (event) {
    var syscard = Hub.makeSystemCard(event);
    syscard.appendChild(buildApprovalCard(event));
    Hub.insertAtEnd(syscard);
  };

  function buildApprovalCard(event) {
    var kind = (event.details || {}).gate_kind;
    var box = el("div", "approval-card");
    box.appendChild(el("div", "approval-title",
      kind === "push" ? "موافقة الدفع إلى الفرع" : "منحة مسار الكتابة"));
    var actions = el("div", "approval-actions");
    var ok = el("button", "btn primary", "أوافق");
    var no = el("button", "btn danger", "أرفض");
    actions.appendChild(ok); actions.appendChild(no);
    box.appendChild(actions);
    function decide(approved) {
      ok.disabled = true; no.disabled = true;
      Hub.fetchJSON("/api/mission/textstats/approve", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ run_id: event.cycle_id, kind: kind, approved: approved })
      }).then(function () {
        box.appendChild(el("div", "approval-result",
          approved ? "✔ وُافقت" : "✕ رُفضت — fail-closed"));
      });
    }
    ok.addEventListener("click", function () { decide(true); });
    no.addEventListener("click", function () { decide(false); });
    return box;
  }

  // ---------- تشغيل المسارات المتقدمة (من settings.js) ----------
  Hub.runAdvanced = function (name) {
    if (Hub.state.busy) return;
    Hub.state.activeRun = { kind: name === "mission" ? "mission" : name, cycleId: "" };
    Hub.setBusy(true);
    Hub.stopButtonEnable(false);
    var stopBtn = Hub.currentStopRunEl();
    if (name === "mission") { stopBtn.hidden = false; }

    if (name === "router-demo") {
      Hub.addWorking("عرض أحداث الموجّه…");
      Hub.postStream("/api/router/demo", {}).then(Hub.onTaskFinished, failed);
    } else if (name === "eoe") {
      var orderText = Hub.$("input").value.trim();
      if (!orderText) {
        Hub.onTaskFinished();
        Hub.$("input").focus();
        return;
      }
      Hub.$("input").value = "";
      Hub.addUserMessage("أمر تنفيذي (طوله " + orderText.length + " حرفًا)");
      Hub.addWorking("تنفيذ الأمر التنفيذي…");
      Hub.postStream("/api/eoe/stream", { order_text: orderText })
        .then(Hub.onTaskFinished, failed);
    } else if (name === "mission") {
      var goalText = Hub.$("input").value.trim();
      Hub.$("input").value = "";
      Hub.addUserMessage(goalText || "المهمة الحية الافتراضية: تقرير جيوسياسي + PDF عربي");
      Hub.addWorking("المهمة الحية المتخصصة تعمل…");
      Hub.postStream("/api/mission/stream", { goal: goalText || "" })
        .then(Hub.onTaskFinished, failed);
    } else if (name === "build") {
      Hub.addUserMessage("ابنِ حزمة textstats وادفعها إلى فرعها");
      Hub.addWorking("مهمة البناء تعمل…");
      Hub.postStream("/api/mission/textstats/stream", {})
        .then(Hub.onTaskFinished, failed);
    }

    function failed(err) {
      Hub.removeWorking();
      Hub.showErrorCard({
        kind: "cycle_error", role: "coordinator",
        text: "تعذر البث: " + err.message
      });
      Hub.onTaskFinished();
    }
  };

  window.TaskCards = { beginTask: beginTask };
})();
