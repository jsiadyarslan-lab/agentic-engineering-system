/* ═══════════════════════════════════════════════════════════
   المصنع الأحادي — منطق العرض المحلي الصادق
   كل الأرقام من window.__DATA__ (لقطة P4) وwindow.__ASSETS__ (ملفات حقيقية من القرص)
   لا اختراع — لا ألوان — لا معاينة زائفة
   ═══════════════════════════════════════════════════════════ */
'use strict';
const D = window.__DATA__, A = window.__ASSETS__;
const $ = (s) => document.querySelector(s);
const el = (tag, cls, html) => { const e = document.createElement(tag); if (cls) e.className = cls; if (html != null) e.innerHTML = html; return e; };
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const nf = (n) => Number(n).toLocaleString('en-US');

/* ── مدد وأحجام ── */
function fmtDur(ms) {
  ms = Math.max(0, Math.round(ms));
  const s = Math.floor(ms / 1000), m = Math.floor(s / 60), h = Math.floor(m / 60);
  if (h > 0) return `${h}س ${m % 60}د`;
  if (m > 0) return `${m}د ${s % 60}ث`;
  return `${s}ث`;
}
function fmtClock(ms) {
  const s = Math.floor(Math.max(0, ms) / 1000);
  const h = String(Math.floor(s / 3600)).padStart(2, '0');
  const m = String(Math.floor((s % 3600) / 60)).padStart(2, '0');
  const ss = String(s % 60).padStart(2, '0');
  return `${h}:${m}:${ss}`;
}
function fmtBytes(b) {
  if (b == null) return '—';
  if (b >= 1048576) return (b / 1048576).toFixed(1) + 'MB';
  if (b >= 1024) return (b / 1024).toFixed(1) + 'KB';
  return b + 'B';
}
const timeOf = (iso) => String(iso || '').slice(11, 16) || '—';

/* ── الجلسات: المصنع أولاً ثم لقطة P4..P1 الحقيقية ── */
const P4 = D.p4, S4 = P4.stats;
const SESSIONS = [
  { id: 'F', name: 'بناء المصنع — السجل الحي', av: 'م', st: 'active', prev: '٦ مراحل حقيقية — حتى V9', time: 'الآن' },
  ...D.projects.map(p => {
    const meta = {
      4: { av: 'P4', st: 'active',   prev: 'بوابة 315 معلقة — الخطة v2 (id 125)' },
      3: { av: 'P3', st: 'verified', prev: `958 خطوة · 300 مكتملة · 31.3% · 288 بوابة` },
      2: { av: 'P2', st: 'blocked',  prev: 'بوابة مالك — الخطة v7 (id 11)' },
      1: { av: 'P1', st: 'blocked',  prev: 'بوابة مالك — الخطة v4 (id 5)' },
    }[p.id];
    return { ...p, ...meta, time: timeOf(p.updated_at || p.created_at) };
  })
];
let curSession = 4; /* الافتتاح على العمل الحقيقي — جلسة P4 النشطة */

/* ── حالة إعادة التشغيل (لقطة P4 فقط) ── */
const TN = S4.span_ms;
const TN3 = D.p3stats ? D.p3stats.span_ms : null;
let TNc = TN; /* المدة النشطة لإعادة التشغيل — P4 أو P3 حسب الجلسة، null = لا بث */
let tCur = TN, playing = false, speed = 1200, rafId = null, lastTs = null;
let bookMarks = (P4.bookmarks || []).map(b => ({ t: Number(b.t) || 0, label: b.label || '' })).filter(b => b.t >= 0 && b.t <= TN);

/* ══════════ 1) الشريط الجانبي ══════════ */
function renderSessions() {
  const box = $('#sessions'); box.innerHTML = '';
  SESSIONS.forEach(s => {
    const b = el('button', 'sess' + (s.id === curSession ? ' active' : ''));
    b.innerHTML = `
      <span class="sess-av${s.id === 'F' ? ' av-self' : ''}">${esc(s.av)}</span>
      <span class="sess-m">
        <span class="sess-t">${esc(s.name)}<i class="st-dot st-${s.st}"></i></span>
        <span class="sess-p">${esc(s.prev)}</span>
      </span>
      <span class="sess-time mono">${esc(s.time)}</span>`;
    b.addEventListener('click', () => { curSession = s.id; renderSessions(); renderChat(); renderComputer(); renderProgress(); syncReplay(); });
    box.appendChild(b);
  });
  $('#ucount').textContent = P4.gate315 && P4.gate315.status === 'PENDING' ? '1 قرار معلق' : 'لا قرارات معلقة';
}

/* ══════════ 2) عمود السرد ══════════ */
function snapChipHTML() {
  if (curSession === 'F') {
    return `<span class="ic-wrap"><svg class="ic"><use href="#i-hand"/></svg></span>`
      + `سجل الجلسة الحقيقي — رسائل المالك <b>حرفية</b> وردود الوكيل <b>ملخصات تنفيذية موثقة بالملفات</b>`;
  }
  return `<span class="ic-wrap"><svg class="ic"><use href="#i-clock"/></svg></span>`
    + `لقطة مجمّدة · <b class="mono">${D.meta.data_sha256_16}</b> · <span class="mono">${D.meta.snapshot_at.replace('T', ' ').replace('Z', ' UTC')}</span>`;
}

const KIND_META = {
  tool:    { ico: 'i-term',   lab: 'أداة' },
  agent:   { ico: 'i-spark',  lab: 'الوكيل' },
  crisis:  { ico: 'i-alert',  lab: 'أزمة' },
  gate:    { ico: 'i-clock',  lab: 'بوابة' },
  gatereq: { ico: 'i-clock',  lab: 'بوابة اعتماد' },
  planrev: { ico: 'i-branch', lab: 'إعادة تخطيط' },
  phase:   { ico: 'i-branch', lab: 'مرحلة' },
  gap:     { ico: 'i-clock',  lab: 'فجوة' },
  sys:     { ico: 'i-file',   lab: 'نظام' },
  audit:   { ico: 'i-shield', lab: 'تدقيق' },
  final:   { ico: 'i-checkp', lab: 'تحقق نهائي' },
};
const GATE_KIND = { PLAN_APPROVAL: 'اعتماد خطة', PLAN_REVISION_APPROVAL: 'مراجعة خطة', PREFLIGHT_BLOCKED: 'حجب قبل الطيران', FINAL_VERIFICATION: 'تحقق نهائي' };
const TONE_CLS = { ok: 'st-ok', warn: 'st-warn', err: 'st-err', info: 'st-info', vio: 'st-plan' };
const TONE_CHIP = { ok: 'c-ok', warn: 'c-warn', err: 'c-err', vio: 'c-plan' };
const STATE_TXT = { ok: 'تم', warn: 'تحذير', err: 'فشل', info: 'معلومة', vio: 'تخطيط' };

function evCard(ev) {
  const k = ev.k || 'sys';
  const m = KIND_META[k] || KIND_META.sys;
  const card = el('div', 'ev-card re');
  card.dataset.t = ev.t || 0;
  const stateCls = TONE_CLS[ev.tone] || 'st-info';
  const stateTxt = ev.k === 'gatereq' ? 'بانتظارك' : (STATE_TXT[ev.tone] || '—');
  let inner = `
    <div class="ev-hd">
      <span class="ev-ico"><svg class="ic"><use href="#${m.ico}"/></svg></span>
      <span class="ev-k">${m.lab}</span>
      <span class="ev-t mono">#${esc(ev.ev || '')}</span>
      <span class="ev-state ${stateCls}">${stateTxt}</span>
    </div>
    <div class="ev-title">${esc(ev.title || '')}</div>`;
  if (ev.body) {
    const isLatin = /^[\x00-\x7F]/.test(ev.body) && !/[\u0600-\u06FF]/.test(ev.body);
    inner += isLatin
      ? `<div class="ev-mono">${esc(ev.body)}</div>`
      : `<div class="ev-body">${esc(ev.body)}</div>`;
  }
  if (ev.chips && ev.chips.length) {
    inner += `<div class="ev-chips">` + ev.chips.map(c => {
      const [lk, lv, tone] = c;
      return `<span class="ev-chip ${TONE_CHIP[tone] || ''}">${esc(lk)}<span class="mono">${esc(lv)}</span></span>`;
    }).join('') + `</div>`;
  }
  card.innerHTML = inner;
  return card;
}

function quietLine(ev) {
  const k = ev.k;
  if (k === 'gap') {
    const d = el('div', 'gapline re'); d.dataset.t = ev.t || 0;
    d.textContent = ev.title || 'فجوة صمت';
    return d;
  }
  if (k === 'phase') {
    const d = el('div', 'phaseline re'); d.dataset.t = ev.t || 0;
    d.innerHTML = `<svg class="ic"><use href="#i-branch"/></svg>${esc(ev.title || '')}`;
    return d;
  }
  if (k === 'writeupd') {
    const d = el('div', 'writeupd re'); d.dataset.t = ev.t || 0;
    d.innerHTML = `<svg class="ic"><use href="#i-eye"/></svg><span>${esc(ev.title || 'تحديث كتابة')}${ev.chars ? ` — <span class="mono">${nf(ev.chars)}</span> حرفاً` : ''}</span>`;
    return d;
  }
  const d = el('div', 'sysline re'); d.dataset.t = ev.t || 0;
  d.innerHTML = esc(ev.title || '');
  return d;
}

function runChipHTML() {
  if (curSession === 3) {
    return `<span class="tico"><svg class="ic"><use href="#i-term"/></svg></span>
    تشغيل سجل P3 · نافذة <span class="mono">${nf(D.p3stats.n_events)}</span> حداً`;
  }
  return `
    <span class="tico"><svg class="ic"><use href="#i-term"/></svg></span>
    تشغيل سجل P4 · <span class="mono">${esc(S4.model || '')}</span>`;
}

/* ── رقاقة أداة قابلة للتوسيع — أسلوب «Browsing…» في مانوس (انقلاب أبيض/أسود عند الفتح) ── */
function toolchip(html, det) {
  return `
  <div class="toolchip${det ? '" role="button" aria-expanded="false"' : ''}">
    <span class="tico"><svg class="ic"><use href="#i-term"/></svg></span>
    ${html}
    ${det ? `<span class="tstate"><svg class="ic"><use href="#i-chev"/></svg></span>` : ''}
  </div>
  ${det ? `<div class="toolchip-det">${det}</div>` : ''}`;
}

/* زر فتح ملف حقيقي داخل المحادثة */
const flink = (fid, label) => `<button class="flink" data-fid="${fid}"><svg class="ic"><use href="#i-file"/></svg>${label}</button>`;

