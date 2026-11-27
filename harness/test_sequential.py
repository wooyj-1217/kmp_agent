"""Synthetic evidence in disposable projects only; no production history enrichment."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import bootstrap
from harness.tasks import Tasks
from harness.logging import Logger
from harness import sequential as seq

ROOT = Path(__file__).resolve().parents[1]


class SequentialTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        for name, value in {"input.md": "input", "output.md": "output", "decision.md": "decision"}.items():
            (self.root / name).write_text(value)
        self.logger = Logger(self.root)
        self.run_id = self.logger.start("PRODUCT", "orchestrator", "synthetic sequential collection")
        self.tasks = Tasks(self.root, self.run_id)

    def register(self, tid="T", deps=None):
        return self.tasks.register("F", tid, "planning", "fixture", "docs", [{"id": "AC", "required": True}],
                                   ["input.md"], dependencies=deps)

    def start(self, tid="T"):
        self.tasks.ready(tid)
        return self.tasks.begin(tid, "planning")

    def test_dependencies_order_only_does_not_gate_or_infer(self):
        self.register("A")
        self.register("B")
        self.tasks.configure_collection("B", dependency_relations=[{"task_id": "A", "kind": "ORDER_ONLY", "reason": "operator preference"}],
                                        shared_modules=[], shared_resources="UNKNOWN")
        self.start("B")  # A remains TODO; order-only is not a data dependency.
        self.assertEqual(self.tasks.read()["tasks"]["A"]["state"], "TODO")
        self.register("C", ["A"])
        with self.assertRaises(ValueError):
            self.tasks.configure_collection("C", dependency_relations=[])
        with self.assertRaises(ValueError):
            self.tasks.ready("C")
        self.assertEqual(seq.report(self.root)["tasks"]["A"]["dependencies"]["status"], "MISSING")

    def test_attempt_wait_file_delta_and_unknown_actor(self):
        seq.save_settings(self.root, {"schema_version": 1, "modules": {"docs": ["output.md"]}})
        self.register()
        self.tasks.configure_collection("T", dependency_relations=[], shared_modules=["docs"], shared_resources=[], feature_version="feature-r1")
        run = self.start()
        self.tasks.checkpoint("T", run["agent_run_id"], "approval", "input.md", wait_type="DECISION", wait_target="approval-1")
        self.tasks.resume("T", run["agent_run_id"], "decision.md")
        (self.root / "output.md").write_text("changed")
        self.tasks.submit("T", run["agent_run_id"], ["output.md"], "done")
        current = self.tasks.read()["tasks"]["T"]["executions"][0]
        self.assertEqual(current["attempt_id"], run["agent_run_id"])
        self.assertEqual(current["waits"][0]["outcome"], "RELEASED")
        self.assertIsNotNone(current["waits"][0]["ended_at"])
        self.assertEqual(current["collection"]["modification_actor"], "UNKNOWN")
        self.assertEqual(current["collection"]["observed_modules"]["output.md"], ["docs"])
        self.assertEqual([f["path"] for f in current["collection"]["changed_files"]], ["output.md"])
        report = seq.report(self.root)["tasks"]["T"]["executions"][0]
        self.assertEqual(report["harness"]["status"], "COLLECTED")
        self.assertTrue(report["baseline_id"]["value"].startswith("sha256:"))
        self.assertEqual(report["feature_version"]["value"], "feature-r1")

    def test_role_snapshot_prunes_ignored_root_caches_and_preserves_v1(self):
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        (self.root / ".gitignore").write_text("/.gradle-local/\n/.konan-local/\n/.xcode-derived/\n")
        caches = [".gradle-local/cache", ".konan-local/cache", ".xcode-derived/cache"]
        for path in caches:
            cache = self.root / path
            cache.parent.mkdir()
            cache.write_text("initial")
        tracked = ".gradle-local/tracked-source"
        (self.root / tracked).write_text("keep")
        subprocess.run(["git", "-C", str(self.root), "add", "-f", tracked], check=True)
        self.register()
        run = self.start()
        collection = run["collection"]
        self.assertEqual(collection["snapshot_policy"], "generated_pruned_v2")
        self.assertIn(caches[0], collection["files_start"])
        self.assertNotIn(caches[1], collection["files_start"])
        self.assertNotIn(caches[2], collection["files_start"])

        outer_run = self.logger.start("HARNESS_BUILD", "orchestrator", "measure cache exclusion")
        start = self.logger.run(outer_run)["observed"]
        self.assertEqual(start["snapshot_policy"], "generated_pruned_v2")
        self.assertNotIn(caches[1], start["files"])
        self.assertIn(tracked, start["files"])
        self.logger.append("run_started", "legacy", "HARNESS_BUILD", observed={
            "snapshot_policy": "generated_pruned_v1",
            "files": seq.log.snapshot(self.root, prune_generated=True),
        })

        legacy = copy.deepcopy(run)
        legacy["collection"]["snapshot_policy"] = "generated_pruned_v1"
        legacy["collection"]["files_start"] = seq.log.snapshot(self.root, prune_generated=True)
        (self.root / caches[1]).write_text("changed")
        (self.root / "output.md").write_text("changed")
        task = self.tasks.read()["tasks"]["T"]
        seq.finish(self.tasks, task, run)
        seq.finish(self.tasks, task, legacy)
        self.assertNotIn(caches[1], collection["files_end"])
        self.assertIn(caches[1], legacy["collection"]["files_end"])
        self.assertIn(caches[1], {f["path"] for f in legacy["collection"]["changed_files"]})
        self.assertEqual([f["path"] for f in collection["changed_files"]], ["output.md"])
        outer = self.logger.checkpoint(outer_run, "finished", finish=True)
        legacy_outer = self.logger.checkpoint("legacy", "finished", finish=True)
        self.assertEqual([f["path"] for f in outer["observed"]["changed_files"]], ["output.md"])
        self.assertIn(caches[1], {f["path"] for f in legacy_outer["observed"]["changed_files"]})

    def test_named_command_timing_link_failure_and_unlinked(self):
        seq.save_settings(self.root, {"schema_version": 1, "commands": {"check": {
            "kind": "test", "argv": ["rtk", "proxy", sys.executable, "-c", "raise SystemExit(7)"]}}})
        self.register()
        run = self.start()
        self.assertEqual(self.logger.command(self.run_id, task_id="T", agent_run_id=run["agent_run_id"],
                         attempt_id=run["attempt_id"], command_name="check"), 7)
        self.assertEqual(self.logger.command(self.run_id, ["rtk", "proxy", sys.executable, "-c", "pass"]), 0)
        report = seq.report(self.root)
        linked, unlinked = report["commands"]
        self.assertEqual(linked["returncode"]["value"], 7)
        self.assertEqual(linked["kind"]["value"], "test")
        self.assertGreaterEqual(linked["elapsed_seconds"]["value"], 0)
        self.assertEqual(linked["link"]["status"], "COLLECTED")
        self.assertEqual(unlinked["task_id"], "UNKNOWN")
        self.assertEqual(report["commands_without_links"], 1)
        self.assertEqual(report["commands_outside_wrapper"], "UNKNOWN")
        with self.assertRaises(ValueError):
            self.logger.command(self.run_id, ["rtk", "true"], task_id="T")
        with self.assertRaises(ValueError):
            self.logger.command(self.run_id, ["rtk", "true"], task_id="T", agent_run_id=run["agent_run_id"], attempt_id="wrong")

    def test_missing_command_finish_is_not_zero(self):
        self.logger.append("command_started", self.run_id, observed={"call_id": "interrupted", "started_at": "observed"})
        command = seq.report(self.root)["commands"][0]
        self.assertEqual(command["ended_at"]["status"], "MISSING")
        self.assertEqual(command["returncode"]["value"], "UNKNOWN")

    def test_fail_closes_wait_as_cancelled_and_records_delta(self):
        self.register()
        run = self.start()
        self.tasks.checkpoint("T", run["agent_run_id"], "waiting", "input.md")
        with self.assertRaises(ValueError):
            self.logger.command(self.run_id, ["rtk", "true"], task_id="T", agent_run_id=run["agent_run_id"], attempt_id=run["attempt_id"])
        self.tasks.fail("T", run["agent_run_id"], "cancel")
        current = self.tasks.read()["tasks"]["T"]["executions"][0]
        self.assertEqual(current["waits"][0]["outcome"], "CANCELLED")
        self.assertEqual(current["waits"][0]["type"], "UNKNOWN")
        self.assertEqual(current["collection"]["changed_files"], [])

    def test_integration_links_existing_cr_and_preserves_evidence(self):
        self.register()
        run = self.start()
        def fixture(state):
            state["deliverables"] = {"feature": {"changes": [{"id": "CR-001", "impacts": {"tasks": ["T"]}}]}}
        self.tasks._mutate("synthetic_cr", fixture)
        record = self.tasks.integration("T", run["agent_run_id"], kind="CONFLICT", reason="actual synthetic conflict",
            evidence="input.md", cr={"folder": "feature", "id": "CR-001"}, conflict_files=["output.md"])
        self.assertEqual(record["before_commit"], "UNKNOWN")
        self.assertTrue(self.tasks._valid_artifact(record["evidence"]))
        with self.assertRaises(ValueError):
            self.tasks.integration("T", run["agent_run_id"], kind="REWORK", reason="fixture", evidence="input.md",
                                   cr={"folder": "feature", "id": "CR-missing"})

    def test_legacy_history_readonly_and_no_backfill(self):
        self.register()
        run = self.start()
        state = json.loads(self.tasks.path.read_text())
        historical = state["tasks"]["T"]["executions"][0]
        historical.pop("collection")
        historical.pop("attempt_id")
        self.tasks._save(state)
        before = self.tasks.path.read_bytes()
        events = self.logger.path.read_bytes()
        result = seq.report(self.root)["tasks"]["T"]["executions"][0]
        self.assertEqual(result["files"]["status"], "MISSING")
        self.assertEqual(result["harness"]["status"], "MISSING")
        self.assertEqual(self.tasks.path.read_bytes(), before)
        self.assertEqual(self.logger.path.read_bytes(), events)
        self.tasks.submit("T", run["agent_run_id"], ["output.md"], "legacy remains supported")
        self.assertNotIn("collection", self.tasks.read()["tasks"]["T"]["executions"][0])

    def test_settings_reject_escape_and_no_auto_execution(self):
        with self.assertRaises(ValueError):
            seq.save_settings(self.root, {"schema_version": 1, "commands": {"bad": {"kind": "build", "argv": ["rtk", "true"], "cwd": "../other"}}})
        saved = seq.save_settings(self.root, {"schema_version": 1, "modules": {"m": ["src"]}})
        self.assertFalse(saved["automatic_execution"])

    def test_late_declaration_is_not_a_rewritten_start(self):
        self.register()
        run = self.start()
        with self.assertRaises(ValueError):
            self.tasks.configure_collection("T", shared_modules=["docs"])
        self.tasks.configure_collection("T", agent_run_id=run["agent_run_id"], shared_modules=["docs"], shared_resources="UNKNOWN")
        with self.assertRaises(ValueError):
            self.tasks.configure_collection("T", agent_run_id=run["agent_run_id"], feature_version="invented-later")
        current = self.tasks.read()["tasks"]["T"]["executions"][0]
        self.assertNotIn("shared_modules", current["collection"])
        self.assertEqual(current["collection_declarations"][0]["shared_modules"], ["docs"])


class TemporaryProjectCLI(unittest.TestCase):
    def test_init_task_command_coverage_and_init_reuse(self):
        self._installed_command_flow()

    def test_approved_contract_transition_installed_command_flow(self):
        self._installed_command_flow(transition=True)

    def test_prelaunch_timeout_then_retry_installed_command_flow(self):
        self._installed_command_flow(preflight_retry=True)

    def test_transition_then_prelaunch_timeout_retry_installed_flow(self):
        self._installed_command_flow(transition=True,preflight_retry=True)

    def test_pinned_upgrade_preserves_approved_command_flow(self):
        keys = ('KMP_TEST_UPGRADE_SOURCE', 'KMP_TEST_UPGRADE_FROM', 'KMP_TEST_UPGRADE_TO')
        upgrade = tuple(os.environ.get(key) for key in keys)
        if not any(upgrade):
            self.skipTest('pinned upgrade requires a Git source and two commit SHAs')
        self.assertTrue(all(upgrade), ', '.join(keys))
        self.expected_installation_mode = 'installed'
        self._installed_command_flow(transition=True, preflight_retry=True, upgrade=upgrade)

    def _installed_command_flow(self, transition=False, preflight_retry=False, upgrade=None):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve() / "applied project"
            root.mkdir()
            subprocess.run(["rtk", "proxy", "git", "init", "-q", str(root)], check=True)
            (root / "input.md").write_text("synthetic input")
            (root / "output.md").write_text("synthetic output")
            (root / "src").mkdir()
            (root / "src/App.kt").write_text("val value = 1\n")
            # Real compile/test subprocesses for a synthetic fixture; no KMP/product build claim.
            (root / "src/fixture_rules.py").write_text("def add(left, right): return left + right\n")
            (root / "tools").mkdir()
            (root / "tools/fixture_checks.py").write_text("""from pathlib import Path
