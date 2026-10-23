"""Exercise the browser helpers without a database or browser dependency."""
from pathlib import Path
import shutil
import subprocess
import unittest


@unittest.skipUnless(shutil.which('node'), 'Node.js required for browser helper tests')
class PlanControlTests(unittest.TestCase):
    def test_connection_preview_switching_ignores_stale_responses(self):
        app = Path(__file__).resolve().parents[2] / 'ui/static/app.js'
        script = r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(process.argv[1],'utf8');
vm.runInThisContext(source.slice(source.indexOf('async function updateConnectionPreview'),source.indexOf('function updatePreview(){',source.indexOf('async function updateConnectionPreview'))));
const pending=[];global.api=url=>new Promise(resolve=>pending.push({url,resolve}));
const text={textContent:''},box={dataset:{},classList:{toggle(){}},querySelector:()=>text};
const mode={value:'existing'},file={value:'a.properties'};
const card={querySelector:s=>s==='.connection-preview'?box:s==='.connection-mode'?mode:file};
(async()=>{
const a=updateConnectionPreview(card);file.value='b.properties';const b=updateConnectionPreview(card);
pending[1].resolve({jdbc_url:'jdbc:b://host'});await b;
pending[0].resolve({jdbc_url:'jdbc:a://host'});await a;
assert.equal(text.textContent,'jdbc:b://host');
await updateConnectionPreview(card);assert.equal(pending.length,2);
mode.value='create';await updateConnectionPreview(card);assert.equal(text.textContent,'');
})().catch(e=>{console.error(e);process.exitCode=1});
'''
        result = subprocess.run(['node', '-e', script, str(app)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_plan_groups_and_schedule_duration(self):
        app = Path(__file__).resolve().parents[2] / 'ui/static/app.js'
        script = r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(process.argv[1],'utf8');
const helpers=source.slice(source.indexOf('function isProfilePlan'),source.indexOf('function datasetDisplay'));
const options=(items,label,value)=>items.map(x=>`<option value="${value(x)}">${label(x)}</option>`).join('');
vm.runInThisContext(helpers);
const plans=['http_concurrency','jdbc_variable_concurrency','jdbc_arrivals','jdbc_qps','jdbc_sequential','jdbc_run_once'].map(id=>({id,label:id}));
const html=planOptions(plans),split=html.indexOf('<optgroup label="Advanced">');
assert(split>0);
assert(html.indexOf('Sequential')<html.indexOf('Fixed QPS'));
assert(html.indexOf('Fixed QPS')<html.indexOf('Arrival-rate profile'));
assert(html.indexOf('jdbc_variable_concurrency')>split);
assert(html.indexOf('http_concurrency')>split);
for(const p of plans)assert.equal(html.split(`value="${p.id}"`).length,2);
assert(isProfilePlan('jdbc_arrivals'));
assert(isProfilePlan('jdbc_variable_concurrency'));
assert(!isProfilePlan('jdbc_qps'));
assert.equal(profileDurationText({duration_s:300}),'300 seconds (5 min)');
assert.equal(profileDurationText({duration_s:90}),'90 seconds (1.5 min)');
assert.equal(profileDurationText({duration_s:null}),'Select a valid load profile');
assert(source.includes("classList.toggle('hidden',runOnce||isProfilePlan(p))"));
assert(source.includes("$('profileDuration').textContent='Cannot calculate duration: '+e.message"));
const isRunOncePlan=id=>['jdbc_sequential','jdbc_run_once','http_run_once'].includes(id);
const env={HOLD_PERIOD:300,QPS:2,QPM:60,MAX_CONCURRANCY:100,CONCURRENT_QUERY_COUNT:4,MEASURED_ITERATIONS:1,RAMP_UP_TIME:10,RAMP_UP_STEPS:2,RECYCLE_ON_EOF:true,QUERY_TIMEOUT:300};
const arrival=relevantEnvironment(env,'jdbc_arrivals');
assert(!('HOLD_PERIOD' in arrival));assert(!('QPS' in arrival));
assert(!('CONCURRENT_QUERY_COUNT' in arrival));assert.equal(arrival.MAX_CONCURRANCY,100);
assert.equal(relevantEnvironment(env,'jdbc_qps').HOLD_PERIOD,300);
assert.equal(relevantEnvironment(env,'jdbc_concurrency').CONCURRENT_QUERY_COUNT,4);
assert(!('MAX_CONCURRANCY' in relevantEnvironment(env,'jdbc_concurrency')));
assert(!('RECYCLE_ON_EOF' in relevantEnvironment(env,'jdbc_sequential')));
assert.equal(env.HOLD_PERIOD,300); // filtering must not mutate execution inputs
const group={children:[{},{}]},select={value:'jdbc_sequential',querySelector:()=>group},toggle={checked:false};
const $=id=>id==='plan'?select:toggle;
let defaults=0;const applyPlanDefault=()=>defaults++;
syncPlanVisibility();assert(group.hidden);assert(group.children.every(o=>o.hidden));
toggle.checked=true;syncPlanVisibility();assert(!group.hidden);
select.value='jdbc_variable_concurrency';toggle.checked=false;
syncPlanVisibility(true);assert(toggle.checked);assert(!group.hidden);
toggle.checked=false;syncPlanVisibility();assert.equal(select.value,'jdbc_sequential');assert.equal(defaults,1);
const page=fs.readFileSync(process.argv[1].replace('app.js','index.html'),'utf8');
assert(page.includes('Reuse or save settings'));assert(page.includes('CLI configuration'));
const engineCardSource=source.slice(source.lastIndexOf('function engineCard('),source.indexOf('function metadataFromCard'));
assert(engineCardSource.includes('connection-dataset-hint'));
assert(engineCardSource.includes('catalog/schema defaults'));
assert(engineCardSource.includes('fully qualified table names (FQN)'));
assert(engineCardSource.includes('warm-up queries'));
assert(!/<details[^>]*class="card (?:advanced-card|preview-card)"[^>]*\sopen/.test(page));
'''
        result = subprocess.run(['node', '-e', script, str(app)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
