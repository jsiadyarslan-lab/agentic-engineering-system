/* agent hub v2 — واجهة المحادثة (تأسيس).
 * سقف دائم: <2000 سطر (يُفحص في tests/contracts/test_thinness.py).
 * البث: POST /api/chat/stream يعيد أحداث SSE {token} ثم {done}.
 * الأدوار والشارات: مفردات core/roles — الواجهة تعرضها فقط.
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

  var busy = false;
  var conversationStarted = false;

  // ---------- أدوات ----------
  function scrollDown() {
    scrollEl.scrollTop = scrollEl.scrollHeight;
  }

  function hideWelcome() {
    if (welcomeEl) welcomeEl.style.display = "none";
  }

  function makeMsg(role, content) {
    var meta = ROLE_LABELS[role] || { sym: "·", ar: role };
    var wrap = document.createElement("div");
    wrap.className = "msg " + (role === "user" ? "user" : "role");
    var m = document.createElement("div");
    m.className = "msg-meta";
    var s = document.createElement("span");
    s.className = "sym"; s.textContent = meta.sym;
    var t = document.createElement("span");
    t.className = "who"; t.textContent = meta.ar;
    m.appendChild(s); m.appendChild(t);
    var b = document.createElement("div");
    b.className = "msg-body";
    b.textContent = content || "";
    wrap.appendChild(m); wrap.appendChild(b);
    return { root: wrap, body: b };
  }

  function addUserMessage(text) {
    var msg = makeMsg("user", text);
    messagesEl.appendChild(msg.root);
    scrollDown();
  }

  function addTyping() {
    var msg = makeMsg("coordinator", "");
    msg.body.innerHTML =
      '<span class="typing"><i></i><i></i><i></i></span>';
    messagesEl.appendChild(msg.root);
    scrollDown();
    return msg;
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

  // ---------- البث ----------
  function streamReply(userText) {
    var typing = addTyping();
    var started = false;
    var msg = null;

    fetch("/api/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: userText })
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
              var payload;
              try { payload = JSON.parse(line.slice(5).trim()); }
              catch (e) { return; }
              if (payload.token !== undefined) {
                if (!started) {
                  started = true;
                  typing.root.remove();
                  msg = makeMsg("coordinator", "");
                  msg.body.classList.add("stream-cursor");
                  messagesEl.appendChild(msg.root);
                }
                msg.body.textContent += payload.token;
                scrollDown();
              } else if (payload.done) {
                finish();
              }
            });
            return pump();
          });
        }
        return pump();
      })
      .catch(function (err) {
        typing.root.remove();
        var fallback = makeMsg(
          "coordinator",
          "تعذر البث: " + err.message
        );
        messagesEl.appendChild(fallback.root);
        setBusy(false);
      });

    function finish() {
      if (msg) msg.body.classList.remove("stream-cursor");
      if (!started) typing.root.remove();
      setBusy(false);
      scrollDown();
    }
  }

  function setBusy(state) {
    busy = state;
    sendEl.disabled = state;
    inputEl.disabled = state;
    if (!state) inputEl.focus();
  }

  function send() {
    var text = inputEl.value.trim();
    if (!text || busy) return;
    inputEl.value = "";
    autoGrow();
    hideWelcome();
    markConversation(text.slice(0, 36));
    addUserMessage(text);
    setBusy(true);
    streamReply(text);
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
  inputEl.addEventListener("input", autoGrow);

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
