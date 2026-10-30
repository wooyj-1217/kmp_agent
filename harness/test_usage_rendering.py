"""Render the actual usage view with synthetic quarantined/valid values."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest


@unittest.skipUnless(shutil.which('node'), 'optional JS runtime unavailable')
class UsageRenderingTests(unittest.TestCase):
    def test_unknown_identity_is_not_rendered_as_zero_and_conflict_is_visible(self):
        asset = Path(__file__).with_name('dashboard_assets') / 'usage.js'
        script = r'''
const fs=require('fs'),vm=require('vm');
const context={document:{addEventListener(){}},mode:'tokens',esc:String,
 detail:(title,body)=>title+body,json:JSON.stringify,date:String,
 data:{usage:{rows:[],comparison:null,scope_info:{tasks:1,role_executions:1,responses:0},
 totals:{tokens:null},identity_conflicts:[{reason:'native_identity_conflict'}],excluded:1,conflicts:[]}}};
vm.createContext(context);vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),context);
console.log(JSON.stringify({unknown:vm.runInContext('num(null)',context),
 zero:vm.runInContext('num(0)',context),known:vm.runInContext('num(120)',context),
 html:vm.runInContext('usageSection()',context)}));
'''
        run = subprocess.run(['node', '-e', script, str(asset)], capture_output=True, text=True, check=True)
        result = json.loads(run.stdout)
        self.assertEqual((result['unknown'], result['zero'], result['known']), ('미확인', '0', '120'))
        self.assertIn('식별자가 충돌한 1개 응답', result['html'])
        self.assertIn('해당 사용량은 미확정', result['html'])
        self.assertNotIn('로그에서 확인된 사용량 0 토큰', result['html'])


if __name__ == '__main__':
    unittest.main()
