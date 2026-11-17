/* AES conversational workspace contract smoke test (isolated Node harness).
   Never reaches Oracle. Throws if routing, evidence status or SSE behavior regress. */
'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const html=fs.readFileSync(path.resolve(__dirname,'../../src/ui/factory_v3_live.html'),'utf8');
const js=html.match(/<script>([\s\S]*?)<\/script>/)?.[1];
assert(js,'inline factory script exists');
const serverState={id:4,name:'مشروع الإنتاج #4',status:'PAUSED',objective:'إنشاء الموقع',
  gates:[],phases:[],executions:[],evidence:[],events:[],plan:null};
function response(data){return{ok:true,status:200,text:async()=>JSON.stringify(data)}}
const calls=[];
let holdSecondRead=false, releaseSecondRead=null, streamErrorAfterBind=false, brokenStream=false, serverRunning=false, persistBrokenQuestion=true;
let savedMessages=[{id:1,role:'user',content:'تحدث'},{id:2,role:'assistant',content:'رد فعلي',state_badge:'COMPLETED'}];
async function fetchMock(url,opts={}){
  calls.push(url);
  if(url==='/api/chat/stream'){
    const id=22;
    const events=(streamErrorAfterBind?[
      {kind:'conversation.bind',scope:{conversation_id:id},details:{conversation_id:id}},
      {kind:'chat.error',scope:{conversation_id:id},text:'OLD_THREAD_PROVIDER_ERROR'}
    ]:[
      {kind:'conversation.bind',scope:{conversation_id:id},details:{conversation_id:id}},
      {kind:'message_delta',scope:{conversation_id:id},delta:'رد '},
      {kind:'message_delta',scope:{conversation_id:999},delta:'تسرب ممنوع'},
      {kind:'message_delta',delta:'حدث بلا نطاق'},
      {kind:'message_completed',scope:{conversation_id:999}},
      {kind:'message_delta',scope:{conversation_id:id},delta:'فعلي'},
      {kind:'message_completed',scope:{conversation_id:id}}
    ]).map(x=>'data: '+JSON.stringify(x)+'\r\n\r\n');
    const chunks=[events[0],...events.slice(1).flatMap(event=>{
      const line=event.replace(',"scope":',',\r\ndata: "scope":');
      const split=line.indexOf('\r');
      return [line.slice(0,split+1),line.slice(split+1,-3),line.slice(-3)];
    })];
    let n=0;
    return{ok:true,status:200,body:{getReader(){return{async read(){
      if(brokenStream&&n===1){if(persistBrokenQuestion)savedMessages.push({id:3,role:'user',content:'تحدث'});throw new DOMException('original transport detail','AbortError');}
      if(n>=chunks.length)return{done:true};
      if(holdSecondRead&&n===1){await new Promise(resolve=>{releaseSecondRead=resolve});holdSecondRead=false;}
      return{done:false,value:new TextEncoder().encode(chunks[n++])}
    }}}}};
  }
  if(url==='/api/projects')return response({projects:[{id:4,name:'مشروع الإنتاج #4',status:'PAUSED',objective:'إنشاء الموقع'}]});
  if(url==='/api/projects/4/state')return response(serverState);
  if(url==='/api/projects/4/conversations')return response({conversations:[{conversation_id:22,project_id:4,title:'محادثة حقيقية'}]});
  if(url==='/api/conversations/22/messages')return response({conversation_id:22,messages:savedMessages.slice()});
  if(url.startsWith('/api/chat/active?conversation_id=')){const id=Number(url.split('=').at(-1));return response({stream:'chat-'+id,running:id===22&&serverRunning});}
  if(url==='/api/conversations/35')return response({conversation_id:35,title:'محادثة أقدم',project_id:4});
  if(url==='/api/conversations/35/messages')return response({conversation_id:35,messages:[{role:'assistant',content:'رد أقدم'}]});
  if(url==='/api/conversations/41')return response({conversation_id:41,title:'خارج المشروع',project_id:9});
  if(url==='/api/conversations/22')return response({conversation_id:22,project_id:4,title:'محادثة حقيقية'});
  if(url==='/api/chat/stop?conversation_id=22')return response({status:'STOPPING'});
  if(url==='/api/research/providers')return response({providers:[{name:'Real Search Source',effective_status:'STALE',state_reason:'Probe expired'}]});
  if(url==='/api/execution/environments')return response({environments:[{id:7,name:'OCI Worker',backend:'REMOTE_WORKER',state:'NOT_READY',is_default:true}]});
  if(url==='/api/models/config')return response({roles:[{key:'chat',label:'محادثة',selection:{provider:'real-provider',model:'real-model'}}],providers:[{id:'real-provider',label:'Model Provider',state:'غير متصل',reason:'No key'}]});
  throw new Error('Unexpected API call: '+url);
}
let lastHash='#/p/4/chat';
const root={innerHTML:'',scrollTop:0,scrollHeight:100,dataset:{}};
const listeners={};
const browser={
  document:{
    getElementById(_id){return root},
    documentElement:{setAttribute(){}},
    addEventListener(name,fn){listeners[name]=fn},
    querySelector(){return null},
    activeElement:null,
    hidden:false
  },
  location:{hash:lastHash},
  history:{replaceState(_a,_b,value){browser.location.hash=value}},
  window:{addEventListener(){},confirm(){return true}},
  fetch:fetchMock,FormData:class{get(name){return name==='message'?'تحدث':''}},
  setTimeout,clearTimeout,setInterval(){},
  AbortController,DOMException,TextEncoder,TextDecoder,Date,JSON,Number,String,
  console
};
vm.runInNewContext(js+'\n;globalThis.__test={route,state,submitChat,paint,loadAll,handle,followSavedReply};',browser,{timeout:1500});
async function settle(){
  for(let i=0;i<10;i++)await new Promise(resolve=>setImmediate(resolve));
}
(async()=>{
  await settle();
  assert.equal(browser.__test.route().view,'chat','project must open into chat, not dashboard');
  assert(root.innerHTML.includes('aes-chat-layout'),'chat surface must render');
  assert(root.innerHTML.includes('المشروع متوقف مؤقتًا'),'backend project status must remain visible');
  assert(root.innerHTML.includes('محادثة حقيقية'),'existing conversations must load');
  assert.equal(typeof listeners.input,'function','input draft handler must be registered');
  listeners.input({target:{name:'message',value:'مسودة لم ترسل بعد',closest:()=>true}});
  browser.__test.paint();
  assert(root.innerHTML.includes('مسودة لم ترسل بعد'),'draft must persist after a view render');
  await browser.__test.submitChat({});
  await settle();
  assert.equal(browser.__test.state.conversationId,22,'stable conversation binding must be used');
  assert.equal(browser.__test.state.error,'','no false error for complete stream');
  assert(!browser.__test.state.liveText.includes('تسرب ممنوع'),'foreign SSE scope must be rejected');
  assert(!browser.__test.state.liveText.includes('حدث بلا نطاق'),'unscoped SSE must be rejected');
  assert(root.innerHTML.includes('رد فعلي'),'persisted assistant response must render');
  assert(calls.includes('/api/conversations/22'),'new chat must verify its project scope before rendering');
  await browser.__test.loadAll();
  assert.equal(browser.__test.state.conversationId,22,'direct link survives reload using conversation_id');
  assert(root.innerHTML.includes('رد فعلي'),'transcript must be restored on reload');
  assert(root.innerHTML.includes('href="#/p/4/chat/22"'),'chat list must include an actual deep link');
  assert(!calls.some(x=>/\/plan\/approve|\/resume|\/gates\//.test(x)),'a question must not execute owner actions');
  browser.location.hash='#/p/4/chat';
  browser.__test.state.conversationId=null;
  browser.__test.state.messages=null;
  browser.__test.state.error='';
  holdSecondRead=true;
  const pending=browser.__test.submitChat({});
  await settle();
  assert.equal(typeof releaseSecondRead,'function','test stream must pause after first bind');
  browser.location.hash='#/p/4/chat/23';
  browser.__test.state.conversationId=23;
  browser.__test.state.messages=null;
  browser.__test.paint();
  assert(!root.innerHTML.includes('قيد الإرسال'),'pending reply must not render in another conversation');
  releaseSecondRead();
  await pending;
  assert.equal(browser.__test.state.conversationId,23,'in-flight reply must not switch currently selected conversation');
  assert.equal(browser.__test.route().conversationId,23,'navigation link must remain on conversation 23');

  browser.location.hash='#/p/4/chat';
  browser.__test.state.conversationId=null;
  browser.__test.state.messages=null;
  browser.__test.state.error='';
  streamErrorAfterBind=true;
  holdSecondRead=true;
  const interrupted=browser.__test.submitChat({});
  await settle();
  assert.equal(typeof releaseSecondRead,'function','failed stream must be paused before error');
  browser.location.hash='#/p/4/chat/23';
  browser.__test.state.conversationId=23;
  browser.__test.state.error='';
  releaseSecondRead();
  await interrupted;
  assert.equal(browser.__test.state.error,'','error from old conversation must not appear in newly selected thread');
  assert(!root.innerHTML.includes('OLD_THREAD_PROVIDER_ERROR'),'old stream failure must be hidden');
  assert.equal(browser.__test.state.conversationId,23,'an error cannot hijack selected conversation');
  streamErrorAfterBind=false;

  browser.location.hash='#/p/4/outputs';
  browser.__test.state.artifacts={artifacts:Array.from({length:35},(_,i)=>({
    name:'article-'+i+'.html',kind:'file',step_id:i+1,evidence_id:100+i,verdict:'UNVERIFIED',
    sha256:'evidence-sha-'+i
  })).concat([{name:'build.js',kind:'file',step_id:44,evidence_id:999,verdict:'FAILED'}])};
  browser.__test.state.artifactQuery='';
  browser.__test.state.artifactType='all';
  browser.__test.state.artifactLimit=30;
  browser.__test.paint();
  assert(root.innerHTML.includes('عرض المزيد (6)'),'pagination should constrain huge artifact lists');
  assert(!root.innerHTML.includes('article-34.html'),'initial view must not flood all results');
  browser.__test.state.artifactType='code';
  browser.__test.paint();
  assert(root.innerHTML.includes('build.js'),'code filter must show code evidence');
  assert(root.innerHTML.includes('حكم دليل الخطوة: FAILED'),'step verdict must not be upgraded');
  assert(!root.innerHTML.includes('article-0.html'),'code filter must exclude HTML pages');
  browser.__test.state.preview={name:'index.html',text:'<h1>Test</h1><script>evil()</script>'};
  browser.__test.state.previewMode='visual';
  browser.__test.paint();
  assert(root.innerHTML.includes('sandbox=""'),'HTML preview must not inherit running script privileges');
  assert(root.innerHTML.includes('Content-Security-Policy'),'HTML preview must inject restrictive CSP');
  assert(root.innerHTML.includes('&lt;script&gt;evil()&lt;/script&gt;'),'source markup must be encoded in srcdoc attribute');
  browser.__test.state.preview=null;
  browser.location.hash='#/p/4/runs';
  browser.__test.state.details={...serverState,plan:{id:12,approved_by_owner:true},
    phases:[{id:41,plan_id:11,title:'Older'},{id:42,plan_id:12,title:'Current'}]};
  browser.__test.state.steps={steps:[
    {id:111,phase_id:41,phase_title:'Older',objective:'خطوة تاريخية فاشلة',status:'FAILED',attempts:3},
    {id:112,phase_id:42,phase_title:'Current',objective:'خطوة حاليّة ناجحة',status:'COMPLETED',attempts:1}
  ]};
  browser.__test.paint();
  assert(root.innerHTML.includes('خطوات الخطة الحالية (1)'),'current plan should count only its steps');
  assert(root.innerHTML.includes('خطوة حاليّة ناجحة'),'actual objective field must be displayed');
  assert(root.innerHTML.includes('الخطط القديمة (1 خطوة)'),'historical plan must be separate');
  browser.location.hash='#/tools';
  await browser.__test.loadAll();
  assert(root.innerHTML.includes('Real Search Source'),'real research provider must be shown');
  assert(root.innerHTML.includes('STALE'),'expired research probe must not be displayed as READY');
  assert(root.innerHTML.includes('OCI Worker'),'real execution environment must be shown');
  browser.location.hash='#/settings';
  await browser.__test.loadAll();
  assert(root.innerHTML.includes('real-model'),'real role model assignment must be shown');
  assert(root.innerHTML.includes('غير متصل'),'provider configuration missing must remain visible');
  browser.location.hash='#/p/4/chat/22';
  browser.__test.state.conversationId=22;
  browser.__test.state.busy=true;
  browser.__test.state.pendingProjectId=4;
  browser.__test.state.pendingConversationId=22;
  browser.__test.state.activeChatId=22;
  browser.__test.state.stopPending=false;
  browser.__test.paint();
  assert(root.innerHTML.includes('طلب إيقاف الرد'),'stop button must be offered during real stream');
  await browser.__test.handle('stop-chat');
  assert(calls.includes('/api/chat/stop?conversation_id=22'),'stop must call the server endpoint');
  assert(browser.__test.state.streamNotice.includes('طلب الإيقاف قُبل'),'STOPPING is not falsely reported as finished');

  browser.__test.state.busy=false;
  browser.location.hash='#/p/4/chat/35';
  await browser.__test.loadAll();
  assert(root.innerHTML.includes('رد أقدم'),'old chat not in project list must still load after ownership check');
  browser.location.hash='#/p/4/chat/41';
  await browser.__test.loadAll();
  assert(root.innerHTML.includes('تعذر فتح المحادثة'),'invalid direct links must show an error, not a blank new chat');
  assert(!calls.includes('/api/conversations/41/messages'),'do not load another project’s transcript');
  assert(root.innerHTML.includes('aria-label="رسالة للمساعد" disabled'),'invalid direct link disables sending');
  browser.location.hash='#/p/4/chat/22';
  await browser.__test.loadAll();
  const postsBefore=calls.filter(x=>x==='/api/chat/stream').length;
  brokenStream=true;serverRunning=true;
  await browser.__test.submitChat({});
  assert.equal(browser.__test.state.serverChat,'running');
  assert(root.innerHTML.includes('الخادم ما زال يعالج الرسالة'));
  assert(root.innerHTML.includes('aria-label="رسالة للمساعد" disabled'));
  assert(!root.innerHTML.includes('original transport detail'));
  await browser.__test.submitChat({});
  assert.equal(calls.filter(x=>x==='/api/chat/stream').length,postsBefore+1,'no automatic or duplicate post while backend is active');
  await browser.__test.loadAll();
  assert(root.innerHTML.includes('الخادم يعالج رسالة في هذه المحادثة.'),'reload detects the running server job');
  savedMessages.push({id:4,role:'assistant',content:'رد وصل بعد انقطاع العرض',state_badge:'COMPLETED'});
  serverRunning=false;
  await browser.__test.followSavedReply();
  assert(root.innerHTML.includes('رد وصل بعد انقطاع العرض'));
  assert(root.innerHTML.includes('وصل الرد المحفوظ من الخادم.'));
  assert(!root.innerHTML.includes('aria-label="رسالة للمساعد" disabled'));
  assert.equal(calls.filter(x=>x==='/api/chat/stream').length,postsBefore+1);
  persistBrokenQuestion=false;
  await browser.__test.submitChat({});
  assert(!root.innerHTML.includes('وصل الرد المحفوظ من الخادم.'),'historical reply cannot prove new delivery');
  await browser.__test.followSavedReply();
  assert(root.innerHTML.includes('لم يحفظ الخادم ردًا نهائيًا.'));
  assert.equal(calls.filter(x=>x==='/api/chat/stream').length,postsBefore+2);
  process.stdout.write('AES_CHAT_UI_SMOKE_PASS\n');
})().catch(e=>{console.error(e);process.exitCode=1});
