/* agent hub v2 — بطاقات التنفيذ: المهمة بمراحلها + المسارات المتقدمة.
 * الأمر 006 §9: بدل رموز الأدوار الخمسة كواجهة أساسية، المهمة تظهر
 * بطاقة واحدة أنيقة: التخطيط ✓ / المراجعة ✓ / التنفيذ جارٍ… / التحقق
 * بانتظار — والتفاصيل الكاملة (المزود/النموذج/الزمن/الأدلة) داخل
 * أقسام قابلة للفتح، لا شاشة طرفية.
 */
(function () {
  "use strict";

  if (!window.Hub) return;
  var Hub = window.Hub;
  var H = Hub.handlers;

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

  // ---------- أداة DOM ----------
  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  // ---------- بطاقة المهمة ----------
  var card = null;          // عناصر بطاقة المهمة الجارية
  var cardState = { lastRouterCall: null };

  function beginTask() {
    card = null;
    cardState.lastRouterCall = null;
  }

  function ensureCard(event) {
    if (card) return card;
    var root = el("div", "task-card");
    root.id = "task-card-live";

    var head = el("div", "task-head");
    var title = el("span", "task-title", "المهمة قيد التنفيذ");
    var spinner = el("span", "task-spinner");
    head.appendChild(spinner);
    head.appendChild(title);
    root.appendChild(head);

    var steps = el("div", "task-steps");
    STEP_DEFS.forEach(function (def, i) {
      var step = el("div", "step" + (i === 0 ? " active" : " pending"));
      step.setAttribute("data-step", def.key);
      step.appendChild(el("span", "step-mark", i === 0 ? "◌" : "□"));
      step.appendChild(el("span", "step-label", def.label));
      step.appendChild(el("span", "step-note", i === 0 ? "جارٍ…" : "بانتظار"));
      steps.appendChild(step);
    });
    root.appendChild(steps);

    var rolesBox = el("div", "task-roles");
    var rolesToggle = el("button", "task-fold", "تفاصيل الأدوار ▾");
    var rolesList = el("div", "task-roles-list");
    rolesList.hidden = true;
    rolesToggle.addEventListener("click", function () {
      rolesList.hidden = !rolesList.hidden;
      rolesToggle.textContent = rolesList.hidden
        ? "تفاصيل الأدوار ▾" : "تفاصيل الأدوار ▴";
    });
    rolesBox.appendChild(rolesToggle);
    rolesBox.appendChild(rolesList);
    root.appendChild(rolesBox);

    var toolsBox = el("div", "task-tools");
    var toolsToggle = el("button", "task-fold", "التنفيذ والأدوات ▾");
    var toolsList = el("div", "task-tools-list");
    toolsList.hidden = true;
    toolsToggle.addEventListener("click", function () {
      toolsList.hidden = !toolsList.hidden;
      toolsToggle.textContent = toolsList.hidden
        ? "التنفيذ والأدوات ▾" : "التنفيذ والأدوات ▴";
    });
    toolsBox.appendChild(toolsToggle);
    toolsBox.appendChild(toolsList);
    root.appendChild(toolsBox);

    var actions = el("div", "task-actions");
    root.appendChild(actions);

    card = { root: root, title: title, spinner: spinner, steps: steps,
             rolesList: rolesList, toolsList: toolsList, actions: actions,
             cycleId: event && event.cycle_id };
    Hub.$("messages").appendChild(root);
    Hub.scrollDown();
    return card;
  }

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
  function stepActive(key, note) { setStep(key, "◌", note || "جارٍ…", "active"); }
  function stepPending(key) { setStep(key, "□", "بانتظار", "pending"); }

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

  // تسمية النموذج المُعرّف لكل دور من إعدادات الواجهة (ما أُرسل فعلًا)
  function roleModelLine(roleKey) {
    var cfg = Hub.state.modelsConfig;
    if (!cfg || !cfg.roles) return "";
    var found = cfg.roles.filter(function (r) { return r.key === roleKey; })[0];
    return found ? found.selection.provider + " / " + found.selection.model : "";
  }

  function addRoleDetail(event) {
    if (!card) return;
    var meta = STEP_DEFS.filter(function (d) { return d.key === event.role; })[0];
    var roleKey = meta ? meta.key : event.role;
    var entry = el("div", "role-detail");
    var head = el("div", "role-detail-head");
    head.appendChild(el("span", "rd-name",
      (meta ? meta.label : ROLE_LABELS[event.role] || event.role)));
    var modelLine = roleModelLine(roleKey);
    if (modelLine) {
      head.appendChild(el("span", "rd-model", modelLine));
    }
    if (event.duration_ms) {
      head.appendChild(el("span", "rd-time", Hub.fmtTime(event.duration_ms)));
    }
    var link = el("span", "details-link", "التفاصيل");
    link.addEventListener("click", function () { Hub.openModal(event); });
    head.appendChild(link);
    entry.appendChild(head);
    if (event.text) {
      entry.appendChild(el("div", "rd-text", event.text));
    }
    card.rolesList.appendChild(entry);
  }

  function addToolRow(event) {
    if (!card) return;
    var row = el("div", "tool-row");
    var head = el("div", "tool-head");
    var site = event.execution_site === "substrate" ? "داخل الركيزة" : "معن خارجها";
    head.appendChild(el("span", "tool-name", event.tool || event.kind));
    head.appendChild(el("span", "tool-site", site));
    if (event.duration_ms) {
      head.appendChild(el("span", "tool-time", Hub.fmtTime(event.duration_ms)));
    }
    var link = el("span", "details-link", "التفاصيل");
    link.addEventListener("click", function () { Hub.openModal(event); });
    head.appendChild(link);
    row.appendChild(head);
    if (event.kind === "tool.failed") {
      row.classList.add("failed");
      row.appendChild(el("div", "tool-note", "فشلت: " + (event.error || "")));
    } else if (event.args_summary) {
      var a = event.args_summary;
      var desc = a.results !== undefined
        ? (a.results + " نتيجة" + (a.first ? " — " + a.first : ""))
        : (a.pages !== undefined ? ("صفحات: " + a.pages)
          : (a.chars !== undefined ? (a.chars + " حرفًا") : (a.path || "")));
      row.appendChild(el("div", "tool-note", desc));
    }
    card.toolsList.appendChild(row);
  }

  // ---------- أحداث المهمة ----------
  H["task.start"] = function (event) {
    ensureCard(event);
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
      stepDone(stepKey, kind === "review_verdict" ? "تمت الموافقة" : "اكتمل");
      activateNextAfter(stepKey);
      addRoleDetail(event);
      Hub.scrollDown();
    };
  });

  H["state_change"] = function (event) {
    // تغيّر الحالة ينعكس على المراحل — سطر رفيع داخل البطاقة
    if (!card) return;
    var to = (event.details || {}).to || event.state;
    if (!to) return;
    var note = el("div", "task-state-line", to);
    card.toolsList.parentNode.insertBefore(note, card.toolsList.parentNode.firstChild);
  };

  H["tool.call"] = function (event) {
    ensureCard(event);
    addToolRow(event);
    Hub.scrollDown();
  };
  H["tool.failed"] = function (event) {
    ensureCard(event);
    addToolRow(event);
  };
  H["tool.site_declared"] = function (event) {
    ensureCard(event);
    addToolRow(event);
  };

  // أحداث الموجّه داخل البطاقة — سطور رفيعة (المزود/النموذج/الزمن)
  H["router.call.logged"] = function (event) {
    cardState.lastRouterCall = event;
    if (!card) return;
    var d = event.details || event;
    var line = el("div", "router-line");
    line.textContent = "استدعاء: " + (d.provider || "?") + " / " +
      (d.model || "?") + " · " + Hub.fmtTime(d.duration_ms || 0) +
      (d.tokens ? " · ~" + d.tokens + " توكن" : "");
    card.toolsList.appendChild(line);
  };
  H["rate_limit.wait"] = function (event) {
    if (card) card.toolsList.appendChild(el("div", "router-line wait",
      "انتظار حد المعدل: " + ((event.details || {}).wait_s || event.wait_seconds) + " ث"));
  };
  H["cooling.cooldown"] = function (event) {
    if (card) card.toolsList.appendChild(el("div", "router-line wait",
      "تبريد اختناق…"));
  };
  H["failover.logged"] = function (event) {
    var d = event.details || {};
    if (card) card.toolsList.appendChild(el("div", "router-line",
      "تبدّل المزود: " + (d.from || "?") + " ← " + (d.to || "?")));
  };
  H["router.event"] = function (event) {
    // نسخة مغلّفة من أحداث الموجّه في مسار المهمة
    var inner = { kind: event.kind, role: "router", details: event, text: "" };
    if (event.kind === "router.call.logged") H["router.call.logged"](inner);
  };

  H["CONFIGURATION_REQUIRED"] = function (event) {
    Hub.removeWorking();
    var box = el("div", "config-card");
    box.appendChild(el("div", "config-title",
      "لم تبدأ المهمة — إعداد المزودات مطلوب"));
    var why = el("div", "config-why");
    why.textContent = event.text || "";
    box.appendChild(why);
    var available = (event.details || {}).available_providers || [];
    if (available.length) {
      box.appendChild(el("div", "config-note",
        "المزودات المتاحة الآن: " + available.join("، ")));
    }
    var btn = el("button", "btn primary", "افتح الإعدادات");
    btn.addEventListener("click", function () {
      var open = document.createEvent("Event");
      open.initEvent("hub:open-settings", true, true);
      document.dispatchEvent(open);
    });
    box.appendChild(btn);
    Hub.$("messages").appendChild(box);
    Hub.scrollDown();
    Hub.onTaskFinished();
  };

  H["cycle_error"] = function (event) {
    Hub.removeWorking();
    var syscard = Hub.makeSystemCard(event);
    syscard.classList.add("error");
    Hub.$("messages").appendChild(syscard);
    Hub.scrollDown();
    Hub.onTaskFinished();
  };

  H["cycle.stopped"] = function (event) {
    if (card) {
      card.title.textContent = "أُوقفت المهمة بأمر";
      card.spinner.className = "task-spinner stopped";
    }
    Hub.removeWorking();
    var d = event.details || {};
    var syscard = Hub.makeSystemCard(event);
    syscard.classList.add("stop-card");
    Hub.insertBeforeWorking(syscard);
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
    Hub.postStream("/api/cycle/resume", { cycle_id: cycleId })
      .then(Hub.onTaskFinished, function (err) {
        var syscard = Hub.makeSystemCard({
          kind: "cycle_error", role: "coordinator",
          text: "تعذر الاستئناف: " + err.message
        });
        Hub.$("messages").appendChild(syscard);
        Hub.onTaskFinished();
      });
  }

  H["task_done"] = function (event) {
    Hub.removeWorking();
    if (card) {
      card.spinner.className = "task-spinner " +
        (event.verdict === "PASS" ? "pass" : "fail");
      card.title.textContent =
        event.verdict === "PASS" ? "اكتملت المهمة بنجاح" :
        event.verdict === "STOPPED" ? "أُوقفت المهمة" :
        "توقفت المهمة عند حدّ صلب";
    } else {
      ensureCard(event);
    }
    STEP_DEFS.forEach(function (d) {
      if (stepNode(d.key) && stepNode(d.key).classList.contains("active")) {
        stepDone(d.key);
      }
    });

    var d = event.details || {};
    var summary = el("div", "task-verdict " +
      (event.verdict === "PASS" ? "pass" : "fail"));
    summary.textContent =
      (event.verdict === "PASS" ? "الحكم: اكتملت بأدلة كاملة" :
        "الحكم: " + (event.verdict || "") + " — " + (event.text || ""));
    var facts = el("div", "task-facts");
    facts.textContent =
      "الحالة النهائية: " + (d.final_state || "—") +
      " · أدوات: " + (d.tool_calls_count !== undefined ? d.tool_calls_count : "—") +
      " · ملفات: " + (d.files_count !== undefined ? d.files_count : "—") +
      " · المدة: " + Hub.fmtTime(d.duration_ms || 0);
    if (card) {
      card.actions.appendChild(summary);
      card.actions.appendChild(facts);
    }

    if (event.verdict === "PASS" && d.cycle_id) {
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
      if (card) card.actions.appendChild(verify);
    }
    if (d.evidence_path) {
      var note = el("div", "task-evidence");
      note.textContent = "الأدلة: " + d.evidence_path +
        (d.evidence_sha256 ? " · sha256: " + String(d.evidence_sha256).slice(0, 16) + "…" : "");
      if (card) card.actions.appendChild(note);
    }
    Hub.scrollDown();
    Hub.onTaskFinished();
  };

  // ---------- المسارات المتقدمة (قسم تقني — يُفتح من الإعدادات) ----------

  H["role:mission"] = function (event) {
    // أحداث المهمة الحية المتخصصة (تقرير جيوسياسي + PDF)
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
      Hub.$("messages").appendChild(syscard);
      Hub.scrollDown();
      Hub.onTaskFinished();
      return;
    }
    if (event.kind === "mission_error") {
      Hub.removeWorking();
      var errcard = Hub.makeSystemCard(event);
      errcard.classList.add("error");
      Hub.$("messages").appendChild(errcard);
      Hub.onTaskFinished();
      return;
    }
    var generic = Hub.makeSystemCard(event);
    Hub.insertBeforeWorking(generic);
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
    Hub.insertBeforeWorking(syscard);

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
    var syscard = Hub.makeSystemCard(event);
    Hub.insertBeforeWorking(syscard);
  };
  H["router.demo.done"] = H["router.demo.error"] = function (event) {
    Hub.removeWorking();
    var syscard = Hub.makeSystemCard(event);
    Hub.$("messages").appendChild(syscard);
    Hub.scrollDown();
    Hub.onTaskFinished();
  };

  // مهمة البناء (textstats) — بطاقات موافقة داخلية
  H["approval.card"] = function (event) {
    var syscard = Hub.makeSystemCard(event);
    syscard.appendChild(buildApprovalCard(event));
    Hub.insertBeforeWorking(syscard);
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
      }).then(function (out) {
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
      var syscard = Hub.makeSystemCard({
        kind: "cycle_error", role: "coordinator",
        text: "تعذر البث: " + err.message
      });
      Hub.$("messages").appendChild(syscard);
      Hub.onTaskFinished();
    }
  };

  // تصدير للوحدة
  window.TaskCards = { beginTask: beginTask };
})();
