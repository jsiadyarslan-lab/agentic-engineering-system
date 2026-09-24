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
      '"></span><span>' + Hub.esc(label) + "</span>";
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
        ? '<span class="meta-stream">● streaming</span>'
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
    if (state.live) { state.live.complete({}); setLiveState(conversationId, null, state.activeId, undefined, Object.assign({}, state.frozen, (_obj = {}, _obj[state.activeId] = true, _obj))); }
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
    msg.setStatus("generating", event.text || "🌐 بحث في الويب…");
  };

  H["research.results"] = function (event) {
    var conversationId = event.details && event.details.conversation_id ? event.details.conversation_id : getCurrentConversationId();
    setCurrentConversation(conversationId);
    var msg = ensureLive(event);
    msg.setStatus("generating", event.text || "🌐 نتائج البحث وصلت");
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
      event.text || "🌐 البحث غير متاح — الإجابة بلا ويب");
  };

  H["research.fetched"] = function (event) {
    var conversationId = event.details && event.details.conversation_id ? event.details.conversation_id : getCurrentConversationId();
    setCurrentConversation(conversationId);
    var msg = ensureLive(event);
    msg.setStatus("generating", event.text || "🌐 جُلبت صفحة");
  };

  H["research.fetch_failed"] = function (event) {
    var conversationId = event.details && event.details.conversation_id ? event.details.conversation_id : getCurrentConversationId();
    setCurrentConversation(conversationId);
    var msg = ensureLive(event);
    msg.setStatus("generating", event.text || "🌐 تعذر جلب صفحة");
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
