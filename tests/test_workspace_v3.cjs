'use strict';
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('src/ui/workspace-v3.html','utf8').match(/<script>([\s\S]+)<\/script>/)[1];
const app={innerHTML:'',contains(){return false},querySelectorAll(){return []}};
const dialog={open:false,innerHTML:'',querySelector(){},addEventListener(){},showModal(){this.open=true},close(){this.open=false}};
const elements={app,dialog,toast:{}};const pending={};const requests=[];const queued=[];const headers={'content-type':'application/json'};
const live={
 '/api/projects':{projects:[{id:4,name:'Live editorial project',status:'AWAITING_OWNER_APPROVAL'}]},
 '/api/conversations':{conversations:[{conversation_id:92,title:'Live chat',project_id:4}]},
 '/health':{app:'Agentic Engineering System',version:'4.0.0'},
 '/api/projects/4/state':{id:4,name:'Live editorial project',objective:'Real goal',status:'AWAITING_OWNER_APPROVAL',plan:{version:2},gates:[],events:[{kind:'EXECUTION_FAILED',payload:{reason:'Real server reason'}}]},
 '/api/projects/4/runtime':{project_id:4,status:'AWAITING_OWNER_APPROVAL',last_error:'Worker heartbeat lost',waiting_for:{label:'اعتماد المالك للخطة'},run_id:'run-17',available_actions:[]},
 '/api/projects/4/conversations':{conversations:[{conversation_id:92,title:'Live chat',project_id:4}]},
 '/api/projects/4/steps':{steps:[{id:1047,objective:'Build site',status:'FAILED',last_error:'Real failure'}]},
 '/api/projects/4/executions':{executions:[]},
 '/api/conversations/92/messages':{messages:[{id:1,role:'assistant',content:'Stored reply'}]},
 '/api/projects/4/artifacts':{artifacts:[{name:'report.md',step_id:1047,kind:'file',sha256:'aab'}]},
 '/api/projects/4/artifacts/content?step_id=1047&name=report.md':{plain:'Actual report content'},
 '/api/projects/4/plan/approve':{launch:{launched:false,detail:'runner is blocked',reason:'conflict'}},
};
const location={hash:'#/p/4'};
let active=false;const events={};
function response(v){if(v===undefined)return new Response(JSON.stringify({detail:'unexpected route'}),{status:404,headers});return typeof v.plain==='string'?new Response(v.plain,{headers:{'content-type':'text/plain'}}):new Response(JSON.stringify(v),{headers})}
const cx=vm.createContext({location,AbortController,Response,TextDecoder,URLSearchParams,setTimeout,clearTimeout,setInterval(){},requestAnimationFrame(f){queued.push(f)},document:{documentElement:{dataset:{}},getElementById:k=>elements[k],addEventListener(k,f){events[k]=f}},window:{scrollTo(){},addEventListener(k,f){events[k]=f}},fetch:(path,req)=>{requests.push([path,req.method,req.body]);if(!active&&path==='/api/conversations')return new Promise(r=>pending.nav=r);return Promise.resolve(response(live[path]))}});
const js=s=>vm.runInContext(s,cx);
async function flush(){for(let i=0;i<5;i++){await new Promise(r=>setImmediate(r));while(queued.length)queued.shift()()}}
async function visit(h){location.hash=h;events.hashchange();await flush()}
(async()=>{
 js(source);await flush();
 assert.match(app.innerHTML,/Live editorial project/);
 assert.match(app.innerHTML,/Worker heartbeat lost/);
 assert.doesNotMatch(app.innerHTML,/manifest\.json|A02/);
 assert.equal(requests.some(([p,m])=>m==='POST'),false);
 active=true;pending.nav(response(live['/api/conversations']));await flush();
 await visit('#/p/4/run/evidence');
 assert.match(app.innerHTML,/Build site/);assert.match(app.innerHTML,/Real server reason/);
 await visit('#/p/4/outputs');js('openArt(S.route,0)');await flush();
 assert.match(app.innerHTML,/Actual report content/);
 await visit('#/p/4/decisions');
 assert.match(app.innerHTML,/خطة تنتظر اعتمادك/);
 js("eventAction('approve:4')");
 assert.match(dialog.innerHTML,/قد يطلق التنفيذ فورًا/);
 assert.equal(requests.some(([p,m])=>m==='POST'),false);
 js("eventAction('confirm')");await flush();
 assert.deepEqual(requests.find(([p,m])=>m==='POST'),['/api/projects/4/plan/approve','POST','{"approved":true}']);
 assert.match(elements.toast.textContent,/runner is blocked/);
 await visit('#/p/4/chat/92');assert.match(app.innerHTML,/Stored reply/);
 const wire=new Response('data: {"kind":"message_delta","delta":"real "}\r\n\r\ndata: {"kind":"message_completed"}\r\n\r\n',{headers:{'content-type':'text/event-stream'}});
 cx.wire=wire;assert.equal(await js("sse(wire,e=>e.kind==='message_completed'?false:undefined,1000)"),true);
 assert.equal(requests.some(([p])=>!p.startsWith('/')),false);
 console.log('PASS live UI contracts: project fast render, historical failure, artifact text, explicit real approval, failed launch, saved conversation and SSE framing');
})().catch(e=>{console.error(e);process.exitCode=1});
