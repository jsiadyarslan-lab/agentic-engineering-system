/* agent hub v2 — النواة: محادثة/مهمة + الشريط الجانبي + الـcomposer.
 * سقف دائم: <2000 سطر لكل ملف واجهة (tests/contracts/test_thinness.py).
 * الأمر 006: واجهة محادثة أولًا — زر ＋ يفصل «محادثة» (نموذج واحد)
 * عن «مهمة» (دورة الأدوار الخمسة الحية)، والإرسال يمين الصندوق بصريًا.
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

  // ---------- الحالة ----------
  var state = {
    mode: "chat",                 // "chat" | "task"
    conversationId: null,         // المحادثة المفتوحة
    busy: false,
    activeRun: null,              // { kind: "task"|"mission"|"chat", cycleId }
    modelsConfig: null,           // آخر إعدادات نماذج (يملؤها settings.js)
  };

  // معالجات الأحداث المتخصصة — يسجلها task-cards.js (فصل الوحدات)
  var handlers = {};

  // ---------- أدوات عامة ----------
  function scrollDown() {
    scrollEl.scrollTop = scrollEl.scrollHeight;
  }

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

  // ---------- بث SSE عام ----------
  function postStream(url, body) {
    return fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    }).then(function (resp) {
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

  // ---------- توجيه الأحداث: النواة أو الوحدات المتخصصة ----------
  function renderEvent(event) {
    if (state.activeRun && !state.activeRun.cycleId && event.cycle_id &&
        event.cycle_id.indexOf("chat-") !== 0) {
      state.activeRun.cycleId = event.cycle_id;
    }
    var special = handlers[event.kind] || handlers["role:" + event.role];
    if (special) {
      special(event);
      return;
    }
    defaultEvent(event);
  }

  function defaultEvent(event) {
    // أحداث عامة بلا معالج متخصص — بطاقة نظامية رفيعة بتفاصيل قابلة للفتح
    var card = makeSystemCard(event);
    insertBeforeWorking(card);
  }

  // ---------- بطاقة نظامية رفيعة (أحداث المحادثة والأخطاء) ----------
  function makeSystemCard(event) {
    var wrap = document.createElement("div");
    wrap.className = "sys-card" +
      (event.kind === "chat.error" || event.kind === "cycle_error" ||
       event.kind === "CONFIGURATION_REQUIRED" ? " error" : "");
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

  // ---------- مؤشر العمل ----------
  var workingEl = null;

  function addWorking(label) {
    removeWorking();
    workingEl = document.createElement("div");
    workingEl.className = "working";
    workingEl.id = "working-indicator";
    workingEl.innerHTML =
      '<span class="typing"><i></i><i></i><i></i></span>' +
      '<span class="working-label">' + esc(label || "جارٍ العمل…") + "</span>";
    messagesEl.appendChild(workingEl);
    scrollDown();
  }

  function removeWorking() {
    var indicator = $("working-indicator");
    if (indicator) indicator.remove();
    workingEl = null;
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

  // ---------- الرسائل: فقاعات حديثة ----------
  function addUserMessage(text) {
    var wrap = document.createElement("div");
    wrap.className = "bubble user";
    var body = document.createElement("div");
    body.className = "bubble-body";
    body.textContent = text;
    wrap.appendChild(body);
    messagesEl.appendChild(wrap);
    scrollDown();
  }

  function addAssistantBubble() {
    var wrap = document.createElement("div");
    wrap.className = "bubble assistant";
    var body = document.createElement("div");
    body.className = "bubble-body";
    body.textContent = "";
    var foot = document.createElement("div");
    foot.className = "bubble-foot";
    wrap.appendChild(body);
    wrap.appendChild(foot);
    messagesEl.appendChild(wrap);
    scrollDown();
    return { root: wrap, body: body, foot: foot };
  }

  function addHistoryMessage(message) {
    // إعادة عرض رسالة محفوظة من قاعدة البيانات عند فتح محادثة
    if (message.role === "user") {
      addUserMessage(message.content);
      return;
    }
    if (message.role === "assistant") {
      // رسالة خلاصة مهمة محفوظة — نص عادي في فقاعة مساعد
      var bubble = addAssistantBubble();
      bubble.body.textContent = message.content;
      return;
    }
    // أدوار أخرى (thinker/…) — لا تُعرض في التاريخ المختصر
  }

  // ---------- نافذة التفاصيل ----------
  var modalBackdrop = $("modal-backdrop");
  var modalJson = $("modal-json");
  var modalTitle = $("modal-title");

  function openModal(event) {
    modalTitle.textContent = (event.role || "") + " — " + event.kind;
    modalJson.textContent = JSON.stringify(event, null, 2);
    modalBackdrop.hidden = false;
  }

  function closeModal() { modalBackdrop.hidden = true; }
  $("modal-close").addEventListener("click", closeModal);
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
  function loadConversations() {
    fetchJSON("/api/conversations").then(function (out) {
      if (!out.ok) return;
      renderConversations(out.j.conversations || []);
    });
  }

  function renderConversations(list) {
    var empty = $("conv-empty");
    if (empty && list.length) empty.remove();
    conversationsEl.querySelectorAll(".conv-item").forEach(function (n) { n.remove(); });
    if (!list.length) return;
    var today = new Date(); today.setHours(0, 0, 0, 0);
    list.forEach(function (c) {
      var item = document.createElement("button");
      item.className = "conv-item" +
        (c.conversation_id === state.conversationId ? " active" : "");
      var updated = new Date(c.updated_at);
      var when = updated >= today ? "اليوم" : "سابقًا";
      var icon = c.mode === "task" ? "🎯" : "💬";
      item.innerHTML =
        '<span class="conv-icon">' + icon + "</span>" +
        '<span class="conv-text">' + esc(c.title) + "</span>" +
        '<span class="conv-when">' + when + "</span>";
      item.title = c.title + " — " + when;
      item.addEventListener("click", function () { openConversation(c); });
      conversationsEl.appendChild(item);
    });
  }

  function openConversation(c) {
    state.conversationId = c.conversation_id;
    setMode(c.mode === "task" ? "task" : "chat", { silent: true });
    chatTitleEl.textContent = c.title;
    modeBadgeEl.hidden = false;
    modeBadgeEl.textContent = c.mode === "task" ? "مهمة" : "محادثة";
    messagesEl.textContent = "";
    hideWelcome();
    fetchJSON("/api/conversations/" + c.conversation_id + "/messages")
      .then(function (out) {
        if (!out.ok) return;
        (out.j.messages || []).forEach(addHistoryMessage);
        scrollDown();
      });
    renderConversationsLast();
  }

  var _lastConversations = [];

  function renderConversationsLast() {
    renderConversations(_lastConversations);
  }

  // تغليف loadConversations ليتذكر القائمة (تحديث active بعد الفتح)
  var _loadConversations = loadConversations;
  loadConversations = function () {
    fetchJSON("/api/conversations").then(function (out) {
      if (!out.ok) return;
      _lastConversations = out.j.conversations || [];
      renderConversations(_lastConversations);
    });
  };

  function newChat() {
    state.conversationId = null;
    chatTitleEl.textContent = "محادثة جديدة";
    modeBadgeEl.hidden = true;
    messagesEl.textContent = "";
    if (welcomeEl) welcomeEl.style.display = "";
    setMode("chat");
    inputEl.focus();
    renderConversationsLast();
  }

  $("new-chat").addEventListener("click", newChat);

  // ---------- طي الشريط الجانبي ----------
  var sidebarEl = $("sidebar");
  function toggleSidebar() {
    document.body.classList.toggle("sidebar-collapsed");
  }
  $("sidebar-toggle").addEventListener("click", toggleSidebar);
  var collapseBtn = $("sidebar-collapse");
  if (collapseBtn) collapseBtn.addEventListener("click", toggleSidebar);

  // ---------- النمط: محادثة / مهمة ----------
  function setMode(mode, opts) {
    state.mode = mode;
    var isTask = mode === "task";
    modeChipEl.textContent = isTask ? "مهمة" : "محادثة";
    modeChipEl.classList.toggle("task", isTask);
    inputEl.placeholder = isTask
      ? "صف هدف المهمة… (Enter للإرسال · Shift+Enter لسطر جديد)"
      : "اكتب رسالتك… (Enter للإرسال · Shift+Enter لسطر جديد)";
    taskSettingsEl.hidden = !isTask;
    if (!opts || !opts.silent) {
      if (isTask) renderTaskSettingsSummary();
    }
    if (isTask) renderTaskSettingsSummary();
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

  // اقتراحات شاشة البداية تضبط النمط أيضًا
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

  // ---------- الإرسال: توزيع حسب النمط ----------
  function send() {
    var text = inputEl.value.trim();
    if (!text || state.busy) return;
    inputEl.value = "";
    autoGrow();
    updateSendState();
    hideWelcome();
    addUserMessage(text);
    if (state.mode === "task") {
      startTask(text);
    } else {
      startChat(text);
    }
  }

  // ---------- المحادثة الحية ----------
  function startChat(text) {
    state.activeRun = { kind: "chat", cycleId: "" };
    setBusy(true);
    var bubble = null;
    var body = null;

    postStream("/api/chat/stream", {
      message: text,
      conversation_id: state.conversationId,
    }).then(finish, failed);

    handlers["chat.start"] = function (event) {
      state.conversationId = event.details.conversation_id;
      chatTitleEl.textContent = chatTitleEl.textContent === "محادثة جديدة"
        ? text.slice(0, 40) : chatTitleEl.textContent;
      modeBadgeEl.hidden = false;
      modeBadgeEl.textContent = "محادثة";
      bubble = addAssistantBubble();
      body = bubble.body;
    };
    handlers["chat.delta"] = function (event) {
      if (!body) return;
      body.textContent += (body.textContent ? " " : "") + event.text;
      scrollDown();
    };
    handlers["chat.done"] = function (event) {
      var d = event.details || {};
      if (bubble) {
        bubble.foot.textContent =
          (d.provider || "") + " · " + (d.model || "") +
          " · " + fmtTime(d.duration_ms || 0);
      }
      removeWorking();
    };
    handlers["chat.error"] = function (event) {
      removeWorking();
      var card = makeSystemCard(event);
      messagesEl.appendChild(card);
      scrollDown();
    };

    function failed(err) {
      removeWorking();
      var card = makeSystemCard({
        kind: "chat.error", role: "chat",
        text: "تعذر البث: " + err.message,
        details: { error: String(err.message) }
      });
      messagesEl.appendChild(card);
      finish();
    }

    function finish() {
      delete handlers["chat.start"];
      delete handlers["chat.delta"];
      delete handlers["chat.done"];
      delete handlers["chat.error"];
      state.activeRun = null;
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
    }).then(finish, failed);

    function failed(err) {
      removeWorking();
      var card = makeSystemCard({
        kind: "cycle_error", role: "coordinator",
        text: "تعذر البث: " + err.message,
        details: { error: String(err.message) }
      });
      messagesEl.appendChild(card);
      finish();
    }

    function finish() {
      removeWorking();
      state.activeRun = null;
      setBusy(false);
      stopRunEl.hidden = true;
      loadConversations();
    }
  }

  // حدث المهمة يصل من البث — بطاقة التنفيذ تديرها task-cards.js
  handlers["task.conversation"] = function (event) {
    state.conversationId = event.details.conversation_id;
    chatTitleEl.textContent =
      chatTitleEl.textContent === "محادثة جديدة"
        ? "مهمة جديدة" : chatTitleEl.textContent;
    modeBadgeEl.hidden = false;
    modeBadgeEl.textContent = "مهمة";
  };

  // ---------- الإيقاف الفوري (الأمر 004) ----------
  function requestStop() {
    if (!state.activeRun || !state.activeRun.cycleId) return;
    stopRunEl.disabled = true;
    stopRunEl.textContent = "■ جارٍ طلب الإيقاف…";
    var isMission = state.activeRun.kind === "mission";
    var url = isMission ? "/api/mission/stop" : "/api/cycle/stop";
    var body = isMission
      ? { reason: "زر الإيقاف من الواجهة" }
      : { cycle_id: state.activeRun.cycleId, reason: "زر الإيقاف من الواجهة" };
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
      insertBeforeWorking(card);
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
    fmtTime: fmtTime,
    fetchJSON: fetchJSON,
    postStream: postStream,
    renderEvent: renderEvent,
    scrollDown: scrollDown,
    addUserMessage: addUserMessage,
    makeSystemCard: makeSystemCard,
    insertBeforeWorking: insertBeforeWorking,
    removeWorking: removeWorking,
    addWorking: addWorking,
    openModal: openModal,
    setBusy: setBusy,
    loadConversations: function () { loadConversations(); },
    onTaskFinished: function () {
      state.activeRun = null;
      setBusy(false);
      stopRunEl.hidden = true;
      loadConversations();
    },
    stopButtonEnable: function (enabled) {
      stopRunEl.disabled = !enabled;
    },
    currentStopRunEl: function () { return stopRunEl; },
  };

  // ---------- الإقلاع ----------
  setMode("chat");
  loadConversations();
  inputEl.focus();
})();
