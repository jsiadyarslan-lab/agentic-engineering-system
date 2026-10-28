/* Agentic Engineering System — المحادثة الحية المتدفقة (الأمر 008 §2-§6).
 *
 * message_started ← chat.status(generating) ← message_delta* ←
 * message_completed — مع مؤشر حالة صادق من أحداث فعلية فقط (§31 لا
 * كذب)، وعارض Markdown مقيد الأداء (buffer → throttled render §4)،
 * وبصمة المزود/النموذج أسفل الرسالة (§6)، وإعادة اتصال بلا فقد (§19).
 */
(function () {
  "use strict";

  if (!window.Hub || !window.MD) return;
  var Hub = window.Hub;
  var H = Hub.handlers;
  var MD = window.MD;

  var STATUS_TEXT = {
    connecting: "يتصل بالنموذج…",
    generating: "يكتب الآن…",
    stream_fallback: "نقل كامل معلن…",
    completed: "",
    failed: ""
  };

  // ---------- الرسالة الحية الواحدة ----------
  function LiveMessage(messageId) {
    this.id = messageId;
    this.root = document.createElement("div");
    this.root.className = "bubble assistant live-msg";
    this.body = document.createElement("div");
    this.body.className = "bubble-body md-body";
    this.status = document.createElement("div");
    this.status.className = "live-status";
    this.foot = document.createElement("div");
    this.foot.className = "bubble-foot";
    this.meta = document.createElement("div");
    this.meta.className = "bubble-meta";
    this.root.appendChild(this.body);
    this.root.appendChild(this.status);
    this.root.appendChild(this.foot);
    this.root.appendChild(this.meta);
    this.text = "";
    this.buffer = "";
    this.provider = "";
    this.model = "";
    this.startedAt = null;
    this.dirty = false;
    this.raf = null;
  }

  LiveMessage.prototype.setStatus = function (key, note) {
    var label = note || STATUS_TEXT[key] || key;
    if (!label) { this.status.hidden = true; return; }
    this.status.hidden = false;
    this.status.innerHTML =
      '<span class="status-dot' + (key === "generating" ? " pulse" : "") +
      '" aria-hidden="true"></span><span>' + Hub.esc(label) + "</span>";
    Hub.onLiveContent();
  };

  LiveMessage.prototype.setMeta = function (info, streaming) {
    this.provider = info.provider || this.provider;
    this.model = info.model || this.model;
    this.meta.hidden = false;
    this.meta.innerHTML =
      '<span class="meta-prov" dir="ltr">' + Hub.esc(this.provider) + "</span>" +
      '<span class="meta-model" dir="ltr">' + Hub.esc(this.model) + "</span>" +
      (streaming
        ? '<span class="meta-stream"><span class="status-dot live pulse" aria-hidden="true"></span>يعمل الآن</span>'
        : "");
  };

  LiveMessage.prototype.appendDelta = function (delta) {
    this.text += delta;
    this.buffer += delta;
    this.dirty = true;
    if (this.raf === null) {
      var self = this;
      this.raf = setTimeout(function () { self.flush(); }, 90);
    }
  };

  LiveMessage.prototype.flush = function (final) {
    if (this.raf !== null) {
      clearTimeout(this.raf);
      this.raf = null;
    }
    if (!this.dirty && !final) return;
    this.dirty = false;
    // عارض كامل لكن على عقدة واحدة فقط — لا إعادة رسم الصفحة (§32)
    this.body.innerHTML = MD.render(this.text, { streaming: !final });
    Hub.onLiveContent();
  };

  LiveMessage.prototype.complete = function (details) {
    var d = details || {};
    this.flush(true);
    this.setStatus("completed");
    this.status.hidden = true;
    var secs = d.duration_ms ? (d.duration_ms / 1000).toFixed(1) + " ث" : "";
    this.foot.textContent =
      ((d.streamed ? "بث حي · " : "") + secs).trim();
    this.setMeta(d, false);
    this.root.classList.remove("streaming");
  };

  // ---------- إدارة الرسائل الجارية (013.7 §P11) — لكل محادثة حالة مستقلة ----------
  // كل محادثة تحمل كائن حالة: { live, activeId, expectedId, frozen, lastSourcesByMessage }
  var conversationStates = new Map();
  var currentConversationId = "";

  function getConversationState(conversationId) {
    if (!conversationStates.has(conversationId)) {
      conversationStates.set(conversationId, {
        live: null,
        activeId: "",
        expectedId: "",
        frozen: {},
        lastSourcesByMessage: {}
      });
    }
    return conversationStates.get(conversationId);
  }

  function setCurrentConversation(conversationId) {
    currentConversationId = conversationId || "";
  }

  function messageAllowed(conversationId, messageId) {
    var id = messageId || "";
    var state = getConversationState(conversationId);
    if (id && state.frozen[id]) return false;          // (§F) ثبات بعد الاكتمال
    if (state.expectedId && id && id !== state.expectedId) return false;  // (§E) عزل
    return true;
  }

  function getLiveState(conversationId) {
    var state = getConversationState(conversationId);
    return {
      live: state.live,
      activeId: state.activeId,
      expectedId: state.expectedId,
      frozen: state.frozen,
      lastSourcesByMessage: state.lastSourcesByMessage
    };
  }

  function setLiveState(conversationId, live, activeId, expectedId, frozen, lastSourcesByMessage) {
    var state = getConversationState(conversationId);
    if (live !== undefined) state.live = live;
    if (activeId !== undefined) state.activeId = activeId;
    if (expectedId !== undefined) state.expectedId = expectedId;
    if (frozen !== undefined) state.frozen = frozen;
    if (lastSourcesByMessage !== undefined) state.lastSourcesByMessage = lastSourcesByMessage;
  }

  function getCurrentConversationId() {
    return currentConversationId;
  }

  function ensureLive(event) {
    var conversationId = getCurrentConversationId();
    var id = event.message_id || "";
    if (!messageAllowed(conversationId, id)) return null;
    var state = getLiveState(conversationId);
    if (state.live && state.activeId === id) return state.live;
    if (state.live) {
      // (007 BUG-01) كان _obj غير معلن — ReferenceError تحت "use strict"
      // عند ورود رسالة حية أثناء بثّ رسالة أخرى بنفس المحادثة.
      state.live.complete({});
      var frozen = Object.assign({}, state.frozen);
      frozen[state.activeId] = true;
      setLiveState(conversationId, null, state.activeId, undefined, frozen);
    }
    var live = new LiveMessage(id);
    setLiveState(conversationId, live, id, undefined, undefined, undefined);
    Hub.insertAtEnd(live.root);
    return live;
  }

  H["message_started"] = function (event) {
    var conversationId = event.details && event.details.conversation_id ? event.details.conversation_id : getCurrentConversationId();
    setCurrentConversation(conversationId);
    var msg = ensureLive(event);
    if (!msg) return;
    msg.setMeta(event.details || {}, true);
    msg.root.classList.add("streaming");
    msg.setStatus(event.status || "connecting");
  };

  H["chat.status"] = function (event) {
    var conversationId = event.details && event.details.conversation_id ? event.details.conversation_id : getCurrentConversationId();
    setCurrentConversation(conversationId);
    var state = getLiveState(conversationId);
    if (!state.live && event.message_id) ensureLive(event);
    if (state.live) state.live.setStatus(event.status, event.text);
  };

  H["message_delta"] = function (event) {
    var conversationId = event.details && event.details.conversation_id ? event.details.conversation_id : getCurrentConversationId();
    setCurrentConversation(conversationId);
    var msg = ensureLive(event);
    if (!msg) return;
    if (!msg.root.classList.contains("streaming")) {
      msg.root.classList.add("streaming");
      msg.setMeta(event.details || {}, true);
    }
    msg.setStatus("generating");
    msg.appendDelta(event.delta != null ? event.delta : (event.text || ""));
  };

  H["message_completed"] = function (event) {
    var conversationId = event.details && event.details.conversation_id ? event.details.conversation_id : getCurrentConversationId();
    var state = getLiveState(conversationId);
    if (state.live && (event.message_id === state.activeId || !event.message_id)) {
      var bubble = state.live.root;
      var messageId = event.message_id || state.activeId;
      state.live.complete(event.details);
      // (§F) الرسالة المكتملة مجمّدة — لا حدث لاحق يستبدل محتواها
      var state = getLiveState(conversationId);
      var frozen = Object.assign({}, state.frozen);
      frozen[messageId] = true;
      setLiveState(conversationId, null, state.activeId, undefined, frozen);
      state.live.root.setAttribute("data-msg-id", messageId);
      state.live.root.setAttribute("data-msg-state", "completed");
      setLiveState(conversationId, null);
      // (013.4 §26) الشريط يُبنى عند الاكتمال — research.used وصل
      // قبله فالمصادر جاهزة (الترتيب مضمون من الخادم)
      var state2 = getLiveState(conversationId);
      var web = (event.details && event.details.web_used) ||
        (state2.lastSourcesByMessage[messageId] || {}).show;
      if (web) {
        buildWebUsedBar(
          bubble, messageId,
          (state2.lastSourcesByMessage[messageId] || {}).sources || []
        );
      }
    }
    Hub.onChatDone(event);
  };

  H["chat.error"] = function (event) {
    var conversationId = event.details && event.details.conversation_id ? event.details.conversation_id : getCurrentConversationId();
    var state = getLiveState(conversationId);
    if (state.live && messageAllowed(conversationId, event.message_id || state.activeId)) {
      state.live.flush(true);
      state.live.status.hidden = true;
      var frozen = Object.assign({}, state.frozen);
      frozen[state.activeId] = true;
      setLiveState(conversationId, undefined, undefined, undefined, frozen);
      if (state.live.root) {
        state.live.root.setAttribute("data-msg-state", "failed");
      }
      setLiveState(conversationId, null, "");
    }
    Hub.showErrorCard(event);
    Hub.onChatDone(event);
  };

  // ---------- (013.4 §26+§29) الويب في المحادثة: مؤشر ومصادر (013.7 §P11) — لكل محادثة ----------
  // research.started/results/unavailable/fetched: سطور حالة حية أثناء
  // البحث — وresearch.used يثبت 🌐 مع مصادر قابلة للفتح بعد الاكتمال.

  function getLastSourcesByMessage(conversationId) {
    var state = getConversationState(conversationId);
    return state.lastSourcesByMessage;
  }

  function setLastSourcesByMessage(conversationId, messageId, data) {
    var state = getConversationState(conversationId);
    state.lastSourcesByMessage[messageId || ""] = data;
  }

  function getLastSourcesForMessage(conversationId, messageId) {
    var sources = getLastSourcesByMessage(conversationId);
    return sources[messageId || ""];
  }

  function setLastSourcesForMessage(conversationId, messageId, data) {
    var state = getConversationState(conversationId);
    state.lastSourcesByMessage[messageId || ""] = data;
  }

  H["research.started"] = function (event) {
    var conversationId = event.details && event.details.conversation_id ? event.details.conversation_id : getCurrentConversationId();
    setCurrentConversation(conversationId);
    var msg = ensureLive(event);
    msg.setStatus("generating", event.text || "بحث في الويب…");
  };

  H["research.results"] = function (event) {
    var conversationId = event.details && event.details.conversation_id ? event.details.conversation_id : getCurrentConversationId();
    setCurrentConversation(conversationId);
    var msg = ensureLive(event);
    msg.setStatus("generating", event.text || "نتائج البحث وصلت");
    setLastSourcesForMessage(conversationId, event.message_id || "", {
      show: true,
      sources: ((event.details || {}).results || []).map(function (r) {
        return { title: r.title, url: r.url };
      }),
    });
  };

  H["research.unavailable"] = function (event) {
    var conversationId = event.details && event.details.conversation_id ? event.details.conversation_id : getCurrentConversationId();
    setCurrentConversation(conversationId);
    var msg = ensureLive(event);
    msg.setStatus("generating",
      event.text || "البحث غير متاح — الإجابة بلا ويب");
  };

  H["research.fetched"] = function (event) {
    var conversationId = event.details && event.details.conversation_id ? event.details.conversation_id : getCurrentConversationId();
    setCurrentConversation(conversationId);
    var msg = ensureLive(event);
    msg.setStatus("generating", event.text || "جُلبت صفحة");
  };

  H["research.fetch_failed"] = function (event) {
    var conversationId = event.details && event.details.conversation_id ? event.details.conversation_id : getCurrentConversationId();
    setCurrentConversation(conversationId);
    var msg = ensureLive(event);
    msg.setStatus("generating", event.text || "تعذر جلب صفحة");
  };

  H["research.used"] = function (event) {
    var conversationId = event.details && event.details.conversation_id ? event.details.conversation_id : getCurrentConversationId();
    setCurrentConversation(conversationId);
    // المصادر النهائية المستخدمة — تُخزن ليبنى عليها الشريط أسفل الرسالة
    setLastSourcesForMessage(conversationId, event.message_id || "", {
      show: true,
      sources: ((event.details || {}).sources || []),
    });
    // إن انتهت الرسالة قبل هذا الحدث (سباق الترتيب) — ابنِ الشريط الآن
    var existing = document.querySelector(
      ".web-used-bar[data-msg='" + (event.message_id || "") + "']");
    if (existing) return;
    var lastAssistant = document.querySelector(
      ".messages .bubble.assistant:last-of-type");
    if (lastAssistant && !getLiveState(getCurrentConversationId()).live) {
      buildWebUsedBar(lastAssistant, event.message_id || "",
        (event.details || {}).sources || []);
    }
  };

  /** شريط «🌐 استُخدم الويب» بمصادر قابلة للطي (§26). */
  function buildWebUsedBar(bubble, messageId, sources) {
    if (bubble.querySelector(".web-used-bar")) return;
    var bar = document.createElement("div");
    bar.className = "web-used-bar";
    bar.setAttribute("data-msg", messageId);
    var head = document.createElement("button");
    head.className = "web-used-head";
    head.textContent = "🌐 استُخدم الويب في هذه الإجابة" +
      (sources.length ? " — " + sources.length + " مصادر" : "");
    var list = document.createElement("div");
    list.className = "web-used-sources";
    list.hidden = true;
    sources.slice(0, 8).forEach(function (source) {
      var item = document.createElement("a");
      item.className = "web-source";
      item.href = source.url || "#";
      item.target = "_blank";
      item.rel = "noopener noreferrer";
      item.dir = "auto";
      item.textContent = (source.title || source.url || "").slice(0, 90);
      item.title = source.url || "";
      list.appendChild(item);
    });
    head.addEventListener("click", function () {
      list.hidden = !list.hidden;
      head.classList.toggle("open", !list.hidden);
    });
    bar.appendChild(head);
    bar.appendChild(list);
    bubble.appendChild(bar);
  }

  // ============================================================
  // (013.7 §P18) واجهة تنفيذ المحادثة — بطاقات مرحلة/خطوة/أداة حية
  // ============================================================
  var STATUS_ICON = {
    running: "⏳",
    succeeded: "✅",
    failed: "❌",
    blocked: "🚫",
    pending: "⏸️",
  };

  var PHASE_STATUS_TEXT = {
    starting: "جارٍ البدء…",
    running: "قيد التنفيذ…",
    completed: "مكتملة",
    failed: "فشلت",
  };

  var STEP_STATUS_TEXT = {
    starting: "جارٍ البدء…",
    running: "قيد التنفيذ…",
    awaiting_approval: "بانتظار اعتماد المالك",
    blocked: "محجوبة",
    completed: "مكتملة",
    failed: "فشلت",
  };

  var TOOL_STATUS_TEXT = {
    started: "⏳ بدء الأداة…",
    succeeded: "✅ نجحت",
    failed: "❌ فشلت",
  };

  var PREFLIGHT_STATUS_TEXT = {
    started: "⏳ فحص ما قبل التنفيذ…",
    capabilities_evaluated: "🔍 تقييم الإمكانات…",
    environment_check_started: "🔧 فحص بيئة التنفيذ…",
    environment_ready: "✅ البيئة جاهزة",
    blocked: "🚫 حاجب توفير — يحتاج تدخّل المالك",
    rechecked: "🔄 إعادة فحص…",
    pass: "✅ الفحص نجح — التنفيذ سيبدأ",
  };

  /** شريط حالة تنفيذي مضغوط — يُدرج داخل فقاعة المحادثة أو في لوحة جانبية. */
  function LiveExecutionCard() {
    this.root = document.createElement("div");
    this.root.className = "execution-card";
    this.root.innerHTML =
      '<div class="execution-header">' +
        '<span class="execution-title">تنفيذ المشروع</span>' +
        '<span class="execution-badge">جارٍ…</span>' +
      '</div>' +
      '<div class="execution-body"></div>';
    this.body = this.root.querySelector(".execution-body");
    this.phases = new Map(); // phase_id -> {el, steps: Map}
    this.currentPhaseId = null;
    this.currentStepId = null;
  }

  LiveExecutionCard.prototype.getOrCreatePhase = function (phaseId, title) {
    var phase = this.phases.get(phaseId);
    if (phase) return phase;
    var el = document.createElement("div");
    el.className = "execution-phase";
    el.innerHTML =
      '<div class="phase-header">' +
        '<span class="phase-icon">📋</span>' +
        '<span class="phase-title">' + Hub.esc(title || "مرحلة") + '</span>' +
        '<span class="phase-status">جارٍ…</span>' +
      '</div>' +
      '<div class="phase-steps"></div>';
    phase = {
      el: el,
      title: title,
      stepsEl: el.querySelector(".phase-steps"),
      steps: new Map(),
      status: "starting",
    };
    this.phases.set(phaseId, phase);
    this.body.appendChild(el);
    return phase;
  };

  LiveExecutionCard.prototype.getOrCreateStep = function (phase, stepId, objective) {
    var step = phase.steps.get(stepId);
    if (step) return step;
    var el = document.createElement("div");
    el.className = "execution-step";
    el.innerHTML =
      '<div class="step-header">' +
        '<span class="step-icon">📝</span>' +
        '<span class="step-title">' + Hub.esc(objective || "خطوة") + '</span>' +
        '<span class="step-status">جارٍ…</span>' +
      '</div>' +
      '<div class="step-tools"></div>';
    step = {
      el: el,
      objective: objective,
      toolsEl: el.querySelector(".step-tools"),
      tools: new Map(),
      status: "starting",
    };
    phase.steps.set(stepId, step);
    phase.stepsEl.appendChild(el);
    return step;
  };

  LiveExecutionCard.prototype.getOrCreateTool = function (step, toolKey, toolName) {
    var tool = step.tools.get(toolKey);
    if (tool) return tool;
    var el = document.createElement("div");
    el.className = "execution-tool";
    el.innerHTML =
      '<span class="tool-icon">🔧</span>' +
      '<span class="tool-name">' + Hub.esc(toolName || "أداة") + '</span>' +
      '<span class="tool-status">بدء…</span>' +
      '<span class="tool-duration"></span>';
    tool = { el: el, status: "started" };
    step.tools.set(toolKey, tool);
    step.toolsEl.appendChild(el);
    return tool;
  };

  LiveExecutionCard.prototype.updatePhaseStatus = function (phaseId, status, text) {
    var phase = this.phases.get(phaseId);
    if (!phase) return;
    phase.status = status;
    var badge = phase.el.querySelector(".phase-status");
    if (badge) badge.textContent = text || PHASE_STATUS_TEXT[status] || status;
    phase.el.classList.remove("phase-starting", "phase-running", "phase-completed", "phase-failed");
    phase.el.classList.add("phase-" + status);
  };

  LiveExecutionCard.prototype.updateStepStatus = function (phaseId, stepId, status, text) {
    var phase = this.phases.get(phaseId);
    if (!phase) return;
    var step = phase.steps.get(stepId);
    if (!step) return;
    step.status = status;
    var badge = step.el.querySelector(".step-status");
    if (badge) badge.textContent = text || STEP_STATUS_TEXT[status] || status;
    step.el.classList.remove("step-starting", "step-running", "step-awaiting_approval", "step-blocked", "step-completed", "step-failed");
    step.el.classList.add("step-" + status);
  };

  LiveExecutionCard.prototype.updateToolStatus = function (phaseId, stepId, toolKey, status, text, durationMs) {
    var phase = this.phases.get(phaseId);
    if (!phase) return;
    var step = phase.steps.get(stepId);
    if (!step) return;
    var tool = step.tools.get(toolKey);
    if (!tool) return;
    tool.status = status;
    var badge = tool.el.querySelector(".tool-status");
    if (badge) badge.textContent = text || TOOL_STATUS_TEXT[status] || status;
    var dur = tool.el.querySelector(".tool-duration");
    if (dur && durationMs) dur.textContent = " (" + (durationMs / 1000).toFixed(1) + " ث)";
    tool.el.classList.remove("tool-started", "tool-succeeded", "tool-failed");
    tool.el.classList.add("tool-" + status);
  };

  LiveExecutionCard.prototype.setOverallStatus = function (status, text) {
    var badge = this.root.querySelector(".execution-badge");
    if (badge) {
      badge.textContent = text || (STATUS_ICON[status] ? STATUS_ICON[status] + " " + status : status);
      badge.className = "execution-badge " + status;
    }
  };

  LiveExecutionCard.prototype.addEvidence = function (phaseId, stepId, evidence) {
    var phase = this.phases.get(phaseId);
    if (!phase) return;
    var step = phase.steps.get(stepId);
    if (!step) return;
    var toolsEl = step.toolsEl;
    var el = document.createElement("div");
    el.className = "step-evidence";
    el.innerHTML =
      '<span class="evidence-icon">📎</span>' +
      '<span class="evidence-label">أدلة: ' + (evidence.files || []).map(function (f) { return Hub.esc(f.name || f.path || f); }).join(", ") + '</span>';
    toolsEl.appendChild(el);
  };

  // ============================================================
  // معالجات أحداث التنفيذ (013.7 §P18)
  // ============================================================

  function getOrCreateExecutionCard(conversationId) {
    var state = getConversationState(conversationId);
    if (!state.executionCard) {
      state.executionCard = new LiveExecutionCard();
      var messages = document.querySelector(".messages");
      if (messages) messages.appendChild(state.executionCard.root);
    }
    return state.executionCard;
  }

  function clearExecutionCard(conversationId) {
    var state = getConversationState(conversationId);
    if (state.executionCard && state.executionCard.root.parentNode) {
      state.executionCard.root.parentNode.removeChild(state.executionCard.root);
    }
    state.executionCard = null;
  }

  H["PHASE_STARTED"] = function (event) {
    var conversationId = event.details && event.details.conversation_id ? event.details.conversation_id : getCurrentConversationId();
    setCurrentConversation(conversationId);
    var card = getOrCreateExecutionCard(conversationId);
    var phaseId = (event.details || {}).phase_id;
    var title = (event.details || {}).title;
    if (!phaseId) return;
    card.getOrCreatePhase(phaseId, title);
    card.updatePhaseStatus(phaseId, "running", "قيد التنفيذ…");
    card.setOverallStatus("running", "⏳ جارٍ التنفيذ…");
  };

  H["STEP_STARTED"] = function (event) {
    var conversationId = event.details && event.details.conversation_id ? event.details.conversation_id : getCurrentConversationId();
    setCurrentConversation(conversationId);
    var card = getOrCreateExecutionCard(conversationId);
    var phaseId = (event.details || {}).phase_id;
    var stepId = (event.details || {}).step_id;
    var objective = (event.details || {}).objective;
    if (!phaseId || !stepId) return;
    var phase = card.getOrCreatePhase(phaseId, "");
    card.getOrCreateStep(phase, stepId, objective);
    card.updateStepStatus(phaseId, stepId, "running", "قيد التنفيذ…");
  };

  H["EXECUTION_STARTED"] = function (event) {
    var conversationId = event.details && event.details.conversation_id ? event.details.conversation_id : getCurrentConversationId();
    setCurrentConversation(conversationId);
    var card = getOrCreateExecutionCard(conversationId);
    card.setOverallStatus("running", "⏳ جارٍ التنفيذ…");
  };

  H["ROLE_EXECUTING"] = function (event) {
    var conversationId = event.details && event.details.conversation_id ? event.details.conversation_id : getCurrentConversationId();
    setCurrentConversation(conversationId);
    var card = getOrCreateExecutionCard(conversationId);
    var role = (event.details || {}).role;
    var objective = (event.details || {}).objective;
    if (role) {
      card.setOverallStatus("running", "⏳ " + role + ": " + (objective || "تنفيذ…"));
    }
  };

  H["TOOL_EXECUTION"] = function (event) {
    var conversationId = event.details && event.details.conversation_id ? event.details.conversation_id : getCurrentConversationId();
    setCurrentConversation(conversationId);
    var card = getOrCreateExecutionCard(conversationId);
    var phaseId = (event.details || {}).phase_id;
    var stepId = (event.details || {}).step_id;
    var tool = (event.details || {}).tool;
    var phase = (event.details || {}).phase; // started/succeeded/failed
    var role = (event.details || {}).role;
    var durationMs = (event.details || {}).duration_ms;
    var summary = (event.details || {}).summary;
    var error = (event.details || {}).error;
    if (!phaseId || !stepId || !tool) return;
    var ph = card.getOrCreatePhase(phaseId, "");
    var st = card.getOrCreateStep(ph, stepId, "");
    var toolKey = tool + "_" + (event.details || {}).role;
    var tl = card.getOrCreateTool(st, toolKey, tool);
    var status = (phase === "succeeded") ? "succeeded" : (phase === "failed" ? "failed" : "started");
    var text = summary || (status === "started" ? "بدء…" : (status === "succeeded" ? "نجحت" : "فشلت"));
    if (error) text += " — " + error;
    card.updateToolStatus(phaseId, stepId, toolKey, status, text, durationMs);
  };

  H["EVIDENCE_CREATED"] = function (event) {
    var conversationId = event.details && event.details.conversation_id ? event.details.conversation_id : getCurrentConversationId();
    setCurrentConversation(conversationId);
    var card = getOrCreateExecutionCard(conversationId);
    var phaseId = (event.details || {}).phase_id;
    var stepId = (event.details || {}).step_id;
    var evidence = event.details || {};
    if (!phaseId || !stepId) return;
    card.addEvidence(phaseId, stepId, evidence);
    card.setOverallStatus("succeeded", "✅ أدلة منشأة");
  };

  // --- فحوصات ما قبل التنفيذ ---
  H["PREFLIGHT_STARTED"] = function (event) {
    var conversationId = event.details && event.details.conversation_id ? event.details.conversation_id : getCurrentConversationId();
    setCurrentConversation(conversationId);
    var card = getOrCreateExecutionCard(conversationId);
    card.setOverallStatus("running", "⏳ " + (PREFLIGHT_STATUS_TEXT.started || "فحص ما قبل التنفيذ…"));
  };

  H["CAPABILITIES_EVALUATED"] = function (event) {
    var conversationId = event.details && event.details.conversation_id ? event.details.conversation_id : getCurrentConversationId();
    setCurrentConversation(conversationId);
    var card = getOrCreateExecutionCard(conversationId);
    card.setOverallStatus("running", "🔍 " + (PREFLIGHT_STATUS_TEXT.capabilities_evaluated || "تقييم الإمكانات…"));
  };

  H["ENVIRONMENT_CHECK_STARTED"] = function (event) {
    var conversationId = event.details && event.details.conversation_id ? event.details.conversation_id : getCurrentConversationId();
    setCurrentConversation(conversationId);
    var card = getOrCreateExecutionCard(conversationId);
    card.setOverallStatus("running", "🔧 " + (PREFLIGHT_STATUS_TEXT.environment_check_started || "فحص بيئة التنفيذ…"));
  };

  H["ENVIRONMENT_READY"] = function (event) {
    var conversationId = event.details && event.details.conversation_id ? event.details.conversation_id : getCurrentConversationId();
    setCurrentConversation(conversationId);
    var card = getOrCreateExecutionCard(conversationId);
    card.setOverallStatus("running", "✅ " + (PREFLIGHT_STATUS_TEXT.environment_ready || "البيئة جاهزة"));
  };

  H["PREFLIGHT_BLOCKED"] = function (event) {
    var conversationId = event.details && event.details.conversation_id ? event.details.conversation_id : getCurrentConversationId();
    setCurrentConversation(conversationId);
    var card = getOrCreateExecutionCard(conversationId);
    var reason = (event.details || {}).reason || "حاجب توفير";
    card.setOverallStatus("blocked", "🚫 " + reason);
  };

  H["PREFLIGHT_RECHECKED"] = function (event) {
    var conversationId = event.details && event.details.conversation_id ? event.details.conversation_id : getCurrentConversationId();
    setCurrentConversation(conversationId);
    var card = getOrCreateExecutionCard(conversationId);
    card.setOverallStatus("running", "🔄 " + (PREFLIGHT_STATUS_TEXT.rechecked || "إعادة فحص…"));
  };

  H["PREFLIGHT_PASS"] = function (event) {
    var conversationId = event.details && event.details.conversation_id ? event.details.conversation_id : getCurrentConversationId();
    setCurrentConversation(conversationId);
    var card = getOrCreateExecutionCard(conversationId);
    card.setOverallStatus("succeeded", "✅ " + (PREFLIGHT_STATUS_TEXT.pass || "الفحص نجح — التنفيذ سيبدأ"));
  };

  // --- نتائج التنفيذ ---
  H["TEST_COMPLETED"] = function (event) {
    var conversationId = event.details && event.details.conversation_id ? event.details.conversation_id : getCurrentConversationId();
    setCurrentConversation(conversationId);
    var card = getOrCreateExecutionCard(conversationId);
    var verdict = (event.details || {}).final_state;
    card.setOverallStatus(verdict === "PASS" ? "succeeded" : "failed", (verdict === "PASS" ? "✅" : "❌") + " الاختبار: " + verdict);
  };

  H["REVIEW_COMPLETED"] = function (event) {
    var conversationId = event.details && event.details.conversation_id ? event.details.conversation_id : getCurrentConversationId();
    setCurrentConversation(conversationId);
    var card = getOrCreateExecutionCard(conversationId);
    var verdict = (event.details || {}).verdict;
    card.setOverallStatus(verdict === "PASS" ? "succeeded" : "failed", (verdict === "PASS" ? "✅" : "❌") + " المراجعة: " + verdict);
  };

  H["AUDIT_COMPLETED"] = function (event) {
    var conversationId = event.details && event.details.conversation_id ? event.details.conversation_id : getCurrentConversationId();
    setCurrentConversation(conversationId);
    var card = getOrCreateExecutionCard(conversationId);
    var verdict = (event.details || {}).verdict;
    card.setOverallStatus(verdict === "PASS" ? "succeeded" : "failed", (verdict === "PASS" ? "✅" : "❌") + " التدقيق: " + verdict);
  };

  // ---------- إعادة الاتصال (§19+§34+013.5 §E/§G) ----------
  function attachStream(conversationId, after) {
    return fetch(
      "/api/chat/events/" + conversationId + "?after=" + (after || 0)
    ).then(function (resp) {
      if (!resp.ok) throw new Error("HTTP " + resp.status);
      return Hub.pumpSSE(resp);
    });
  }

  /** تعليق البث بعد refresh — يُستدعى عند فتح محادثة فيها توليد جارٍ.
   *
   * (013.5 §E/§G) لا استئناف من الصفر أبدًا: موضع الاستئناف يأتي من
   * الخادم (``last_seq`` = آخر تسلسل مسجَّل في هذا التيار)، ومعرّف
   * الرسالة الجارية يأتي صريحًا (``message_id``). البدء من صفر كان
   * يُعيد بث **تاريخ المحادثة كله** فيُعاد رسمه كأنه ردٌّ جديد — وهو
   * الجذر الحرفي لظهور «Confirmation of Completion / A15 /
   * HASH-MANIFEST» ردًّا على سؤال غير متعلق بها.
   */
  window.ChatLive = {
    resumeIfRunning: function (conversationId) {
      return Hub.fetchJSON(
        "/api/chat/active?conversation_id=" + conversationId
      ).then(function (out) {
        if (!out.ok || !out.j.running) {
          setLiveState(conversationId, undefined, undefined, "", Object.assign({}, getConversationState(conversationId).frozen));
          return { running: false, resumed_from: null };
        }
        var expectedId = out.j.message_id || "";
        Hub.setBusy(true);
        Hub.state.activeRun = { kind: "chat", cycleId: "" };
        // (013.5 §G) الفقاعة الحية تُبنى الآن صراحةً بدل انتظار أول
        // قطعة: الرسالة الجارية معلومة من الخادم، فلا «صمت» حتى
        // تصل أول قطعة.
        if (expectedId) {
          var msg = ensureLive({ message_id: expectedId, details: {} });
          if (msg) {
            msg.root.classList.add("streaming");
            msg.setStatus("generating");
          }
        }
        var from = out.j.last_seq || 0;
        Hub.state.lastSeq = Math.max(Hub.state.lastSeq || 0, from);
        return attachStream(conversationId, from).then(
          Hub.onChatDone, function () { Hub.onChatDone({}); }
        ).then(function () { return { running: true, resumed_from: from }; });
      });
    },
    /** (013.5 §G) موضع الاستئناف الحقيقي — للاختبارات والتشخيص. */
    currentExpectation: function (conversationId) {
      var state = getConversationState(conversationId);
      return { message_id: state.expectedId, frozen: Object.keys(state.frozen) };
    },
    /** (013.5 §E/013.7 §P11) بداية هوية محادثة جديدة: تُصفَّر مرجعية النطاق. */
    resetScope: function (conversationId, messageId) {
      var state = getConversationState(conversationId);
      state.live = null;
      state.activeId = "";
      state.frozen = {};
      state.expectedId = messageId || "";
    },
  };
})();
