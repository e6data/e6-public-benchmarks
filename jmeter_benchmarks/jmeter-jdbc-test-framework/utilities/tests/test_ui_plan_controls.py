"""Exercise the browser helpers without a database or browser dependency."""
from pathlib import Path
import shutil
import subprocess
import unittest


@unittest.skipUnless(shutil.which('node'), 'Node.js required for browser helper tests')
class PlanControlTests(unittest.TestCase):
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
'''
        result = subprocess.run(['node', '-e', script, str(app)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
