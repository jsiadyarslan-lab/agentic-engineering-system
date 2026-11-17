
/* Browser acceptance for the new AES Chat Factory preview only.
   Fixtures are created IN THIS TEST, not included in the production bundle. */
const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const BASE = process.env.AES_UI_URL || "http://127.0.0.1:8010/workspace";
const OUTPUT = process.env.AES_UI_SCREENSHOTS || "browser-artifacts";
const project = {id:4,name:"موقع إخباري عربي تجريبي",objective:"إنشاء 12 مقالًا عربيًا مع بحث",status:"PAUSED"};
const snapshot = {
  ...project,phases:[{id:1,title:"Foundation",status:"COMPLETED"}],
  gates:[],events:[{kind:"JOB_INTERRUPTED",id:1,message:"لا نبضة منذ 311 ثانية"}],
  executions:[],evidence:[],plan:{id:1,version:2,approved_by_owner:true},
  execution_gate:{blocked_reason:"توقف العامل. لم تُستأنف الدورة تلقائيًا"}
};
const json=(route,data,status=200)=>route.fulfill({
  status,contentType:"application/json; charset=utf-8",body:JSON.stringify(data)
});
let stored = [];
let convId=51;
let scopedPosted = null;
let workflowPosts = 0;
async function setup(page) {
  await page.route("**/api/**",async route=>{
    const request=route.request(),u=new URL(request.url()),p=u.pathname;
    if(request.method()==="POST" && p.includes("/api/projects/4/")){
      workflowPosts++;
      return json(route,{launch:{launched:false,reason:"not_ready"}});
    }
    if(p==="/api/projects" && request.method()==="GET")return json(route,{projects:[project],recovery:[],active_run:null});
    if(p==="/api/conversations" && request.method()==="GET")
      return json(route,{conversations:stored.length?[{conversation_id:convId,title:"استعلام",project_id:4}]:[]});
    if(p==="/api/projects/4/state")return json(route,snapshot);
    if(p==="/api/projects/4/steps")return json(route,{steps:[{id:1052,phase_title:"Build",objective:"Create build.js",status:"COMPLETED"}]});
    if(p==="/api/projects/4/artifacts")return json(route,{artifacts:[{name:"index.html",kind:"file",step_id:1052,sha256:"abcdef",bytes:140,verdict:"PASS"}]});
    if(p==="/api/projects/4/artifacts/content")return route.fulfill({status:200,contentType:"text/plain",body:'{"headline":"محتوى حقيقي من المثال"}'});
    if(p==="/api/providers")return json(route,{providers:[]});
    if(p==="/api/environment/readiness")return json(route,{state:"READY"});
    if(p==="/api/conversations/51")return json(route,{conversation_id:51,project_id:4,title:"استعلام"});
    if(p==="/api/conversations/51/messages")return json(route,{conversation_id:51,messages:stored});
    if(p==="/api/chat/active")return json(route,{running:false,last_seq:4});
    if(p==="/api/chat/stream" && request.method()==="POST"){
      scopedPosted=JSON.parse(request.postData());
      assert.equal(scopedPosted.project_id,4,"scope must be present before first turn");
      const user=scopedPosted.message;
      stored=[{role:"user",content:user,created_at:"2026-11-17T19:00:00Z"},
              {role:"assistant",content:"رد موثق من اختبار محلي",state_badge:"COMPLETED"}];
      const event=(kind,extra={})=>({
        kind,seq:kind==="conversation.bind"?1:kind==="message_delta"?2:3,
        message_id:"msg-ui-test",
        scope:{project_id:4,conversation_id:51,message_id:"msg-ui-test",stream:"chat-51"},
        details:{conversation_id:51},...extra
      });
      const data=[event("conversation.bind"),event("message_delta",{delta:"رد موثق من اختبار محلي"}),
                  event("message_completed"),{kind:"stream.done",seq:4}];
      return route.fulfill({status:200,contentType:"text/event-stream",headers:{"Cache-Control":"no-cache"},
        body:data.map(e=>"data: "+JSON.stringify(e)+"\n\n").join("")});
    }
    return json(route,{detail:"Not Found"},404);
  });
}
(async()=>{
  fs.mkdirSync(OUTPUT,{recursive:true});
  const browser=await chromium.launch({headless:true});
  try{
    const desktop=await browser.newPage({viewport:{width:1366,height:850},deviceScaleFactor:1});
    const errors=[];
    desktop.on("pageerror",e=>errors.push(e.message));
    await setup(desktop);
    await desktop.goto(BASE,{waitUntil:"domcontentloaded"});
    await desktop.waitForSelector("#projects-list a.nav-item",{timeout:15000});
    assert.match(await desktop.locator("#thread").innerText(),/ماذا تريد أن تنجز اليوم/);
    await desktop.screenshot({path:path.join(OUTPUT,"01-home-desktop.png"),fullPage:true});
    await desktop.goto(BASE+"#/p/4",{waitUntil:"domcontentloaded"});
    await desktop.getByText("توقف العامل. لم تُستأنف الدورة تلقائيًا").waitFor({timeout:15000});
    assert.match(await desktop.locator("#thread").innerText(),/PAUSED/);
    // Diagnostics must not be the page's default initial content.
    assert.equal(await desktop.locator("#thread").getByText("JOB_INTERRUPTED").count(),0);
    await desktop.screenshot({path:path.join(OUTPUT,"02-project-desktop.png"),fullPage:true});
    await desktop.locator('button[data-action="tab-outputs"]').first().click();
    await desktop.getByText("index.html").waitFor({timeout:15000});
    await desktop.locator('button[data-action="file-0"]').click();
    await desktop.getByText('{"headline":"محتوى حقيقي من المثال"}').waitFor({timeout:12000});
    await desktop.screenshot({path:path.join(OUTPUT,"03-evidence-preview.png"),fullPage:true});
    await desktop.locator('button[data-action="inspector-close"]').click();
    await desktop.locator("#prompt").fill("ما آخر تقدم للمشروع؟");
    await desktop.locator("#composer-form").evaluate(form=>form.requestSubmit());
    await desktop.getByText("رد موثق من اختبار محلي").waitFor({timeout:15000});
    assert.equal(scopedPosted.project_id,4);
    assert.equal(scopedPosted.message,"ما آخر تقدم للمشروع؟");
    assert.equal(workflowPosts,0,"chat must never start an engineering job");
    await desktop.screenshot({path:path.join(OUTPUT,"04-scoped-chat-desktop.png"),fullPage:true});
    await desktop.locator('button[data-action="tab-runs"]').first().click();
    await desktop.getByText("Create build.js").waitFor({timeout:15000});
    assert.equal(workflowPosts,0);
    assert.deepEqual(errors,[],"browser JS exceptions: "+errors.join(";"));

    const mobile=await browser.newPage({viewport:{width:390,height:844},deviceScaleFactor:1,isMobile:true});
    const mobileErrors=[];
    mobile.on("pageerror",e=>mobileErrors.push(e.message));
    await setup(mobile);
    await mobile.goto(BASE+"#/p/4",{waitUntil:"domcontentloaded"});
    await mobile.getByText("توقف العامل. لم تُستأنف الدورة تلقائيًا").waitFor({timeout:15000});
    assert.equal(await mobile.locator("#sidebar").evaluate(x=>x.classList.contains("open")),false);
    await mobile.locator("#sidebar-toggle").click();
    assert.equal(await mobile.locator("#sidebar").evaluate(x=>x.classList.contains("open")),true);
    await mobile.locator("#veil").click({position:{x:8,y:300}});
    await mobile.screenshot({path:path.join(OUTPUT,"05-project-mobile.png"),fullPage:true});
    assert.deepEqual(mobileErrors,[]);
    console.log("AES_CHAT_FACTORY_BROWSER_PASS desktop mobile scopes previews no-fake-launch");
  }finally{await browser.close();}
})().catch(err=>{console.error("AES_CHAT_FACTORY_BROWSER_FAIL",err.stack||String(err));process.exitCode=1;});
