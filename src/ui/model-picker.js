/* Agentic Engineering System — منتقي النماذج (الأمر 008 §7-§11+§35).
 *
 * لا select من نموذجين: قائمة كاملة قابلة للبحث والتمرير والتنقل
 * بلوحة المفاتيح، مع اكتشاف حي (GET /models) يُدمج مع المعلن —
 * «82 models» الحقيقية تظهر كما هي (لا hard-code للرقم). فشل الاكتشاف
 * = رسالة صادقة + إدخال يدوي يظل متاحًا (§9).
 */
(function () {
  "use strict";

  if (!window.Hub) return;
  var Hub = window.Hub;

  var open = null;   // اللوحة المفتوحة حاليًا

  function esc(s) { return Hub.esc(s); }

  function closePicker() {
    if (open) {
      open.panel.remove();
      open.backdrop.remove();
      document.removeEventListener("keydown", open.keyHandler, true);
      open = null;
    }
  }

  /**
   * فتح المنتقي.
   * opts: {
   *   anchor: عنصر الزر,
   *   current: النموذج المختار حاليًا,
   *   provider: {id, name},
   *   configuration: {id, name},
   *   models: القائمة المعلنة (DB),
   *   onPick(model), onManual(model)
   * }
   */
  function openPicker(opts) {
    if (open) closePicker();
    var backdrop = document.createElement("div");
    backdrop.className = "mp-backdrop";
    var panel = document.createElement("div");
    panel.className = "mp-panel";
    panel.dir = "rtl";

    // الرأس: بحث + عداد
    var head = document.createElement("div");
    head.className = "mp-head";
    var search = document.createElement("input");
    search.className = "mp-search";
    search.placeholder = "🔍 ابحث عن نموذج…";
    search.dir = "auto";
    var count = document.createElement("span");
    count.className = "mp-count";
    head.appendChild(search);
    head.appendChild(count);
    panel.appendChild(head);

    var listBox = document.createElement("div");
    listBox.className = "mp-list";
    panel.appendChild(listBox);

    var status = document.createElement("div");
    status.className = "mp-status";
    panel.appendChild(status);

    // الإدخال اليدوي — متاح دائمًا (§9 حتى عند فشل الاكتشاف)
    var manual = document.createElement("div");
    manual.className = "mp-manual";
    var manualInput = document.createElement("input");
    manualInput.className = "mp-input";
    manualInput.placeholder = "أو اكتب اسم نموذج يدويًا";
    manualInput.dir = "ltr";
    var manualBtn = document.createElement("button");
    manualBtn.className = "mp-btn";
    manualBtn.textContent = "استخدام";
    manual.appendChild(manualInput);
    manual.appendChild(manualBtn);
    panel.appendChild(manual);

    document.body.appendChild(backdrop);
    document.body.appendChild(panel);

    var state = {
      items: [],            // {id, source: discovered|declared|default}
      filtered: [],
      cursor: 0,
    };
    var ctx = {
      panel: panel, backdrop: backdrop,
      keyHandler: function (e) {
        if (e.key === "Escape") { e.stopPropagation(); closePicker(); }
        else if (e.key === "ArrowDown") { e.preventDefault(); move(1); }
        else if (e.key === "ArrowUp") { e.preventDefault(); move(-1); }
        else if (e.key === "Enter" && state.filtered.length) {
          e.preventDefault();
          pick(state.filtered[state.cursor].id);
        }
      },
    };
    open = ctx;

    // التموضع قرب الزر
    var rect = opts.anchor.getBoundingClientRect();
    var width = Math.min(360, window.innerWidth - 24);
    panel.style.width = width + "px";
    var top = Math.min(rect.bottom + 6, window.innerHeight - 380);
    var left = Math.max(12, Math.min(
      rect.left, window.innerWidth - width - 12));
    if (getComputedStyle(document.documentElement).direction === "rtl") {
      left = Math.max(12, Math.min(rect.right - width, window.innerWidth - width - 12));
    }
    panel.style.top = Math.max(8, top) + "px";
    panel.style.left = left + "px";

    function normalize(models, source) {
      var seen = {};
      var out = [];
      (models || []).forEach(function (m) {
        if (!m || seen[m]) return;
        seen[m] = 1;
        out.push({ id: m, source: source });
      });
      return out;
    }

    function allIds() {
      var declared = normalize(opts.models, "declared");
      if (opts.current && !declared.some(function (x) { return x.id === opts.current; })) {
        declared.unshift({ id: opts.current, source: "current" });
      }
      return declared;
    }

    function render() {
      var q = search.value.trim().toLowerCase();
      state.filtered = state.items.filter(function (item) {
        return !q || item.id.toLowerCase().indexOf(q) !== -1;
      });
      state.cursor = Math.max(0, Math.min(state.cursor,
        Math.max(0, state.filtered.length - 1)));
      count.textContent = state.filtered.length
        ? state.filtered.length + " نموذج" : "";
      listBox.textContent = "";
      state.filtered.forEach(function (item, i) {
        var row = document.createElement("button");
        row.className = "mp-item" +
          (item.id === opts.current ? " current" : "") +
          (i === state.cursor ? " cursor" : "");
        row.type = "button";
        var name = document.createElement("span");
        name.className = "mp-model";
        name.dir = "ltr";
        name.textContent = item.id;
        row.appendChild(name);
        var tag = document.createElement("span");
        tag.className = "mp-tag " + item.source;
        tag.textContent = item.source === "discovered"
          ? "مكتشف" : item.source === "current" ? "الحالي"
          : item.id === opts.current ? "مختار" : "معلن";
        row.appendChild(tag);
        row.addEventListener("click", function () { pick(item.id); });
        row.addEventListener("mousemove", function () {
          if (state.cursor !== i) {
            state.cursor = i;
            paintCursor();
          }
        });
        listBox.appendChild(row);
      });
      if (!state.filtered.length) {
        var empty = document.createElement("div");
        empty.className = "mp-empty";
        empty.textContent = q ? "لا مطابقات للبحث" : "لا نماذج بعد";
        listBox.appendChild(empty);
      }
    }

    function paintCursor() {
      listBox.querySelectorAll(".mp-item").forEach(function (node, i) {
        node.classList.toggle("cursor", i === state.cursor);
      });
      var active = listBox.querySelectorAll(".mp-item")[state.cursor];
      if (active && active.scrollIntoView) active.scrollIntoView({ block: "nearest" });
    }

    function move(delta) {
      if (!state.filtered.length) return;
      state.cursor = (state.cursor + delta + state.filtered.length)
        % state.filtered.length;
      paintCursor();
    }

    function pick(model) {
      closePicker();
      if (opts.onPick) opts.onPick(model);
    }

    function manualPick() {
      var value = manualInput.value.trim();
      if (!value) return;
      closePicker();
      if (opts.onManual) opts.onManual(value);
      else if (opts.onPick) opts.onPick(value);
    }

    search.addEventListener("input", function () { state.cursor = 0; render(); });
    manualBtn.addEventListener("click", manualPick);
    manualInput.addEventListener("keydown", function (e) {
      if (e.key === "Enter") { e.preventDefault(); manualPick(); }
    });
    backdrop.addEventListener("click", closePicker);

    // الاكتشاف الحي (§9): اجلب القائمة إن دعم المزود GET /models —
    // النتيجة تُدمج (مكتشف + معلن) بلا استبدال.
    state.items = allIds();
    render();
    search.focus();

    if (opts.configuration && opts.configuration.id) {
      status.textContent = "…جلب قائمة النماذج الحية";
      Hub.fetchJSON("/api/provider-configurations/" + opts.configuration.id +
        "/models?live=1")
        .then(function (out) {
          if (open !== ctx) return;
          if (out.ok && out.j.model_ids) {
            var discovered = normalize(out.j.model_ids, "discovered");
            var known = {};
            state.items.forEach(function (x) { known[x.id] = 1; });
            discovered.forEach(function (x) {
              if (!known[x.id]) { state.items.push(x); known[x.id] = 1; }
              else {
                var found = state.items.filter(function (y) { return y.id === x.id; })[0];
                if (found) found.source = "discovered";
              }
            });
            status.textContent = "اكتشاف حي: " + out.j.model_ids.length + " نموذجًا";
            status.className = "mp-status ok";
          } else {
            status.textContent = "تعذر جلب قائمة النماذج الآن — الإدخال اليدوي متاح";
            status.className = "mp-status bad";
          }
          render();
        }, function () {
          if (open !== ctx) return;
          status.textContent = "تعذر جلب قائمة النماذج الآن — الإدخال اليدوي متاح";
          status.className = "mp-status bad";
        });
    }
  }

  window.ModelPicker = { open: openPicker, close: closePicker };
})();
