/* Agentic Engineering System — النواة: محادثة/مهمة + الشريط الجانبي.
 * سقف دائم: <2000 سطر لكل ملف واجهة (tests/contracts/test_thinness.py).
 * الأمر 008: المحادثة والمهمة تجربة واحدة حية — مؤشرات صادقة من
 * أحداث فعلية، تمرير ذكي (لا إجبار أثناء القراءة §5)، استرداد بعد
 * refresh (§34)، وأي حدث خام يظل متاحًا من «التفاصيل» لا كعرض أساسي.
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
  var chatTitleEl = $("chat-title");
  var modeBadgeEl = $("mode-badge");
  var modeChipEl = $("mode-chip");
  var plusEl = $("plus");
  var plusMenuEl = $("plus-menu");
  var stopRunEl = $("stop-run");
  var taskSettingsEl = $("task-settings");
  var taskSettingsBodyEl = $("task-settings-body");
  var followBtn = $("follow-btn");

  // ---------- الحالة ----------
  var state = {
    mode: "chat",                 // "chat" | "task" | "project"
    conversationId: null,         // المحادثة المفتوحة
    projectScopeId: null,         // (013.5 §E) المشروع المفتوح — نطاق العرض
    busy: false,
    activeRun: null,              // { kind: "task"|"mission"|"chat", cycleId }
    modelsConfig: null,           // آخر إعدادات نماذج (يملؤها settings.js)
    lastSeq: 0,                   // آخر seq وصل — لإعادة الاتصال (§19)
    historyLoaded: false,         // (013.5 §G) حُمّل التاريخ الدائم فعلًا
    scopeDiscarded: 0,            // (013.5 §E) أحداث أُسقطت خارج النطاق
  };

  var handlers = {};              // معالجات تسجلها الوحدات الشقيقة

  // ---------- تمرير ذكي (§5): أسفل = متابعة تلقائية، صعود = توقف ----------
  var sticky = true;

  function nearBottom() {
    return scrollEl.scrollHeight - scrollEl.scrollTop - scrollEl.clientHeight < 48;
  }

  function updateSticky() {
    var wasSticky = sticky;
    sticky = nearBottom();
    if (wasSticky && !sticky && followBtn) followBtn.hidden = false;
    if (sticky && followBtn) followBtn.hidden = true;
  }
  scrollEl.addEventListener("scroll", updateSticky, { passive: true });

  function scrollDown() {
    scrollEl.scrollTop = scrollEl.scrollHeight;
    sticky = true;
    if (followBtn) followBtn.hidden = true;
  }

  if (followBtn) {
    followBtn.addEventListener("click", function () {
      scrollDown();
      inputEl.focus();
    });
  }

  function onLiveContent() {
    // تحديث حي: تمرير فقط إن كان المالك في الأساس — لا إجبار (§5)
    if (sticky) scrollEl.scrollTop = scrollEl.scrollHeight;
  }

  // ---------- أدوات عامة ----------
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function fmtTime(ms) {
    if (ms === null || ms === undefined) return "";
    if (ms < 1000) return ms + " مث";
    return (ms / 1000).toFixed(1) + " ث";
  }

  function fetchJSON(url, options) {
    return fetch(url, options).then(function (resp) {
      return resp.json().then(function (j) { return { ok: resp.ok, j: j }; });
    });
  }

  function hideWelcome() {
    if (welcomeEl) welcomeEl.style.display = "none";
  }

  function setBusy(busyFlag) {
    state.busy = busyFlag;
    sendEl.disabled = busyFlag || !inputEl.value.trim();
    inputEl.disabled = false;
    if (!busyFlag) inputEl.focus();
    updateSendState();
  }

  // ---------- بث SSE عام + مضخة قابلة لإعادة الاستخدام (§19) ----------
  function parseSSEChunk(bufferObj, chunkText, onEvent) {
    bufferObj.buf += chunkText;
    var parts = bufferObj.buf.split("\n\n");
    bufferObj.buf = parts.pop();
    parts.forEach(function (part) {
      var line = part.split("\n")
        .find(function (l) { return l.indexOf("data:") === 0; });
      if (!line) return;
      var event;
      try { event = JSON.parse(line.slice(5).trim()); }
      catch (e) { return; }
      if (event.seq) state.lastSeq = Math.max(state.lastSeq, event.seq);
      onEvent(event);
    });
  }

  function pumpSSE(resp) {
    var reader = resp.body.getReader();
    var decoder = new TextDecoder("utf-8");
    var bufferObj = { buf: "" };
    function pump() {
      return reader.read().then(function (chunk) {
        if (chunk.done) return;
        parseSSEChunk(bufferObj, decoder.decode(chunk.value, { stream: true }), renderEvent);
        return pump();
      });
    }
    return pump();
  }

  function postStream(url, body) {
    return fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    }).then(function (resp) {
      if (!resp.ok) throw new Error("HTTP " + resp.status);
      return pumpSSE(resp);
    });
  }

  /** بث GET قابل لإعادة الاتصال — after يكمل من آخر حدث (§19). */
  function getStream(url) {
    return fetch(url).then(function (resp) {
      if (!resp.ok) throw new Error("HTTP " + resp.status);
      return pumpSSE(resp);
    });
  }

  // ---------- (013.5 §E) عزل النطاق: لا حدث بلا هوية تُطابقه ----------
  /* الجذر الموثّق للتلوث: الأحداث كانت تُبتلع بلا نطاق، فأي إعادة
   * بث (after=0) تُعيد رسم محتوى تاريخي داخل المحادثة المفتوحة —
   * رؤية المالك: سؤال «ما هي أحدث نماذج كلاود؟» فظهر
   * «Confirmation of Completion / A15 registration / HASH-MANIFEST».
   * المنع هنا: حدث لا يطابق نطاق العرض النشط يُسقط **قبل** أي عرض،
   * لا فلترة بصرية بعده. */

  /** نطاق الحدث الموحّد — من scope الصريح أو من الحقول القديمة. */
  function eventScope(event) {
    if (event && event.scope && typeof event.scope === "object") {
      return event.scope;
    }
    var d = (event && event.details) || {};
    return {
      stream: event.cycle_id || event.stream || "",
      conversation_id: d.conversation_id != null ? d.conversation_id
        : (event.conversation_id != null ? event.conversation_id : null),
      message_id: event.message_id || d.message_id || null,
      project_id: event.project_id != null ? event.project_id
        : (d.project_id != null ? d.project_id : null),
      run_id: d.run_id != null ? d.run_id : null,
      job_id: d.job_id != null ? d.job_id : null,
    };
  }

  /** هل ينتمي الحدث إلى العرض النشط الآن؟ */
  function eventInActiveScope(event) {
    var scope = eventScope(event);
    var stream = String(scope.stream || "");
    var isChatStream = stream.indexOf("chat-") === 0;
    var isTaskStream = stream.indexOf("task-") === 0 ||
      stream.indexOf("cycle-") === 0;

    if (state.mode === "project") {
      // عرض المشروع: أحداث المحادثة والمهام لا تدخله أبدًا.
      if (isChatStream || isTaskStream) return false;
      var pid = scope.project_id;
      if (pid != null && state.projectScopeId != null &&
          Number(pid) !== Number(state.projectScopeId)) {
        return false;
      }
      return true;
    }

    // عرض المحادثة: أي حدث مشروع/تشغيل/وظيفة يُسقط — الحقيقة هنا
    // رسائل فقط (§H: إسقاطان منفصلان لا تيار عام واحد).
    if (!isChatStream) {
      if (scope.project_id != null || scope.run_id != null ||
          scope.job_id != null) return false;
      if (isTaskStream) return false;
      // حدث بلا تيار معروف: يقبل فقط إن طابق المحادثة صراحةً.
      if (scope.conversation_id == null) return false;
    }
    if (scope.conversation_id != null && state.conversationId != null &&
        Number(scope.conversation_id) !== Number(state.conversationId)) {
      return false;
    }
    if (isChatStream && state.conversationId != null &&
        stream !== "chat-" + state.conversationId) {
      return false;
    }
    return true;
  }

  // ---------- توجيه الأحداث: النواة أو الوحدات المتخصصة ----------
  function renderEvent(event) {
    if (event.kind === "stream.done") return;   // علامة تحكم لا رسالة
    // (013.4) علامة خاتمة الخيط الداخلية — تصل الآن مع البث (ضمان
    // ترتيب الاكتمال قبل إغلاق التيار) ولا تُعرض كرسالة
    if (event.kind === "task.thread_done") return;
    // (013.5 §E) بوابة العزل — قبل أي معالج أو عرض
    if (!eventInActiveScope(event)) {
      state.scopeDiscarded = (state.scopeDiscarded || 0) + 1;
      return;
    }
    if (state.activeRun && !state.activeRun.cycleId && event.cycle_id &&
        event.cycle_id.indexOf("chat-") !== 0) {
      state.activeRun.cycleId = event.cycle_id;
      if (stopRunEl) stopRunEl.disabled = false;
    }
    var special = handlers[event.kind] || handlers["role:" + event.role];
    if (special) {
      special(event);
      return;
    }
    defaultEvent(event);
  }

  function defaultEvent(event) {
    // أحداث عامة بلا معالج متخصص — بطاقة رفيعة بتفاصيل قابلة للفتح
    var card = makeSystemCard(event);
    insertAtEnd(card);
  }

  // ---------- بطاقة نظامية (أخطاء/إشعارات) بتفاصيل قابلة للطي (§21-§22) ----------
  function makeSystemCard(event) {
    var wrap = document.createElement("div");
    var isError = event.kind === "chat.error" || event.kind === "cycle_error" ||
      event.kind === "CONFIGURATION_REQUIRED" || (event.status || "").indexOf("FAIL") === 0;
    wrap.className = "sys-card" + (isError ? " error" : "");
    var head = document.createElement("div");
    head.className = "sys-head";
    var title = document.createElement("span");
    title.textContent = event.text || event.kind;
    head.appendChild(title);
    if (event.duration_ms) {
      var time = document.createElement("span");
      time.className = "sys-time";
      time.textContent = fmtTime(event.duration_ms);
      head.appendChild(time);
    }
    var link = document.createElement("span");
    link.className = "details-link";
    link.textContent = "التفاصيل";
    link.addEventListener("click", function () { openModal(event); });
    head.appendChild(link);
    wrap.appendChild(head);
    return wrap;
  }

  /** بطاقة خطأ مفهومة (§22): السبب/الحالة/الإجراء + تفاصيل تقنية طيّة. */
  function showErrorCard(event) {
    var wrap = document.createElement("div");
    wrap.className = "sys-card error human-error";
    var box = document.createElement("div");
    box.className = "he-body";
    box.appendChild(el("div", "he-title", "⚠ تعذر إكمال الطلب"));
    var d = event.details || {};
    var reason = event.text || "";
    /* (014-المرحلة 2) ثنائية تسمية/قيمة: التسمية عربية ثانوية، والقيمة
       التقنية (استثناءات/رموز) mono LTR معزولة — لا تنساب كنثر */
    var rowReason = el("div", "he-row");
    rowReason.appendChild(el("span", "he-label", "السبب:"));
    rowReason.appendChild(el("span", "he-val", reason));
    box.appendChild(rowReason);
    if (event.code || d.code) {
      var rowCode = el("div", "he-row");
      rowCode.appendChild(el("span", "he-label", "الحالة:"));
      rowCode.appendChild(el("span", "he-val", String(event.code || d.code)));
      box.appendChild(rowCode);
    }
    box.appendChild(el("div", "he-row",
      "الإجراء: لن يُعتبر الطلب ناجحًا — أعد المحاولة أو راجع الإعدادات."));
    wrap.appendChild(box);
    var details = document.createElement("details");
    details.className = "he-tech";
    details.innerHTML = "<summary>التفاصيل التقنية</summary>";
    var pre = document.createElement("pre");
    pre.dir = "ltr";
    pre.textContent = JSON.stringify(event, null, 2);
    details.appendChild(pre);
    wrap.appendChild(details);
    insertAtEnd(wrap);
    scrollDown();
  }

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  // ---------- مؤشر العمل ----------
  function addWorking(label) {
    removeWorking();
    var indicator = document.createElement("div");
    indicator.className = "working";
    indicator.id = "working-indicator";
    indicator.innerHTML =
      '<span class="typing"><i></i><i></i><i></i></span>' +
      '<span class="working-label">' + esc(label || "جارٍ العمل…") + "</span>";
    messagesEl.appendChild(indicator);
    scrollDown();
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
    onLiveContent();
  }

  function insertAtEnd(node) {
    messagesEl.appendChild(node);
    onLiveContent();
  }

  /* (014-المرحلة 2) نسخ كتل الكود: تفويض واحد ينجو من إعادة بناء innerHTML
     أثناء البث — زر .md-copy داخل رأس الكتلة ينسخ جسمها */
  messagesEl.addEventListener("click", function (ev) {
    var btn = ev.target.closest ? ev.target.closest(".md-copy") : null;
    if (!btn) return;
    var fig = btn.closest(".md-codeblock");
    var codeEl = fig && fig.querySelector("pre code");
    if (!codeEl) return;
    var text = codeEl.textContent;
    var done = function () {
      btn.classList.add("copied");
      btn.setAttribute("data-done", "تم النسخ");
      setTimeout(function () {
        btn.classList.remove("copied");
        btn.removeAttribute("data-done");
      }, 1600);
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(done, done);
    } else {
      done();
    }
  });

  // ---------- الرسائل ----------
  /* (014-المرحلة 2) ساعة رسالة: HH:MM بأرقام لاتينية داخل عزل LTR أحادي */
  function fmtClock(iso) {
    var d = iso ? new Date(iso) : new Date();
    if (isNaN(d.getTime())) return "";
    var hh = String(d.getHours()).padStart(2, "0");
    var mm = String(d.getMinutes()).padStart(2, "0");
    return hh + ":" + mm;
  }

  /* (014-المرحلة 2) ترويسة مجموعة رسائل: مرسل 12px/600 + زمن 11px mono —
     ترويسة ثنائية الطبقة تحل «عناصر اليتامى» (رسائل ؟ بلا سياق) وتفصل
     طباعيًا بين المتحدثين كما في Devin. */
  function msgHead(who, iso) {
    var head = document.createElement("div");
    head.className = "msg-head";
    var w = document.createElement("span");
    w.className = "msg-who";
    w.textContent = who;
    head.appendChild(w);
    var clock = fmtClock(iso);
    if (clock) {
      var t = document.createElement("span");
      t.className = "msg-when";
      t.textContent = clock;
      head.appendChild(t);
    }
    return head;
  }

  function addUserMessage(text, when) {
    var wrap = document.createElement("div");
    wrap.className = "bubble user";
    wrap.appendChild(msgHead("أنت", when || null));
    var body = document.createElement("div");
    body.className = "bubble-body";
    body.dir = "auto";   // (010 §4) الاتجاه من المحتوى: عربي RTL / إنجليزي LTR
    body.textContent = text;
    wrap.appendChild(body);
    insertAtEnd(wrap);
    scrollDown();
  }

  function addAssistantBubble(when) {
    var wrap = document.createElement("div");
    wrap.className = "bubble assistant";
    wrap.appendChild(msgHead("المساعد", when || null));
    var body = document.createElement("div");
    body.className = "bubble-body md-body";
    body.dir = "auto";   // (010 §4) الجملة العربية تبدأ يمينًا — والكود/الجداول LTR داخل العارض
    body.textContent = "";
    var foot = document.createElement("div");
    foot.className = "bubble-foot";
    wrap.appendChild(body);
    wrap.appendChild(foot);
    insertAtEnd(wrap);
    scrollDown();
    return { root: wrap, body: body, foot: foot };
  }

  function addHistoryMessage(message) {
    if (message.role === "user") {
      addUserMessage(message.content, message.created_at);
      return;
    }
    if (message.role === "assistant") {
      var bubble = addAssistantBubble(message.created_at);
      if (window.MD) {
        bubble.body.innerHTML = window.MD.render(message.content);
      } else {
        bubble.body.textContent = message.content;
      }
      /* (014-المرحلة 2) الحكم شارة صادقة: قيمة أحادية 11px — غامقة حمراء
         بأيقونة عند الفشل بدل نص رمادي ضائع */
      if (message.state_badge) {
        var badge = String(message.state_badge);
        var v = el("span", "verdict" + (/FAIL|ERROR|BLOCKED/i.test(badge) ? " fail" : ""), badge);
        bubble.foot.appendChild(document.createTextNode("الحكم: "));
        bubble.foot.appendChild(v);
      }
      return;
    }
    // أدوار أخرى (thinker/…) — لا تُعرض في التاريخ المختصر
  }

  // ---------- نافذة التفاصيل ----------
  var modalBackdrop = $("modal-backdrop");
  var modalJson = $("modal-json");
  var modalTitle = $("modal-title");
  var modalCopy = $("modal-copy");

  function openModal(event) {
    modalTitle.textContent = (event.role || "") + " — " + event.kind;
    modalJson.textContent = JSON.stringify(event, null, 2);
    modalBackdrop.hidden = false;
  }

  function closeModal() { modalBackdrop.hidden = true; }
  $("modal-close").addEventListener("click", closeModal);
  if (modalCopy) {
    modalCopy.addEventListener("click", function () {
      navigator.clipboard && navigator.clipboard.writeText(modalJson.textContent);
      modalCopy.textContent = "نُسخ ✓";
      setTimeout(function () { modalCopy.textContent = "نسخ JSON"; }, 1200);
    });
  }
  modalBackdrop.addEventListener("click", function (e) {
    if (e.target === modalBackdrop) closeModal();
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") {
      closeModal();
      plusMenuEl.hidden = true;
    }
  });

  // ---------- الشريط الجانبي: محادثات حقيقية ----------
  var _lastConversations = [];
  var _conversationsState = "idle";   // idle | loading | success | error

  function loadConversations() {
    if (_conversationsState !== "loading") renderConversationsLoading();
    _conversationsState = "loading";
    fetchJSON("/api/conversations").then(function (out) {
      if (!out.ok) {
        _conversationsState = "error";
        renderConversationsError(out.j && out.j.detail);
        return;
      }
      _conversationsState = "success";
      _lastConversations = out.j.conversations || [];
      renderConversations(_lastConversations);
    }, function () {
      _conversationsState = "error";
      renderConversationsError();
    });
  }

  function renderConversationsLoading() {
    var empty = $("conv-empty");
    if (empty) empty.textContent = "جارٍ تحميل المحادثات…";
  }

  function renderConversationsError(detail) {
    var empty = $("conv-empty");
    if (empty) {
      empty.innerHTML = "";
      empty.appendChild(el("div", "conv-err", "تعذر تحميل المحادثات"));
      if (detail) empty.appendChild(el("div", "conv-err-detail", String(detail).slice(0, 120)));
      var retry = el("button", "conv-retry", "إعادة المحاولة");
      retry.addEventListener("click", function () { loadConversations(); });
      empty.appendChild(retry);
      empty.style.display = "";
    }
  }

  function renderConversations(list) {
    var empty = $("conv-empty");
    if (empty) {
      if (list.length) empty.remove();
      else {
        empty.textContent = "لا محادثات بعد";
        empty.style.display = "";
      }
    }
    conversationsEl.querySelectorAll(".conv-item").forEach(function (n) { n.remove(); });
    if (!list.length) return;
    var today = new Date(); today.setHours(0, 0, 0, 0);
    list.forEach(function (c) {
      var item = document.createElement("button");
      item.className = "conv-item" +
        (c.conversation_id === state.conversationId ? " active" : "");
      var updated = new Date(c.updated_at);
      var when = updated >= today ? "اليوم" : "سابقًا";
      // (AES-UI-PREMIUM-REDESIGN-001) أيقونة SVG موحدة بدل الرموز التعبيرية
      var icon = c.mode === "task"
        ? '<span class="icon sm"><svg><use href="#i-task"/></svg></span>'
        : '<span class="icon sm"><svg><use href="#i-chat"/></svg></span>';
      item.innerHTML =
        icon +
        '<span class="conv-text">' + esc(c.title) + "</span>" +
        '<span class="conv-when">' + when + "</span>";
      item.title = c.title + " — " + when;
      item.addEventListener("click", function () { openConversation(c); });
      conversationsEl.appendChild(item);
    });
  }

  /** فتح محادثة من معرفها وحدها (010 §2) — للتوجيه الدائم والاسترداد. */
  function openConversationById(id) {
    fetchJSON("/api/conversations/" + id).then(function (out) {
      if (!out.ok) {
        showErrorCard({
          kind: "conversation.error", role: "system",
          text: "تعذر تحميل المحادثة #" + id +
            (out.j && out.j.detail ? " — " + out.j.detail : ""),
          details: out.j || {},
        });
        return;
      }
      openConversation(out.j);
    }, function () {
      showErrorCard({
        kind: "conversation.error", role: "system",
        text: "تعذر الوصول للخدمة لتحميل المحادثة #" + id,
        details: {},
      });
    });
  }

  function openConversation(c) {
    /* (013.1 §5+§6) فتح محادثة من داخل عرض المشروع يخرج من وضع
     * المشروع أولًا — قبل هذا الإصلاح كان المشروع يبقى مغطيًا
     * للشاشة والمحادثة تُحمّل خلفه: «Previous Chat لا يفتح» حرفيًا. */
    if (document.body.classList.contains("mode-project")
        && window.HubProjects) {
      window.HubProjects.exitProjectMode();
    }
    /* (013.7 §P11) تصفير حالة المحادثة السابقة: إيقاف البث الحي،
     * إعادة تعيين متغيرات الحالة، مسح مصادر الويب. */
    if (window.ChatLive) window.ChatLive.resetScope(c.conversation_id, "");
    state.activeRun = null;
    state.busy = false;
    state.scopeDiscarded = 0;
    setBusy(false);

    if (document.body.classList.contains("mode-project")
        && window.HubProjects) {
      window.HubProjects.exitProjectMode();
    }
    state.conversationId = c.conversation_id;
    state.projectScopeId = null;
    state.lastSeq = 0;
    state.historyLoaded = false;
    saveActiveConversation(c.conversation_id);
    setHashQuietly("#/chat/" + c.conversation_id);
    setMode(c.mode === "task" ? "task" : "chat", { silent: true });
    chatTitleEl.textContent = c.title;
    modeBadgeEl.hidden = false;
    modeBadgeEl.textContent = c.mode === "task" ? "مهمة" : "محادثة";
    messagesEl.textContent = "";
    hideWelcome();
    var loadingCard = el("div", "history-loading", "جارٍ تحميل الرسائل…");
    messagesEl.appendChild(loadingCard);
    /* (013.5 §G) ترتيب الاسترداد الملزم:
     *   1. لقطة المحادثة (فوق)
     *   2. الرسائل الدائمة  ← لا تُستبدل أبدًا بإسقاط ناقص
     *   3. الاشتراك بالبث الحي **بعد** اكتمال التاريخ
     *   4. مصالحة بالتسلسل (after = last_seq الحقيقي، لا صفر)
     * قبل هذا الإصلاح كان الاشتراك يبدأ قبل وصول الرسائل، فيُبنى
     * فقاعة حية ثم تُضاف الرسائل التاريخية بعدها (ترتيب مقلوب)،
     * أو تُرسم إعادة بث قديمة كأنها ردٌّ جديد. */
    return fetchJSON("/api/conversations/" + c.conversation_id + "/messages")
      .then(function (out) {
        loadingCard.remove();
        if (!out.ok) {
          showErrorCard({
            kind: "conversation.error", role: "system",
            text: "تعذر تحميل رسائل المحادثة" +
              (out.j && out.j.detail ? " — " + out.j.detail : ""),
            details: out.j || {},
          });
          return;
        }
        (out.j.messages || []).forEach(addHistoryMessage);
        state.historyLoaded = true;
        // (007 BUG-04) محادثة موجودة بلا رسائل مرئية كانت تعرض لوحة
        // فارغة صامتة — حالة فراغ صادقة بدل السواد الأبيض.
        if (!out.j.messages || !out.j.messages.length) {
          var emptyNote = el("div", "history-loading",
            "لا رسائل مرئية في هذه المحادثة بعد — أرسل رسالة للبدء.");
          emptyNote.style.color = "var(--text-dim)";
          messagesEl.appendChild(emptyNote);
        }
        scrollDown();
        renderConversations(_lastConversations);
        // (013.5 §G) الآن فقط — الاشتراك الحي والمصالحة
        resumeActiveRun(c.conversation_id);
      }, function () {
        loadingCard.remove();
        showErrorCard({
          kind: "conversation.error", role: "system",
          text: "تعذر الوصول للخدمة لتحميل الرسائل", details: {},
        });
      });
  }

  /** استرداد بعد refresh (§34): مهمة/توليد جارٍ يعاد تعليقه حيًا. */
  function resumeActiveRun(conversationId) {
    fetchJSON("/api/cycle/active").then(function (out) {
      if (!out.ok || !out.j.running) {
        if (window.ChatLive) window.ChatLive.resumeIfRunning(conversationId);
        return;
      }
      if (out.j.conversation_id !== conversationId) {
        if (window.ChatLive) window.ChatLive.resumeIfRunning(conversationId);
        return;
      }
      // المهمة الجارية لهذه المحادثة — أعد بناء التجربة من الأرشيف (§19)
      setBusy(true);
      state.activeRun = { kind: "task", cycleId: out.j.cycle_id };
      stopRunEl.hidden = false;
      stopRunEl.disabled = false;
      if (window.TaskCards) window.TaskCards.beginTask();
      getStream("/api/cycle/events/" + out.j.cycle_id + "?after=0")
        .then(onTaskFinished, function () { onTaskFinished(); });
    });
  }

  function newChat() {
    /* (013.7 §P11) تصفير حالة المحادثة السابقة. */
    if (window.ChatLive) window.ChatLive.resetScope("", "");
    state.activeRun = null;
    state.busy = false;
    state.scopeDiscarded = 0;
    setBusy(false);

    state.conversationId = null;
    state.lastSeq = 0;
    saveActiveConversation(null);
    setHashQuietly("");
    chatTitleEl.textContent = "محادثة جديدة";
    modeBadgeEl.hidden = true;
    messagesEl.textContent = "";
    if (welcomeEl) welcomeEl.style.display = "";
    setMode("chat");
    inputEl.focus();
    renderConversations(_lastConversations);
  }

  $("new-chat").addEventListener("click", newChat);

  // (AES-DESIGN-IMPL-012) اختصار Ctrl+K كما في التصميم
  document.addEventListener("keydown", function (e) {
    if ((e.ctrlKey || e.metaKey) && String(e.key).toLowerCase() === "k") {
      e.preventDefault();
      newChat();
    }
  });

  // (AES-DESIGN-IMPL-012) بحث الشريط الجانبي: تصفية المحادثات والمشاريع
  var sideSearch = document.getElementById("side-search");
  if (sideSearch) {
    sideSearch.addEventListener("input", function () {
      var q = this.value.trim().toLowerCase();
      var items = document.querySelectorAll("#conversations .conv-item, #projects-list .pj-item");
      items.forEach(function (el) {
        el.hidden = !!q && el.textContent.toLowerCase().indexOf(q) === -1;
      });
    });
  }

  // ---------- طي الشريط الجانبي ----------
  function toggleSidebar() {
    document.body.classList.toggle("sidebar-collapsed");
  }
  $("sidebar-toggle").addEventListener("click", toggleSidebar);
  var collapseBtn = $("sidebar-collapse");
  if (collapseBtn) collapseBtn.addEventListener("click", toggleSidebar);
  // (AES-EXP-03) على الشاشات الضيقة: الشريط يبدأ مطويًا — كان يفتح
  // افتراضيًا فيغطي الدردشة على الهاتف (390px) ويقصّها إلى شريط ضيق.
  // نفس دلالة الصنف القائمة (collapsed = مخفي) والزر ☰ يفتحه overlay.
  var sidebarMq = window.matchMedia("(max-width: 900px)");
  if (sidebarMq.matches) {
    document.body.classList.add("sidebar-collapsed");
  }
  // (007 BUG-03) كان الطي يُقرر مرة عند التحميل فقط — تغيير حجم النافذة
  // بعد التحميل (جوال↔سطح مكتب، أو تدوير جهاز) كان يُبقي الحالة القديمة:
  // شريط مطوي فوق سطح 1440، أو شريط مفتوح يغطي 390. الآن يتزامن مع
  // عبور نقطة الانكسار 900px، مع احترام اختيار المستخدم اليدوي المؤقت
  // (لا نفتح عليه شريطًا فتحه بنفسه ثم ضيّق النافذة هربًا منه).
  var sidebarUserOverride = false;
  ["sidebar-toggle", "sidebar-collapse"].forEach(function (id) {
    var btn = $(id);
    if (btn) btn.addEventListener("click", function () { sidebarUserOverride = true; });
  });
  if (sidebarMq.addEventListener) {
    sidebarMq.addEventListener("change", function (e) {
      if (sidebarUserOverride) return;
      document.body.classList.toggle("sidebar-collapsed", e.matches);
    });
  }

  // ---------- النمط: محادثة / مهمة ----------
  function setMode(mode, opts) {
    state.mode = mode;
    var isTask = mode === "task";
    var isProject = mode === "project";
    modeChipEl.textContent = isTask ? "مهمة"
      : isProject ? "مشروع" : "محادثة";
    modeChipEl.classList.toggle("task", isTask);
    modeChipEl.classList.toggle("project", isProject);
    inputEl.placeholder = isTask
      ? "صف هدف المهمة… (Enter للإرسال · Shift+Enter لسطر جديد)"
      : isProject
      ? "صف هدف المشروع — سيُحوَّل إلى خطة تعتمدها ثم يُنفَّذ ذاتيًا…"
      : "اكتب رسالتك… (Enter للإرسال · Shift+Enter لسطر جديد)";
    taskSettingsEl.hidden = !isTask;
    updateComposerHint();
    if (!opts || !opts.silent) {
      if (isTask) renderTaskSettingsSummary();
    }
    if (isTask) renderTaskSettingsSummary();
  }

  /* (013 §33) ماذا سيحدث عند الإرسال؟ — وضوح القصد قبل الضغط */
  function updateComposerHint() {
    var hint = document.getElementById("composer-hint");
    if (!hint) return;
    var text = "";
    if (state.mode === "project") {
      text = "سيتم تحليل الهدف وإعداد خطة تنفيذ للمراجعة — لا تنفيذ قبل اعتمادك.";
    } else if (state.mode === "task") {
      text = "ستعمل دورة الأدوار الخمسة على الهدف بأدلة قابلة للفحص.";
    }
    hint.textContent = text;
    hint.hidden = !text;
  }

  function renderTaskSettingsSummary() {
    if (!taskSettingsBodyEl) return;
    var cfg = state.modelsConfig;
    if (!cfg || !cfg.roles) {
      taskSettingsBodyEl.innerHTML =
        '<div class="ts-row">حمّل الإعدادات أولًا من ⚙</div>';
      return;
    }
    var rows = cfg.roles
      .filter(function (r) { return r.key !== "chat"; })
      .map(function (r) {
        return '<div class="ts-row"><span>' + esc(r.label) + "</span>" +
          '<span class="ts-model" dir="ltr">' + esc(r.selection.provider) +
          " / " + esc(r.selection.model) + "</span></div>";
      }).join("");
    taskSettingsBodyEl.innerHTML = rows +
      '<div class="ts-hint">غيّر النماذج من ⚙ الإعدادات — لكل دور اختياره المستقل.</div>';
  }

  // زر ＋ وقائمته
  plusEl.addEventListener("click", function (e) {
    e.stopPropagation();
    plusMenuEl.hidden = !plusMenuEl.hidden;
  });
  document.addEventListener("click", function () { plusMenuEl.hidden = true; });
  plusMenuEl.querySelectorAll(".plus-option").forEach(function (btn) {
    btn.addEventListener("click", function () {
      setMode(btn.getAttribute("data-mode"));
      inputEl.focus();
    });
  });

  document.querySelectorAll(".suggestion").forEach(function (btn) {
    btn.addEventListener("click", function () {
      setMode(btn.getAttribute("data-mode"));
      inputEl.focus();
    });
  });

  var taskSettingsToggleEl = $("task-settings-toggle");
  if (taskSettingsToggleEl) {
    taskSettingsToggleEl.addEventListener("click", function () {
      taskSettingsBodyEl.hidden = !taskSettingsBodyEl.hidden;
      taskSettingsToggleEl.querySelector(".caret").textContent =
        taskSettingsBodyEl.hidden ? "▾" : "▴";
    });
  }

  // ---------- الإدخال ----------
  function autoGrow() {
    inputEl.style.height = "auto";
    inputEl.style.height = Math.min(inputEl.scrollHeight, 180) + "px";
  }

  function updateSendState() {
    sendEl.disabled = state.busy || !inputEl.value.trim();
  }

  inputEl.addEventListener("input", function () {
    autoGrow();
    updateSendState();
  });
  inputEl.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  });
  sendEl.addEventListener("click", send);

  // ---------- توجيه دائم (010 §2): #/chat/{id} و #/project/{id} ----------
  var _applyingRoute = false;

  function saveActiveConversation(id) {
    try {
      if (id === null) localStorage.removeItem("hub:active-conversation");
      else localStorage.setItem("hub:active-conversation", String(id));
    } catch (e) { /* تخزين غير متاح — التوجيه يكفي */ }
  }

  function savedActiveConversation() {
    try { return localStorage.getItem("hub:active-conversation"); }
    catch (e) { return null; }
  }

  function setHashQuietly(hash) {
    if (location.hash === hash) return;
    _applyingRoute = true;
    try { location.hash = hash; } catch (e) { /* ignore */ }
    // الحدث يصل غير متزامن — العلم يمنع أي دوران متزامن فقط،
    // وapplyRoute نفسه تراجعي (idempotent) فلا دوران غير متزامن.
    setTimeout(function () { _applyingRoute = false; }, 0);
  }

  /** تطبيق المسار الحالي: محادثة أو مشروع أو بداية جديدة. */
  var _routeTries = 0;

  function applyRoute() {
    if (_applyingRoute) return;
    var hash = location.hash || "";
    var chatMatch = hash.match(/^#\/chat\/(\d+)$/);
    var projectMatch = hash.match(/^#\/project\/(\d+)$/);
    if (chatMatch) {
      var id = parseInt(chatMatch[1], 10);
      if (state.conversationId !== id) openConversationById(id);
      return;
    }
    if (projectMatch) {
      var projectId = parseInt(projectMatch[1], 10);
      if (window.HubProjects) {
        _routeTries = 0;
        window.HubProjects.openProject(projectId);
      } else if (_routeTries < 40) {
        // (010 §14) projects.js يُحمّل بعد app.js — أعد المحاولة حتى
        // يجهز (التحديث المباشر على #/project/{id} يعمل من أول مرة).
        _routeTries += 1;
        setTimeout(applyRoute, 150);
      }
      return;
    }
    // لا مسار: محادثة محفوظة سابقًا (استرداد بعد refresh §1) أو بداية
    if (document.body.classList.contains("mode-project")) {
      if (window.HubProjects) window.HubProjects.exitProjectMode();
      return;
    }
    var saved = savedActiveConversation();
    if (saved && !state.conversationId
        && chatTitleEl.textContent === "محادثة جديدة") {
      openConversationById(parseInt(saved, 10));
    }
  }

  window.addEventListener("hashchange", applyRoute);

  // ---------- هوية المحادثة (010 §1): الربط حدث أول لا حالة ضمنية ----------
  handlers["conversation.bind"] = function (event) {
    var d = event.details || {};
    // (013.5 §E) هوية الرسالة الجارية تصبح مرجع النطاق حصرًا — أي
    // حدث لرسالة أخرى في هذه المحادثة يُسقط ولا يُرسم.
    if (window.ChatLive && window.ChatLive.resetScope) {
      window.ChatLive.resetScope(event.message_id || "");
    }
    if (d.conversation_id) {
      var changed = state.conversationId !== d.conversation_id;
      state.conversationId = d.conversation_id;
      saveActiveConversation(d.conversation_id);
      setHashQuietly("#/chat/" + d.conversation_id);
      if (changed) {
        loadConversations();   // عنصر واحد في القائمة — لا عنصر لكل رسالة
        if (d.mode === "chat" && chatTitleEl.textContent === "محادثة جديدة") {
          // العنوان يأتي من أول رسالة — القائمة ستجلب
        }
      }
    }
  };

  handlers["task.conversation"] = function (event) {
    var d = event.details || {};
    if (d.conversation_id) {
      state.conversationId = d.conversation_id;
      saveActiveConversation(d.conversation_id);
      setHashQuietly("#/chat/" + d.conversation_id);
      loadConversations();
    }
    chatTitleEl.textContent =
      chatTitleEl.textContent === "محادثة جديدة"
        ? "مهمة جديدة" : chatTitleEl.textContent;
    modeBadgeEl.hidden = false;
    modeBadgeEl.textContent = "مهمة";
  };

  // ---------- الإرسال: توزيع حسب النمط ----------
  function send() {
    var text = inputEl.value.trim();
    if (!text || state.busy) return;
    inputEl.value = "";
    autoGrow();
    updateSendState();
    hideWelcome();
    state.lastSeq = 0;
    if (state.mode === "project") {
      // (013 §8+§33) الهدف مشروع: يُنشأ ويُفتح حيًّا — الخطة والاعتماد
      // والتنفيذ بطاقات تتدفق هناك؛ رسالة الهدف نفسها تظهر في المشهد
      addUserMessage(text);
      if (window.HubProjects) {
        window.HubProjects.createProjectFromObjective(text);
      }
      setMode("chat", { silent: true });
      return;
    }
    addUserMessage(text);
    if (state.mode === "task") {
      startTask(text);
    } else {
      startChat(text);
    }
  }

  // ---------- المحادثة الحية (المنطق في chat-stream.js — هنا التنسيق) ----------
  var WEB_MODES = ["auto", "on", "off"];
  var WEB_TITLES = {
    auto: "البحث في الويب: تلقائي — يبحث عند الحاجة (013.4 §26)",
    on: "البحث في الويب: مفعّل دائمًا",
    off: "البحث في الويب: معطّل",
  };
  var webMode = "auto";
  var webToggle = $("web-toggle");
  if (webToggle) {
    webToggle.addEventListener("click", function () {
      webMode = WEB_MODES[(WEB_MODES.indexOf(webMode) + 1) %
        WEB_MODES.length];
      webToggle.className = "web-toggle " + webMode;
      webToggle.title = WEB_TITLES[webMode];
      webToggle.classList.toggle("active", webMode === "on");
      webToggle.classList.toggle("off", webMode === "off");
    });
  }

  function startChat(text) {
    state.activeRun = { kind: "chat", cycleId: "" };
    setBusy(true);
    stopRunEl.hidden = false;
    stopRunEl.disabled = false;
    postStream("/api/chat/stream", {
      message: text,
      conversation_id: state.conversationId,
      web: webMode,
    }).then(finish, failed);

    function failed(err) {
      showErrorCard({
        kind: "chat.error", role: "chat",
        text: "تعذر البث: " + err.message,
        details: { error: String(err.message) }
      });
      finish();
    }

    function finish() {
      state.activeRun = null;
      stopRunEl.hidden = true;
      setBusy(false);
      loadConversations();
    }
  }

  /** انتهت رسالة محادثة — تحرير الحالة (من chat-stream.js). */
  function onChatDone() {
    if (state.activeRun && state.activeRun.kind === "chat") {
      state.activeRun = null;
      stopRunEl.hidden = true;
      setBusy(false);
      loadConversations();
    }
  }

  // ---------- المهمة الحية ----------
  function startTask(goal) {
    state.activeRun = { kind: "task", cycleId: "" };
    setBusy(true);
    stopRunEl.hidden = false;
    stopRunEl.disabled = true;

    if (window.TaskCards) window.TaskCards.beginTask();

    postStream("/api/cycle/stream", {
      goal: goal,
      conversation_id: state.conversationId,
    }).then(onTaskFinished, failed);

    function failed(err) {
      removeWorking();
      showErrorCard({
        kind: "cycle_error", role: "coordinator",
        text: "تعذر البث: " + err.message,
        details: { error: String(err.message) }
      });
      onTaskFinished();
    }
  }

  function onTaskFinished() {
    removeWorking();
    if (state.activeRun && state.activeRun.kind !== "task") return;
    state.activeRun = null;
    setBusy(false);
    stopRunEl.hidden = true;
    loadConversations();
  }

  // ---------- الإيقاف الفوري (الأمر 004 + 013.7 §P12) ----------
  function requestStop() {
    if (!state.activeRun) return;
    stopRunEl.disabled = true;
    stopRunEl.textContent = "■ جارٍ طلب الإيقاف…";
    var kind = state.activeRun.kind;
    var url, body;
    if (kind === "chat") {
      // Chat mode: stop by conversation_id
      if (!state.conversationId) return;
      url = "/api/chat/stop";
      body = { conversation_id: state.conversationId };
    } else if (kind === "mission") {
      url = "/api/mission/stop";
      body = { reason: "زر الإيقاف من الواجهة" };
    } else {
      url = "/api/cycle/stop";
      body = { cycle_id: state.activeRun.cycleId, reason: "زر الإيقاف من الواجهة" };
    }
    fetchJSON(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    }).then(function (out) {
      var card = makeSystemCard({
        kind: "stop.receipt", role: "coordinator",
        state: "STOPPING",
        text: out.ok
          ? "■ طلب الإيقاف قُبل — يُكرَّم عند أقرب حدّ آمن وتُكتب اللقطة"
          : "تعذر طلب الإيقاف: " + ((out.j && out.j.detail) || ""),
        details: out.j || {}
      });
      card.classList.add("stop-card");
      insertAtEnd(card);
    });
  }

  stopRunEl.addEventListener("click", function () {
    if (state.busy) requestStop();
  });

  // ---------- حالة الركيزة من /health ----------
  fetchJSON("/health").then(function (out) {
    if (!out.ok || !out.j.substrate) return;
    var dot = $("substrate-dot");
    var label = $("substrate-label");
    if (out.j.substrate.available) {
      dot.classList.add("on");
      dot.title = "تنفيذ معزول (namespaces + seccomp)";
      label.textContent = "الركيزة: معزولة";
    } else {
      dot.classList.add("off");
      dot.title = "المنصة لا تدعم العزل — وضع متوافق معلن";
      label.textContent = "الركيزة: متوافقة (بلا عزل)";
    }
  });

  // ---------- التصدير للوحدات الشقيقة ----------
  window.Hub = {
    state: state,
    handlers: handlers,
    $: $,
    esc: esc,
    el: el,
    fmtTime: fmtTime,
    fetchJSON: fetchJSON,
    postStream: postStream,
    getStream: getStream,
    pumpSSE: pumpSSE,
    renderEvent: renderEvent,
    eventScope: eventScope,
    eventInActiveScope: eventInActiveScope,
    scrollDown: scrollDown,
    onLiveContent: onLiveContent,
    addUserMessage: addUserMessage,
    makeSystemCard: makeSystemCard,
    showErrorCard: showErrorCard,
    insertAtEnd: insertAtEnd,
    insertBeforeWorking: insertBeforeWorking,
    removeWorking: removeWorking,
    addWorking: addWorking,
    openModal: openModal,
    setMode: setMode,  /* (AES-DESIGN-IMPL-012) إصلاح TypeError: factory-control ينادي Hub.setMode عند العودة من المصنع */
    setBusy: setBusy,
    onChatDone: onChatDone,
    loadConversations: function () { loadConversations(); },
    onTaskFinished: onTaskFinished,
    stopButtonEnable: function (enabled) {
      stopRunEl.disabled = !enabled;
    },
    currentStopRunEl: function () { return stopRunEl; },
  };

  // ---------- الإقلاع ----------
  setMode("chat");
  loadConversations();
  applyRoute();               // التوجيه الدائم: استرداد المحادثة/المشروع
  inputEl.focus();
})();
