from pathlib import Path
import tempfile
import unittest
from harness.dashboard_fixture import write_fixture
from harness.dashboard import snapshot

class ProjectProgressTests(unittest.TestCase):
 def test_project_summary_separates_work_and_does_not_claim_project_completion(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);write_fixture(root);s=snapshot(root,'normal');p=s['project_progress'];self.assertEqual(p['completion'],'NOT_ESTABLISHED');self.assertGreaterEqual(len(p['groups']),1)
   for group in p['groups']:
    self.assertEqual(group['completion'],'NOT_ESTABLISHED')
    for phase in group['phases']:self.assertEqual(phase['completion'],'PROJECT_STAGE_COMPLETION_NOT_ESTABLISHED')
 def test_project_scope_and_current_execution_are_distinct(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);write_fixture(root);s=snapshot(root,'normal');self.assertIn('프로젝트 전체',s['project_progress']['scope']);self.assertIn('현재 실행 작업:',s['human_progress']['agent_message']);self.assertIn('위치:',s['human_progress']['agent_message'])

if __name__=='__main__':unittest.main()