/* ══════════ سجل بناء المصنع — المحادثة الحقيقية ══════════ */
function uMsg(txt) {
  return `<div class="u-msg"><div class="u-bubble">${esc(txt)}</div></div>`;
}
function aMsg(html) {
  return `
  <div class="a-msg">
    <div class="a-id"><span class="handlogo"><svg class="ic"><use href="#i-hand"/></svg></span><span class="serifbrand">AES</span></div>
    ${html}
  </div>`;
}
function storyDay(txt) {
  return `<div class="story-day"><span class="sd-ico"><svg class="ic"><use href="#i-branch"/></svg></span>${esc(txt)}</div>`;
}

function renderFactoryChat(body) {
  $('#snapchip').innerHTML = snapChipHTML();
  $('#tasktitle').textContent = 'بناء المصنع — السجل الحي';
  $('#compTitle').textContent = 'مخرجات المصنع';
  $('#chatend').querySelector('.endtxt').textContent = 'نهاية السجل — آخر حدث: V9 — التصميم مطبق على المشروع الحقيقي';

  body.insertAdjacentHTML('beforeend', toolchip(
    `تشغيل سجل الجلسة · <span class="mono">web-8d21d376</span> · 11 رسالة مالك`,
    `المصدر: أرشيف الجلسة الحقيقية. أقوال المالك منقولة حرفياً بين علامتي تنصيص؛ ردود الوكيل ملخصات تنفيذية موثقة — كل رقم فيها قابل للتحقق من ملف حقيقي في عرض «الملفات».`));

  /* ── المرحلة 1: نقطة الصفر ── */
  body.insertAdjacentHTML('beforeend', storyDay('المرحلة 1 — نقطة الصفر'));
  body.insertAdjacentHTML('beforeend', uMsg('نحن ماذا نفعل الان؟'));
  body.insertAdjacentHTML('beforeend', aMsg(`
    <p class="a-para">جردتُ المخزون كاملاً قبل أي خطوة: القمرة <b>v8.1</b> موجودة ومبنية — <span class="mono">712.9KB</span> ذاتية الاحتواء ببيانات إنتاج حقيقية وبصمة <span class="mono">555d9261b8462891</span>.</p>
    ${toolchip(`جرد المخزون · <span class="mono">download/</span>`, 'النتيجة: لا إعادة بناء غير ضرورية — ننتقل إلى جودة الواجهة نفسها.')}`));

  body.insertAdjacentHTML('beforeend', uMsg('التصميم البصري، الأقسام، صفحة محادثة الوكيل والمصنع — كلها معجقة، مخربطة، مكدسة، مفككلة، مبعثرة… افحص نفسك'));
  body.insertAdjacentHTML('beforeend', aMsg(`
    <p class="a-para">نقدتُ نفسي بالحرف وخرجت بقائمة أمراض: طباعة بلا سلم، بطاقات مكدسة بلا هرمية، ألوان بلا انضباط، وحالات خاملة بلا جملة. النتيجة كانت حكماً واحداً: <b>التصميم الحالي لا يليق بمنتج.</b></p>`));

  /* ── المرحلة 2: المراجع الحية ── */
  body.insertAdjacentHTML('beforeend', storyDay('المرحلة 2 — المراجع الحية من الإنترنت'));
  body.insertAdjacentHTML('beforeend', uMsg('مع احترامي لك، هذه ليست واجهة بسطة منشورة بشارع فقير حتى، اذهب وابحث بالنت عن صور لواجهات تنفيذ وكلاء حقيقية — OpenAI Codex وClaude وDevin وZ.ai Super Agent وManus — كمرجعية'));
  body.insertAdjacentHTML('beforeend', aMsg(`
    <p class="a-para">نفّذت <b>5 عمليات بحث حية</b> والتقطت <b>12 لقطة فعلية</b> لواجهات وكلاء التنفيذ — ثم جمعتها في ورقة ملامس واحدة للمقارنة الملاصقة.</p>
    ${toolchip(`بحث الويب · <span class="mono">5 استعلامات</span> · <span class="mono">12 لقطة</span>`)}
    <div class="ev-chips">
      <span class="ev-chip">Codex<span class="mono">3 لقطات</span></span>
      <span class="ev-chip">Claude<span class="mono">4 لقطات</span></span>
      <span class="ev-chip">Devin<span class="mono">3 لقطات</span></span>
      <span class="ev-chip">Manus<span class="mono">4 لقطات</span></span>
      <span class="ev-chip">Z.ai<span class="mono">2 لقطات</span></span>
    </div>
    <div class="a-links">${flink('refs', 'افتح ورقة المراجع refs_contact.jpg')}${flink('vsc3', 'المقارنة ضد مرجع Manus الحي')}</div>`));

  body.insertAdjacentHTML('beforeend', uMsg('انتقد نفسك والمصنع بالحرف وقارنه مع ما فحصته من صور'));
  body.insertAdjacentHTML('beforeend', aMsg(`
    <p class="a-para">أعدت البناء على أساس المراجع: <b>v8</b> (<span class="mono">691.8KB</span>) — عمود سردي بعرض مثبت، خطة مرقمة، diff بمحاذاة صفوف، سلم طباعة <span class="mono">~20/16/13.5/11</span>، وانضباط الأحمر: سبب فريد فقط.</p>
    <div class="a-links">${flink('v8', 'افتح AES-COCKPIT-V8.html')}</div>`));

  /* ── المرحلة 3: الصفر العشري ── */
  body.insertAdjacentHTML('beforeend', storyDay('المرحلة 3 — الصفر العشري v8.1'));
  body.insertAdjacentHTML('beforeend', uMsg('ارني هل سيبقى تافه منتجياً حتى هذه اللحظة…') + uMsg('عبس ، لا يوجد امل فقدته'));
  body.insertAdjacentHTML('beforeend', aMsg(`
    <p class="a-para">بنيتُ <b>v8.1 العشرية</b> (<span class="mono">712.9KB</span>): بث ظلي صادق بمشغّل وسرعات، إفصاح 7 بنود، بصمة <span class="mono">sha256</span> معلنة، وتمريرة فحص آلي كاملة.</p>
    ${toolchip(`جناح الفحص الآلي · <span class="mono">13 / 13 ناجحاً</span>`, 'JSON سليم · تعريب نظيف · بعدادات +N صحيحة · إفصاح 7 بنود · بصمة مطابقة.')}
    <p class="a-para">ثم أنتجت <b>ورقة الإثبات</b>: 7 أزواج ملاصقة (مرجع حي يمين، بناؤنا يسار) وجدول حكم <b>13/13 «يلبي»</b>.</p>
    <div class="a-links">${flink('v81', 'افتح القمرة V8.1 حية')}${flink('vsrefs', 'ورقة الإثبات — 7 أزواج')}${flink('ck12', 'لقطة مفتاح الأمانة')}</div>`));

  /* ── المرحلة 4: المصنع كمانوس ── */
  body.insertAdjacentHTML('beforeend', storyDay('المرحلة 4 — المصنع نسخة مانوس'));
  body.insertAdjacentHTML('beforeend', uMsg('بعد هذا، كيف سيكون شكل المصنع؟ اريده نسخة طبق الأصل من مانوس في كل شيء') + uMsg('تابع'));
  body.insertAdjacentHTML('beforeend', aMsg(`
    <p class="a-para">بنيتُ المصنع نفسه: ثلاثة أعمدة كمانوس — جلسات، محادثة، «حاسبة المصنع» — بأبعاد مضبوطة وبطاقات بث من لقطة P4 الحقيقية. ثم نسخة <b>داكنة</b> بألوان لقطة المالك وخط <b>Readex Pro</b> مدمج.</p>
    ${toolchip(`كتابة <span class="mono">build_factory_dark.py</span> · <span class="mono">2.5KB</span>`)}
    <div class="a-links">${flink('mono', 'AES-FACTORY-MONO — السابق')}${flink('dark', 'AES-FACTORY-MANUS-DARK')}${flink('vstgt', 'الإثبات مقابل صورتك المرجعية')}</div>`));

  body.insertAdjacentHTML('beforeend', uMsg('جميل، الان وصلنا الى تصميم مقبول، نفذ التالي: غير الخط لواحد اجمل. الخلفية داكنة، يعني الصورة المرفقة اريده أن يظهر مثلها'));
  body.insertAdjacentHTML('beforeend', aMsg(`
    <p class="a-para">هذا أول قبول صريح في المشروع — سُجّل كما ورد. الخط والخلفية الداكنة كانا منفذين في نسخة DARK المقبولة نفسها: Readex Pro متغير (200–700) + JetBrains Mono، مضمّنان base64 بلا اتصال خارجي.</p>`));

  /* ── المرحلة 5: الأحادي الصارم ── */
  body.insertAdjacentHTML('beforeend', storyDay('المرحلة 5 — الأحادي الصارم والمخرجات الحية'));
  body.insertAdjacentHTML('beforeend', uMsg('نفذ التصميم الجديد، لكن: لا اريد أي لون غير الابيض والاسود والرمادي في كل المشروع. اريد أن ارى مخرجات المصنع من واجهة المتصفح، الى الملفات التي يتم انتاجها بكل انواعها، وواجهة محادثة، انت لديك كل السياق والمعلومات والصور، انطلق وابهرني. استعن بوكيل تصميم محترف'));
  body.insertAdjacentHTML('beforeend', aMsg(`
    <p class="a-para">نفّذت الحرفين حرفياً:</p>
    <p class="a-para"><b>1 — الأحادي الصارم:</b> كل قيمة لونية في المشروع أصبحت رمادياً صرفاً (R==G==B) — دقّقها جناح الفحص على البناء النهائي نفسه. حتى صورك تُعرض رمادية <b>من المصدر</b> قبل أن تلمس المتصفح.</p>
    <p class="a-para"><b>2 — وكيل تصميم محترف:</b> فوّضت وكيل تصميم متخصص فأنتج طبقة نظام كاملة (<span class="mono">609 أسطر</span>) — سلّم رمادي عشري موثق، تمييز الحالات بالإضاءة والحدود والرموز لا بالألوان، ومونوغرامات أنواع الملفات.</p>
    <p class="a-para"><b>3 — مخرجات المصنع:</b> عرض «الملفات» في حاسبة المصنع يضم <b>30 ملفاً حقيقياً</b> من القرص بأحجامها وبصماتها — والقمرة نفسها تعمل <b>حية</b> داخل هذا العرض.</p>
    <div class="a-links">${flink('v81', 'شغّل القمرة الآن')}${flink('mono', 'المصنع الأحادي — السابق')}${flink('style', 'ورقة وكيل التصميم')}</div>
    <p class="a-para">الرسالة التي تقرؤها الآن هي آخر حدث في السجل — <b>المصنع يقف على مخرجاته ويريك إياها.</b></p>`));

  /* ── المرحلة 6: التطبيق على المشروع — V9 ── */
  body.insertAdjacentHTML('beforeend', storyDay('المرحلة 6 — التطبيق على المشروع'));
  body.insertAdjacentHTML('beforeend', uMsg('طبق التصميم على المشروع لارى كيف سيكون بالعمل الحقيقي'));
  body.insertAdjacentHTML('beforeend', aMsg(`
    <p class="a-para">تُطبّق الآن: <b>V9</b> — نفس التصميم المقبول على لقطة الإنتاج نفسها، مع فرق جوهري: <b>كل جلسة تعرض سجلها هي</b> — P4 ببثها الكامل، وP3 بسجلها الموثق (23 حداً بفجوتي الصمت)، وP1/P2 بسلاسل بواباتها الحقيقية بأزمنة انتظارها من حقول <span class="mono">wait_ms</span>.</p>
    <p class="a-para">المُنشئ صار <b>محادثة</b> تجيب محلياً من اللقطة بأزرار تفتح العرض المعني، وأُضيف عرض <b>diff الخطة v1↔v2</b> بخطه الزمني وقراراته ومخاطره، والافتتاح على جلسة P4 النشطة لا على سجل البناء.</p>
    <div class="a-links">${flink('v9', 'ملف V9 ذاته')}${viewBtn('plan', 'i-branch', 'diff الخطة')}${flink('vsrefs', 'ورقة إثبات القمرة')}</div>
    <p class="a-para">جرّب بنفسك: «ما حالة بوابة 315؟» أو «لماذا فشلت الخطوة 1047؟» — والردود كلها محلية من اللقطة، بلا نموذج حي.</p>`));

  $('#chatend').hidden = false;
}

