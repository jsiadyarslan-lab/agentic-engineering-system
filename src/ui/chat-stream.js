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

  // ---------- إدارة الرسائل الجارية ----------
  var live = null;           // LiveMessage الحالية
  var activeId = "";

  /* (013.5 §E/§F) حارس الرسالة الجارية: عند استئناف بث بعد تحديث
   * الصفحة نعرف **معرّف الرسالة الجارية حصرًا** من الخادم. أي حدث
   * لرسالة أخرى = إعادة بث تاريخية أو تلوث نطاق ← يُسقط، ولا يُبنى
   * له فقاعة. الرسالة المكتملة مجمّدة: لا حدث لاحق يعدّلها. */
  var expectedId = "";
  var frozen = {};

  function messageAllowed(messageId) {
    var id = messageId || "";
    if (id && frozen[id]) return false;          // (§F) ثبات بعد الاكتمال
    if (expectedId && id && id !== expectedId) return false;  // (§E) عزل
    return true;
  }

  function ensureLive(event) {
    var id = event.message_id || "";
    if (!messageAllowed(id)) return null;
    if (live && activeId === id) return live;
    if (live) { live.complete({}); frozen[activeId] = true; live = null; }
    live = new LiveMessage(id);
    activeId = id;
    Hub.insertAtEnd(live.root);
    return live;
  }

  H["message_started"] = function (event) {
    var msg = ensureLive(event);
    if (!msg) return;
    msg.setMeta(event.details || {}, true);
    msg.root.classList.add("streaming");
    msg.setStatus(event.status || "connecting");
  };

  H["chat.status"] = function (event) {
    if (!live && event.message_id) ensureLive(event);
    if (live) live.setStatus(event.status, event.text);
  };

  H["message_delta"] = function (event) {
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
    if (live && (event.message_id === activeId || !event.message_id)) {
      var bubble = live.root;
      var messageId = event.message_id || activeId;
      live.complete(event.details);
      // (§F) الرسالة المكتملة مجمّدة — لا حدث لاحق يستبدل محتواها
      frozen[messageId] = true;
      bubble.setAttribute("data-msg-id", messageId);
      bubble.setAttribute("data-msg-state", "completed");
      live = null;
      activeId = "";
      // (013.4 §26) الشريط يُبنى عند الاكتمال — research.used وصل
      // قبله فالمصادر جاهزة (الترتيب مضمون من الخادم)
      var web = (event.details && event.details.web_used) ||
        (lastSourcesByMessage[messageId] || {}).show;
      if (web) {
        buildWebUsedBar(
          bubble, messageId,
          (lastSourcesByMessage[messageId] || {}).sources || []
        );
      }
    }
    Hub.onChatDone(event);
  };

  H["chat.error"] = function (event) {
    if (live && messageAllowed(event.message_id || activeId)) {
      live.flush(true);
      live.status.hidden = true;
      frozen[activeId] = true;
      if (live.root) {
        live.root.setAttribute("data-msg-state", "failed");
      }
      live = null;
      activeId = "";
    }
    Hub.showErrorCard(event);
    Hub.onChatDone(event);
  };

  // ---------- (013.4 §26+§29) الويب في المحادثة: مؤشر ومصادر ----------
  // research.started/results/unavailable/fetched: سطور حالة حية أثناء
  // البحث — وresearch.used يثبت 🌐 مع مصادر قابلة للفتح بعد الاكتمال.

  var lastSourcesByMessage = {};

  function pendingWebBadge(messageId, show) {
    lastSourcesByMessage[messageId || ""] = lastSourcesByMessage[
      messageId || ""] || { show: show, sources: null };
    lastSourcesByMessage[messageId || ""].show = show;
  }

  H["research.started"] = function (event) {
    var msg = ensureLive(event);
    msg.setStatus("generating", event.text || "🌐 بحث في الويب…");
  };

  H["research.results"] = function (event) {
    var msg = ensureLive(event);
    msg.setStatus("generating", event.text || "🌐 نتائج البحث وصلت");
    lastSourcesByMessage[event.message_id || ""] = {
      show: true,
      sources: ((event.details || {}).results || []).map(function (r) {
        return { title: r.title, url: r.url };
      }),
    };
  };

  H["research.unavailable"] = function (event) {
    var msg = ensureLive(event);
    msg.setStatus("generating",
      event.text || "🌐 البحث غير متاح — الإجابة بلا ويب");
  };

  H["research.fetched"] = function (event) {
    var msg = ensureLive(event);
    msg.setStatus("generating", event.text || "🌐 جُلبت صفحة");
  };

  H["research.fetch_failed"] = function (event) {
    var msg = ensureLive(event);
    msg.setStatus("generating", event.text || "🌐 تعذر جلب صفحة");
  };

  H["research.used"] = function (event) {
    // المصادر النهائية المستخدمة — تُخزن ليبنى عليها الشريط أسفل الرسالة
    lastSourcesByMessage[event.message_id || ""] = {
      show: true,
      sources: ((event.details || {}).sources || []),
    };
    // إن انتهت الرسالة قبل هذا الحدث (سباق الترتيب) — ابنِ الشريط الآن
    var existing = document.querySelector(
      ".web-used-bar[data-msg='" + (event.message_id || "") + "']");
    if (existing) return;
    var lastAssistant = document.querySelector(
      ".messages .bubble.assistant:last-of-type");
    if (lastAssistant && !live) {
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
          expectedId = "";
          return { running: false, resumed_from: null };
        }
        expectedId = out.j.message_id || "";
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
    currentExpectation: function () {
      return { message_id: expectedId, frozen: Object.keys(frozen) };
    },
    /** (013.5 §E) بداية هوية محادثة جديدة: تُصفَّر مرجعية النطاق. */
    resetScope: function (messageId) {
      live = null;
      activeId = "";
      frozen = {};
      expectedId = messageId || "";
    },
  };
})();
