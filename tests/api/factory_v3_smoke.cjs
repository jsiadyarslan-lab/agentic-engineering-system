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
async function fetchMock(url,opts={}){
  calls.push(url);
  if(url==='/api/chat/stream'){
    const id=22;
    const events=[
      {kind:'conversation.bind',scope:{conversation_id:id},details:{conversation_id:id}},
      {kind:'message_delta',scope:{conversation_id:id},delta:'رد '},
      {kind:'message_delta',scope:{conversation_id:999},delta:'تسرب ممنوع'},
      {kind:'message_delta',delta:'حدث بلا نطاق'},
      {kind:'message_completed',scope:{conversation_id:999}},
      {kind:'message_delta',scope:{conversation_id:id},delta:'فعلي'},
      {kind:'message_completed',scope:{conversation_id:id}}
    ].map(x=>'data: '+JSON.stringify(x)+'\n\n');
    let n=0;
    return{ok:true,status:200,body:{getReader(){return{async read(){
      if(n>=events.length)return{done:true};
      return{done:false,value:new TextEncoder().encode(events[n++])}
    }}}}};
  }
  if(url==='/api/projects')return response({projects:[{id:4,name:'مشروع الإنتاج #4',status:'PAUSED',objective:'إنشاء الموقع'}]});
  if(url==='/api/projects/4/state')return response(serverState);
  if(url==='/api/projects/4/conversations')return response({conversations:[{id:22,title:'محادثة حقيقية'}]});
  if(url==='/api/conversations/22/messages')return response({messages:[{role:'user',content:'تحدث'},{role:'assistant',content:'رد فعلي'}]});
  if(url==='/api/conversations/22/move-to-project')return response({project_id:4});
  throw new Error('Unexpected API call: '+url);
}
let lastHash='#/p/4/chat';
const root={innerHTML:'',scrollTop:0,scrollHeight:100};
const listeners={};
const browser={
  document:{
    getElementById(_id){return root},
    documentElement:{setAttribute(){}},
    addEventListener(name,fn){listeners[name]=fn},
    activeElement:null,
    hidden:false
  },
  location:{hash:lastHash},
  history:{replaceState(_a,_b,value){browser.location.hash=value}},
  window:{addEventListener(){},confirm(){return true}},
  fetch:fetchMock,FormData:class{get(name){return name==='message'?'تحدث':''}},
  setTimeout,clearTimeout,setInterval(){},
  AbortController,TextEncoder,TextDecoder,Date,JSON,Number,String,
  console
};
vm.runInNewContext(js+'\n;globalThis.__test={route,state,submitChat,paint};',browser,{timeout:1500});
async function settle(){
  for(let i=0;i<10;i++)await new Promise(resolve=>setImmediate(resolve));
}
(async()=>{
  await settle();
  assert.equal(browser.__test.route().view,'chat','project must open into chat, not dashboard');
  assert(root.innerHTML.includes('aes-chat-layout'),'chat surface must render');
  assert(root.innerHTML.includes('PAUSED'),'backend project status must remain visible');
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
  assert(calls.includes('/api/conversations/22/move-to-project'),'new chat must be linked to project');
  assert(!calls.some(x=>/\/plan\/approve|\/resume|\/gates\//.test(x)),'a question must not execute owner actions');
  process.stdout.write('AES_CHAT_UI_SMOKE_PASS\n');
})().catch(e=>{console.error(e);process.exitCode=1});
