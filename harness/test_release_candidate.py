"""Release gates use synthetic sessions/temporary Git only; never live logs."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

ROOT=Path(__file__).resolve().parents[1]

def load(name):
    spec=importlib.util.spec_from_file_location('release_'+name,ROOT/'harness'/f'{name}.py')
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);return mod


class ReleaseCollectionTests(unittest.TestCase):
    def test_legacy_cli_long_full_sync_repeat_and_interruption(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'source.jsonl'
            records=[dict(type='session_meta',payload={'id':'release-synthetic'})]
            records += [dict(ordinal=i,type='response_item',payload=dict(type='message',role='user',id=f'm{i}',content=[{'text':'synthetic '*500}])) for i in range(1,5001)]
            source.write_text(''.join(json.dumps(r)+'\n' for r in records))
            timings=[]
            for expected in [5000,0]:
                start=time.monotonic();result=subprocess.run(['rtk','proxy',sys.executable,'-B',str(ROOT/'harness/logging.py'),'--root',str(root),'sync',str(source)],text=True,capture_output=True,timeout=60)
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertEqual(json.loads(result.stdout)['imported'],expected)
                timings.append(time.monotonic()-start)
            # Run the actual legacy CLI with a deterministic interruption after
            # durable batch storage, immediately before last-sync metadata.
            records.append(dict(ordinal=5001,type='response_item',payload=dict(type='message',role='user',id='m5001',content=[])))
            source.write_text(''.join(json.dumps(r)+'\n' for r in records))
            script='''import importlib.util,sys,os
from pathlib import Path
spec=importlib.util.spec_from_file_location('log',sys.argv[1]);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
original=m.Logger.write_metadata
def stop(self,name,value):
 if name=='last-sync.json':os._exit(75)
 return original(self,name,value)
m.Logger.write_metadata=stop
sys.argv=['logging.py','--root',sys.argv[2],'sync',sys.argv[3]]
m.main()
'''
            crash=subprocess.run(['rtk','proxy',sys.executable,'-B','-c',script,str(ROOT/'harness/logging.py'),str(root),str(source)],capture_output=True,timeout=60)
            self.assertEqual(crash.returncode,75)
            log=load('logging').Logger(root);before=log.path.read_bytes();start=time.monotonic()
            self.assertEqual(log.sync(source),0);recovery=time.monotonic()-start
            self.assertEqual(log.path.read_bytes(),before)
            events=log.read();self.assertEqual(len(events),5001)
            self.assertEqual(len({e['source_key'] for e in events}),5001)
            self.assertEqual([e['sequence'] for e in events],list(range(1,5002)))
            print(json.dumps({'release_gate':'legacy_full_cli','source_bytes':source.stat().st_size,'initial_process_seconds':timings[0],'repeat_process_seconds':timings[1],'interruption_exit':75,'recovery_collection_seconds':recovery,'events':len(events)}),flush=True)

    def test_separated_link_status_probe_projects(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'input.md').write_text('synthetic input')
            subprocess.run(['rtk','proxy','git','init','--quiet',str(root)],check=True)
            tasks=load('tasks');log=tasks.logging.Logger(root);run=log.start('HARNESS_BUILD','planning','synthetic')
            t=tasks.Tasks(root,run);t.register('F','T','planning','synthetic','test',[{'id':'AC','required':True,'text':'synthetic'}],['input.md']);t.ready('T');agent=t.begin('T','planning')['agent_run_id']
            t.intervention('T',agent,'synthetic-session','turn','CORRECTION','synthetic correction',['input.md'],'message')
            source=root/'source.jsonl';source.write_text(''.join(json.dumps(r)+'\n' for r in [dict(type='session_meta',payload={'id':'synthetic-session'}),dict(type='event_msg',payload={'type':'task_started','turn_id':'turn'}),dict(ordinal=2,type='response_item',payload={'type':'message','role':'user','id':'message','content':[{'text':'synthetic'}]})]))
            inc=load('incremental_sync');inc.collect(log,source,mode='manual')
            self.assertEqual(sum(e['event_type']=='human_intervention' for e in log.read()),0)
            before=log.path.read_bytes();timings={}
            for action in ['link','link','status','probe','projects']:
                argv=['rtk','proxy',sys.executable,'-B',str(ROOT/'harness/collection_maintenance.py'),'--root',str(root),action]
                if action=='probe':argv.append(str(source))
                start=time.monotonic();r=subprocess.run(argv,text=True,capture_output=True,timeout=20);timings.setdefault(action,[]).append(time.monotonic()-start)
                self.assertEqual(r.returncode,0,r.stderr)
            self.assertTrue(log.path.read_bytes().startswith(before))
            self.assertEqual(sum(e['event_type']=='human_intervention' for e in log.read()),1)
            print(json.dumps({'release_gate':'explicit_postprocessing','result':'PASS','process_seconds':timings}),flush=True)

if __name__=='__main__':unittest.main()