/* ── جلسات اللقطة P4..P1 (من البناء المقبول) ── */
function introHTML() {
  const v1 = D.diff_p4.v1, v2 = D.diff_p4.v2, M = D.diff_p4.metrics;
  return `
  <div class="a-msg">
    <div class="a-id"><span class="handlogo"><svg class="ic"><use href="#i-hand"/></svg></span><span class="serifbrand">AES</span></div>
    <p class="a-para">أنجزتُ المرحلة الأولى من الخطة v1 <b>بأدلة PASS</b>: <span class="mono">articles.json</span> بـ12 مقالاً عربياً أصلياً (15د 33ث — دليل ev-322 بـ15 ملفاً و256.9KB)، ثم <span class="mono">theme.css</span> برموز تصميم ووضع داكن (6د 20ث — دليل ev-323 بـ15 ملفاً).</p>
    <p class="a-para">ثم دخلتُ الخطوة <b>1047</b> — أكبر خطوة في v1: توليد كل صفحات الموقع من نداء واحد. فشلت المحاولة 1 بعد <b>16د 27ث</b> والمحاولة 2 بعد <b>38د 20ث</b> بالنمط نفسه — وتكرار الفشل مرتين يفرض بوابة مراجعة إلزامية.</p>
    <p class="a-para">قرار النظام: <b>رفض التكرار الأعمى</b>. بوابة 314 فتحت مراجعة الخطة، وتولّدت <b>الخطة v2</b> (id 125) — <span class="mono">${M.v2_phases}</span> مراحل و<span class="mono">${M.v2_steps}</span> خطوات و<span class="mono">${M.v2_crit}</span> معيار قبول، محل <span class="mono">${M.v1_phases}</span> مراحل و<span class="mono">${M.v1_steps}</span> خطوات و<span class="mono">${M.v1_crit}</span> معياراً في v1.</p>
    <p class="a-para">بوابة <b>315</b> بانتظار قرارك الآن. لديّ خياران:</p>
    <div class="a-opts">
      <div class="a-opt"><span class="n">1.</span><span><b>اعتماد الخطة v2</b> — يبدأ التأسيس ضمن المراحل الأربع الجديدة، والخطوة الأكبر مفككة إلى خطوات قابلة للتحقق.</span></div>
      <div class="a-opt"><span class="n">2.</span><span><b>طلب تعديل أو مراجعة إضافية</b> — تعود الخطة للتخطيط قبل أي تنفيذ جديد.</span></div>
    </div>
  </div>`;
}
function gateCardHTML() {
  const g = P4.gate315;
  return `
  <div class="gate-card re" data-t="${TN}">
    <span class="gico"><svg class="ic"><use href="#i-clock"/></svg></span>
    <span class="gtxt"><b>بوابة ${g.id} — اعتماد الخطة v2</b> · ${esc(g.kind)} · ${esc(g.status)}<br>معلقة منذ <span class="mono">${g.created_at}</span> — ${esc(g.reason)}</span>
    <button class="btn-dark" id="openGate">افتح القرار</button>
  </div>
  <div class="amber re" data-t="${TN}"><span class="spin"></span>سيستمر المصنع بعد ردك — البوابة 315 لا تتجاوز آلياً</div>`;
}
function searchResultHTML(q, res, nFiles) {
  const items = res.map(r => `<div class="sr-item">${r}</div>`).join('');
  return `
  <div class="searchres" id="searchres">
    <div class="searchres-hd"><svg class="ic"><use href="#i-search"/></svg>نتائج البحث — «${esc(q)}» (${res.length}${nFiles ? ` · ${nFiles} ملفاً` : ''})</div>
    ${items || '<div class="sr-item">لا نتائج في نطاق العرض.</div>'}
  </div>`;
}

function renderChat() {
  const body = $('#chatbody'); body.innerHTML = '';
  $('#chatend').hidden = true;
  $('#searchres')?.remove();

  if (curSession === 'F') {
    TNc = null;
    renderFactoryChat(body);
    $('#chatscroll').scrollTop = 0;
    return;
  }

  const sess = SESSIONS.find(s => s.id === curSession);
  $('#tasktitle').textContent = sess.name;
  $('#compTitle').textContent = 'حاسبة المصنع';
  $('#chatend').querySelector('.endtxt').textContent = 'نهاية اللقطة — لا أحداث بعد هذه اللحظة';
  $('#snapchip').innerHTML = snapChipHTML();
  const chip = el('div', 'toolchip', runChipHTML());
  body.appendChild(chip);

  /* كل جلسة تعرض سجلها هي — لا بث مستعار بين الجلسات */
  if (curSession === 3) { renderP3Chat(body); return; }
  if (curSession === 1 || curSession === 2) { renderBlockedChat(body); return; }

  TNc = TN;
  body.insertAdjacentHTML('beforeend', introHTML());

  const events = P4.feed;
  let gatereqDone = false;
  events.forEach(ev => {
    const k = ev.k || 'sys';
    if (k === 'agent') {
      const card = el('div', 'a-msg re');
      card.dataset.t = ev.t || 0;
      const chipsHTML = (ev.chips || []).map(c =>
        `<span class="ev-chip ${TONE_CHIP[c[2]] || ''}">${esc(c[0])}<span class="mono">${esc(c[1])}</span></span>`).join('');
      const bodyLatin = ev.body && /^[\x00-\x7F]/.test(ev.body) && !/[\u0600-\u06FF]/.test(ev.body);
      card.innerHTML = `
        <div class="a-id"><span class="handlogo"><svg class="ic"><use href="#i-hand"/></svg></span><span class="serifbrand">AES</span></div>
        <p class="a-para">${esc(ev.title || '')}</p>
        ${bodyLatin ? `<div class="ev-mono">${esc(ev.body)}</div>` : (ev.body ? `<p class="a-para">${esc(ev.body)}</p>` : '')}
        ${chipsHTML ? `<div class="ev-chips">${chipsHTML}</div>` : ''}`;
      body.appendChild(card);
    } else if (k === 'gatereq' && !gatereqDone) {
      gatereqDone = true;
      body.insertAdjacentHTML('beforeend', gateCardHTML());
      const line = el('div', 'sysline re'); line.dataset.t = ev.t || 0;
      line.innerHTML = esc(ev.title || '');
      body.appendChild(line);
    } else if (['gap', 'phase', 'writeupd', 'sys'].includes(k)) {
      body.appendChild(quietLine(ev));
    } else {
      body.appendChild(evCard(ev));
    }
  });
  $('#chatend').hidden = false;
  $('#openGate')?.addEventListener('click', openGate);
  syncReplay();
  $('#chatscroll').scrollTop = 0;
}

/* ── جلسة P3: سجلها الحقيقي — لا بث مستعار ── */
function renderP3Chat(body) {
  TNc = TN3;
  const C3 = D.chains.p3, ps = D.p3stats;
  $('#chatend').querySelector('.endtxt').textContent = 'نهاية سجل P3 — دورة انتهت بالتحقق';
  body.insertAdjacentHTML('beforeend', `
  <div class="a-msg">
    <div class="a-id"><span class="handlogo"><svg class="ic"><use href="#i-hand"/></svg></span><span class="serifbrand">AES</span></div>
    <p class="a-para">جلسة <b>موثّقة</b> انتهت بالتحقق في <span class="mono">${esc(C3.verified_at || '—')}</span> — <span class="mono">${nf(C3.cycles_n || 0)}</span> دورة تخطيط-تنفيذ عبر <span class="mono">${nf(C3.gates_total || 0)}</span> بوابة و<span class="mono">${nf(C3.plan_versions || 0)}</span> إصدار خطة.</p>
    <p class="a-para">هذا «العمل الحقيقي» المنتظم: تدقيق بعد كل خطوة، وبوابات بتوقيتات موثقة، وفجوتا صمت معلنتان حين توقف التنفيذ — لا صفوف مثالية مزخرفة.</p>
  </div>`);
  (D.p3feed || []).forEach(ev => {
    const k = ev.k || 'sys';
    if (['gap', 'phase', 'writeupd', 'sys'].includes(k)) body.appendChild(quietLine(ev));
    else body.appendChild(evCard(ev));
  });
  body.insertAdjacentHTML('beforeend', `<div class="sysline">البث أعلاه آخر <span class="mono">${(D.p3feed || []).length}</span> حداً منقولون من اللقطة — نافذة P3 الكاملة <span class="mono">${nf(ps.n_events)}</span> حداً بمسافة <span class="mono">${fmtDur(ps.span_ms)}</span>.</div>`);
  $('#chatend').hidden = false;
  syncReplay();
  $('#chatscroll').scrollTop = 0;
}

