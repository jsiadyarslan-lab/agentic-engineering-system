/* Agentic Engineering System — محرّك السرد اللحظي (AES-UI-REDESIGN-016 · M1).
 *
 * يحوّل كل حدث مصنع خام إلى جملة عربية بشرية من الحمولة الحقيقية حصرًا:
 * لا نصوص مصطنعة، لا معرّفات قاعدة بيانات مكشوفة في السطر الرئيسي،
 * لا أنواع إنجليزية خام. كل قيمة تقنية (أداة/مسار/نموذج) تُعرض بعزل
 * BiDi (dir=ltr عبر tech()) داخل جملة عربية سليمة — عقد DSH للسرد الحي.
 * العقد الكامل للحدث يبقى متاحًا بالنقر (markJson/data-json) — شفافية كاملة
 * دون تلويث السرد.
 */
(function () {
  "use strict";

  /* ---------- أدوار الوكلاء (هوية AES-UI-REDESIGN-014) ---------- */
  var ROLES = {
    thinker:     { label: "المفكّر",  cls: "role-thinker" },
    planner:     { label: "المخطّط",  cls: "role-planner" },
    implementer: { label: "المنفّذ",   cls: "role-implementer" },
    builder:     { label: "البنّاء",   cls: "role-implementer" },
    reviewer:    { label: "المحكّم",   cls: "role-reviewer" },
    auditor:     { label: "المدقّق",   cls: "role-reviewer" },
    verifier:    { label: "المتحقّق",  cls: "role-reviewer" },
    coordinator: { label: "المنسّق",   cls: "role-coordinator" },
    owner:       { label: "المالك",    cls: "role-coordinator" },
  };

  function roleMeta(r) {
    return ROLES[String(r || "").toLowerCase()] ||
      { label: r ? String(r) : "وكيل", cls: "role-coordinator" };
  }

  /* ---------- قاموس أنواع الأحداث: كل نوع له عنوان عربي ونبرة ---------- */
  var KINDS = {
    PLAN_CREATED:            ["خطة جديدة", ""],
    PLAN_REVISED:            ["خطة منقّحة", ""],
    PLAN_GENERATING:         ["يولّد النموذج مسودة الخطة…", "run"],
    PLANNING_STARTED:        ["بدأت جلسة التخطيط", ""],
    PLAN_APPROVAL_REQUIRED:  ["خطة بانتظار اعتمادك", "warn"],
    PLAN_REVISION_APPROVAL:  ["تنقيحة بانتظار اعتمادك", "warn"],
    PLAN_APPROVED:           ["اعتُمدت الخطة — انطلق التنفيذ", "ok"],
    PHASE_STARTED:           ["بدأت مرحلة", ""],
    PHASE_COMPLETED:         ["اكتملت مرحلة", "ok"],
    STEP_STARTED:            ["بدأت خطوة", ""],
    STEP_COMPLETED:          ["اكتملت خطوة", "ok"],
    EXECUTION_STARTED:       ["بدأ تنفيذ", ""],
    EXECUTION_COMPLETED:     ["اكتمل تنفيذ", "ok"],
    EXECUTION_FAILED:        ["فشل تنفيذ", "fail"],
    EXECUTION_BLOCKED:       ["تنفيذ محجوز", "warn"],
    EXECUTION_OPENED:        ["فُتح مسار تنفيذ جديد", ""],
    ROLE_EXECUTING:          ["دور يعمل", ""],
    TOOL_EXECUTION:          ["أداة", ""],
    MODEL_CALL_STARTED:      ["استدعاء نموذج", "run"],
    MODEL_CALL_PROGRESS:     ["إنتاج جارٍ", "run"],
    MODEL_CALL_COMPLETED:    ["اكتمل استدعاء النموذج", "ok"],
    MODEL_REASONING:         ["تفكير جارٍ", "run"],
    EVIDENCE_CREATED:        ["أدلة جديدة", ""],
    TEST_COMPLETED:          ["انتهى الفحص", ""],
    REVIEW_COMPLETED:        ["حكم المراجعة", ""],
    AUDIT_COMPLETED:         ["اكتمل التدقيق", ""],
    CHECKPOINT_CREATED:      ["نقطة حفظ", ""],
    PREFLIGHT_PASS:          ["نجح فحص التمهيد", "ok"],
    PREFLIGHT_BLOCKED:       ["فحص التمهيد حاجب — التنفيذ موقوف", "fail"],
    ENVIRONMENT_READY:       ["بيئة التنفيذ المعزولة جاهزة", "ok"],
    OWNER_GATE_REQUIRED:     ["قرار بانتظار اعتمادك", "warn"],
    OWNER_GATE_RESOLVED:     ["بوابة المالك حُسمت", "ok"],
    PROJECT_CREATED:         ["سُجّل مشروع جديد في المصنع", ""],
    PROJECT_VERIFIED:        ["اعتُمد المشروع كمتحقَّق منه", "ok"],
    JOB_QUEUED:              ["قُبّطت وظيفة تنفيذ", ""],
    JOB_STARTED:             ["بدأ عامل التنفيذ معالجة الوظيفة", "run"],
    JOB_COMPLETED:           ["اكتملت وظيفة التنفيذ", "ok"],
    JOB_FAILED:              ["فشلت وظيفة التنفيذ", "fail"],
    STAGE_REVIEW:            ["مراجعة مرحلية", ""],
    message_delta:           ["بث حرفي جارٍ", "run"],
    message_completed:       ["اكتملت رسالة الوكيل", "ok"],
    PROVIDER_TEST_STARTED:   ["اختبار مزوّد النموذج بدأ", "run"],
    PROVIDER_TEST_COMPLETED: ["انتهى اختبار المزوّد", ""],
    "router.call.logged":    ["توجيه دور إلى نموذج", ""],
    RECOVERY_ASSESSED:       ["قُيّمت حالة الاسترداد بعد الإقلاع", ""],
    JOB_RECOVERY_ASSESSED:   ["قُيّمت وظيفة المشروع بعد الإقلاع", ""],
  };

  function title(kind) {
    var k = KINDS[String(kind || "")];
    return k ? k[0] : String(kind || "حدث");
  }

  function toneOf(kind) {
    var k = KINDS[String(kind || "")];
    return k ? k[1] : "";
  }

  /* ---------- أدوات: أسماء عربية للأدوات، ومسارات مختصرة ---------- */
  var TOOLS = {
    write_file: "كتابة ملف", read_file: "قراءة ملف", edit_file: "تعديل ملف",
    apply_patch: "تطبيق رقعة", list_dir: "استعراض مجلد", mkdir: "إنشاء مجلد",
    create_dir: "إنشاء مجلد", run_cmd: "تنفيذ أمر", run_command: "تنفيذ أمر",
    shell: "تنفيذ أمر", bash: "تنفيذ أمر", execute: "تنفيذ أمر",
    node: "تشغيل سكربت", python: "تشغيل سكربت", python3: "تشغيل سكربت",
    web_search: "بحث ويب", fetch_url: "جلب رابط", http_get: "جلب رابط",
    git: "عملية git", test: "تشغيل اختبار", run_tests: "تشغيل اختبار",
    grep: "بحث نصي", glob: "بحث أنماط", patch: "تطبيق رقعة",
  };

  function toolLabel(t) {
    return TOOLS[String(t || "").toLowerCase()] || String(t || "أداة");
  }

  /* المسار الحقيقي من حمولة الأداة: إما summary بقاموس بايثون
     ('path': '...') أو نص مباشر — يُختصر إلى موقعه نسبةً لجذر المشروع. */
  function pathFromSummary(s) {
    if (!s) return "";
    var str = String(s);
    var m = str.match(/'path':\s*'([^']+)'/) || str.match(/"path":\s*"([^"]+)"/);
    var p = m ? m[1] : (str.indexOf("/") === 0 || str.indexOf("/") > 0 ? str.split(" ")[0] : str);
    if (!p || p.length > 200) return "";
    p = p.replace(/^\/opt\/agentic-engineering-system\/runtime\/projects\/\d+\/steps\//, "steps/")
         .replace(/^\/opt\/agentic-engineering-system\/runtime\/projects\/\d+\//, "مشروع/")
         .replace(/^\/opt\/agentic-engineering-system\//, "مصنع/");
    var parts = p.split("/");
    if (parts.length > 4) p = parts.slice(0, 2).join("/") + "/…/" + parts.slice(-2).join("/");
    return p;
  }

  function fmtShortDur(ms) {
    var n = Number(ms) || 0;
    if (n < 1000) return n + " مللي";
    if (n < 60000) return (n / 1000).toFixed(1) + "ث";
    return Math.round(n / 60000) + "د";
  }

  /* سرد أداة: فعل + اسم عربي + مدة حقيقية + مسار حقيقي مختصر */
  function toolNarr(p) {
    var phase = String(p.phase || "");
    var verb = phase === "started" ? "يستدعي" :
               phase === "succeeded" ? "نجحت" :
               phase === "failed" ? "فشلت" : "أداة";
    var text = verb + " «" + toolLabel(p.tool) + "»";
    if (phase !== "started" && p.duration_ms) text += " (" + fmtShortDur(p.duration_ms) + ")";
    if (p.error) text += " — خطأ: " + String(p.error).slice(0, 140);
    return { text: text, ltr: pathFromSummary(p.summary) };
  }

  /* ---------- السرد العام لكل عائلة نوع غير مغطاة برسّام مخصص ---------- */
  function stepRef(p) {
    return p && p.step_id != null ? " — الخطوة " + p.step_id : "";
  }

  function narrate(kind, p) {
    p = p || {};
    var k = String(kind || "");
    var chips = [];
    var text = "";

    if (k === "PLAN_CREATED" || k === "PLAN_REVISED") {
      text = (k === "PLAN_CREATED" ? "صاغ المخطّط خطة جديدة" : "نقّح المخطّط الخطة");
      if (p.version != null) text += " — الإصدار " + p.version;
      if (p.phases) text += " بعدد مراحل " + p.phases;
      chips.push("بانتظار اعتماد المالك");
    } else if (k === "PLAN_GENERATING") {
      text = "يولّد النموذج مسودة الخطة الآن…";
    } else if (k === "PLAN_APPROVAL_REQUIRED" || k === "OWNER_GATE_REQUIRED" || k === "PLAN_REVISION_APPROVAL") {
      text = "خطة بانتظار اعتمادك قبل أن يبدأ التنفيذ" + (p.version != null ? " — الإصدار " + p.version : "");
    } else if (k === "PLAN_APPROVED" || k === "OWNER_GATE_RESOLVED") {
      text = "اعتماد المالك صدر — انطلق التنفيذ";
      if (p.decision) chips.push(String(p.decision));
    } else if (k === "PHASE_STARTED" || k === "PHASE_COMPLETED") {
      text = (k === "PHASE_STARTED" ? "بدأت مرحلة" : "اكتملت مرحلة") +
        (p.title ? " «" + p.title + "»" : "") + stepRef(p);
    } else if (k === "JOB_QUEUED") {
      text = p.resumed ? "استُأنفت وظيفة تنفيذ المشروع" : "قُبّطت وظيفة تنفيذ جديدة";
      if (p.note) chips.push(String(p.note).slice(0, 80));
    } else if (k === "JOB_STARTED") {
      text = "بدأ عامل التنفيذ معالجة الوظيفة";
    } else if (k === "JOB_COMPLETED") {
      text = "اكتملت وظيفة التنفيذ بنجاح";
    } else if (k === "JOB_FAILED") {
      text = "فشلت وظيفة التنفيذ";
      if (p.error) chips.push(String(p.error).slice(0, 80));
    } else if (k === "CHECKPOINT_CREATED") {
      text = "حُفظت نقطة استرجاع" + stepRef(p);
    } else if (k === "ENVIRONMENT_READY") {
      text = "بيئة التنفيذ المعزولة جاهزة للعمل";
      if (p.execution_site) chips.push(String(p.execution_site));
    } else if (k === "PREFLIGHT_PASS") {
      text = "نجح فحص التمهيد — الخطوة مؤهلة للتنفيذ" + stepRef(p);
    } else if (k === "PREFLIGHT_BLOCKED") {
      text = "حاجب فحص التمهيد — التنفيذ موقوف" + stepRef(p);
      if (p.reason) chips.push(String(p.reason).slice(0, 80));
    } else if (k === "EXECUTION_OPENED") {
      text = "فُتح مسار تنفيذ جديد" + stepRef(p);
    } else if (k === "STAGE_REVIEW") {
      text = "مراجعة مرحلية" + stepRef(p);
    } else if (k === "message_delta") {
      text = "يستقبل سطرًا جديدًا من الوكيل" + (p.chars ? " (" + p.chars + " حرفًا)" : "");
    } else if (k === "message_completed") {
      text = "اكتملت رسالة الوكيل";
    } else if (k === "PROVIDER_TEST_STARTED") {
      text = "جارٍ اختبار مزوّد نموذج…";
    } else if (k === "PROVIDER_TEST_COMPLETED") {
      var ready = String(p.status || "").indexOf("READY") !== -1;
      text = ready ? "المزوّد جاهز للعمل" : "المزوّد غير صالح: " + String(p.status || "؟");
      if (p.latency_ms) chips.push(fmtShortDur(p.latency_ms));
      if (p.provider) chips.push(String(p.provider));
    } else if (k === "router.call.logged") {
      text = "وجّه الموجّه الدور إلى نموذج";
      if (p.model) chips.push(String(p.model));
    } else if (k === "PROJECT_CREATED") {
      text = "سُجّل مشروع جديد في المصنع";
    } else if (k === "PROJECT_VERIFIED") {
      text = "اعتُمد المشروع كمتحقَّق منه";
    } else {
      return null; /* لا سرد؟ يعرض الرسّام التفاصيل الخام بصدق */
    }
    return { text: text, chips: chips };
  }

  window.Evolution = {
    title: title,
    toneOf: toneOf,
    narrate: narrate,
    toolLabel: toolLabel,
    toolNarr: toolNarr,
    pathFromSummary: pathFromSummary,
    roleMeta: roleMeta,
    fmtShortDur: fmtShortDur,
  };
})();
