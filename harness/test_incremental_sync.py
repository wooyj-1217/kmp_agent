"""Synthetic accuracy, crash/replay, process concurrency and timing evidence."""
import importlib.util
import json
import multiprocessing
import os
import re
from pathlib import Path
import tempfile
import subprocess
import time
import unittest

spec=importlib.util.spec_from_file_location('inc',Path(__file__).with_name('incremental_sync.py'))
inc=importlib.util.module_from_spec(spec);spec.loader.exec_module(inc)


def run(root,source,crash=False):
    if crash == 'partial':
        def partial(writer,encoded):
            writer.buffer.write(encoded[:len(encoded)//2]);writer.buffer.flush();os.fsync(writer.fileno());os._exit(74)
        inc.write_payload=partial
    log=inc.logger_module().Logger(root)
    inc.collect(log,source,before_cursor=(lambda:os._exit(73)) if crash is True else None)


class IncrementalTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.source=self.root/'source.jsonl'
        self.log=inc.logger_module().Logger(self.root)
        self.meta=dict(type='session_meta',payload={'id':'synthetic-session'})

    def rows(self,n,start=1):
        return [dict(ordinal=i,type='response_item',payload=dict(type='message',role='user',id='m'+str(i),content=[{'text':'synthetic '*500}])) for i in range(start,start+n)]

    def write(self,rows):self.source.write_bytes(b''.join((json.dumps(r)+'\n').encode() for r in rows))
    def collect(self,**kwargs):
        n=inc.collect(self.log,self.source,**kwargs)
        print(json.dumps({'case':self._testMethodName,**self.log.last_collection}),flush=True)
        return n

    def test_long_initial_append_noop_and_legacy_compatibility(self):
        rows=[self.meta]+self.rows(5000);self.write(rows)
        self.assertEqual(self.collect(),5000)
        events=self.log.read();self.assertEqual(len({e['source_key'] for e in events}),5000)
        self.assertEqual(self.collect(),0);self.assertEqual(self.log.last_collection['read_bytes'],0)
        with self.source.open('ab') as f:f.write((json.dumps(self.rows(1,5001)[0])+'\n').encode())
        self.assertEqual(self.collect(),1)
        self.assertEqual(self.log.last_collection['complete_records'],1)
        # Legacy importer sees exactly the same identities and adds nothing.
        # Do not run its quadratic append loop: compare converter outputs directly.
        c=inc.Collector(self.log,0,0);inc.logger_module().Logger.sync(c,self.source)
        self.assertEqual({e['source_key'] for e in self.log.read()},{x[4] for x in c.events})
        self.assertEqual([e['sequence'] for e in self.log.read()],list(range(1,5002)))

    def test_crash_after_storage_before_cursor(self):
        self.write([self.meta]+self.rows(10))
        p=multiprocessing.Process(target=run,args=(str(self.root),str(self.source),True));p.start();p.join(15)
        self.assertEqual(p.exitcode,73)
        self.assertEqual(self.collect(),0)
        self.assertEqual(len(self.log.read()),10)

    def test_interrupted_batch_write_repaired_without_truncation(self):
        self.write([self.meta]+self.rows(10))
        p=multiprocessing.Process(target=run,args=(str(self.root),str(self.source),'partial'));p.start();p.join(15)
        self.assertEqual(p.exitcode,74)
        before=self.log.path.read_bytes()
        self.assertEqual(self.collect(),0)
        self.assertTrue(self.log.path.read_bytes().startswith(before))
        self.assertEqual(len(self.log.read()),10)
        self.assertGreater(self.log.last_collection['recovered_batch_bytes'],0)

    def test_concurrent_same_and_different_sessions(self):
        self.write([self.meta]+self.rows(100))
        other=self.root/'other.jsonl';other.write_text(json.dumps(dict(type='session_meta',payload={'id':'other'}))+'\n'+json.dumps(self.rows(1)[0])+'\n')
        start=time.monotonic();ps=[multiprocessing.Process(target=run,args=(str(self.root),str(s))) for s in [self.source,self.source,other]]
        for p in ps:p.start()
        for p in ps:p.join(20);self.assertEqual(p.exitcode,0)
        print(json.dumps({'case':self._testMethodName,'elapsed_seconds':time.monotonic()-start}))
        self.assertEqual(len(self.log.read()),101);self.assertEqual(self.collect(),0)

    def test_partial_line_even_valid_json_is_deferred(self):
        self.write([self.meta]);row=json.dumps(self.rows(1)[0]).encode()
        with self.source.open('ab') as f:f.write(row)
        self.assertEqual(self.collect(),0)
        with self.source.open('ab') as f:f.write(b'\n')
        self.assertEqual(self.collect(),1)

    def test_replace_shrink_and_inplace_mismatch(self):
        self.write([self.meta]+self.rows(3));self.assertEqual(self.collect(),3)
        old=self.source.with_suffix('.old');self.source.rename(old)
        self.write([self.meta]+self.rows(4));self.assertEqual(self.collect(),1)
        self.assertIn('reset_reason',self.log.last_collection)
        self.write([self.meta]+self.rows(1));self.assertEqual(self.collect(),0)
        self.assertIn('reset_reason',self.log.last_collection)
        self.write([self.meta]+self.rows(1,9));self.assertEqual(self.collect(),1)
        self.assertIn('reset_reason',self.log.last_collection)
        self.assertEqual(len(self.log.read()),5)

    def test_long_word_masking_remains_compatible(self):
        redact=inc.logger_module().redact
        for text in ['scheme://name:pass@host', 'prefixscheme://name:pass@host', 'a://u:p@h b://v:q@j']:
            expected=re.sub(r"(\w+://)[^\s/@:]+:[^\s/@]+@",r"\1[REDACTED]@",text)
            self.assertEqual(redact(text),expected)
        start=time.monotonic();self.assertEqual(redact('x'*100000),'x'*100000)
        print(json.dumps({'case':self._testMethodName,'elapsed_seconds':time.monotonic()-start}))

    def test_corrupt_cursor_and_invalid_complete_record_are_safe(self):
        self.write([self.meta]+self.rows(1));self.collect()
        cursor=next(p for p in (self.log.directory/'cursors').glob('*.json') if len(p.stem)==64)
        cursor.write_text('{broken')
        self.assertEqual(self.collect(),0)
        self.assertTrue(self.log.last_collection['cursor_invalid'])
        before=cursor.read_bytes()
        with self.source.open('ab') as f:f.write(b'{broken}\n')
        with self.assertRaises(json.JSONDecodeError):self.collect()
        self.assertEqual(cursor.read_bytes(),before)
        self.assertEqual(self.log.last_collection['status'],'FAILED')

    def test_lock_budget_reports_wait_and_observed_owner(self):
        import fcntl
        stats={};phases=[];path=self.root/'held.lock'
        with path.open('a+') as owner:
            fcntl.flock(owner,fcntl.LOCK_EX)
            with self.assertRaises(TimeoutError):
                with inc.lock(path,stats,'test',timeout=.03,trace=lambda p,**k:phases.append((p,k))):pass
        self.assertGreaterEqual(stats['test_lock_wait_seconds'],.03)
        self.assertEqual(phases[-1][0],'lock_timeout')
        self.assertFalse(phases[-1][1]['owner_hint_is_live_verified'])

    def test_real_subprocess_hook_exit_and_manual_maintenance(self):
        self.write([self.meta]+self.rows(1))
        subprocess.run(['rtk','proxy','git','init','--quiet',str(self.root)],check=True)
        hook=Path(__file__).with_name('codex_sync.py').resolve()
        payload=dict(cwd=str(self.root),session_id='synthetic-session',hook_event_name='Stop',transcript_path=str(self.source))
        start=time.monotonic()
        result=subprocess.run(['rtk','proxy','python3','-B',str(hook)],cwd=self.root,input=json.dumps(payload),text=True,capture_output=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stdout)
        rows=[json.loads(x) for x in (self.log.directory/'hook-diagnostics.jsonl').read_text().splitlines()]
        self.assertEqual(rows[-1]['phase'],'hook_exited')
        self.assertEqual(rows[-1]['completion_scope'],'observed_collector_process_exit')
        self.assertTrue(any(x['phase']=='collector_ready' for x in rows))
        print(json.dumps({'case':self._testMethodName,'elapsed_seconds':time.monotonic()-start}))
        payload['transcript_path']=str(self.root/'missing')
        failure=subprocess.run(['rtk','proxy','python3','-B',str(hook)],cwd=self.root,input=json.dumps(payload),text=True,capture_output=True,timeout=20)
        self.assertNotEqual(failure.returncode,0)
        rows=[json.loads(x) for x in (self.log.directory/'hook-diagnostics.jsonl').read_text().splitlines()]
        self.assertNotEqual(rows[-1]['exit_code'],0)
        tool=Path(__file__).with_name('collection_maintenance.py').resolve()
        for action in ['link','status','projects']:
            result=subprocess.run(['rtk','proxy','python3','-B',str(tool),'--root',str(self.root),action],text=True,capture_output=True,timeout=20)
            self.assertEqual(result.returncode,0,result.stderr)

    def test_turn_model_and_lines_match_legacy(self):
        rows=[self.meta,dict(type='turn_context',payload={'model':'test-model'}),dict(type='event_msg',payload={'type':'task_started','turn_id':'turn'})]+self.rows(1)
        self.write(rows);self.collect()
        with self.source.open('ab') as f:f.write((json.dumps(dict(ordinal=8,type='token_usage_record',payload={'usage':{'input_tokens':3}}))+'\n').encode())
        self.collect();e=self.log.read()[-1]
        self.assertEqual(e['source']['line'],5);self.assertEqual(e['observed']['model'],'test-model');self.assertEqual(e['observed']['session_turn_id'],'turn')

if __name__=='__main__':unittest.main()
