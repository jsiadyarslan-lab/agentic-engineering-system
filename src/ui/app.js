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
    STAGNANT: "▲ STAGNANT"
  };

  var busy = false;
  var conversationStarted = false;

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
    chip.className = "state-chip";
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

})();
