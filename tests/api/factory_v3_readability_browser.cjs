/* Local browser acceptance with contract fixtures. No requests are sent to Oracle. */
'use strict';
const assert=require('node:assert/strict');
const http=require('node:http');
const fs=require('node:fs');
const path=require('node:path');
const {chromium}=require('playwright');
const html=fs.readFileSync(process.env.AES_BROWSER_TEST_HTML||path.join(__dirname,'../../src/ui/factory_v3_live.html'));
const goal='SPEC_ENGLISH_ONLY '+('Long engineering requirements with Arabic identifiers وتفاصيل. '.repeat(120));
const project={id:4,name:'موقع إخباري متعدد الصفحات',status:'PAUSED',objective:goal,gates:[],events:[]};
const chats=[{conversation_id:26,project_id:4,title:'؟'},{conversation_id:31,project_id:4,title:'محادثة ثانية'}];
const rich='### حالة التنفيذ\n\n**لم يبدأ تشغيل جديد.**\n\n- أول خطوة\n- ثاني خطوة\n\n| الملف | الحالة |\n| --- | --- |\n| index.html | محفوظ |\n\n```js\nconst x = 42;\n```\n\n[الدليل](https://example.com/)\n\n<label>نص حرفي غير منفّذ</label>\n';
const saved=new Map([[26,[{role:'user',content:'رسالة محفوظة'},{role:'assistant',content:'رد سابق من الاختبار'},{role:'assistant',content:rich},...Array.from({length:32},(_,n)=>({role:'assistant',content:'Content '+n}))]],[31,[{role:'assistant',content:'محتوى المحادثة الثانية'}]],[90,[{role:'assistant',content:'سجل قديم ليس في القائمة'}]]]);
const trace=[];
let streamScenario='ok', waitForFirstDelta=null, waitForCompletion=null;
const server=http.createServer(async(req,res)=>{
 const url=req.url;
 trace.push([req.method,url]);
 const json=(data,code=200)=>{res.writeHead(code,{'Content-Type':'application/json'});res.end(JSON.stringify(data));};
 if(url.startsWith('/static/')){res.writeHead(200,{'Content-Type':'text/html;charset=utf-8'});res.end(html);return;}
 if(url.startsWith('/api/chat/active?conversation_id=')){const id=Number(url.split('=').at(-1));return json({running:false,stream:'chat-'+id});}
 if(url==='/api/projects')return json({projects:[project]});
 if(url==='/api/projects/4/state')return json(project);
 if(url==='/api/projects/4/conversations')return json({project_id:4,conversations:chats});
 if(url==='/api/projects/4/artifacts')return json({artifacts:[]});
 if(url==='/api/conversations/90')return json({conversation_id:90,project_id:4,title:'محادثة قديمة'});
 if(url==='/api/conversations/8')return json({conversation_id:8,project_id:77,title:'غير تابعة'});
 if(url==='/api/conversations/404')return json({detail:'محادثة غير معروفة'},404);
 const messages=/^\/api\/conversations\/(\d+)\/messages$/.exec(url);
 if(messages){const id=Number(messages[1]);return json({conversation_id:id,messages:saved.get(id)||[]});}
 if(req.method==='POST'&&url==='/api/chat/stream'){
   const reqChunks=[];for await(const c of req)reqChunks.push(c);
   const {message,conversation_id:id,project_id}=JSON.parse(Buffer.concat(reqChunks));
   assert.equal(project_id,4,'scope must be sent in the original request');
   if(streamScenario==='auth')return json({detail:'private diagnostics'},401);
   if(id!==26)return json({detail:'Must continue conversation 26'},422);
   const bind='data: '+JSON.stringify({kind:'conversation.bind',scope:{conversation_id:id}})+'\r\n\r\n';
   const delta='data: {"kind":"message_delta","scope":{"conversation_id":26},\r\ndata: "delta":"رد حي من بث الاختبار"}\r\n\r\n';
   const complete='data: '+JSON.stringify({kind:'message_completed',scope:{conversation_id:id}})+'\r\n\r\n';
   res.writeHead(200,{'content-type':'text/event-stream','cache-control':'no-cache'});
   res.flushHeaders();
   res.write(bind);
   if(waitForFirstDelta)await waitForFirstDelta;
   else await new Promise(r=>setTimeout(r,240));
   res.write(delta.slice(0,-3));res.write(delta.slice(-3));
   if(waitForCompletion)await waitForCompletion;
   else await new Promise(r=>setTimeout(r,180));
   if(streamScenario==='ok'){
     saved.get(id).push({id:91,role:'user',content:message},
       {id:92,role:'assistant',content:'رد محفوظ بعد البث',state_badge:'COMPLETED'});
   }
   res.write(complete);
   res.end();return;
 }
 return json({detail:'unknown route'},404);
});
async function main(){
 await new Promise(r=>server.listen(0,'127.0.0.1',r));
 const origin='http://127.0.0.1:'+server.address().port;
 const browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_PATH?{executablePath:process.env.CHROMIUM_PATH}:{})});
 try{
   for(const [width,height] of [[1440,761],[900,650],[390,720]]){
     const page=await browser.newPage({viewport:{width,height}});
     await page.addInitScript(()=>{
       const timer=window.setTimeout.bind(window);
       window.setTimeout=(fn,ms,...args)=>timer(fn,ms===12000&&String(fn).includes('لم يصل نص الرد بعد')?60:ms,...args);
     });
     const errors=[];page.on('pageerror',e=>errors.push(e.message));
     await page.route('**/*',route=>route.request().url().startsWith(origin+'/')?route.continue():route.abort());
     const url=origin+'/static/factory_v3_live.html#/p/4/chat/26';
     await page.goto(url);
     await page.getByRole('heading',{name:'محادثة 26',exact:true}).waitFor({timeout:3500});
     const input=page.getByRole('textbox',{name:'رسالة للمساعد'}),send=page.getByRole('button',{name:'إرسال ↑'});
     await page.getByText('رد سابق من الاختبار',{exact:true}).waitFor({state:'attached'});
     assert.equal(await page.getByText(/SPEC_ENGLISH_ONLY/).count(),0);
     const b=await input.boundingBox(),s=await send.boundingBox();
     assert.ok(b.y>=0&&b.y+b.height<=height&&s.y+s.height<=height,JSON.stringify({width,height,input:b,send:s}));
     const scroll=await page.locator('.aes-chat-thread').evaluate(e=>({inner:e.scrollHeight,shown:e.clientHeight,doc:document.documentElement.scrollHeight}));
     assert.ok(scroll.inner>scroll.shown&&scroll.doc<=height,JSON.stringify(scroll));
     assert.equal(await input.isEnabled(),true);
     await page.getByText('تنفيذ المشروع متوقف مؤقتًا · المحادثة متاحة',{exact:true}).waitFor();
     const body=page.locator('.aes-reply-body').filter({hasText:'حالة التنفيذ'});
     assert.equal(await body.getByRole('heading',{name:'حالة التنفيذ'}).count(),1);
     assert.equal(await body.locator('strong').textContent(),'لم يبدأ تشغيل جديد.');
     assert.equal(await body.getByRole('listitem').count(),2);
     assert.equal(await body.getByRole('cell',{name:'index.html'}).count(),1);
     assert.equal(await body.locator('pre').getAttribute('dir'),'ltr');
     assert.equal(await body.getByRole('link',{name:'الدليل'}).getAttribute('rel'),'noopener noreferrer');
     assert.equal(await body.locator('label').count(),0);
     assert.ok((await body.textContent()).includes('<label>نص حرفي غير منفّذ</label>'));
     assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));

     if(width===1440){
       if(process.env.AES_TEST_SCREENSHOT){
         await body.getByRole('heading',{name:'حالة التنفيذ'}).scrollIntoViewIfNeeded();
         await page.screenshot({path:process.env.AES_TEST_SCREENSHOT});
       }
       let unblockDelta, unblockCompletion;
       waitForFirstDelta=new Promise(resolve=>{unblockDelta=resolve;});
       waitForCompletion=new Promise(resolve=>{unblockCompletion=resolve;});
       await input.fill('رسالة اختبار ثبات المحادثة');
       await send.click();
       try{
         const waiting=page.locator('.aes-wait-message').filter({hasText:'الرسالة لدى الخادم. لم يصل نص الرد بعد.'});
         await waiting.waitFor({timeout:8000});
       }catch(error){
         console.error('Chat status at failure',JSON.stringify({
           notices:await page.locator('.aes-chat-feedback,.aes-wait-message').allTextContents(),
           sent:trace.filter(([m])=>m==='POST').map(([,u])=>u),
         }));
         unblockCompletion();waitForCompletion=null;
         throw error;
       }finally{unblockDelta();waitForFirstDelta=null;}
       try{
         await page.locator('.aes-stream-content').filter({hasText:'رد حي من بث الاختبار'}).waitFor({timeout:8000});
       }finally{unblockCompletion();waitForCompletion=null;}
       await page.getByText('رد محفوظ بعد البث',{exact:true}).waitFor();
       await page.getByText('حُفظ الرد في المحادثة.',{exact:true}).waitFor();
       await page.reload();
       await page.getByText('رد محفوظ بعد البث',{exact:true}).waitFor();
       assert.equal(page.url(),url);
       const countBefore=trace.filter(([m])=>m==='POST').length;
       await page.getByRole('link',{name:'محادثة ثانية',exact:true}).click();
       await page.getByText('محتوى المحادثة الثانية',{exact:true}).waitFor();
       await page.goBack();
       await page.getByText('رد محفوظ بعد البث',{exact:true}).waitFor();
       await page.getByRole('link',{name:'نظرة عامة'}).click();
       const spec=page.getByText(/SPEC_ENGLISH_ONLY/);
       await spec.waitFor();
       assert.equal(await spec.evaluate(e=>getComputedStyle(e).direction),'ltr');
       await page.goto(url.replace('/26','/90'));
       await page.getByText('سجل قديم ليس في القائمة',{exact:true}).waitFor();
       await page.goto(url.replace('/26','/8'));
       await page.getByText('المحادثة لا تنتمي إلى هذا المشروع.',{exact:true}).waitFor();
       assert.equal(await input.isDisabled(),true);
       assert.equal(trace.some(([,p])=>p==='/api/conversations/8/messages'),false);
       await page.goto(url.replace('/26','/404'));
       await page.getByText('تعذر فتح المحادثة',{exact:true}).waitFor();
       assert.equal(await input.isDisabled(),true);
       assert.equal(trace.filter(([m])=>m==='POST').length,countBefore);
       await page.goto(url);
       await page.getByText('رد محفوظ بعد البث',{exact:true}).waitFor();
       streamScenario='auth';
       await input.fill('مسودة تحفظ مع رفض الدخول');
       await send.click();
       await page.getByRole('alert').getByText('انتهت جلسة الدخول. سجّل الدخول ثم أعد الإرسال.',{exact:true}).waitFor();
       assert.equal(await input.inputValue(),'مسودة تحفظ مع رفض الدخول');
       assert.equal(await page.getByText('private diagnostics',{exact:false}).count(),0);
       streamScenario='missing_saved_reply';
       await input.fill('لا تعتمد الاكتمال دون السجل');
       await send.click();
       await page.getByRole('alert').getByText('وصل إقرار بانتهاء الرد، لكن لم يتأكد حفظه في السجل.',{exact:true}).waitFor();
       assert.equal(await page.getByText('حُفظ الرد في المحادثة.',{exact:true}).count(),0);
       assert.equal(await input.isDisabled(),true);
       assert.equal(trace.filter(([m])=>m==='POST').length,countBefore+2,'exactly one POST for each explicit send');
       assert.equal(trace.some(([m,u])=>m==='POST'&&u!=='/api/chat/stream'),false,'chat must not launch project work');
     }
     assert.deepEqual(errors,[]);
     await page.close();
     console.log('PASS',width+'x'+height,'direct-link, visible composer, scrolling transcript');
   }
   console.log('AES_CHAT_BROWSER_PASS');
 }finally{await browser.close();server.close();}
}
if(process.env.AES_BROWSER_SERVE)server.listen(Number(process.env.AES_BROWSER_SERVE),'127.0.0.1',()=>console.log('LOCAL_FIXTURE_READY',server.address().port));
else main().catch(error=>{console.error(error);server.close();process.exitCode=1;});
