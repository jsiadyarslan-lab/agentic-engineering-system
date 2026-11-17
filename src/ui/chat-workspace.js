
/* AES Chat Factory — live API client. No local fixtures, no synthetic verdicts. */
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, c =>
    ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const txt = v => (v === null || v === undefined || v === "") ? "غير محدد" : String(v);
  const safeNum = v => Number.isInteger(+v) && +v > 0 ? +v : null;
  const state = {
    route:{pid:null,cid:null}, projects:[],conversations:[],project:null,snapshot:null,
    messages:[],steps:null,artifacts:null,preview:null, providers:null,readiness:null,modelConfig:null,webMode:"auto",
    mode:"ask",panel:"runs",panelOpen:false,sideOpen:false,
    dark:true,revision:0,loading:false,busy:false,streaming:false,streamText:"",
    streamStatus:"",streamMessage:null,stopRequested:false,pendingMessage:null,
    banner:"",error:"",fileFilter:"",source:null,streamAbort:null,replayAbort:null,
    lastSeq:0,activeGeneration:0
  };
  const routeUrl = (pid,cid) =>
    pid ? "#/p/"+pid+(cid?"/c/"+cid:"") : cid ? "#/c/"+cid : "#/";
  function parseRoute() {
    const hash = location.hash || "#/";
    const project = /^#\/p\/([1-9]\d*)(?:\/c\/([1-9]\d*))?$/.exec(hash);
    if(project) return {pid:safeNum(project[1]),cid:safeNum(project[2])};
    const chat = /^#\/c\/([1-9]\d*)$/.exec(hash);
    return chat ? {pid:null,cid:safeNum(chat[1])} : {pid:null,cid:null};
  }
  function callUrl(base,qs={}) {
    const p=new URLSearchParams();
    Object.entries(qs).forEach(([k,v]) => {if(v!==null&&v!==undefined) p.set(k,String(v));});
    return base + (p.size ? "?"+p.toString():"");
  }
  async function request(path,opts={},limit=14000) {
    const ac=new AbortController(),timer=setTimeout(()=>ac.abort(),limit);
    try{
      const response=await fetch(path,{
        method:"GET",cache:"no-store",credentials:"same-origin",signal:ac.signal,...opts
      });
      const body=await response.text();
      let parsed=body;
      try{parsed=body?JSON.parse(body):null;}catch{}
      if(!response.ok){
        const info=typeof parsed==="object"&&parsed ? parsed.detail||parsed.message||"" : String(body).slice(0,250);
        throw Error("HTTP "+response.status+(info?" — "+(typeof info==="string"?info:JSON.stringify(info)):""));
      }
      return parsed;
    }catch(err){
      throw Error(err?.name==="AbortError"?"انتهت مهلة الطلب دون استجابة، وقد تستمر العملية في الخادم.":String(err.message||err));
    }finally{clearTimeout(timer);}
  }
  const post = (path,data={}) => request(path,{
    method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(data)
  },30000);
  const statusClass=s=>String(s||"").toLowerCase().replace(/[^a-z-]/g,"");
  const status=s=>'<span class="status '+statusClass(s)+'">'+esc(txt(s))+'</span>';
  const time=s=>{if(!s)return "—";const d=new Date(s);return Number.isNaN(d.getTime())?"—":d.toLocaleString("ar",{dateStyle:"short",timeStyle:"short"});};
  const action=(label,id,cls="")=>'<button type="button" class="btn '+cls+'" data-action="'+esc(id)+'">'+esc(label)+'</button>';
  function report(message,isError=false){
    if(isError){state.error=String(message);}else{state.banner=String(message);state.error="";}
    $("live-announce").textContent=String(message);
    renderThread();
  }
  function projectName(p) {return p?.name||("مشروع #"+(p?.id||state.route.pid||"—"));}
  function currentProject(){return state.snapshot||state.project;}
  function linkProject(p){return routeUrl(p.id,null);}
  function renderSidebar(){
    const list=$("projects-list"),con=$("chats-list");
    list.innerHTML=state.projects.length ?
      state.projects.slice(0,70).map(p=>'<a class="nav-item '+(state.route.pid===p.id?"active":"")+'" href="'+linkProject(p)+'"><span>▣</span><span class="t">'+esc(projectName(p))+'</span>'+status(p.status)+'</a>').join("") :
      '<p class="empty">لا مشاريع مسجلة، أو تعذر جلب القائمة.</p>';
    const filtered=state.conversations.filter(c=>!state.route.pid || c.project_id===state.route.pid);
    con.innerHTML=filtered.length ?
      filtered.slice(0,60).map(c=>'<a class="nav-item '+(state.route.cid===c.conversation_id?"active":"")+'" href="'+routeUrl(c.project_id,c.conversation_id)+'"><span>⌕</span><span class="t">'+esc(c.title||"محادثة")+'</span></a>').join("") :
      '<p class="empty">لا محادثات لهذا السياق.</p>';
    $("current-title").textContent=state.route.pid?projectName(currentProject()):state.route.cid?"محادثة":"مساحة العمل";
    const st=currentProject()?.status;
    $("current-status").textContent=st?"المشروع · "+st:(state.error?"تعذر الاتصال":"بيانات حقيقية");
  }
  function showNotice(){
    return (state.error ? '<div class="notice error" role="alert"><strong>تعذر إكمال العملية</strong><div>'+esc(state.error)+'</div>'+action("إعادة القراءة","refresh")+'</div>' : "")+
      (state.banner ? '<div class="notice" role="status">'+esc(state.banner)+'</div>' : "");
  }
  function projectCard(){
    const p=currentProject(); if(!p)return state.loading?'<div class="pending"><span class="mini-progress"></span> جارٍ جلب حالة المشروع…</div>':
      '<div class="notice">لا توجد لقطة مشروع صالحة. لا يمكن تأكيد حالة تشغيله.</div>';
    const snap=state.snapshot||{},open=(snap.gates||[]).filter(g=>g.status==="PENDING");
    const gate=snap.execution_gate||{};
    const count=Array.isArray(snap.phases)?snap.phases.length:null;
    const paused=["PAUSED","BLOCKED","FAILED","INTERRUPTED"].includes(String(p.status||""));
    return '<article class="project-block" aria-label="حالة المشروع الحالية">'+
      '<div class="topic-tag">المشروع #'+esc(p.id)+' · لقطة خادم حقيقية</div><h2>'+esc(projectName(p))+'</h2>'+
      '<p>'+esc(p.objective||"لم يُسجّل هدف.")+'</p>'+
      '<div class="statline">'+status(p.status)+
      '<span class="status">'+esc(count===null?"المراحل غير محمّلة":count+" مراحل")+'</span>'+
      '<span class="status">'+esc(state.snapshot?open.length+" بوابة معلّقة":"لم تُقرأ البوابات")+'</span>'+
      (snap.plan?'<span class="status">خطة مسجلة</span>':'')+'</div>'+
      (paused?'<div class="notice" style="margin-top:12px"><strong>آخر وضع معروف:</strong> '+esc(gate.blocked_reason||gate.owner_action||"المشروع لا يعمل حاليًا؛ راجع أحدث حدث وقرار قبل الاستئناف.")+'</div>':'')+
      '<div class="action-row">'+action("التشغيل","tab-runs","primary")+action("المخرجات","tab-outputs")+action("القرارات","tab-decisions")+
      (p.status==="DRAFT"&&!snap.plan?action("توليد خطة","generate-plan"): "")+
      (snap.plan&&!snap.plan.approved_by_owner?action("مراجعة الخطة","tab-runs"): "")+
      (["PAUSED","BLOCKED"].includes(p.status)&&open.length===0?action("استئناف بعد المراجعة","resume"): "")+
      '</div></article>';
  }
  function conversationMarkup(){
    const bits=state.messages.map(m=>{
      const isUser=m.role==="user";
      return '<article class="message '+(isUser?"user":"assistant")+'">'+
        '<div class="avatar" aria-hidden="true">'+(isUser?"":"✳")+'</div>'+
        '<div class="message-body" dir="auto"><div class="msg-meta"><strong>'+esc(isUser?"أنت":"المصنع · محادثة")+'</strong>'+
        (m.state_badge?status(m.state_badge):"")+'</div>'+
        '<div>'+esc(m.content||"")+'</div></div></article>';
    }).join("");
    if(state.pendingMessage && !state.messages.some(m=>m.content===state.pendingMessage&&m.role==="user")){
      bits+='<article class="message user"><div class="message-body"><div class="msg-meta">جارٍ إرسال الرسالة…</div>'+esc(state.pendingMessage)+'</div></article>';
    }
    if(state.streaming)bits+='<article class="message assistant" aria-live="polite"><div class="avatar">✳</div>'+
      '<div class="message-body" dir="auto"><div class="msg-meta"><strong>المصنع</strong><span class="mini-progress"></span> '+esc(state.streamStatus||"جاري الاتصال…")+'</div>'+
      '<div>'+esc(state.streamText||"")+'</div></div></article>';
    return bits;
  }
  function renderIntro(){
    if(state.route.pid) return projectCard()+
      (state.messages.length||state.streaming||state.route.cid?"":'<div class="intro"><h1>تحدث عن مشروعك</h1><p>الرسالة سؤال محفوظ؛ لن تُطلق مهمة دون أمر صريح.</p></div>');
    return '<div class="intro"><div class="mark">✳</div>'+
      '<h1>ماذا تريد أن تنجز اليوم؟</h1>'+
      '<p>ابدأ من محادثة، أو حوّل هدفك إلى مشروع هندسي بقرارات وأدلة ومخرجات حقيقية.</p>'+
      '<div class="suggest"><button data-action="suggest-project" type="button"><b>ابدأ مشروعًا هندسيًا</b><br>إنشاء هدف واضح وخطة قابلة للاعتماد</button>'+
      '<button data-action="suggest-chat" type="button"><b>اسأل المصنع</b><br>محادثة حقيقية مع مزود النموذج</button>'+
      '<button data-action="all-decisions" type="button"><b>راجع قراراتك</b><br>القرارات المفتوحة من قاعدة المشاريع</button>'+
      '<button data-action="tab-outputs" type="button"><b>افتح المخرجات</b><br>ملفات مثبتة بأدلتها، لا وعود لفظية</button></div></div>';
  }
  function renderThread(scroll=false){
    const thread=$("thread"),scroller=$("scrollbody");
    const nearBottom=scroller.scrollHeight-scroller.clientHeight-scroller.scrollTop<140;
    const intro=(state.route.cid&&!state.route.pid) ?
      '<div class="topic-tag">محادثة محفوظة · '+esc(state.route.cid)+'</div>' :
      renderIntro();
    thread.innerHTML=showNotice()+intro+conversationMarkup()+
      (!state.route.pid && !state.route.cid && state.projects.length?
        '<div class="topic-tag">مشاريعك الأخيرة</div>'+state.projects.slice(0,4).map(p=>
        '<div class="card"><div class="card-head"><h4>'+esc(projectName(p))+'</h4>'+status(p.status)+'</div>'+
        '<p>'+esc((p.objective||"").slice(0,180))+'</p>'+
        '<div class="action-row">'+action("افتح","project-"+p.id)+'</div></div>').join(""):"");
    if(scroll||nearBottom)scroller.scrollTop=scroller.scrollHeight;
    $("stop-chat").hidden=!state.streaming;
    $("send").disabled=state.streaming||state.busy;
  }
  function selectPanel(mode){
    if(!state.route.pid && !["settings","tools","decisions","search"].includes(mode)){
      report("اختر مشروعًا أولًا لعرض تشغيله ومخرجاته.",true);
      return;
    }
    state.panel=mode; state.panelOpen=true; renderPanel();
    loadPanelData(mode);
  }
  function renderPanel(){
    const panel=$("inspector"); panel.hidden=!state.panelOpen;
    $("panel-title").textContent={
      runs:"التشغيل والخطة",outputs:"المخرجات",decisions:"قرارات المالك",
      browser:"المراجع والمتصفح",settings:"الإعدادات",tools:"الإضافات",
      search:"البحث"
    }[state.panel]||"لوحة العمل";
    $("panel-tabs").hidden=["settings","tools","search"].includes(state.panel);
    if(!state.panelOpen)return;
    const id=state.route.pid;
    const c=$("panel-content");
    if(state.panel==="runs")c.innerHTML=renderRuns();
    else if(state.panel==="outputs")c.innerHTML=renderOutputs();
    else if(state.panel==="decisions")c.innerHTML=renderDecisions();
    else if(state.panel==="browser")c.innerHTML=renderBrowser();
    else if(state.panel==="settings")c.innerHTML=renderSettings();
    else if(state.panel==="tools")c.innerHTML=renderTools();
    else if(state.panel==="search")c.innerHTML='<label for="local-search">ابحث في أسماء المشاريع والمحادثات</label><input id="local-search" class="surface-input" placeholder="اسم المشروع أو المحادثة"><div id="search-results"></div>';
    if(!id && ["runs","outputs","browser"].includes(state.panel))c.innerHTML='<div class="empty">اختر مشروعًا من الشريط الجانبي.</div>';
  }
  function renderRuns(){
    const snap=state.snapshot,p=currentProject();
    if(!p)return '<div class="empty">تنتظر لقطة حالة المشروع من الخادم.</div>';
    const plan=snap?.plan;
    const steps=state.steps?.steps||[];
    const latest=[...steps].sort((a,b)=>(b.id||0)-(a.id||0));
    let body='<div class="card"><div class="card-head"><h4>'+esc(projectName(p))+'</h4>'+status(p.status)+'</div>'+
      '<p>'+esc(snap?.execution_gate?.blocked_reason||"القراءة الحالية من API.")+'</p>'+
      '<div class="action-row">'+(p.status==="DRAFT"&&!plan?action("توليد خطة","generate-plan","primary"):"")+
      (plan&&!plan.approved_by_owner?action("اعتماد الخطة","approve-plan","primary"):"")+
      (["PAUSED","BLOCKED"].includes(p.status)?action("استئناف","resume"):"")+
      (p.status==="RUNNING"?action("إيقاف مؤقت","pause"):"")+
      (p.status==="BLOCKED"?action("إعادة فحص البيئة","preflight"):"")+
      '</div></div>';
    if(plan)body+='<div class="card"><div class="card-head"><h4>الخطة الحالية</h4>'+
      '<span class="status">v'+esc(plan.version||"—")+'</span></div><p>'+
      esc(plan.approved_by_owner?"الخطة معتمدة في السجل":"الخطة تحتاج مراجعة واعتمادًا قبل التشغيل")+'</p>'+
      '<details><summary>تفاصيل الخطة المسجلة</summary><pre class="preview" dir="ltr">'+esc(JSON.stringify(plan,null,2))+'</pre></details></div>';
    body+='<div class="topic-tag">خطوات التنفيذ · الأحدث أولًا</div>';
    body+=state.steps===null?'<p class="quiet">جارٍ جلب الخطوات…</p>':
      latest.length?latest.slice(0,35).map(s=>'<div class="card"><div class="card-head"><h4>#'+esc(s.id)+' '+esc(s.objective||s.title||"خطوة")+'</h4>'+status(s.status)+'</div>'+
      '<p class="mini">'+esc(s.phase_title||"")+'</p>'+
      '<details><summary>معايير القبول والتاريخ</summary><pre class="preview">'+esc(JSON.stringify(s,null,2))+'</pre></details></div>').join(""):'<div class="empty">لا خطوات مسجلة.</div>';
    if(snap?.events?.length)body+='<details><summary>السجل التشخيصي (مطوي افتراضيًا)</summary>'+
      snap.events.slice(-25).reverse().map(e=>'<div class="card"><div class="row"><b>'+esc(e.kind||"حدث")+'</b><small>'+esc(time(e.created_at||e.timestamp))+'</small></div><div class="quiet">'+esc(e.message||e.state||e.payload?.reason||"")+'</div></div>').join("")+'</details>';
    return body;
  }
  function renderOutputs(){
    if(!state.route.pid)return '<div class="empty">افتح مشروعًا.</div>';
    let body='<div class="notice">تُعرض ملفات الأدلة فقط. ظهور ملف لا يعني اعتماد التسليم النهائي.</div>'+
      '<label for="file-search" class="sr-only">بحث في الملفات</label>'+
      '<input id="file-search" class="surface-input" placeholder="ابحث باسم الملف" value="'+esc(state.fileFilter)+'">';
    const items=(state.artifacts?.artifacts||[]).filter(a=>
      (a.name||"").toLocaleLowerCase().includes(state.fileFilter.toLocaleLowerCase()));
    if(!state.artifacts)return body+'<div class="empty">جارٍ جلب أدلة الملفات…</div>';
    body+=items.length?items.slice(0,80).map((a)=>{
      const index=(state.artifacts.artifacts||[]).indexOf(a);
      return '<div class="card"><div class="card-head"><h4 class="file-name">'+esc(a.name||"ملف")+'</h4>'+status(a.verdict||"دليل")+'</div>'+
        '<div class="mini">خطوة #'+esc(a.step_id)+' · '+esc(a.kind||"file")+' · '+esc(time(a.created_at))+'</div>'+
        (a.sha256?'<div class="mini mono">'+esc(a.sha256.slice(0,22))+'…</div>':"")+
        '<div class="action-row">'+(a.kind==="file"&&safeNum(a.step_id)?action("معاينة النص","file-"+index):"")+'</div></div>';
    }).join(""):'<div class="empty">لا ملفات دليل مطابقة للبحث.</div>';
    if(state.preview){
      body='<div class="card"><div class="card-head"><h4 class="file-name">'+esc(state.preview.name)+'</h4>'+
      action("رجوع للملفات","close-preview")+'</div><p class="mini">معاينة نصية للقراءة فقط من API. قد تكون مقتطعة عند 256KB؛ ليست حزمة التسليم.</p>'+
      '<div class="preview" dir="auto">'+esc(state.preview.content)+'</div>'+
      '<div class="action-row">'+action("تنزيل النص المعروض","download-preview")+'</div></div>'+body;
    }
    return body;
  }
  function renderDecisions(){
    const items=(state.snapshot?.gates||[]).filter(g=>g.status==="PENDING");
    if(!state.route.pid){
      const list=state.projects.filter(p=>["PAUSED","BLOCKED","WAITING_OWNER"].includes(p.status));
      return list.length?list.map(p=>'<div class="card"><div class="card-head"><h4>'+esc(projectName(p))+'</h4>'+status(p.status)+'</div>'+action("افتح القرارات","project-"+p.id)+'</div>').join(""):
        '<div class="empty">لا قرارات مفتوحة مؤكدة من قائمة المشاريع وحدها. افتح المشروع لتحديد بواباته.</div>';
    }
    if(!state.snapshot)return '<div class="empty">جارٍ جلب بوابات المشروع…</div>';
    let body='';
    if(state.snapshot.plan&&!state.snapshot.plan.approved_by_owner){
      body+='<div class="card"><h4>اعتماد خطة المشروع</h4><p>الاعتماد يطلق التنفيذ الحقيقي تلقائيًا؛ راجع الخطة قبل القرار.</p>'+
        action("عرض الخطة","tab-runs")+action("اعتماد","approve-plan","primary")+'</div>';
    }
    body+=items.length?items.map(g=>
      '<div class="card"><div class="card-head"><h4>'+esc(g.kind||"قرار مالك")+'</h4>'+status(g.status)+'</div>'+
      '<p>'+esc(g.reason||g.description||"راجع الدليل قبل اتخاذ القرار")+'</p>'+
      '<div class="mini">بوابة #'+esc(g.id)+'</div>'+
      '<details><summary>أدلة وتفاصيل القرار</summary><pre class="preview">'+esc(JSON.stringify(g,null,2))+'</pre></details>'+
      '<div class="action-row">'+action("اعتماد","gate-yes-"+g.id,"primary")+action("رفض","gate-no-"+g.id)+'</div></div>').join(""):'<div class="empty">لا توجد بوابات مالك معلّقة في هذه اللقطة.</div>';
    if(state.snapshot.status==="VERIFIED")body+='<div class="notice">التحقق النهائي مسجل في حالة المشروع.</div>';
    return body;
  }
  function renderBrowser(){
    return '<div class="card"><h4>المراجع والمتصفح</h4><p>المصنع لا يوفر في هذا العقد جلسة متصفح مدمج قابلة للتحكم. لا تُعرض نافذة وهمية.</p>'+
      '<a class="btn" href="/evolution" target="_blank" rel="noopener noreferrer">فتح متصفح تطور المصنع ↗</a></div>'+
      '<div class="card"><h4>معاينة منتج حقيقي</h4><p>يمكنك فحص الملفات النصية المثبتة من «المخرجات». الروابط الخارجية تُفتح خارج المصنع حتى تتوفر جلسة متصفح مصرح بها.</p>'+
      action("المخرجات","tab-outputs")+'</div>';
  }

  function renderTools(){
    if(!state.providers)return '<div class="empty">جارٍ قراءة المزودات من الخادم…</div>';
    const items=Array.isArray(state.providers)?state.providers:Array.isArray(state.providers.providers)?state.providers.providers:[];
    return '<div class="notice">هذه حالة التسجيل في قاعدة الخادم، وليست إثباتًا بأن كل استدعاء نموذج سينجح. لا تُعرض مفاتيح API.</div>'+
      (items.length?items.map(p=>{
        const configEnabled=(p.configurations||[]).some(c=>c.enabled);
        const available=Boolean(p.enabled&&configEnabled&&(p.auth_type!=="bearer"||p.has_key));
        return '<div class="card"><div class="card-head"><h4>'+esc(p.display_name||p.name||p.id||"مزود")+'</h4>'+
          status(available?"مكوّن":"غير جاهز")+'</div>'+
          '<p class="mini">'+esc(available?"مسجل ومهيأ مبدئيًا؛ يتطلب اختبار قدرة مستقل.":p.has_key===false?"لا يوجد مفتاح محفوظ.":"التكوين أو التفعيل غير مكتمل.")+'</p>'+
          '<div class="mini">التكوينات: '+esc((p.configurations||[]).length)+'</div></div>';
      }).join(""):'<div class="empty">لم يُرجع API أي مزودات.</div>')+
      '<div class="card"><h4>المتصفح المدمج</h4><p>التحكم بمتصفح خارجي يتطلب جلسة متصفح وموافقات؛ لا يوجد هذا العقد في API الحالي.</p>'+
      action("متصفح التطور الموجود","tab-browser")+'</div>';
  }
  function renderSettings(){
    const theme=document.documentElement.dataset.theme||"dark";
    const roles=state.modelConfig?.roles||[];
    const chat=roles.find(x=>x.key==="chat")?.selection||{};
    const providers=state.modelConfig?.providers||[];
    const options=providers.map(p=>
      '<option value="'+esc(p.id)+'" '+(p.id===chat.provider?"selected":"")+'>'+esc(p.label||p.id)+
      (p.available?"":" · غير متاح")+'</option>').join("");
    const roleList=roles.map(r=>
      '<div class="row" style="justify-content:space-between;border-bottom:1px solid var(--line);padding:6px 0"><span>'+
      esc(r.label||r.key)+'</span><small>'+esc((r.selection?.provider||"—")+" / "+(r.selection?.model||"—"))+'</small></div>').join("");
    return '<div class="card"><h4>المظهر</h4><div class="action-row">'+
      action("داكن","theme-dark",theme==="dark"?"primary":"")+
      action("فاتح","theme-light",theme==="light"?"primary":"")+'</div></div>'+
      '<div class="card"><h4>بحث المحادثة</h4><p>اختيار طريقة استخدام البحث في الرسائل القادمة فقط.</p>'+
      '<div class="action-row">'+["auto","on","off"].map(m=>
        action(({auto:"تلقائي",on:"بحث صريح",off:"بدون ويب"})[m],"web-"+m,state.webMode===m?"primary":"")).join("")+
      '</div></div>'+
      '<div class="card"><h4>نماذج المحادثة</h4><p>تغيير ربط نموذج المحادثة يحفظ إعدادًا عامًا يؤثر على الطلبات المقبلة.</p>'+
      (!state.modelConfig?'<div class="empty">جارٍ قراءة إعدادات النماذج…</div>':
      '<form id="chat-settings-form"><label for="model-provider">المزود</label>'+
      '<select id="model-provider" name="provider" class="surface-input" required>'+options+'</select>'+
      '<label for="model-id">معرف النموذج</label>'+
      '<input id="model-id" name="model" class="surface-input mono" required maxlength="200" value="'+esc(chat.model||"")+'">'+
      '<input type="hidden" name="configuration" value="'+esc(chat.configuration||"")+'">'+
      '<div class="action-row"><button class="btn primary" type="submit">حفظ ربط المحادثة</button></div></form>')+'</div>'+
      '<div class="card"><h4>ربط الأدوار المسجل</h4>'+(roleList||'<p>لم تصل بيانات الدور.</p>')+'</div>'+
      '<div class="card"><h4>حالة البيئة الفعلية</h4>'+
      (state.readiness?'<pre class="preview">'+esc(JSON.stringify(state.readiness,null,2))+'</pre>':
      '<p>جارٍ قراءة جاهزية الخادم…</p>')+'</div>'+
      '<div class="card"><h4>الإضافات</h4><p>استعرض المزودات الفعلية دون نقل مفاتيحها إلى المتصفح.</p>'+
      action("الإضافات","tools")+'</div>'+
      '<div class="card"><h4>الإعدادات المتقدمة</h4><p>لا تُعرض واجهة مزيفة لميزات لم يُنقل عقد API الخاص بها.</p>'+
      '<a class="btn" href="/static/factory-legacy.html">الواجهة السابقة</a></div>';
  }
  async function saveChatSettings(form) {
    if(state.busy)return;
    const fd=new FormData(form),provider=String(fd.get("provider")||"").trim(),
      model=String(fd.get("model")||"").trim();
    const previousProvider=state.modelConfig?.roles?.find(r=>r.key==="chat")?.selection?.provider;
    const configuration=provider===previousProvider?String(fd.get("configuration")||"").trim():"";
    if(!provider||!model)return report("المزود والنموذج مطلوبان.",true);
    if(!window.confirm("ستُحفظ إعدادات نموذج المحادثة في قاعدة المصنع، وستؤثر على الرسائل القادمة. متابعة؟"))return;
    state.busy=true;
    try {
      const result=await request("/api/models/config",{
        method:"PUT",headers:{"Content-Type":"application/json"},
        body:JSON.stringify({chat:{provider,model,configuration}})
      },20000);
      if(result?.success!==true)throw Error("رد غير متوقع؛ لم نؤكد الحفظ.");
      state.modelConfig=await request("/api/models/config",{},12000);
      report("أكد الخادم حفظ نموذج المحادثة. لن تتأثر الرسائل المحفوظة.");
      renderPanel();
    }catch(e){report("فشل حفظ الإعدادات: "+e.message,true);}
    finally{state.busy=false;}
  }
  async function loadPanelData(mode) {
    const key=state.revision,id=state.route.pid;
    try{
      if(mode==="runs"&&id&&state.steps===null){
        const d=await request("/api/projects/"+id+"/steps");
        if(key===state.revision){state.steps=d;renderPanel();}
      }else if(mode==="outputs"&&id&&state.artifacts===null){
        const d=await request("/api/projects/"+id+"/artifacts",{},20000);
        if(key===state.revision){state.artifacts=d;renderPanel();}
      }else if(mode==="tools"&&state.providers===null){
        const d=await request("/api/providers");
        state.providers=d;renderPanel();
      }else if(mode==="settings"){
        const pending=[];
        if(state.readiness===null)pending.push(request("/api/environment/readiness")
          .then(d=>{state.readiness=d;}));
        if(state.modelConfig===null)pending.push(request("/api/models/config")
          .then(d=>{state.modelConfig=d;}));
        if(pending.length)await Promise.all(pending);
        renderPanel();
      }
    }catch(e){report("تعذر فتح القسم: "+e.message,true);}
  }
  async function loadCollections(key){
    const all=await Promise.allSettled([request("/api/projects"),request("/api/conversations")]);
    if(key!==state.revision)return;
    if(all[0].status==="fulfilled")state.projects=all[0].value?.projects||[];
    else state.error="تعذر جلب المشاريع: "+all[0].reason.message;
    if(all[1].status==="fulfilled")state.conversations=all[1].value?.conversations||[];
    else state.error+=" تعذر جلب المحادثات: "+all[1].reason.message;
    const pid=state.route.pid;
    state.project=state.projects.find(p=>p.id===pid)||null;
    renderSidebar();renderThread();
  }
  async function loadProject(key){
    const id=state.route.pid;if(!id)return;
    try{
      const d=await request("/api/projects/"+id+"/state",{},22000);
      if(key!==state.revision)return;
      state.snapshot=d;state.project=d;
      renderSidebar();renderThread();renderPanel();
    }catch(e){if(key===state.revision)report("تعذر جلب الحالة التفصيلية للمشروع: "+e.message,true);}
  }
  async function loadMessages(key){
    const cid=state.route.cid;if(!cid)return;
    try{
      const [meta,history]=await Promise.all([
        request("/api/conversations/"+cid),
        request("/api/conversations/"+cid+"/messages")
      ]);
      if(key!==state.revision)return;
      if((meta.project_id||null)!==(state.route.pid||null)){
        report("مُنعت قراءة محادثة خارج نطاق المشروع. افتح المحادثة من مشروعها الصحيح.",true);
        return;
      }
      state.messages=history.messages||[];
      renderThread(true);
      const active=await request(callUrl("/api/chat/active",{conversation_id:cid}),{},9000);
      if(key!==state.revision)return;
      if(active.running && !state.streaming){
        state.streaming=true;state.streamStatus="إعادة اتصال بتوليد قائم…";state.streamMessage=active.message_id;
        state.streamText="";renderThread(true);
        resumeStream(cid,key,active.last_seq||0,active.message_id);
      }
    }catch(e){if(key===state.revision)report("تعذر استعادة المحادثة: "+e.message,true);}
  }
  async function openRoute(){
    const key=++state.revision;
    if(state.streamAbort){state.streamAbort.abort();state.streamAbort=null;}
    if(state.replayAbort){state.replayAbort.abort();state.replayAbort=null;}
    state.route=parseRoute();state.project=null;state.snapshot=null;
    state.messages=[];state.steps=null;state.artifacts=null;state.preview=null;
    state.pendingMessage=null;state.streamStatus="";state.streamText="";
    state.streaming=false;state.error="";state.banner="";state.loading=true;
    state.panelOpen=false;state.sideOpen=false;syncOverlay();
    renderSidebar();renderThread();renderPanel();
    await loadCollections(key);
    if(key!==state.revision)return;
    const work=[loadProject(key),loadMessages(key)];
    await Promise.allSettled(work);
    if(key!==state.revision)return;
    state.loading=false;renderSidebar();renderThread();
  }
  function syncOverlay(){
    $("sidebar").classList.toggle("open",state.sideOpen);
    $("veil").hidden=!state.sideOpen;
    $("inspector").hidden=!state.panelOpen;
  }
  function modalCreate(initial=""){
    $("dialog-host").hidden=false;
    $("dialog-host").innerHTML='<div class="dialog-scrim" role="presentation"><form id="create-project-form" class="dialog" role="dialog" aria-modal="true" aria-labelledby="create-title">'+
      '<h2 id="create-title">مشروع جديد</h2><p class="quiet">سيُنشأ مشروع DRAFT حقيقي. لا يبدأ التنفيذ إلا بتوليد واعتماد الخطة.</p>'+
      '<label for="project-name">اسم المشروع</label><input id="project-name" name="name" maxlength="200" required class="surface-input" placeholder="مثال: موقع عربي متكامل">'+
      '<label for="project-goal">الهدف والمخرج النهائي</label><textarea id="project-goal" name="objective" minlength="3" required class="surface-input" placeholder="ما الذي تريد إنتاجه؟">'+esc(initial)+'</textarea>'+
      '<div class="modal-actions"><button class="btn" type="button" data-action="close-dialog">إلغاء</button><button class="btn primary" type="submit">إنشاء المشروع</button></div></form></div>';
    $("project-name").focus();
  }
  function closeDialog(){ $("dialog-host").hidden=true;$("dialog-host").innerHTML=""; }
  async function createProject(form){
    if(state.busy)return;
    const data=new FormData(form),name=String(data.get("name")||"").trim(),
      objective=String(data.get("objective")||"").trim();
    if(!name||objective.length<3)return;
    state.busy=true;
    try{
      const result=await post("/api/projects",{name,objective,execution_policy:"STRICT_ISOLATED"});
      const id=safeNum(result?.id||result?.project?.id);
      if(!id)throw Error("عاد الخادم دون معرف مشروع؛ راجع قائمة المشاريع قبل إعادة الإنشاء.");
      closeDialog();state.mode="ask";syncMode();location.hash=routeUrl(id,null);
    }catch(e){$("dialog-host").querySelector(".dialog").insertAdjacentHTML("afterbegin",'<div class="notice error">'+esc(e.message)+'</div>');}
    finally{state.busy=false;}
  }
  function syncMode(){
    $("mode-ask").classList.toggle("active",state.mode==="ask");
    $("mode-build").classList.toggle("active",state.mode==="build");
    $("prompt").placeholder=state.mode==="build"?"صف المشروع الذي تريد إنشاءه…":"اكتب رسالة…";
    $("composer-hint").textContent=state.mode==="build"?
      "سيفتح نموذج إنشاء مشروع DRAFT. لا يبدأ تشغيل تلقائي.":
      "المحادثة محفوظة. تنفيذ المشروع يتطلب اعتمادًا صريحًا.";
  }
  function readSSEFrame(frame){
    const raw=frame.split(/\r?\n/).filter(x=>x.startsWith("data:")).map(x=>x.slice(5).trimStart()).join("\n");
    if(!raw||raw==="[DONE]")return null;
    try{return JSON.parse(raw);}catch{return null;}
  }
  async function consume(reader,consumer){
    const decoder=new TextDecoder();let carry="",bytes=0;
    while(true){
      const item=await reader.read();if(item.done)break;
      bytes+=item.value.byteLength;
      if(bytes>4_000_000)throw Error("تجاوز بث المحادثة 4MB؛ افحص المحادثة المحفوظة.");
      carry+=decoder.decode(item.value,{stream:true});
      const frames=carry.split(/\r?\n\r?\n/);carry=frames.pop()||"";
      for(const f of frames){const data=readSSEFrame(f);if(data)consumer(data);}
    }
    if(carry.trim()){const data=readSSEFrame(carry);if(data)consumer(data);}
  }
  function handleStreamEvent(event,key,allowedMessage){
    if(key!==state.revision)return;
    const scope=event.scope||{};
    const cid=safeNum(scope.conversation_id||event.details?.conversation_id);
    const pid=safeNum(scope.project_id);
    if(pid!==null&&pid!==state.route.pid)return;
    if(state.route.cid&&cid&&state.route.cid!==cid)return;
    if(allowedMessage&&event.message_id&&event.message_id!==allowedMessage)return;
    if(event.seq)state.lastSeq=Math.max(state.lastSeq,+event.seq||0);
    if(event.kind==="conversation.bind"){
      const id=cid||safeNum(event.details?.conversation_id);
      if(id&&!state.route.cid){state.route.cid=id;history.replaceState(null,"",routeUrl(state.route.pid,id));}
      state.streamMessage=event.message_id||state.streamMessage;
    }else if(event.kind==="message_delta"){
      state.streamText+=String(event.delta||event.text||"");
      state.streamStatus="يكتب الرد…";
    }else if(event.kind==="chat.error"){
      state.streamStatus="فشل التوليد";
      state.error=String(event.text||event.code||"فشل المحادثة");
    }else if(event.kind==="chat.status"){
      state.streamStatus=String(event.text||event.status||"جارٍ التوليد");
    }else if(event.kind==="message_completed"){
      state.streamStatus="اكتمل الرد، يجري تثبيت الرسائل من القاعدة.";
    }else if(event.kind==="research.started"){
      state.streamStatus="يجري البحث…";
    }
    renderThread(true);
  }
  async function sendMessage(message){
    if(state.busy||state.streaming)return;
    state.error="";state.banner="";state.pendingMessage=message;
    state.streaming=true;state.streamText="";state.streamMessage=null;
    state.streamStatus="إرسال إلى المحادثة الحقيقية…";state.stopRequested=false;
    const key=state.revision;state.lastSeq=0;
    const body={message,conversation_id:state.route.cid||null,project_id:state.route.pid||null,web:state.webMode};
    const controller=new AbortController();state.streamAbort=controller;
    renderThread(true);
    try{
      const res=await fetch("/api/chat/stream",{
        method:"POST",credentials:"same-origin",cache:"no-store",
        headers:{"Content-Type":"application/json"},body:JSON.stringify(body),signal:controller.signal
      });
      if(!res.ok){const b=await res.text();throw Error("HTTP "+res.status+" — "+b.slice(0,200));}
      await consume(res.body.getReader(),ev=>handleStreamEvent(ev,key,null));
      if(key!==state.revision)return;
      if(state.route.cid){
        const d=await request("/api/conversations/"+state.route.cid+"/messages");
        if(key!==state.revision)return;
        state.messages=d.messages||[];
      }else{
        state.error="لم يرجع الخادم معرّف المحادثة؛ افحص قائمة المحادثات قبل إعادة إرسال الرسالة.";
      }
    }catch(e){
      if(key===state.revision)state.error=controller.signal.aborted?
        "انقطع اتصال المتصفح بالبث، وقد يستمر النموذج على الخادم. افتح المحادثة المحفوظة قبل الإرسال ثانية.":
        "تعذر إرسال المحادثة أو إكمال بثها: "+(e.message||e);
    }finally{
      if(key===state.revision){
        state.streaming=false;state.pendingMessage=null;state.streamAbort=null;
        renderThread(true);
        request("/api/conversations").then(d=>{if(key===state.revision){state.conversations=d.conversations||[];renderSidebar();}}).catch(()=>{});
      }
    }
  }
  async function resumeStream(cid,key,lastSeq,messageId){
    const controller=new AbortController();state.replayAbort=controller;
    const after=Math.max(0,(+lastSeq||0)-120);
    try{
      const res=await fetch(callUrl("/api/chat/events/"+cid,{after}),{
        credentials:"same-origin",cache:"no-store",signal:controller.signal
      });
      if(!res.ok)throw Error("HTTP "+res.status);
      await consume(res.body.getReader(),ev=>handleStreamEvent(ev,key,messageId));
      if(key!==state.revision)return;
      const history=await request("/api/conversations/"+cid+"/messages");
      if(key!==state.revision)return;
      state.messages=history.messages||[];state.error="";
    }catch(e){
      if(key===state.revision&&!controller.signal.aborted)state.error="تعذر استعادة بث المحادثة: "+e.message;
    }finally{
      if(key===state.revision){state.streaming=false;state.replayAbort=null;renderThread(true);}
    }
  }
  async function mutate(path,data,confirmText){
    if(state.busy)return;
    if(confirmText&&!window.confirm(confirmText))return;
    const key=state.revision;
    state.busy=true;state.error="";state.banner="أُرسل الطلب إلى الخادم. لا نعتمد نجاحه قبل الرد.";renderThread();
    try{
      const result=await post(path,data);
      if(key!==state.revision)return;
      const launch=result?.launch;
      state.banner=launch ? (launch.launched?
        "قَبِل الخادم القرار وأطلق التشغيل الحقيقي. راقب حالة المشروع.":
        "سُجّل القرار، لكن إطلاق التنفيذ غير مثبت: "+(launch.reason||"سبب غير معروف")):
        "رد الخادم مسجل. يتم تحديث حالة المشروع.";
      await loadProject(key);
    }catch(e){if(key===state.revision)state.error="لم يثبت نجاح الإجراء: "+e.message;}
    finally{state.busy=false;renderThread();renderPanel();}
  }
  async function previewFile(index){
    const a=state.artifacts?.artifacts?.[index],id=state.route.pid;
    if(!a||a.kind!=="file"||!safeNum(a.step_id))return;
    state.error="";state.banner="جارٍ جلب النص من سجل الملفات المثبتة…";renderThread();
    try{
      const path=callUrl("/api/projects/"+id+"/artifacts/content",{step_id:a.step_id,name:a.name});
      const controller=new AbortController(),clock=setTimeout(()=>controller.abort(),18000);
      let content;
      try {
        const response=await fetch(path,{credentials:"same-origin",cache:"no-store",signal:controller.signal});
        if(!response.ok)throw Error("HTTP "+response.status);
        content=await response.text(); // preserve JSON documents as text, not parsed objects
      }finally{clearTimeout(clock);}
      state.preview={name:a.name,content,sha256:a.sha256,bytes:a.bytes};
      state.banner="المعاينة من API، ولا تعادل تحقق SHA256 للمحتوى كاملًا.";
      renderPanel();renderThread();
    }catch(e){report("تعذر قراءة الملف: "+e.message,true);}
  }
  function downloadPreview(){
    if(!state.preview)return;
    const blob=new Blob([state.preview.content],{type:"text/plain;charset=utf-8"});
    const url=URL.createObjectURL(blob),anchor=document.createElement("a");
    anchor.href=url;anchor.download=(state.preview.name||"preview.txt").split("/").pop()+".preview.txt";
    anchor.click();URL.revokeObjectURL(url);
  }
  async function refresh(){
    const key=state.revision;
    await loadCollections(key);
    if(state.route.pid)await loadProject(key);
    if(state.route.cid&&!state.streaming)await loadMessages(key);
    if(state.panelOpen)loadPanelData(state.panel);
  }
  async function handleAction(id){
    const project=state.route.pid;
    if(id==="home"){location.hash="#/";return;}
    if(id==="sidebar"){state.sideOpen=!state.sideOpen;syncOverlay();return;}
    if(id==="close-overlays"){state.sideOpen=false;syncOverlay();return;}
    if(id==="inspector"){state.panelOpen=!state.panelOpen;syncOverlay();renderPanel();if(state.panelOpen)loadPanelData(state.panel);return;}
    if(id==="inspector-close"){state.panelOpen=false;syncOverlay();return;}
    if(id==="new-chat"){
      state.sideOpen=false;
      const next=routeUrl(project,null);
      if(location.hash===next){
        state.route.cid=null;state.messages=[];state.streamText="";state.pendingMessage=null;
        renderThread();renderSidebar();
      }else location.hash=next;
      syncOverlay();$("prompt").focus();return;
    }
    if(id==="refresh"){await refresh();return;}
    if(id==="create-project"||id==="suggest-project"){modalCreate();return;}
    if(id==="close-dialog"){closeDialog();return;}
    if(id==="suggest-chat"){state.mode="ask";syncMode();$("prompt").focus();return;}
    if(id==="mode-ask"){state.mode="ask";syncMode();return;}
    if(id==="mode-build"){state.mode="build";syncMode();return;}
    if(id==="all-decisions"){selectPanel("decisions");return;}
    if(id==="tools"||id==="settings"||id==="search"){selectPanel(id);return;}
    if(id.startsWith("tab-")){selectPanel(id.slice(4));return;}
    if(id.startsWith("project-")){location.hash=routeUrl(safeNum(id.slice(8)),null);return;}
    if(id==="generate-plan"&&project)return mutate(
      "/api/projects/"+project+"/plan/generate",{},
      "سيُنشئ المصنع خطة جديدة عبر مزود نموذج وقد يستهلك موارد فعلية. متابعة؟");
    if(id==="approve-plan"&&project)return mutate(
      "/api/projects/"+project+"/plan/approve",{approved:true,feedback:""},
      "هل راجعت خطة هذا المشروع؟ الاعتماد يُطلق التنفيذ الحقيقي تلقائيًا وقد يستهلك موارد.");
    if(id==="resume"&&project)return mutate(
      "/api/projects/"+project+"/resume",{},
      "سيستأنف المشروع من نقطة الحفظ ويطلق تشغيلًا حقيقيًا. هل وافقت؟");
    if(id==="pause"&&project)return mutate(
      "/api/projects/"+project+"/pause",{reason:"إيقاف مؤقت بقرار المالك"},
      "سيُرسل طلب إيقاف مؤقت للتنفيذ. متابعة؟");
    if(id==="preflight"&&project)return mutate(
      "/api/projects/"+project+"/preflight",{},
      "إعادة الفحص قد تطلق التنفيذ تلقائيًا إذا اجتاز الفحص. هل وافقت؟");
    if(id.startsWith("gate-")&&project){
      const parts=id.split("-"),gid=safeNum(parts[2]),yes=parts[1]==="yes";
      if(!gid)return;
      return mutate("/api/projects/"+project+"/gates/"+gid,
        {approved:yes,note:"قرار مالك من مساحة Chat Factory"},
        yes?"اعتماد البوابة قد يطلق التنفيذ فورًا. هل راجعت دليلها وتوافق؟":
          "رفض البوابة قد يوقف العمل. هل تريد تسجيل الرفض؟");
    }
    if(id.startsWith("file-")){await previewFile(Number(id.slice(5)));return;}
    if(id==="close-preview"){state.preview=null;renderPanel();return;}
    if(id==="download-preview"){downloadPreview();return;}
    if(id.startsWith("web-")){
      const webMode=id.slice(4);
      if(!["auto","on","off"].includes(webMode))return;
      state.webMode=webMode;
      localStorage.setItem("aes:chat:web-mode",webMode);
      renderPanel();return;
    }
    if(id.startsWith("theme-")){
      const theme=id.slice(6);
      if(!["dark","light"].includes(theme))return;
      document.documentElement.dataset.theme=theme;localStorage.setItem("aes:chat:theme",theme);
      renderPanel();return;
    }
    if(id==="stop-chat"&&state.route.cid){
      if(!window.confirm("إيقاف توليد المحادثة الجارية؟ قد يتوقف عند أقرب نقطة آمنة."))return;
      try{const res=await post(callUrl("/api/chat/stop",{conversation_id:state.route.cid}),{});
        state.banner="رد الخادم: "+(res.message||res.status||"طلب إيقاف مسجل");renderThread();
      }catch(e){report("تعذر تأكيد إيقاف المحادثة: "+e.message,true);}
    }
  }
  async function onSubmit(e){
    if(e.target?.id==="create-project-form"){e.preventDefault();await createProject(e.target);return;}
    if(e.target?.id==="chat-settings-form"){e.preventDefault();await saveChatSettings(e.target);return;}
    if(e.target?.id!=="composer-form")return;
    e.preventDefault();const box=$("prompt"),message=box.value.trim();
    if(!message)return;
    if(state.mode==="build"){modalCreate(message);return;}
    box.value="";box.style.height="";
    await sendMessage(message);
  }
  function wire(){
    document.addEventListener("click",e=>{
      const btn=e.target.closest("[data-action]");
      if(btn){e.preventDefault();handleAction(btn.dataset.action);}
    });
    document.addEventListener("submit",onSubmit);
    $("prompt").addEventListener("keydown",e=>{
      if(e.key==="Enter"&&!e.shiftKey){e.preventDefault();if(!state.streaming)$("composer-form").requestSubmit();}
    });
    $("prompt").addEventListener("input",e=>{
      e.target.style.height="auto";e.target.style.height=Math.min(160,e.target.scrollHeight)+"px";
    });
    document.addEventListener("input",e=>{
      if(e.target.id==="file-search"){state.fileFilter=e.target.value;renderPanel();const f=$("file-search");if(f){f.focus();f.setSelectionRange(f.value.length,f.value.length);}}
      if(e.target.id==="local-search"){
        const q=e.target.value.trim().toLocaleLowerCase();
        $("search-results").innerHTML=state.projects.filter(p=>
          projectName(p).toLocaleLowerCase().includes(q)&&q).slice(0,25).map(p=>
          '<a class="nav-item" href="'+routeUrl(p.id,null)+'">'+esc(projectName(p))+'</a>').join("")+
          state.conversations.filter(c=>(c.title||"").toLocaleLowerCase().includes(q)&&q).slice(0,25).map(c=>
          '<a class="nav-item" href="'+routeUrl(c.project_id,c.conversation_id)+'">'+esc(c.title)+'</a>').join("");
      }
    });
    window.addEventListener("hashchange",openRoute);
    document.addEventListener("visibilitychange",()=>{
      if(!document.hidden&&!state.streaming)loadProject(state.revision);
    });
    setInterval(()=>{
      if(!document.hidden&&!state.streaming&&!state.busy&&state.route.pid)loadProject(state.revision);
    },30000);
    document.documentElement.dataset.theme=localStorage.getItem("aes:chat:theme")==="light"?"light":"dark";
    const priorWebMode=localStorage.getItem("aes:chat:web-mode");
    state.webMode=["auto","on","off"].includes(priorWebMode)?priorWebMode:"auto";
    syncMode();openRoute();
  }
  wire();
})();