import importlib.util, py_compile, sys, unittest
root = Path.cwd()
artifact = root / '.harness/fixture_rules.pyc'
if sys.argv[1] == 'build':
    py_compile.compile('src/fixture_rules.py', cfile=str(artifact), doraise=True)
    (root / '.harness/build.done').write_text('compiled fixture')
else:
    assert (root / '.harness/build.done').is_file()
    spec = importlib.util.spec_from_file_location('fixture_rules', artifact)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    def check():
        assert module.add(2, 3) == 5
        assert (root / 'src/App.kt').read_text() == 'val value = 3\\n'
    result = unittest.TextTestRunner().run(unittest.TestSuite([unittest.FunctionTestCase(check)]))
    assert result.wasSuccessful()
    (root / '.harness/test.done').write_text('fixture test passed')
""")
            build_argv = ['rtk', 'proxy', sys.executable, 'tools/fixture_checks.py', 'build']
            test_argv = ['rtk', 'proxy', sys.executable, 'tools/fixture_checks.py', 'test']
            (root / ".gitignore").write_text(".harness/\n.kmp-agent/\n.codex/\n")
            def git(*args):
                return subprocess.run(["rtk", "proxy", "git", *args], cwd=root, check=True, capture_output=True)
            git("add", ".")
            git("-c", "user.name=Synthetic", "-c", "user.email=synthetic@example.invalid", "commit", "-qm", "disposable baseline")
            if upgrade:
                source, previous, candidate = upgrade
                bootstrap.install(root, source=source, ref=previous)
            else:
                bootstrap.install(root, development=ROOT)
            runtime = bootstrap.reference(root, bootstrap.read(root / bootstrap.MANIFEST))
            env = {k: v for k, v in os.environ.items() if k != "CODEX_THREAD_ID"}
            native=root/'synthetic-native/session.jsonl';native.parent.mkdir()
            session='00000000-0000-4000-8000-000000000712'
            native_records=[{'type':'session_meta','payload':{'id':session,'source':'cli'}}]
            native.write_text(json.dumps(native_records[0])+'\n')
            # Unit-only native-store location; the real installed entrypoint still runs.
            shim=native.parent/'run_installed.py'
            shim.write_text("import runpy,sys,subprocess\nfrom pathlib import Path\nfrom unittest.mock import patch\nsys.path.insert(0,%r)\nentry=sys.argv[1];sys.argv=sys.argv[1:]\npatch('harness.decisions.native_store',return_value=Path(%r)).start()\noriginal_call=subprocess.call\ndef invoke(argv,**kwargs):\n    if len(argv)>1 and argv[1]==%r:\n        return original_call([sys.executable,__file__,*argv[1:]],**kwargs)\n    return original_call(argv,**kwargs)\nsubprocess.call=invoke\nrunpy.run_path(entry,run_name='__main__')\n" % (str(runtime),str(native.parent),str(runtime/'harness/cli.py')))
            if preflight_retry:
                text=shim.read_text()
                injection = """from harness.command_preflight import current
