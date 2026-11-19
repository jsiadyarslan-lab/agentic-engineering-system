const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const [file, asset]=process.argv.slice(2);
const {rows,pid,qid,cid}=JSON.parse(fs.readFileSync(file,'utf-8'));
const page=fs.readFileSync(asset,'utf-8'), script=page.match(/<script>([\s\S]*?)<\/script>/)[1];
const root={innerHTML:'',dataset:{}}, requests=[], dialogs=[];
const browser={
 document:{getElementById:()=>root,querySelector:()=>null,addEventListener(){},documentElement:{setAttribute(){}}},
 window:{addEventListener(){},confirm:msg=>(dialogs.push(msg),false)},
 location:{hash:'#/p/'+pid+'/chat/'+cid},
 setTimeout,clearTimeout,setInterval(){},AbortController,TextEncoder,TextDecoder,console,
 async fetch(path,options){requests.push({path,method:options?.method||'GET'});
  assert.equal(options?.method||'GET','GET'); assert(Object.hasOwn(rows,path),path);
  return {ok:true,text:async()=>JSON.stringify(rows[path])};
 }
};
vm.runInNewContext(script+'\n;globalThis.test={loadAll,handle,state};',browser);
(async()=>{
 const {loadAll,handle}=browser.test;
 await loadAll();
 assert.match(root.innerHTML,/رد المحادثة الحية/);
 assert.match(root.innerHTML,/name="message"/);
 const nav=root.innerHTML; for(const v of ['chat','plan','runs','outputs','decisions']) assert(nav.includes('#/p/'+pid+'/'+v),v);
 const go=async (id,view)=>{browser.location.hash='#/p/'+id+'/'+view;await loadAll();};
 await go(pid,'plan');
 assert.match(root.innerHTML,/إنشاء الهيكل/);
 assert.match(root.innerHTML,/حفظ ملف موثق/);
 assert.match(root.innerHTML,/معتمد/);
 await go(pid,'runs');
 assert.match(root.innerHTML,/متعطّل · لا تشغيل نشط/);
 assert.match(root.innerHTML,/web_search · STALE/);
 assert.match(root.innerHTML,/آخر حالة محفوظة/);
 assert.match(root.innerHTML,/المحاولة #/);
 await handle('resume');
 assert(dialogs.length===1&&dialogs[0].includes('استئناف'));
 assert(requests.every(r=>r.method==='GET'));
 await go(pid,'evidence');
 assert.match(root.innerHTML,/تشخيص حجب/);
 await go(qid,'outputs');
 assert.match(root.innerHTML,/لا أدلة محفوظة/);
 assert.doesNotMatch(root.innerHTML,/تشخيص حجب/);
 console.log('WORKSPACE_TABS_SAME_PROJECT_PASS');
})().catch(e=>{console.error(e);process.exitCode=1;});
