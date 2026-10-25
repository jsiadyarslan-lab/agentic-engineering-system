/* عرض سير العمل (013.4 §19-§23+§43+§47-§48) — سطح التحكم الحقيقي.
 *
 * المصدر الوحيد: لقطة زمن التشغيل القانونية /api/projects/{id}/runtime
 * (§8) — لا اشتقاقًا موازيًا هنا أبدًا. يعرض:
 * - خط الأنابيب GOAL→PLAN→APPROVAL→PREPARE→EXECUTE→TEST→REVIEW→AUDIT→DONE
 *   (المرحلة الحالية بارزة، المكتمل مضغوط، القادم خافت، المحجوب بسببه)
 * - تفاصيل المرحلة عند النقر (§20): العملية الجارية/الدور/الأدوات
 * - خط النشاط الحي (§21): سطور مفهومة لا JSON خام
 * - الأدوار الحية (§23): دور واحد نشط + تاريخ مضغوط — لا خمسة روبوتات
 * - التاريخ الطويل صفحات (§43): مؤشر رجوع لا غرق DOM
 * - الأدلة (§48) والمخرجات (§47) من السجل الدائم حصرًا
 */
(function () {
  "use strict";

  var Hub = window.Hub;
  var STATUS_LABELS = {
    DRAFT: "مسودة", PLANNING: "توليد الخطة",
    AWAITING_OWNER_APPROVAL: "ينتظر اعتمادك",
    READY: "جاهز", RUNNING: "يعمل الآن", PAUSED: "متوقف مؤقتًا",
    BLOCKED: "محجوب", REVISING: "مراجعة", VERIFIED: "مُتحقق",
    COMPLETED: "مكتمل", STOPPED: "متوقف", ESCALATED: "مُصعَّد",
  };
  var STAGE_ORDER = ["GOAL", "PLAN", "APPROVAL", "PREPARE", "EXECUTE",
    "TEST", "REVIEW", "AUDIT", "DONE"];

  function esc(s) { return Hub.esc(s); }
  function el(tag, cls, text) { return Hub.el(tag, cls, text); }

  /* ---------- (AES-ORACLE-UI-RUNTIME-002 §4) وصول فعلي لمحتوى المخرجات ----------
   * كل ملف مخرج مرتبط بسجل دليل معتمد، ومحتواه عبر نقطة النهاية
   * /evidence/{id}/files/{name}/content — الخادم يُحل الملف من السجل
   * ويتحقق من بصمته. هنا: أزرار فتح/تنزيل + معاينة نصية داخلية
   * + إفصاح خطأ صادق عند فشل الوصول. لا روابط لواجهات غير موجودة. */

  var PREVIEW_TEXT_EXT = ["md", "txt", "json", "log", "csv", "py", "js",
                          "ts", "css", "html", "yml", "yaml", "xml", "sh"];
  var PREVIEW_NATIVE_EXT = ["pdf", "png", "jpg", "jpeg", "gif", "webp", "svg"];

  function artifactContentUrl(projectId, evidenceId, name, download) {
    return "/api/projects/" + projectId + "/evidence/" + evidenceId
      + "/files/" + encodeURIComponent(name) + "/content"
      + (download ? "?download=1" : "");
  }

  function fileExt(name) {
    var dot = String(name).lastIndexOf(".");
    return dot >= 0 ? String(name).slice(dot + 1).toLowerCase() : "";
  }

  function ensurePreviewModal() {
    var modal = document.getElementById("ae-file-preview");
    if (modal) return modal;
    modal = document.createElement("div");
    modal.id = "ae-file-preview";
    modal.className = "ae-file-preview-backdrop";
    modal.hidden = true;
    var box = document.createElement("div");
    box.className = "ae-file-preview";
    var head = document.createElement("div");
    head.className = "ae-file-preview-head";
    var titleEl = document.createElement("span");
    titleEl.className = "ae-file-preview-title";
    var close = document.createElement("button");
    close.className = "ae-file-preview-close";
    close.textContent = "✕";
    close.addEventListener("click", function () { modal.hidden = true; });
    head.appendChild(titleEl);
    head.appendChild(close);
    var bodyEl = document.createElement("pre");
    bodyEl.className = "ae-file-preview-body";
    bodyEl.dir = "auto";
    box.appendChild(head);
    box.appendChild(bodyEl);
    modal.appendChild(box);
    document.body.appendChild(modal);
    return modal;
  }

  function openArtifact(projectId, a) {
    var ext = fileExt(a.name);
    var url = artifactContentUrl(projectId, a.evidence_id, a.name, 0);
    if (PREVIEW_TEXT_EXT.indexOf(ext) !== -1) {
      var modal = ensurePreviewModal();
      var titleEl = modal.querySelector(".ae-file-preview-title");
      var bodyEl = modal.querySelector(".ae-file-preview-body");
      titleEl.textContent = a.name;
      bodyEl.textContent = "…جارٍ التحميل";
      modal.hidden = false;
      fetch(url, { credentials: "same-origin" })
        .then(function (resp) {
          if (!resp.ok) {
            return resp.json().catch(function () { return {}; })
              .then(function (j) {
                throw new Error("HTTP " + resp.status
                  + (j && j.detail ? " — " + j.detail : ""));
              });
          }
          return resp.text();
        })
        .then(function (text) {
          bodyEl.textContent = String(text).slice(0, 200000);
        })
        .catch(function (err) {
          bodyEl.textContent = "تعذر فتح الملف — " + err.message;
        });
      return;
    }
    if (PREVIEW_NATIVE_EXT.indexOf(ext) !== -1) {
      window.open(url, "_blank", "noopener");
      return;
    }
    triggerDownload(projectId, a);
  }

  function triggerDownload(projectId, a) {
    var link = document.createElement("a");
    link.href = artifactContentUrl(projectId, a.evidence_id, a.name, 1);
    link.download = a.name;
    document.body.appendChild(link);
    link.click();
    link.remove();
  }

  function artifactActionsRow(projectId, a) {
    var actions = el("div", "wf-artifact-actions");
    if (a.kind !== "file" || !a.evidence_id) return actions;
    var openB = el("button", "wf-artifact-act",
      PREVIEW_TEXT_EXT.indexOf(fileExt(a.name)) !== -1
        || PREVIEW_NATIVE_EXT.indexOf(fileExt(a.name)) !== -1
        ? "فتح" : "فتح (تنزيل)");
    openB.title = "فتح أو معاينة الملف من سجل الدليل";
    openB.addEventListener("click", function () {
      try { openArtifact(projectId, a); } catch (err) { /* لا انفجار */ }
    });
    var dl = el("button", "wf-artifact-act", "تنزيل");
    dl.title = "تنزيل الملف الأصلي";
    dl.addEventListener("click", function () {
      try { triggerDownload(projectId, a); } catch (err) { /* لا انفجار */ }
    });
    actions.appendChild(openB);
    actions.appendChild(dl);
    return actions;
  }

  /** خط الأنابيب — المرحلة الحالية بارزة والمحجوب يشرح سببه (§19). */
  function renderPipeline(container, snap) {
    var pipe = el("div", "wf-pipeline");
    var current = snap.stage || "GOAL";
    var currentIdx = STAGE_ORDER.indexOf(current);
    STAGE_ORDER.forEach(function (key, index) {
      var label = ((snap.stage_labels || {})[key]) || key;
      var item = el("div", "wf-stage");
      if (index < currentIdx) item.classList.add("done");
      else if (index === currentIdx) item.classList.add("current");
      else item.classList.add("future");
      var dot = el("span", "wf-stage-dot");
      dot.textContent = index < currentIdx ? "✓"
        : index === currentIdx ? "●" : "○";
      item.appendChild(dot);
      item.appendChild(el("span", "wf-stage-label", label));
      item.addEventListener("click", function () {
        renderStageDetails(container, snap, key);
      });
      pipe.appendChild(item);
      if (index < STAGE_ORDER.length - 1) {
        pipe.appendChild(el("span", "wf-stage-arrow",
                            index < currentIdx ? "—" : "·"));
      }
    });
    return pipe;
  }

  /** المحجوب يشرح سببه حرفيًا (§19) — من اللقطة لا تخمين. */
  function renderBlocking(container, snap) {
    if (!snap.blocking_reason) return null;
    var box = el("div", "wf-blocking");
    box.appendChild(el("div", "wf-blocking-title", "⚠ عائق يحتاج انتباهك"));
    box.appendChild(el("div", "wf-blocking-reason",
                       snap.blocking_reason));
    var waiting = snap.waiting_for || {};
    if (waiting.kind === "owner_approval" || waiting.kind === "owner_gate") {
      box.appendChild(el("div", "wf-blocking-hint",
        "القرار لك — عالج البوابة من تبويب «المحادثة»"));
    }
    return box;
  }

  /* (013.5 §J) رموز الانتظار الصادقة — نفس مفردات project-live.js.
   * «توليد الخطة جارٍ» لم تكن كافية: المالك بقي ‏17992ث أمام شاشة
   * لا تقول إن كان الاستدعاء وصل للمزود أصلًا ولا كم بقي للسقف. */
  var WAIT_PHASE_TEXT = {
    QUEUED: "في الطابور — لم يبدأ الاستدعاء بعد",
    CONNECTING: "جارٍ الاتصال بالمزود وإرسال الطلب",
    /* 013.5 §D/§J: استدلال حيّ ≠ صمت — المزود يعمل ويُقاس عدّاده. */
    REASONING: "المزود يستدل الآن — نشاط حقيقي وصل، والإجابة لم تبدأ بعد",
    AWAITING_PROVIDER: "بانتظار رد المزود — الطلب مُرسَل ولم يصل نشاط",
    PAUSED: "موقوف بقرار المالك",
    DONE: "اكتمل",
    FAILED: "فشل مصنَّف",
    INTERRUPTED: "انقطع العامل المولِّد",
    CANCELLED: "أُلغي",
  };

  function wfSeconds(value) {
    var n = Number(value);
    if (!isFinite(n) || n < 0) return "—";
    if (n < 60) return n + " ث";
    var minutes = Math.floor(n / 60);
    if (minutes < 60) return minutes + " د " + (n % 60) + " ث";
    return Math.floor(minutes / 60) + " س " + (minutes % 60) + " د";
  }

  function wfRemaining(deadline) {
    if (!deadline) return null;
    var target = new Date(deadline).getTime();
    if (isNaN(target)) return null;
    return Math.max(0, Math.round((target - Date.now()) / 1000));
  }

  /** بطاقة التخطيط الحي (§36 + §D/§J): ماذا ينتظر حرفيًا وسقفه. */
  function renderPlanningLive(snap) {
    var planning = snap.planning || {};
    if (!planning.active) return null;
    var detail = planning.detail || {};
    var waiting = planning.waiting_for || {};
    var phase = planning.wait_phase || "CONNECTING";
    var card = el("div", "wf-planning-live");
    var title = el("div", "wf-planning-title");
    title.appendChild(el("span", null, "⏳ توليد الخطة جارٍ — "));
    title.appendChild(el("span", "wf-wait-phase", phase));
    card.appendChild(title);
    card.appendChild(el("div", "wf-planning-wait",
      WAIT_PHASE_TEXT[phase] || ("حالة انتظار معلنة: " + phase)));
    var rows = el("div", "wf-planning-rows");
    function row(label, value) {
      if (value === null || value === undefined || value === "") return;
      var r = el("div", "wf-planning-row");
      r.appendChild(el("span", "wf-pl-k", label));
      var v = el("span", "wf-pl-v", String(value));
      v.dir = "auto";
      r.appendChild(v);
      rows.appendChild(r);
    }
    row("المزود", waiting.provider || detail.provider);
    row("النموذج", waiting.model || detail.model);
    row("الطلب", waiting.request_id || detail.request_id);
    row("المحاولة", waiting.attempt);
    row("مضى على الجلسة", wfSeconds(detail.elapsed_s));
    row("آخر نشاط مزود حقيقي", wfSeconds(detail.silence_s) + " مضت");
    row("آخر نبضة عملية", detail.heartbeat_at
      ? new Date(detail.heartbeat_at).toLocaleTimeString("ar") : "—");
    var left = wfRemaining(detail.hard_deadline_at);
    row("السقف الصلب المتبقي", left === null ? "غير معلن"
      : wfSeconds(left) + " (حد " + wfSeconds(detail.hard_timeout_s) + ")");
    card.appendChild(rows);
    return card;
  }

  /** الأدوار الحية (§23): دور واحد نشط + تاريخ مضغوط. */
  function renderRoles(snap) {
    var role = (snap.activity || {}).role || "";
    if (!role) return null;
    var ROLE_LABELS = {
      thinker: "المفكر", implementer: "المنفذ",
      verifier: "المتحقق", reviewer: "المراجع",
      arbiter: "المحكَّم", coordinator: "المنسق",
    };
    var order = ["thinker", "implementer", "verifier", "reviewer",
                 "arbiter"];
    var box = el("div", "wf-roles");
    var seen = {};
    if (role && order.indexOf(role) === -1) role = "coordinator";
    seen[role] = true;
    box.appendChild(el("span", "wf-role current",
      "● " + (ROLE_LABELS[role] || role) + " نشط"));
    var trail = el("span", "wf-roles-trail");
    order.forEach(function (key) {
      if (key === role) return;
      var chip = el("span", "wf-role muted",
        "✓ " + (ROLE_LABELS[key] || key));
      chip.title = "دورة الأدوار الخمسة — الدور النشط واحد فقط";
      trail.appendChild(chip);
    });
    box.appendChild(trail);
    return box;
  }

  /** تقدم حقيقي (§50): خطوات مكتملة/كلية من الأحداث — لا نسب مخترعة. */
  function renderProgress(snap) {
    var p = snap.progress || {};
    if (!p.steps_total) return null;
    var box = el("div", "wf-progress");
    var bar = el("div", "wf-progress-bar");
    var fill = el("div", "wf-progress-fill");
    fill.style.width = (p.percent || 0) + "%";
    bar.appendChild(fill);
    box.appendChild(bar);
    box.appendChild(el("span", "wf-progress-text",
      p.steps_completed + " / " + p.steps_total + " خطوة" +
      (p.steps_failed ? " · فشلت " + p.steps_failed : "")));
    return box;
  }

  /** تفاصيل مرحلة (§20) — نقرة تفتح العملية الجارية والأدوات والدور.
   * تنشئ اللوحة وتعيدها؛ النقر على مرحلة يملأها ببياناتها. */
  function renderStageDetails(container, snap, stageKey) {
    var panel = container.querySelector(".wf-details");
    if (!panel) {
      panel = el("div", "wf-details");
      panel.hidden = true;
    }
    if (stageKey == null) {
      return panel;   // الإطار فقط — يُخفى حتى تنقر مرحلة
    }
    panel.textContent = "";
    panel.hidden = false;
    var head = el("div", "wf-details-head");
    head.appendChild(el("span", "wf-details-title",
      "المرحلة: " + ((snap.stage_labels || {})[stageKey] || stageKey)));
    var close = el("button", "wf-details-close", "✕");
    close.addEventListener("click", function () { panel.hidden = true; });
    head.appendChild(close);
    panel.appendChild(head);

    var rows = el("div", "wf-details-rows");
    function row(label, value) {
      if (value === undefined || value === null || value === "") return;
      var r = el("div", "wf-details-row");
      r.appendChild(el("span", "wf-pl-k", label));
      r.appendChild(el("span", "wf-pl-v", String(value)));
      rows.appendChild(r);
    }
    var waiting = snap.waiting_for || {};
    var activity = snap.activity || {};
    row("الحالة", STATUS_LABELS[snap.status] || snap.status);
    row("ينتظر", waiting.label || "—");
    if (stageKey === "EXECUTE" && snap.progress &&
        snap.progress.current_step) {
      row("العملية الجارية", snap.progress.current_step.objective);
    }
    row("الدور النشط", activity.role || "—");
    row("الأداة الأخيرة", activity.tool || "—");
    row("المزود", activity.provider || "");
    if (snap.environment && snap.environment.state) {
      row("بيئة التنفيذ", snap.environment.state === "READY"
        ? "✓ جاهزة" : snap.environment.state);
    }
    row("العامل", snap.worker ? "✓ متصل" : "—");
    if (snap.elapsed_s != null) {
      row("مضى", Math.round(snap.elapsed_s) + " ثانية");
    }
    panel.appendChild(rows);
  }

  /** تبويب سير العمل — الأنابيب + العوائق + التخطيط الحي + الأدوار. */
  function renderWorkflowTab(body, snap) {
    body.textContent = "";
    var card = el("div", "wf-card");
    card.appendChild(renderPipeline(card, snap));
    var blocking = renderBlocking(card, snap);
    if (blocking) card.appendChild(blocking);
    var planning = renderPlanningLive(snap);
    if (planning) card.appendChild(planning);
    card.appendChild(renderStageDetails(card, snap, null));
    var roles = renderRoles(snap);
    if (roles) card.appendChild(roles);
    var progress = renderProgress(snap);
    if (progress) card.appendChild(progress);
    body.appendChild(card);
  }

  /** تبويب النظرة العامة — الهدف والخطة والبيئة بإيجاز هادئ. */
  function renderOverviewTab(body, snap, snapshot) {
    body.textContent = "";
    var card = el("div", "wf-card wf-overview");
    card.appendChild(el("h3", "wf-section-title", "الهدف"));
    var objective = el("div", "wf-objective");
    objective.dir = "auto";
    objective.textContent = snap.objective || "";
    card.appendChild(objective);

    var plan = snapshot && snapshot.plan;
    if (plan) {
      card.appendChild(el("h3", "wf-section-title",
        "الخطة v" + plan.version +
        (plan.approved ? " — معتمدة" : " — بانتظار اعتمادك")));
      var phases = el("div", "wf-phases");
      ((plan.phases || []).length ? plan.phases :
        (snapshot.phases || [])).forEach(function (phase, i) {
        var line = el("div", "wf-phase-line");
        line.textContent = (i + 1) + ". " + (phase.title || "") +
          " (" + ((phase.steps || []).length) + " خطوة)";
        phases.appendChild(line);
      });
      card.appendChild(phases);
    }

    if (snap.last_error) {
      var errBox = el("div", "wf-blocking");
      errBox.appendChild(el("div", "wf-blocking-title", "آخر خطأ معلن"));
      errBox.appendChild(el("div", "wf-blocking-reason",
                            snap.last_error));
      card.appendChild(errBox);
    }
    body.appendChild(card);
  }

  /** تبويب الأدلة (§48) — نوع/طابع/مصدر/حالة لكل بند. */
  function renderEvidenceTab(body, projectId) {
    body.textContent = "";
    var card = el("div", "wf-card");
    card.appendChild(el("h3", "wf-section-title", "الأدلة"));
    Hub.fetchJSON("/api/projects/" + projectId + "/evidence")
      .then(function (out) {
        if (!out.ok) {
          card.appendChild(el("div", "wf-empty",
            "تعذر تحميل الأدلة — " + (out.j && out.j.detail)));
          return;
        }
        var items = out.j.evidence || [];
        if (!items.length) {
          card.appendChild(el("div", "wf-empty",
            "لا أدلة بعد — تُنتج مع كل خطوة تنفيذ مكتملة"));
          return;
        }
        items.forEach(function (item) {
          var row = el("div", "wf-evidence-row");
          row.appendChild(el("span", "wf-evidence-badge",
            item.verdict === "PASS" ? "✓" : "·"));
          var text = el("div", "wf-evidence-text");
          text.appendChild(el("div", "wf-evidence-line",
            "خطوة #" + (item.step_id || "—") + " · " +
            (item.verdict || "")));
          var files = Object.keys(item.files || {});
          if (files.length) {
            /* (AES-ORACLE-UI-RUNTIME-002 §4) ملفات الأدلة قابلة
             * للفتح والتنزيل بنفس عقد المخرجات — لا أسماء بلا وصول */
            var filesWrap = el("div", "wf-evidence-files");
            files.forEach(function (fname) {
              var meta = (item.files || {})[fname] || {};
              var fa = {
                name: fname,
                kind: "file",
                evidence_id: item.id,
                bytes: meta.bytes || 0,
                sha256: meta.sha256 || "",
              };
              var frow = el("div", "wf-artifact-row");
              frow.appendChild(el("span", "wf-artifact-icon", "📄"));
              var ftext = el("div", "wf-evidence-text");
              ftext.appendChild(el("div", "wf-evidence-line", fname));
              if (fa.bytes) {
                ftext.appendChild(el("div", "wf-evidence-sub",
                  (fa.bytes / 1024).toFixed(1) + " كيلوبايت"));
              }
              frow.appendChild(ftext);
              frow.appendChild(artifactActionsRow(projectId, fa));
              filesWrap.appendChild(frow);
            });
            text.appendChild(filesWrap);
          }
          row.appendChild(text);
          row.appendChild(el("span", "wf-evidence-time",
            (item.created_at || "").slice(11, 19)));
          card.appendChild(row);
        });
      });
    body.appendChild(card);
  }

  /** تبويب المخرجات (§47) — من الأدلة الدائمة حصرًا. */
  function renderArtifactsTab(body, projectId) {
    body.textContent = "";
    var card = el("div", "wf-card");
    card.appendChild(el("h3", "wf-section-title", "المخرجات"));
    Hub.fetchJSON("/api/projects/" + projectId + "/artifacts")
      .then(function (out) {
        if (!out.ok) return;
        var items = out.j.artifacts || [];
        if (!items.length) {
          card.appendChild(el("div", "wf-empty",
            "لا مخرجات بعد — ما لم يُثبت لا يُعرض"));
          return;
        }
        items.forEach(function (a) {
          var row = el("div", "wf-artifact-row");
          row.appendChild(el("span", "wf-artifact-icon",
            a.kind === "file" ? "📄" : "📦"));
          var text = el("div", "wf-evidence-text");
          text.appendChild(el("div", "wf-evidence-line", a.name));
          var subBits = [];
          if (a.kind === "file" && fileExt(a.name)) {
            subBits.push(String(fileExt(a.name)).toUpperCase());
          }
          if (a.bytes) {
            subBits.push((a.bytes / 1024).toFixed(1) + " كيلوبايت");
          }
          if (a.verdict) subBits.push("الدليل: " + a.verdict);
          if (subBits.length) {
            text.appendChild(el("div", "wf-evidence-sub",
              subBits.join(" · ")));
          }
          row.appendChild(text);
          row.appendChild(artifactActionsRow(projectId, a));
          var sha = el("button", "wf-artifact-sha", "sha256");
          sha.title = a.sha256 || "";
          sha.addEventListener("click", function () {
            if (navigator.clipboard && a.sha256) {
              navigator.clipboard.writeText(a.sha256);
              sha.textContent = "نُسخ ✓";
              setTimeout(function () { sha.textContent = "sha256"; },
                1200);
            }
          });
          row.appendChild(sha);
          card.appendChild(row);
        });
      });
    body.appendChild(card);
  }

  /** تبويب التاريخ (§16+§43) — صفحات بمؤشر رجوع لا غرق DOM. */
  function renderHistoryTab(body, projectId) {
    body.textContent = "";
    var card = el("div", "wf-card");
    card.appendChild(el("h3", "wf-section-title",
      "التاريخ — كل ما حدث، صفحة صفحة"));
    var list = el("div", "wf-history-list");
    card.appendChild(list);
    var more = el("button", "wf-history-more", "تحميل الأقدم");
    var state = { before: 0 };

    function loadPage() {
      var url = "/api/projects/" + projectId +
        "/history?limit=60" +
        (state.before ? "&before_id=" + state.before : "");
      Hub.fetchJSON(url).then(function (out) {
        if (!out.ok) return;
        var events = out.j.events || [];
        events.forEach(function (event) {
          list.appendChild(historyLine(event));
        });
        more.hidden = !out.j.has_more;
        if (out.j.has_more) state.before = out.j.next_before;
        if (!events.length && !list.children.length) {
          list.appendChild(el("div", "wf-empty", "لا أحداث بعد"));
        }
      });
    }
    more.addEventListener("click", loadPage);
    card.appendChild(more);
    body.appendChild(card);
    loadPage();
  }

  /** سطر تاريخ مفهوم (§16) — انتقالات/قرارات/إعادات/فشل/أدلة. */
  function historyLine(event) {
    var line = el("div", "wf-history-line");
    var time = (event.created_at || "").slice(11, 19);
    line.appendChild(el("span", "wf-history-time", time || "·"));
    line.appendChild(el("span", "wf-history-dot",
      eventKindDot(event.kind)));
    var text = el("span", "wf-history-text");
    text.dir = "auto";
    text.textContent = historyText(event);
    line.appendChild(text);
    var details = el("button", "wf-history-json", "{…}");
    details.title = "التفاصيل التقنية";
    details.addEventListener("click", function () {
      Hub.openModal({
        role: "workflow", kind: event.kind, payload: event.payload,
      });
    });
    line.appendChild(details);
    return line;
  }

  function eventKindDot(kind) {
    if (/(FAIL|BLOCKED|INTERRUPTED|ERROR)/.test(kind)) return "⚠";
    if (/(COMPLETED|PASS|READY|APPROVED|VERIFIED)/.test(kind)) return "✓";
    if (/(STARTED|OPENED|RESUMED)/.test(kind)) return "●";
    return "·";
  }

  var HISTORY_LABELS = {
    PROJECT_CREATED: "أُنشئ المشروع",
    PLANNING_STARTED: "بدأ توليد الخطة",
    PLAN_GENERATING: "التوليد يستدعي النموذج",
    PLAN_CREATED: "وُلدت الخطة",
    PLAN_APPROVAL_REQUIRED: "الخطة تنتظر اعتمادك",
    PLAN_APPROVED: "اعتمدت الخطة",
    PLANNING_FAILED: "فشل توليد الخطة",
    PLANNING_INTERRUPTED: "انقطع توليد الخطة",
    PLANNING_RETRY: "أُعيدت محاولة التوليد",
    PREFLIGHT_STARTED: "بدأ فحص الجاهزية",
    PREFLIGHT_PASS: "الفحص نجح",
    PREFLIGHT_BLOCKED: "الفحص محجوب",
    EXECUTION_OPENED: "فُتح التنفيذ",
    PHASE_STARTED: "بدأت مرحلة",
    PHASE_COMPLETED: "اكتملت مرحلة",
    STEP_STARTED: "بدأت خطوة",
    STEP_COMPLETED: "اكتملت خطوة",
    EXECUTION_STARTED: "بدأ تنفيذ",
    EXECUTION_COMPLETED: "اكتمل تنفيذ",
    EXECUTION_FAILED: "فشل تنفيذ",
    EXECUTION_BLOCKED: "التنفيذ محجوب — مزود غير جاهز",
    EVIDENCE_CREATED: "دليل جديد",
    AUDIT_COMPLETED: "تدقيق",
    REVIEW_COMPLETED: "مراجعة اكتملت",
    TEST_COMPLETED: "اختبار اكتمل",
    RETRY_REQUESTED: "إعادة محاولة",
    OWNER_GATE_RESOLVED: "قرار مالك",
    JOB_CREATED: "وظيفة جديدة",
    JOB_STARTED: "بدأت الوظيفة",
    JOB_WAITING: "الوظيفة تنتظر",
    JOB_FAILED: "فشلت الوظيفة",
    JOB_PAUSED: "الوظيفة متوقفة مؤقتًا",
    PROJECT_PAUSED: "المشروع متوقف مؤقتًا",
    PROJECT_STOPPED: "أُوقف المشروع نهائيًا",
    PROJECT_RESUMED: "استؤنف المشروع",
    PROJECT_ARCHIVED: "أُرشف المشروع",
    PROJECT_RESTORED: "استُرجع المشروع",
    PROJECT_RENAMED: "أُعيدت التسمية",
    PROJECT_DUPLICATED: "نسخة من مشروع",
    PROJECT_VERIFIED: "تحقق نهائي",
    OWNER_STOP_REQUESTED: "طلبت الإيقاف",
    WORKFLOW_DIAGNOSED: "تشخيص سير العمل",
    MODEL_CALL_STARTED: "استدعاء نموذج بدأ",
    MODEL_CALL_COMPLETED: "استدعاء نموذج اكتمل",
    MODEL_CALL_FAILED: "استدعاء نموذج فشل",
    CHECKPOINT_CREATED: "نقطة حفظ",
    STAGE_REVIEW: "مراجعة مرحلة",
    ROLE_EXECUTING: "دور يعمل",
    TOOL_EXECUTION: "أداة",
    FILE_WRITTEN: "كُتب ملف",
    BROWSER_NAVIGATE: "تنقّل متصفح",
    BROWSER_SCREENSHOT: "لقطة متصفح",
    BROWSER_PAGE_LOADED: "تحميل صفحة",
    BROWSER_FAILURE: "فشل متصفح",
    GATE_AUTO_RESOLVED: "بوابة حُلَّت آليًا",
  };

  function historyText(event) {
    var label = HISTORY_LABELS[event.kind] || event.kind;
    var payload = event.payload || {};
    var extra = "";
    if (event.kind === "PLANNING_FAILED" && payload.error_class) {
      extra = " [" + payload.error_class + "]";
    }
    if (event.kind === "MODEL_CALL_FAILED" && payload.error_class) {
      extra = " [" + payload.error_class + "]";
    }
    if (event.kind === "PHASE_STARTED" && payload.title) {
      extra = ": " + payload.title;
    }
    if (event.kind === "STEP_STARTED" && payload.objective) {
      extra = ": " + String(payload.objective).slice(0, 60);
    }
    if (event.kind === "TOOL_EXECUTION" && payload.tool) {
      extra = ": " + payload.tool + " " + (payload.phase || "");
    }
    return label + extra;
  }

  /* ---------- (AES-LIVE-FACTORY-E2E-001 المرحلة 4) مساحة المشاهدة الحية ----------
   *
   * ثلاث لوحات مربوطة بالتشغيل نفسه لا بنسخ منفصلة:
   * - المعاينة: الموقع قيد البناء من ملفات المشروع الحقيقية
   *   عبر /preview — إطار حي + فتح مستقل + حالة صادقة قبل أول index.html.
   * - متصفح الوكيل: لقطات Chromium حقيقية من أحداث BROWSER_SCREENSHOT
   *   الدائمة (بصمة sha256 تُتحقق عند التقديم) + خط التنقل والنقر.
   * - الطرفية: تيار الأدوات والأوامر الفعلي (TOOL_EXECUTION بدء/نجاح/
   *   فشل + FILE_WRITTEN) — لا سلسلة تفكير خام.
   * كل لوحة تُغذي نفسها بنبض خفيف وتتوقف حين تغادر تبويبها. */

  function inDocument(node) {
    return node && document.contains(node);
  }

  function fmtBytes(n) {
    n = Number(n) || 0;
    if (n >= 1048576) return (n / 1048576).toFixed(1) + " م.ب";
    if (n >= 1024) return (n / 1024).toFixed(1) + " ك.ب";
    return n + " بايت";
  }

  function fmtClock(iso) {
    return String(iso || "").slice(11, 19) || "·";
  }

  /** تبويب المعاينة (4أ) — إطار حي من مساحة المشروع الفعلية. */
  function renderPreviewTab(body, projectId) {
    body.textContent = "";
    var card = el("div", "wf-card");
    card.appendChild(el("h3", "wf-section-title",
      "معاينة الموقع — قيد البناء من ملفات المشروع"));
    var status = el("div", "wf-preview-status",
      "…يفحص مساحة العمل");
    card.appendChild(status);
    var frameWrap = el("div", "wf-preview-wrap");
    frameWrap.hidden = true;
    var frameBar = el("div", "wf-preview-bar");
    var urlBox = el("span", "wf-preview-url", "");
    var openBtn = el("button", "wf-preview-open", "فتح مستقل");
    var reloadBtn = el("button", "wf-preview-open", "تحديث");
    frameBar.appendChild(urlBox);
    frameBar.appendChild(reloadBtn);
    frameBar.appendChild(openBtn);
    var frame = el("iframe", "wf-preview-frame");
    frame.setAttribute("title", "معاينة الموقع");
    frame.setAttribute("loading", "lazy");
    frameWrap.appendChild(frameBar);
    frameWrap.appendChild(frame);
    card.appendChild(frameWrap);
    var filesNote = el("div", "wf-preview-files", "");
    card.appendChild(filesNote);
    body.appendChild(card);

    function refresh() {
      Hub.fetchJSON("/api/projects/" + projectId + "/preview")
        .then(function (out) {
          if (!inDocument(status)) return;
          if (!out.ok) {
            status.textContent = "تعذر فحص المعاينة — " +
              (out.j && out.j.detail);
            return;
          }
          var meta = out.j || {};
          if (!meta.available) {
            status.textContent = meta.reason ||
              "لا توجد واجهة بعد";
            frameWrap.hidden = true;
            return;
          }
          status.textContent = "تُخدَّم من مساحة الخطوة #" +
            meta.step_id + " — " +
            ((meta.files || []).length) + " ملفاً";
          if (frame.getAttribute("src") !== meta.entry) {
            frame.setAttribute("src", meta.entry);
          }
          frameWrap.hidden = false;
          urlBox.textContent = meta.entry;
          var names = (meta.files || []).map(function (f) {
            return f.path;
          }).slice(0, 12);
          filesNote.textContent = names.length
            ? "ملفات الخدمة: " + names.join(" · ") : "";
        });
    }
    openBtn.addEventListener("click", function () {
      window.open(frame.getAttribute("src"), "_blank", "noopener");
    });
    reloadBtn.addEventListener("click", function () {
      if (frame.getAttribute("src")) {
        frame.setAttribute("src", frame.getAttribute("src"));
      }
      refresh();
    });
    refresh();
    var timer = setInterval(function () {
      if (!inDocument(status)) { clearInterval(timer); return; }
      refresh();
    }, 7000);
  }

  /** تبويب متصفح الوكيل (4ب) — لقطات حقيقية بخط زمني. */
  function renderBrowserTab(body, projectId) {
    body.textContent = "";
    var card = el("div", "wf-card");
    card.appendChild(el("h3", "wf-section-title",
      "متصفح الوكيل — جلسة Chromium حقيقية من التشغيل"));
    var status = el("div", "wf-preview-status", "…يُحمَّل");
    card.appendChild(status);
    var gallery = el("div", "wf-shot-gallery");
    card.appendChild(gallery);
    card.appendChild(el("h3", "wf-section-title",
      "خط التنقل والعمليات"));
    var timeline = el("div", "wf-browser-timeline");
    card.appendChild(timeline);
    body.appendChild(card);

    function refresh() {
      Hub.fetchJSON("/api/projects/" + projectId + "/browser-activity")
        .then(function (out) {
          if (!inDocument(status)) return;
          if (!out.ok) {
            status.textContent = "تعذر تحميل نشاط المتصفح — " +
              (out.j && out.j.detail);
            return;
          }
          var shots = out.j.screenshots || [];
          var lines = out.j.timeline || [];
          status.textContent = shots.length
            ? shots.length + " لقطة مثبتة · " + lines.length + " عملية"
            : "لا لقطات متصفح بعد — تظهر لحظة استخدام الوكيل للمتصفح";
          gallery.textContent = "";
          shots.slice(-12).forEach(function (shot) {
            var cell = el("div", "wf-shot-cell");
            var img = el("img", "wf-shot-img");
            img.setAttribute("src", shot.image_url);
            img.setAttribute("alt", "لقطة متصفح " + fmtClock(shot.at));
            img.setAttribute("loading", "lazy");
            cell.appendChild(img);
            var cap = el("div", "wf-shot-cap");
            cap.appendChild(el("span", "wf-shot-time",
              fmtClock(shot.at)));
            if (shot.url) {
              cap.appendChild(el("span", "wf-shot-url",
                String(shot.url).slice(0, 60)));
            }
            cell.appendChild(cap);
            gallery.appendChild(cell);
          });
          timeline.textContent = "";
          lines.slice(-30).reverse().forEach(function (line) {
            var row = el("div", "wf-browser-line");
            row.appendChild(el("span", "wf-history-time",
              fmtClock(line.at)));
            row.appendChild(el("span", "wf-history-dot", "🌐"));
            var text = el("span", "wf-history-text");
            text.dir = "auto";
            text.textContent = browserLineText(line);
            row.appendChild(text);
            timeline.appendChild(row);
          });
        });
    }
    refresh();
    var timer = setInterval(function () {
      if (!inDocument(status)) { clearInterval(timer); return; }
      refresh();
    }, 8000);
  }

  function browserLineText(line) {
    var labels = {
      BROWSER_SCREENSHOT: "لقطة شاشة",
      BROWSER_NAVIGATE: "انتقل إلى",
      BROWSER_PAGE_LOADED: "حُمّلت صفحة",
      BROWSER_CLICK: "نقر",
      BROWSER_TYPE: "كتابة",
      BROWSER_EXTRACT: "استخلص محتوى",
      BROWSER_DOWNLOAD: "نزّل ملفاً",
      BROWSER_SESSION_CREATED: "فُتحت جلسة متصفح",
      BROWSER_SESSION_CLOSED: "أُغلقت جلسة المتصفح",
      BROWSER_SESSION_INTERRUPTED: "انقطعت جلسة المتصفح",
      BROWSER_FAILURE: "فشل متصفح",
    };
    var label = labels[line.kind] || line.kind;
    var extra = line.url || line.summary || "";
    return label + (extra ? ": " + extra : "");
  }

  /** تبويب الطرفية (4ج) — تيار الأدوات والأوامر الفعلي. */
  function renderTerminalTab(body, projectId) {
    body.textContent = "";
    var card = el("div", "wf-card");
    card.appendChild(el("h3", "wf-section-title",
      "الطرفية — الأوامر والأدوات كما نُفذت"));
    var term = el("div", "wf-terminal");
    card.appendChild(term);
    var note = el("div", "wf-evidence-sub",
      "كل سطر حدث دائم: أداة/أمر + حالة + مدة. المخرجات الكاملة الطويلة في تبويب الأدلة والمخرجات.");
    card.appendChild(note);
    body.appendChild(card);

    var seen = {};
    var count = 0;

    function appendLine(event) {
      if (seen[event.id]) return;
      seen[event.id] = true;
      count += 1;
      var payload = event.payload || {};
      var line = el("div", "wf-terminal-line");
      line.appendChild(el("span", "wf-history-time",
        fmtClock(event.created_at)));
      var mark = "·";
      if (/FAIL|BLOCKED|ERROR/.test(event.kind)) mark = "✗";
      else if (/COMPLETED|PASS|WRITTEN|SUCCEED/.test(event.kind)) mark = "✓";
      else if (/STARTED|OPENED/.test(event.kind)) mark = "▸";
      line.appendChild(el("span", "wf-term-mark", mark));
      var text = el("span", "wf-term-text");
      text.dir = "auto";
      text.textContent = terminalText(event);
      line.appendChild(text);
      if (payload.duration_ms) {
        line.appendChild(el("span", "wf-term-dur",
          (payload.duration_ms / 1000).toFixed(1) + "ث"));
      }
      term.appendChild(line);
    }

    function refresh() {
      Hub.fetchJSON("/api/projects/" + projectId +
        "/events?limit=300")
        .then(function (out) {
          if (!inDocument(term)) return;
          if (!out.ok) return;
          var events = out.j.events || [];
          var fresh = 0;
          events.forEach(function (event) {
            if (terminalKind(event.kind)) {
              if (!seen[event.id]) fresh += 1;
              appendLine(event);
            }
          });
          if (fresh && term.scrollHeight - term.scrollTop < 220) {
            term.scrollTop = term.scrollHeight;
          }
          if (!term.children.length) {
            term.appendChild(el("div", "wf-empty",
              "لا تنفيذ أوامر بعد — يظهر هنا أول استدعاء أداة"));
          }
        });
    }
    refresh();
    var timer = setInterval(function () {
      if (!inDocument(term)) { clearInterval(timer); return; }
      refresh();
    }, 5000);
  }

  function terminalKind(kind) {
    kind = String(kind || "");
    return kind === "TOOL_EXECUTION" || kind === "FILE_WRITTEN" ||
      kind === "BROWSER_NAVIGATE" || kind === "BROWSER_SCREENSHOT" ||
      kind === "BROWSER_PAGE_LOADED" || kind === "BROWSER_FAILURE" ||
      kind === "STEP_STARTED" || kind === "STEP_COMPLETED" ||
      kind === "MODEL_CALL_STARTED" || kind === "MODEL_CALL_COMPLETED" ||
      kind === "MODEL_CALL_FAILED";
  }

  function terminalText(event) {
    var payload = event.payload || {};
    if (event.kind === "TOOL_EXECUTION") {
      var phase = payload.phase === "succeeded" ? "نجح"
        : payload.phase === "failed" ? "فشل" : "بدأ";
      var tool = payload.tool || "أداة";
      var summary = "";
      if (payload.tool === "write_file" ||
          payload.tool === "read_file") {
        try {
          var parsed = payload.summary;
          if (typeof parsed === "string" && parsed[0] === "{") {
            parsed = JSON.parse(parsed);
          }
          summary = " " + ((parsed && parsed.path) ||
            String(payload.summary).slice(0, 80));
        } catch (e) {
          summary = " " + String(payload.summary).slice(0, 80);
        }
      } else if (payload.summary) {
        summary = " " + String(payload.summary).slice(0, 80);
      }
      var err = payload.error ? " — " + payload.error : "";
      return tool + summary + " — " + phase + err;
    }
    if (event.kind === "FILE_WRITTEN") {
      return "كُتب ملف: " + (payload.path || "") +
        " (" + (payload.role || "") + ")";
    }
    if (event.kind === "MODEL_CALL_STARTED") {
      return "استدعاء نموذج (" + (payload.role || "") + ") " +
        (payload.model || "");
    }
    if (event.kind === "MODEL_CALL_COMPLETED") {
      return "اكتمل الاستدعاء (" + (payload.role || "") + ")";
    }
    if (event.kind === "MODEL_CALL_FAILED") {
      return "فشل استدعاء النموذج — " +
        String(payload.error_class || payload.error || "").slice(0, 80);
    }
    if (event.kind === "STEP_STARTED") {
      return "—— بدأت خطوة #" + (payload.step_id || "?") + ": " +
        String(payload.objective || "").slice(0, 70);
    }
    if (event.kind === "STEP_COMPLETED") {
      return "—— اكتملت خطوة #" + (payload.step_id || "?");
    }
    var label = HISTORY_LABELS[event.kind] || event.kind;
    return label + (payload.url ? ": " + payload.url : "");
  }

  /* ---------- (RLR-001 §3) مساحة التنفيذ الحية — لوحان متزامنان ----------
   *
   * اليسار: سجل التنفيذ الفعلي من أحداث المحرك الدائمة (أدوات + ملفات +
   *   استدعاءات نموذج + بوابات + توقف/استئناف + فشل مصنَّف) — بث SSE حي
   *   عبر LiveEvents مع استعادة من الدائم عند الفصل (last_event_id).
   * اليمين: المتصفح الحي — مرآة عرض من الجلسة الفعلية: آخر لقطة
   *   Chromium + شريط URL/حالة + معاينة المشروع من ملفاته الحقيقية.
   *   المرآة موسومة صراحة: ليست متصفحًا تفاعليًا مُبثًّا.
   * الحالات صريحة: متصل/منقطع-يعيد الاتصال/لا نشاط بعد. لا نشاط وهمي.
   */

  var LIVE_LOG_KINDS = {
    TOOL_EXECUTION: 1, FILE_WRITTEN: 1, BROWSER_NAVIGATE: 1,
    BROWSER_SCREENSHOT: 1, BROWSER_PAGE_LOADED: 1, BROWSER_FAILURE: 1,
    BROWSER_SESSION_CREATED: 1, BROWSER_SESSION_CLOSED: 1,
    BROWSER_SESSION_INTERRUPTED: 1, STEP_STARTED: 1, STEP_COMPLETED: 1,
    MODEL_CALL_STARTED: 1, MODEL_CALL_COMPLETED: 1, MODEL_CALL_FAILED: 1,
    EXECUTION_STARTED: 1, EXECUTION_COMPLETED: 1, EXECUTION_FAILED: 1,
    EXECUTION_BLOCKED: 1, PROVIDER_TRANSIENT_FAILURE: 1,
    RETRY_REQUESTED: 1, GATE_AUTO_RESOLVED: 1, OWNER_GATE_RESOLVED: 1,
    PLAN_APPROVAL_REQUIRED: 1, CHECKPOINT_CREATED: 1,
    AUDIT_COMPLETED: 1, ADJUDICATION_COMPLETED: 1, EVIDENCE_CREATED: 1,
  };

  var LIVE_STATE_LABELS = {
    DRAFT: "مسودة — لم تُولَّد خطة بعد",
    PLANNING: "قيد التخطيط",
    AWAITING_OWNER_APPROVAL: "بانتظار قرار المالك",
    READY: "جاهز للتنفيذ",
    RUNNING: "قيد التنفيذ",
    PAUSED: "موقوف — قابل للاستئناف",
    BLOCKED: "محجوب — بوابة مالك مفتوحة",
    COMPLETED: "مكتمل",
    FAILED: "فاشل",
    REVISING: "قيد المراجعة",
  };

  function renderLiveWorkspaceTab(body, projectId) {
    body.textContent = "";
    var split = el("div", "wf-live-split");
    var left = el("section", "wf-live-pane wf-live-log-pane");
    var right = el("section", "wf-live-pane wf-live-browser-pane");
    split.appendChild(left);
    split.appendChild(right);
    body.appendChild(split);

    /* ----- اللوح الأيسر: سجل التنفيذ الفعلي ----- */
    var logCard = el("div", "wf-card");
    var logHead = el("div", "wf-live-head");
    logHead.appendChild(el("h3", "wf-section-title",
      "سجل التنفيذ الفعلي — أحداث المحرك كما حدثت"));
    var conn = el("span", "wf-live-conn", "…يفحص الاتصال");
    logHead.appendChild(conn);
    logCard.appendChild(logHead);
    var stateRow = el("div", "wf-live-state", "الحالة: …");
    logCard.appendChild(stateRow);
    var term = el("div", "wf-terminal wf-live-term");
    logCard.appendChild(term);
    logCard.appendChild(el("div", "wf-evidence-sub",
      "كل سطر حدث دائم من المحرك. عند انقطاع الاتصال تُستعاد الأحداث " +
      "الفائتة من الخادم لا من ذاكرة الواجهة."));
    left.appendChild(logCard);

    var seen = {};
    var lastState = null;

    function appendLive(event) {
      if (seen[event.id]) return;
      seen[event.id] = true;
      var line = el("div", "wf-terminal-line");
      line.appendChild(el("span", "wf-history-time",
        fmtClock(event.created_at)));
      var mark = "·";
      if (/FAIL|BLOCKED|ERROR|INTERRUPTED/.test(event.kind)) mark = "✗";
      else if (/COMPLETED|PASS|WRITTEN|SUCCEED|RESOLVED/.test(event.kind)) {
        mark = "✓";
      } else if (/STARTED|OPENED|REQUESTED/.test(event.kind)) mark = "▸";
      line.appendChild(el("span", "wf-term-mark", mark));
      var text = el("span", "wf-term-text");
      text.dir = "auto";
      text.textContent = terminalText(event);
      line.appendChild(text);
      var payload = event.payload || {};
      if (payload.duration_ms) {
        line.appendChild(el("span", "wf-term-dur",
          (payload.duration_ms / 1000).toFixed(1) + "ث"));
      }
      if (payload.error_class) {
        line.appendChild(el("span", "wf-term-class",
          String(payload.error_class)));
      }
      term.appendChild(line);
      if (term.scrollHeight - term.scrollTop < 260) {
        term.scrollTop = term.scrollHeight;
      }
      if (event.kind === "PROVIDER_TRANSIENT_FAILURE") {
        line.classList.add("wf-live-transient");
      }
    }

    function refreshState() {
      Hub.fetchJSON("/api/projects/" + projectId + "/state")
        .then(function (out) {
          if (!inDocument(stateRow)) return;
          if (!out.ok) {
            stateRow.textContent = "تعذر قراءة الحالة — " +
              (out.j && out.j.detail);
            return;
          }
          lastState = out.j || {};
          var st = lastState.project && lastState.project.status
            || lastState.status || "?";
          var label = LIVE_STATE_LABELS[st] || st;
          var step = lastState.current_step || lastState.step;
          stateRow.textContent = "الحالة: " + label +
            (step && step.title ? " · الخطوة: " +
              String(step.title).slice(0, 50) : "") +
            (lastState.elapsed_s ? " · مضى " +
              fmtSeconds(lastState.elapsed_s) : "");
        });
    }

    function refreshBackfill() {
      Hub.fetchJSON("/api/projects/" + projectId + "/events?limit=300")
        .then(function (out) {
          if (!inDocument(term)) return;
          if (!out.ok) return;
          (out.j.events || []).forEach(function (event) {
            if (LIVE_LOG_KINDS[event.kind]) appendLive(event);
          });
          if (!term.children.length) {
            term.appendChild(el("div", "wf-empty",
              "لا نشاط تنفيذ بعد — يظهر هنا أول حدث حقيقي من المحرك " +
              "(تخطيط، أداة، ملف، متصفح، بوابة)"));
          }
        });
    }

    /* بث حي: اشتراك SSE — الأحداث الجديدة تُلحق لحظة وصولها */
    if (window.LiveEvents && window.LiveEvents.onEvent) {
      window.LiveEvents.onEvent(function (event) {
        if (!inDocument(term)) return;
        if (String(event.project_id || "") !== String(projectId)) return;
        if (LIVE_LOG_KINDS[event.kind]) appendLive(event);
      });
    }

    refreshState();
    refreshBackfill();
    var stateTimer = setInterval(function () {
      if (!inDocument(stateRow)) { clearInterval(stateTimer); return; }
      refreshState();
    }, 5000);

    /* ----- اللوح الأيمن: المتصفح الحي (مرآة الجلسة الفعلية) ----- */
    var mirrorCard = el("div", "wf-card");
    var mirrorHead = el("div", "wf-live-head");
    mirrorHead.appendChild(el("h3", "wf-section-title",
      "المتصفح الحي — مرآة من جلسة الوكيل الفعلية"));
    var mirrorTag = el("span", "wf-live-mirror-tag",
      "مرآة عرض من الجلسة الفعلية — ليست متصفحًا تفاعليًا مُبثًّا");
    mirrorHead.appendChild(mirrorTag);
    mirrorCard.appendChild(mirrorHead);
    var mirrorStrip = el("div", "wf-live-strip",
      "حالة الجلسة: …يُحمَّل");
    mirrorCard.appendChild(mirrorStrip);
    var shotWrap = el("div", "wf-live-shot");
    var shotImg = el("img", "wf-shot-img");
    shotImg.setAttribute("alt", "آخر لقطة من جلسة متصفح الوكيل");
    shotImg.setAttribute("loading", "lazy");
    shotWrap.appendChild(shotImg);
    var shotEmpty = el("div", "wf-empty",
      "لا لقطة بعد — تظهر لحظة استخدام الوكيل للمتصفح فعلًا");
    shotWrap.appendChild(shotEmpty);
    shotImg.hidden = true;
    mirrorCard.appendChild(shotWrap);
    var miniHead = el("div", "wf-live-mini-head",
      "معاينة المشروع من ملفاته الحقيقية");
    mirrorCard.appendChild(miniHead);
    var miniWrap = el("div", "wf-preview-wrap wf-live-mini");
    var miniFrame = el("iframe", "wf-preview-frame");
    miniFrame.setAttribute("title", "معاينة المشروع");
    miniFrame.setAttribute("loading", "lazy");
    miniWrap.appendChild(miniFrame);
    var miniStatus = el("div", "wf-preview-status", "…يفحص مساحة العمل");
    mirrorCard.appendChild(miniStatus);
    mirrorCard.appendChild(miniWrap);
    right.appendChild(mirrorCard);

    function refreshMirror() {
      Hub.fetchJSON("/api/projects/" + projectId + "/browser-activity")
        .then(function (out) {
          if (!inDocument(mirrorStrip)) return;
          if (!out.ok) {
            mirrorStrip.textContent = "تعذر تحميل نشاط المتصفح — " +
              (out.j && out.j.detail);
            return;
          }
          var shots = out.j.screenshots || [];
          var lines = out.j.timeline || [];
          var lastNav = null;
          for (var i = lines.length - 1; i >= 0; i -= 1) {
            if (lines[i].kind === "BROWSER_NAVIGATE" ||
                lines[i].kind === "BROWSER_PAGE_LOADED") {
              lastNav = lines[i];
              break;
            }
          }
          if (lastNav) {
            mirrorStrip.textContent =
              "آخر تنقل: " + (lastNav.url || "?") +
              (lines.length ? " · " + lines.length + " عملية مسجلة" : "");
          } else {
            mirrorStrip.textContent = shots.length
              ? shots.length + " لقطة مثبتة من الجلسة"
              : "لا جلسة متصفح بعد — الحالة صادقة لا تمثيلية";
          }
          if (shots.length) {
            var latest = shots[shots.length - 1];
            if (shotImg.getAttribute("src") !== latest.image_url) {
              shotImg.setAttribute("src", latest.image_url);
            }
            shotImg.hidden = false;
            shotEmpty.hidden = true;
          } else {
            shotImg.hidden = true;
            shotEmpty.hidden = false;
          }
        });
      Hub.fetchJSON("/api/projects/" + projectId + "/preview")
        .then(function (out) {
          if (!inDocument(miniStatus)) return;
          if (!out.ok) {
            miniStatus.textContent = "تعذر فحص المعاينة";
            return;
          }
          var meta = out.j || {};
          if (!meta.available) {
            miniStatus.textContent = meta.reason || "لا توجد واجهة بعد";
            miniWrap.hidden = true;
            return;
          }
          miniStatus.textContent = "تُخدَّم من مساحة الخطوة #" +
            meta.step_id + " — " + ((meta.files || []).length) + " ملفاً";
          if (miniFrame.getAttribute("src") !== meta.entry) {
            miniFrame.setAttribute("src", meta.entry);
          }
          miniWrap.hidden = false;
        });
    }
    refreshMirror();
    var mirrorTimer = setInterval(function () {
      if (!inDocument(mirrorStrip)) { clearInterval(mirrorTimer); return; }
      refreshMirror();
    }, 7000);

    /* حالة الاتصال الصادقة — من مدير البث لا من تخمين محلي */
    function refreshConn() {
      if (!inDocument(conn)) return;
      var off = document.body.classList.contains("live-disconnected");
      conn.textContent = off
        ? "منقطع — يعيد الاتصال ويستعيد الأحداث الفائتة…"
        : "متصل · بث حي";
      conn.classList.toggle("off", off);
    }
    refreshConn();
    document.addEventListener("visibilitychange", refreshConn);
    var connTimer = setInterval(refreshConn, 2000);
    var obs = new MutationObserver(refreshConn);
    obs.observe(document.body, { attributes: true,
                                 attributeFilter: ["class"] });
  }

  window.WorkflowView = {
    renderWorkflowTab: renderWorkflowTab,
    renderOverviewTab: renderOverviewTab,
    renderEvidenceTab: renderEvidenceTab,
    renderArtifactsTab: renderArtifactsTab,
    renderHistoryTab: renderHistoryTab,
    renderPreviewTab: renderPreviewTab,
    renderBrowserTab: renderBrowserTab,
    renderTerminalTab: renderTerminalTab,
    renderLiveWorkspaceTab: renderLiveWorkspaceTab,
    STATUS_LABELS: STATUS_LABELS,
  };
})();