from harness.execution_policy import WorkerGate
import time

original_init = WorkerGate.__init__
def expire_at_worker_gate(self, *args, **kwargs):
    original_init(self, *args, **kwargs)
    if Path(%r).exists():
        budget = current()
        assert budget is not None and budget.armed and budget.name == 'worker_gate'
        budget.deadline = time.monotonic() - 1

WorkerGate.__init__ = expire_at_worker_gate
runpy.run_path(entry, run_name='__main__')
""" % str(root/'.harness/slow-preflight')
                text=text.replace("runpy.run_path(entry,run_name='__main__')", injection)
                shim.write_text(text)
            def cli(action, expected_exit=0, payload=None, **options):
                argv = ["rtk", "proxy", sys.executable, '-B',str(shim),str(root / ".kmp-agent/agent.py"), action]
                for name, value in options.items():
                    argv.extend(["--" + name.replace("_", "-"), str(value)])
                proc = subprocess.run(argv, cwd=root, env=env, input=payload, capture_output=True, text=True)
                self.assertEqual(proc.returncode, expected_exit, proc.stdout + proc.stderr)
                return json.loads(proc.stdout)
            config = Path(temporary) / "settings.json"
            config.write_text(json.dumps({"schema_version": 1, "modules": {"app": ["src"]}, "commands": {
                "build": {"kind": "build", "argv": build_argv},
                "test": {"kind": "test", "argv": test_argv}}}))
            cli("init", tracking_settings=config)
            settings_before = (root / seq.SETTINGS).read_bytes()
            cli("init")
            self.assertEqual((root / seq.SETTINGS).read_bytes(), settings_before)
            run_id = cli("start",work_type="PRODUCT",request="Synthetic installed command coverage; no product approval claim")["run_id"]
            def task(operation, data):
                path = Path(temporary) / "operation.json"
                path.write_text(json.dumps(data))
                return cli("task", operation=operation, data=path, run_id=run_id)
            task("register", {"feature_id": "F", "task_id": "T", "role": "development", "execution_scope": "code_implementation", "work_type":"PRODUCT",
                "title": "synthetic", "scope": "code", "criteria": [{"id": "AC", "required": True}], "inputs": ["input.md"]})
            # Synthetic typed source approval is confined to an immutable document task;
            # changing implementation bytes must not rewrite the approval's source task.
            from harness.execution_plan import attach_existing
            from harness.requirement_lineage import file_ref, approval_subject, load
            from harness.decisions import digest
            from harness.project_contract import FIELDS, DOCUMENTS, SERVER, API
            manager=Tasks(root,run_id)
            manager.register('F','AUTH','planning','Synthetic source approval','Unit fixture only; never human/product acceptance',[{'id':'A','required':True}],['input.md'],execution_scope='documentation')
            policy={'settings':{'implementation_targets':['jvm'],'ui_technology':'Kotlin Multiplatform CLI','database':None,'server_mode':'none','code_ownership':'synthetic source'},
                    'ui_sharing':'none','ui_owners':{},'platform_entrypoints':{'jvm':['src/App.kt']},
                    'target_commands':{'jvm':[build_argv,test_argv]},
                    'source_rules':[{'glob':'src/*.kt','required_patterns':['val value'],'forbidden_patterns':[]}]}
            lineage={'schema_version':1,'scope':'PRODUCT','purpose':'Synthetic installed CLI contract regression, not actual approval',
                     'sources':[dict(id='U',kind='USER_ORIGINAL',anchor='synthetic source',**file_ref(root,'input.md'))],
                     'requirements':[{'id':'TECH','source':'U','anchor':'synthetic source','expected':{'development_constraints':policy}}],
                     'derived_items':[], 'human_authorization':{'question_id':'SYNTHETIC-APPROVAL','task_id':'AUTH'}}
            # The exact policy is an authoritative fixture value, not an omitted requirement.
            (root/'derived.md').write_text('Synthetic implementation mapping only')
            lineage['sources'].append(dict(id='D',kind='AGENT_DERIVED',anchor='synthetic mapping',**file_ref(root,'derived.md')))
            lineage['derived_items']=[{'id':'PLAN','source':'D','anchor':'synthetic mapping','source_ids':['TECH'],'expected':{'development_constraints':policy}}]
            (root/'requirement-lineage.json').write_text(json.dumps(lineage))
            store=patch('harness.decisions.native_store',return_value=native.parent);store.start();self.addCleanup(store.stop)
            from harness.stage_readiness import DOMAINS, ROLES
            stages={}
            for stage,tid in [('planning','P'),('design','D'),('development_plan','PLAN')]:
                checks={domain:stage+'-'+domain for domain in DOMAINS[stage]}
                manager.register('F',tid,ROLES[stage], 'Synthetic '+stage,'Document contract fixture only; not a product or visual observation',
                    [{'id':v,'required':True,'description':k} for k,v in checks.items()],['input.md'],
                    work_type='PRODUCT',execution_scope='documentation')
                stages[stage]={'task_id':tid,'checks':checks}
            attach_existing(manager,['P','D','PLAN','T'],'IMPLEMENT','delivery_with_qa','Synthetic installed command coverage','input.md','Connect fixture before any work')
            manager.configure_execution_policy(str(native),session,apply_to_work_types=['PRODUCT'])
            def approve_lineage(qid, targets, candidate=None, supersedes=None):
                manager.open_question(qid,'Synthetic unit only: approve exact technology source for command transport?', targets,
                    [{'id':'approve','label':'Approve synthetic unit policy'}],approval_purpose='requirement_lineage',
                    approval_subject=approval_subject(candidate or load(root)),supersedes_question_id=supersedes,
                    approval_artifacts=list(dict.fromkeys(s['path'] for s in (candidate or load(root))['sources'])))
                question=manager.question_status()[qid]['question']
                call='synthetic-sequential-prompt-'+qid
                native_records.append({'type':'response_item','payload':{'type':'function_call','name':'request_user_input_async','call_id':call,'arguments':json.dumps({'questions':[{'question':question,'options':['Approve synthetic unit policy']}]})}})
                item=json.dumps(['request_user_input_async',call,0],separators=(',',':'))
                text='<send_user_message_question_reply>\n'+json.dumps([{'answer':'Approve synthetic unit policy','question':question,'questionItemId':item}])+'\n</send_user_message_question_reply>'
                event={'type':'event_msg','payload':{'type':'user_message','message':text}}
                user={'type':'response_item','payload':{'type':'message','role':'user','content':[{'type':'input_text','text':text}]}}
                native_records.extend([event,user]);native.write_text(''.join(json.dumps(r)+'\n' for r in native_records))
                manager.answer_question(qid,record_ordinal=len(native_records)-1,payload_sha256=digest(event['payload']),user_input_record_ordinal=len(native_records),user_input_payload_sha256=digest(user['payload']))
            approve_lineage('SYNTHETIC-APPROVAL', ['AUTH'])
            settings={k:{'status':'CONFIRMED','value':'synthetic contract','reason':'synthetic unit only'} for k in FIELDS}
            for key in DOCUMENTS:settings[key]['value']='input.md'
            for key,value in policy['settings'].items():settings[key]['value']=value
            for key in SERVER|API:settings[key].update(status='NOT_APPLICABLE',value=None,reason='No server in this synthetic transport test')
            (root/'product-settings.json').write_text(json.dumps(settings))
            task('configure-stage',{'task_id':'T','stage':'ui','settings':'product-settings.json'})
            manager.configure_task_plan('T',{'version':1,'owner':'development','whole_plan_task_id':'T','completion_criteria':['command and coverage observed'],'inputs':['input.md'],'outputs':['src/App.kt'],'verification':['approved test command'],'steps':[{'id':'S','action':'synthetic source change','completion_criteria':['command and coverage observed'],'inputs':['input.md'],'outputs':['src/App.kt'],'verification':['approved test command']}]},'Synthetic installed lifecycle fixture')
            task("configure-development", {"task_id": "T", "baselines": {"planning": "input.md"}, "code_paths": ["src"]})
            task("configure-collection", {"task_id": "T", "dependency_relations": [], "shared_modules": ["app"], "shared_resources": []})
            manager.configure_stage_workflow('F',stages)
            upstream=[]
            for stage,config in stages.items():
                tid=config['task_id']
                fields={'completion_criteria':['synthetic document criteria'],'inputs':['input.md'],'outputs':[stage+'.md'],'verification':['synthetic unit review']}
                manager.configure_task_plan(tid,{'version':1,'owner':ROLES[stage],'whole_plan_task_id':tid,
                    **fields,'steps':[{'id':'S','action':'synthetic contract document',**fields}]},'Synthetic pre-work fixture plan')
                manager.bind_stage_inputs(tid,['input.md',*upstream],'Explicit synthetic document baseline')
                manager.ready(tid);work=manager.begin(tid,ROLES[stage])
                document=stage+'.md';(root/document).write_text('Synthetic document contract; no visual/model/product observation.')
                status={'specification':'COMPLETE','mockup':'NOT_PRODUCED','visual_review':'NOT_RUN'} if stage=='design' else None
                manager.submit(tid,work['agent_run_id'],[document],'Synthetic document only',status)
                review=manager.begin(tid,'verification',review=True,execution_mode='local_check')
                manager.review(tid,review['agent_run_id'],[{'criterion_id':c,'result':'PASS','evidence':'input.md'} for c in config['checks'].values()],
                    'Synthetic orchestration fixture; no real reviewer/model/product claim')
                upstream.append(document)
            manager.bind_stage_inputs('T',[a['path'] for a in manager.read()['tasks']['T']['inputs']]+upstream,'Bind current synthetic stage documents')
            # Also authorize this tracked task; preserve the existing document approval.
            approve_lineage('SYNTHETIC-CODE-APPROVAL', ['T'])
            task("ready", {"task_id": "T"})
            run = task("begin", {"task_id": "T", "role": "development"})
            from harness.product_guard import evaluate, authorize_command
            original_questions = copy.deepcopy(manager.read()['required_questions'])
            original_native = native.read_bytes()
            if upgrade:
                task('checkpoint', dict(task_id='T', agent_run_id=run['agent_run_id'],
                    reason='Synthetic implementation paused before updating the harness', checkpoint='input.md'))
                before = bootstrap.read(root / bootstrap.MANIFEST)
                cli("update", ref=candidate)
                after = bootstrap.read(root / bootstrap.MANIFEST)
                self.assertEqual(after['commit'], candidate)
                self.assertEqual(after['previous']['commit'], before['commit'])
                self.assertEqual(after['project_id'], before['project_id'])
                self.assertEqual(manager.read()['required_questions'], original_questions)
                self.assertEqual(native.read_bytes(), original_native)
                updated_runtime = bootstrap.reference(root, after)
                shim.write_text(shim.read_text().replace(str(runtime), str(updated_runtime)))
                task('resume', dict(task_id='T', agent_run_id=run['agent_run_id'], decision='input.md'))
            command_run_id = run_id
            for value in (2, 3):
                if value == 3:
                    if transition:
                        # T2 is approved against the still-current T1 task basis.
                        # The official operation must preserve this exact receipt.
                        candidate = copy.deepcopy(load(root))
                        for rows in (candidate['requirements'], candidate['derived_items']):
                            rows[0]['expected']['development_constraints']['source_rules'][0]['required_patterns'] = ['val value = [23]']
                        (root/'technical-proposal.json').write_text('Synthetic T2 proposal: accept the exact revised fixture source rule')
                        proposal_ref = file_ref(root,'technical-proposal.json')
                        candidate['sources'].extend([
                            dict(id='PROPOSAL',kind='APPROVED_REQUIREMENTS',anchor='synthetic T2',
                                 approval={'source':'U','anchor':'synthetic explicit approval','approved_sha256':proposal_ref['sha256']},**proposal_ref),
                            dict(id='PROPOSAL-DERIVED',kind='AGENT_DERIVED',anchor='synthetic T2 mapping',**proposal_ref)])
                        candidate['requirements'][0]['source'] = 'PROPOSAL'
                        candidate['derived_items'][0]['source'] = 'PROPOSAL-DERIVED'
                        candidate['human_authorization'] = {'question_id':'SYNTHETIC-T2','task_id':'T'}
                        approve_lineage('SYNTHETIC-T2', ['T'], candidate, supersedes='SYNTHETIC-CODE-APPROVAL')
                        original_questions = copy.deepcopy(manager.read()['required_questions'])
                        original_native = native.read_bytes()
                        canonical = root/'requirement-lineage.json'
                        before = __import__('hashlib').sha256(canonical.read_bytes()).hexdigest()
                        (root/'candidate.json').write_text(json.dumps(candidate))
                        task('transition-approved-contract',dict(task_id='T',agent_run_id=run['agent_run_id'],
                            question_id='SYNTHETIC-T2',candidate='candidate.json',before_sha256=before,
                            reason='Apply the exact approved synthetic technical proposal',evidence='input.md'))
                        self.assertEqual(load(root),candidate)
                    else:
                        task('checkpoint',dict(task_id='T',agent_run_id=run['agent_run_id'],
                            reason='Synthetic handoff after authorized implementation',checkpoint='input.md'))
                    cli('finish',run_id=run_id,result='Synthetic blocked/handoff',end_reason='handoff')
                    task('resume',dict(task_id='T',agent_run_id=run['agent_run_id'],decision='input.md'))
                    blocked = cli('command',expected_exit=1,run_id=run_id,task_id='T',
                        agent_run_id=run['agent_run_id'],attempt_id=run['attempt_id'],command_name='build')
                    self.assertIn('run already finished',blocked['cause'])
                    self.assertIn('continue-command-run', blocked['cause'])
                    prefix = (f'python3 .kmp-agent/agent.py command --task-id T --agent-run-id {run["agent_run_id"]}'
                              f' --attempt-id {run["attempt_id"]}')

                    def command_hook(command_run, options):
                        payload = dict(hook_event_name='PreToolUse', cwd=str(root),
                            session_id=session, tool_name='exec_command',
                            tool_input={'cmd': f'{prefix} --run-id {command_run} {options}'})
                        if upgrade:
                            return cli('guard', payload=json.dumps(payload))
                        return evaluate(root, payload)

                    closed = command_hook(run_id, '--command-name build')['hookSpecificOutput']
                    self.assertEqual(closed['permissionDecision'], 'deny')
                    self.assertIn('continue-command-run', closed['permissionDecisionReason'])
                    continuation = task('continue-command-run',dict(task_id='T',agent_run_id=run['agent_run_id'],
                        previous_run_id=run_id,reason='Continue the same approved build/test attempt',evidence='input.md'))
                    command_run_id = continuation['command_run_id']
                    continuation_cmd = 'python3 .kmp-agent/agent.py task --run-id ' + run_id + ' --operation continue-command-run --data docs/guard-inputs/continuation.json'
                    self.assertEqual(evaluate(root,dict(hook_event_name='PreToolUse',cwd=str(root),
                        session_id=session,tool_name='exec_command',tool_input={'cmd':continuation_cmd})),{})
                    wrong_root = evaluate(root,dict(hook_event_name='PreToolUse',cwd=str(root),
                        session_id='wrong-native-session',tool_name='exec_command',tool_input={'cmd':continuation_cmd}))
                    self.assertEqual(wrong_root['hookSpecificOutput']['permissionDecision'],'deny')
                preview = '*** Begin Patch\n*** Update File: src/App.kt\n@@\n-val value = ' + str(value - 1) + '\n+val value = ' + str(value) + '\n*** End Patch'
                self.assertEqual(evaluate(root, dict(hook_event_name='PreToolUse', cwd=str(root),
                    session_id=session, tool_name='apply_patch', tool_input=preview)), {})
                (root / "src/App.kt").write_text("val value = " + str(value) + "\n")
            outside = '*** Begin Patch\n*** Add File: outside/App.kt\n+val value = 1\n*** End Patch'
            denied = evaluate(root, dict(hook_event_name='PreToolUse', cwd=str(root),
                session_id=session, tool_name='apply_patch', tool_input=outside))
            self.assertEqual(denied['hookSpecificOutput']['permissionDecision'], 'deny')
            self.assertFalse((root / 'outside/App.kt').exists())
            if command_run_id != run_id:
                with self.assertRaisesRegex(ValueError, 'run differs from active execution'):
                    authorize_command(root, manager.read(), 'T', ['rtk', 'proxy', 'git', 'status'], run_id=run_id)
            with self.assertRaisesRegex(ValueError, 'target_commands'):
                authorize_command(root, manager.read(), 'T', ['unapproved-command'], run_id=command_run_id)
            settings_path = root / seq.SETTINGS
            settings_bytes = settings_path.read_bytes()
            changed = json.loads(settings_bytes)
            changed['commands']['build']['argv'] = ['rtk', 'proxy', 'git', 'status']
            settings_path.write_text(json.dumps(changed))
            try:
                denied = command_hook(command_run_id, '--command-name build')['hookSpecificOutput']
                self.assertEqual(denied['permissionDecision'], 'deny')
                self.assertIn('authoritative target_commands', denied['permissionDecisionReason'])
            finally:
                settings_path.write_bytes(settings_bytes)
            if preflight_retry:
                flag=root/'.harness/slow-preflight';flag.write_text('Synthetic fault injection only')
                timed_out=cli('command',expected_exit=1,run_id=command_run_id,task_id='T',
                    agent_run_id=run['agent_run_id'],attempt_id=run['attempt_id'],command_name='build')
                self.assertEqual(timed_out['error_type'],'PreflightTimeout')
                self.assertIn('worker_gate',timed_out['cause'])
                self.assertIn('command-preflight',timed_out['recovery'])
                self.assertFalse((root/'.harness/build.done').exists())
                execution=manager.read()['tasks']['T']['executions'][0]
                diagnostics = [
                    row for path in (root/'.harness/logs/command-preflight').glob('*.jsonl')
                    for row in map(json.loads, path.read_text().splitlines())
                    if row['state'] == 'CLEANUP_DEFERRED'
                    or row['stage'] == 'abort_ownership_cleanup'
                ]
                self.assertTrue(execution.get('command_prelaunch_aborts'), diagnostics)
                flag.unlink()
            command_run_ids = []
            for name in ('build','test'):
                command = 'python3 .kmp-agent/agent.py command --run-id ' + command_run_id + ' --task-id T --agent-run-id ' + run['agent_run_id'] + ' --attempt-id ' + run['attempt_id'] + ' --command-kind ' + name + " --argv-json '" + json.dumps(build_argv if name=='build' else test_argv) + "'"
                self.assertEqual(evaluate(root,dict(hook_event_name='PreToolUse',cwd=str(root),
                    session_id=session,tool_name='exec_command',tool_input={'cmd':command})),{})
                cli('command',run_id=command_run_id,task_id='T',agent_run_id=run['agent_run_id'],
                    attempt_id=run['attempt_id'],command_name=name)
                self.assertEqual(command_hook(command_run_id, f'--command-name={name}'), {})
                denied = command_hook(command_run_id, f'--command-name {name} --command-kind other')
                self.assertIn('conflicts with named configuration', denied['hookSpecificOutput']['permissionDecisionReason'])
                command_run_ids.append(command_run_id)
                if transition and name == 'build':
                    cli('finish',run_id=command_run_id,result='Synthetic command handoff',end_reason='handoff')
                    continuation = task('continue-command-run',dict(task_id='T',agent_run_id=run['agent_run_id'],
                        previous_run_id=command_run_id,reason='Continue synthetic target testing',evidence='input.md'))
                    command_run_id = continuation['command_run_id']
            current = manager.read()
            self.assertEqual(current['required_questions'],original_questions)
            self.assertEqual(native.read_bytes(),original_native)
            self.assertEqual(len(current['tasks']['T']['executions']),1)
            self.assertEqual(current['tasks']['T']['executions'][0]['run_id'],run_id)
            self.assertEqual(current['tasks']['T']['executions'][0]['attempt_id'],run['attempt_id'])
            self.assertTrue((root/'.harness/build.done').is_file())
            self.assertTrue((root/'.harness/test.done').is_file())
            task("submit", {"task_id": "T", "agent_run_id": run["agent_run_id"], "outputs": ["src/App.kt"], "summary": "synthetic"})
            if transition:
                # Mechanical architecture review accepts authenticated continued commands;
                # this does not claim independent requirements/model/product QA.
                from harness.development_constraints import review_gate
                manager_state = manager.read()
                submitted = manager_state['tasks']['T']
                events = manager.logger.read()
                command_ends = [e for e in events if e.get('event_type') == 'command_finished'
                                and e.get('agent_run_id') == run['agent_run_id']
                                and e.get('observed',{}).get('returncode') == 0]
                proofs = []
                for argv, event in zip((build_argv,test_argv), command_ends):
                    observed = event['observed']
                    proofs.append(dict(argv=argv,exit_code=0,**{key:observed[key] for key in
                                  ('call_id','stdout_sha256','stderr_sha256')}))
                evidence = dict(constraints_sha256=submitted['stage_contract']['development_constraints']['sha256'],
                    constraint_review_run_id=run['agent_run_id'],
                    constraint_target_results=[dict(target='jvm',result='PASS',commands=proofs)])
                with patch.object(manager,'read',side_effect=AssertionError('nested task lock')):
                    manager._mutate('continued_command_review_gate',
                        lambda state: review_gate(manager,state['tasks']['T'],evidence,state=state),'T')
                forged_events = copy.deepcopy(events)
                for event in forged_events:
                    if event.get('event_type') in {'command_started','command_finished'}:
                        event['run_id'] = 'unlinked-run'
                with patch.object(manager.logger,'read',return_value=forged_events):
                    with self.assertRaisesRegex(ValueError,'start/finish'):
                        review_gate(manager,submitted,evidence)
            result = cli("collection-report")
            self.assertEqual(result["commands_without_links"], 0)
            completed_commands=[c for c in result['commands'] if c.get('returncode',{}).get('value') == 0]
            self.assertEqual(len(completed_commands),2)
            self.assertEqual(len(result['commands']),3 if preflight_retry else 2)
            self.assertTrue(all(c['returncode']['value']==0 and c['link']['status']=='COLLECTED' for c in completed_commands))
            self.assertEqual([c['run_id'] for c in completed_commands],command_run_ids)
            execution = result["tasks"]["T"]["executions"][0]
            self.assertEqual(execution["files"]["value"][0]["path"], "src/App.kt")
            self.assertEqual(execution["observed_modules"]["value"]["src/App.kt"], ["app"])
            self.assertEqual(execution["modification_actor"], "UNKNOWN")
            self.assertEqual(result["parallelization_verdict"], "NOT_EVALUATED")
            self.assertTrue((root / ".harness/logs/sequential-coverage.json").is_file())
            self.assertEqual(execution["harness"]["value"]["mode"], getattr(self, "expected_installation_mode", "development"))
            refused=cli("finish",expected_exit=1,run_id=run_id,result="synthetic command observed, no QA claim")
            self.assertIn("not officially DONE",refused["cause"])
            bootstrap.install(root, development=ROOT, update=True)
            self.assertEqual((root / seq.SETTINGS).read_bytes(), settings_before)


if __name__ == "__main__":
    unittest.main()