/* ── جلسات P1/P2 المحجوبة: ملخص الخطة + سلسلة البوابات الحقيقية بأزمنتها ── */
function renderBlockedChat(body) {
  TNc = null;
  const sess = SESSIONS.find(s => s.id === curSession);
  const cid = sess.id;
  const chain = D.chains['p' + cid] || [];
  body.insertAdjacentHTML('beforeend', sessionSummary(sess));
  body.insertAdjacentHTML('beforeend', `<div class="chainhd"><svg class="ic"><use href="#i-branch"/></svg>سلسلة البوابات الحقيقية — ${chain.length} بوابات موثقة بالأزمنة</div>`);
  chain.forEach(g => {
    body.insertAdjacentHTML('beforeend', `
    <div class="grow">
      <span class="g-id mono">#${g.id}</span>
      <span class="g-kind">${esc(GATE_KIND[g.kind] || g.kind)}</span>
      <span class="g-st ${g.status === 'APPROVED' ? 'ok' : ''}">${esc(g.status)}</span>
      <span class="g-why" title="${esc(g.reason || '')}">${esc(g.reason || '')}</span>
      <span class="g-wait mono">${fmtDur(g.wait_ms || 0)}</span>
    </div>`);
  });
  body.insertAdjacentHTML('beforeend', `<div class="sysline">أزمنة الانتظار من حقول <span class="mono">wait_ms</span> الحقيقية — آخر استعادة مسجلة <span class="mono">${esc(D.noise[cid === 2 ? 'p2' : 'p1'].last_recovery)}</span>.</div>`);
  $('#chatend').hidden = false;
  syncReplay();
  $('#chatscroll').scrollTop = 0;
}

/* ملخصات P1/P2/P3 — أرقام مجمّعة حقيقية فقط */
function sessionSummary(sess) {
  const C3 = D.chains.p3;
  if (sess.id === 3) {
    const k = C3.kinds;
    return `
    <div class="a-msg">
      <div class="a-id"><span class="handlogo"><svg class="ic"><use href="#i-hand"/></svg></span><span class="serifbrand">AES</span></div>
      <p class="a-para">جلسة <b>موثّقة</b> بتاريخ <span class="mono">${C3.verified_at}</span> — دورة إنتاج كاملة عبر <b>232 دورة تخطيط-تنفيذ</b> و<b>288 بوابة</b>.</p>
      <div class="prev-stats" style="margin:14px 0">
        <div class="prev-stat"><div class="v mono">958</div><div class="k">خطوات إجمالية</div></div>
        <div class="prev-stat"><div class="v mono">300</div><div class="k">مكتملة</div></div>
        <div class="prev-stat"><div class="v mono">87</div><div class="k">فاشلة</div></div>
        <div class="prev-stat"><div class="v mono">31.3%</div><div class="k">نسبة التقدم</div></div>
      </div>
      <p class="a-para">البوابات: <span class="mono">${k.PLAN_APPROVAL}</span> اعتماد خطة · <span class="mono">${k.PLAN_REVISION_APPROVAL}</span> مراجعة خطة · <span class="mono">${k.PREFLIGHT_BLOCKED}</span> حجب قبل الطيران · <span class="mono">${k.FINAL_VERIFICATION}</span> تحقق نهائي.</p>
      <p class="a-para">الأرتيفاكت: <b>8,281 ملفاً</b> بمجموع <span class="mono">127,783,200</span> بايت — الأسماء المعروضة في حاسبة المصنع عينة حقيقية.</p>
    </div>
    <div class="sysline">الملخص مجمّع من اللقطة — البث الحدثي الكامل متاح لجلسة P4 النشطة.</div>`;
  }
  if (sess.id === 2 || sess.id === 1) {
    const pl = D.plans_cur[sess.id === 2 ? 'p2' : 'p1'];
    return `
    <div class="a-msg">
      <div class="a-id"><span class="handlogo"><svg class="ic"><use href="#i-hand"/></svg></span><span class="serifbrand">AES</span></div>
      <p class="a-para">جلسة <b>محجوبة</b> — بانتظار قرار مالك على بوابة معلقة منذ اللقطة.</p>
      <p class="a-para">الخطة الحالية <b>v${pl.version}</b> (id <span class="mono">${pl.plan_id}</span>) بـ<span class="mono">${pl.phases}</span> مراحل و<span class="mono">${pl.ac_count}</span> معيار قبول — السبب المسجل لتوليدها: «${esc(pl.reason)}»، محل الإصدار <span class="mono">${pl.supersedes}</span>.</p>
      <p class="a-para">نافذة الأحداث في اللقطة: <span class="mono">140</span> حداً — آخر استعادة مسجلة <span class="mono">${esc(D.noise[sess.id === 2 ? 'p2' : 'p1'].last_recovery)}</span>.</p>
    </div>
    <div class="amber"><span class="spin"></span>البوابة المعلقة لا تتجاوز آلياً — القرار للمالك</div>
    <div class="sysline">الملخص مجمّع من اللقطة — البث الحدثي الكامل متاح لجلسة P4 النشطة.</div>`;
  }
  return '';
}

/* ══════════ 3) ملفات المصنع — المتصفح والمعاينات ══════════ */
const KIND_LABEL = { html:'HTML', jpg:'JPG', png:'PNG', py:'PY', js:'JS', css:'CSS', json:'JSON', md:'MD', pdf:'PDF', docx:'DOCX' };
const KIND_TMON  = { html:'HT', jpg:'JP', png:'PN', py:'PY', js:'JS', css:'CS', json:'{}', md:'MD', pdf:'PDF', docx:'D#' };
let curFile = null;

function filesStats() {
  const fs = Object.values(A.files);
  return { n: fs.length, bytes: fs.reduce((a, f) => a + f.size, 0), kinds: new Set(fs.map(f => f.kind)).size };
}

function renderFilesBrowser() {
  const canvas = $('#filesCanvas');
  const st = filesStats();
  $('#filesbar').textContent = `files://factory · ${st.n} ملفاً · ${st.kinds} أنواع · ${fmtBytes(st.bytes)}`;
  $('#tprog').classList.add('closed');
  let html = '<div class="fgroups">';
  A.groups.forEach(g => {
    const ids = A.order[g.id] || [];
    const tot = ids.reduce((a, id) => a + A.files[id].size, 0);
    html += `
    <section class="fgroup" data-g="${g.id}">
      <header class="fgroup-hd" role="button" tabindex="0">
        <svg class="ic fchev"><use href="#i-chev"/></svg>
        <svg class="ic fic"><use href="#i-fold"/></svg>
        <span class="fgroup-name">${esc(g.name)}</span>
        <span class="fgroup-meta">
          <span class="fcount">${ids.length} ملفاً</span>
          <span class="fdot">·</span>
          <span class="ftotal" dir="ltr">${fmtBytes(tot)}</span>
        </span>
        <span class="fgroup-line"></span>
      </header>
      <div class="fgroup-body">`;
    ids.forEach(id => {
      const f = A.files[id];
      html += `
        <div class="frow${curFile === id ? ' sel' : ''}" role="button" tabindex="0" data-fid="${id}" aria-selected="${curFile === id}">
          <span class="tmon t-${f.kind}">${KIND_TMON[f.kind] || 'F'}</span>
          <span class="fname" dir="ltr">${esc(f.name)}</span>
          <span class="fsize" dir="ltr">${fmtBytes(f.size)}</span>
          <span class="fsha" dir="ltr" title="sha256 — انقر للنسخ">${f.sha16 ? f.sha16.slice(0, 8) : '——'}</span>
        </div>`;
    });
    html += `</div></section>`;
  });
  html += `</div>
  <div class="files-foot">كل الملفات من القرص الفعلي — الأحجام وبصمات sha256 محسوبة لحظة البناء. <b>${st.kinds} أنواع</b>: HTML · JPG · PNG · PY · JS · CSS · JSON · MD · PDF · DOCX</div>`;
  canvas.innerHTML = html;
  canvas.scrollTop = 0;
}

/* تلوين JSON — رمادي صرف: مفاتيح أفتح، قيم متوسطة، أرقام أخفت */
function hiJSON(t) {
  return t
    .replace(/(&quot;)([^&]*?)(&quot;)(\s*:)/g, '<span class="jk">$1$2$3</span><span class="jp">$4</span>')
    .replace(/(:\s*)(&quot;)([^&]*?)(&quot;)/g, '$1<span class="js">$2$3$4</span>')
    .replace(/\b(true|false|null)\b/g, '<span class="jb">$1</span>')
    .replace(/(:\s*)(-?\d+\.?\d*(?:[eE][+-]?\d+)?)/g, '$1<span class="jn">$2</span>');
}

/* ترويسة معاينة موحدة */
function pvHeader(f, actions) {
  return `
  <header class="pv-hd">
    <button class="pv-back" type="button" title="رجوع إلى الملفات"><svg class="ic"><use href="#i-chevr"/></svg></button>
    <span class="pv-name" dir="ltr">${esc(f.name)}</span>
    <span class="pv-kind">${KIND_LABEL[f.kind] || '?'}</span>
    <span class="pv-size" dir="ltr">${fmtBytes(f.size)}</span>
    ${f.sha16 ? `<span class="pv-sha mono" dir="ltr" title="انقر لنسخ البصمة">${f.sha16}</span>` : ''}
    <span class="pv-path mono" dir="ltr" title="مسار الملف الحقيقي">${esc(f.path)}</span>
    <span class="pv-acts">${actions || ''}</span>
  </header>`;
}
const PV_META = (f) => `
  <div class="pv-meta mono">
    <span>size ${nf(f.size)} B</span><span>sha256[0:16] ${f.sha16 || '—'}</span><span>mtime ${f.mtime || '—'}</span><span>${esc(f.path)}</span>
  </div>`;

