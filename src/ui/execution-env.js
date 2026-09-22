/* Agentic Engineering System — بيئات التنفيذ (010 §28 + 011 §4+§24-§25).
 *
 * الإعدادات ← بيئات التنفيذ: لوحة «حقيقة المضيف» أولًا (Host Platform
 * منفصل عن Backend منفصل عن Isolation — من runtime الفعلي لا أسماء)،
 * ثم البيئات المسجلة بحالتها الصادقة وأعمدة المضيف/العزل/الشبكة/
 * القدرات، وإضافة بيئة، وتحقق بفحوص حقيقية، وتنفيذ اختباري يثبت
 * المنفذ لا المسبار وحده (§40).
 */
(function () {
  "use strict";

  if (!window.Hub) return;
  var Hub = window.Hub;
  var esc = Hub.esc;

  var STATUS_LABELS = {
    UNKNOWN: "لم تُتحقق بعد", READY: "جاهزة — تحقق حقيقي ناجح",
    NOT_READY: "فحص فاشل — سبب معروف", UNAVAILABLE: "غير متاحة على هذه المنصة",
  };
  var STATUS_CLASSES = { READY: "ok", NOT_READY: "bad", UNAVAILABLE: "bad" };

  function statusBadge(status) {
    return '<span class="env-badge ' + (STATUS_CLASSES[status] || "wait") +
      '">' + (STATUS_LABELS[status] || status) + "</span>";
  }

  function body() { return document.getElementById("exec-env-body"); }
  function addForm() { return document.getElementById("exec-env-add"); }

  function load() {
    var el = body();
    if (!el) return;
    el.innerHTML = '<div class="env-loading">جارٍ تحميل بيئات التنفيذ…</div>';
    Hub.fetchJSON("/api/execution/environments").then(function (out) {
      if (!out.ok) {
        el.innerHTML = '<div class="env-err">تعذر تحميل البيئات — ' +
          esc(out.j && out.j.detail || "") + "</div>";
        return;
      }
      var environments = out.j.environments || [];
      var supported = out.j.supported_backends || [];
      // (011 §24-§25) حقيقة المضيف من runtime — لوحة مستقلة قبل القائمة
      Hub.fetchJSON("/api/execution/host-truth").then(function (ht) {
        render(environments, supported, ht.ok ? ht.j : null);
      }, function () {
        render(environments, supported, null);
      });
    }, function () {
      el.innerHTML = '<div class="env-err">تعذر الوصول للخدمة</div>';
    });
  }

  function hostTruthHtml(ht) {
    if (!ht) return "";
    var compat = !!ht.platform_compatibility_mode;
    var truth = ht.runtime_truth || {};
    return '<div class="host-truth' + (compat ? " compat" : "") + '">' +
      '<div class="ht-title">حقيقة المضيف — من الـruntime الفعلي لا من الأسماء</div>' +
      '<div class="ht-grid">' +
      '<div class="ht-row"><span>المنصة المضيفة</span><b dir="ltr">' +
        esc(ht.host_platform || "؟") + "</b></div>" +
      '<div class="ht-row"><span>التنفيذ المحلي</span><b>' +
        esc(ht.local_execution === "AVAILABLE" ? "متاح (معزول)"
          : "متوافق فقط — بلا عزل، معلن") + "</b></div>" +
      '<div class="ht-row"><span>العزل المحلي</span><b>' +
        esc(ht.isolation === "SANDBOXED" ? "متاح (ركيزة namespaces+seccomp)"
          : "غير متاح على هذه المنصة") + "</b></div>" +
      '<div class="ht-row"><span>Python</span><b dir="ltr">' +
        esc(truth.python || "؟") + "</b></div>" +
      '<div class="ht-row"><span>Git</span><b dir="ltr">' +
        esc(truth.git || "غير مثبت") + "</b></div>" +
      '<div class="ht-row"><span>النواة</span><b dir="ltr">' +
        esc(truth.kernel || "؟") + "</b></div>" +
      '<div class="ht-row"><span>المعالجات/الذاكرة</span><b dir="ltr">' +
        esc((truth.cpu_cores || "؟") + " · " + (truth.memory || "؟")) + "</b></div>" +
      "</div>" +
      '<div class="ht-note">' + esc(ht.compatibility_note || "") + "</div>" +
      (compat
        ? '<div class="ht-cmd">عامل Linux للعزل الصارم: <code dir="ltr">' +
          esc(ht.worker_command || "python scripts/execution_worker.py") +
          "</code></div>"
        : "") +
      "</div>";
  }

  function render(environments, supported, hostTruth) {
    var el = body();
    var html = hostTruthHtml(hostTruth);
    if (!environments.length) {
      html += '<div class="env-empty">لا بيئات مسجلة بعد</div>';
    }
    environments.forEach(function (env) {
      var profile = env.profile || {};
      var caps = (profile.capabilities || []).join("، ");
      html += '<div class="env-card" data-id="' + env.id + '">' +
        '<div class="env-card-head">' +
        '<span class="env-name">' + esc(env.name) + "</span>" +
        statusBadge(env.status) +
        (env.is_default ? '<span class="env-default">افتراضية</span>' : "") +
        (env.compatibility_mode
          ? '<span class="env-compat">وضع متوافق — بلا عزل، معلن</span>' : "") +
        "</div>" +
        '<div class="env-rows">' +
        '<div class="env-row"><span>الخلفية</span><span dir="ltr">' +
        esc(env.backend) + "</span></div>" +
        '<div class="env-row"><span>المضيف</span><span dir="ltr">' +
        esc(env.host_platform || profile.host_platform || "؟") + "</span></div>" +
        '<div class="env-row"><span>النظام</span><span dir="ltr">' +
        esc(profile.os || "؟") + " / " + esc(profile.architecture || "؟") +
        "</span></div>" +
        '<div class="env-row"><span>العزل</span><span>' +
        (env.isolation === "SANDBOXED" ? "معزولة (namespaces+seccomp)"
          : env.isolation === "WORKER_DECLARED" ? "حسب إعلان العامل"
          : env.isolation === "REMOTE" ? "عاملة عن بعد"
          : "بلا عزل — معلنة") + "</span></div>" +
        (env.backend === "REMOTE_WORKER"
          ? '<div class="env-row"><span>العامل</span><span dir="ltr">' +
            esc(env.endpoint) + "</span></div>"
          : "") +
        '<div class="env-row"><span>الشبكة</span><span>' +
        esc(profile.network_policy || "—") + "</span></div>" +
        (caps
          ? '<div class="env-row"><span>القدرات</span><span dir="ltr">' +
            esc(caps) + "</span></div>"
          : "") +
        (env.last_verified_at
          ? '<div class="env-row"><span>آخر تحقق</span><span dir="ltr">' +
            esc(String(env.last_verified_at).replace("T", " ").slice(0, 19)) +
            "</span></div>"
          : "") +
        "</div>";
      if (env.failure_reason) {
        html += '<div class="env-reason">السبب: ' + esc(env.failure_reason) +
          "</div>";
      }
      html += '<div class="env-actions">' +
        '<button class="pv-btn primary env-verify" data-id="' + env.id +
        '">تحقق (فحوص حقيقية)</button>' +
        '<button class="pv-btn env-test" data-id="' + env.id +
        '">تنفيذ اختباري</button>' +
        (!env.is_default
          ? '<button class="pv-btn env-default-btn" data-id="' + env.id +
            '">تعيين افتراضية</button>' : "") +
        (env.name !== "local-linux"
          ? '<button class="pv-btn danger env-delete" data-id="' + env.id +
            '">حذف</button>' : "") +
        "</div>" +
        '<div class="env-result" id="env-result-' + env.id + '" hidden></div>' +
        "</div>";
    });
    el.innerHTML = html;
    wire(environments);
    renderAddForm(supported);
  }

  function renderAddForm(supported) {
    var form = addForm();
    if (!form) return;
    var options = (supported || []).map(function (b) {
      return '<option value="' + esc(b.backend) + '">' + esc(b.backend) +
        " — " + esc(b.description) + "</option>";
    }).join("");
    form.innerHTML =
      '<div class="env-add-head">إضافة بيئة — خيارات مدعومة من الكود فعلًا حصرًا</div>' +
      '<div class="env-add-grid">' +
      '<label>الاسم<input id="env-add-name" placeholder="linux-worker-1"></label>' +
      '<label>الخلفية<select id="env-add-backend">' + options + "</select></label>" +
      '<label>رابط العامل (REMOTE_WORKER فقط)<input id="env-add-endpoint" ' +
      'dir="ltr" placeholder="http://192.168.1.20:8900"></label>' +
      '<label>التوكن (اختياري — يُخزن محليًا ولا يُعاد أبدًا)' +
      '<input id="env-add-token" type="password" dir="ltr" placeholder="سر-مشترك"></label>' +
      '<label class="env-add-check"><input type="checkbox" id="env-add-default"> ' +
      "تعيين افتراضية بعد إضافتها</label>" +
      "</div>" +
      '<div class="env-add-actions">' +
      '<button class="pv-btn primary" id="env-add-submit">إضافة البيئة</button>' +
      '<span class="env-add-hint">العامل: python scripts/execution_worker.py ' +
      "--port 8900 --token سر-مشترك على أي جهاز Linux/WSL2</span>" +
      "</div>" +
      '<div class="env-add-result" id="env-add-result"></div>';
    document.getElementById("env-add-submit").addEventListener("click", submitAdd);
    var backendSel = document.getElementById("env-add-backend");
    backendSel.addEventListener("change", function () {
      var isRemote = backendSel.value === "REMOTE_WORKER";
      document.getElementById("env-add-endpoint").disabled = !isRemote;
      document.getElementById("env-add-token").disabled = !isRemote;
    });
  }

  function submitAdd() {
    var name = document.getElementById("env-add-name").value.trim();
    var backend = document.getElementById("env-add-backend").value;
    var endpoint = document.getElementById("env-add-endpoint").value.trim();
    var token = document.getElementById("env-add-token").value;
    var makeDefault = document.getElementById("env-add-default").checked;
    var result = document.getElementById("env-add-result");
    if (!name) {
      result.textContent = "الاسم مطلوب";
      return;
    }
    result.textContent = "…جارٍ الإضافة";
    Hub.fetchJSON("/api/execution/environments", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: name, backend: backend, endpoint: endpoint,
        token: token, make_default: makeDefault,
      }),
    }).then(function (out) {
      if (!out.ok) {
        result.textContent = out.j && out.j.detail || "فشلت الإضافة";
        return;
      }
      result.textContent = "أُضيفت — جارٍ التحقق الحقيقي…";
      verify(out.j.id, true);
    });
  }

  function wire(environments) {
    var el = body();
    el.querySelectorAll(".env-verify").forEach(function (btn) {
      btn.addEventListener("click", function () {
        verify(parseInt(btn.getAttribute("data-id"), 10), false, btn);
      });
    });
    el.querySelectorAll(".env-test").forEach(function (btn) {
      btn.addEventListener("click", function () {
        testRun(parseInt(btn.getAttribute("data-id"), 10), btn);
      });
    });
    el.querySelectorAll(".env-default-btn").forEach(function (btn) {
      btn.addEventListener("click", function () {
        Hub.fetchJSON("/api/execution/environments/" +
          btn.getAttribute("data-id") + "/default", { method: "POST" })
          .then(function () { load(); });
      });
    });
    el.querySelectorAll(".env-delete").forEach(function (btn) {
      btn.addEventListener("click", function () {
        if (!window.confirm("حذف هذه البيئة؟")) return;
        Hub.fetchJSON("/api/execution/environments/" +
          btn.getAttribute("data-id"), { method: "DELETE" })
          .then(function () { load(); });
      });
    });
  }

  function showResult(id, content) {
    var box = document.getElementById("env-result-" + id);
    if (!box) return;
    box.hidden = false;
    box.innerHTML = content;
  }

  function verify(id, fromAdd, btn) {
    if (btn) { btn.disabled = true; btn.textContent = "…جارٍ التحقق"; }
    Hub.fetchJSON("/api/execution/environments/" + id + "/verify",
      { method: "POST" }).then(function (out) {
      if (btn) { btn.disabled = false; btn.textContent = "تحقق (فحوص حقيقية)"; }
      if (!out.ok) {
        showResult(id, '<div class="env-err">تعذر التحقق — ' +
          esc(out.j && out.j.detail || "") + "</div>");
        return;
      }
      var v = out.j.verify || {};
      var checks = (v.checks || []).map(function (c) {
        return '<div class="env-check ' + (c.ok ? "ok" : "bad") + '">' +
          (c.ok ? "✓" : "✕") + " " + esc(c.name) +
          (c.detail ? ' — <span dir="ltr">' + esc(String(c.detail).slice(0, 80)) + "</span>" : "") +
          "</div>";
      }).join("");
      // (011 §10) سلم جاهزية العامل البعيد: درجات مسماة بالترتيب
      var ladder = (v.checks || []).some(function (c) {
        return c.name === "connectivity" || c.name === "authentication";
      });
      if (ladder) {
        checks = '<div class="env-ladder-note">سلم جاهزية العامل — ' +
          "connectivity ← authentication ← heartbeat ← environment ← " +
          "workspace ← execute ← artifact؛ أي درجة تفشل توقف السلم " +
          "بسببها</div>" + checks;
      }
      var head =
        '<div class="env-verify-head' + (out.j.status === "READY" ? " ok" : "") +
        '">' +
        (out.j.status === "READY"
          ? "✓ البيئة جاهزة — فحوص حقيقية اجتازت"
          : "✕ التحقق فاشل: " + esc(out.j.failure_reason || v.reason || "")) +
        "</div>" + checks;
      // أعد بناء القائمة بالحالة الجديدة ثم أظهر النتيجة في الـDOM الجديد
      load();
      Hub.fetchJSON("/api/execution/environments").then(function () {
        setTimeout(function () { showResult(id, head); }, 200);
      });
    }, function () {
      if (btn) { btn.disabled = false; btn.textContent = "تحقق (فحوص حقيقية)"; }
      showResult(id, '<div class="env-err">تعذر الوصول للخدمة</div>');
    });
  }

  function testRun(id, btn) {
    if (btn) { btn.disabled = true; btn.textContent = "…جارٍ التنفيذ"; }
    Hub.fetchJSON("/api/execution/environments/" + id + "/test-run",
      { method: "POST" }).then(function (out) {
      if (btn) { btn.disabled = false; btn.textContent = "تنفيذ اختباري"; }
      if (!out.ok) {
        showResult(id, '<div class="env-err">تعذر التنفيذ — ' +
          esc(out.j && out.j.detail || "") + "</div>");
        return;
      }
      var pre = document.createElement("pre");
      pre.setAttribute("dir", "ltr");
      pre.textContent = out.j.stdout || out.j.stderr || out.j.detail || "(بلا مخرجات)";
      showResult(id,
        '<div class="env-verify-head">تنفيذ فعلي — exit=' + out.j.exit_code +
        " · " + out.j.duration_ms + "مث</div>");
      var box = document.getElementById("env-result-" + id);
      if (box) box.appendChild(pre);
    });
  }

  window.ExecutionEnv = { load: load };
})();
