/* agent hub v2 — واجهة الدورة الكاملة + أحداث الموجّه (الأمر الثالث).
 * سقف دائم: <2000 سطر (يُفحص في tests/contracts/test_thinness.py).
 * البث: POST /api/cycle/stream يعيد أحداث SSE لحظة حدوثها — كل حدث دور
 * يُعرض برمزه وشارة حالته وزمنه ورابط تفاصيله (الـ JSON الكامل).
 * الموافقة: POST /api/cycle/verify — القناة الوحيدة إلى VERIFIED.
 */
(function () {
  "use strict";

  // ---------- عناصر ----------
  var $ = function (id) { return document.getElementById(id); };
  var messagesEl = $("messages");
  var welcomeEl = $("welcome");
  var inputEl = $("input");
  var sendEl = $("send");
  var scrollEl = $("chat-scroll");
  var conversationsEl = $("conversations");
  var modalBackdrop = $("modal-backdrop");
  var modalJson = $("modal-json");
  var modalTitle = $("modal-title");
  var modalClose = $("modal-close");

  // ---------- رموز الأدوار (تطابق core/roles.py) ----------
  var ROLE_LABELS = {
    thinker: { sym: "◆", ar: "المفكر" },
    reviewer: { sym: "◇", ar: "المدقق" },
    implementer: { sym: "▸", ar: "المنفذ" },
    verifier: { sym: "✦", ar: "المراجع" },
    arbiter: { sym: "⚖", ar: "المُحكَّم" },
    coordinator: { sym: "◉", ar: "المنسّق" },
    router: { sym: "⇄", ar: "الموجّه" },
    eoe: { sym: "⚡", ar: "محرك الأوامر" },
    user: { sym: "●", ar: "أنت" }
  };

  // ---------- شارات الحالات (تطابق core/roles.py + الحكمان الفرعيان) ----------
  var STATE_BADGES = {
    DRAFT: "◌ DRAFT",
    UNDER_REVIEW: "◌ UNDER_REVIEW",
    APPROVED: "◌ APPROVED",
    EXECUTING: "◌ EXECUTING",
    EXECUTED: "✓ EXECUTED",
    VERIFYING: "◌ VERIFYING",
    EVIDENCED: "✦ EVIDENCED",
    ADJUDICATED: "⚖ ADJUDICATED",
    VERIFIED: "✔ VERIFIED",
    FAILED: "✕ FAILED",
    ESCALATED_TO_HUMAN: "▲ ESCALATED_TO_HUMAN",
    NOT_EVIDENCED: "◌ NOT_EVIDENCED",
    STAGNANT: "▲ STAGNANT",
    STOPPING: "◌ STOPPING",
    STOPPED: "⏹ STOPPED"
  };

  var busy = false;
  var conversationStarted = false;

  // ---------- الأمر 004: تتبع الجارية القابلة للإيقاف + زر الإيقاف ----------
  var activeRun = null; // { kind: "cycle"|"mission", cycleId }
  var stopRunEl = $("stop-run");

  function resetStopButton() {
    if (!stopRunEl) return;
    stopRunEl.disabled = true;
    stopRunEl.innerHTML = "<b>■</b> إيقاف فوري";
  }

  function trackRun(event) {
    if (activeRun && !activeRun.cycleId && event.cycle_id) {
      activeRun.cycleId = event.cycle_id;
    }
  }

  function requestStop() {
    if (!activeRun || !stopRunEl || stopRunEl.disabled) return;
    if (activeRun.kind === "cycle" && !activeRun.cycleId) {
      stopRunEl.innerHTML = "<b>■</b> انتظر أول حدث…";
      return;
    }
    stopRunEl.disabled = true;
    stopRunEl.innerHTML = "<b>■</b> جارٍ طلب الإيقاف…";
    var isMission = activeRun.kind === "mission";
    var body = isMission
      ? { reason: "زر الإيقاف من الواجهة" }
      : { cycle_id: activeRun.cycleId, reason: "زر الإيقاف من الواجهة" };
    fetch(isMission ? "/api/mission/stop" : "/api/cycle/stop", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    })
      .then(function (resp) {
        return resp.json().then(function (j) { return { ok: resp.ok, j: j }; });
      })
      .then(function (out) {
        var r = (out.j && out.j.receipt) || {};
        var note = makeRoleMessage({
          role: "coordinator",
          kind: "stop.receipt",
          state: "STOPPING",
          text: out.ok
            ? "■ طلب الإيقاف قُبل (" + (r.requested_by || "owner") +
              " عند " + (r.at || "?") +
              ") — يُكرّم عند أقرب حدّ آمن، واللقطة ستُكتب"
            : "تعذّر طلب الإيقاف: " + ((out.j && out.j.detail) || "خطأ غير معروف"),
          details: out.j || {}
        });
        note.root.classList.add("stop-card");
        insertBeforeWorking(note.root);
        if (!out.ok) resetStopButton();
      })
      .catch(function (err) {
        resetStopButton();
      });
  }

  if (stopRunEl) {
    stopRunEl.addEventListener("click", function () {
      if (busy) requestStop();
    });
  }

  // ---------- أدوات ----------
  function scrollDown() {
    scrollEl.scrollTop = scrollEl.scrollHeight;
  }

  function hideWelcome() {
    if (welcomeEl) welcomeEl.style.display = "none";
  }

  function badgeFor(state) {
    if (!state) return null;
    return STATE_BADGES[state] || state;
  }

  function fmtTime(ms) {
    if (!ms && ms !== 0) return "";
    if (ms < 1000) return ms + "مث";
    return (ms / 1000).toFixed(1) + "ث";
  }

  // ---------- بناء رسالة دور: رمز + اسم + شارة + زمن + تفاصيل ----------
  function makeRoleMessage(event) {
    var meta = ROLE_LABELS[event.role] || { sym: "·", ar: event.role };
    var wrap = document.createElement("div");
    wrap.className = "msg role";

    var head = document.createElement("div");
    head.className = "msg-meta";

    var sym = document.createElement("span");
    sym.className = "sym"; sym.textContent = meta.sym;
    var who = document.createElement("span");
    who.className = "who"; who.textContent = meta.ar;
    head.appendChild(sym); head.appendChild(who);

    var badgeText = badgeFor(event.state);
    if (badgeText) {
      var badge = document.createElement("span");
      badge.className = "msg-badge" +
        (event.kind === "task_verification" && event.state === "NOT_EVIDENCED"
          ? " dim" : "") +
        (event.state === "VERIFIED" || event.state === "ESCALATED_TO_HUMAN"
          ? " final" : "");
      badge.textContent = badgeText;
      head.appendChild(badge);
    }

    if (event.duration_ms) {
      var time = document.createElement("span");
      time.className = "msg-time";
      time.textContent = fmtTime(event.duration_ms);
      head.appendChild(time);
    }

    var link = document.createElement("span");
    link.className = "details-link";
    link.textContent = "عرض التفاصيل";
    link.addEventListener("click", function () { openModal(event); });
    head.appendChild(link);

    var body = document.createElement("div");
    body.className = "msg-body";
    body.textContent = event.text || "";

    wrap.appendChild(head); wrap.appendChild(body);
    return { root: wrap, body: body };
  }

  function addUserMessage(text) {
    var wrap = document.createElement("div");
    wrap.className = "msg user";
    var head = document.createElement("div");
    head.className = "msg-meta";
    var sym = document.createElement("span");
    sym.className = "sym"; sym.textContent = "●";
    var who = document.createElement("span");
    who.className = "who"; who.textContent = "أنت";
    head.appendChild(sym); head.appendChild(who);
    var body = document.createElement("div");
    body.className = "msg-body";
    body.textContent = text;
    wrap.appendChild(head); wrap.appendChild(body);
    messagesEl.appendChild(wrap);
    scrollDown();
  }

  // رقاقة تغيّر حالة الخطة — سطر رفيع بين الرسائل
  function addStateChip(event) {
    var chip = document.createElement("div");
    chip.className = "state-chip" +
      (event.state === "STOPPING" || event.state === "STOPPED" ? " chip-stop" : "");
    chip.textContent = event.state || "";
    messagesEl.appendChild(chip);
    scrollDown();
  }

  // مؤشر «الدورة تعمل» — يبقى أسفل القائمة حتى نهاية البث
  function addWorking() {
    var wrap = document.createElement("div");
    wrap.className = "msg role";
    wrap.id = "working-indicator";
    var head = document.createElement("div");
    head.className = "msg-meta";
    var sym = document.createElement("span");
    sym.className = "sym"; sym.textContent = "◉";
    var who = document.createElement("span");
    who.className = "who"; who.textContent = "الدورة تعمل";
    head.appendChild(sym); head.appendChild(who);
    var body = document.createElement("div");
    body.className = "msg-body";
    body.innerHTML = '<span class="typing"><i></i><i></i><i></i></span>';
    wrap.appendChild(head); wrap.appendChild(body);
    messagesEl.appendChild(wrap);
    scrollDown();
    return wrap;
  }

  function removeWorking() {
    var indicator = $("working-indicator");
    if (indicator) indicator.remove();
  }

  function insertBeforeWorking(node) {
    var indicator = $("working-indicator");
    if (indicator) {
      messagesEl.insertBefore(node, indicator);
    } else {
      messagesEl.appendChild(node);
    }
    scrollDown();
  }

  function markConversation(title) {
    if (conversationStarted) return;
    conversationStarted = true;
    var empty = $("conv-empty");
    if (empty) empty.remove();
    var item = document.createElement("div");
    item.className = "conv-item active";
    item.textContent = title;
    conversationsEl.appendChild(item);
  }

  // ---------- نافذة التفاصيل ----------
  function openModal(event) {
    var meta = ROLE_LABELS[event.role] || { sym: "·", ar: event.role };
    modalTitle.textContent = meta.sym + " " + meta.ar + " — " + event.kind;
    modalJson.textContent = JSON.stringify(event, null, 2);
    modalBackdrop.hidden = false;
  }

  function closeModal() { modalBackdrop.hidden = true; }

  modalClose.addEventListener("click", closeModal);
  modalBackdrop.addEventListener("click", function (e) {
    if (e.target === modalBackdrop) closeModal();
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") closeModal();
  });

  // ---------- عرض حدث واحد وفق نوعه ----------
  function renderEvent(event) {
    trackRun(event);
    if (event.role === "eoe") {
      renderEoeEvent(event);
      return;
    }
    switch (event.kind) {
      case "goal":
        return; // رسالة المستخدم عُرضت محليًا عند الإرسال
      case "state_change":
        addStateChip(event);
        return;
      case "cycle.stopped":
        renderStopCard(event);
        return;
      case "cycle.resumed":
      case "cycle.resume_requested": {
        var info = makeRoleMessage(event);
        insertBeforeWorking(info.root);
        return;
      }
      case "cycle_done":
        renderCycleDone(event);
        return;
      case "rate_limit.wait":
        addRouterWait(event);
        return;
      case "cooling.cooldown":
        addCooling(event);
        return;
      case "failover.logged":
        addFailover(event);
        return;
      case "router.call.logged":
        addCallLogged(event);
        return;
      case "router.demo.start":
      case "router.demo.phase":
      case "router.demo.done":
      case "router.demo.error":
        renderRouterDemo(event);
        return;
      case "mission.start":
        renderMissionStart(event);
        return;
      case "mission_done":
        renderMissionDone(event);
        return;
      case "mission_error": {
        var errMsg = makeRoleMessage(event);
        errMsg.body.classList.add("cycle-error");
        errMsg.body.textContent = "المهمة فشلت قبل الدورة: " +
          ((event.details || {}).error || event.text);
        removeWorking();
        messagesEl.appendChild(errMsg.root);
        scrollDown();
        return;
      }
      case "tool.call":
        renderToolCall(event);
        return;
      case "tool.site_declared": {
        var declared = makeRoleMessage(event);
        declared.body.textContent = "⚠ نفيذ معلن خارج الركيزة: " +
          event.tool + " (" + ((event.reason || "").slice(0, 90)) + ")";
        insertBeforeWorking(declared.root);
        return;
      }
      default: {
        // plan | plan_revised | review_verdict | task_execution |
        // task_verification | verification_rollup | arbiter_decision |
        // cycle_error | user_verification
        var msg = makeRoleMessage(event);
        if (event.kind === "cycle_error") {
          msg.body.classList.add("cycle-error");
        }
        insertBeforeWorking(msg.root);
      }
    }
  }

  // ---------- أحداث الموجّه (الأمر الثالث: الحزم الثلاث منقولة من v1) ----------

  function addRouterWait(event) {
    var d = event.details || {};
    var msg = makeRoleMessage(event);
    msg.body.textContent = "⏳ انتظار حد المعدل: " + d.wait_seconds +
      " ثانية" + (d.attempt ? " (المحاولة " + d.attempt + ")" : "");
    insertBeforeWorking(msg.root);
  }

  function addCooling(event) {
    var d = event.details || {};
    var msg = makeRoleMessage(event);
    msg.body.textContent = "🧊 تبريد اختناق: " + d.wait_s + " ثانية (محاولة " +
      d.attempt + " من " + d.max_waits + ")";
    if (d.reason) {
      var reason = document.createElement("div");
      reason.className = "router-reason";
      reason.textContent = "السبب: " + d.reason;
      msg.body.appendChild(reason);
    }
    insertBeforeWorking(msg.root);
  }

  function addFailover(event) {
    var d = event.details || {};
    var msg = makeRoleMessage(event);
    msg.body.textContent = "🔄 تبدّل المزود: من " + d.from + " إلى " + d.to +
      " (السبب: " + d.reason + ")";
    insertBeforeWorking(msg.root);
  }

  function addCallLogged(event) {
    var d = event.details || {};
    var msg = makeRoleMessage(event);
    msg.root.classList.add("router-call");
    msg.body.textContent = "";
    var line1 = document.createElement("div");
    line1.textContent = "استدعاء عبر الموجّه — المزود: " + d.provider +
      " · النموذج: " + d.model;
    var line2 = document.createElement("div");
    line2.textContent = "التوكنات: " + d.tokens + " · الزمن: " +
      fmtTime(d.duration_ms) +
      (d.cooled ? " · 🧊 تبريد ×" + d.cooling_waits : "") +
      (d.failed_over ? " · 🔄 تبدّل من " + d.failover_from : "");
    msg.body.appendChild(line1);
    msg.body.appendChild(line2);
    insertBeforeWorking(msg.root);
  }

  function renderRouterDemo(event) {
    var d = event.details || {};
    if (event.kind === "router.demo.done" || event.kind === "router.demo.error") {
      removeWorking();
      var done = makeRoleMessage(event);
      done.root.classList.add("cycle-summary");
      if (event.kind === "router.demo.error") {
        done.body.classList.add("cycle-error");
        done.body.textContent = "تعذّر عرض أحداث الموجّه: " + (d.error || "");
      } else if (d.note) {
        var note = document.createElement("div");
        note.textContent = d.note;
        done.body.appendChild(note);
      }
      messagesEl.appendChild(done.root);
      scrollDown();
      return;
    }
    // start | phase — سطر تمهيدي رفيع
    var intro = makeRoleMessage(event);
    intro.body.textContent = d.note || "تشغيل عرض أحداث الموجّه — الحزم الثلاث بنقل mock…";
    insertBeforeWorking(intro.root);
  }

  // ---------- خلاصة الدورة + زر الموافقة (القناة الوحيدة إلى VERIFIED) ----------
  function renderCycleDone(event) {
    removeWorking();
    var details = event.details || {};
    var msg = makeRoleMessage(event);
    msg.root.classList.add("cycle-summary");

    var stateLine = document.createElement("div");
    stateLine.textContent =
      "الحالة النهائية: " + (badgeFor(details.final_state) || details.final_state) +
      (details.sub_verdict ? "  ·  حكم فرعي: " + badgeFor(details.sub_verdict) : "");
    msg.body.appendChild(stateLine);

    if (details.tasks && details.tasks.length) {
      var tasksLine = document.createElement("div");
      tasksLine.textContent = "المهام: " + details.tasks.map(function (t) {
        return t.task_id + " (" + t.attempts + " محاولة" +
          (t.evidenced ? "، مثبتة)" : "، غير مثبتة)");
      }).join(" · ");
      msg.body.appendChild(tasksLine);
    }

    if (details.review_cycles) {
      var reviewLine = document.createElement("div");
      reviewLine.textContent = "جولات المراجعة: " + details.review_cycles;
      msg.body.appendChild(reviewLine);
    }

    if (details.arbiter_decisions && details.arbiter_decisions.length) {
      var arbLine = document.createElement("div");
      arbLine.textContent = "قرارات المحكَّم: " + details.arbiter_decisions.join(" · ");
      msg.body.appendChild(arbLine);
    }

    if (details.can_verify) {
      var btn = document.createElement("button");
      btn.className = "verify-btn";
      btn.textContent = "✔ أوافق على النتيجة";
      btn.addEventListener("click", function () { verifyCycle(event.cycle_id, btn); });
      msg.body.appendChild(btn);
    } else {
      var note = document.createElement("div");
      note.className = "verified-note";
      note.textContent =
        details.final_state === "ESCALATED_TO_HUMAN"
          ? "▲ الدورة صُعِّدت إليك — القرار النهائي قرارك"
          : "لا موافقة مطلوبة في هذا المسار";
      msg.body.appendChild(note);
    }

    messagesEl.appendChild(msg.root);
    scrollDown();
  }

  function verifyCycle(cycleId, btn) {
    btn.disabled = true;
    fetch("/api/cycle/verify", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ cycle_id: cycleId })
    })
      .then(function (resp) {
        if (!resp.ok) {
          return resp.json().then(function (err) {
            throw new Error(err.detail || ("HTTP " + resp.status));
          });
        }
        return resp.json();
      })
      .then(function (outcome) {
        btn.replaceWith(makeVerifiedNote());
        if (outcome.event) renderEvent(outcome.event);
        scrollDown();
      })
      .catch(function (err) {
        btn.disabled = false;
        btn.textContent = "تعذّرت الموافقة: " + err.message;
      });
  }

  function makeVerifiedNote() {
    var note = document.createElement("span");
    note.className = "verified-note";
    note.textContent = "✔ VERIFIED — موافقتك سُجّلت";
    return note;
  }

  // ---------- بث SSE عام (الدورة وعرض الموجّه على الملصق نفسه) ----------
  function postStream(url, body) {
    return fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    })
      .then(function (resp) {
        if (!resp.ok) throw new Error("HTTP " + resp.status);
        var reader = resp.body.getReader();
        var decoder = new TextDecoder("utf-8");
        var buffer = "";

        function pump() {
          return reader.read().then(function (chunk) {
            if (chunk.done) return;
            buffer += decoder.decode(chunk.value, { stream: true });
            var parts = buffer.split("\n\n");
            buffer = parts.pop();
            parts.forEach(function (part) {
              var line = part.split("\n")
                .find(function (l) { return l.indexOf("data:") === 0; });
              if (!line) return;
              var event;
              try { event = JSON.parse(line.slice(5).trim()); }
              catch (e) { return; }
              renderEvent(event);
            });
            return pump();
          });
        }
        return pump();
      });
  }

  function streamCycle(goal) {
    activeRun = { kind: "cycle", cycleId: "" };
    if (stopRunEl) { stopRunEl.disabled = false; }
    addWorking();
    postStream("/api/cycle/stream", { goal: goal })
      .then(finishStream, streamFailed);

    function streamFailed(err) {
      var fallback = makeRoleMessage({
        role: "coordinator",
        kind: "cycle_error",
        state: null,
        text: "تعذّر البث: " + err.message,
        details: { error: String(err.message) }
      });
      messagesEl.appendChild(fallback.root);
      finishStream();
    }

    function finishStream() {
      removeWorking();
      setBusy(false);
      activeRun = null;
      resetStopButton();
      scrollDown();
    }
  }

  // ---------- عرض أحداث الموجّه: الحزم الثلاث بنقل mock (الأمر الثالث) ----------
  function streamRouterDemo() {
    hideWelcome();
    markConversation("⇄ عرض أحداث الموجّه (الأمر الثالث)");
    addWorking();
    postStream("/api/router/demo", {})
      .then(finishDemo, demoFailed);

    function demoFailed(err) {
      var fallback = makeRoleMessage({
        role: "router",
        kind: "router.demo.error",
        state: null,
        text: "",
        details: { error: String(err.message) }
      });
      fallback.body.classList.add("cycle-error");
      fallback.body.textContent = "تعذّر البث: " + err.message;
      messagesEl.appendChild(fallback.root);
      finishDemo();
    }

    function finishDemo() {
      removeWorking();
      setBusy(false);
      if (routerDemoEl) routerDemoEl.disabled = false;
      scrollDown();
    }
  }

  function setBusy(state) {
    busy = state;
    sendEl.disabled = state;
    inputEl.disabled = state;
    if (!state) {
      inputEl.focus();
      updateSendLabel();
    }
  }

  // ---------- زر «ابدأ الدورة» يظهر عند كتابة الهدف ----------
  function updateSendLabel() {
    if (busy) return;
    var hasText = inputEl.value.trim().length > 0;
    sendEl.textContent = hasText ? "ابدأ الدورة" : "←";
    sendEl.classList.toggle("wide", hasText);
    sendEl.title = hasText ? "ابدأ دورة كاملة بين الأدوار الخمسة" : "اكتب هدفًا أولًا";
  }

  function send() {
    var text = inputEl.value.trim();
    if (!text || busy) return;
    inputEl.value = "";
    autoGrow();
    updateSendLabel();
    hideWelcome();
    markConversation(text.slice(0, 36));
    addUserMessage(text);
    setBusy(true);
    sendEl.textContent = "…";
    streamCycle(text);
  }

  // ---------- الإدخال ----------
  function autoGrow() {
    inputEl.style.height = "auto";
    inputEl.style.height = Math.min(inputEl.scrollHeight, 160) + "px";
  }

  // ---------- الأمر السادس: المهمة الحية (ربط نموذج حقيقي + PDF) ----------
  var missionRunEl = $("mission-run");

  // ---------- الأمر 004: بطاقة الإيقاف + الاستئناف ----------
  function renderStopCard(event) {
    var d = event.details || {};
    var msg = makeRoleMessage(event);
    msg.root.classList.add("stop-card");
    msg.body.textContent = "■ أُوقفت الدورة بأمر (" +
      (d.stopped_by || "المالك") + ") عند " +
      (d.honored_at_step || "؟") +
      " — الحالة والأدلة الجزئية محفوظة في " +
      (d.snapshot_path || "stop_snapshot.json");
    var sha = document.createElement("div");
    sha.className = "router-reason";
    sha.textContent = "لقطة sha256: " +
      String(d.snapshot_sha256 || "").slice(0, 20) + "…";
    msg.body.appendChild(sha);
    var resumeBtn = document.createElement("button");
    resumeBtn.className = "verify-btn";
    resumeBtn.textContent = "▶ استئناف من نقطة الإيقاف";
    resumeBtn.addEventListener("click", function () {
      resumeBtn.disabled = true;
      setBusy(true);
      resumeRun(event.cycle_id);
    });
    msg.body.appendChild(resumeBtn);
    insertBeforeWorking(msg.root);
  }

  function resumeRun(cycleId) {
    activeRun = { kind: "cycle", cycleId: cycleId };
    if (stopRunEl) { stopRunEl.disabled = false; }
    addWorking();
    postStream("/api/cycle/resume", { cycle_id: cycleId })
      .then(finishStream, streamFailed);

    function streamFailed(err) {
      var fallback = makeRoleMessage({
        role: "coordinator",
        kind: "cycle_error",
        state: null,
        text: "تعذّر الاستئناف: " + err.message,
        details: { error: String(err.message) }
      });
      messagesEl.appendChild(fallback.root);
      finishStream();
    }

    function finishStream() {
      removeWorking();
      setBusy(false);
      activeRun = null;
      resetStopButton();
      scrollDown();
    }
  }

  function renderMissionStart(event) {
    var msg = makeRoleMessage(event);
    msg.body.textContent = "🚀 مهمة حية — نموذج حقيقي بلا mock: " +
      (event.goal || "") +
      " — المصادر تجلب من الويب والـPDF يُولد داخل الركيزة";
    insertBeforeWorking(msg.root);
  }

  function renderToolCall(event) {
    var msg = makeRoleMessage(event);
    msg.root.classList.add("router-call");
    var a = event.args_summary || {};
    var desc = a.results !== undefined
      ? (a.results + " نتيجة — " + (a.first || ""))
      : a.pages !== undefined
        ? ("صفحات: " + a.pages)
        : (a.chars !== undefined ? (a.chars + " حرفًا") : (a.path || ""));
    msg.body.textContent = "🔧 " + event.tool + " — " + desc +
      " · sha256: " + String(event.output_sha256 || "").slice(0, 10) +
      " · " + (event.execution_site === "substrate"
        ? "داخل الركيزة" : "معلاَن خارجها") +
      " · " + fmtTime(event.duration_ms || 0);
    insertBeforeWorking(msg.root);
  }

  function renderMissionDone(event) {
    removeWorking();
    var d = event.details || {};
    var msg = makeRoleMessage(event);
    msg.root.classList.add("cycle-summary");
    if (event.verdict === "PASS") {
      msg.body.textContent = "✅ VERDICT: PASS — المهمة اكتملت بأدلة كاملة";
    } else if (event.verdict === "STOPPED") {
      msg.root.classList.add("mission-stopped");
      msg.body.textContent = "■ VERDICT: STOPPED — أُوقفت بأمر والأدلة الجزئية محفوظة — " +
        (event.text || "");
    } else {
      msg.body.classList.add("cycle-error");
      msg.body.textContent = "⛔ VERDICT: HARD STOP — " + (event.text || "");
    }
    var facts = document.createElement("div");
    facts.textContent =
      "الحالة: " + (d.final_state || "—") +
      " · صفحات PDF: " + (d.pdf_pages !== undefined ? d.pdf_pages : "—") +
      " · المصادر: " + (d.sources_count !== undefined ? d.sources_count : "—") +
      " · المدة: " + fmtTime(d.duration_ms || 0);
    msg.body.appendChild(facts);
    if (Array.isArray(d.verdict_reasons) && d.verdict_reasons.length) {
      var list = document.createElement("div");
      list.className = "router-reason";
      list.textContent = "أسباب التوقف: " + d.verdict_reasons.join(" · ");
      msg.body.appendChild(list);
    }
    if (event.verdict === "STOPPED") {
      var resumeM = document.createElement("button");
      resumeM.className = "verify-btn";
      resumeM.textContent = "▶ استئناف المهمة من اللقطة";
      resumeM.addEventListener("click", function () {
        resumeM.disabled = true;
        setBusy(true);
        streamMission("", true);
      });
      msg.body.appendChild(resumeM);
    }
    if (event.verdict === "PASS") {
      var openBtn = document.createElement("button");
      openBtn.className = "verify-btn ghost";
      openBtn.textContent = "📄 افتح التقرير";
      openBtn.addEventListener("click", function () {
        window.open("/api/mission/report", "_blank");
      });
      msg.body.appendChild(openBtn);
      if (d.cycle_id) {
        var verifyBtn = document.createElement("button");
        verifyBtn.className = "verify-btn";
        verifyBtn.textContent = "✔ أوافق على النتيجة";
        verifyBtn.addEventListener("click", function () {
          verifyMission(d.cycle_id, verifyBtn);
        });
        msg.body.appendChild(verifyBtn);
      }
    }
    var evLink = document.createElement("button");
    evLink.className = "verify-btn ghost";
    evLink.textContent = "🧾 الأدلة (evidence.json)";
    evLink.addEventListener("click", function () {
      window.open("/api/mission/evidence", "_blank");
    });
    msg.body.appendChild(evLink);
    messagesEl.appendChild(msg.root);
    scrollDown();
  }

  function verifyMission(cycleId, btn) {
    btn.disabled = true;
    fetch("/api/mission/verify", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ cycle_id: cycleId })
    })
      .then(function (resp) { return resp.json(); })
      .then(function () {
        btn.replaceWith(makeVerifiedNote());
        scrollDown();
      })
      .catch(function (err) {
        btn.disabled = false;
        btn.textContent = "تعذّرت الموافقة: " + err.message;
      });
  }

  function streamMission(goal, resume) {
    activeRun = { kind: "mission", cycleId: "" };
    if (stopRunEl) { stopRunEl.disabled = false; }
    addWorking();
    postStream(resume ? "/api/mission/resume" : "/api/mission/stream",
      resume ? {} : { goal: goal || "" })
      .then(finishStream, streamFailed);

    function streamFailed(err) {
      var fallback = makeRoleMessage({
        role: "mission",
        kind: "mission_error",
        state: null,
        text: "تعذّر البث: " + err.message,
        details: { error: String(err.message) }
      });
      messagesEl.appendChild(fallback.root);
      finishStream();
    }

    function finishStream() {
      removeWorking();
      busy = false;
      activeRun = null;
      resetStopButton();
      if (missionRunEl) missionRunEl.disabled = false;
      scrollDown();
    }
  }

  if (missionRunEl) {
    missionRunEl.addEventListener("click", function () {
      if (busy) return;
      setBusy(true);
      missionRunEl.disabled = true;
      hideWelcome();
      markConversation("🚀 المهمة الحية الافتراضية");
      var goalText = inputEl.value.trim();
      if (goalText) {
        addUserMessage(goalText);
        inputEl.value = "";
        autoGrow();
      } else {
        addUserMessage("نفّذ المهمة الافتراضية: تقرير جيوسياسي من صفحة، 5-8 مصادر، PDF عربي A4");
      }
      streamMission(goalText);
    });
  }

  var routerDemoEl = $("router-demo");
  if (routerDemoEl) {
    routerDemoEl.addEventListener("click", function () {
      if (busy) return;
      setBusy(true);
      routerDemoEl.disabled = true;
      streamRouterDemo();
    });
  }

  sendEl.addEventListener("click", send);
  inputEl.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  });
  inputEl.addEventListener("input", function () {
    autoGrow();
    updateSendLabel();
  });

  // ---------- حالة الركيزة من /health (إعلان صادق لا ادعاء) ----------
  fetch("/health")
    .then(function (r) { return r.json(); })
    .then(function (h) {
      var dot = $("substrate-dot");
      var label = $("substrate-label");
      if (!h.substrate) return;
      if (h.substrate.available) {
        dot.classList.add("on");
        dot.title = "تنفيذ معزول (namespaces + seccomp)";
        label.textContent = "الركيزة: معزولة ✓";
      } else {
        dot.classList.add("off");
        dot.title = "المنصة لا تدعم العزل — وضع متوافق معلن";
        label.textContent = "الركيزة: متوافمة (بلا عزل)";
      }
    })
    .catch(function () { /* الشارة تبقى رمادية = غير معروف */ });

  inputEl.focus();

  // ---------- الأمر الرابع: محرك الأوامر التنفيذية (EOE) ----------
  var eoeRunEl = $("eoe-run");

  var EOE_KIND_LABELS = {
    "order.parsed": "الأمر حُلّل — العقد والأقسام والقالب",
    "grant.requested": "منح مقترحة من الأمر",
    "grant.awaiting_owner": "بطاقة موافقة المنح",
    "grant.approved": "المنح وُقّعت بعد موافقتك",
    "section.started": "قسم بدأ",
    "section.proof": "إثبات قسم",
    "section.done": "قسم اكتمل",
    "hard_stop.fired": "توقف صلب",
    "push.awaiting_owner": "بطاقة موافقة الدفع",
    "push.approval_needed": "دفع ينتظر موافقتك",
    "push.done": "الدفع انتهى",
    "report.ready": "التقرير جاهز",
    "eoe.finished": "انتهى تنفيذ الأمر",
    "eoe.error": "خطأ EOE"
  };

  function eoeRunStream(orderText) {
    addWorking();
    postStream("/api/eoe/stream", { order_text: orderText })
      .then(finishStream, streamFailed);

    function streamFailed(err) {
      var fallback = makeRoleMessage({
        role: "eoe",
        kind: "eoe.error",
        state: null,
        text: "تعذّر بث الأمر: " + err.message,
        details: { error: String(err.message) }
      });
      messagesEl.appendChild(fallback.root);
      finishStream();
    }

    function finishStream() {
      removeWorking();
      busy = false;
      inputEl.value = "";
      autoGrow();
      scrollDown();
    }
  }

  function renderEoeEvent(event) {
    var kind = event.kind;
    var details = event.details || {};
    var label = EOE_KIND_LABELS[kind] || kind;
    var text = label;

    if (kind === "section.started") {
      text = "القسم §" + (details.section ?? "?") + " — " +
        (details.title || "") + " بدأ التنفيذ" +
        (details.commands && details.commands.length
          ? " (" + details.commands.length + " أمر معلن)"
          : "");
    } else if (kind === "section.done") {
      var st = details.state === "executed" ? "منفَّذ" :
        (details.state === "declared" ? "مُعلن" : "موقوف");
      text = "القسم §" + (details.section ?? "?") + " — " + st;
    } else if (kind === "section.proof") {
      if (details.inside_probe !== undefined) {
        text = "مسبار الكتابة الداخلي: " +
          (String(details.inside_probe).indexOf("PROBE-BLOCKED") === 0
            ? "محجوب (EROFS) — العزل سليم ✓"
            : String(details.inside_probe));
      } else {
        text = "إثبات خارجي §" + (details.section ?? "?") + ": " +
          (details.identical ? "البصمة متطابقة قبل/بعد ✓"
            : "اختلاف: " + JSON.stringify(details.diffs || []));
      }
    } else if (kind === "order.parsed") {
      text = "الأمر حُلّل: " + (details.sections ?? "?") + " أقسام · وضع " +
        (details.mode || "?") + " · " + (details.stops ?? "?") +
        " شرط توقف · " + (details.decisions ?? "?") + " قرارات مالك · " +
        (details.template_fields ?? "?") + " حقل قالب";
    } else if (kind === "hard_stop.fired") {
      text = "توقف صلب: " + (details.reason || "") + " — " +
        (details.detail || "").slice(0, 160);
    }

    var msg = makeRoleMessage({
      role: "eoe",
      kind: kind,
      state: kind === "hard_stop.fired" ? "HARD STOP" : null,
      text: text,
      details: details
    });
    if (kind === "section.started" || kind === "section.proof" ||
        kind === "section.done") {
      msg.root.classList.add("eoe-section");
    }
    if (kind === "hard_stop.fired") msg.root.classList.add("eoe-hardstop");

    if (kind === "grant.awaiting_owner") {
      msg.body.appendChild(
        makeApprovalCard(event.cycle_id, "grants", details.proposals || [])
      );
    } else if (kind === "push.awaiting_owner") {
      msg.body.appendChild(
        makeApprovalCard(event.cycle_id, "push", [
          { kind: "الدفع", scope: "موقع أحادي الاستخدام",
            target: "commit " + (details.commit_sha || "?") }
        ])
      );
    } else if (kind === "eoe.finished") {
      if (details.report_text) {
        var pre = document.createElement("pre");
        pre.className = "report-mono";
        pre.textContent = details.report_text;
        msg.body.appendChild(pre);
      }
      if (details.artifact_hash) {
        var hash = document.createElement("div");
        hash.className = "report-hash";
        hash.textContent = "artifact sha256: " + details.artifact_hash;
        msg.body.appendChild(hash);
      }
      var verdict = document.createElement("div");
      verdict.className = "approval-result";
      verdict.textContent = details.verdict === "PASS"
        ? "✔ VERDICT: PASS" : "✕ VERDICT: HARD STOP";
      msg.body.appendChild(verdict);
    }
    messagesEl.appendChild(msg.root);
    scrollDown();
  }

  function makeApprovalCard(runId, kind, items) {
    var card = document.createElement("div");
    card.className = "approval-card";
    var title = document.createElement("div");
    title.className = "approval-title";
    title.textContent = kind === "grants"
      ? "بطاقة موافقة المنح — بلا موافقتك لا وصول"
      : "بطاقة موافقة الدفع — موافقة موقعة أحادية الاستخدام";
    card.appendChild(title);

    var list = document.createElement("div");
    list.className = "approval-items";
    items.forEach(function (item) {
      var row = document.createElement("div");
      row.textContent = "• " + (item.kind || "") + " [" + (item.scope || "") +
        "] → " + (item.target || "");
      list.appendChild(row);
    });
    card.appendChild(list);

    var actions = document.createElement("div");
    actions.className = "approval-actions";
    var okBtn = document.createElement("button");
    okBtn.className = "btn-approve";
    okBtn.textContent = kind === "grants" ? "أوافق على المنح" : "أوافق على الدفع";
    var noBtn = document.createElement("button");
    noBtn.className = "btn-deny";
    noBtn.textContent = "أرفض";
    actions.appendChild(okBtn);
    actions.appendChild(noBtn);
    card.appendChild(actions);

    var result = document.createElement("div");
    result.className = "approval-result";
    card.appendChild(result);

    function decide(approved) {
      okBtn.disabled = true;
      noBtn.disabled = true;
      fetch("/api/eoe/approve", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ run_id: runId, kind: kind, approved: approved })
      })
        .then(function (resp) {
          if (!resp.ok) throw new Error("HTTP " + resp.status);
          return resp.json();
        })
        .then(function (outcome) {
          result.textContent = approved
            ? "✔ " + (outcome.note || "استؤنف التنفيذ")
            : "✕ الرفض مسجل — لا وصول (fail-closed)";
        })
        .catch(function (err) {
          result.textContent = "تعذرت الموافقة: " + err.message;
          okBtn.disabled = false;
          noBtn.disabled = false;
        });
    }
    okBtn.addEventListener("click", function () { decide(true); });
    noBtn.addEventListener("click", function () { decide(false); });
    return card;
  }

  if (eoeRunEl) {
    eoeRunEl.addEventListener("click", function () {
      if (busy) return;
      var orderText = inputEl.value.trim();
      if (!orderText) {
        inputEl.focus();
        return;
      }
      hideWelcome();
      conversationStarted = true;
      busy = true;
      eoeRunEl.disabled = true;
      setTimeout(function () { eoeRunEl.disabled = false; }, 400);
      var userMsg = makeRoleMessage({
        role: "user",
        kind: "order",
        state: null,
        text: "أمر تنفيذي (طوله " + orderText.length + " حرفًا) — نفّذه كما كُتب",
        details: { order_text: orderText.slice(0, 2000) }
      });
      messagesEl.appendChild(userMsg.root);
      scrollDown();
      eoeRunStream(orderText);
    });
  }


  // ================================================================ //
  // الأمر السادس المنقح — المزودات والمفاتيح + مهمة البناء textstats
  // ================================================================ //

  var providersBackdrop = $("providers-backdrop");
  var providersBody = $("providers-body");
  var providersOpenEl = $("providers-open");

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  // ---------- بطاقات المزودات (الأمر 005: بلا inline styles + رقاقات نماذج بمصدر معلن) ----------

  function pvModelsHtml(models, defaultModel, source) {
    if (!Array.isArray(models) || !models.length) return "";
    var chips = models.map(function (m) {
      return '<span class="pv-chip' + (m === defaultModel ? " default" : "") + '">' +
        esc(m) + (m === defaultModel ? " · الافتراضي" : "") + "</span>";
    }).join("");
    var srcLabel = source === "live"
      ? '<span class="pv-src live">● جُلبت حيًا الآن</span>'
      : '<span class="pv-src declared">◇ معلنة من البطاقة — بلا اتصال حي</span>';
    return '<div class="pv-models">' + chips + srcLabel + "</div>";
  }

  function renderProviderModels(name, box) {
    var result = box.querySelector('.pv-result[data-provider="' + name + '"]');
    var modelsBox = box.querySelector('.pv-models-box[data-provider="' + name + '"]');
    if (result) result.textContent = "…جلب قائمة النماذج";
    fetch("/api/providers/" + name + "/models?refresh=1")
      .then(function (r) { return r.json(); })
      .then(function (j) {
        var src = j.source || "live";
        if (result) {
          result.textContent = j.ok
            ? "اتصال ناجح — " + (j.models_count || 0) + " نموذج (" +
              (j.latency_ms || 0) + "ms)"
            : (j.message || "تعذّر الجلب الحي — تُعرض النماذج المعلنة");
        }
        if (modelsBox) {
          var card = box.querySelector('.pv-card[data-provider="' + name + '"]');
          var def = card ? (card.getAttribute("data-default") || "") : "";
          modelsBox.innerHTML = pvModelsHtml(j.model_ids, def, src);
        }
      })
      .catch(function (err) {
        if (result) result.textContent = "تعذّر الجلب: " + err.message;
      });
  }

  function loadProviders() {
    if (!providersBody) return;
    providersBody.textContent = "جارٍ التحميل…";
    fetch("/api/providers")
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var htmlParts = [];
        var store = data.store || {};
        htmlParts.push(
          '<div class="pv-store"><b>المخزن المحلي:</b> ' +
          esc(store.warning || store.file || "") +
          " · التشفير: " +
          (store.encryption_available ? "DPAPI (Windows)" : "صلاحيات 600") +
          "</div>"
        );
        (data.providers || []).forEach(function (p) {
          htmlParts.push(
            '<div class="pv-card" data-provider="' + esc(p.id) + '" data-default="' + esc(p.model) + '">' +
            '<div class="pv-head">' +
            '<span class="pv-title">' + esc(p.label) + "</span>" +
            '<span class="pv-status ' + (p.has_key ? "ok" : "none") + '">' +
            (p.has_key ? ("مفتاح محفوظ " + esc(p.key_masked)) : (p.requires_key ? "بلا مفتاح" : "بلا مفتاح مطلوب")) +
            "</span></div>" +
            '<div class="pv-meta">' + esc(p.base_url) +
            " · النموذج الافتراضي: " + esc(p.model) + "</div>" +
            '<div class="pv-note">' + esc(p.note || "") + "</div>"
          );
          if (p.requires_key) {
            htmlParts.push(
              '<div class="pv-row">' +
              '<input type="password" data-provider="' + esc(p.id) + '" class="pv-input" ' +
              'placeholder="مفتاح API — يُخزَّن مشفّرًا محليًا فقط">' +
              '<button class="pv-btn primary prov-save" data-provider="' + esc(p.id) + '">حفظ المفتاح</button>' +
              '<button class="pv-btn danger prov-delete" data-provider="' + esc(p.id) + '">حذف</button>' +
              "</div>"
            );
          }
          htmlParts.push(
            '<div class="pv-row" style="margin-top:8px">' +
            '<button class="pv-btn prov-test" data-provider="' + esc(p.id) + '">اختبار الاتصال</button>' +
            '<button class="pv-btn prov-models" data-provider="' + esc(p.id) + '">قائمة النماذج</button>' +
            "</div>" +
            '<div class="pv-result" data-provider="' + esc(p.id) + '"></div>' +
            '<div class="pv-models-box" data-provider="' + esc(p.id) + '">' +
            pvModelsHtml(p.known_models, p.model, "declared") +
            "</div></div>"
          );
        });
        providersBody.innerHTML = htmlParts.join("");

        providersBody.querySelectorAll(".prov-save").forEach(function (btn) {
          btn.addEventListener("click", function () {
            var name = btn.getAttribute("data-provider");
            var input = providersBody.querySelector('.pv-input[data-provider="' + name + '"]');
            var result = providersBody.querySelector('.pv-result[data-provider="' + name + '"]');
            btn.disabled = true;
            fetch("/api/providers/" + name + "/key", {
              method: "PUT",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ key: input.value })
            })
              .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
              .then(function (out) {
                result.textContent = out.ok ? "✔ حُفظ (" + (out.j.key_masked || "") + ")" : "✕ " + (out.j.detail || "فشل الحفظ");
                if (out.ok) { input.value = ""; loadProviders(); }
              })
              .catch(function (err) { result.textContent = "✕ " + err.message; })
              .finally(function () { btn.disabled = false; });
          });
        });
        providersBody.querySelectorAll(".prov-delete").forEach(function (btn) {
          btn.addEventListener("click", function () {
            var name = btn.getAttribute("data-provider");
            fetch("/api/providers/" + name + "/key", { method: "DELETE" })
              .then(function () { loadProviders(); });
          });
        });
        providersBody.querySelectorAll(".prov-test").forEach(function (btn) {
          btn.addEventListener("click", function () {
            var name = btn.getAttribute("data-provider");
            var result = providersBody.querySelector('.pv-result[data-provider="' + name + '"]');
            btn.disabled = true;
            result.textContent = "…اختبار الاتصال";
            fetch("/api/providers/" + name + "/test", { method: "POST" })
              .then(function (r) { return r.json(); })
              .then(function (j) {
                result.textContent = j.ok
                  ? "✔ اتصال ناجح (" + j.models_count + " نموذج، " + j.latency_ms + "ms)"
                  : "✕ " + (j.message || "فشل الاتصال");
              })
              .catch(function (err) { result.textContent = "✕ " + err.message; })
              .finally(function () { btn.disabled = false; });
          });
        });
        providersBody.querySelectorAll(".prov-models").forEach(function (btn) {
          btn.addEventListener("click", function () {
            btn.disabled = true;
            renderProviderModels(btn.getAttribute("data-provider"), providersBody);
            setTimeout(function () { btn.disabled = false; }, 800);
          });
        });
      });
  }

  if (providersOpenEl) {
    providersOpenEl.addEventListener("click", function () {
      if (providersBackdrop) providersBackdrop.hidden = false;
      loadProviders();
    });
  }
  var providersCloseEl = $("providers-close");
  if (providersCloseEl) {
    providersCloseEl.addEventListener("click", function () {
      providersBackdrop.hidden = true;
    });
  }
  if (providersBackdrop) {
    providersBackdrop.addEventListener("click", function (e) {
      if (e.target === providersBackdrop) providersBackdrop.hidden = true;
    });
  }

  // ---- مهمة البناء textstats: بث SSE + بطاقتا موافقة -----------------

  var buildRunEl = $("build-run");
  var buildBusy = false;

  function buildApprovalCard(ev) {
    var kind = ev.details && ev.details.gate_kind;
    var payload = (ev.details && ev.details.payload) || {};
    var card = document.createElement("div");
    card.className = "approval-card";
    var title = document.createElement("div");
    title.className = "approval-title";
    title.textContent = "⚖ بطاقة موافقة — " + (kind === "push" ? "الدفع إلى mission/textstats" : "منحة المسار textstats/**");
    card.appendChild(title);
    var info = document.createElement("div");
    info.className = "approval-items";
    info.textContent = kind === "push"
      ? "commit: " + String(payload.commit_sha || "").slice(0, 12) + " | ملفات: " + (payload.files || []).join(", ")
      : "المسارات: " + (payload.paths || []).join(", ");
    card.appendChild(info);
    var row = document.createElement("div");
    row.className = "approval-actions";
    var okBtn = document.createElement("button");
    okBtn.className = "btn-approve";
    okBtn.textContent = "أوافق";
    var noBtn = document.createElement("button");
    noBtn.className = "btn-deny";
    noBtn.textContent = "أرفض";
    row.appendChild(noBtn);
    row.appendChild(okBtn);
    card.appendChild(row);
    function decide(approved) {
      okBtn.disabled = true;
      noBtn.disabled = true;
      fetch("/api/mission/textstats/approve", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ run_id: ev.cycle_id, kind: kind, approved: approved })
      })
        .then(function (r) { return r.json(); })
        .then(function () { title.textContent += approved ? " — ✔ وُافقت" : " — ✕ رُفضت"; })
        .catch(function () { title.textContent += " — تعذرت الإجابة"; });
    }
    okBtn.addEventListener("click", function () { decide(true); });
    noBtn.addEventListener("click", function () { decide(false); });
    return card;
  }

  function streamBuildMission() {
    var parts = [];
    var decoder = new TextDecoder();
    fetch("/api/mission/textstats/stream", { method: "POST" })
      .then(function (resp) {
        if (!resp.ok) throw new Error("HTTP " + resp.status);
        var reader = resp.body.getReader();
        function pump() {
          return reader.read().then(function (chunk) {
            if (chunk.done) return;
            parts.push(decoder.decode(chunk.value, { stream: true }));
            var buf = parts.join("");
            var events = buf.split("\n\n");
            parts = [events.pop()];
            events.forEach(function (block) {
              if (!block.startsWith("data: ")) return;
              var ev;
              try { ev = JSON.parse(block.slice(6)); } catch (e) { return; }
              if (ev.kind === "approval.card") {
                var msg = makeRoleMessage(ev);
                messagesEl.appendChild(msg.root);
                msg.root.appendChild(buildApprovalCard(ev));
                scrollDown();
                return;
              }
              var view = makeRoleMessage(ev);
              messagesEl.appendChild(view.root);
              scrollDown();
            });
            return pump();
          });
        }
        return pump();
      })
      .catch(function (err) {
        var fallback = makeRoleMessage({
          role: "mission", kind: "mission_error", state: null,
          text: "تعذر بدء مهمة البناء: " + err.message, details: {}
        });
        messagesEl.appendChild(fallback.root);
      })
      .finally(function () {
        buildBusy = false;
        if (buildRunEl) buildRunEl.disabled = false;
        scrollDown();
      });
  }

  if (buildRunEl) {
    buildRunEl.addEventListener("click", function () {
      if (buildBusy) return;
      buildBusy = true;
      buildRunEl.disabled = true;
      hideWelcome();
      markConversation("🏗️ مهمة البناء textstats");
      addUserMessage("ابنِ حزمة textstats: CLI عدّ أسطر/كلمات/أحرف + suite pytest + README، ثم ادفعها إلى mission/textstats");
      streamBuildMission();
    });
  }

})();