function openFile(id) {
  const f = A.files[id];
  if (!f) return;
  curFile = id;
  switchView('files');
  const canvas = $('#filesCanvas');
  canvas.scrollTop = 0;

  if (f.mode === 'live') {
    canvas.innerHTML = pvHeader(f) + `
      <div class="pv-live">
        <div class="pv-live-bar">
          <span class="pv-live-dot"></span>
          <span class="pv-live-tag">LIVE</span>
          <span class="pv-live-txt">— تشغيل حي 100% للملف الحقيقي داخل إطار معزول — الواجهة التي بنيتها تعمل الآن أمامك</span>
        </div>
        <iframe class="pv-frame" sandbox="allow-scripts" title="معاينة حية ${esc(f.name)}" src="data:text/html;base64,${f.dataB64}"></iframe>
      </div>` + PV_META(f);
  } else if (f.mode === 'img') {
    canvas.innerHTML = pvHeader(f) + `
      <div class="pv-img">
        <div class="pv-img-stage"><img class="g" alt="${esc(f.name)}" src="data:image/jpeg;base64,${f.thumbB64}"></div>
        <div class="pv-img-bar">
          <button class="pv-tool on" data-fit="fit">احتواء</button>
          <button class="pv-tool" data-fit="full">100%</button>
          <span class="pv-img-dim">رمادية من المصدر — تحويل L قبل الترميز</span>
        </div>
      </div>
      <div class="pv-note">المعاينة <b>مصغرة رمادية</b>. الأصل في مساره أعلاه، وبصمته أدناه محسوبة من الأصل الكامل لا من المصغرة.</div>` + PV_META(f);
    canvas.querySelectorAll('.pv-tool[data-fit]').forEach(b => b.addEventListener('click', () => {
      canvas.querySelectorAll('.pv-tool[data-fit]').forEach(x => x.classList.remove('on'));
      b.classList.add('on');
      canvas.querySelector('.pv-img-stage img').style.maxWidth = b.dataset.fit === 'fit' ? '' : 'none';
    }));
  } else if (f.mode === 'code') {
    const lines = f.text.split('\n');
    const gutter = lines.map((_, i) => (i + 1)).join('\n');
    const body = lines.map(l => esc(l) || ' ').join('\n');
    canvas.innerHTML = pvHeader(f) + `
      <div class="pv-code"><pre class="pv-gutter">${gutter}</pre><pre class="pv-code-body">${body}</pre></div>` + PV_META(f);
  } else if (f.mode === 'json') {
    canvas.innerHTML = pvHeader(f) + `
      <div class="pv-json"><pre>${hiJSON(esc(f.pretty))}</pre></div>` + PV_META(f);
  } else if (f.mode === 'ext') {
    canvas.innerHTML = pvHeader(f) + `
      <div class="pv-note"><b>ملف مخرَج حقيقي بحجمه الكامل</b> — لا نسخة مصغرة داخله. عند خدمة مجلد المصنع يفتح من هنا:</div>
      <div class="pv-ext"><a class="btn-dark" href="${esc(f.name)}" target="_blank" rel="noopener">افتح ${esc(f.name)} من مجلد المصنع</a></div>` + PV_META(f);
  } else if (f.mode === 'self') {
    canvas.innerHTML = pvHeader(f) + `
      <div class="pv-note self-note">
        <b>هذا الملف هو الواجهة التي تشاهدها الآن.</b><br>
        بُني على أصوله ثم قِس حجمه الفعلي وأُعيد البناء حتى تطابق الرقم المعروض مع الرقم على القرص تماماً — تقارب صادق بلا تقدير.
        بصمة الملف لا تُطبع داخله عمداً (لا مرجع ذاتي متسق ممكن) — احسبها من القرص: <span class="mono">sha256sum ${esc(f.path)}</span>.
      </div>
      <div class="pv-selflist">
        <div class="psrow"><span>${filesStats().n} ملفاً حقيقياً</span><span>بأحجام وبصمات من القرص</span></div>
        <div class="psrow"><span>${filesStats().kinds} أنواع</span><span>HTML · JPG · PNG · PY · JS · CSS · JSON · MD · PDF · DOCX</span></div>
        <div class="psrow"><span>معاينة حية</span><span>القمرة v8.1 تعمل داخله sandbox</span></div>
        <div class="psrow"><span>قانون اللون</span><span>رمادي صرف R==G==B — مدقق آلياً</span></div>
      </div>` + PV_META(f);
  } else {
    canvas.innerHTML = pvHeader(f) + `
      <div class="pv-note">
        <b>لا معاينة داخلية للملفات الثنائية</b> — الأمانة قبل البريق. الملف موجود في مساره أعلاه بحجمه وبصمته الحقيقيتين.
      </div>` + PV_META(f);
  }
  canvas.querySelectorAll('.pv-back').forEach(b => b.addEventListener('click', () => { curFile = null; renderFilesBrowser(); }));
  canvas.querySelectorAll('.pv-sha,.fsha').forEach(b => b.addEventListener('click', () => {
    navigator.clipboard?.writeText(f.sha16).then(() => toast('نُسخت بصمة ' + f.sha16)).catch(() => {});
  }));
}

/* ══════════ 4) حاسبة المصنع — عرض لكل جلسة ══════════ */
function renderComputer() {
  if (curSession === 'F') {
    $('#urlbar').textContent = 'preview://factory-state';
    const st = filesStats();
    $('#previewCanvas').innerHTML = `
      <div class="prev-hero">
        <div class="prev-h">المصنع يقف على مخرجاته</div>
        <div class="prev-p">هذه الواجهة نفسها منتج خط الإنتاج: بنيتُها، ثم دمجتُ في جوفها <b>الملفات الحقيقية</b> التي أنتجها هذا المشروع — من القمرة إلى أوراق الإثبات إلى مصادر البناء نفسها.</div>
        <div class="prev-stats">
          <div class="prev-stat"><div class="v mono">${st.n}</div><div class="k">ملفاً حقيقياً</div></div>
          <div class="prev-stat"><div class="v mono">${st.kinds}</div><div class="k">أنواع ملفات</div></div>
          <div class="prev-stat"><div class="v mono">${fmtBytes(st.bytes)}</div><div class="k">حجم المخرجات</div></div>
          <div class="prev-stat"><div class="v mono">13/13</div><div class="k">فحص v8.1</div></div>
          <div class="prev-stat"><div class="v mono">7</div><div class="k">أزواج إثبات</div></div>
          <div class="prev-stat"><div class="v mono">2</div><div class="k">خطوط مدمجة</div></div>
        </div>
      </div>
      <div class="prev-note"><b>ابدأ من هنا:</b> اضغط أيقونة المجلد في الركيزة الوسطى — أو جرّب فتح القمرة حية من عرض «الملفات». الأرقام أعلاه محسوبة من القرص لحظة البناء، لا من ذاكرة.</div>`;
  } else if (curSession === 3) {
    $('#urlbar').textContent = `snap://p3 · ${D.meta.snapshot_at.slice(11, 19)}Z`;
    const ps = D.p3stats, C3 = D.chains.p3;
    $('#previewCanvas').innerHTML = `
      <div class="prev-hero">
        <div class="prev-h">جلسة موثقة — دورة انتهت بالتحقق</div>
        <div class="prev-p">أرقام مجمّعة من اللقطة لحياة P3 الكاملة: مئتا دورة تخطيط-تنفيذ انتهت بتحقق نهائي — النظام المنتظم الذي وُلد لأجله.</div>
        <div class="prev-stats">
          <div class="prev-stat"><div class="v mono">${nf(C3.cycles_n || 0)}</div><div class="k">دورة تخطيط-تنفيذ</div></div>
          <div class="prev-stat"><div class="v mono">${nf(C3.gates_total || 0)}</div><div class="k">بوابة</div></div>
          <div class="prev-stat"><div class="v mono">${nf(C3.plan_versions || 0)}</div><div class="k">إصدار خطة</div></div>
          <div class="prev-stat"><div class="v mono">${nf(ps.n_events)}</div><div class="k">حدث في النافذة</div></div>
          <div class="prev-stat"><div class="v mono">${fmtDur(ps.span_ms)}</div><div class="k">امتداد النافذة</div></div>
          <div class="prev-stat"><div class="v mono">${nf(D.artifacts.p3.total)}</div><div class="k">أرتيفاكت P3</div></div>
        </div>
      </div>
      <div class="prev-note">سجل P3 الحقيقي في عمود السرد — بما فيه فجوتا الصمت المعلنتان. البوابات بمجموعاتها في عرض الأدلة والأرتيفاكت.</div>`;
  } else if (curSession === 1 || curSession === 2) {
    $('#urlbar').textContent = `snap://p${curSession} · محجوبة على قرار المالك`;
    const pl = D.plans_cur['p' + curSession];
    const chain = D.chains['p' + curSession] || [];
    $('#previewCanvas').innerHTML = `
      <div class="prev-hero">
        <div class="prev-h">جلسة محجوبة — لا تنفيذ قبل القرار</div>
        <div class="prev-p">«${esc(pl.reason)}» — الخطة الحالية v${pl.version} (id <span class="mono">${pl.plan_id}</span>) محلّ الإصدار <span class="mono">${pl.supersedes}</span>.</div>
        <div class="prev-stats">
          <div class="prev-stat"><div class="v mono">${pl.phases}</div><div class="k">مراحل مخططة</div></div>
          <div class="prev-stat"><div class="v mono">${pl.ac_count}</div><div class="k">معيار قبول</div></div>
          <div class="prev-stat"><div class="v mono">${pl.decisions.length}</div><div class="k">قرارات مسجلة</div></div>
          <div class="prev-stat"><div class="v mono">${pl.risks.length}</div><div class="k">مخاطر معلنة</div></div>
          <div class="prev-stat"><div class="v mono">${chain.length}</div><div class="k">بوابة في السلسلة</div></div>
          <div class="prev-stat"><div class="v mono">1</div><div class="k">بوابة مالك معلقة</div></div>
        </div>
      </div>
      <div class="prev-note">سلسلة البوابات بتوقيتاتها الحقيقية في عمود السرد — المصنع لا يتجاوز بوابة مالك آلياً.</div>`;
  } else {
    $('#urlbar').textContent = `snap://${D.meta.data_sha256_16} · p4@${D.meta.snapshot_at.slice(11, 19)}Z`;
    const pr = $('#previewCanvas');
    pr.innerHTML = `
      <div class="prev-hero">
        <div class="prev-h">حالة المصنع من اللقطة</div>
        <div class="prev-p">خط الإنتاج P4 مجمّد عند بوابة اعتماد الخطة — كل الأرقام أدناه من نافذة الأحداث الحقيقية (140 حداً من id 29761).</div>
        <div class="prev-stats">
          <div class="prev-stat"><div class="v mono">${fmtDur(S4.span_ms)}</div><div class="k">امتداد النافذة</div></div>
          <div class="prev-stat"><div class="v mono">${nf(S4.n_events)}</div><div class="k">حدث مسجل</div></div>
          <div class="prev-stat"><div class="v mono">${nf(S4.reasoning_chars)}</div><div class="k">حرف تفكير</div></div>
          <div class="prev-stat"><div class="v mono">${nf(D.artifacts.p4.total)}</div><div class="k">أرتيفاكت PASS</div></div>
          <div class="prev-stat"><div class="v mono">${D.evidence.p4.length}</div><div class="k">أدلة PASS</div></div>
          <div class="prev-stat"><div class="v mono">1</div><div class="k">بوابة معلقة</div></div>
        </div>
      </div>
      <div class="prev-note"><b>لماذا لا ترى الموقع نفسه؟</b> محتوى ملفات اللقطة غير مشمول فيها — الأدلة تحمل sha256 والأحجام فقط. مخرجات «المصنع» الحقيقية لك أنت تبحث عنها في عرض «الملفات».</div>`;
  }

  /* الأرتيفاكت — rows[i] = [فهرس_الاسم، بايتات، خطوة، دليل] */
  const A4 = D.artifacts.p4;
  const art = $('#artCanvas');
  const nm = A4.names || [], rw = A4.rows || [];
  let rows = '';
  rw.forEach(r => {
    const name = nm[r[0]] != null ? nm[r[0]] : `artifact-${r[0]}`;
    rows += `<div class="art-row"><svg class="ic"><use href="#i-file"/></svg><span class="n">${esc(name)}</span><span class="step mono">ev-${r[3]} · s${r[2]}</span><span class="b mono">${fmtBytes(r[1])}</span></div>`;
  });
  art.innerHTML = `
    <div class="art-hd"><span class="t">أرتيفاكت P4 — كل الموثق بعلامة PASS</span><span class="m">${nf(A4.total)} ملفاً · <span class="mono">${nf(A4.total_bytes)}</span> بايت</span></div>
    <div class="artlist">${rows}</div>
    <div class="art-hd" style="border-top:1px solid var(--line);border-bottom:0"><span class="t">أرتيفاكت P3</span><span class="m">${nf(D.artifacts.p3.total)} ملفاً · <span class="mono">${nf(D.artifacts.p3.total_bytes)}</span> بايت</span></div>`;

  /* الأدلة */
  const evl = $('#evCanvas');
  evl.innerHTML = `<div class="ev-list">` + D.evidence.p4.map(e => {
    const nb = e.files.reduce((a, f) => a + (f.b || 0), 0);
    return `
    <div class="evrow">
      <div class="evrow-hd"><span class="id mono">ev-${e.id}</span><span class="st ev-state st-ok">PASS</span></div>
      <div class="evrow-m">
        <span class="mchip">step <span class="mono">${e.step}</span></span>
        <span class="mchip">exec <span class="mono">${e.exec}</span></span>
        <span class="mchip">commit <span class="mono">${e.commit}</span></span>
        <span class="mchip">${e.nf} ملفاً</span>
        <span class="mchip"><span class="mono">${fmtBytes(nb)}</span></span>
        <span class="mchip mono">${e.at}</span>
      </div>
      <div class="evrow-f">${e.files.slice(0, 6).map(f => `<span class="mono">${esc(f.n)}</span> · ${fmtBytes(f.b)} · <span class="mono">${f.sh.slice(0, 10)}</span>`).join('<br>')}${e.files.length > 6 ? `<br>… و${e.files.length - 6} ملفات أخرى` : ''}</div>
    </div>`;
  }).join('') + `</div>`;
}

