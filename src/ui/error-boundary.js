/* Agentic Engineering System — حدود الأخطاء العامة (الأمر 010 §32).
 *
 * فشل JS أو Promise غير المعالج لا يحوّل مساحة العمل صفحة سوداء:
 * شريط خطأ غير معيق أسفل الشاشة — عنوان + معرّف طلب + تفاصيل تقنية
 * قابلة للطي + إعادة تحميل. مساحة العمل تبقى صالحة للاستخدام.
 */
(function () {
  "use strict";

  var bar = document.getElementById("error-boundary");
  if (!bar) return;

  var count = 0;

  function requestId() {
    return "err-" + Date.now().toString(36) +
      "-" + Math.random().toString(36).slice(2, 7);
  }

  function show(kind, message, stack) {
    count += 1;
    var id = requestId();
    bar.hidden = false;
    bar.innerHTML = "";
    var head = document.createElement("div");
    head.className = "eb-head";
    var title = document.createElement("span");
    title.className = "eb-title";
    title.textContent = "⚠ حدث خطأ في الواجهة (" + count + ") — " + kind;
    head.appendChild(title);

    var actions = document.createElement("span");
    actions.className = "eb-actions";
    var reload = document.createElement("button");
    reload.className = "eb-btn";
    reload.textContent = "إعادة تحميل الصفحة";
    reload.addEventListener("click", function () { location.reload(); });
    var dismiss = document.createElement("button");
    dismiss.className = "eb-btn ghost";
    dismiss.textContent = "إخفاء";
    dismiss.addEventListener("click", function () { bar.hidden = true; });
    actions.appendChild(reload);
    actions.appendChild(dismiss);
    head.appendChild(actions);
    bar.appendChild(head);

    var body = document.createElement("div");
    body.className = "eb-body";
    var msg = document.createElement("div");
    msg.className = "eb-msg";
    msg.textContent = String(message).slice(0, 300);
    body.appendChild(msg);
    var rid = document.createElement("div");
    rid.className = "eb-rid";
    rid.setAttribute("dir", "ltr");
    rid.textContent = "Request ID: " + id;
    body.appendChild(rid);

    if (stack) {
      var details = document.createElement("details");
      details.className = "eb-details";
      details.innerHTML = "<summary>التفاصيل التقنية</summary>";
      var pre = document.createElement("pre");
      pre.setAttribute("dir", "ltr");
      pre.textContent = String(stack).slice(0, 4000);
      details.appendChild(pre);
      body.appendChild(details);
    }
    bar.appendChild(body);
  }

  window.addEventListener("error", function (event) {
    show(
      "خطأ JavaScript",
      event.message || "خطأ غير معروف",
      event.error && event.error.stack ? event.error.stack : ""
    );
  });

  window.addEventListener("unhandledrejection", function (event) {
    var reason = event.reason;
    show(
      "Promise غير معالج",
      reason && reason.message ? reason.message : String(reason),
      reason && reason.stack ? reason.stack : ""
    );
  });

  window.ErrorBoundary = {
    report: function (message, stack) {
      show("تقرير داخلي", message, stack || "");
    },
  };
})();
