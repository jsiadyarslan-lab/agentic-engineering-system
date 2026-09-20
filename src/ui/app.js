/* agent hub v2 — واجهة الدورة الكاملة (الأمر الثاني).
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
    switch (event.kind) {
      case "goal":
        return; // رسالة المستخدم عُرضت محليًا عند الإرسال
      case "state_change":
        addStateChip(event);
        return;
      case "cycle_done":
        renderCycleDone(event);
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

  // ---------- بث الدورة: SSE لحظة الحدوث ----------
  function streamCycle(goal) {
    var working = addWorking();

    fetch("/api/cycle/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ goal: goal })
    })
      .then(function (resp) {
        if (!resp.ok) throw new Error("HTTP " + resp.status);
        var reader = resp.body.getReader();
        var decoder = new TextDecoder("utf-8");
        var buffer = "";

        function pump() {
          return reader.read().then(function (chunk) {
            if (chunk.done) return finish();
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
      })
      .catch(function (err) {
        removeWorking();
        var fallback = makeRoleMessage({
          role: "coordinator",
          kind: "cycle_error",
          state: null,
          text: "تعذّر البث: " + err.message,
          details: { error: String(err.message) }
        });
        messagesEl.appendChild(fallback.root);
        setBusy(false);
      });

    function finish() {
      removeWorking();
      setBusy(false);
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
})();