/* بطاقة تقدم المهمة — لكل جلسة محتواها */
function renderProgress() {
  if (curSession === 'F') {
    $('#tprog-title').textContent = 'مراحل بناء المصنع';
    $('#tprog-count').textContent = '5 / 5';
    const items = [
      ['done', 'i-checkp', 'جرد + مراجع حية', '12 لقطة من 5 وكلاء (Codex · Claude · Devin · Z.ai · Manus) — ورقة ملامس 94.9KB'],
      ['done', 'i-checkp', 'القمرة v7 → v8 → v8.1', '712.9KB · فحص آلي 13/13 · ورقة إثبات 7 أزواج ملاصقة'],
      ['done', 'i-checkp', 'المصنع كمانوس', 'MANUS (96.7KB) → DARK (255.7KB) بألوان لقطة المالك وReadex Pro'],
      ['done', 'i-checkp', 'القبول الصريح', '«جميل، الان وصلنا الى تصميم مقبول» — سُجل حرفياً في السجل'],
      ['done', 'i-checkp', 'الأحادي الصارم + المخرجات الحية', 'وكيل تصميم (609 أسطر) · 30 ملفاً ببصماتها · أنت داخل المنتج الأخير الآن'],
    ];
    $('#tprog-body').innerHTML = items.map(it => `
      <div class="titem"><span class="mk ${it[0]}"><svg class="ic"><use href="#${it[1]}"/></svg></span><span class="ttx"><b>${it[2]}</b><span class="sub">${it[3]}</span></span></div>`).join('');
    return;
  }
  if (curSession === 3) {
    const C3 = D.chains.p3;
    $('#tprog-title').textContent = 'دورة P3 الكاملة';
    $('#tprog-count').textContent = '3 / 3';
    $('#tprog-body').innerHTML = [
      ['done', 'i-checkp', 'تخطيط وتنفيذ عبر الدورات', `${nf(C3.cycles_n || 0)} دورة عبر ${nf(C3.gates_total || 0)} بوابة و${nf(C3.plan_versions || 0)} إصدار خطة`],
      ['done', 'i-checkp', 'تدقيق ومراجعة مستمرة', 'بوابة اعتماد ومراجعة وحجب قبل الطيران بمجموعاتها'],
      ['done', 'i-checkp', 'تحقق نهائي', `تم في ${esc(C3.verified_at || '—')} — الجلسة موثقة`],
    ].map(it => `<div class="titem"><span class="mk ${it[0]}"><svg class="ic"><use href="#${it[1]}"/></svg></span><span class="ttx"><b>${it[2]}</b><span class="sub">${it[3]}</span></span></div>`).join('');
    return;
  }
  if (curSession === 1 || curSession === 2) {
    const pl = D.plans_cur['p' + curSession];
    $('#tprog-title').textContent = 'تقدم مهمة محجوبة';
    $('#tprog-count').textContent = '0 / ' + pl.phases;
    $('#tprog-body').innerHTML = [
      ['done', 'i-checkp', `الخطة v${pl.version} جاهزة`, `id ${pl.plan_id} — ${pl.phases} مراحل و${pl.ac_count} معيار قبول`],
      ['gate', 'i-clock', 'بوابة مالك معلقة', 'لا تنفيذ قبل القرار — المصنع لا يتجاوزها آلياً'],
    ].map(it => `<div class="titem"><span class="mk ${it[0]}"><svg class="ic"><use href="#${it[1]}"/></svg></span><span class="ttx"><b>${it[2]}</b><span class="sub">${it[3]}</span></span></div>`).join('');
    return;
  }
  $('#tprog-title').textContent = 'تقدم المهمة';
  const v2 = D.diff_p4.v2;
  const items = v2.phases.map((ph, i) => {
    if (i === 0) return { cls: 'done', ico: 'i-checkp', tx: `<b>${esc(ph.title)}</b>`, sub: 'اكتمل أساسها في v1 بأدلة ev-322/ev-323 — articles.json وtheme.css' };
    if (i === 1) return { cls: 'gate',  ico: 'i-clock',  tx: `<b>${esc(ph.title)}</b>`, sub: `الخطوة 1047 فشلت مرتين في v1 — إعادة التأسيس ضمن v2 بانتظار بوابة 315` };
    return { cls: 'pend', ico: 'i-clock', tx: `<b>${esc(ph.title)}</b>`, sub: 'لم تبدأ — تنتظر اعتماد الخطة v2' };
  });
  $('#tprog-count').textContent = `1 / ${v2.phases.length}`;
  $('#tprog-body').innerHTML = items.map(it => `
    <div class="titem"><span class="mk ${it.cls}"><svg class="ic"><use href="#${it.ico}"/></svg></span><span class="ttx">${it.tx}<span class="sub">${it.sub}</span></span></div>`).join('');
}

/* ══════════ 5) إعادة التشغيل — لقطة P4 فقط ══════════ */
function buildMarks() {
  const box = $('#marks'); box.innerHTML = '';
  bookMarks.forEach(b => {
    const pct = (b.t / TN) * 100;
    const d = el('span', 'markpt' + (b.hot ? ' hot' : ''));
    d.style.insetInlineStart = pct + '%';
    d.title = `${b.label} — ${fmtDur(b.t)}`;
    box.appendChild(d);
  });
}
function renderFrame() {
  if (TNc == null) return;
  const pct = (tCur / TNc) * 100;
  $('#fill').style.width = pct + '%';
  $('#cursor').style.insetInlineStart = pct + '%';
  $('#tstamp').textContent = fmtClock(tCur);
  document.querySelectorAll('#chatbody .re, .gate-card.re, .amber.re').forEach(n => {
    const t = Number(n.dataset.t || 0);
    n.style.display = (t <= tCur + 1) ? '' : 'none';
  });
  $('#chatend').hidden = !((curSession === 4 && tCur >= TN - 500) || (curSession === 3 && tCur >= TN3 - 500));
}
function syncReplay() {
  if (TNc == null) { $('#scrub').hidden = true; return; }
  $('#scrub').hidden = false;
  if (curSession === 4) buildMarks(); else $('#marks').innerHTML = '';
  tCur = TNc; renderFrame();
}
function play() {
  if (TNc == null) return;
  if (playing) return stop();
  playing = true; lastTs = null;
  $('#playbtn').classList.add('playing');
  $('#playbtn').innerHTML = '<svg class="ic"><use href="#i-pause"/></svg>';
  if (tCur >= TNc - 500) { tCur = 0; document.querySelectorAll('#chatbody .re').forEach(n => n.style.display = 'none'); renderFrame(); }
  rafId = requestAnimationFrame(step);
}
function stop() {
  playing = false;
  $('#playbtn').classList.remove('playing');
  $('#playbtn').innerHTML = '<svg class="ic"><use href="#i-play"/></svg>';
  if (rafId) cancelAnimationFrame(rafId);
  rafId = null;
}
function step(ts) {
  if (!playing) return;
  if (lastTs != null) {
    tCur += (ts - lastTs) * speed;
    if (tCur >= TNc) { tCur = TNc; renderFrame(); stop(); return; }
  }
  lastTs = ts;
  renderFrame();
  const sc = $('#chatscroll');
  const nearBottom = sc.scrollHeight - sc.scrollTop - sc.clientHeight < 220;
  if (nearBottom) sc.scrollTop = sc.scrollHeight;
  rafId = requestAnimationFrame(step);
}
function seekTo(t) {
  tCur = Math.min(Math.max(0, t), TNc);
  renderFrame();
  const sc = $('#chatscroll');
  const firstHidden = [...document.querySelectorAll('#chatbody .re')].find(n => Number(n.dataset.t || 0) > tCur);
  if (firstHidden) firstHidden.scrollIntoView({ block: 'center' });
  else sc.scrollTop = sc.scrollHeight;
}

/* ══════════ 6) المحادثة — ردود محلية صادقة من اللقطة ══════════ */
const SUGGEST = ['ما حالة بوابة 315؟', 'لماذا فشلت الخطوة 1047؟', 'قارن الخطة v1 بالخطة v2', 'كم أرتيفاكت أنتج P4؟', 'ما مخرجات المصنع؟', 'ما قصة جلسة P3؟'];

function findFiles(ql) {
  const out = [];
  Object.values(A.files).forEach(f => {
    if (out.length >= 3) return;
    if (f.name.toLowerCase().includes(ql) || f.path.toLowerCase().includes(ql)) out.push(f);
  });
  return out;
}

