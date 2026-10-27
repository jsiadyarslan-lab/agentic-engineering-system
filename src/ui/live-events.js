/* Agentic Engineering System — مدير البث الحي (013 §5).
 * عقد البث الكامل: اتصال تلقائي، إعادة اتصال، Last-Event-ID/replay،
 * بلا تكرار (إسقاط بالمعرف الرتيب)، استرداد الفائت، مصالحة الحالة
 * عند العودة (visibilitychange)، وصحة الاتصال (keepalive من الخادم).
 *
 * الحقيقة من الدائمة (المعرف الرتيب) — الواجهة لا تخمن أبدًا.
 */
(function () {
  "use strict";

  var STATE = { last_id: 0, source: null, backoff: 400, timer: null,
                handlers: [], healthTimer: null, connectedAt: 0,
                connected: false };  // (W1-T02) هل البث متصل فعلًا؟

  function lastEventId() { return STATE.last_id; }

  function onEvent(handler) {
    STATE.handlers.push(handler);
    return function off() {
      STATE.handlers = STATE.handlers.filter(function (h) {
        return h !== handler;
      });
    };
  }

  function dispatch(event) {
    if (!event || typeof event.kind !== "string") return;
    // إسقاط المكرر: المعرف الرتيب حصرًا (لا أحداث مزدوجة أبدًا)
    var id = parseInt(event.id || event.event_id || 0, 10);
    if (id) {
      if (id <= STATE.last_id) return;
      STATE.last_id = id;
    }
    STATE.handlers.forEach(function (h) {
      try { h(event); } catch (e) { /* مستقبِل لا يكسر البث */ }
    });
  }

  function connect() {
    if (STATE.source) return;
    if (typeof EventSource === "undefined") return; // متصفح قديم: الاستطلاع الآمن يبقى
    var url = "/api/projects/events/stream";
    if (STATE.last_id) url += "?after_id=" + STATE.last_id;
    try {
      STATE.source = new EventSource(url);
    } catch (err) { scheduleReconnect(); return; }

    STATE.source.onopen = function () {
      STATE.backoff = 400;
      STATE.connectedAt = Date.now();
      STATE.connected = true;
      document.body.classList.remove("live-disconnected");
    };
    STATE.source.onmessage = function (message) {
      var event;
      try { event = JSON.parse(message.data); }
      catch (err) { return; }
      if (!event || String(event.kind).indexOf("stream.") === 0) return;
      dispatch(event);
    };
    STATE.source.onerror = function () {
      // انقطاع: أعد الاتصال بمهلة متدرجة — الخادم مصدر الحقيقة
      detach();
      document.body.classList.add("live-disconnected");
      scheduleReconnect();
    };
  }

  function detach() {
    STATE.connected = false;
    if (STATE.source) {
      STATE.source.close();
      STATE.source = null;
    }
    if (STATE.timer) { clearTimeout(STATE.timer); STATE.timer = null; }
  }

  function scheduleReconnect() {
    if (STATE.timer) return;
    var wait = Math.min(STATE.backoff, 8000);
    STATE.backoff = Math.min(STATE.backoff * 2, 8000);
    STATE.timer = setTimeout(function () {
      STATE.timer = null;
      connect();
    }, wait);
  }

  /* العودة من الخلفية: الخادم ربما أُعيد أو أرسل أحداثًا كثيرة أثناء
   * الغياب — مصالحة فورية (اللقطة) ثم استئناف البث من آخر معرف. */
  function reconcile() {
    if (STATE.source) return;
    connect();
    if (window.HubProjects && window.HubProjects.reconcile) {
      try { window.HubProjects.reconcile(); } catch (e) { /* لاحقًا */ }
    }
  }

  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "visible") reconcile();
  });
  window.addEventListener("online", reconcile);

  window.LiveEvents = {
    connect: connect,
    onEvent: onEvent,
    lastEventId: lastEventId,
    reconcile: reconcile,
    isConnected: function () { return STATE.connected; },  // (W1-T02)
  };

  connect();
})();
