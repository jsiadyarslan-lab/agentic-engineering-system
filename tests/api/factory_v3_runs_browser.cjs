/* Local UI regression. Project/attempt IDs reproduce the contract, not live Oracle data. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');

const html = fs.readFileSync(path.join(__dirname, '../../src/ui/factory_v3_live.html'));
const phaseTitle = 'إعداد المشروع وإنشاء الهيكل الأولي وتوثيق ملفات البناء الأساسية';
const step = {id:1058, phase_id:27, status:'READY', attempts:2, objective:'إنشاء هيكل المشروع'};
const project = {id:5, name:'مشروع 5 — اختبار محلي', status:'BLOCKED'};
const snapshot = {...project, active_run:null, current_step_id:1058, current_phase_id:27,
  plan:{id:9, approved_by_owner:true}, phases:[{id:27, plan_id:9, status:'RUNNING', title:phaseTitle}],
  execution_gate:{state:'APPROVED_BUT_BLOCKED', step_id:1058, execution_id:673,
    reason:'web_search: STALE — انتهت صلاحية فحص مزوّد البحث',
    owner_action:'افحص جاهزية مزوّد البحث، ثم راجع الخطوة.'},
  evidence:[], executions:[{id:673,status:'FAILED'},{id:672,status:'FAILED'}],
  gates:[], events:[]};
const variants = {
  foreign:{...snapshot, active_run:{project_id:4, job_id:91}},
  active:{...snapshot, status:'RUNNING', active_run:{project_id:5, job_id:92},
    execution_gate:{state:'OPEN'}},
  unclassified:{...snapshot, execution_gate:{state:'OPEN'},
    last_error:'لم يكتمل البناء بالأدلة المطلوبة.'},
};
const mutations = [];
const server = http.createServer((req, res) => {
  const json = (body, status=200) => {
    res.writeHead(status, {'Content-Type':'application/json'});
    res.end(JSON.stringify(body));
  };
  if (req.method !== 'GET') {
    mutations.push(req.url);
    return json({error:'read-only test server'},405);
  }
  const route = new URL(req.url, 'http://127.0.0.1').pathname;
  if (route === '/static/factory_v3_live.html') {
    res.writeHead(200, {'Content-Type':'text/html; charset=utf-8'});
    return res.end(html);
  }
  if (route === '/api/projects') return json({projects:[project]});
  if (route === '/api/projects/5/state') {
    const scenario = new URL(req.headers.referer || 'http://127.0.0.1')
      .searchParams.get('scenario');
    return json(Object.hasOwn(variants, scenario) ? variants[scenario] : snapshot);
  }
  if (route === '/api/projects/5/steps') return json({steps:[step]});
  if (route === '/api/projects/5/runtime') return json({});
  if (route === '/api/projects/5/artifacts') return json({artifacts:[]});
  return json({},404);
});

async function main() {
  const {chromium} = require('playwright');
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const origin = 'http://127.0.0.1:' + server.address().port;
  const url = scenario => origin+'/static/factory_v3_live.html?scenario='+scenario+'#/p/5/runs';
  const browser = await chromium.launch({
    headless:true, ...(process.env.CHROMIUM_PATH ? {executablePath:process.env.CHROMIUM_PATH} : {}),
  });
  try {
    for (const width of [1440, 900, 390]) {
      const page = await browser.newPage({viewport:{width,height:760}});
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      await page.goto(url('blocked'));
      await page.getByRole('heading',{name:'متعطّل · لا تشغيل نشط',exact:true}).waitFor();
      const summary = page.locator('.aes-run-summary');
      assert.match(await summary.innerText(), /الخطوة 1058/);
      assert.match(await summary.innerText(), /web_search: STALE/);
      assert.match(await summary.innerText(), /لا دليل تحقق محفوظ/);
      assert.doesNotMatch(await summary.innerText(), /إضافة بيئة/);
      const row = page.locator('.aes-phase-row').filter({hasText:phaseTitle});
      assert.equal(await row.locator('small').textContent(), 'آخر حالة محفوظة');
      const sizes = await row.evaluate(e => {
        const size = cls => e.querySelector(cls).getBoundingClientRect();
        return {title:size('.aes-phase-title').width, badge:size('.status').width,
          overflow:document.documentElement.scrollWidth>innerWidth};
      });
      assert.ok(sizes.title > sizes.badge * 1.5 && !sizes.overflow, JSON.stringify(sizes));
      console.log('PASS', width, JSON.stringify(sizes));
      if (width === 1440) {
        await page.goto(url('foreign'));
        await page.getByRole('heading',{name:'متعطّل · لا تشغيل نشط',exact:true}).waitFor();
        assert.equal(await page.getByRole('button',{name:'إيقاف التشغيل'}).count(),0);
        await page.goto(url('active'));
        await page.getByRole('heading',{name:'قيد التنفيذ · تشغيل نشط',exact:true}).waitFor();
        assert.equal(await row.locator('small').count(),0);
        await page.goto(url('unclassified'));
        await page.getByText('لم يكتمل البناء بالأدلة المطلوبة.',{exact:true}).waitFor();
        assert.doesNotMatch(await summary.innerText(), /web_search/);
      }
      assert.deepEqual(errors,[]);
      await page.close();
    }
    assert.deepEqual(mutations,[]);
    console.log('AES_PROJECT_RUNS_BROWSER_PASS');
  } finally {
    await browser.close();
  }
}

if (process.env.AES_RUNS_TEST_SERVE) {
  // A standalone preview of the blocked case, with no outbound traffic.
  server.listen(Number(process.env.AES_RUNS_TEST_SERVE), '127.0.0.1',
    () => console.log('LOCAL_FIXTURE_READY', server.address().port));
} else {
  main().catch(error => { console.error(error); process.exitCode=1; })
    .finally(() => server.close());
}
