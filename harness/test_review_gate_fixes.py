"""Stage routing and human request summaries use current native evidence."""
import unittest
from harness import test_stage_readiness as fixture
from harness.dashboard_workspace import workspace,request_status
from harness.stage_readiness import assess,STAGES
from harness.findings import blocking


class ReviewGateFixes(unittest.TestCase):
    def setUp(self):
        self.case=fixture.StageReadinessTest();self.case.setUp();self.addCleanup(self.case.doCleanups)
        self.root=self.case.root.resolve();self.manager=self.case.t

    def approve_all(self):
        for stage in STAGES:self.case.approve(stage)

    def issue(self,kind,severity,blocking_flag):
        def add(s):s.setdefault('issues',[]).append({'id':'ISSUE-fixture','feature_id':'F','task_id':'planning','owner':'planning','severity':severity,'status':'OPEN','observed':'synthetic issue','qa_finding':{'kind':kind,'blocking':blocking_flag}})
        self.manager._mutate('fixture_qa_issue',add,'planning')

    def test_optional_qa_improvement_does_not_revoke_approved_stages(self):
        self.approve_all()
        for severity in ['MINOR','MAJOR']:
            self.issue('improvement',severity,False)
            state=self.manager.read()
            self.assertEqual(blocking(state,state['tasks']['planning']),[])
            self.assertEqual(assess(self.root,state,'F')['status'],'PASS')

    def test_explicit_nonblocking_finding_uses_same_policy(self):
        self.approve_all();self.issue('usability','MAJOR',False)
        self.assertEqual(assess(self.root,self.manager.read(),'F')['status'],'PASS')

    def test_actual_blocker_still_returns_owner_and_blocks_downstream(self):
        self.approve_all();self.issue('baseline_gap','MAJOR',True)
        state=self.manager.read();self.assertEqual(len(blocking(state,state['tasks']['planning'])),1)
        stages=assess(self.root,state,'F')['stages']
        self.assertEqual(stages[0]['status'],'REWORK_REQUIRED')
        self.assertTrue(all(s['status']=='WAITING_UPSTREAM' for s in stages[1:]))

    def link_request(self):
        logger=self.manager.logger;run=self.manager.read()['tasks']['planning']['executions'][0]
        logger.append('session_message',self.manager.run_id,'PRODUCT',source={'session_id':'fixture-human'},observed={'role':'user','message_id':'fixture-message','content':[{'type':'input_text','text':'fixture request'}]})
        event_id=logger.read()[-1]['event_id']
        logger.append('human_intervention',self.manager.run_id,'PRODUCT',task_id='planning',feature_id='F',agent_run_id=run['agent_run_id'],summary={'source_event_id':event_id,'source_session_id':'fixture-human','source_message_id':'fixture-message','classification':'STATUS_OR_EXPLANATION','basis':'explicit synthetic association','role':'planning','stage':'work'})

    def test_request_completion_tracks_changed_output_not_raw_done(self):
        self.case.approve('planning');self.link_request()
        first=workspace(self.root);self.assertEqual(first['requests'][0]['status'],'연결된 작업 검증 완료')
        (self.root/'planning.md').write_text('changed after review')
        changed=workspace(self.root)
        self.assertEqual(changed['requests'][0]['status'],'재검증 필요')
        self.assertEqual(next(t for t in changed['tasks'] if t['task_id']=='planning')['state'],'DONE')

    def test_request_cannot_claim_verified_completion_with_missing_evidence(self):
        self.case.approve('planning');self.link_request()
        task=self.manager.read()['tasks']['planning'];proof=task['reviews'][0]['results'][0]['evidence']
        (self.root/proof['snapshot']).unlink()
        data=workspace(self.root)
        self.assertEqual(data['requests'][0]['status'],'재검증 필요')
        self.assertEqual(next(t for t in data['tasks'] if t['task_id']=='planning')['state'],'DONE')
        current=self.manager.read()['tasks']['planning']
        self.assertEqual(current['reviews'][0]['results'][0]['result'],'PASS')
        self.assertEqual(current['validation_status'][current['reviews'][0]['agent_run_id']]['state'],'RECHECK_REQUIRED')

    def test_conflicts_unknown_links_and_active_recheck_are_explicit(self):
        tasks={'T':{'state':'DONE'}}
        for verdict,status in [('CONFLICT','기록·검증 불일치'),('NOT_RUN','완료 보고 · 검증 미확인'),('RECHECK_REQUIRED','재검증 필요')]:
            self.assertEqual(request_status(['T'],tasks,{'T':{'verdict':verdict}},False),status)
        self.assertEqual(request_status(['T'],tasks,{'T':{'verdict':'RECHECK_REQUIRED'}},True),'진행 중 · 재검증 필요')
        self.assertEqual(request_status(['missing'],tasks,{},False),'연결 작업 상태 미확인')


if __name__=='__main__':unittest.main()