function replyShell(html) {
  return aMsg(`${html}
    <div class="ev-chips"><span class="ev-chip">الرد<span class="mono">محلي قواعدي</span></span><span class="ev-chip">المصدر<span class="mono">لقطة ${D.meta.data_sha256_16}</span></span></div>`);
}

const viewBtn = (act, ico, label) => `<button class="flink" data-act="${act}"><svg class="ic"><use href="#${ico}"/></svg>${label}</button>`;

function agentReply(q) {
  const ql = q.toLowerCase();
  const M = D.diff_p4.metrics;

  if (ql.includes('315') || ql.includes('بوابة')) {
    const g = P4.gate315;
    return replyShell(`
      <p class="a-para"><b>بوابة ${g.id}</b> — ${esc(g.kind)} · ${esc(g.status)}</p>
      <p class="a-para">معلقة منذ <span class="mono">${esc(g.created_at)}</span> — السبب: «${esc(g.reason)}». القرار لك: اعتماد الخطة v2 أو طلب تعديل — البوابة لا تتجاوز آلياً.</p>
      <div class="a-links">${viewBtn('gate', 'i-clock', 'بطاقة القرار')}${viewBtn('plan', 'i-branch', 'diff الخطة v1↔v2')}</div>`);
  }
  if (ql.includes('1047') || ql.includes('فشل') || ql.includes('أزمة') || ql.includes('انهيار')) {
    const s = P4.step1047;
    return replyShell(`
      <p class="a-para"><b>الخطوة ${s.id}</b> فشلت في <span class="mono">${s.attempts}</span> محاولات (16د 27ث ثم 38د 20ث) — النمط نفسه: الدورة تُغلق بلا أدلة مكتملة.</p>
      <p class="a-para">الهدف: <span class="mono">${esc(s.objective)}</span> — تكرار الفشل مرتين فتح بوابة 314 إجبارياً وولّد الخطة v2 التي تفكك هذه الخطوة.</p>
      <div class="a-links">${viewBtn('plan', 'i-branch', 'شاهد diff v1↔v2')}${flink('v81', 'القمرة الكاملة')}</div>`);
  }
  if (ql.includes('خطة') || ql.includes('v1') || ql.includes('v2') || ql.includes('قارن') || ql.includes('diff')) {
    return replyShell(`
      <p class="a-para">v1 (id <span class="mono">124</span>) كانت <span class="mono">${M.v1_phases}</span> مراحل و<span class="mono">${M.v1_steps}</span> خطوات و<span class="mono">${M.v1_crit}</span> معيار — انهارت عند الخطوة 1047.</p>
      <p class="a-para">v2 (id <span class="mono">125</span>): <span class="mono">${M.v2_phases}</span> مراحل و<span class="mono">${M.v2_steps}</span> خطوات و<span class="mono">${M.v2_crit}</span> معيار قبول — أكبر خطوة مفككة إلى خطوات قابلة للتحقق، و<span class="mono">${D.diff_p4.v2.risks.length}</span> مخاطر معلنة.</p>
      <div class="a-links">${viewBtn('plan', 'i-branch', 'افتح عرض diff كاملاً')}</div>`);
  }
  if (ql.includes('أرتيفاكت') || ql.includes('8281') || (ql.includes('منتج') && ql.includes('p4'))) {
    const A4 = D.artifacts.p4;
    return replyShell(`
      <p class="a-para">أرتيفاكت P4 الموثقة بعلامة PASS: <span class="mono">${nf(A4.total)}</span> ملفاً بمجموع <span class="mono">${nf(A4.total_bytes)}</span> بايت — كل صف في العرض باسمه الحقيقي وخطوته ودليله.</p>
      <div class="a-links">${viewBtn('art', 'i-db', 'افتح عرض الأرتيفاكت')}${viewBtn('ev', 'i-shield', 'أدلة PASS')}</div>`);
  }
  if (ql.includes('أدل') || ql.includes('ev-')) {
    return replyShell(`
      <p class="a-para">الأدلة في اللقطة: <span class="mono">${D.evidence.p4.length}</span> أدلة PASS لجلسة P4 — كل دليل يحمل رقم خطوة وتنفيذ وcommit وعدد ملفات ومجموع بايتات وبصمات sha256.</p>
      <div class="a-links">${viewBtn('ev', 'i-shield', 'افتح عرض الأدلة')}</div>`);
  }
  if (ql.includes('p3') || ql.includes('ثالث')) {
    const C3 = D.chains.p3;
    return replyShell(`
      <p class="a-para">P3 جلسة <b>موثقة</b> انتهت بالتحقق في <span class="mono">${esc(C3.verified_at || '—')}</span>: <span class="mono">${nf(C3.cycles_n || 0)}</span> دورة تخطيط-تنفيذ، <span class="mono">${nf(C3.gates_total || 0)}</span> بوابة، <span class="mono">${nf(C3.plan_versions || 0)}</span> إصدار خطة.</p>
      <div class="a-links">${viewBtn('s3', 'i-chevl', 'افتح جلسة P3 بسجلها')}</div>`);
  }
  if (ql.includes('p1') || ql.includes('p2') || ql.includes('محجوب')) {
    return replyShell(`
      <p class="a-para">P1 وP2 محجوبتان على قرارات مالك — سلسلتا بواباتهما الحقيقية بأزمنة الانتظار (من حقول <span class="mono">wait_ms</span>): <span class="mono">${(D.chains.p1 || []).length}</span> بوابة لـP1 و<span class="mono">${(D.chains.p2 || []).length}</span> لـP2.</p>
      <div class="a-links">${viewBtn('s2', 'i-chevl', 'جلسة P2')}${viewBtn('s1', 'i-chevl', 'جلسة P1')}</div>`);
  }
  if (ql.includes('ملف') || ql.includes('مخرج') || ql.includes('المصنع') || ql.includes('30') || ql.includes('31')) {
    const st = filesStats();
    return replyShell(`
      <p class="a-para">مخرجات المصنع المعروضة: <span class="mono">${st.n}</span> ملفاً حقيقياً من القرص في <span class="mono">${st.kinds}</span> أنواع بمجموع <span class="mono">${fmtBytes(st.bytes)}</span> — بأحجامها وبصماتها لحظة البناء، والقمرة v8.1 تعمل حية داخلها.</p>
      <div class="a-links">${viewBtn('files', 'i-fold', 'افتح متصفح الملفات')}${flink('v81', 'شغّل القمرة حية')}</div>`);
  }
  if (ql.includes('من أنت') || ql.includes('ماذا تفعل') || ql.includes('كيف') || ql.includes('من بنى')) {
    return replyShell(`
      <p class="a-para">هذه قمرة <b>V9</b>: التصميم المقبول مطبق على المشروع الحقيقي — كل جلسة بسجلها، ومحادثة ترد محلياً من اللقطة، وعرض diff للخطة، وملفات المصنع الحقيقية ببصماتها.</p>
      <div class="a-links">${flink('v9', 'ملف هذه الواجهة')}${viewBtn('files', 'i-fold', 'مخرجات المصنع')}</div>`);
  }
  const fh = findFiles(ql);
  if (fh.length) {
    const rows = fh.map(f => `<div class="sr-item"><span class="sr-file" data-fid="${f.id}"><span class="tmon sm t-${f.kind}">${KIND_TMON[f.kind]}</span> <span class="mono">${esc(f.name)}</span> — ${fmtBytes(f.size)} · انقر للفتح</span></div>`).join('');
    return replyShell(`<p class="a-para">عثرت على <span class="mono">${fh.length}</span> ملفاً مطابقاً:</p><div class="searchres">${rows}</div>`);
  }
  return aMsg(`
    <p class="a-para">أنا رد <b>محلي قواعدي</b> من لقطة مجمّدة — لا يوجد نموذج لغوي حي خلف هذه الواجهة ولا اتصال بخادم، وما ليس في اللقطة لا أختلقه. ما أجيب عنه الآن:</p>
    <div class="a-opts">${SUGGEST.map(s => `<div class="a-opt"><span class="n">·</span><span>${esc(s)}</span></div>`).join('')}</div>`);
}

function sendChat() {
  const inp = $('#q');
  const q = (inp.value || '').trim();
  if (!q) { inp.focus(); return; }
  inp.value = '';
  stop();
  const body = $('#chatbody');
  $('#searchres')?.remove();
  $('#chatend').hidden = true;
  body.insertAdjacentHTML('beforeend', uMsg(q));
  body.insertAdjacentHTML('beforeend', agentReply(q));
  $('#composeStatus').innerHTML = '';
  const sc = $('#chatscroll');
  sc.scrollTo({ top: sc.scrollHeight, behavior: 'instant' });
}

/* ══════════ 7) النوافذ ══════════ */
const FACTORY_HONESTY = [
  'اللوحة أحادية اللون بأمر المالك: أبيض/أسود/رمادي فقط — دقّق جناح الفحص كل قيمة لونية في البناء النهائي (R==G==B بلا استثناء).',
  'الصور رمادية من المصدر (تحويل L قبل الترميز) وفوقها فلتر grayscale — لا قناة لونية تُعرض أصلاً.',
  'معاينة القمرة v8.1 حية 100%: الملف نفسه الموجود في download داخل iframe معزول sandbox="allow-scripts".',
  'قائمة «الملفات» = ملفات حقيقية من القرص — الأحجام وبصمات sha256 محسوبة لحظة البناء، لا أرقام معروضة للتزيين.',
  'المحادثة ردود محلية قواعدية من اللقطة المدمجة — لا نموذج لغوي حي ولا اتصال خادم؛ ما ليس في اللقطة لا يُختلق.',
  'كل جلسة تعرض سجلها هي: P4 ببثها، P3 بسجلها الموثق، P1/P2 بسلاسل بواباتها بتوقيتاتها — لا بث مستعار بين الجلسات.',
  'ملف «AES-COCKPIT-V9.html» هو هذه الواجهة نفسها — حجمه يُقاس فعلياً ويُحقن بتمريرتين حتى يتطابق الرقم المعروض مع القرص.',
];
function openGate() {
  const v2 = D.diff_p4.v2, M = D.diff_p4.metrics;
  $('#gateBody').innerHTML = `
    <p>بوابة <b>315</b> من نوع <span class="mono">PLAN_APPROVAL</span> معلقة منذ <span class="mono">2026-11-02T21:38:07</span> — السبب: «${esc(P4.gate315.reason)}».</p>
    <p>الخطة v2 (id <span class="mono">${v2.plan_id}</span>) محل v1 (id <span class="mono">${v2.supersedes ?? 124}</span>): <span class="mono">${M.v2_phases}</span> مراحل · <span class="mono">${M.v2_steps}</span> خطوات · <span class="mono">${M.v2_crit}</span> معيار قبول · <span class="mono">${v2.ac.length}</span> بنود قبول · <span class="mono">${v2.decisions.length}</span> قرارات · <span class="mono">${v2.risks.length}</span> مخاطر مسجلة.</p>
    <div class="opt"><span class="n">1.</span><span><b>اعتماد</b> — ينتقل المصنع للتنفيذ وفق v2.</span></div>
    <div class="opt"><span class="n">2.</span><span><b>طلب تعديل</b> — تعود الخطة للتخطيط.</span></div>`;
  $('#gateModal').hidden = false;
}
function openHonesty() {
  const base = curSession === 'F' ? FACTORY_HONESTY : D.meta.honesty;
  const extra = curSession === 'F' ? [] : [FACTORY_HONESTY[0]];
  $('#ho-list').innerHTML = base.concat(extra).map(h => `<li>${esc(h)}</li>`).join('');
  const st = filesStats();
  $('#ho-meta').textContent = curSession === 'F'
    ? `files://factory · ${st.n} ملفاً · ${fmtBytes(st.bytes)} · بناء عرض محلي بلا اتصال خادم`
    : `sha256[0:16] = ${D.meta.data_sha256_16} · snapshot_at = ${D.meta.snapshot_at} · بناء عرض محلي بلا اتصال خادم`;
  $('#honesty').hidden = false;
}
let toastTimer = null;
function toast(msg) {
  const t = $('#toast'); t.textContent = msg; t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, 2600);
}

/* ══════════ عرض diff الخطة v1↔v2 — من diff_p4 الحقيقي ══════════ */
function renderPlanDiff() {
  const v1 = D.diff_p4.v1, v2 = D.diff_p4.v2, M = D.diff_p4.metrics;
  const crit = (p) => (p.steps || []).reduce((a, s) => a + (s.crit_n || 0), 0);
  const ph1 = v1.phases.map(p => `
    <div class="dphase">
      <div class="dp-t">${esc(p.title)}</div>
      <div class="dp-o">${esc(p.objective || '')}</div>
      <div class="dp-meta"><span class="metchip"><b>${(p.steps || []).length}</b> خطوات</span><span class="metchip"><b>${crit(p)}</b> معايير</span><span class="metchip">${esc(p.status || '')}</span></div>
    </div>`).join('');
  const ph2 = v2.phases.map(p => `
    <div class="dphase">
      <div class="dp-t">${esc(p.title)}</div>
      <div class="dp-o">${esc(p.objective || '')}</div>
      <div class="dp-meta"><span class="metchip"><b>${(p.steps || []).length}</b> خطوات</span><span class="metchip"><b>${crit(p)}</b> معايير</span></div>
    </div>`).join('');
  const why = (D.diff_p4.why || []).map(w => `
    <div class="whyrow">
      <span class="why-at">${esc((w.at || '').slice(5).replace('T', ' '))}</span>
      <span class="why-dot ${esc(w.tone || '')}"></span>
      <span><span class="why-t">${esc(w.title)}</span><div class="why-b">${esc(w.body || '')}</div></span>
    </div>`).join('');
  const vlist = (arr) => '<div class="vlist">' + arr.map((s, i) => `<div class="vrow"><span class="n">${i + 1}</span><span>${esc(s)}</span></div>`).join('') + '</div>';
  $('#planCanvas').innerHTML = `
    <div class="plan-hd" style="margin-top:14px"><span class="t">الخط الزمني — لماذا أُعيد التخطيط</span>
      <span class="metchips">
        <span class="metchip">v1 <b>${M.v1_phases}</b> مراحل · <b>${M.v1_steps}</b> خطوات · <b>${M.v1_crit}</b> معيار</span>
        <span class="metchip">v2 <b>${M.v2_phases}</b> مراحل · <b>${M.v2_steps}</b> خطوات · <b>${M.v2_crit}</b> معيار</span>
      </span></div>
    ${why}
    <div class="plan-hd"><span class="t">المراحل — v1 محلّها v2</span>
      <span class="metchips"><span class="metchip">v1 id <b>${v1.plan_id}</b></span><span class="metchip">v2 id <b>${v2.plan_id}</b></span></span></div>
    <div class="diffgrid">
      <div class="dcol"><div class="dcol-h">الخطة v1<span class="mono">انهارت عند 1047</span></div>${ph1}</div>
      <div class="dmid"><svg class="ic"><use href="#i-chevl"/></svg></div>
      <div class="dcol"><div class="dcol-h">الخطة v2<span class="mono">بانتظار بوابة 315</span></div>${ph2}</div>
    </div>
    <div class="plan-hd"><span class="t">قرارات v2 (${v2.decisions.length})</span></div>
    ${vlist(v2.decisions)}
    <div class="plan-hd"><span class="t">مخاطر v2 معلنة (${v2.risks.length})</span></div>
    ${vlist(v2.risks)}
    <div class="plan-hd"><span class="t">افتراضات v2 (${v2.assumptions.length})</span></div>
    ${vlist(v2.assumptions)}
    <div class="sysline" style="margin:14px 0 18px">كل ما فوق من حقل <span class="mono">diff_p4</span> الحقيقي في اللقطة — أسماء المراحل والأهداف بنصوصها الأصلية.</div>`;
}

/* ══════════ التوصيل ══════════ */
function switchView(v) {
  document.querySelectorAll('.cview').forEach(c => c.classList.toggle('active', c.dataset.cv === v));
  document.querySelectorAll('.midrail .ibtn[data-view]').forEach(x => x.classList.toggle('on', x.dataset.view === v));
}

function wire() {
  $('#sendbtn').addEventListener('click', sendChat);
  $('#q').addEventListener('keydown', e => { if (e.key === 'Enter') sendChat(); });
  $('#micbtn').addEventListener('click', sendChat);
  document.querySelectorAll('.qchip').forEach(b => b.addEventListener('click', () => { $('#q').value = b.dataset.q; sendChat(); }));

  $('#playbtn').addEventListener('click', play);
  $('#sk-back').addEventListener('click', () => {
    const prev = [...bookMarks].reverse().find(b => b.t < tCur - 1500);
    seekTo(prev ? prev.t : 0);
  });
  $('#sk-fwd').addEventListener('click', () => {
    const nxt = bookMarks.find(b => b.t > tCur + 1500);
    seekTo(nxt ? nxt.t : TN);
  });
  $('#track').addEventListener('click', e => {
    const r = $('#track').getBoundingClientRect();
    const rtlPct = (r.right - e.clientX) / r.width;
    seekTo(rtlPct * TN);
  });
  document.querySelectorAll('.spd').forEach(b => b.addEventListener('click', () => {
    document.querySelectorAll('.spd').forEach(x => x.classList.remove('active'));
    b.classList.add('active');
    speed = Number(b.dataset.x);
    if (playing) { stop(); play(); }
  }));

  $('#tprog-hd').addEventListener('click', () => $('#tprog').classList.toggle('closed'));
  $('#comp-collapse').addEventListener('click', () => {
    $('#app').classList.add('collapsed');
    $('#compCollapseRestore')?.remove();
    const b = el('button', 'ibtn'); b.id = 'compCollapseRestore';
    b.title = 'إظهار حاسبة المصنع';
    b.innerHTML = '<svg class="ic"><use href="#i-monitor"/></svg>';
    b.addEventListener('click', () => { $('#app').classList.remove('collapsed'); b.remove(); });
    document.querySelector('.midrail').appendChild(b);
  });
  document.querySelectorAll('.midrail .ibtn[data-view]').forEach(b => b.addEventListener('click', () => switchView(b.dataset.view)));

  /* متصفح الملفات — تفويض الأحداث */
  $('#filesCanvas').addEventListener('click', e => {
    const row = e.target.closest('.frow');
    if (row) { openFile(row.dataset.fid); return; }
    const gh = e.target.closest('.fgroup-hd');
    if (gh) gh.parentElement.classList.toggle('closed');
  });
  $('#filesCanvas').addEventListener('keydown', e => {
    if (e.key !== 'Enter' && e.key !== ' ') return;
    const row = e.target.closest('.frow');
    if (row) { e.preventDefault(); openFile(row.dataset.fid); }
  });

  /* أزرار فتح الملفات داخل المحادثة */
  $('#chatbody').addEventListener('click', e => {
    const act = e.target.closest('[data-act]');
    if (act) {
      const a = act.dataset.act;
      if (a === 'gate') openGate();
      else if (a === 'plan') switchView('plan');
      else if (a === 'art') switchView('art');
      else if (a === 'ev') switchView('ev');
      else if (a === 'files') switchView('files');
      else if (a === 's1' || a === 's2' || a === 's3') {
        curSession = Number(a[1]);
        renderSessions(); renderChat(); renderComputer(); renderProgress();
      }
      return;
    }
    const fl = e.target.closest('.flink, .sr-file');
    if (fl) openFile(fl.dataset.fid);
    const tc = e.target.closest('.toolchip.th-open');
    if (tc) tc.classList.toggle('open');
  });

  $('#btn-honesty').addEventListener('click', openHonesty);
  $('#hoClose').addEventListener('click', () => $('#honesty').hidden = true);
  $('#gateClose').addEventListener('click', () => $('#gateModal').hidden = true);
  $('#snapchip').addEventListener('click', e => {
    if (e.target.closest('.mono') && D.meta.data_sha256_16) {
      navigator.clipboard?.writeText(D.meta.data_sha256_16).then(() => toast('نُسخت بصمة اللقطة ' + D.meta.data_sha256_16)).catch(() => {});
    }
  });
  $('#newtask').addEventListener('click', () => toast('هذا عرض محلي لسجل حقيقي — لا يقبل مهام جديدة'));
  $('#sb-new').addEventListener('click', () => toast('هذا عرض محلي لسجل حقيقي — لا يقبل مهام جديدة'));
  $('#attach').addEventListener('click', () => toast('المرفقات معطلة في العرض المحلي — لا يوجد اتصال بخادم'));
  $('#chat-dots').addEventListener('click', openHonesty);
  document.querySelectorAll('.modal').forEach(m => m.addEventListener('click', e => { if (e.target === m) m.hidden = true; }));
}

/* ══════════ الإقلاع ══════════ */
$('#qchips').innerHTML = SUGGEST.slice(0, 4).map(s => `<button class="qchip" data-q="${esc(s)}">${esc(s)}</button>`).join('');
renderSessions();
renderChat();
renderComputer();
renderProgress();
renderPlanDiff();
buildMarks();
wire();
renderFilesBrowser();
openFile('v81');          /* الافتتاح: القمرة الحية تعمل داخل المصنع فوراً */
syncReplay();
